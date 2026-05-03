"""
Concrete framework adapters and AdapterRegistry.

The registry inspects the wrapped object's type and module to
automatically select the right adapter without the user having
to specify the framework.
"""

from __future__ import annotations

from typing import Any

from agentdeploy.adapters.base import AgentAdapter


class _LangGraphAdapter(AgentAdapter):
    framework_name = "langgraph"

    def validate(self) -> None:
        cls_name = type(self.agent).__name__
        if "CompiledGraph" not in cls_name and "CompiledStateGraph" not in cls_name:
            raise ValueError(
                f"Expected a LangGraph CompiledGraph, got {cls_name}. "
                "Did you forget to call graph.compile()?"
            )

    def pip_extras(self) -> list[str]:
        return ["langgraph>=0.2", "langchain-core>=0.2"]

    def entrypoint_code(self, app_name: str, port: int) -> str:
        return f"""
import json, os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from agent import graph  # imported from user's agent module

server = FastAPI(title="{app_name}")

@server.get("/health")
async def health():
    return {{"status": "ok", "framework": "langgraph"}}

@server.post("/invoke")
async def invoke(request: Request):
    body = await request.json()
    result = await graph.ainvoke(body.get("input", {{}}), config=body.get("config", {{}}))
    return JSONResponse(result)

if __name__ == "__main__":
    uvicorn.run(server, host="0.0.0.0", port={port})
"""


class _CrewAIAdapter(AgentAdapter):
    framework_name = "crewai"

    def validate(self) -> None:
        cls_name = type(self.agent).__name__
        module = type(self.agent).__module__
        if "crewai" not in module and cls_name != "Crew":
            raise ValueError(f"Expected a CrewAI Crew object, got {cls_name} from {module}.")

    def pip_extras(self) -> list[str]:
        return ["crewai>=0.70"]

    def entrypoint_code(self, app_name: str, port: int) -> str:
        return f"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from agent import crew  # imported from user's agent module

server = FastAPI(title="{app_name}")

@server.get("/health")
async def health():
    return {{"status": "ok", "framework": "crewai"}}

@server.post("/invoke")
async def invoke(request: Request):
    body = await request.json()
    result = crew.kickoff(inputs=body.get("inputs", {{}}))
    return JSONResponse({{"result": str(result)}})

if __name__ == "__main__":
    uvicorn.run(server, host="0.0.0.0", port={port})
"""


class _OpenAIAgentAdapter(AgentAdapter):
    framework_name = "openai-agents"

    # Modules that legitimately host the OpenAI Agents SDK Agent class.
    _MODULE_PREFIXES = ("agents.", "openai.agents", "openai_agents")

    def validate(self) -> None:
        module = type(self.agent).__module__
        cls_name = type(self.agent).__name__
        # Be strict: match real module roots, not any module containing
        # the substring "agents" (which would otherwise catch
        # langchain.agents, llama_index.agent, etc.).
        if not (module == "agents" or module.startswith(self._MODULE_PREFIXES)):
            raise ValueError(
                f"Expected an OpenAI Agents SDK Agent, got {cls_name} from "
                f"module {module!r}. Install with `pip install openai-agents` "
                "and pass the Agent instance to .wrap()."
            )
        if cls_name != "Agent":
            raise ValueError(f"Expected an OpenAI Agents SDK Agent class, got {cls_name}.")

    def pip_extras(self) -> list[str]:
        return ["openai>=1.50", "openai-agents>=0.1"]

    def entrypoint_code(self, app_name: str, port: int) -> str:
        return f"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from agents import Runner
import uvicorn
from agent import agent  # imported from user's agent module

server = FastAPI(title="{app_name}")

@server.get("/health")
async def health():
    return {{"status": "ok", "framework": "openai-agents"}}

@server.post("/invoke")
async def invoke(request: Request):
    body = await request.json()
    result = await Runner.run(agent, input=body.get("input", ""))
    return JSONResponse({{"result": result.final_output}})

if __name__ == "__main__":
    uvicorn.run(server, host="0.0.0.0", port={port})
"""


class _CallableAdapter(AgentAdapter):
    """Fallback: any async callable is treated as a BYOF agent."""

    framework_name = "callable"

    def validate(self) -> None:
        if not callable(self.agent):
            raise ValueError(f"Expected a callable agent, got {type(self.agent).__name__}.")

    def pip_extras(self) -> list[str]:
        return []

    def entrypoint_code(self, app_name: str, port: int) -> str:
        return f"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from agent import agent  # your callable

server = FastAPI(title="{app_name}")

@server.get("/health")
async def health():
    return {{"status": "ok", "framework": "callable"}}

@server.post("/invoke")
async def invoke(request: Request):
    body = await request.json()
    result = await agent(body.get("input", {{}}))
    return JSONResponse({{"result": result}})

if __name__ == "__main__":
    uvicorn.run(server, host="0.0.0.0", port={port})
"""


class AdapterRegistry:
    """
    Auto-detect the right adapter by inspecting the agent object's
    type name and module path. Ordered from most-specific to most-general.
    """

    _registry: list[tuple[str, type[AgentAdapter]]] = [
        ("langgraph", _LangGraphAdapter),
        ("crewai", _CrewAIAdapter),
        ("openai", _OpenAIAgentAdapter),
        ("callable", _CallableAdapter),
    ]

    @classmethod
    def detect(cls, agent: Any) -> AgentAdapter:
        module = type(agent).__module__
        cls_name = type(agent).__name__

        # LangGraph (most specific)
        if "langgraph" in module or "CompiledGraph" in cls_name or "CompiledStateGraph" in cls_name:
            return _LangGraphAdapter(agent)
        # CrewAI
        if "crewai" in module or cls_name == "Crew":
            return _CrewAIAdapter(agent)
        # OpenAI Agents SDK — strict module-root match to avoid catching
        # langchain.agents / llama_index.agent / etc.
        if (
            module == "agents" or module.startswith(_OpenAIAgentAdapter._MODULE_PREFIXES)
        ) and cls_name == "Agent":
            return _OpenAIAgentAdapter(agent)
        # Fallback: any callable
        if callable(agent):
            return _CallableAdapter(agent)

        raise ValueError(
            f"Could not detect framework for {cls_name} from {module}. "
            "Wrap it manually: app.wrap(agent, adapter=MyAdapter(agent))"
        )

    @classmethod
    def register(cls, key: str, adapter_class: type[AgentAdapter]) -> None:
        """Register a custom adapter for a new framework."""
        cls._registry.insert(0, (key, adapter_class))
