"""
AgentDeploy CLI — agentdeploy <command>

Commands:
  init      Scaffold a new agentdeploy project
  validate  Check an AgentApp config without building
  build     Run build() from a config file
  version   Print the SDK version
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="agentdeploy",
    help="Zero-boilerplate deployment for AI agent frameworks.",
    add_completion=False,
)
console = Console()


@app.command()
def version():
    """Print the installed AgentDeploy version."""
    from agentdeploy import __version__
    console.print(f"[bold]AgentDeploy[/bold] v{__version__}")


@app.command()
def init(
    name: str = typer.Argument(..., help="Agent name (used as directory and K8s name)"),
    framework: str = typer.Option(
        "langgraph",
        "--framework", "-f",
        help="Agent framework: langgraph | crewai | openai | callable",
    ),
    target: str = typer.Option(
        "kubernetes",
        "--target", "-t",
        help="Deploy target: kubernetes | docker-compose | lambda | cloud-run",
    ),
):
    """Scaffold a new AgentDeploy project with example files."""
    proj_dir = Path(name)
    if proj_dir.exists():
        console.print(f"[red]Directory '{name}' already exists.[/red]")
        raise typer.Exit(1)

    proj_dir.mkdir()
    (proj_dir / "agent.py").write_text(_agent_stub(framework))
    (proj_dir / "agentdeploy_config.py").write_text(_config_stub(name, framework, target))
    (proj_dir / "requirements.txt").write_text(_requirements(framework))
    (proj_dir / ".gitignore").write_text("deploy/\n__pycache__/\n.env\n*.pyc\n")
    (proj_dir / ".env.example").write_text("OPENAI_API_KEY=\nANTHROPIC_API_KEY=\n")

    console.print(Panel(
        f"[bold green]Project '{name}' created.[/bold green]\n\n"
        f"  [dim]cd {name}[/dim]\n"
        f"  [dim]# Edit agent.py with your {framework} agent[/dim]\n"
        f"  [dim]# Edit agentdeploy_config.py to configure deployment[/dim]\n"
        f"  [dim]agentdeploy build[/dim]",
        title="agentdeploy init",
    ))


@app.command()
def validate(
    config: str = typer.Option(
        "agentdeploy_config.py",
        "--config", "-c",
        help="Path to the agentdeploy config file",
    ),
):
    """Validate an AgentApp configuration without generating files."""
    cfg_path = Path(config)
    if not cfg_path.exists():
        console.print(f"[red]Config file not found: {config}[/red]")
        raise typer.Exit(1)

    try:
        agent_app = _load_app_from_config(cfg_path)
    except Exception as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1) from e

    table = Table(title="AgentApp validation", show_header=False)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Name",      agent_app.name)
    table.add_row("Version",   agent_app.version)
    table.add_row("Framework", agent_app._adapter.framework_name if agent_app._adapter else "not wrapped")
    table.add_row("Memory",    f"{agent_app._memory_mb} MB")
    table.add_row("Timeout",   f"{agent_app._timeout_seconds}s")
    table.add_row("Port",      str(agent_app._port))
    table.add_row("Secrets",   ", ".join(agent_app._secrets) or "none")
    console.print(table)
    console.print("[green]Validation passed.[/green]")


@app.command()
def build(
    config: str = typer.Option(
        "agentdeploy_config.py",
        "--config", "-c",
        help="Path to the agentdeploy config file",
    ),
    output: str = typer.Option(
        "./deploy",
        "--output", "-o",
        help="Output directory for generated artifacts",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and show what would be generated without writing files",
    ),
):
    """Generate deployment artifacts from an agentdeploy config."""
    cfg_path = Path(config)
    if not cfg_path.exists():
        console.print(f"[red]Config file not found: {config}[/red]")
        raise typer.Exit(1)

    with console.status("[bold]Loading config...[/bold]"):
        try:
            agent_app = _load_app_from_config(cfg_path)
        except Exception as e:
            console.print(f"[red]Config load error:[/red] {e}")
            raise typer.Exit(1) from e

    console.print(f"[bold]Building[/bold] {agent_app}")

    if dry_run:
        console.print("[yellow]Dry run — no files written.[/yellow]")
        return

    try:
        from agentdeploy.core.deploy import deploy as _deploy
        result = (
            _deploy(agent_app)
            .to_kubernetes()
            .with_output_dir(output)
            .build()
        )
    except Exception as e:
        console.print(f"[red]Build failed:[/red] {e}")
        raise typer.Exit(1) from e

    console.print(Panel(
        "\n".join(f"  [dim]{f}[/dim]" for f in result.files),
        title=f"[green]Build complete[/green] — {result.output_dir}",
    ))
    console.print("\n[bold]Next steps:[/bold]")
    for step in result.next_steps:
        console.print(f"  {step}")


def _load_app_from_config(cfg_path: Path):
    """
    Import the config module and return the AgentApp it exports.
    Expects the config file to expose `app = AgentApp(...).wrap(...)`.
    """
    spec = importlib.util.spec_from_file_location("agentdeploy_config", cfg_path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(cfg_path.parent))
    spec.loader.exec_module(module)
    sys.path.pop(0)
    if not hasattr(module, "app"):
        raise AttributeError(
            f"Config file '{cfg_path}' must define a top-level `app = AgentApp(...)` variable."
        )
    return module.app


def _agent_stub(framework: str) -> str:
    stubs = {
        "langgraph": """from langgraph.graph import StateGraph, END
from typing import TypedDict

class State(TypedDict):
    input: str
    output: str

def process(state: State) -> State:
    # TODO: add your logic here
    return {"output": f"processed: {state['input']}"}

builder = StateGraph(State)
builder.add_node("process", process)
builder.set_entry_point("process")
builder.add_edge("process", END)
graph = builder.compile()
""",
        "crewai": """from crewai import Agent, Task, Crew

researcher = Agent(
    role="Researcher",
    goal="Find relevant information",
    backstory="Expert researcher with broad knowledge",
)

task = Task(
    description="Research the topic: {topic}",
    expected_output="A concise summary",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[task])
""",
        "callable": """async def agent(input: dict) -> dict:
    # TODO: implement your agent logic here
    return {"result": f"processed: {input}"}
""",
    }
    return stubs.get(framework, stubs["callable"])


def _config_stub(name: str, framework: str, target: str) -> str:
    agent_obj = {"langgraph": "graph", "crewai": "crew", "callable": "agent"}.get(framework, "agent")
    return f"""from agentdeploy import AgentApp, deploy
from agent import {agent_obj}

app = (
    AgentApp("{name}", description="My {framework} agent")
    .wrap({agent_obj})
    .env("ANTHROPIC_API_KEY", from_secret="anthropic-key")
    .resources(memory_mb=1024, timeout_seconds=120)
)

# Uncomment to run deployment programmatically:
# result = deploy(app).to_{target.replace("-", "_")}().build()
# print(result)
"""


def _requirements(framework: str) -> str:
    base = "agentdeploy\nfastapi\nuvicorn\n"
    extras = {
        "langgraph": "langgraph>=0.2\nlangchain-core>=0.2\n",
        "crewai": "crewai>=0.70\n",
        "openai": "openai>=1.50\n",
        "callable": "",
    }
    return base + extras.get(framework, "")


if __name__ == "__main__":
    app()
