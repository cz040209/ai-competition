"""Nearby places, ranked by what they would cost against today's room.

Reads through the same `kira.services.day_plan` the day-planner screen uses,
so the Butler's idea of what an outing costs cannot drift from the app's.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.money import Money
from kira.services import day_plan as day_plan_service

MODULE = "day_plan"

# Suria KLCC — the FakeMaps seed centre, and the prototype's own fallback for
# a user who has not shared their location.
_KLCC_LAT = 3.1577
_KLCC_LNG = 101.7120


class PlanArgs(BaseModel):
    lat: float = Field(
        default=_KLCC_LAT, description="Latitude to search from. Defaults to KLCC."
    )
    lng: float = Field(
        default=_KLCC_LNG, description="Longitude to search from. Defaults to KLCC."
    )
    mode: Literal["walk", "transit", "ride"] = Field(
        default="walk", description="How the user would travel there."
    )
    halal_only: bool = Field(default=False, description="Only show halal places.")
    cap_sen: int | None = Field(
        default=None,
        gt=0,
        description=(
            "A display ceiling on total outing cost, in sen. Leave unset to use "
            "today's safe-to-spend."
        ),
    )


async def _build(ctx: ToolContext, args: PlanArgs) -> ToolResult:
    room_sen = ctx.dashboard.safe_today_sen
    cap_sen = args.cap_sen if args.cap_sen is not None else room_sen
    found = day_plan_service.find_places(
        lat=args.lat,
        lng=args.lng,
        mode=args.mode,
        halal_only=args.halal_only,
        cap_sen=cap_sen,
        room_sen=room_sen,
    )
    top = found.places[:5]
    currency = ctx.currency

    def money(sen: int) -> str:
        return money_str(Money(sen, currency))

    # The room is stated rather than left in the shares: on a day already spent
    # out every share is null, and a model given only those would have nothing
    # to quote but a figure it made up. The two counts are stated for the same
    # reason: an empty list otherwise reads as a ceiling problem even when the
    # user is nowhere near anything the adapter knows, or is standing beside a
    # place their own halal filter took out.
    value = {
        "room_sen": room_sen,
        "cap_sen": cap_sen,
        "nearby_count": found.nearby_count,
        "matching_count": found.matching_count,
        "places": [
            {
                "id": place.id,
                "name": place.name,
                "kind": place.kind,
                "km": place.km,
                "travel_sen": place.travel_sen,
                "minutes": place.minutes,
                "total_sen": place.total_sen,
                "share": place.share,
                "band": place.band,
                "confidence": place.confidence,
                "halal": place.halal,
                "note": place.note,
            }
            for place in top
        ],
    }

    # Labelled as the dashboard tool labels it, so the two collapse into one row
    # rather than reading as two figures that happen to agree.
    room_row = EvidenceRow("Safe to spend today", money(room_sen))
    if top:
        best = top[0]
        evidence = (
            room_row,
            EvidenceRow("Cheapest nearby", best.name),
            EvidenceRow("Total cost", money(best.total_sen)),
            EvidenceRow("Fits today's room", best.band),
        )
    elif found.nearby_count == 0:
        evidence = (room_row, EvidenceRow("Nearby places", "none within range"))
    elif found.matching_count == 0:
        # Only reachable with halal_only on, so naming it is a statement of what
        # the filter did, not a guess at why the list came back empty.
        evidence = (
            room_row,
            EvidenceRow(
                "Nearby places",
                f"{found.nearby_count} within range, none of them halal",
            ),
        )
    else:
        evidence = (
            room_row,
            EvidenceRow(
                "Nearby places",
                f"{found.matching_count} within range, none under the ceiling",
            ),
        )

    return ToolResult(value, evidence)


SPECS = (
    ToolSpec(
        name="build_day_plan",
        module=MODULE,
        kind="read",
        label="Finding places nearby",
        description=(
            "Find nearby curated places and rank them by total outing cost (meal "
            "estimate plus travel) against today's safe-to-spend. Call this for "
            "'where can I eat', 'what can I afford for lunch nearby', or any question "
            "about going somewhere near a given location."
        ),
        args_model=PlanArgs,
        handler=_build,
    ),
)
