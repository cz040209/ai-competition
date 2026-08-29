"""Day-planner endpoint: money-constrained place discovery."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import DayPlanResponse, PlanDraftRequest, TransactionResponse
from kira.services.clock import today_for
from kira.services.dashboard import today_dashboard
from kira.services.day_plan import add_to_today, find_places
from kira.services.transactions import InvalidTransaction, TransactionView

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


@router.post("/drafts", status_code=status.HTTP_201_CREATED, response_model=TransactionResponse)
async def post_plan_draft(
    body: PlanDraftRequest, user: CurrentUser, session: SessionDep
) -> TransactionView:
    """Add a planned outing to today. It waits as a draft until it is confirmed.

    Deliberately not a client POST to /v1/transactions with ``source: "plan"``:
    the date is the server's clock, the confidence band's percentage is the
    server's mapping, and the note that says the money has not moved is the
    server's wording. Left to the client, three things a plan draft depends on
    would be restatable by whoever called it.

    Nothing here touches safe-to-spend, and that is the point rather than an
    omission — a draft is excluded from every engine calculation, so the figure
    on Today is the same after this call as before it.
    """
    try:
        view = await add_to_today(
            session,
            user,
            name=body.name,
            total_sen=body.total_sen,
            confidence=body.confidence,
            today=today_for(),
        )
    except InvalidTransaction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return view
