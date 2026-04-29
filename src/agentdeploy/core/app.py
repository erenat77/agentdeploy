"""
AgentApp — wraps any agent framework into a deployable unit.

Supports LangGraph, CrewAI, OpenAI Agents SDK, Claude SDK,
and any custom callable agent (BYOF — Bring Your Own Framework).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from agentdeploy.adapters.base import AgentAdapter
from agentdeploy.adapters.registry import AdapterRegistry


class AgentConfig(BaseModel):
    name: str
    description: str = ""
    version: str = "0.1.0"
    env_vars: dict[str, str] = {}
    secrets: list[str] = []
    memory_mb: int = 1024
    timeout_seconds: int = 300


@dataclass
class AgentApp:
    """
    Entry point for AgentDeploy. Wrap your agent, configure it,
    then call deploy() to generate deployment artifacts.

    Usage:
        app = AgentApp("my-agent", description="Summarisation crew")
        app.wrap(my_langgraph_graph)
        app.env("OPENAI_API_KEY", from_secret="openai-secret")
    """

    name: str
    description: str = ""
    version: str = "0.1.0"
    _agent: Any = field(default=None, init=False, repr=False)
    _adapter: AgentAdapter | None = field(default=None, init=False, repr=False)
    _env: dict[str, str] = field(default_factory=dict, init=False)
    _secrets: list[str] = field(default_factory=list, init=False)
    _memory_mb: int = field(default=1024, init=False)
    _timeout_seconds: int = field(default=300, init=False)
    _health_path: str = field(default="/health", init=False)
    _port: int = field(default=8080, init=False)

    def wrap(self, agent: Any) -> "AgentApp":
        """
        Detect the framework of `agent` automatically and wrap it.

        Supported: LangGraph CompiledGraph, CrewAI Crew,
                   OpenAI Agent, Anthropic Claude SDK agent,
                   or any async callable (BYOF).
        """
        self._agent = agent
        self._adapter = AdapterRegistry.detect(agent)
        return self

    def env(self, key: str, value: str = "", *, from_secret: str = "") -> "AgentApp":
        """Set an environment variable. Use from_secret for sensitive values."""
        if from_secret:
            self._secrets.append(from_secret)
            self._env[key] = f"secret:{from_secret}"
        else:
            self._env[key] = value
        return self

    def resources(self, *, memory_mb: int = 1024, timeout_seconds: int = 300) -> "AgentApp":
        """Set resource limits for the container."""
        self._memory_mb = memory_mb
        self._timeout_seconds = timeout_seconds
        return self

    def port(self, port: int) -> "AgentApp":
        """Override the default HTTP port (default: 8080)."""
        self._port = port
        return self

    def health_path(self, path: str) -> "AgentApp":
        """Override the default health check path (default: /health)."""
        self._health_path = path
        return self

    def to_config(self) -> AgentConfig:
        plain_env = {k: v for k, v in self._env.items() if not v.startswith("secret:")}
        return AgentConfig(
            name=self.name,
            description=self.description,
            version=self.version,
            env_vars=plain_env,
            secrets=self._secrets,
            memory_mb=self._memory_mb,
            timeout_seconds=self._timeout_seconds,
        )

    def __repr__(self) -> str:
        framework = self._adapter.framework_name if self._adapter else "unwrapped"
        return f"AgentApp(name={self.name!r}, framework={framework!r}, port={self._port})"
