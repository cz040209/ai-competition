"""What build_day_plan hands the model, which is the only thing it can quote.

The places come from the ``place_world`` fixture, not the shipped KL set: the
screen and the Butler have to tell the same story about an empty list, and that
agreement is what these tests are for -- not which places OpenStreetMap had.
"""

from __future__ import annotations

import pytest

from kira.agent.tools import ToolContext
from kira.agent.tools.day_plan import PlanArgs, _build
from kira.db.models import TXN_CONFIRMED, Transaction
from kira.money import Money
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot
from tests.conftest import StubRouting, serving


async def context_for(session, user, today) -> ToolContext:
    return ToolContext(
        session=session,
        user=user,
        today=today,
        snapshot=await load_snapshot(session, user, today),
        dashboard=await today_dashboard(session, user, today),
    )


async def spend_out(session, user, today) -> None:
    session.add(
        Transaction(
            user_id=user.id,
            merchant="Blowout",
            amount=Money(500_000, user.currency),
            occurred_on=today,
            category="food",
            status=TXN_CONFIRMED,
            source="manual",
            note="",
        )
    )
    await session.commit()


@pytest.fixture
async def user(butler):
    return butler[0]


class TestFiguresGivenToTheModel:
    async def test_the_room_and_the_cap_are_stated_outright(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(**place_world.origin))

        assert result.value["room_sen"] == context.dashboard.safe_today_sen
        assert result.value["cap_sen"] == context.dashboard.safe_today_sen
        assert result.value["places"]

    async def test_a_spent_out_day_carries_no_share_to_read_as_a_percentage(
        self, session, user, today, place_world
    ):
        await spend_out(session, user, today)
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=5000, **place_world.origin))

        # The model is told the room is nil and given nothing that could be
        # narrated as "200% of your room" or divided back into a room.
        assert result.value["room_sen"] == 0
        assert result.value["places"]
        for place in result.value["places"]:
            assert place["share"] is None
            assert place["band"] == "over"

    async def test_the_evidence_names_the_room_the_bands_were_judged_on(
        self, session, user, today, place_world
    ):
        await spend_out(session, user, today)
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=5000, **place_world.origin))

        assert dict(row.as_pair() for row in result.evidence)["Safe to spend today"] == "RM0.00"

    async def test_a_ceiling_that_matches_nothing_still_states_the_room(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=1, **place_world.origin))

        assert result.value["places"] == []
        assert dict(row.as_pair() for row in result.evidence)["Safe to spend today"] == "RM52.97"


class TestWhatTheModelIsToldAboutDistance:
    """The Butler quotes these figures out loud, so it has to know which of the
    two distances produced them. A model handed only a fare will read it as a
    price, and a straight-line fare in KL is not one."""

    async def test_each_place_carries_its_basis_and_its_address(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(
            context, PlanArgs(mode="ride", cap_sen=100_000, **place_world.origin)
        )

        assert result.value["places"]
        for place in result.value["places"]:
            assert place["distance_basis"] in ("road", "straight_line")
            assert place["address"]

    async def test_a_straight_line_search_is_labelled_as_one_in_the_evidence(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(
            context, PlanArgs(mode="ride", cap_sen=100_000, **place_world.origin)
        )

        evidence = dict(row.as_pair() for row in result.evidence)
        # Beside "Total cost", so the figure above it cannot read as a quote.
        assert "straight line" in evidence["Distance measured"]

    async def test_a_routed_search_says_by_road_and_prices_on_it(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        # Kopi Kaki is 50 m away and free either way, so it is the cheapest and
        # the row is about it: 900 m of road, which is a fare rather than
        # "already there".
        with serving(StubRouting({"w1": 900.0})):
            result = await _build(
                context, PlanArgs(mode="ride", cap_sen=100_000, **place_world.origin)
            )

        best = result.value["places"][0]
        assert best["name"] == place_world.cheap.name
        assert best["distance_basis"] == "road"
        assert best["road_km"] == 0.9
        assert best["travel_sen"] == 671  # RM5.00 + 0.9 km at RM1.90
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Distance measured"] == "0.9 km by road"


class TestWhyTheListIsEmpty:
    """All three empty lists look the same to the model, so the two counts are
    what keep it from telling the user to raise a ceiling that is not the
    problem. The screen and the Butler have to agree about which cause it was:
    a fix that reached only one of them would just move the wrong story."""

    async def test_a_ceiling_too_low_leaves_places_in_range(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=1, **place_world.origin))

        assert result.value["places"] == []
        assert result.value["nearby_count"] > 0
        assert result.value["matching_count"] > 0
        evidence = dict(row.as_pair() for row in result.evidence)
        assert "none under the ceiling" in evidence["Nearby places"]

    async def test_out_of_range_leaves_nothing_in_range(self, session, user, today, place_world):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=100_000, **place_world.out_of_range))

        assert result.value["places"] == []
        assert result.value["nearby_count"] == 0
        assert result.value["matching_count"] == 0
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Nearby places"] == "none within range"

    async def test_a_halal_filter_that_admits_nothing_is_not_narrated_as_a_ceiling(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(
            context,
            PlanArgs(cap_sen=100_000, halal_only=True, **place_world.lone_non_halal),
        )

        assert result.value["places"] == []
        assert result.value["nearby_count"] == 1
        assert result.value["matching_count"] == 0
        evidence = dict(row.as_pair() for row in result.evidence)
        # The ceiling here is RM1,000 and the place costs RM20. A model handed
        # only "1 within range" would reach for the ceiling, which is the one
        # thing the user cannot fix from here.
        assert evidence["Nearby places"] == "1 within range, none of them halal"
        assert "ceiling" not in evidence["Nearby places"]
