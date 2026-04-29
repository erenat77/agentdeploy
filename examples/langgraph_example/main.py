"""
LangGraph example — from graph to Kubernetes in ~30 lines.

This is what a developer writes. AgentDeploy handles everything else.
"""

from agentdeploy import AgentApp, deploy, HITLGate, HITLDecision, Telemetry

# --- 1. Your existing LangGraph agent (unchanged) ---
# from langgraph.graph import StateGraph
# from langchain_anthropic import ChatAnthropic
#
# graph = StateGraph(...)
# ... define nodes and edges ...
# compiled_graph = graph.compile()

# For this example we mock the compiled graph:
class _MockCompiledGraph:
    """Simulates a LangGraph CompiledStateGraph."""
    __name__ = "CompiledStateGraph"
    async def ainvoke(self, input, config=None):
        return {"result": f"processed: {input}"}

compiled_graph = _MockCompiledGraph()
type(compiled_graph).__name__ = "CompiledStateGraph"
type(compiled_graph).__module__ = "langgraph.graph.state"


# --- 2. Wrap and configure ---
app = (
    AgentApp("summarisation-agent", description="Summarises documents using LangGraph")
    .wrap(compiled_graph)
    .env("ANTHROPIC_API_KEY", from_secret="anthropic-key")
    .env("LOG_LEVEL", "INFO")
    .resources(memory_mb=2048, timeout_seconds=120)
)

print(f"Wrapped: {app}")


# --- 3. Deploy to Kubernetes with autoscaling + HITL ---
result = (
    deploy(app)
    .to_kubernetes(
        namespace="agents",
        image="summarisation-agent:0.1.0",
        registry="registry.mycompany.com",
    )
    .with_replicas(2)
    .with_autoscale(min=1, max=8, cpu_percent=60)
    .with_hitl_gate(
        webhook="https://myapp.com/api/hitl/approve",
        timeout_seconds=1800,
    )
    .with_telemetry(endpoint="http://otel-collector:4317")
    .with_output_dir("/tmp/agentdeploy_example")
    .build()
)

print(result)


# --- 4. For local dev, use Docker Compose instead ---
local_result = (
    deploy(app)
    .to_docker_compose(output_dir="/tmp/agentdeploy_example/local")
    .with_redis()
    .with_otel_collector()
    .build()
)

print(f"\nDocker Compose written to: {local_result.compose_path}")
print("Run with: docker compose up --build")


# --- 5. Use HITL inside your agent logic ---
gate = HITLGate(console_fallback=True)  # swap for webhook= in prod

async def safe_agent_run(user_input: str):
    telemetry = Telemetry("summarisation-agent")

    async with telemetry.trace("invoke", input=user_input) as span:
        result = await compiled_graph.ainvoke({"input": user_input})

        # Gate before any destructive / irreversible action
        approval = await gate.checkpoint(
            state=result,
            description="Agent about to write output to database",
        )

        if approval.decision == HITLDecision.REJECT:
            return {"status": "rejected", "reason": approval.reason}

        final_state = approval.modified_state or result
        span.set_tokens(prompt=320, completion=80, model="claude-sonnet-4-6")
        span.set_attribute("hitl.decision", approval.decision)

        return final_state


if __name__ == "__main__":
    import asyncio
    output = asyncio.run(safe_agent_run("Summarise the Q3 earnings report"))
    print(f"\nFinal output: {output}")
