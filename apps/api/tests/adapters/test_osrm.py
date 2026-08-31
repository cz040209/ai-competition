"""OsrmRouting against an in-process transport. Nothing here touches a network.

Two things are being pinned. One is that a good table response is read the way
OSRM writes it -- the origin's own cell dropped, the rest lined up with the
destinations in order. The other is bigger: the public router is a volunteer
service the app is not entitled to, so every way it can let us down has to come
back as "no answer", never as an exception on a page that states money.
"""

from __future__ import annotations

import json

import httpx
import pytest

from kira.adapters.osrm import OsrmRouting
from kira.adapters.protocols import RoutingAdapter

BASE_URL = "https://router.example"

# Bangsar, and the shop that is 3.71 km away in a straight line and 8.10 km by
# road -- the journey whose fare this whole adapter exists to get right.
ORIGIN = (3.1285, 101.6709)
SHOP = (3.095396, 101.675218)
SECOND = (3.1466, 101.7106)


def routing_that(handler, timeout_seconds: float = 2.5) -> OsrmRouting:
    return OsrmRouting(BASE_URL, timeout_seconds, transport=httpx.MockTransport(handler))


def answering(body: object, status_code: int = 200) -> OsrmRouting:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return routing_that(handler)


def table(*rows: object) -> dict[str, object]:
    """A well-formed one-source table. Cell 0 is the origin against itself."""
    return {"code": "Ok", "distances": [[0, *rows]], "durations": [[0, *rows]]}


class TestProtocolConformance:
    def test_it_satisfies_the_routing_protocol(self):
        assert isinstance(answering(table(8101.0)), RoutingAdapter)


class TestAGoodAnswer:
    async def test_it_reads_road_metres_in_destination_order(self):
        routing = answering(table(8101.0, 4210.5))
        assert await routing.road_metres(ORIGIN, [SHOP, SECOND]) == [8101.0, 4210.5]

    async def test_the_road_figure_is_not_the_straight_line(self):
        """The bug this replaces, stated as an assertion.

        3.71 km of great circle, 8.10 km of driving. A ride fare is 500 sen
        plus 190 sen a kilometre, so the difference between the two is RM12.05
        and RM20.39 for the same trip.
        """
        routing = answering(table(8101.0))
        [metres] = await routing.road_metres(ORIGIN, [SHOP])
        assert metres == 8101.0

    async def test_it_asks_one_source_against_every_destination_in_one_call(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=table(1.0, 2.0))

        await routing_that(handler).road_metres(ORIGIN, [SHOP, SECOND])

        assert len(seen) == 1, "one origin against many destinations is one request"
        url = str(seen[0].url)
        # The exact shape the service was verified against, comma and all: one
        # source, the origin first, then every destination in lng,lat order.
        # The public server only deploys driving -- /foot/ answers with the same
        # numbers under a different name, which would be a car's route sold as a
        # walk, so the profile is not a parameter.
        assert url == (
            f"{BASE_URL}/table/v1/driving/"
            "101.670900,3.128500;101.675218,3.095396;101.710600,3.146600"
            "?sources=0&annotations=distance,duration"
        )

    async def test_an_unroutable_destination_is_null_beside_routed_ones(self):
        # OSRM writes null for a destination it cannot reach. That is a fact
        # about one place, and must not discard the answers around it.
        routing = answering(table(8101.0, None, 4210.5))
        assert await routing.road_metres(ORIGIN, [SHOP, SECOND, SHOP]) == [
            8101.0,
            None,
            4210.5,
        ]

    async def test_no_destinations_means_no_request_at_all(self):
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("an empty search must not call the router")

        assert await routing_that(handler).road_metres(ORIGIN, []) == []


class TestEveryWayItCanFail:
    """All of them end the same way: one None per destination, no exception."""

    async def test_a_timeout_answers_nothing(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        assert await routing_that(handler).road_metres(ORIGIN, [SHOP, SECOND]) == [None, None]

    async def test_a_refused_connection_answers_nothing(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        assert await routing_that(handler).road_metres(ORIGIN, [SHOP]) == [None]

    @pytest.mark.parametrize("status_code", [400, 429, 500, 502, 503])
    async def test_a_non_200_answers_nothing(self, status_code: int):
        routing = answering(table(8101.0), status_code=status_code)
        assert await routing.road_metres(ORIGIN, [SHOP]) == [None]

    async def test_a_code_other_than_ok_answers_nothing(self):
        # OSRM reports its own failures inside a 200. A body read without
        # checking "code" would turn "NoRoute" into a distance of nothing.
        body = {"code": "NoSegment", "message": "Could not find a matching segment"}
        assert await answering(body).road_metres(ORIGIN, [SHOP]) == [None]

    async def test_a_body_that_is_not_json_answers_nothing(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>502 Bad Gateway</html>")

        assert await routing_that(handler).road_metres(ORIGIN, [SHOP]) == [None]

    async def test_json_that_is_not_a_table_answers_nothing(self):
        for body in (
            [1, 2, 3],
            {"code": "Ok"},
            {"code": "Ok", "distances": []},
            {"code": "Ok", "distances": [None]},
            {"code": "Ok", "distances": "8101"},
        ):
            assert await answering(body).road_metres(ORIGIN, [SHOP]) == [None], body

    async def test_a_row_of_the_wrong_width_answers_nothing(self):
        # Two destinations were asked about and one figure came back. Which of
        # the two it belongs to is unknowable, and guessing would put one
        # place's distance on the other place's fare.
        routing = answering(table(8101.0))
        assert await routing.road_metres(ORIGIN, [SHOP, SECOND]) == [None, None]

    async def test_a_cell_that_is_not_a_distance_is_dropped_alone(self):
        routing = answering(table("8101", 4210.5))
        assert await routing.road_metres(ORIGIN, [SHOP, SECOND]) == [None, 4210.5]

    async def test_a_negative_distance_is_dropped(self):
        routing = answering(table(-1.0, 4210.5))
        assert await routing.road_metres(ORIGIN, [SHOP, SECOND]) == [None, 4210.5]

    async def test_it_never_raises_whatever_the_transport_does(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise RuntimeError("something nobody predicted")

        assert await routing_that(handler).road_metres(ORIGIN, [SHOP]) == [None]


class TestTheTimeout:
    async def test_the_configured_timeout_is_the_one_used(self):
        seen: list[httpx.Timeout | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.extensions.get("timeout"))
            return httpx.Response(200, content=json.dumps(table(8101.0)))

        await routing_that(handler, timeout_seconds=2.5).road_metres(ORIGIN, [SHOP])

        # A page that states today's money does not wait on a free service.
        assert seen == [{"connect": 2.5, "pool": 2.5, "read": 2.5, "write": 2.5}]
