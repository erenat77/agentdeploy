"""
Telemetry — wraps OpenTelemetry tracing for agent runs.

Automatically instruments:
  - Per-run spans with agent name, framework, input/output tokens
  - Cost estimation per provider
  - Failure traces with exception capture

Usage:
    telemetry = Telemetry(service_name="my-agent")

    async with telemetry.trace("invoke", input=user_input) as span:
        result = await my_agent.invoke(user_input)
        span.set_tokens(prompt=512, completion=128, model="gpt-4o")
    # Span is ended automatically, cost is calculated and logged
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gpt-4o":            {"prompt": 0.005,   "completion": 0.015},
    "gpt-4o-mini":       {"prompt": 0.00015, "completion": 0.0006},
    "claude-sonnet-4-6": {"prompt": 0.003,   "completion": 0.015},
    "claude-opus-4-6":   {"prompt": 0.015,   "completion": 0.075},
    "gemini-1.5-pro":    {"prompt": 0.0035,  "completion": 0.0105},
}


@dataclass
class OtelConfig:
    endpoint: str = "http://localhost:4317"
    service_name: str = "agentdeploy"


class AgentSpan:
    """Thin wrapper around an OTel span with agent-specific helpers."""

    def __init__(self, span: Any, start_time: float) -> None:
        self._span = span
        self._start_time = start_time
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._model = ""

    def set_tokens(
        self,
        *,
        prompt: int = 0,
        completion: int = 0,
        model: str = "",
    ) -> None:
        self._prompt_tokens = prompt
        self._completion_tokens = completion
        self._model = model
        if self._span and OTEL_AVAILABLE:
            self._span.set_attribute("llm.prompt_tokens", prompt)
            self._span.set_attribute("llm.completion_tokens", completion)
            self._span.set_attribute("llm.model", model)
            cost = self._estimate_cost(prompt, completion, model)
            if cost is not None:
                self._span.set_attribute("llm.cost_usd", round(cost, 6))

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span and OTEL_AVAILABLE:
            self._span.set_attribute(key, value)

    def record_exception(self, exc: Exception) -> None:
        if self._span and OTEL_AVAILABLE:
            self._span.record_exception(exc)

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start_time) * 1000

    def _estimate_cost(self, prompt: int, completion: int, model: str) -> float | None:
        rates = COST_PER_1K_TOKENS.get(model)
        if not rates:
            return None
        return (prompt / 1000 * rates["prompt"]) + (completion / 1000 * rates["completion"])


class Telemetry:
    """
    Agent telemetry wrapper. Initialise once per service, then
    use as an async context manager around agent invocations.
    """

    def __init__(
        self,
        service_name: str,
        *,
        otel_endpoint: str = "",
        enabled: bool = True,
    ) -> None:
        self.service_name = service_name
        self.enabled = enabled and OTEL_AVAILABLE
        self._tracer = None

        if self.enabled and otel_endpoint:
            provider = TracerProvider()
            exporter = OTLPSpanExporter(endpoint=otel_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer(service_name)

    @asynccontextmanager
    async def trace(
        self,
        operation: str,
        *,
        input: Any = None,
        agent_name: str = "",
        framework: str = "",
    ) -> AsyncGenerator[AgentSpan, None]:
        """
        Async context manager that wraps an agent operation in a span.

        async with telemetry.trace("invoke", input=user_msg) as span:
            result = await agent.run(user_msg)
            span.set_tokens(prompt=100, completion=50, model="claude-sonnet-4-6")
        """
        start = time.perf_counter()

        if self.enabled and self._tracer:
            with self._tracer.start_as_current_span(
                f"{self.service_name}.{operation}"
            ) as otel_span:
                if agent_name:
                    otel_span.set_attribute("agent.name", agent_name)
                if framework:
                    otel_span.set_attribute("agent.framework", framework)
                agent_span = AgentSpan(otel_span, start)
                try:
                    yield agent_span
                except Exception as e:
                    agent_span.record_exception(e)
                    raise
        else:
            agent_span = AgentSpan(None, start)
            try:
                yield agent_span
            except Exception:
                raise
