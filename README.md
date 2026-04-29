# AgentDeploy

[![CI](https://github.com/erenat77/agentdeploy/actions/workflows/ci.yml/badge.svg)](https://github.com/erenat77/agentdeploy/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentdeploy.svg)](https://pypi.org/project/agentdeploy/)
[![Python](https://img.shields.io/pypi/pyversions/agentdeploy.svg)](https://pypi.org/project/agentdeploy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Zero-boilerplate deployment for AI agent frameworks.**

Take any LangGraph, CrewAI, OpenAI Agents SDK, or custom agent and generate production-ready Kubernetes manifests, Docker Compose files, Lambda handlers, or Cloud Run services — in under 10 lines of Python.

---

## The problem it solves

Every team building AI agents in 2025–2026 faces the same 3–6 week detour:

- Write the agent (30 min)
- Figure out how to containerise it (1 day)
- Write Kubernetes manifests with correct resource limits, health checks, and HPA (2 days)
- Add human-in-the-loop gates (1 week)
- Wire up OpenTelemetry tracing and cost tracking (3 days)
- Repeat for every new agent

AgentDeploy collapses this to a single fluent call.

---

## Install

```bash
# pip
pip install agentdeploy

# uv (recommended)
uv add agentdeploy

# With framework extras:
uv add "agentdeploy[langgraph]"
uv add "agentdeploy[crewai]"
uv add "agentdeploy[openai]"
uv add "agentdeploy[all]"
```

---

## Quick start

```python
from agentdeploy import AgentApp, deploy

# 1. Wrap your existing agent (framework auto-detected)
app = (
    AgentApp("my-agent", description="Summarisation agent")
    .wrap(my_langgraph_graph)               # or CrewAI Crew, OpenAI Agent, callable
    .env("ANTHROPIC_API_KEY", from_secret="anthropic-key")
    .resources(memory_mb=2048, timeout_seconds=120)
)

# 2. Generate Kubernetes manifests + Dockerfile
result = (
    deploy(app)
    .to_kubernetes(namespace="agents", image="my-agent:0.1.0")
    .with_replicas(2)
    .with_autoscale(min=1, max=10, cpu_percent=60)
    .with_hitl_gate(webhook="https://yourapp.com/api/approve")
    .with_telemetry(endpoint="http://otel-collector:4317")
    .build()
)

print(result)
# → Dockerfile, deployment.yaml, service.yaml, hpa.yaml, secret.yaml
# → kubectl apply -k ./deploy/my-agent/k8s/
```

---

## Supported frameworks

| Framework | Detection | Adapter |
|---|---|---|
| LangGraph | `CompiledStateGraph` type | `_LangGraphAdapter` |
| CrewAI | `crewai` module, `Crew` type | `_CrewAIAdapter` |
| OpenAI Agents SDK | `openai.agents` module | `_OpenAIAgentAdapter` |
| Any `async callable` | fallback | `_CallableAdapter` |

Custom framework? Register your own adapter:

```python
from agentdeploy.adapters import AdapterRegistry, AgentAdapter

class MyAdapter(AgentAdapter):
    framework_name = "my-framework"
    def validate(self): ...
    def pip_extras(self): return ["my-framework>=1.0"]
    def entrypoint_code(self, app_name, port): return "..."

AdapterRegistry.register("my-framework", MyAdapter)
```

---

## Deploy targets

### Kubernetes
```python
deploy(app).to_kubernetes(namespace="prod", image="myimg:1.0")
    .with_replicas(3)
    .with_autoscale(min=1, max=20, cpu_percent=70)
    .with_hitl_gate(webhook="https://yourapp.com/approve")
    .with_telemetry(endpoint="http://otel-collector:4317")
    .build()
```
Generates: `Dockerfile`, `deployment.yaml`, `service.yaml`, `hpa.yaml`, `secret.yaml`, `kustomization.yaml`

### Docker Compose (local / staging)
```python
deploy(app).to_docker_compose()
    .with_redis()
    .with_otel_collector()
    .build()
# → docker compose up --build
```

### AWS Lambda
```python
deploy(app).to_lambda(region="us-east-1", function_name="my-agent")
    .build()
# → sam build && sam deploy
```

### Google Cloud Run
```python
deploy(app).to_cloud_run(project="my-gcp-project", region="us-central1")
    .with_scaling(min_instances=0, max_instances=20)
    .build()
# → gcloud builds submit && gcloud run services replace ...
```

---

## Human-in-the-Loop (HITL)

Add human oversight at any decision point:

```python
from agentdeploy import HITLGate, HITLDecision

gate = HITLGate(webhook="https://yourapp.com/api/approve")

async def run_agent(user_input):
    state = await my_agent.ainvoke(user_input)

    approval = await gate.checkpoint(
        state=state,
        description="Agent about to write to production database",
    )

    if approval.decision == HITLDecision.REJECT:
        return {"status": "cancelled", "reason": approval.reason}

    return approval.modified_state or state
```

Your webhook endpoint resolves the checkpoint:
```python
from agentdeploy import HITLGate, HITLDecision, CheckpointResult

@app.post("/api/approve/{checkpoint_id}")
async def approve(checkpoint_id: str):
    await gate.resolve(checkpoint_id, CheckpointResult(
        decision=HITLDecision.APPROVE,
        reviewer="alice@company.com",
    ))
```

Delivery channels: `webhook=`, `slack_webhook=`, `console_fallback=True` (local dev)

---

## Telemetry

```python
from agentdeploy import Telemetry

telemetry = Telemetry("my-agent", otel_endpoint="http://otel-collector:4317")

async with telemetry.trace("invoke", input=user_input) as span:
    result = await my_agent.ainvoke(user_input)
    span.set_tokens(prompt=512, completion=128, model="claude-sonnet-4-6")
    # → auto-calculates cost, writes span to OTel collector
```

Built-in cost estimation for: `gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4-6`, `claude-opus-4-6`, `gemini-1.5-pro`

---

## CLI

```bash
# Scaffold a new project
agentdeploy init my-agent --framework langgraph --target kubernetes

# Validate config without building
agentdeploy validate

# Build artifacts
agentdeploy build --output ./deploy

# Dry run
agentdeploy build --dry-run
```

---

## Project layout (generated)

```
deploy/
└── my-agent/
    ├── Dockerfile
    ├── server.py          # auto-generated FastAPI entrypoint
    └── k8s/
        ├── deployment.yaml
        ├── service.yaml
        ├── hpa.yaml
        ├── secret.yaml    # placeholder — fill in before applying
        └── kustomization.yaml
```

Apply to cluster:
```bash
kubectl apply -k ./deploy/my-agent/k8s/
kubectl rollout status deployment/my-agent -n agents
```

---

## Roadmap

- [ ] v0.2 — Helm chart output target
- [ ] v0.2 — Multi-agent topology (one app, N agent pods with message bus wiring)
- [ ] v0.3 — Budget enforcement middleware (per-run token caps)
- [ ] v0.3 — Replay debugger (capture + replay full execution traces)
- [ ] v0.4 — Pulumi / Terraform IaC output
- [ ] v0.5 — GitHub Actions / GitLab CI pipeline generation

---

## Contributing

```bash
git clone https://github.com/erenat77/agentdeploy
cd agentdeploy
uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
pre-commit install
pytest tests/ -v
```

PRs welcome. Please add tests for new adapters and targets.

---

## License

MIT
