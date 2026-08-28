"""Turn nearby curated places into money-constrained outings.

Ports kira-prototype.jsx's evaluate() (line 661): cost, travel time, and how
much of today's safe-to-spend each outing would use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kira.adapters.geo import haversine_km
from kira.adapters.protocols import Place
from kira.adapters.registry import get_adapters
from kira.money import round_half_up

Mode = Literal["walk", "transit", "ride"]
Band = Literal["ok", "tight", "over"]


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
    km: float
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
    place: Place, origin_lat: float, origin_lng: float, mode: Mode, room_sen: int
) -> EvaluatedPlace:
    """room_sen is always today's real safe-to-spend -- it is NOT the same as
    the caller's display cap_sen, which only filters what is shown."""
    km = haversine_km(origin_lat, origin_lng, place.lat, place.lng)
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
        km=km,
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


def find_places(
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
    share/band and must never be swapped with cap_sen."""
    nearby = get_adapters().maps.places_near(lat, lng, radius_km)
    matching = [place for place in nearby if not halal_only or place.halal]
    evaluated = (evaluate_place(place, lat, lng, mode, room_sen) for place in matching)
    under_cap = (p for p in evaluated if p.total_sen <= cap_sen)
    return PlacesFound(
        places=tuple(sorted(under_cap, key=lambda p: p.total_sen)),
        nearby_count=len(nearby),
        matching_count=len(matching),
    )
