"""Road distance from OSRM's table service.

The public router at router.project-osrm.org is run by volunteers, and the day
planner is not entitled to it. So every failure mode it has -- slow, down,
rate-limited, answering something that is not JSON -- resolves to the same
thing here: no answer, returned calmly, one ``None`` per destination. The
planner then measures in a straight line and says on screen that it did. What
must never happen is an exception reaching a page whose whole job is to state
what an outing costs.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

# Only the driving profile is deployed on the public server. Asking it for
# /foot/ returns the driving numbers under a walking name, which would put a
# car's route and a car's speed behind the word "walk" -- so the profile is
# fixed here and the planner keeps its own per-mode speeds.
_PROFILE = "driving"


def _metres(value: object) -> float | None:
    """One cell of the table, or None if it is not a distance.

    OSRM writes ``null`` for a destination it cannot reach. Anything else
    unexpected in that cell is treated the same way, because a fare is about to
    be built on it.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    metres = float(value)
    return metres if metres >= 0 else None


class OsrmRouting:
    """One table call per search: one origin against every candidate."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        # The seam the tests drive: httpx.MockTransport answers in-process, so
        # no test in this suite can reach the real router. None is the network.
        self._transport = transport

    async def road_metres(
        self, origin: tuple[float, float], destinations: Sequence[tuple[float, float]]
    ) -> list[float | None]:
        destinations = list(destinations)
        if not destinations:
            return []
        # The one answer every failure below returns. Named once so no branch
        # can accidentally return a shorter list than it was asked about.
        unanswered: list[float | None] = [None] * len(destinations)

        # OSRM takes its coordinates lng,lat -- the opposite order to the pairs
        # used everywhere else in this codebase, which is worth saying out loud
        # because swapping them silently returns distances across the Pacific.
        points = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in (origin, *destinations))
        # The query is written into the URL rather than handed to httpx as
        # params, so the comma in "distance,duration" stays a comma. httpx would
        # percent-encode it, and this is the exact URL shape the service was
        # verified against.
        url = (
            f"{self._base_url}/table/v1/{_PROFILE}/{points}"
            "?sources=0&annotations=distance,duration"
        )

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.get(url)
            if response.status_code != 200:
                return unanswered
            body = response.json()
        except Exception:
            # Deliberately everything: a timeout, a refused connection, a DNS
            # failure, a body that is not JSON, and whatever else a third-party
            # service invents. None of them is worth more than the straight
            # line, and all of them are worth less than a working page.
            return unanswered

        if not isinstance(body, dict) or body.get("code") != "Ok":
            return unanswered
        distances = body.get("distances")
        if not isinstance(distances, list) or not distances:
            return unanswered
        row = distances[0]
        # sources=0 asks about exactly one origin, so the table is one row, and
        # its first cell is the origin measured against itself. The rest line up
        # with the destinations in the order they were sent.
        if not isinstance(row, list) or len(row) != len(destinations) + 1:
            return unanswered
        return [_metres(cell) for cell in row[1:]]
