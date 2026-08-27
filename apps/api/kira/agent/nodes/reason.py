"""agent — the model bound to the registry's tools.

This turn never streams: DashScope's compatibility mode forbids `tools` with
`stream=True`, and a turn that emits tool calls rather than prose has nothing
worth streaming anyway.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

from kira.agent import events, prompt
from kira.agent.llm import OfflineChatModel, get_chat_model
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY


def _model(runtime: Runtime[ButlerContext], attachment):
    factory = runtime.context.model_factory
    if factory is not None:
        return factory(streaming=False, attachment=attachment)
    return get_chat_model(streaming=False, attachment=attachment)


async def agent(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    attachment = state.get("attachment")
    system = SystemMessage(
        prompt.system_prompt(
            context=state.get("context_block", ""),
            memory=state.get("memory_block", ""),
            history=state.get("history_block", ""),
            attachment=state.get("attachment_block", ""),
            tool_names=tuple(spec.name for spec in REGISTRY),
        )
    )
    conversation = [system, *state.get("messages", [])]

    model = _model(runtime, attachment).bind_tools(REGISTRY.schemas())
    try:
        reply = await model.ainvoke(conversation)
    except Exception as exc:  # the venue's network is not the user's problem
        events.emit(runtime, events.THINKING, text="Working from what is already here")
        fallback = OfflineChatModel(attachment=attachment).bind_tools(REGISTRY.schemas())
        reply = await fallback.ainvoke(conversation)
        reply.response_metadata["kira_fallback"] = str(exc)

    if not isinstance(reply, AIMessage):  # pragma: no cover - defensive
        reply = AIMessage(content=str(reply))
    return {"messages": [reply], "iterations": state.get("iterations", 0) + 1}
