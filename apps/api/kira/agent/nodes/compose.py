"""compose — the answer, and the only turn that streams.

No tools are bound here, which is both what DashScope requires for streaming
and what keeps the model from reaching for one more number mid-sentence. The
evidence is already fixed by the time this runs.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

from kira.agent import events, prompt
from kira.agent.llm import OfflineChatModel, get_chat_model
from kira.agent.state import ButlerContext, ButlerState

FALLBACK = (
    "I could not reach my language model just now.\n"
    "The numbers above are still live and correct — they come from your ledger, not from it."
)


def _model(runtime: Runtime[ButlerContext], attachment):
    factory = runtime.context.model_factory
    if factory is not None:
        return factory(streaming=True, attachment=attachment)
    return get_chat_model(streaming=True, attachment=attachment)


def _evidence_block(rows: list[list[str]]) -> str:
    if not rows:
        return "No tool returned a figure this turn. Say so rather than estimating."
    lines = "\n".join(f"- {label}: {value}" for label, value in rows)
    return "These are the figures the tools returned. Use them exactly:\n" + lines


async def compose(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    events.emit(runtime, events.THINKING, text="Putting it in words")
    evidence = state.get("evidence") or []
    system = SystemMessage(
        prompt.system_prompt(
            context=state.get("context_block", ""),
            memory=state.get("memory_block", ""),
            history=state.get("history_block", ""),
            attachment=state.get("attachment_block", ""),
        )
        + "\n\n"
        + _evidence_block(evidence)
        + "\n\n"
        + prompt.COMPOSE_INSTRUCTION
    )
    # The instruction goes in the system block rather than as a trailing turn:
    # the last human message must stay the user's question, not ours.
    conversation = [system, *state.get("messages", [])]

    model = _model(runtime, state.get("attachment"))
    answer = await _stream(runtime, model, conversation)
    if not answer.strip():
        offline = OfflineChatModel(attachment=state.get("attachment"))
        answer = await _stream(runtime, offline, conversation)
    if not answer.strip():
        answer = FALLBACK

    return {"answer": answer, "messages": [AIMessage(content=answer)]}


async def _stream(runtime, model, conversation) -> str:
    """Emit tokens as they arrive; fall back to one shot if streaming fails."""
    collected: list[str] = []
    try:
        async for chunk in model.astream(conversation):
            piece = chunk.content
            if not isinstance(piece, str) or not piece:
                continue
            collected.append(piece)
            events.emit(runtime, events.TOKEN, text=piece)
        return "".join(collected)
    except Exception as exc:
        events.emit(runtime, events.THINKING, text="Falling back to what is already here")
        try:
            reply = await model.ainvoke(conversation)
        except Exception:
            return ""
        text = reply.content if isinstance(reply.content, str) else ""
        if text:
            events.emit(runtime, events.TOKEN, text=text)
        else:  # pragma: no cover - defensive
            events.emit(runtime, events.ERROR, message=str(exc))
        return text
