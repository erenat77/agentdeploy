"""
AgentDeploy — zero-boilerplate deployment for AI agent frameworks.

Wrap any LangGraph, CrewAI, OpenAI Agents SDK, or custom agent and
generate production-ready Kubernetes manifests, Docker Compose files,
Lambda handlers, or Cloud Run services.

Public API:
    AgentApp         — wrap and configure an agent
    deploy           — start a deployment pipeline for an AgentApp
    HITLGate         — human-in-the-loop checkpoint primitive
    HITLDecision     — APPROVE / REJECT / MODIFY enum
    CheckpointResult — result returned by a HITL checkpoint
    Telemetry        — OpenTelemetry-backed agent tracing with cost tracking
"""

from agentdeploy.core.app import AgentApp
from agentdeploy.core.deploy import deploy
from agentdeploy.core.hitl import CheckpointResult, HITLDecision, HITLGate
from agentdeploy.core.observability import Telemetry

__version__ = "0.1.0"

__all__ = [
    "AgentApp",
    "deploy",
    "HITLGate",
    "HITLDecision",
    "CheckpointResult",
    "Telemetry",
    "__version__",
]
