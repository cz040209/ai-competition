"""What build_day_plan hands the model, which is the only thing it can quote.

The places come from the ``place_world`` fixture, not the shipped KL set: the
screen and the Butler have to tell the same story about an empty list, and that
agreement is what these tests are for -- not which places OpenStreetMap had.
"""

from __future__ import annotations

import pytest

from kira.agent.tools import ToolContext
from kira.agent.tools.day_plan import SPECS, PlanArgs, _build
from kira.db.models import TXN_CONFIRMED, Transaction
from kira.money import Money
from kira.services import day_plan as day_plan_service
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


class TestAskingForOneKindOfFood:
    """The planner could not be asked what sort of food, so it was a price
    filter wearing a recommendation's clothes. Nothing in the arguments carried
    "noodles", so no prompt could ever have honoured it."""

    async def test_the_kind_reaches_the_search(self, session, user, today, place_world):
        context = await context_for(session, user, today)
        result = await _build(
            context, PlanArgs(cap_sen=100_000, kind="Cafe", **place_world.origin)
        )

        assert [p["name"] for p in result.value["places"]] == [
            place_world.cheap.name,
            place_world.second_cafe.name,
        ]
        assert result.value["kind"] == "Cafe"

    async def test_a_kind_that_matches_nothing_comes_back_empty(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(
            context, PlanArgs(cap_sen=100_000, kind="Hawker", **place_world.origin)
        )

        # Never the whole list back. A model handed seven places after asking
        # for one kind would read them as the answer and name one of them.
        assert result.value["places"] == []
        assert result.value["kind_count"] == 0
        assert result.value["matching_count"] == 7
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Nearby places"] == "7 within range, none of them Hawker"
        assert "ceiling" not in evidence["Nearby places"]

    async def test_the_argument_names_the_kinds_the_data_actually_carries(self):
        # The description is the whole mechanism: the model reads it to decide
        # what to pass, and a word that is not in the set matches nothing. So it
        # has to be the set, derived, rather than a list typed out beside it.
        described = PlanArgs.model_fields["kind"].description or ""
        for kind in day_plan_service.known_kinds():
            assert kind in described
        assert "Mamak" in described and "Noodles" in described
        # And it has to say what happens to a word that is not one of them,
        # or the model will invent a category and read the empty list as a
        # verdict on the neighbourhood.
        assert "matches nothing" in described


class TestWhatTheToolAsksTheModelToDoWithIt:
    """The description is the whole of the online mechanism. Handed twelve
    places and no instruction, a model summarises them -- "all five halal
    options, from RM13 to RM14, fit comfortably" -- which names nobody and
    answers nothing."""

    def test_it_asks_for_one_place_chosen_and_justified(self):
        described = {spec.name: spec.description for spec in SPECS}["build_day_plan"]
        assert "Recommend one place" in described
        # Against what: the day, a goal, and anything remembered about them.
        assert "today's room" in described and "remember" in described
        # And the tool that carries the recommendation through, so the offer is
        # made in the same breath rather than waited for.
        assert "add_place_to_today" in described
        # The line the evidence panel rests on.
        assert "never author one" in described


class TestHowMuchTheModelIsGiven:
    """Five cheapest was a list nothing could be chosen from: the model saw the
    bottom of the price order and nothing else, so "the cheapest one" was the
    only recommendation available to it."""

    async def test_it_hands_back_twelve_at_most_in_the_order_they_were_sorted(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        with serving(places=place_world.crowd):
            result = await _build(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        places = result.value["places"]
        assert len(places) == 12
        totals = [p["total_sen"] for p in places]
        assert totals == sorted(totals)
        # The thirteenth is the dearest, and it is the one left out.
        assert totals == [1100 + step * 100 for step in range(12)]
        # Said outright, so the model knows the list was cut rather than ended.
        assert result.value["shown_count"] == 12
        assert result.value["total_under_cap"] == 13

    async def test_a_shorter_list_is_not_padded_and_says_its_own_length(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        assert result.value["shown_count"] == len(result.value["places"]) == 7
        assert result.value["total_under_cap"] == 7


class TestThePriceLandscape:
    """The change that turns "nothing under RM15" into "RM15 reaches the mamak
    and the food courts; the Japanese places start at RM42, which is past
    today's room anyway"."""

    async def test_it_states_every_kind_in_range_with_the_cheapest_of_each(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        rows = {row["kind"]: row for row in result.value["price_landscape"]}
        assert set(rows) == {"Cafe", "Mamak", "Chinese", "Japanese", "Western", "Noodles"}
        assert rows["Cafe"] == {"kind": "Cafe", "count": 2, "cheapest_total_sen": 900}
        assert rows["Japanese"]["cheapest_total_sen"] == 5000

    async def test_it_cannot_disagree_with_the_places_beside_it(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        rows = {row["kind"]: row for row in result.value["price_landscape"]}
        for place in result.value["places"]:
            assert rows[place["kind"]]["cheapest_total_sen"] <= place["total_sen"]
        for kind, row in rows.items():
            listed = [p["total_sen"] for p in result.value["places"] if p["kind"] == kind]
            assert min(listed) == row["cheapest_total_sen"]

    async def test_a_ceiling_that_admits_nothing_still_states_what_is_there(
        self, session, user, today, place_world
    ):
        # The single reason for the whole thing. With the list empty, this is
        # all the model has to answer with, and without it the only honest reply
        # left is an apology.
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=500, **place_world.origin))

        assert result.value["places"] == []
        cheapest = result.value["price_landscape"][0]
        assert cheapest == {"kind": "Cafe", "count": 2, "cheapest_total_sen": 900}
        assert len(result.value["price_landscape"]) == 6

    async def test_it_is_all_money_in_whole_sen(self, session, user, today, place_world):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        for row in result.value["price_landscape"]:
            assert isinstance(row["cheapest_total_sen"], int)


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


class TestTheNearestPlacesAboveTheCeiling:
    """What the model is handed when the ceiling admitted nothing at all.

    A model given an empty list can only apologise. Given the cheapest few
    places just above the ceiling, and told plainly that is what they are, it
    can say the useful thing instead -- without either of them being counted
    among the places that fitted.
    """

    async def test_a_ceiling_below_everything_hands_over_the_nearest(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=500, **place_world.origin))

        assert result.value["places"] == []
        assert [p["name"] for p in result.value["nearest_over_cap"]] == [
            place_world.cheap.name,
            place_world.mid.name,
            place_world.near_non_halal.name,
        ]
        # Every one of them over the ceiling, and banded so on the row, so no
        # reading of this payload has them fitting.
        assert all(p["band"] == "over" for p in result.value["nearest_over_cap"])
        assert all(p["total_sen"] > 500 for p in result.value["nearest_over_cap"])
        # And they are not folded into any count of what did fit.
        assert result.value["shown_count"] == 0
        assert result.value["total_under_cap"] == 0

    async def test_the_evidence_names_the_closest_and_how_far_over_it_is(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=500, **place_world.origin))

        evidence = dict(row.as_pair() for row in result.evidence)
        assert "none under the ceiling" in evidence["Nearby places"]
        # Labelled as above the ceiling rather than as the cheapest nearby: a
        # reader skimming the panel alone must not take it for one that fitted.
        assert evidence["Closest above the ceiling"] == f"{place_world.cheap.name} at RM9.00"
        assert evidence["Over the ceiling by"] == "RM4.00"

    async def test_a_ceiling_that_admits_some_places_hands_over_none(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await _build(context, PlanArgs(cap_sen=1000, **place_world.origin))

        assert [p["name"] for p in result.value["places"]] == [place_world.cheap.name]
        assert result.value["nearest_over_cap"] == []
        evidence = dict(row.as_pair() for row in result.evidence)
        assert "Closest above the ceiling" not in evidence

    async def test_an_empty_list_no_ceiling_caused_hands_over_none(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        out_of_range = await _build(
            context, PlanArgs(cap_sen=100_000, **place_world.out_of_range)
        )
        no_halal = await _build(
            context,
            PlanArgs(cap_sen=100_000, halal_only=True, **place_world.lone_non_halal),
        )
        for result in (out_of_range, no_halal):
            assert result.value["places"] == []
            assert result.value["nearest_over_cap"] == []

    def test_the_description_tells_the_model_never_to_present_one_as_fitting(self):
        spec = next(spec for spec in SPECS if spec.name == "build_day_plan")
        assert "nearest_over_cap" in spec.description
        assert "Never present one as fitting" in spec.description
