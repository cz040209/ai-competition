from sqlalchemy import select

from kira.db.models import TXN_CONFIRMED, Transaction, User
from kira.money import Money
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user
from kira.services.clock import today_for

KLCC_LAT = 3.1577
KLCC_LNG = 101.7120

# George Town, Penang: ~300 km from every seeded place.
PENANG_LAT = 5.4141
PENANG_LNG = 100.3288

# 4.9 km due south of Lot 10 Hutong: the only seeded place in range of here is
# Lot 10 itself, which is not halal.
ONLY_NON_HALAL_LAT = 3.10248
ONLY_NON_HALAL_LNG = 101.7106


async def demo_token(client, session) -> str:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


class TestDayPlanAuth:
    async def test_requires_a_token(self, client):
        response = await client.get(
            "/v1/day-plan/places", params={"lat": KLCC_LAT, "lng": KLCC_LNG}
        )
        assert response.status_code == 401


class TestDayPlanPlaces:
    async def test_returns_places_sorted_by_total_cost(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG},
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

    async def test_states_the_room_it_judged_against(self, client, session):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG},
            headers=headers,
        )
        body = response.json()
        # Stated, not inferable: the client must never have to divide its way
        # back to this figure.
        assert body["room_sen"] == safe_today_sen

    async def test_omitting_cap_sen_defaults_to_todays_safe_to_spend(self, client, session):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        assert dashboard.status_code == 200, dashboard.text
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # With no cap_sen given, the endpoint must fall back to room_sen as the
        # cap, so nothing shown can cost more than today's safe-to-spend.
        assert body["cap_sen"] == safe_today_sen
        assert all(p["total_sen"] <= safe_today_sen for p in body["places"])

    async def test_reports_the_cap_it_actually_applied(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["cap_sen"] == 100_000

    async def test_a_cap_sen_above_room_still_reports_bands_from_room(self, client, session):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG, "cap_sen": 100_000},
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

    async def test_halal_only_excludes_non_halal_places(self, client, session):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG, "halal_only": True, "cap_sen": 100_000},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        places = response.json()["places"]
        assert places
        assert all(p["halal"] for p in places)

    async def test_never_leaks_a_float_for_money_fields(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG},
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


class TestWhyTheListIsEmpty:
    """An empty list has three causes and the client must not have to guess:
    a ceiling too low is the user's to move, a halal toggle is theirs to switch
    off, and distance is neither."""

    async def test_it_reports_how_many_places_were_in_range(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["nearby_count"] == len(body["places"])
        assert body["matching_count"] == len(body["places"])

    async def test_out_of_range_reports_nil_in_range_and_no_places(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": PENANG_LAT, "lng": PENANG_LNG, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["nearby_count"] == 0
        assert body["matching_count"] == 0
        assert body["places"] == []

    async def test_a_halal_filter_that_admits_nothing_is_told_apart_from_a_ceiling(
        self, client, session
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "lat": ONLY_NON_HALAL_LAT,
            "lng": ONLY_NON_HALAL_LNG,
            "cap_sen": 100_000,
        }

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
        assert [p["name"] for p in shown["places"]] == ["Lot 10 Hutong"]
        assert shown["matching_count"] == 1

    async def test_the_counts_nest_so_the_first_nil_one_is_the_cause(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG, "halal_only": True, "cap_sen": 1000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["nearby_count"] > body["matching_count"] > len(body["places"])

    async def test_a_ceiling_too_low_reports_places_in_range_and_none_shown(
        self, client, session
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={"lat": KLCC_LAT, "lng": KLCC_LNG, "cap_sen": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Same empty list as the Penang case above, and the only thing that
        # tells the two apart is this count -- which is the whole point of it.
        assert body["places"] == []
        assert body["nearby_count"] > 0
        # Nothing was filtered out for not being halal, so the ceiling is the
        # cause and is the one thing the copy may point the user at.
        assert body["matching_count"] == body["nearby_count"]


class TestDayOnWhichNothingIsLeft:
    """A day already spent out is the state the whole product exists for."""

    async def test_room_is_reported_as_zero_not_left_to_be_inferred(self, client, session):
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
            params={"lat": KLCC_LAT, "lng": KLCC_LNG, "cap_sen": 5000},
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

    async def test_with_no_ceiling_given_nothing_is_offered(self, client, session):
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
            params={"lat": KLCC_LAT, "lng": KLCC_LNG},
            headers=headers,
        )
        body = response.json()
        # The cap defaults to the room, and the room is nil: the honest answer
        # is an empty list under a stated ceiling of zero, not a stocked one.
        assert body["cap_sen"] == 0
        assert body["places"] == []
