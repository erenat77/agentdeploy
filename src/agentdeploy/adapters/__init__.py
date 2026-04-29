"""Framework adapters and the auto-detection registry."""

from agentdeploy.adapters.base import AgentAdapter
from agentdeploy.adapters.registry import AdapterRegistry

__all__ = ["AgentAdapter", "AdapterRegistry"]
