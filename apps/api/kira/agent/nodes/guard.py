"""guard — the write boundary, and the only place a tool call becomes permitted.

Every proposed call passes through here before anything executes. Unknown
names, arguments that fail validation and protected resources are refused with
a message the model can read; what survives is split by `ToolSpec.kind`, and a
write is routed to approval rather than to execution.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from pydantic import ValidationError

from kira.agent import events
from kira.agent.policy import refusal_for
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY
from kira.config import get_settings


def _last_ai(state: ButlerState) -> AIMessage | None:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage):
            return message
    return None


def _refusal(call: dict[str, Any], reason: str) -> ToolMessage:
    """A refusal is a tool result, not an error: the model has to see it."""
    return ToolMessage(
        content=json.dumps({"refused": True, "reason": reason}),
        name=call.get("name", "unknown"),
        tool_call_id=call.get("id", ""),
        status="error",
    )


async def guard(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    reply = _last_ai(state)
    calls = list(getattr(reply, "tool_calls", None) or [])
    if not calls:
        return {"approved_reads": [], "pending_write": None}

    context = runtime.context
    settings = get_settings()
    if state.get("iterations", 0) > settings.butler_max_tool_iterations:
        return {
            "approved_reads": [],
            "pending_write": None,
            "messages": [
                _refusal(call, "Enough looking; answer from what you already have.")
                for call in calls
            ],
        }

    reads: list[dict[str, Any]] = []
    write: dict[str, Any] | None = None
    refusals: list[str] = []
    responses: list[ToolMessage] = []

    for call in calls:
        name = call.get("name", "")
        spec = REGISTRY.get(name)
        if spec is None:
            reason = f"There is no tool called {name}."
            refusals.append(reason)
            responses.append(_refusal(call, reason))
            continue

        try:
            args = spec.args_model.model_validate(call.get("args") or {})
        except ValidationError as exc:
            reason = f"{name} was called with arguments it cannot accept: {exc.errors()}"
            refusals.append(reason)
            responses.append(_refusal(call, reason))
            continue

        # Protected resources are refused whatever the tier, and before anything runs.
        blocked = await refusal_for(
            context.session, context.user, name, args.model_dump(mode="json")
        )
        if blocked is not None:
            refusals.append(blocked)
            responses.append(_refusal(call, blocked))
            events.emit(runtime, events.THINKING, text="That one is off limits")
            continue

        permitted = {
            "id": call.get("id", ""),
            "name": name,
            "args": args.model_dump(mode="json"),
        }
        if spec.is_write:
            # Only the first write is ever proposed: an approval card asks about
            # one change, and the user answering it is the point.
            if write is None:
                write = permitted
            else:
                reason = "One change at a time. Ask me again once this one is decided."
                refusals.append(reason)
                responses.append(_refusal(call, reason))
        else:
            reads.append(permitted)

    return {
        "approved_reads": reads,
        "pending_write": write,
        "refusals": refusals,
        "messages": responses,
    }


def route_after_guard(state: ButlerState) -> str:
    if state.get("approved_reads"):
        return "tools"
    if state.get("pending_write"):
        return "approval"
    return "compose"


def route_after_tools(state: ButlerState) -> str:
    """Where a turn goes once its reads have run.

    Back to the model only when the guard refused something and it deserves a
    second attempt with that refusal in front of it. Otherwise the reads are the
    answer, and a second tool-bound round trip is latency the user pays for
    nothing.
    """
    if state.get("pending_write"):
        return "approval"
    if state.get("refusals"):
        return "agent"
    return "compose"
