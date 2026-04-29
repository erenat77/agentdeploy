"""
HITLGate — Human-in-the-Loop gate primitive.

Agents call gate.checkpoint(state) at decision points.
If the gate is armed, execution pauses and waits for a human
decision (approve / reject / modify) before continuing.

Delivery channels:
  - Webhook (any HTTP endpoint)
  - Slack (via incoming webhook URL)
  - Console (for local dev — prints and waits for stdin)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class HITLDecision(StrEnum):
    APPROVE = "approve"
    REJECT  = "reject"
    MODIFY  = "modify"


@dataclass
class HITLConfig:
    webhook: str = ""
    slack_channel: str = ""
    timeout_seconds: int = 3600


@dataclass
class CheckpointResult:
    decision: HITLDecision
    modified_state: Any = None
    reviewer: str = ""
    reason: str = ""
    reviewed_at: float = field(default_factory=time.time)


class HITLGate:
    """
    Add human oversight to any agent at a checkpoint.

    Usage:
        gate = HITLGate(webhook="https://yourapp.com/approve")

        # Inside your agent or orchestrator:
        result = await gate.checkpoint(
            state=current_state,
            description="Agent is about to call the payments API",
        )
        if result.decision == HITLDecision.REJECT:
            return "Cancelled by reviewer"
        state = result.modified_state or current_state
    """

    def __init__(
        self,
        *,
        webhook: str = "",
        slack_webhook: str = "",
        timeout_seconds: int = 3600,
        auto_approve_after: int | None = None,
        console_fallback: bool = True,
    ) -> None:
        self.webhook = webhook
        self.slack_webhook = slack_webhook
        self.timeout_seconds = timeout_seconds
        self.auto_approve_after = auto_approve_after
        self.console_fallback = console_fallback
        self._pending: dict[str, asyncio.Future] = {}

    async def checkpoint(
        self,
        state: Any,
        *,
        description: str = "",
        run_id: str = "",
    ) -> CheckpointResult:
        """
        Pause execution and wait for a human decision.

        Returns a CheckpointResult with the decision and
        optionally a modified state from the reviewer.
        """
        checkpoint_id = run_id or f"cp-{int(time.time() * 1000)}"
        payload = {
            "checkpoint_id": checkpoint_id,
            "description": description,
            "state": state if isinstance(state, (str, int, float, bool)) else str(state),
        }

        if self.webhook:
            return await self._wait_for_webhook(checkpoint_id, payload)
        elif self.slack_webhook:
            return await self._notify_slack(checkpoint_id, payload)
        elif self.console_fallback:
            return await self._console_prompt(payload)
        else:
            logger.warning("HITLGate has no delivery channel — auto-approving.")
            return CheckpointResult(decision=HITLDecision.APPROVE)

    async def resolve(self, checkpoint_id: str, result: CheckpointResult) -> None:
        """
        Called by your webhook handler when the reviewer responds.
        Use this in your FastAPI/Flask route that receives approvals.

        Example:
            @app.post("/approve/{checkpoint_id}")
            async def approve(checkpoint_id: str, body: ApproveBody):
                result = CheckpointResult(decision=HITLDecision.APPROVE, reviewer=body.user)
                await gate.resolve(checkpoint_id, result)
        """
        future = self._pending.get(checkpoint_id)
        if future and not future.done():
            future.set_result(result)

    async def _wait_for_webhook(
        self, checkpoint_id: str, payload: dict
    ) -> CheckpointResult:
        import httpx

        loop = asyncio.get_event_loop()
        future: asyncio.Future[CheckpointResult] = loop.create_future()
        self._pending[checkpoint_id] = future

        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    self.webhook,
                    json={**payload, "callback_id": checkpoint_id},
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"HITLGate webhook delivery failed: {e}")

        try:
            return await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except TimeoutError:
            logger.warning(f"HITLGate checkpoint {checkpoint_id} timed out.")
            if self.auto_approve_after and self.timeout_seconds >= self.auto_approve_after:
                return CheckpointResult(
                    decision=HITLDecision.APPROVE,
                    reason="auto-approved after timeout",
                )
            return CheckpointResult(
                decision=HITLDecision.REJECT,
                reason="timed out waiting for human review",
            )
        finally:
            self._pending.pop(checkpoint_id, None)

    async def _notify_slack(
        self, checkpoint_id: str, payload: dict
    ) -> CheckpointResult:
        import httpx

        message = {
            "text": f"*HITL checkpoint* `{checkpoint_id}`\n{payload.get('description', '')}\n"
                    f"State: ```{payload.get('state', '')}```\n"
                    f"Reply with `/approve {checkpoint_id}` or `/reject {checkpoint_id}`"
        }
        try:
            async with httpx.AsyncClient() as client:
                await client.post(self.slack_webhook, json=message, timeout=10)
        except Exception as e:
            logger.error(f"Slack delivery failed: {e}")

        loop = asyncio.get_event_loop()
        future: asyncio.Future[CheckpointResult] = loop.create_future()
        self._pending[checkpoint_id] = future
        try:
            return await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except TimeoutError:
            return CheckpointResult(
                decision=HITLDecision.REJECT,
                reason="timed out waiting for Slack response",
            )
        finally:
            self._pending.pop(checkpoint_id, None)

    async def _console_prompt(self, payload: dict) -> CheckpointResult:
        print(f"\n[HITLGate] Checkpoint: {payload.get('description', '')}")
        print(f"State: {payload.get('state', '')}")
        choice = input("Decision [approve/reject/modify]: ").strip().lower()
        if choice.startswith("a"):
            return CheckpointResult(decision=HITLDecision.APPROVE, reviewer="console")
        elif choice.startswith("m"):
            modified: Any = input("Enter modified state (JSON or string): ").strip()
            with contextlib.suppress(json.JSONDecodeError):
                modified = json.loads(modified)
            return CheckpointResult(
                decision=HITLDecision.MODIFY,
                modified_state=modified,
                reviewer="console",
            )
        return CheckpointResult(decision=HITLDecision.REJECT, reviewer="console")
