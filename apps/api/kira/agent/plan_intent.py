"""Reading a sentence into the day planner's own controls.

The Plan screen already has the controls — how the user would travel, whether
the list is halal only, the ceiling, the order it is read in. This turns a
sentence into a setting for each of them and hands them back for the screen to
apply, so what was understood arrives as chips the user can see and correct
with a tap.

It answers nothing, and that is deliberate. A reply printed beside the chips
would be a second opinion about the same list, with nothing on the page to say
which of the two the rows below actually came from.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from kira.agent.llm import get_chat_model, offline_reason
from kira.agent.tools.day_plan import PlanArgs
from kira.agent.tools.spec import money_str
from kira.config import get_settings
from kira.money import Money
from kira.services.day_plan import Mode, resolve_kind

# The three orders the Plan screen offers. They live on the client, because
# ordering a list it already holds costs no round trip -- but a sentence is
# read here, so the words for them have to be known here too.
Sort = Literal["balanced", "cheapest", "closest"]


# Subclassed rather than restated, and the docstring below is kept short for
# the same reason it exists at all: it is sent to the model as the schema's
# description. A live model already fills PlanArgs correctly from "somewhere
# halal near KLCC under RM15", so a second copy of those fields here would be a
# second set of descriptions to keep in agreement about what a ceiling in sen is.
class PlanIntent(PlanArgs):
    """The day planner's controls, as one sentence would set them."""

    sort: Sort = Field(
        default="balanced",
        description=(
            "The order the list is read in. 'cheapest' for the least money "
            "whatever the journey, 'closest' for the shortest journey whatever "
            "it costs — that is the one for 'I'd rather not go far' — and "
            "'balanced' when the sentence weighs the two against each other."
        ),
    )
    unread: str = Field(
        default="",
        max_length=140,
        description=(
            "Any part of the request you could not turn into one of the fields "
            "above, in the user's own words. A place to search near belongs "
            "here: where the search is measured from is not yours to set. "
            "Leave it empty when you used all of the sentence."
        ),
    )


@dataclass(frozen=True, slots=True)
class Filters:
    """The Plan screen's controls, as the screen holds them."""

    lat: float
    lng: float
    mode: Mode
    halal_only: bool
    # None means the screen has no ceiling of its own and today's safe-to-spend
    # is standing in for one.
    cap_sen: int | None
    # One kind of food, in the curated set's own spelling, or None for all of
    # them. Only ever a word that set carries -- see ``interpret``.
    kind: str | None
    sort: Sort


@dataclass(frozen=True, slots=True)
class Interpretation:
    """What one sentence came to.

    ``filters`` is the whole new control state or it is None, and never
    anything in between. Half a filter set is the worst of the three outcomes:
    the user reads the list below as the answer to everything they asked for,
    and it is the answer to part of it.
    """

    filters: Filters | None
    understood: str = ""
    unread: str = ""
    reason: str = ""


# Every one of these ends by saying the screen did not move, and that is the
# point rather than a repetition to be tidied away. A degraded path that goes
# quiet is indistinguishable from one that worked.
UNREACHABLE = (
    "I could not reach my language model just now, so I have not read that. "
    "Nothing below has changed."
)
TOO_SLOW = (
    "Reading that was taking longer than {seconds} seconds, so I stopped. "
    "Nothing below has changed."
)
UNREADABLE = "I could not read that into these filters. Nothing below has changed."
NOTHING_TO_SET = "There is nothing in that I can set on this screen. Nothing below has changed."

_INSTRUCTION = """You set the controls on a day-planner screen. You do not answer the user.

Their sentence describes what they want from a list of nearby places to eat. Turn
it into settings for the controls below and nothing else: the screen re-ranks its
own list from whatever you set, and it is the only thing the user will read.

Set only the fields the sentence actually asks for. Anything it does not mention
stays exactly as it is, so do not restate a control the user said nothing about.

Money is in sen. RM15 is 1500.

The kind of food is not free text. Set it only to one of the words listed in its
description, and only when the sentence actually asks for that food. A word that
is not in that list will be dropped and read back to the user as something I
could not place, so guessing at the nearest category costs them their filter.

Where the search is measured from is not yours to set. It comes from the user's
device, and a location they did not give would move the whole list somewhere they
never asked about. If the sentence names a place to search near, put those words
in `unread` and leave the coordinates alone.

The controls are currently:
{current}"""

_MODE_WORDS: dict[Mode, str] = {"walk": "on foot", "transit": "by LRT", "ride": "by Grab"}

_SORT_WORDS: dict[Sort, str] = {
    "balanced": "cost and time weighed together",
    "cheapest": "cheapest first",
    "closest": "closest first",
}


def _seconds(value: float) -> str:
    return f"{value:g}"


def _current_block(current: Filters, currency: str) -> str:
    ceiling = (
        f"{money_str(Money(current.cap_sen, currency))}"
        if current.cap_sen is not None
        else "none of the user's own; today's safe-to-spend is standing in"
    )
    return "\n".join(
        (
            f"- travelling: {current.mode}",
            f"- halal only: {'on' if current.halal_only else 'off'}",
            f"- ceiling: {ceiling}",
            f"- kind of food: {current.kind or 'any'}",
            f"- order: {current.sort}",
        )
    )


def _understood(before: Filters, after: Filters, currency: str) -> str:
    """The short line the screen reads back, built from what actually changed.

    Written from the filters rather than asked of the model on purpose. A line
    the model wrote could describe a setting other than the one the chips are
    about to show, and the whole reason for showing a line is that a misreading
    should be visible.
    """
    said: list[str] = []
    if after.halal_only != before.halal_only:
        said.append("halal only" if after.halal_only else "halal off")
    if after.cap_sen != before.cap_sen:
        said.append(
            f"under {money_str(Money(after.cap_sen, currency))}"
            if after.cap_sen is not None
            else "no ceiling but today's room"
        )
    if after.kind != before.kind:
        said.append(after.kind.lower() if after.kind is not None else "any kind of food")
    if after.mode != before.mode:
        said.append(_MODE_WORDS[after.mode])
    if after.sort != before.sort:
        said.append(_SORT_WORDS[after.sort])
    if not said:
        return ""
    return "I read that as " + ", ".join(said) + "."


async def interpret(text: str, current: Filters, *, currency: str = "MYR") -> Interpretation:
    """One sentence, read into the controls, or nothing at all.

    There is no partial answer here. Offline, too slow, refused or unparseable
    all come back with no filters and a reason the screen can print.
    """
    if offline_reason() is not None:
        return Interpretation(None, reason=UNREACHABLE)

    timeout = get_settings().day_plan_interpret_timeout_seconds
    model = get_chat_model(streaming=False).with_structured_output(PlanIntent)
    conversation = [
        SystemMessage(_INSTRUCTION.format(current=_current_block(current, currency))),
        HumanMessage(text),
    ]
    try:
        # The timeout is here rather than on the client because it has to bound
        # the whole call, retries included. This box sits above a live list and
        # a model thinking for half a minute would hold the screen with it.
        async with asyncio.timeout(timeout):
            read = await model.ainvoke(conversation)
    except TimeoutError:
        return Interpretation(None, reason=TOO_SLOW.format(seconds=_seconds(timeout)))
    except Exception:
        # A refusal, a dead network, a malformed answer the parser rejected.
        # None of them is the user's problem and none of them may move a chip.
        return Interpretation(None, reason=UNREADABLE)

    if not isinstance(read, PlanIntent):
        # Prose where a filled schema was asked for.
        return Interpretation(None, reason=UNREADABLE)

    # Anything the model did not state is left as it was. Pydantic would fill an
    # omitted field with the schema's default instead, which on a user who is on
    # the LRT would quietly put them back on foot -- a change they did not ask
    # for is the same failure as a change half-applied.
    said = read.model_fields_set

    # A kind is the one control whose vocabulary is finite and not the model's.
    # Asked for somewhere "hawker" or "healthy", a live model will fill this
    # field confidently with a word no place carries, and applying it would
    # empty the list behind a chip the user cannot argue with -- the screen
    # would be showing them nothing on the strength of a category that does not
    # exist. So an unrecognised word sets no filter and is handed back as
    # unread, which is what the box already does with the rest of a sentence it
    # could not place. A recognised one is stored in the set's own spelling, so
    # the chip reads like the places do.
    kind, unplaceable = current.kind, ""
    if "kind" in said:
        if read.kind is None:
            kind = None
        elif (resolved := resolve_kind(read.kind)) is not None:
            kind = resolved
        else:
            unplaceable = read.kind.strip()

    after = Filters(
        # The origin is the caller's, always. Whatever the model put in lat/lng
        # is dropped here rather than trusted: a location the user never gave is
        # the one thing on this screen it must not be able to invent.
        lat=current.lat,
        lng=current.lng,
        mode=read.mode if "mode" in said else current.mode,
        halal_only=read.halal_only if "halal_only" in said else current.halal_only,
        cap_sen=read.cap_sen if "cap_sen" in said else current.cap_sen,
        kind=kind,
        sort=read.sort if "sort" in said else current.sort,
    )

    # Joined rather than one replacing the other: a sentence can name a place to
    # search near and a kind of food nothing here serves, and dropping either
    # would be the screen going quiet about half of what it could not use.
    unread = ", ".join(part for part in (read.unread.strip(), unplaceable) if part)
    understood = _understood(current, after, currency)
    if not understood:
        # It parsed, and it asked for nothing. Applying that would leave a line
        # on screen claiming a reading behind a list that never moved.
        return Interpretation(None, unread=unread, reason=NOTHING_TO_SET)
    return Interpretation(after, understood=understood, unread=unread)
