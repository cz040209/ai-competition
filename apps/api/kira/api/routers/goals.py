"""Authenticated REST contracts for deterministic goal planning."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time

from fastapi import APIRouter, HTTPException, status

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import (
    GoalCreateRequest,
    GoalCreateResponse,
    GoalDetailResponse,
    GoalImpactRequest,
    GoalImpactResponse,
    GoalMilestoneResponse,
    GoalPlanResponse,
    GoalScenarioResponse,
    GoalScenariosResponse,
)
from kira.db.models import Goal, GoalPlanRecord
from kira.engine import GoalImpact, GoalScenario
from kira.services.clock import today_for
from kira.services.goal_planning import (
    GoalNotFound,
    InvalidFundingAccount,
    create_draft_goal,
    create_scenarios,
    current_plan_record,
    owned_goal,
    plan_from_record,
    purchase_impact,
)

router = APIRouter(prefix="/v1/goals", tags=["goals"])


def _as_of_utc() -> datetime:
    return datetime.combine(today_for(), time.min, tzinfo=UTC)


def _goal_response(goal: Goal, current_plan_version: int | None = None) -> GoalDetailResponse:
    return GoalDetailResponse(
        goal_id=goal.id,
        user_id=goal.user_id,
        goal_type=goal.goal_type,
        name=goal.name,
        currency=goal.currency,
        target_amount_sen=goal.target.sen,
        current_saved_sen=goal.saved.sen,
        target_date=goal.target_date,
        horizon=goal.horizon,
        priority=goal.priority,
        status=goal.status,
        funding_account_ids=[uuid.UUID(value) for value in goal.funding_account_ids],
        current_plan_version=current_plan_version,
    )


def _plan_response(record: GoalPlanRecord) -> GoalPlanResponse:
    plan = plan_from_record(record)
    return GoalPlanResponse(
        plan_id=record.id,
        goal_id=record.goal_id,
        version=record.version,
        approval_status=record.approval_status,
        feasible=plan.feasible,
        target_amount_sen=plan.target_amount_sen,
        current_saved_sen=plan.current_saved_sen,
        remaining_amount_sen=plan.remaining_amount_sen,
        target_date=plan.target_date,
        required_contribution_per_payday_sen=plan.required_contribution_per_payday_sen,
        next_required_reserve_sen=plan.next_required_reserve_sen,
        projected_completion_date=plan.projected_completion_date,
        milestones=[
            GoalMilestoneResponse(
                percentage=item.percentage,
                amount_sen=item.amount_sen,
                projected_date=item.projected_date,
            )
            for item in plan.milestones
        ],
        risk_flags=list(plan.risk_flags),
        assumptions=list(plan.assumptions),
        calculation_version=plan.calculation_version,
        evidence_refs=list(plan.evidence_refs),
    )


def _scenario_response(scenario: GoalScenario) -> GoalScenarioResponse:
    return GoalScenarioResponse(
        scenario_id=uuid.UUID(scenario.scenario_id),
        goal_id=uuid.UUID(scenario.goal_id),
        label=scenario.label,
        feasible=scenario.feasible,
        contribution_per_payday_sen=scenario.contribution_per_payday_sen,
        target_date=scenario.target_date,
        goal_delay_days=scenario.goal_delay_days,
        flexible_spending_delta_sen=scenario.flexible_spending_delta_sen,
        tradeoffs=list(scenario.tradeoffs),
        risk_flags=list(scenario.risk_flags),
        calculation_version=scenario.calculation_version,
        evidence_refs=list(scenario.evidence_refs),
    )


def _impact_response(impact: GoalImpact) -> GoalImpactResponse:
    return GoalImpactResponse(
        goal_id=uuid.UUID(impact.goal_id),
        proposed_spend_sen=impact.proposed_spend_sen,
        safe_to_spend=impact.safe_to_spend,
        protected_money_touched=impact.protected_money_touched,
        goal_reserve_shortfall_sen=impact.goal_reserve_shortfall_sen,
        projected_completion_date=impact.projected_completion_date,
        goal_delay_days=impact.goal_delay_days,
        flexible_spending_remaining_sen=impact.flexible_spending_remaining_sen,
        risk_flags=list(impact.risk_flags),
        assumptions=list(impact.assumptions),
        calculation_version=impact.calculation_version,
        evidence_refs=list(impact.evidence_refs),
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=GoalCreateResponse)
async def create_goal(
    body: GoalCreateRequest, user: CurrentUser, session: SessionDep
) -> GoalCreateResponse:
    try:
        goal, plan = await create_draft_goal(
            session,
            user,
            goal_type=body.goal_type,
            name=body.name,
            target_amount_sen=body.target_amount_sen,
            current_saved_sen=body.current_saved_sen,
            target_date=body.target_date,
            priority=body.priority,
            funding_account_ids=tuple(body.funding_account_ids),
            as_of_utc=_as_of_utc(),
        )
    except (ValueError, TypeError, InvalidFundingAccount) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return GoalCreateResponse(goal=_goal_response(goal, plan.version), plan=_plan_response(plan))


@router.get("/{goal_id}", response_model=GoalDetailResponse)
async def get_goal(
    goal_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> GoalDetailResponse:
    try:
        goal = await owned_goal(session, user, goal_id)
        plan = await current_plan_record(session, user, goal_id)
    except GoalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found") from exc
    return _goal_response(goal, plan.version)


@router.get("/{goal_id}/plan", response_model=GoalPlanResponse)
async def get_goal_plan(
    goal_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> GoalPlanResponse:
    try:
        record = await current_plan_record(session, user, goal_id)
    except GoalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal plan not found") from exc
    return _plan_response(record)


@router.post("/{goal_id}/scenarios", response_model=GoalScenariosResponse)
async def post_goal_scenarios(
    goal_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> GoalScenariosResponse:
    try:
        scenarios = await create_scenarios(session, user, goal_id, _as_of_utc())
    except GoalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found") from exc
    return GoalScenariosResponse(scenarios=[_scenario_response(item) for item in scenarios])


@router.post("/{goal_id}/impact", response_model=GoalImpactResponse)
async def post_goal_impact(
    goal_id: uuid.UUID,
    body: GoalImpactRequest,
    user: CurrentUser,
    session: SessionDep,
) -> GoalImpactResponse:
    try:
        impact = await purchase_impact(
            session, user, goal_id, body.proposed_spend_sen, _as_of_utc()
        )
    except GoalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal plan not found") from exc
    return _impact_response(impact)
