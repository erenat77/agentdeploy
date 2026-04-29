"""
AgentAdapter — abstract base class for framework adapters.

Each adapter knows how to:
  - validate the wrapped agent object
  - generate the entrypoint server code
  - declare framework-specific dependencies
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentAdapter(ABC):
    """Base class for all framework adapters."""

    framework_name: str = "unknown"

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self.validate()

    @abstractmethod
    def validate(self) -> None:
        """Raise ValueError if the wrapped object is not the expected type."""

    @abstractmethod
    def entrypoint_code(self, app_name: str, port: int) -> str:
        """
        Return a string of Python code that starts an HTTP server
        exposing POST /invoke and GET /health for this agent.
        This code is written into the container image as server.py.
        """

    @abstractmethod
    def pip_extras(self) -> list[str]:
        """
        Return the pip package names required by this framework
        (e.g. ['langgraph>=0.2', 'langchain-core']).
        These are injected into the generated Dockerfile.
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(framework={self.framework_name!r})"
