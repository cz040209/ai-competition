"""The chat model, in two implementations behind one interface.

Online is Qwen through DashScope's OpenAI-compatible endpoint. Offline is a
deterministic model that emits the same tool calls and writes the same shape of
answer. The graph, the tools, the guard, the evidence and the approval flow are
identical either way — a dead venue network degrades the Butler's prose, not
its behaviour.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from kira.config import get_settings


def _rm(sen: int | None) -> str:
    """RM60, RM18.90 — the way the number is said out loud, not stored."""
    if sen is None:
        return "RM0"
    whole, minor = divmod(abs(int(sen)), 100)
    sign = "-" if sen < 0 else ""
    body = f"{whole:,}" if minor == 0 else f"{whole:,}.{minor:02d}"
    return f"{sign}RM{body}"


_AMOUNT = re.compile(
    r"(?:rm|myr)\s?(\d{1,7}(?:[.,]\d{1,2})?)|(\d{1,7}(?:\.\d{1,2})?)\s*ringgit", re.I
)


def _amount_sen(text: str) -> int | None:
    match = _AMOUNT.search(text)
    if not match:
        return None
    raw = (match.group(1) or match.group(2)).replace(",", ".")
    whole, _, minor = raw.partition(".")
    return int(whole) * 100 + int((minor + "00")[:2] or 0)


# ── the offline model ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Route:
    """One demo-script question: which tools it needs, and how it reads back."""

    name: str
    pattern: re.Pattern[str]
    tools: tuple[str, ...]
    arguments: Any = None
    compose: Any = None


def _payload(messages: Sequence[BaseMessage], tool: str) -> dict[str, Any] | list | None:
    """The value a tool actually returned this run, or None if it did not run."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == tool:
            try:
                return json.loads(message.content if isinstance(message.content, str) else "")
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def _last_human(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _afford_args(text: str, attachment: dict[str, Any] | None) -> dict[str, Any]:
    sen = _amount_sen(text) or (attachment or {}).get("amount_sen") or 0
    label = ""
    for candidate in ("dinner", "lunch", "coffee", "grab", "taxi", "groceries", "movie"):
        if candidate in text.lower():
            label = candidate
            break
    return {"amount_sen": max(1, sen), "label": label}


def _compose_afford(messages: Sequence[BaseMessage], text: str) -> str:
    result = _payload(messages, "calculate_safe_to_spend") or {}
    thing = result.get("label") or "it"
    if result.get("fits"):
        head = (
            f"Yes — {_rm(result.get('amount_sen'))} for {thing} leaves you "
            f"{_rm(result.get('remaining_sen'))} today."
        )
        sub = (
            f"Bills and your buffer were already set aside before that number, so this is "
            f"spare. Spend it and the rest of the cycle still runs at about "
            f"{_rm(result.get('per_day_after_sen'))} a day."
        )
    else:
        head = (
            f"It fits, but it borrows — {_rm(result.get('amount_sen'))} is "
            f"{_rm(result.get('over_by_sen'))} over today's room."
        )
        sub = (
            f"Nothing breaks: the {result.get('days_to_payday', 0)} days to payday absorb it at "
            f"about {_rm(result.get('per_day_after_sen'))} a day instead. Your bills and buffer "
            "are untouched either way."
        )
    return f"{head}\n{sub}"


def _compose_snapshot(messages: Sequence[BaseMessage], text: str) -> str:
    snap = _payload(messages, "get_financial_snapshot") or {}
    activity = _payload(messages, "list_activity") or {}
    head = f"You have {_rm(snap.get('safe_today_sen'))} safe to spend today."
    sub = (
        f"{_rm(snap.get('balance_sen'))} in the account, {_rm(snap.get('reserved_sen'))} held for "
        f"bills, {_rm(snap.get('buffer_sen'))} kept as your buffer and "
        f"{_rm(snap.get('goal_reserve_sen'))} going to your goals. What is left runs at "
        f"{_rm(snap.get('per_day_sen'))} a day for {snap.get('days_to_payday', 0)} days."
    )
    drafts = activity.get("drafts") or []
    if drafts:
        sub += f" {len(drafts)} draft{'s' if len(drafts) != 1 else ''} are still waiting on you."
    return f"{head}\n{sub}"


def _compose_drop(messages: Sequence[BaseMessage], text: str) -> str:
    snap = _payload(messages, "get_financial_snapshot") or {}
    activity = _payload(messages, "list_activity") or {}
    days = activity.get("days") or []
    latest = days[0] if days else {}
    head = (
        f"Because {_rm(latest.get('total_sen'))} landed on "
        f"{latest.get('date', 'the ledger')} and the day's allowance did not grow."
    )
    sub = (
        f"Nothing was reserved differently: {_rm(snap.get('reserved_sen'))} for bills and "
        f"{_rm(snap.get('buffer_sen'))} of buffer are the same as yesterday. Today's room fell to "
        f"{_rm(snap.get('safe_today_sen'))} purely because that spending is now confirmed."
    )
    return f"{head}\n{sub}"


def _compose_goals(messages: Sequence[BaseMessage], text: str) -> str:
    goals = _payload(messages, "list_goals") or []
    if not goals:
        return (
            "You have no goals set yet.\nGive me one target and a monthly figure, and I "
            "will hold it back before I tell you what is safe to spend."
        )
    chosen = goals[0]
    for goal in goals:
        if any(word in text.lower() for word in goal["name"].lower().split()):
            chosen = goal
            break
    head = (
        f"{chosen['name']} is at {_rm(chosen.get('saved_sen'))} of "
        f"{_rm(chosen.get('target_sen'))} — {chosen.get('months_left', 0)} months to go."
    )
    sub = (
        f"That is {_rm(chosen.get('monthly_sen'))} a month, reserved before anything is called "
        "spare. It is not affected by what you spend today."
    )
    return f"{head}\n{sub}"


def _compose_bills(messages: Sequence[BaseMessage], text: str) -> str:
    bills = _payload(messages, "list_commitments") or []
    if not bills:
        return "Nothing is due.\nNo bills are on the books for the rest of this cycle."
    first = bills[0]
    total = sum(bill.get("amount_sen", 0) for bill in bills)
    head = (
        f"{first['name']} is next — {_rm(first.get('amount_sen'))} in "
        f"{first.get('days_until', 0)} days."
    )
    sub = (
        f"{len(bills)} bills totalling {_rm(total)} are already held back, which is why "
        "today's number is smaller than your balance."
    )
    return f"{head}\n{sub}"


def _compose_attachment(messages: Sequence[BaseMessage], text: str) -> str:
    read = _payload(messages, "inspect_attachment") or {}
    afford = _payload(messages, "calculate_safe_to_spend") or {}
    if not read.get("attached"):
        return (
            "I did not get the attachment.\nTry the scan or the microphone again and I "
            "will read it."
        )
    head = (
        f"{_rm(read.get('amount_sen'))} at {read.get('merchant', 'that merchant')} — "
        f"that leaves {_rm(afford.get('remaining_sen'))} for today."
    )
    sub = (
        f"I read it at {read.get('confidence', 0)}% confidence and it is sitting as a draft. "
        "Nothing counts against your day until you confirm it."
    )
    return f"{head}\n{sub}"


def _compose_remember(messages: Sequence[BaseMessage], text: str) -> str:
    return (
        "Noted — I will hold on to that.\n"
        "You can read back everything I remember, and correct or delete any of it, under More."
    )


def _compose_overspend(messages: Sequence[BaseMessage], text: str) -> str:
    snap = _payload(messages, "get_financial_snapshot") or {}
    over = _amount_sen(text) or 0
    days = max(1, snap.get("days_to_payday", 1))
    head = (
        f"{_rm(over)} over is recoverable — it is about {_rm(over // days)} a day "
        "between now and payday."
    )
    sub = (
        "Your bills and your buffer stay where they are. Comparing that against pausing a "
        "goal contribution needs the plan engine, which is not built yet — so for now I can "
        "show you the shape of it, not apply it."
    )
    return f"{head}\n{sub}"


ROUTES: tuple[Route, ...] = (
    Route(
        "attachment",
        re.compile(r"receipt|scanned|photo|this bill|heard|voice note", re.I),
        ("inspect_attachment", "calculate_safe_to_spend"),
        arguments=lambda text, attachment: {
            "inspect_attachment": {},
            "calculate_safe_to_spend": _afford_args(text, attachment),
        },
        compose=_compose_attachment,
    ),
    Route(
        "remember",
        re.compile(r"\bremember\b|from now on|always tell me|never suggest", re.I),
        ("remember",),
        arguments=lambda text, attachment: {
            "remember": {
                "kind": "preference",
                "subject": "stated preference",
                "fact": text.strip()[:280],
                "confidence": 95,
            }
        },
        compose=_compose_remember,
    ),
    Route(
        "overspend",
        re.compile(r"overspent|overspend|blew|over budget|went over", re.I),
        ("get_financial_snapshot", "list_activity"),
        compose=_compose_overspend,
    ),
    Route(
        "afford",
        re.compile(r"afford|can i (?:spend|get|buy|have)|enough for", re.I),
        ("calculate_safe_to_spend",),
        arguments=lambda text, attachment: {
            "calculate_safe_to_spend": _afford_args(text, attachment)
        },
        compose=_compose_afford,
    ),
    Route(
        "drop",
        re.compile(r"why (?:did|is|has)|drop|dropped|went down|fell|lower than", re.I),
        ("get_financial_snapshot", "list_activity"),
        compose=_compose_drop,
    ),
    Route(
        "goals",
        re.compile(r"goal|wedding|saving|emergency fund|on track", re.I),
        ("list_goals",),
        compose=_compose_goals,
    ),
    Route(
        "bills",
        re.compile(r"bill|rent|due|commitment|instal", re.I),
        ("list_commitments",),
        compose=_compose_bills,
    ),
    Route(
        "snapshot",
        re.compile(r".", re.S),
        ("get_financial_snapshot", "list_activity"),
        compose=_compose_snapshot,
    ),
)


def route_for(text: str, attachment: dict[str, Any] | None = None) -> Route:
    if attachment:
        return ROUTES[0]
    for route in ROUTES:
        if route.pattern.search(text):
            return route
    return ROUTES[-1]


class OfflineChatModel(BaseChatModel):
    """A deterministic stand-in that emits real tool calls and real prose.

    It is not a mock in the test sense: the graph runs unmodified against it,
    which is what makes the golden conversation tests worth having.
    """

    bound_tools: list[str] = []
    attachment: dict[str, Any] | None = None

    @property
    def _llm_type(self) -> str:
        return "kira-offline"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> BaseChatModel:
        names = []
        for tool in tools:
            if isinstance(tool, dict):
                names.append(tool.get("function", {}).get("name") or tool.get("name", ""))
            else:
                names.append(getattr(tool, "name", ""))
        return self.model_copy(update={"bound_tools": [name for name in names if name]})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = _last_human(messages)
        route = route_for(text, self.attachment)

        # No tools bound means this is the composition turn: write the answer.
        if not self.bound_tools:
            answer = (route.compose or _compose_snapshot)(messages, text)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])

        # Tools already ran this turn; the model has what it asked for.
        if any(isinstance(message, ToolMessage) for message in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

        arguments = route.arguments(text, self.attachment) if route.arguments else {}
        calls = [
            {
                "name": name,
                "args": arguments.get(name, {}),
                "id": f"offline-{route.name}-{index}",
                "type": "tool_call",
            }
            for index, name in enumerate(route.tools)
            if name in self.bound_tools
        ]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="", tool_calls=calls))]
        )


# ── choosing one ──────────────────────────────────────────────────────────────


def offline_reason() -> str | None:
    """Why the Butler would run offline right now, or None if it would not."""
    settings = get_settings()
    if settings.butler_offline:
        return "BUTLER_OFFLINE is set"
    if not settings.dashscope_api_key:
        return "no DashScope API key is configured"
    return None


def get_chat_model(
    *, streaming: bool = False, attachment: dict[str, Any] | None = None
) -> BaseChatModel:
    """The model for one call.

    `streaming` is a real distinction, not a preference: DashScope's
    compatibility mode forbids `tools` together with `stream=True`, so the
    reasoning turns bind tools and do not stream, and the composition turn
    streams and binds nothing.
    """
    if offline_reason() is not None:
        return OfflineChatModel(attachment=attachment)

    settings = get_settings()
    from langchain_openai import ChatOpenAI  # imported late; the offline path needs no SDK

    return ChatOpenAI(
        base_url=settings.dashscope_base_url,
        api_key=settings.dashscope_api_key,
        model=settings.butler_model,
        streaming=streaming,
        timeout=settings.butler_request_timeout_seconds,
        max_retries=1,
    )
