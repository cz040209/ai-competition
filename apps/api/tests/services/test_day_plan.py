"""find_places() ports kira-prototype.jsx's evaluate() (line 661).

Every scenario runs against the ``place_world`` fixture, not the shipped KL set:
that file is generated from OpenStreetMap and refreshed, so a test naming a real
place would be pinning data rather than behaviour.

The fixture serves ``NoRouting``, so unless a test says otherwise every distance
here is the straight line and every place says so. The road-distance scenarios
below opt in with ``serving(StubRouting(...))``.
"""

from __future__ import annotations

from kira.adapters.protocols import Place
from kira.db.models import SOURCE_PLAN, TXN_DRAFT
from kira.engine import safe_to_spend
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.day_plan import (
    PLAN_CONFIDENCE,
    add_to_today,
    confidence_for,
    evaluate_place,
    find_places,
)
from kira.services.snapshot import load_snapshot
from kira.services.transactions import confirm_draft, list_activity
from tests.conftest import StubRouting, serving


class TestBandThresholds:
    """Walk mode has base=0 and per_km=0, so total_sen == the place's estimate,
    which makes the ok/tight/over boundaries easy to reason about directly."""

    async def test_ok_tight_and_over_all_appear(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=2000,
            )
        ).places
        by_name = {p.name: p for p in places}

        # 900 / 2000 = 0.45 <= 0.6
        assert by_name[place_world.cheap.name].share == 0.45
        assert by_name[place_world.cheap.name].band == "ok"

        # 1250 / 2000 = 0.625, in (0.6, 1.0]
        assert by_name[place_world.mid.name].band == "tight"

        # 5000 / 2000 = 2.5 > 1.0
        assert by_name[place_world.pricey.name].band == "over"

    async def test_band_boundaries_are_inclusive_of_their_upper_edge(self, place_world):
        # A place whose total is exactly 60% of room lands in "ok", not "tight".
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=1500,  # 900 / 1500 = 0.6 exactly
            )
        ).places
        cheap = next(p for p in places if p.name == place_world.cheap.name)
        assert cheap.share == 0.6
        assert cheap.band == "ok"


class TestHalalFilter:
    async def test_excludes_non_halal_places_when_requested(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=True,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        assert places  # sanity: the filter did not empty the whole set
        assert all(p.halal for p in places)
        names = {p.name for p in places}
        assert place_world.near_non_halal.name not in names
        assert place_world.far_non_halal.name not in names

    async def test_includes_non_halal_places_by_default(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        names = {p.name for p in places}
        assert place_world.near_non_halal.name in names


class TestCapFilter:
    async def test_a_place_above_the_cap_is_excluded(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=1500,  # below Omakase Empat's 5000
                room_sen=100_000,
            )
        ).places
        names = {p.name for p in places}
        assert place_world.pricey.name not in names
        assert all(p.total_sen <= 1500 for p in places)


class TestSortOrder:
    async def test_results_are_sorted_ascending_by_total_sen(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        totals = [p.total_sen for p in places]
        assert totals == sorted(totals)


class TestRoomIsNotCap:
    """room_sen (today's real safe-to-spend) drives share/band. cap_sen only
    filters what is shown. Swapping the two is the bug this guards against."""

    async def test_a_place_can_be_shown_by_cap_but_still_be_over_room(self, place_world):
        # Mamak Dua costs 1250 sen (walk mode adds no travel cost). cap_sen=2100
        # admits it into the results; room_sen=1000 means it actually costs more
        # than the user's whole safe-to-spend for today. If the implementation
        # ever computed share against cap_sen instead of room_sen, 1250 / 2100 =
        # 0.595 would read as "ok" -- the correct answer, computed against
        # room_sen, is "over" (1250 / 1000 = 1.25).
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=2100,
                room_sen=1000,
            )
        ).places
        mid = next(p for p in places if p.name == place_world.mid.name)
        assert mid.total_sen == 1250
        assert mid.share == 1.25
        assert mid.band == "over"

    async def test_raising_cap_above_room_still_yields_tight_and_over_entries(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,  # generous cap: nothing is filtered out by price
                room_sen=1000,  # tight room: most places cost more than this
            )
        ).places
        bands = {p.band for p in places}
        assert "tight" in bands or "over" in bands
        assert any(p.total_sen > 1000 for p in places), (
            "a place costing more than room_sen must still appear when cap_sen allows it"
        )


class TestNoRoomLeft:
    """A day already spent out has no share to report, and saying so is the
    only thing that keeps a real share of 2.0 tellable from an absent one."""

    async def test_a_nil_room_yields_no_share_and_every_place_over(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=0,
            )
        ).places
        assert places
        for place in places:
            assert place.share is None
            assert place.band == "over"

    async def test_a_genuine_share_of_two_is_still_reported(self, place_world):
        # Kopi Kaki costs 900 sen against 450 sen of room: exactly the ratio the
        # old zero-room stand-in was indistinguishable from.
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=450,
            )
        ).places
        cheap = next(p for p in places if p.name == place_world.cheap.name)
        assert cheap.share == 2.0


class TestNearbyCount:
    """An empty result has three causes, and only the two counts tell them
    apart: a ceiling the user can move, a filter the user can switch off, or a
    distance neither of those will close."""

    async def test_it_counts_what_the_radius_held_before_the_filters_ran(self, place_world):
        unfiltered = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert unfiltered.nearby_count == len(unfiltered.places)

        filtered = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=1000,  # admits only Kopi Kaki's 900
            room_sen=100_000,
        )
        assert len(filtered.places) < len(unfiltered.places)
        assert filtered.nearby_count == unfiltered.nearby_count

    async def test_a_ceiling_that_admits_nothing_still_counts_the_places_in_range(
        self, place_world
    ):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=1,
            room_sen=100_000,
        )
        assert found.places == ()
        assert found.nearby_count > 0

    async def test_it_is_nil_where_the_seed_data_does_not_reach(self, place_world):
        found = await find_places(
            **place_world.out_of_range,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert found.places == ()
        assert found.nearby_count == 0
        assert found.matching_count == 0


class TestMatchingCount:
    """The third cause. A ceiling the user cannot see past is one thing; a
    halal toggle they set themselves is another, and dragging the ceiling for
    it is advice that cannot work."""

    async def test_it_counts_what_survived_the_halal_filter_not_the_ceiling(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=1,  # admits nothing at all
            room_sen=100_000,
        )
        assert found.places == ()
        # Two of the five places in range are not halal, and the ceiling of one
        # sen is what emptied the rest -- which is the count that says so.
        assert found.nearby_count == 5
        assert found.matching_count == 3

    async def test_the_halal_filter_alone_can_empty_a_generous_ceiling(self, place_world):
        # 4.9 km south of Chophouse Lima: it is the one place in range, and it
        # is not halal. No ceiling reaches it, because the ceiling is not what
        # is holding it back.
        found = await find_places(
            **place_world.lone_non_halal,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert found.places == ()
        assert found.nearby_count == 1
        assert found.matching_count == 0

        # Same spot, same ceiling, halal off: the place was there all along.
        relaxed = await find_places(
            **place_world.lone_non_halal,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert [p.name for p in relaxed.places] == [place_world.far_non_halal.name]
        assert relaxed.matching_count == 1

    async def test_the_counts_nest(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=1000,  # admits only Kopi Kaki's 900
            room_sen=100_000,
        )
        assert found.nearby_count >= found.matching_count >= len(found.places)
        assert found.nearby_count > found.matching_count > len(found.places)


class TestTravelCost:
    async def test_walk_mode_adds_no_travel_cost(self, place_world):
        # walk has base=0 and per_km=0, so travel_sen is always 0 regardless
        # of distance, and total_sen equals the place's own estimate.
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        for place in places:
            assert place.travel_sen == 0

    async def test_ride_mode_adds_a_base_fare_and_per_km_cost(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        # Kopi Kaki is 50 m from the search origin (km < 0.12), so even ride
        # mode charges nothing for "already there".
        doorstep = next(p for p in places if p.name == place_world.cheap.name)
        assert doorstep.km < 0.12
        assert doorstep.travel_sen == 0

        # Anything further away pays ride's base fare plus per-km cost.
        farther = next(p for p in places if p.name == place_world.mid.name)
        assert farther.km >= 0.12
        assert farther.travel_sen > 0

    async def test_every_outing_carries_the_six_minute_buffer_on_top_of_the_travel(
        self, place_world
    ):
        """Ordering, queueing and eating are in none of the mode speeds.

        So six minutes is added to every outing in every mode, including one at
        the search origin itself -- and transit's seven-minute wait sits on top
        of that buffer rather than standing in for it.
        """
        origin_lat = place_world.origin["lat"]
        origin_lng = place_world.origin["lng"]
        doorstep = Place(
            "t2", "Right here", "Test", origin_lat, origin_lng, Money(1000), "high", True, ""
        )
        walked = evaluate_place(doorstep, origin_lat, origin_lng, "walk", 100_000)
        assert walked.km < 0.001
        assert walked.minutes == 6

        ridden = evaluate_place(doorstep, origin_lat, origin_lng, "transit", 100_000)
        assert ridden.minutes == 13  # 7 minutes of waiting, then the same buffer

    async def test_the_fare_is_whole_sen_carried_up_not_a_rounded_float(self, place_world):
        """money.py forbids float arithmetic and Python's round() on money.

        150 m of a ride is exactly 28.5 sen of per-km charge on top of the
        RM5.00 base. round() takes a half to even and yields 528; the half-up
        rounding the rest of the app uses yields 529, which is the fare.
        """
        origin_lat = place_world.origin["lat"]
        origin_lng = place_world.origin["lng"]
        place = Place(
            "t1",
            "Exactly 150 m away",
            "Test",
            origin_lat + 0.150 / 111.195,
            origin_lng,
            Money(1000),
            "high",
            True,
            "",
        )
        evaluated = evaluate_place(place, origin_lat, origin_lng, "ride", 100_000)

        assert round(evaluated.km * 1000) == 150
        assert evaluated.travel_sen == 529
        assert isinstance(evaluated.travel_sen, int)
        assert evaluated.total_sen == 1529


class TestTheDistanceThatIsCharged:
    """The defect this work replaces, written as the two numbers it produced.

    Bangsar to a shop at 3.095396,101.675218 is 3.71 km of great circle and
    8.10 km of road. A ride is RM5.00 plus RM1.90 a kilometre, so the same
    journey is RM12.05 measured one way and RM20.39 measured the other -- and
    only the second is what the driver charges. The great circle is not a
    conservative estimate of a road; it is an unreachable lower bound on one.
    """

    ORIGIN_LAT = 3.1285
    ORIGIN_LNG = 101.6709

    def shop(self) -> Place:
        return Place("s1", "The shop", "Grocer", 3.095396, 101.675218, Money(0), "high", True, "")

    def test_the_straight_line_understates_a_real_kl_ride(self):
        straight = evaluate_place(self.shop(), self.ORIGIN_LAT, self.ORIGIN_LNG, "ride", 100_000)
        assert round(straight.km, 2) == 3.71
        assert straight.travel_sen == 1205  # RM12.05
        assert straight.distance_basis == "straight_line"
        assert straight.road_km is None

    def test_the_road_figure_is_the_one_the_fare_is_built_on(self):
        routed = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=8101.0,
        )
        assert routed.travel_sen == 2039  # RM20.39, near twice the other figure
        assert routed.distance_basis == "road"
        assert routed.road_km == 8.101
        # km is whatever the fare was computed from, so a client reading it is
        # reading the same distance the money came out of.
        assert routed.km == 8.101

    def test_the_clock_moves_with_the_fare(self):
        # Travel time is distance times a per-km speed, so a road figure that
        # doubles the distance has to move the minutes too -- otherwise the
        # screen says RM20 and fourteen minutes, which is not a journey.
        straight = evaluate_place(self.shop(), self.ORIGIN_LAT, self.ORIGIN_LNG, "ride", 100_000)
        routed = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=8101.0,
        )
        assert straight.minutes == 23
        assert routed.minutes == 37

    def test_the_road_fare_is_still_whole_sen_carried_up(self):
        """money.py forbids float arithmetic and Python's round() on money, and
        that does not change because the metres came off a network.

        150 m of a ride is exactly 28.5 sen of per-km charge. round() takes the
        half to even and yields 528; half-up yields 529, which is the fare.
        """
        evaluated = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=150.0,
        )
        assert evaluated.travel_sen == 529
        assert isinstance(evaluated.travel_sen, int)

    def test_a_place_on_the_doorstep_by_road_is_still_free(self):
        # The under-120-metre rule is about being already there, and the road
        # is the distance that decides it now.
        evaluated = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=110.0,
        )
        assert evaluated.km < 0.12
        assert evaluated.travel_sen == 0
        assert evaluated.distance_basis == "road"


class TestWithNoRouter:
    """The offline half. Every figure is the straight line, and says so."""

    async def test_every_place_is_labelled_straight_line(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="ride",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert found.places
        for place in found.places:
            assert place.distance_basis == "straight_line"
            assert place.road_km is None

    async def test_the_fares_are_the_ones_the_great_circle_gives(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="ride",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        fares = {p.name: p.travel_sen for p in found.places}
        assert fares[place_world.cheap.name] == 0  # 50 m: already there
        assert fares[place_world.mid.name] == 595  # 500 m
        assert fares[place_world.near_non_halal.name] == 690  # 1 km
        assert fares[place_world.pricey.name] == 880  # 2 km
        assert fares[place_world.far_non_halal.name] == 1260  # 4 km


class TestWithARouter:
    """The online half, against a router with fixed answers in road metres."""

    async def test_the_fare_and_the_minutes_come_from_the_road(self, place_world):
        # Mamak Dua is 500 m in a straight line and 1.2 km of road.
        with serving(StubRouting({"w2": 1200.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        mid = next(p for p in found.places if p.name == place_world.mid.name)

        assert mid.distance_basis == "road"
        assert mid.road_km == 1.2
        assert mid.km == 1.2
        assert mid.travel_sen == 728  # not the 595 the straight line gives
        assert mid.minutes == 15
        assert mid.total_sen == 1250 + 728

    async def test_the_ceiling_is_applied_after_the_road_distance(self, place_world):
        """The order that makes this worth doing.

        Mamak Dua costs RM12.50 plus RM5.95 of straight-line fare -- RM18.45,
        under a RM19.00 ceiling. By road it is RM7.28 of fare and RM19.78,
        which is over it. Filtering before routing would have shown the user a
        place they cannot afford, at a price that was never available.
        """
        cap_sen = 1900
        with serving(StubRouting({"w2": 1200.0})):
            routed = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=cap_sen,
                room_sen=100_000,
            )
        assert place_world.mid.name not in {p.name for p in routed.places}
        assert all(p.total_sen <= cap_sen for p in routed.places)
        # It is the road distance that excluded it, not the ceiling being tight:
        # with no router the same search shows it.
        unrouted = await find_places(
            **place_world.origin,
            mode="ride",
            halal_only=False,
            cap_sen=cap_sen,
            room_sen=100_000,
        )
        assert place_world.mid.name in {p.name for p in unrouted.places}
        # And it stayed in matching_count either way, so the counts still say
        # the ceiling is what the user could move.
        assert routed.matching_count == unrouted.matching_count

    async def test_the_sort_follows_the_road_totals(self, place_world):
        # Omakase Empat is dearer than everything even before travel, so the
        # interesting swap is between the two mid-priced places: Bak Kut Teh
        # Tiga (RM16.00 + RM6.90 = RM22.90 straight) sits under Chophouse Lima
        # (RM20.00 + RM12.60 = RM32.60) until the road puts it the other way.
        with serving(StubRouting({"w3": 9000.0, "w5": 4200.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        totals = [p.total_sen for p in found.places]
        assert totals == sorted(totals)
        order = [p.name for p in found.places]
        assert order.index(place_world.far_non_halal.name) < order.index(
            place_world.near_non_halal.name
        )

    async def test_it_asks_the_router_once_for_everything_that_survived_the_filters(
        self, place_world
    ):
        stub = StubRouting({})
        with serving(stub):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=True,
                cap_sen=100_000,
                room_sen=100_000,
            )
        assert len(stub.calls) == 1, "one search is one round trip, however many places"
        origin, destinations = stub.calls[0]
        assert origin == (place_world.origin["lat"], place_world.origin["lng"])
        # Three of the five are halal. The two the filter removed are never sent
        # to the router: a place that will not be shown is not worth a distance.
        assert len(destinations) == found.matching_count == 3

    async def test_nothing_in_range_asks_the_router_nothing_useful(self, place_world):
        stub = StubRouting({})
        with serving(stub):
            found = await find_places(
                **place_world.out_of_range,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        assert found.places == ()
        assert stub.calls == [] or stub.calls[0][1] == []


class TestAPartlyAnsweredSearch:
    """A router can route one destination and fail on the next, so the basis is
    per place. A single flag for the whole list would have to lie about half of
    it, and the half it lied about would be the half quoting a fare it cannot
    stand behind."""

    async def test_each_place_carries_the_basis_it_was_actually_measured_on(self, place_world):
        # Two of the five answered; the rest came back null.
        with serving(StubRouting({"w2": 1200.0, "w4": 4500.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        by_name = {p.name: p for p in found.places}
        bases = {name: place.distance_basis for name, place in by_name.items()}

        assert bases[place_world.mid.name] == "road"
        assert bases[place_world.pricey.name] == "road"
        assert bases[place_world.near_non_halal.name] == "straight_line"
        assert bases[place_world.far_non_halal.name] == "straight_line"
        assert len(set(bases.values())) == 2, "one list, two bases"

    async def test_the_routed_ones_are_priced_on_the_road_and_the_rest_are_not(self, place_world):
        with serving(StubRouting({"w2": 1200.0, "w4": 4500.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        fares = {p.name: p.travel_sen for p in found.places}
        road_km = {p.name: p.road_km for p in found.places}

        assert fares[place_world.mid.name] == 728  # 1.2 km of road
        assert fares[place_world.pricey.name] == 1355  # 4.5 km of road
        assert road_km[place_world.mid.name] == 1.2
        assert road_km[place_world.pricey.name] == 4.5

        # Unanswered: the straight-line fares, unchanged, and no road figure to
        # show beside them.
        assert fares[place_world.near_non_halal.name] == 690
        assert fares[place_world.far_non_halal.name] == 1260
        assert road_km[place_world.near_non_halal.name] is None
        assert road_km[place_world.far_non_halal.name] is None


class TestTheAddress:
    async def test_every_place_carries_the_address_it_came_with(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        addresses = {p.name: p.address for p in found.places}
        assert addresses[place_world.cheap.name] == place_world.cheap.address
        assert all(addresses.values()), "a place named on a screen has to be findable"


class TestARouterThatMisbehaves:
    """A wrong-shaped answer is not a distance, and must not become one."""

    async def test_an_answer_of_the_wrong_length_is_not_paired_off_anyway(self, place_world):
        class ShortRouting:
            """Asked about five destinations, answers about one."""

            async def road_metres(self, origin, destinations):
                return [1200.0]

        with serving(ShortRouting()):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )

        # Which place that single figure belongs to is unknowable. Lining it up
        # with the first destination would put one place's road on another
        # place's fare, which is a wrong number nobody could spot. The straight
        # line is wrong by a stated amount instead.
        assert len(found.places) == 5
        assert {p.distance_basis for p in found.places} == {"straight_line"}
        assert all(p.road_km is None for p in found.places)


async def demo(session):
    user = await seed_demo_user(session)
    await session.flush()
    return user


class TestAddingAPlanToToday:
    """A receipt says "I spent this". A plan says "I intend to".

    Both are proposals, so both are drafts — but a draft is excluded from every
    engine calculation, and that exclusion is what these tests are really
    about. Adding a plan must leave today's money exactly where it was.
    """

    async def test_adds_one_draft_for_the_whole_outing(self, session):
        user = await demo(session)
        before = len((await list_activity(session, user)).drafts)

        # RM12.50 of meal and RM5.00 of fare: what the row on the planner shows
        # is the sum, and the sum is what the user tapped.
        added = await add_to_today(
            session,
            user,
            name="Kopi Kaki",
            total_sen=1750,
            confidence="high",
            today=DEMO_TODAY,
        )

        drafts = (await list_activity(session, user)).drafts
        assert len(drafts) == before + 1
        assert added.amount_sen == 1750
        assert added.status == TXN_DRAFT
        assert added.merchant == "Kopi Kaki"
        assert [draft.id for draft in drafts].count(added.id) == 1

    async def test_the_draft_says_it_is_a_plan_and_that_the_price_is_a_guess(self, session):
        user = await demo(session)

        added = await add_to_today(
            session, user, name="Kopi Kaki", total_sen=1750, confidence="high", today=DEMO_TODAY
        )

        assert added.source == SOURCE_PLAN
        assert added.category == "food"
        assert added.category_label == "Food & drink"
        assert added.occurred_on == DEMO_TODAY
        assert "estimate" in added.note
        assert "day plan" in added.note
        # The invariant the whole screen rests on, said on the row itself: the
        # toast that announced this is long gone by the time Activity is read.
        assert "Nothing counts against today until you confirm it." in added.note
        # Nothing here may read as money already put aside.
        assert "pencilled" not in added.note.lower()

    async def test_safe_to_spend_does_not_move_while_it_is_a_plan(self, session):
        user = await demo(session)
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))

        await add_to_today(
            session, user, name="Omakase Empat", total_sen=5000, confidence="low", today=DEMO_TODAY
        )

        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        # RM50.00 of intention, and not one sen of it counted. The user has not
        # eaten yet; a figure that dropped here would be spending their money
        # for them on the strength of a tap.
        assert before.safe_today == Money(5297)
        assert after.safe_today == Money(5297)
        assert after.spent_today == before.spent_today

    async def test_confirming_it_is_what_finally_spends_the_money(self, session):
        user = await demo(session)
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        added = await add_to_today(
            session, user, name="Omakase Empat", total_sen=5000, confidence="low", today=DEMO_TODAY
        )

        await confirm_draft(session, user, added.id)

        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        # RM50.00 leaves today's spending and the balance both, so the day loses
        # RM52.27 rather than RM50.00 — but it loses it now, once the user has
        # said the money is gone, and not a moment before.
        assert after.safe_today == Money(70)
        assert after.spent_today == before.spent_today + Money(5000)

    async def test_it_is_waiting_in_activity_alongside_every_other_draft(self, session):
        user = await demo(session)
        before = (await list_activity(session, user)).draft_total_sen

        added = await add_to_today(
            session, user, name="Kopi Kaki", total_sen=1750, confidence="high", today=DEMO_TODAY
        )

        activity = await list_activity(session, user)
        # Nothing new had to be built for this: drafts already surface here, and
        # a plan is one, so it arrives with the receipt and the voice note.
        waiting = next(draft for draft in activity.drafts if draft.id == added.id)
        assert waiting.source == SOURCE_PLAN
        assert activity.draft_total_sen == before + 1750
        # The ledger is confirmed spending only, and an intention is not that.
        assert added.id not in {
            txn.id for day in activity.days for txn in day.transactions
        }
        assert activity.spent_this_cycle_sen == 63135

    async def test_maps_each_band_to_a_figure_below_what_a_read_claims(self, session):
        user = await demo(session)

        bands = {}
        for band in ("high", "medium", "low"):
            added = await add_to_today(
                session,
                user,
                name=f"Place {band}",
                total_sen=1000,
                confidence=band,
                today=DEMO_TODAY,
            )
            bands[band] = added.confidence

        assert bands == {"high": 70, "medium": 50, "low": 30}
        # A curated price band is a weaker thing than a total printed on a slip.
        # The receipt reader's own scans come in at 94, and nothing here may
        # dress an estimate up to look like one of those.
        assert max(bands.values()) < 94
        assert bands["high"] > bands["medium"] > bands["low"]

    async def test_a_band_this_build_does_not_know_is_read_as_the_least_certain(self, session):
        user = await demo(session)

        # The bands come from a regenerated data file. A word this build has not
        # seen should cost the user their tap the least, and must not be turned
        # into more certainty than anything behind it supports.
        added = await add_to_today(
            session, user, name="Kopi Kaki", total_sen=1750, confidence="astonishing",
            today=DEMO_TODAY,
        )

        assert added.confidence == PLAN_CONFIDENCE["low"]
        assert confidence_for("astonishing") == confidence_for("low")
