"""Turn nearby curated places into money-constrained outings.

Ports kira-prototype.jsx's evaluate() (line 661): cost, travel time, and how
much of today's safe-to-spend each outing would use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from kira.adapters.geo import haversine_km
from kira.adapters.protocols import Place
from kira.adapters.registry import get_adapters
from kira.db.models import SOURCE_PLAN, User
from kira.money import round_half_up
from kira.services.transactions import TransactionView, create_transaction

Mode = Literal["walk", "transit", "ride"]
Band = Literal["ok", "tight", "over"]
# Which distance the fare and the clock below were actually built from. It
# travels with every place because it is per-place: one search can route some
# destinations and fail on others, and a single flag for the list would have to
# lie about half of it.
DistanceBasis = Literal["road", "straight_line"]


@dataclass(frozen=True, slots=True)
class ModeCost:
    base_sen: int
    per_km_sen: int
    min_per_km: float
    wait_min: float


MODES: dict[Mode, ModeCost] = {
    "walk": ModeCost(base_sen=0, per_km_sen=0, min_per_km=13.0, wait_min=0.0),
    "transit": ModeCost(base_sen=210, per_km_sen=0, min_per_km=4.5, wait_min=7.0),
    "ride": ModeCost(base_sen=500, per_km_sen=190, min_per_km=3.2, wait_min=5.0),
}


@dataclass(frozen=True, slots=True)
class EvaluatedPlace:
    id: str
    name: str
    kind: str
    address: str
    # Where it stands, so a client can point a map at this shop rather than at
    # its name. A quarter of the addresses above are a locality rather than a
    # doorstep, and eight of the names in the demo set belong to two branches
    # each -- a name search reaches the wrong one of those with no warning.
    lat: float
    lng: float
    # The distance every figure below was computed from, whichever kind it is.
    km: float
    # The road figure on its own, or None where the router did not answer for
    # this place. Stated separately from ``km`` so a client can show the real
    # driving distance without having to know which basis produced ``km``.
    road_km: float | None
    distance_basis: DistanceBasis
    travel_sen: int
    minutes: int
    total_sen: int
    # None when there is no room left today: a share of nothing is not a number,
    # and any stand-in would be indistinguishable from a real ratio.
    share: float | None
    band: Band
    confidence: str
    halal: bool
    note: str


def evaluate_place(
    place: Place,
    origin_lat: float,
    origin_lng: float,
    mode: Mode,
    room_sen: int,
    road_metres: float | None = None,
) -> EvaluatedPlace:
    """room_sen is always today's real safe-to-spend -- it is NOT the same as
    the caller's display cap_sen, which only filters what is shown.

    ``road_metres`` is what the routing adapter said about this place, or None
    if it said nothing. A car is charged for the road it drives, so where there
    is a road figure it is the one the fare and the travel time are built on;
    the great circle only stands in when there is not, and the basis returned
    with the place says which of the two happened.
    """
    # Kept regardless: it is the fallback, and computing it is free next to the
    # call that may or may not have replaced it.
    straight_line_km = haversine_km(origin_lat, origin_lng, place.lat, place.lng)
    road_km = None if road_metres is None else road_metres / 1000
    basis: DistanceBasis = "straight_line" if road_km is None else "road"
    km = straight_line_km if road_km is None else road_km
    cost = MODES[mode]
    # Distance is a measurement, so a float is right for it. The fare it implies
    # is money, so it is not: the per-km charge is accumulated in whole sen and
    # divided down with the app's own half-up rounding. Handing it to a float and
    # calling round() would round halves to even, which money.py forbids outright
    # -- at 150 m of a ride that is 528 sen where the fare is 529.
    metres = round(km * 1000)
    travel_sen = (
        0 if km < 0.12 else cost.base_sen + round_half_up(cost.per_km_sen * metres, 1000)
    )
    minutes = round(cost.wait_min + km * cost.min_per_km) + 6
    total_sen = place.estimate.sen + travel_sen
    share = total_sen / room_sen if room_sen > 0 else None
    # With nothing left today, every outing is over what is left of it.
    band: Band = (
        "over" if share is None else "ok" if share <= 0.6 else "tight" if share <= 1.0 else "over"
    )
    return EvaluatedPlace(
        id=place.id,
        name=place.name,
        kind=place.kind,
        address=place.address,
        lat=place.lat,
        lng=place.lng,
        km=km,
        road_km=road_km,
        distance_basis=basis,
        travel_sen=travel_sen,
        minutes=minutes,
        total_sen=total_sen,
        share=share,
        band=band,
        confidence=place.confidence,
        halal=place.halal,
        note=place.note,
    )


@dataclass(frozen=True, slots=True)
class PlacesFound:
    """What the maps adapter had, and what survived each filter in turn.

    An empty ``places`` has three unrelated causes and the caller must not have
    to guess between them, so each filter states what it left behind:

    * ``nearby_count`` is what the radius held. Nil means distance is the cause,
      and no ceiling and no toggle will close it.
    * ``matching_count`` is what was still standing after the halal filter, and
      before the ceiling ran. Nil against a non-nil ``nearby_count`` means the
      halal toggle is the cause -- raising the ceiling would do nothing, and
      telling the user to raise it sends them at a slider that cannot help.
    * anything left after that, with ``places`` still empty, is the ceiling:
      the one cause the user can actually drag away.

    The counts nest -- ``nearby_count >= matching_count >= len(places)`` -- so
    the first of them that is nil is the cause.
    """

    places: tuple[EvaluatedPlace, ...]
    nearby_count: int
    matching_count: int


async def find_places(
    *,
    lat: float,
    lng: float,
    mode: Mode,
    halal_only: bool,
    cap_sen: int,
    room_sen: int,
    radius_km: float = 5.0,
) -> PlacesFound:
    """cap_sen filters what is shown; room_sen (today's safe-to-spend) drives
    share/band and must never be swapped with cap_sen.

    The order below is load-bearing. Routing happens after the radius and the
    halal filter and before the ceiling, because it is the only step that costs
    a network call and the only step whose answer changes what the ceiling is
    judging.
    """
    adapters = get_adapters()
    # The radius is measured in a straight line, and that is correct as a
    # pre-filter: the great circle between two points is never longer than a
    # road between them, so a straight-line radius can only ever be too
    # generous. Nothing the road would have put inside it is dropped here --
    # only extra candidates come through, and the ceiling below removes them.
    # Routing first, to filter on road distance, would mean asking a public
    # service about the whole city to throw most of it away.
    nearby = adapters.maps.places_near(lat, lng, radius_km)
    matching = [place for place in nearby if not halal_only or place.halal]

    # One call for everything still standing. A 5 km radius holds a few dozen
    # places, well inside what OSRM's table service answers in one request, so
    # the whole search costs one round trip however many places it found.
    routed = await adapters.routing.road_metres(
        (lat, lng), [(place.lat, place.lng) for place in matching]
    )
    if len(routed) != len(matching):
        # An adapter that answered a different number of destinations than it
        # was asked about cannot be lined up with them, and pairing them off
        # anyway would put one place's distance on another place's fare. The
        # straight line is wrong by a known amount; that would be wrong by an
        # unknown one.
        routed = [None] * len(matching)

    evaluated = [
        evaluate_place(place, lat, lng, mode, room_sen, road_metres=metres)
        for place, metres in zip(matching, routed, strict=True)
    ]
    # The ceiling runs last, on the total the road produced. Applying it to a
    # straight-line total would admit places the user cannot actually afford --
    # the 3.7 km that is really 8.1 km of driving is RM12.05 of fare under a
    # ceiling it clears and RM20.39 in the car it does not.
    under_cap = (p for p in evaluated if p.total_sen <= cap_sen)
    return PlacesFound(
        places=tuple(sorted(under_cap, key=lambda p: p.total_sen)),
        nearby_count=len(nearby),
        matching_count=len(matching),
    )


class UnknownPlace(LookupError):
    """No place with that id sits within range of where the plan was built."""


def find_place(place_id: str, *, lat: float, lng: float, radius_km: float = 5.0) -> Place | None:
    """The place a plan row's id names, or None if nothing around here is it.

    Scoped to the same search the plan came from rather than to the whole
    curated set, and on purpose. An id is a handle on a row somebody was shown;
    one resolved from the other side of the city would put a place on today
    that never appeared in any list. The radius defaults to ``find_places``'s
    own, so an id that came out of a plan resolves back through it.
    """
    for place in get_adapters().maps.places_near(lat, lng, radius_km):
        if place.id == place_id:
            return place
    return None


# ── Adding a plan to today ────────────────────────────────────────────────────

# Every place the planner knows is somewhere to eat, so a planned outing is
# food. Travel is folded into the same row rather than split off into a second
# transport draft: the user tapped one price for one outing, and two rows to
# confirm separately is not what they added.
PLAN_CATEGORY = "food"

# The curated set carries a word, not a percentage. The word is turned into a
# figure here so that every client agrees on what "high" is worth, and so that
# none of them can quietly promote an estimate.
#
# All three sit well under what a read claims -- the receipt reader's own scans
# come in at 94 -- because a price band is a weaker thing than a total printed
# on a slip. Even "high" means the estimate is well founded, never that the bill
# will read RM12.50.
PLAN_CONFIDENCE: dict[str, int] = {"high": 70, "medium": 50, "low": 30}

# A band this module does not recognise is read as the least certain one. The
# alternative -- refusing it, or splitting the difference at "medium" -- would
# either lose the user's tap over a vocabulary change or state more certainty
# than anything actually supports.
UNKNOWN_BAND_CONFIDENCE = PLAN_CONFIDENCE["low"]

# Said on the draft itself, because the toast that announced it is gone by the
# time the user reaches Activity. Three things it has to carry: where it came
# from, that the price is an estimate rather than a bill, and -- the part the
# whole design rests on -- that nothing has happened to today's money yet.
PLAN_NOTE = (
    "Planned, not spent — this is an estimate from your day plan. "
    "Nothing counts against today until you confirm it."
)


def confidence_for(band: str) -> int:
    """The percentage a place's confidence band is worth on a draft."""
    return PLAN_CONFIDENCE.get(band, UNKNOWN_BAND_CONFIDENCE)


async def add_to_today(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    total_sen: int,
    confidence: str,
    today: date,
) -> TransactionView:
    """Put a planned outing on today's drafts. An intention, not a spend.

    A receipt says "I spent this"; a plan says "I intend to". Both are proposals
    until the user says otherwise, which is why this goes through
    ``create_transaction`` like every other capture path instead of writing a
    row of its own — and why adding one moves no figure. Drafts are excluded
    from every engine calculation, so safe-to-spend is exactly what it was until
    the user comes back and confirms they actually ate.

    ``total_sen`` is the whole outing, meal and travel together: it is the
    figure on the row that was tapped, and a draft for the meal alone would not
    be the thing the user thought they added.
    """
    return await create_transaction(
        session,
        user,
        merchant=name,
        amount_sen=total_sen,
        occurred_on=today,
        category=PLAN_CATEGORY,
        source=SOURCE_PLAN,
        confidence=confidence_for(confidence),
        note=PLAN_NOTE,
    )
