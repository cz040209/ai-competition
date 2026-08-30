"""approval — where a proposed write stops and waits for the user.

The row is written, `interrupt()` is called, the HTTP request ends and the
graph state sits in the checkpointer. Nothing has been written to financial
state, and nothing will be until the user answers.

On resume, the arguments are validated and the policy re-checked before the
handler runs. An approval row is not a licence to execute whatever it happens
to contain.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import ValidationError

from kira.agent import events
from kira.agent.policy import refusal_for
from kira.agent.resources import invalidate, tool_context
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY
from kira.services import butler_approvals
from kira.services.audit import ACTOR_USER, record

ACCEPT = "accept"
EDIT = "edit"
REJECT = "reject"


def _message(name: str, call_id: str, payload: dict[str, Any], failed: bool = False) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, default=str),
        name=name,
        tool_call_id=call_id,
        status="error" if failed else "success",
    )


async def approval(
    state: ButlerState, runtime: Runtime[ButlerContext], config: RunnableConfig
) -> dict:
    proposed = state.get("pending_write")
    if not proposed:  # pragma: no cover - the guard routed us here
        return {"pending_write": None}

    context = runtime.context
    spec = REGISTRY.get(proposed["name"])
    if spec is None or not spec.is_write:  # pragma: no cover - the guard checked this
        return {"pending_write": None}

    graph_thread_id = str(config.get("configurable", {}).get("thread_id", ""))
    summary = spec.summarise(spec.args_model.model_validate(proposed["args"]))
    row = await butler_approvals.propose(
        context.session,
        context.user,
        thread_id=context.thread_id,
        tool=spec.name,
        args=proposed["args"],
        summary=summary,
        evidence=state.get("evidence") or [],
        graph_thread_id=graph_thread_id,
        tool_call_id=proposed["id"],
    )
    events.emit(
        runtime,
        events.APPROVAL,
        approval_id=str(row.id),
        tool=spec.name,
        module=spec.module,
        summary=summary,
        args=proposed["args"],
    )

    # The request ends here. What comes back is the user's decision.
    decision = interrupt(
        {
            "approval_id": str(row.id),
            "tool": spec.name,
            "module": spec.module,
            "summary": summary,
            "args": proposed["args"],
        }
    )
    decision = decision or {}
    action = decision.get("action", REJECT)
    if action == REJECT:
        return {
            "pending_write": None,
            "messages": [
                _message(spec.name, proposed["id"], {"applied": False, "reason": "rejected"})
            ],
            "applied": None,
        }

    arguments = decision.get("args") if action == EDIT else proposed["args"]
    try:
        args = spec.args_model.model_validate(arguments or {})
    except ValidationError as exc:
        return {
            "pending_write": None,
            "messages": [
                _message(
                    spec.name,
                    proposed["id"],
                    {"applied": False, "reason": exc.errors()},
                    failed=True,
                )
            ],
            "applied": None,
        }

    # Re-read from the arguments that are actually about to run. An edit changes
    # what the write does, and a summary composed before the interrupt describes
    # the proposal it replaced -- so leaving it standing would file the audit
    # event, settle the row and confirm back to the user in the words of a change
    # nobody made. On an accept the two are the same string.
    summary = spec.summarise(args)

    blocked = await refusal_for(
        context.session, context.user, spec.name, args.model_dump(mode="json")
    )
    if blocked is not None:
        return {
            "pending_write": None,
            "messages": [
                _message(
                    spec.name, proposed["id"], {"applied": False, "reason": blocked}, failed=True
                )
            ],
            "applied": None,
        }

    tools = await tool_context(runtime, state.get("attachment"))
    result = await spec.handler(tools, args)
    invalidate(runtime)
    event = await record(
        context.session,
        context.user,
        actor=ACTOR_USER,
        action=f"butler.{spec.name}",
        detail={"summary": summary, "args": args.model_dump(mode="json"), "result": result.value},
    )
    await butler_approvals.settle(
        context.session,
        row,
        applied=True,
        args=args.model_dump(mode="json"),
        summary=summary,
        audit_event_id=event.id,
    )

    rows = [row_.as_pair() for row_ in result.evidence]
    if rows:
        events.emit(runtime, events.EVIDENCE, rows=rows)
    return {
        "pending_write": None,
        "messages": [_message(spec.name, proposed["id"], {"applied": True, **_dict(result.value)})],
        "evidence": (state.get("evidence") or []) + rows,
        "tools_used": (state.get("tools_used") or []) + [spec.name],
        "applied": {"tool": spec.name, "summary": summary},
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"result": value}
