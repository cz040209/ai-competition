"""find_places() ports kira-prototype.jsx's evaluate() (line 661)."""

from __future__ import annotations

from kira.adapters.protocols import Place
from kira.money import Money
from kira.services.day_plan import evaluate_place, find_places

KLCC_LAT = 3.1577
KLCC_LNG = 101.7120

# George Town, Penang: ~300 km from every seeded place.
PENANG_LAT = 5.4141
PENANG_LNG = 100.3288

# 4.9 km due south of Lot 10 Hutong: the only seeded place within 5 km of here
# is Lot 10 itself, which is not halal.
ONLY_NON_HALAL_LAT = 3.10248
ONLY_NON_HALAL_LNG = 101.7106


class TestBandThresholds:
    """Walk mode has base=0 and per_km=0, so total_sen == the place's estimate,
    which makes the ok/tight/over boundaries easy to reason about directly."""

    def test_ok_tight_and_over_all_appear(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=2000,
        ).places
        by_name = {p.name: p for p in places}

        # 900 / 2000 = 0.45 <= 0.6
        assert by_name["Zus Coffee, Jln Ampang"].share == 0.45
        assert by_name["Zus Coffee, Jln Ampang"].band == "ok"

        # 1250 / 2000 = 0.625, in (0.6, 1.0]
        assert by_name["Nasi Kandar Pelita"].band == "tight"

        # 4600 / 2000 = 2.3 > 1.0
        assert by_name["Sushi Zanmai KLCC"].band == "over"

    def test_band_boundaries_are_inclusive_of_their_upper_edge(self):
        # A place whose total is exactly 60% of room lands in "ok", not "tight".
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=1500,  # 900 / 1500 = 0.6 exactly
        ).places
        zus = next(p for p in places if p.name == "Zus Coffee, Jln Ampang")
        assert zus.share == 0.6
        assert zus.band == "ok"


class TestHalalFilter:
    def test_excludes_non_halal_places_when_requested(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
        ).places
        assert places  # sanity: the filter did not empty the whole set
        assert all(p.halal for p in places)
        names = {p.name for p in places}
        assert "Chee Meng Chicken Rice" not in names
        assert "Lot 10 Hutong" not in names

    def test_includes_non_halal_places_by_default(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        ).places
        names = {p.name for p in places}
        assert "Chee Meng Chicken Rice" in names


class TestCapFilter:
    def test_a_place_above_the_cap_is_excluded(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=1500,  # below Sushi Zanmai's 4600
            room_sen=100_000,
        ).places
        names = {p.name for p in places}
        assert "Sushi Zanmai KLCC" not in names
        assert all(p.total_sen <= 1500 for p in places)


class TestSortOrder:
    def test_results_are_sorted_ascending_by_total_sen(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        ).places
        totals = [p.total_sen for p in places]
        assert totals == sorted(totals)


class TestRoomIsNotCap:
    """room_sen (today's real safe-to-spend) drives share/band. cap_sen only
    filters what is shown. Swapping the two is the bug this guards against."""

    def test_a_place_can_be_shown_by_cap_but_still_be_over_room(self):
        # Nasi Kandar Pelita costs 1250 sen (walk mode adds no travel cost).
        # cap_sen=2100 admits it into the results; room_sen=1000 means it
        # actually costs more than the user's whole safe-to-spend for today.
        # If the implementation ever computed share against cap_sen instead
        # of room_sen, 1250 / 2100 = 0.595 would read as "ok" -- the correct
        # answer, computed against room_sen, is "over" (1250 / 1000 = 1.25).
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=2100,
            room_sen=1000,
        ).places
        pelita = next(p for p in places if p.name == "Nasi Kandar Pelita")
        assert pelita.total_sen == 1250
        assert pelita.share == 1.25
        assert pelita.band == "over"

    def test_raising_cap_above_room_still_yields_tight_and_over_entries(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,  # generous cap: nothing is filtered out by price
            room_sen=1000,  # tight room: most places cost more than this
        ).places
        bands = {p.band for p in places}
        assert "tight" in bands or "over" in bands
        assert any(p.total_sen > 1000 for p in places), (
            "a place costing more than room_sen must still appear when cap_sen allows it"
        )


class TestNoRoomLeft:
    """A day already spent out has no share to report, and saying so is the
    only thing that keeps a real share of 2.0 tellable from an absent one."""

    def test_a_nil_room_yields_no_share_and_every_place_over(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=0,
        ).places
        assert places
        for place in places:
            assert place.share is None
            assert place.band == "over"

    def test_a_genuine_share_of_two_is_still_reported(self):
        # Nasi Kandar Pelita costs 1250 sen against 625 sen of room: exactly the
        # ratio the old zero-room stand-in was indistinguishable from.
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=625,
        ).places
        pelita = next(p for p in places if p.name == "Nasi Kandar Pelita")
        assert pelita.share == 2.0


class TestNearbyCount:
    """An empty result has three causes, and only the two counts tell them
    apart: a ceiling the user can move, a filter the user can switch off, or a
    distance neither of those will close."""

    def test_it_counts_what_the_radius_held_before_the_filters_ran(self):
        unfiltered = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert unfiltered.nearby_count == len(unfiltered.places)

        filtered = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=True,
            cap_sen=1000,  # admits only Zus Coffee's 900
            room_sen=100_000,
        )
        assert len(filtered.places) < len(unfiltered.places)
        assert filtered.nearby_count == unfiltered.nearby_count

    def test_a_ceiling_that_admits_nothing_still_counts_the_places_in_range(self):
        found = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=1,
            room_sen=100_000,
        )
        assert found.places == ()
        assert found.nearby_count > 0

    def test_it_is_nil_where_the_seed_data_does_not_reach(self):
        found = find_places(
            lat=PENANG_LAT,
            lng=PENANG_LNG,
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

    def test_it_counts_what_survived_the_halal_filter_not_the_ceiling(self):
        found = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=True,
            cap_sen=1,  # admits nothing at all
            room_sen=100_000,
        )
        assert found.places == ()
        # Two of the eight seeded places are not halal, and the ceiling of one
        # sen is what emptied the rest -- which is the count that says so.
        assert found.nearby_count == 8
        assert found.matching_count == 6

    def test_the_halal_filter_alone_can_empty_a_generous_ceiling(self):
        # 4.9 km south of Lot 10 Hutong: it is the one seeded place in range,
        # and it is not halal. No ceiling reaches it, because the ceiling is
        # not what is holding it back.
        found = find_places(
            lat=ONLY_NON_HALAL_LAT,
            lng=ONLY_NON_HALAL_LNG,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert found.places == ()
        assert found.nearby_count == 1
        assert found.matching_count == 0

        # Same spot, same ceiling, halal off: the place was there all along.
        relaxed = find_places(
            lat=ONLY_NON_HALAL_LAT,
            lng=ONLY_NON_HALAL_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert [p.name for p in relaxed.places] == ["Lot 10 Hutong"]
        assert relaxed.matching_count == 1

    def test_the_counts_nest(self):
        found = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=True,
            cap_sen=1000,  # admits only Zus Coffee's 900
            room_sen=100_000,
        )
        assert found.nearby_count >= found.matching_count >= len(found.places)
        assert found.nearby_count > found.matching_count > len(found.places)


class TestTravelCost:
    def test_walk_mode_adds_no_travel_cost(self):
        # walk has base=0 and per_km=0, so travel_sen is always 0 regardless
        # of distance, and total_sen equals the place's own estimate.
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        ).places
        for place in places:
            assert place.travel_sen == 0

    def test_ride_mode_adds_a_base_fare_and_per_km_cost(self):
        places = find_places(
            lat=KLCC_LAT,
            lng=KLCC_LNG,
            mode="ride",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        ).places
        # Suria KLCC food court sits at the search origin itself (km < 0.12),
        # so even ride mode charges nothing for "already there".
        food_court = next(p for p in places if p.name == "Suria KLCC food court")
        assert food_court.km < 0.12
        assert food_court.travel_sen == 0

        # Anything further away pays ride's base fare plus per-km cost.
        farther = next(p for p in places if p.name == "Nasi Lemak Antarabangsa")
        assert farther.km >= 0.12
        assert farther.travel_sen > 0

    def test_the_fare_is_whole_sen_carried_up_not_a_rounded_float(self):
        """money.py forbids float arithmetic and Python's round() on money.

        150 m of a ride is exactly 28.5 sen of per-km charge on top of the
        RM5.00 base. round() takes a half to even and yields 528; the half-up
        rounding the rest of the app uses yields 529, which is the fare.
        """
        origin_lat, origin_lng = KLCC_LAT, KLCC_LNG
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
