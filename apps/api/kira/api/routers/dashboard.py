"""Today dashboard endpoint; arithmetic stays below the transport layer."""

from __future__ import annotations

from fastapi import APIRouter

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import DashboardTodayResponse
from kira.services.clock import today_for
from kira.services.dashboard import DashboardToday, today_dashboard

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


@router.get("/today", response_model=DashboardTodayResponse)
async def get_today(user: CurrentUser, session: SessionDep) -> DashboardToday:
    return await today_dashboard(session, user, today_for())
