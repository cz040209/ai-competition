"""Day-planner endpoint: money-constrained place discovery."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import DayPlanResponse
from kira.services.clock import today_for
from kira.services.dashboard import today_dashboard
from kira.services.day_plan import find_places

router = APIRouter(prefix="/v1/day-plan", tags=["day-plan"])


@router.get("/places", response_model=DayPlanResponse)
async def get_places(
    user: CurrentUser,
    session: SessionDep,
    lat: float = Query(...),
    lng: float = Query(...),
    mode: Literal["walk", "transit", "ride"] = "walk",
    halal_only: bool = False,
    cap_sen: int | None = Query(default=None, gt=0),
    radius_km: float = Query(default=5.0, gt=0),
):
    """The cap only filters the list; the room is what every band is judged on."""
    dashboard = await today_dashboard(session, user, today_for())
    room_sen = dashboard.safe_today_sen
    cap = cap_sen if cap_sen is not None else room_sen
    found = await find_places(
        lat=lat,
        lng=lng,
        mode=mode,
        halal_only=halal_only,
        cap_sen=cap,
        room_sen=room_sen,
        radius_km=radius_km,
    )
    return {
        "room_sen": room_sen,
        "cap_sen": cap,
        "nearby_count": found.nearby_count,
        "matching_count": found.matching_count,
        "places": found.places,
    }
