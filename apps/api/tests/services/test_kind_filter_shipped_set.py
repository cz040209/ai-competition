"""Adversarial checks written independently of the feature's own tests.

Runs against the SHIPPED KL set (189 places, 22 kinds) rather than the seven
place fixture, because the fixture is the world the feature was written to pass
in and the shipped file is the world it will run in.
"""

from __future__ import annotations

import pytest

from kira.adapters.fakes import KL_PLACES
from kira.services.day_plan import (
    find_places,
    kind_key,
    known_kinds,
    price_landscape,
    resolve_kind,
)

# Bukit Bintang, dense enough that a 5 km radius holds most of the set.
BB = {"lat": 3.1466, "lng": 101.7113}
# Sri Petaling, far enough south that the radius holds a different slice.
SP = {"lat": 3.0680, "lng": 101.6890}

MODES = ("walk", "transit", "ride")


class TestTheVocabularyCannotBeEmpty:
    def test_the_derivation_actually_produced_something(self):
        assert len(known_kinds()) >= 10, known_kinds()
        assert all(k.strip() for k in known_kinds())

    def test_the_tool_description_is_the_derivation_and_not_a_copy(self):
        from kira.agent.tools.day_plan import PlanArgs

        described = PlanArgs.model_fields["kind"].description or ""
        for kind in known_kinds():
            assert kind in described, kind
        # Nothing in the description that is not a real kind, spelled as a
        # capitalised word in the comma list.
        listed = described.split("carry: ")[1].split(". Anything")[0]
        assert [w.strip() for w in listed.split(",")] == list(known_kinds())


class TestTheFilterNeverWidens:
    @pytest.mark.parametrize("bad", ["hawker", "healthy", "street food", "zzzz", "noodle soup"])
    async def test_a_nonsense_kind_returns_nothing(self, bad):
        found = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000, kind=bad
        )
        assert found.places == (), (bad, len(found.places))
        assert found.kind_count == 0
        # And the cause is readable: there IS food here.
        assert found.nearby_count > 0
        assert found.matching_count > 0
        # The landscape still says what is there.
        assert found.landscape

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    async def test_a_blank_kind_is_no_filter_not_an_empty_one(self, blank):
        wide = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000
        )
        found = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000, kind=blank
        )
        assert [p.id for p in found.places] == [p.id for p in wide.places]
        assert found.kind_count == wide.kind_count == wide.matching_count

    async def test_a_kind_in_the_data_but_not_in_the_radius_returns_nothing(self):
        """The case the feature's own tests skip.

        Find a kind the shipped set carries that has no place inside the radius
        of one origin but does inside another, and assert the near-empty side
        comes back empty rather than widening to everything.
        """
        wide = await find_places(
            **SP, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000
        )
        in_range = {kind_key(p.kind) for p in wide.places}
        absent = [k for k in known_kinds() if kind_key(k) not in in_range]
        assert absent, "pick a sparser origin; every kind is in range here"
        assert wide.places, "origin must have SOME food or the test proves nothing"
        for kind in absent:
            found = await find_places(
                **SP,
                mode="walk",
                halal_only=False,
                cap_sen=1_000_000,
                room_sen=1_000_000,
                kind=kind,
            )
            assert found.places == (), (kind, len(found.places))
            assert found.kind_count == 0
            assert found.matching_count == wide.matching_count

    async def test_a_kind_that_exists_only_outside_the_halal_set_is_not_widened(self):
        found = await find_places(
            **BB, mode="walk", halal_only=True, cap_sen=1_000_000, room_sen=1_000_000, kind="Pizza"
        )
        assert all(p.halal and kind_key(p.kind) == "pizza" for p in found.places)

    async def test_the_ceiling_and_the_kind_compose_rather_than_cancel(self):
        found = await find_places(
            **BB, mode="ride", halal_only=False, cap_sen=1500, room_sen=5000, kind="Japanese"
        )
        assert all(kind_key(p.kind) == "japanese" and p.total_sen <= 1500 for p in found.places)


class TestTheLandscapeAgreesWithTheList:
    """Recomputed here from the places themselves, not read back off the API."""

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("halal", [True, False])
    @pytest.mark.parametrize("origin", [BB, SP])
    async def test_every_row_matches_an_independent_computation(self, mode, halal, origin):
        # Cap wide open so `places` IS the evaluated set and the landscape can
        # be checked against it row for row.
        found = await find_places(
            **origin, mode=mode, halal_only=halal, cap_sen=10_000_000, room_sen=100_000
        )
        expected: dict[str, tuple[int, int]] = {}
        for place in found.places:
            key = kind_key(place.kind)
            count, cheapest = expected.get(key, (0, place.total_sen))
            expected[key] = (count + 1, min(cheapest, place.total_sen))

        actual = {
            kind_key(row.kind): (row.count, row.cheapest_total_sen) for row in found.landscape
        }
        assert actual == expected, (mode, halal, origin)
        # Ordered cheapest first, and the tie-break is stable.
        prices = [row.cheapest_total_sen for row in found.landscape]
        assert prices == sorted(prices)
        # And the row's own spelling is one a place in that group actually has.
        for row in found.landscape:
            group = [p.kind for p in found.places if kind_key(p.kind) == kind_key(row.kind)]
            assert row.kind in group

    async def test_the_landscape_is_unchanged_by_the_kind_asked_for(self):
        wide = await find_places(
            **BB, mode="ride", halal_only=False, cap_sen=1_000_000, room_sen=100_000
        )
        narrow = await find_places(
            **BB,
            mode="ride",
            halal_only=False,
            cap_sen=1_000_000,
            room_sen=100_000,
            kind="Japanese",
        )
        assert wide.landscape == narrow.landscape

    async def test_the_landscape_is_unchanged_by_the_ceiling(self):
        wide = await find_places(
            **BB, mode="ride", halal_only=False, cap_sen=1_000_000, room_sen=100_000
        )
        tiny = await find_places(**BB, mode="ride", halal_only=False, cap_sen=1, room_sen=100_000)
        assert tiny.places == ()
        assert wide.landscape == tiny.landscape

    async def test_the_landscape_does_change_with_the_halal_filter(self):
        wide = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=100_000
        )
        halal = await find_places(
            **BB, mode="walk", halal_only=True, cap_sen=1_000_000, room_sen=100_000
        )
        assert {r.kind for r in halal.landscape} <= {r.kind for r in wide.landscape}
        for row in halal.landscape:
            twin = next(r for r in wide.landscape if r.kind == row.kind)
            assert row.count <= twin.count
            assert row.cheapest_total_sen >= twin.cheapest_total_sen

    def test_the_landscape_of_nothing_is_empty(self):
        assert price_landscape([]) == ()


class TestMoneyStaysInteger:
    @pytest.mark.parametrize("mode", MODES)
    async def test_no_float_reaches_a_money_field(self, mode):
        found = await find_places(
            **BB, mode=mode, halal_only=False, cap_sen=1_000_000, room_sen=7777
        )
        source = {p.id: p for p in KL_PLACES}
        for place in found.places:
            for field in ("travel_sen", "total_sen", "minutes"):
                value = getattr(place, field)
                assert type(value) is int, (field, type(value))
            estimate = source[place.id].estimate.sen
            assert type(estimate) is int
            assert place.total_sen == estimate + place.travel_sen
        for row in found.landscape:
            assert type(row.cheapest_total_sen) is int
            assert type(row.count) is int


class TestResolveKind:
    def test_it_never_falls_back_to_a_neighbour(self):
        for bad in ("chi", "jap", "tea", "noo", "food", "eat", "nice", "hawker", "s"):
            assert resolve_kind(bad) is None, bad

    def test_every_shipped_kind_round_trips(self):
        for kind in known_kinds():
            assert resolve_kind(kind) == kind
            assert resolve_kind(kind.upper()) == kind
            assert resolve_kind(f"  {kind.lower()}  ") == kind

    def test_it_does_not_collapse_two_real_kinds_onto_one_key(self):
        keys = [kind_key(k) for k in known_kinds()]
        assert len(set(keys)) == len(keys), sorted(keys)


class TestTheShippedDataItself:
    def test_every_place_carries_a_kind_the_vocabulary_has(self):
        for place in KL_PLACES:
            assert resolve_kind(place.kind) == place.kind, place


class TestAKindWordInsideAPhrase:
    """People name food the way they eat it, not the way a column is headed.

    "fried chicken" is the dish; ``Chicken`` is the heading. Reading only the
    whole phrase sent "i want eat fried chicken" to the balance instead of the
    planner, which is the one sentence this feature exists for.
    """

    def test_an_adjective_in_front_does_not_hide_the_kind(self):
        assert resolve_kind("fried chicken") == "Chicken"
        assert resolve_kind("japanese food") == "Japanese"

    def test_a_two_word_kind_survives_a_trailing_word(self):
        assert resolve_kind("middle eastern food") == "Middle Eastern"

    def test_a_phrase_carrying_no_kind_still_resolves_to_nothing(self):
        # The rule this must not break: a word the data has no column for is
        # not a filter, because emptying a list for an unactionable reason is
        # worse than ignoring the word.
        for phrase in ("hawker", "something nice", "anywhere cheap", "a treat"):
            assert resolve_kind(phrase) is None, phrase

    def test_it_still_refuses_a_fragment_or_a_near_miss(self):
        # "chi" reaching both Chicken and Chinese, or "tea" reaching Steakhouse,
        # answers a question nobody asked.
        for fragment in ("chi", "tea", "steak", "noodl"):
            assert resolve_kind(fragment) is None, fragment
