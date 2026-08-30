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

# Suria KLCC — the prototype's own fallback for a user who has not shared their
# location. The maps adapter covers the whole city, so this is a starting point
# rather than the one spot its places cluster around.
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


class AddPlaceArgs(BaseModel):
    place_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The id of one of the places build_day_plan returned. The id, not the "
            "name and not its position in the list."
        ),
    )
    name: str = Field(
        min_length=1,
        max_length=120,
        description="That place's name, exactly as the plan gave it.",
    )
    total_sen: int = Field(
        gt=0,
        description=(
            "The whole outing in sen, meal and travel together — the place's "
            "total_sen from the plan, not the meal on its own."
        ),
    )
    lat: float = Field(
        default=_KLCC_LAT, description="The latitude the plan was built from."
    )
    lng: float = Field(
        default=_KLCC_LNG, description="The longitude the plan was built from."
    )


async def _build(ctx: ToolContext, args: PlanArgs) -> ToolResult:
    room_sen = ctx.dashboard.safe_today_sen
    cap_sen = args.cap_sen if args.cap_sen is not None else room_sen
    found = await day_plan_service.find_places(
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
                "address": place.address,
                "km": place.km,
                # The model is told which distance produced the fare so it
                # cannot narrate a straight-line estimate as a quoted price.
                "road_km": place.road_km,
                "distance_basis": place.distance_basis,
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
            # Named beside the cost it produced. A fare measured in a straight
            # line understates a real KL journey, and the row is what stops the
            # figure above it reading as a quote.
            EvidenceRow(
                "Distance measured",
                (
                    f"{best.km:.1f} km by road"
                    if best.distance_basis == "road"
                    else f"{best.km:.1f} km in a straight line"
                ),
            ),
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


async def _add_place(ctx: ToolContext, args: AddPlaceArgs) -> ToolResult:
    place = day_plan_service.find_place(args.place_id, lat=args.lat, lng=args.lng)
    if place is None:
        # The guard refuses an unknown id before a card is ever raised, and the
        # approval refuses it again on resume, so getting here means the curated
        # set moved underneath a card already on screen. Failing is the only
        # honest answer left: the alternative is a draft for a place that is no
        # longer anywhere I can point at.
        raise day_plan_service.UnknownPlace(args.place_id)

    # Straight through the service the screen's own "Add to today" calls, so the
    # date, the plan labelling, the note and the draft invariant are the same
    # ones rather than a second set that agrees today. The band is the curated
    # place's, never the model's -- a percentage is not something it may assert.
    #
    # The name and the total are the approved ones and not the place's, because
    # the card is this path's equivalent of the row that was tapped: what the
    # user read is what lands, and an edited card is the user correcting it.
    view = await day_plan_service.add_to_today(
        ctx.session,
        ctx.user,
        name=args.name,
        total_sen=args.total_sen,
        confidence=place.confidence,
        today=ctx.today,
    )
    currency = ctx.currency
    return ToolResult(
        {
            "id": str(view.id),
            "merchant": view.merchant,
            "amount_sen": view.amount_sen,
            "status": view.status,
            "source": view.source,
            "confidence": view.confidence,
        },
        (
            EvidenceRow(view.merchant, money_str(Money(view.amount_sen, currency))),
            EvidenceRow("Waiting as", "a draft in Activity"),
            # Stated after the write, and unchanged by it. A draft is outside
            # every engine calculation, so the figure here is the same one the
            # card was read against.
            EvidenceRow(
                "Safe to spend today",
                money_str(Money(ctx.dashboard.safe_today_sen, currency)),
            ),
        ),
    )


def _summarise_add_place(args: AddPlaceArgs) -> str:
    return (
        f"Add {args.name} for RM{Money(args.total_sen).ringgit_str()} to today as a "
        "draft. Nothing counts against today until you confirm it."
    )


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
            "about going somewhere near a given location.\n"
            "A preference the user has had you remember is a reason to set these "
            "arguments a certain way. 'I don't like walking far' means mode should be "
            "transit or ride, and that you lead with the shortest journey rather than "
            "the cheapest total. A preference acts on the arguments you pass and the "
            "order you read the places back in, and nowhere else — the ranking itself "
            "is cost against today's room, so the user can always tell why the list "
            "came out the way it did.\n"
            "Name the places. A count and a price range — 'five halal options from "
            "RM13 to RM14' — is not an answer to where to eat: say which ones, using "
            "the names this tool returned and never a name it did not."
        ),
        args_model=PlanArgs,
        handler=_build,
    ),
    ToolSpec(
        name="add_place_to_today",
        module=MODULE,
        kind="write",
        label="Adding a place to today",
        description=(
            "Put one of build_day_plan's places on today as a draft. Call this for "
            "'add the second one', 'put that down for lunch', or any request to keep "
            "a place the plan just offered. Pass its id and the same lat/lng the plan "
            "was built from. It waits in Activity and moves nothing until the user "
            "confirms it."
        ),
        args_model=AddPlaceArgs,
        handler=_add_place,
        summarise=_summarise_add_place,
    ),
)
