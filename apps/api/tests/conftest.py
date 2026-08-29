"""Shared fixtures. Database tests run against in-memory SQLite without Docker."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

os.environ.setdefault("DEMO_TODAY", "2026-09-03")
os.environ.setdefault("JWT_SECRET", "test-secret-for-kira-auth-tests-123456")
# A developer's .env carries a real DashScope key, which would send the Butler's
# HTTP tests over the network to a live model and make them pass or fail on what
# it happened to say. The offline model is the one the golden tests already pin.
os.environ.setdefault("BUTLER_OFFLINE", "true")
# Same reasoning for the router: left on, every day-plan test would put a real
# HTTP request to a volunteer-run public service on the critical path of the
# suite, and its fares would depend on what OSRM said that morning. The fixture
# below hands the planner a router that answers nothing, and the tests that
# care about road distance hand it one that answers known metres.
os.environ.setdefault("ROUTING_ENABLED", "false")

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from kira.adapters import registry
from kira.adapters.fakes import FakeMaps, NoRouting
from kira.adapters.protocols import Place, RoutingAdapter
from kira.adapters.registry import get_adapters
from kira.db.base import Base
from kira.db.session import get_session
from kira.money import Money


@pytest.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
async def client(session) -> AsyncGenerator[AsyncClient, None]:
    from kira.api.app import create_app

    app = create_app()

    async def override() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- the day planner's small fixed world ------------------------------------

# One degree of latitude on the sphere haversine_km measures against, so a place
# offset this way sits exactly the stated number of kilometres from the origin.
_KM_PER_DEGREE_LAT = 6371.0 * math.pi / 180

# Suria KLCC, which is also what the day-plan tool falls back to when the user
# has not shared a location.
_ORIGIN_LAT = 3.1577
_ORIGIN_LNG = 101.7120


def _north(km: float) -> float:
    """A latitude exactly ``km`` north of the origin on its meridian, or south
    of it for a negative ``km``."""
    return _ORIGIN_LAT + km / _KM_PER_DEGREE_LAT


@dataclass(frozen=True, slots=True)
class PlaceWorld:
    """Five places with round prices at known distances, and the origins to
    search them from. Each origin is a dict so it can be splatted straight into
    ``find_places``, the endpoint's query params, or ``PlanArgs``.
    """

    places: tuple[Place, ...]
    origin: dict[str, float]
    out_of_range: dict[str, float]
    lone_non_halal: dict[str, float]
    cheap: Place
    mid: Place
    near_non_halal: Place
    pricey: Place
    far_non_halal: Place


_CHEAP = Place(
    "w1",
    "Kopi Kaki",
    "Cafe",
    _north(0.05),
    _ORIGIN_LNG,
    Money(900),
    "high",
    True,
    "50 m away, inside the no-fare radius.",
    address="1 Jalan Satu, Kuala Lumpur",
)
_MID = Place(
    "w2",
    "Mamak Dua",
    "Mamak",
    _north(0.5),
    _ORIGIN_LNG,
    Money(1250),
    "high",
    True,
    "500 m away.",
    address="2 Jalan Dua, Kuala Lumpur",
)
_NEAR_NON_HALAL = Place(
    "w3",
    "Bak Kut Teh Tiga",
    "Chinese",
    _north(-1.0),
    _ORIGIN_LNG,
    Money(1600),
    "medium",
    False,
    "1 km away.",
    address="3 Jalan Tiga, Kuala Lumpur",
)
_PRICEY = Place(
    "w4",
    "Omakase Empat",
    "Japanese",
    _north(2.0),
    _ORIGIN_LNG,
    Money(5000),
    "low",
    True,
    "2 km away, and the most expensive of the five.",
    address="4 Jalan Empat, Kuala Lumpur",
)
_FAR_NON_HALAL = Place(
    "w5",
    "Chophouse Lima",
    "Western",
    _north(-4.0),
    _ORIGIN_LNG,
    Money(2000),
    "medium",
    False,
    "4 km away, and the only one a search from the south can reach.",
    address="5 Jalan Lima, Kuala Lumpur",
)

PLACE_WORLD = PlaceWorld(
    places=(_CHEAP, _MID, _NEAR_NON_HALAL, _PRICEY, _FAR_NON_HALAL),
    origin={"lat": _ORIGIN_LAT, "lng": _ORIGIN_LNG},
    # George Town, Penang: ~294 km from all five.
    out_of_range={"lat": 5.4141, "lng": 100.3288},
    # 4.9 km further south than Chophouse Lima, which puts that one place inside
    # the 5 km radius and the other four well outside it. It is not halal, so
    # the halal toggle is the only thing that can empty a search from here.
    lone_non_halal={"lat": _north(-8.9), "lng": _ORIGIN_LNG},
    cheap=_CHEAP,
    mid=_MID,
    near_non_halal=_NEAR_NON_HALAL,
    pricey=_PRICEY,
    far_non_halal=_FAR_NON_HALAL,
)


class StubRouting:
    """A router with a fixed, per-place answer, given in road metres by id.

    Deliberately not derived from the coordinates: the whole point of routing
    is that the road is longer than the line between its ends, so a stub that
    computed the straight line and called it a road would prove nothing. Any
    place not named is left unrouted, which is how a partly-answered search is
    written.
    """

    def __init__(
        self, metres_by_id: dict[str, float], places: tuple[Place, ...] = PLACE_WORLD.places
    ) -> None:
        self._by_coordinate = {
            (place.lat, place.lng): metres_by_id.get(place.id) for place in places
        }
        # What the planner actually asked for, so a test can assert it was one
        # call covering every candidate rather than one call per place.
        self.calls: list[tuple[tuple[float, float], list[tuple[float, float]]]] = []

    async def road_metres(
        self, origin: tuple[float, float], destinations: Sequence[tuple[float, float]]
    ) -> list[float | None]:
        destinations = [tuple(point) for point in destinations]
        self.calls.append((origin, list(destinations)))
        return [self._by_coordinate.get(point) for point in destinations]


@contextmanager
def serving(
    routing: RoutingAdapter | None = None, places: tuple[Place, ...] = PLACE_WORLD.places
) -> Iterator[PlaceWorld]:
    """Point the adapter registry at the fixed world and a chosen router.

    Defaults to ``NoRouting``: no test in this suite reaches the network, and
    the planner's straight-line fallback is the behaviour most of them are
    about anyway.
    """
    # get_adapters is lru_cache'd, so patching what it builds from only bites
    # once the cache is dropped -- and the shipped set and the configured router
    # only come back for the next test if it is dropped again once the patch is
    # off.
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(registry, "FakeMaps", lambda: FakeMaps(places))
            patch.setattr(registry, "choose_routing", lambda: routing or NoRouting())
            get_adapters.cache_clear()
            yield PLACE_WORLD
    finally:
        # Cleared again with the patches off, so a test that failed mid-way
        # cannot leave the fixed world cached for whatever runs next.
        get_adapters.cache_clear()


@pytest.fixture
def place_world():
    """Serve the fixed world above in place of the 189 shipped KL places.

    A day-plan test that named a real place would be asserting on a data file
    regenerated from OpenStreetMap, and would go red on the next refresh with
    nothing about the planner having changed.
    """
    with serving() as world:
        yield world
