"""The endpoint runs against the ``place_world`` fixture rather than the shipped
KL set, so a refresh of that data file cannot change what these tests mean."""

from sqlalchemy import select

from kira.db.models import TXN_CONFIRMED, Transaction, User
from kira.money import Money
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user
from kira.services.clock import today_for
from tests.conftest import StubRouting, serving


async def demo_token(client, session) -> str:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


class TestDayPlanAuth:
    async def test_requires_a_token(self, client, place_world):
        response = await client.get("/v1/day-plan/places", params=place_world.origin)
        assert response.status_code == 401


class TestDayPlanPlaces:
    async def test_returns_places_sorted_by_total_cost(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        places = body["places"]
        assert len(places) > 0
        totals = [p["total_sen"] for p in places]
        assert totals == sorted(totals)
        for place in places:
            assert place["band"] in ("ok", "tight", "over")
            assert place["total_sen"] >= place["travel_sen"] >= 0

    async def test_states_the_room_it_judged_against(self, client, session, place_world):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers=headers,
        )
        body = response.json()
        # Stated, not inferable: the client must never have to divide its way
        # back to this figure.
        assert body["room_sen"] == safe_today_sen

    async def test_omitting_cap_sen_defaults_to_todays_safe_to_spend(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        assert dashboard.status_code == 200, dashboard.text
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # With no cap_sen given, the endpoint must fall back to room_sen as the
        # cap, so nothing shown can cost more than today's safe-to-spend.
        assert body["cap_sen"] == safe_today_sen
        assert all(p["total_sen"] <= safe_today_sen for p in body["places"])

    async def test_reports_the_cap_it_actually_applied(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["cap_sen"] == 100_000

    async def test_a_cap_sen_above_room_still_reports_bands_from_room(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # A generous cap_sen must not change what band a place lands in: band
        # is always computed from today's real safe-to-spend, not the cap.
        assert body["room_sen"] == safe_today_sen
        for place in body["places"]:
            share = place["total_sen"] / safe_today_sen if safe_today_sen > 0 else 2.0
            expected = "ok" if share <= 0.6 else "tight" if share <= 1.0 else "over"
            assert place["band"] == expected

    async def test_halal_only_excludes_non_halal_places(self, client, session, place_world):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "halal_only": True, "cap_sen": 100_000},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        places = response.json()["places"]
        assert places
        assert all(p["halal"] for p in places)

    async def test_never_leaks_a_float_for_money_fields(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body["room_sen"], int)
        assert isinstance(body["cap_sen"], int)
        for place in body["places"]:
            assert isinstance(place["total_sen"], int)
            assert isinstance(place["travel_sen"], int)
            assert isinstance(place["minutes"], int)


class TestWhatTheDistanceWasMeasuredOn:
    """The screen has to be able to say whether a fare is a road fare.

    A ride quoted on the great circle can be half the real one in KL, so the
    wire carries the basis for every place and the road figure beside it. The
    client is never left to infer either.
    """

    async def test_every_place_states_its_basis_and_a_road_figure_or_null(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "mode": "ride", "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        places = response.json()["places"]
        assert places
        for place in places:
            assert place["distance_basis"] in ("road", "straight_line")
            if place["distance_basis"] == "road":
                assert place["road_km"] == place["km"]
            else:
                # Nothing to show beside the straight line, and null rather
                # than the straight-line figure repeated under a road label.
                assert place["road_km"] is None

    async def test_with_no_router_it_says_straight_line_rather_than_going_quiet(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "mode": "ride", "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        places = response.json()["places"]
        assert places
        assert {p["distance_basis"] for p in places} == {"straight_line"}

    async def test_a_routed_search_prices_on_the_road_and_says_so(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        params = {**place_world.origin, "mode": "ride", "cap_sen": 100_000}

        # Mamak Dua is 500 m in a straight line and 1.2 km of road: RM5.95 of
        # fare against RM7.28.
        with serving(StubRouting({"w2": 1200.0})):
            response = await client.get("/v1/day-plan/places", params=params, headers=headers)
        assert response.status_code == 200, response.text
        routed = next(
            p for p in response.json()["places"] if p["name"] == place_world.mid.name
        )
        assert routed["distance_basis"] == "road"
        assert routed["road_km"] == 1.2
        assert routed["travel_sen"] == 728

        unrouted = await client.get("/v1/day-plan/places", params=params, headers=headers)
        same = next(
            p for p in unrouted.json()["places"] if p["name"] == place_world.mid.name
        )
        assert same["distance_basis"] == "straight_line"
        assert same["travel_sen"] == 595

    async def test_every_place_carries_an_address(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        places = response.json()["places"]
        assert places
        assert all(p["address"] for p in places)

    async def test_every_place_carries_the_point_it_stands_on(
        self, client, session, place_world
    ):
        """An address is not always enough to find the shop again.

        A quarter of the shipped addresses name a locality rather than a
        doorstep, and several names in that set belong to two branches, so a
        client sending the user to a map has to be able to send them to this
        one. The coordinates are the adapter's own, echoed untouched -- the
        distance work above must not have moved them.
        """
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        by_name = {p["name"]: p for p in response.json()["places"]}
        assert by_name
        for known in place_world.places:
            if known.name in by_name:
                assert by_name[known.name]["lat"] == known.lat
                assert by_name[known.name]["lng"] == known.lng


class TestWhyTheListIsEmpty:
    """An empty list has three causes and the client must not have to guess:
    a ceiling too low is the user's to move, a halal toggle is theirs to switch
    off, and distance is neither."""

    async def test_it_reports_how_many_places_were_in_range(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["nearby_count"] == len(body["places"])
        assert body["matching_count"] == len(body["places"])

    async def test_out_of_range_reports_nil_in_range_and_no_places(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.out_of_range, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["nearby_count"] == 0
        assert body["matching_count"] == 0
        assert body["places"] == []

    async def test_a_halal_filter_that_admits_nothing_is_told_apart_from_a_ceiling(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        params = {**place_world.lone_non_halal, "cap_sen": 100_000}

        response = await client.get(
            "/v1/day-plan/places", params={**params, "halal_only": True}, headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # A place is in range and the ceiling is RM1,000. Neither is the cause,
        # and a client told only "nearby_count > 0" would blame the ceiling and
        # send the user at a slider that cannot reach it.
        assert body["places"] == []
        assert body["nearby_count"] == 1
        assert body["matching_count"] == 0

        relaxed = await client.get(
            "/v1/day-plan/places", params={**params, "halal_only": False}, headers=headers
        )
        shown = relaxed.json()
        assert [p["name"] for p in shown["places"]] == [place_world.far_non_halal.name]
        assert shown["matching_count"] == 1

    async def test_the_counts_nest_so_the_first_nil_one_is_the_cause(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "halal_only": True, "cap_sen": 1000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["nearby_count"] > body["matching_count"] > len(body["places"])

    async def test_a_ceiling_too_low_reports_places_in_range_and_none_shown(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Same empty list as the out-of-range case above, and the only thing
        # that tells the two apart is this count -- which is the whole point.
        assert body["places"] == []
        assert body["nearby_count"] > 0
        # Nothing was filtered out for not being halal, so the ceiling is the
        # cause and is the one thing the copy may point the user at.
        assert body["matching_count"] == body["nearby_count"]


class TestDayOnWhichNothingIsLeft:
    """A day already spent out is the state the whole product exists for."""

    async def test_room_is_reported_as_zero_not_left_to_be_inferred(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        # Spend today's whole allowance, so safe-to-spend floors at zero.
        user = (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one()
        today = today_for()
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

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        assert dashboard.json()["safe_today_sen"] == 0

        # The cap is what the user dragged the ceiling to; the room is still nil.
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 5000},
            headers=headers,
        )
        body = response.json()
        assert body["room_sen"] == 0
        assert body["cap_sen"] == 5000
        assert body["places"], "a raised ceiling should still surface places"
        # No share at all, rather than a stand-in a client could turn into a
        # percentage or divide by to recover a room that is not there.
        for place in body["places"]:
            assert place["band"] == "over"
            assert place["share"] is None

    async def test_with_no_ceiling_given_nothing_is_offered(self, client, session, place_world):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        user = (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one()
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Blowout",
                amount=Money(500_000, user.currency),
                occurred_on=today_for(),
                category="food",
                status=TXN_CONFIRMED,
                source="manual",
                note="",
            )
        )
        await session.commit()

        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers=headers,
        )
        body = response.json()
        # The cap defaults to the room, and the room is nil: the honest answer
        # is an empty list under a stated ceiling of zero, not a stocked one.
        assert body["cap_sen"] == 0
        assert body["places"] == []
