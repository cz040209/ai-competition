"""Goals: progress, what-ifs, and the changes the Butler proposes."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.db.models import HORIZON_LONG, HORIZON_SHORT
from kira.money import Money
from kira.services import goals as goal_service

MODULE = "goals"


class NoArgs(BaseModel):
    """Takes nothing."""


class ProjectArgs(BaseModel):
    goal_id: uuid.UUID = Field(description="The goal to project.")
    monthly_sen: int = Field(
        gt=0, description="The monthly contribution to test, in sen. Changes nothing."
    )


class CreateGoalArgs(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    horizon: str = Field(description=f"'{HORIZON_SHORT}' or '{HORIZON_LONG}'.")
    target_sen: int = Field(gt=0, description="What the goal costs, in sen.")
    monthly_sen: int = Field(gt=0, description="What to set aside each month, in sen.")
    saved_sen: int = Field(default=0, ge=0, description="Already put aside, in sen.")
    note: str = Field(default="", max_length=280)


class UpdateGoalArgs(BaseModel):
    # A Plan card has the stable id, but a person says "Emergency top-up". Both
    # routes end at the same owned-row lookup before anything can be approved.
    goal_id: uuid.UUID | None = None
    target_goal_name: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=80)
    target_sen: int | None = Field(default=None, gt=0)
    monthly_sen: int | None = Field(default=None, gt=0)
    saved_sen: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=280)

    @model_validator(mode="after")
    def _one_goal_identifier(self) -> UpdateGoalArgs:
        if (self.goal_id is None) == (self.target_goal_name is None):
            raise ValueError("provide exactly one of goal_id or target_goal_name")
        return self


def _months(count: int) -> str:
    return "1 month" if count == 1 else f"{count} months"


async def _list(ctx: ToolContext, _: NoArgs) -> ToolResult:
    views = await goal_service.list_goals(ctx.session, ctx.user)
    currency = ctx.currency
    value = [
        {
            "id": str(view.id),
            "name": view.name,
            "horizon": view.horizon,
            "target_sen": view.target_sen,
            "saved_sen": view.saved_sen,
            "monthly_sen": view.monthly_sen,
            "months_left": view.months_left,
        }
        for view in views
    ]
    evidence = tuple(
        EvidenceRow(
            view.name,
            f"{money_str(Money(view.saved_sen, currency))} of "
            f"{money_str(Money(view.target_sen, currency))} · "
            f"{_months(view.months_left)} left",
        )
        for view in views
    )
    return ToolResult(value, evidence)


async def _project(ctx: ToolContext, args: ProjectArgs) -> ToolResult:
    projection = await goal_service.project_goal(
        ctx.session, ctx.user, args.goal_id, args.monthly_sen
    )
    currency = ctx.currency
    moved = projection.months_moved
    value = {
        "id": str(projection.id),
        "name": projection.name,
        "monthly_sen": projection.monthly_sen,
        "months_left": projection.months_left,
        "proposed_monthly_sen": projection.proposed_monthly_sen,
        "proposed_months_left": projection.proposed_months_left,
        "months_moved": moved,
    }
    evidence = (
        EvidenceRow(f"{projection.name} — now", money_str(Money(projection.monthly_sen, currency))),
        EvidenceRow("Ready in", _months(projection.months_left)),
        EvidenceRow(
            "If changed to", money_str(Money(projection.proposed_monthly_sen, currency))
        ),
        EvidenceRow(
            "Ready in",
            f"{_months(projection.proposed_months_left)}"
            + ("" if moved == 0 else f" ({moved:+d})"),
        ),
    )
    return ToolResult(value, evidence)


async def _create(ctx: ToolContext, args: CreateGoalArgs) -> ToolResult:
    view = await goal_service.create_goal(
        ctx.session,
        ctx.user,
        name=args.name,
        horizon=args.horizon,
        target_sen=args.target_sen,
        monthly_sen=args.monthly_sen,
        saved_sen=args.saved_sen,
        note=args.note,
    )
    return ToolResult({"id": str(view.id), "name": view.name}, ())


async def _update(ctx: ToolContext, args: UpdateGoalArgs) -> ToolResult:
    goal_id = args.goal_id
    if goal_id is None:
        wanted = args.target_goal_name.casefold() if args.target_goal_name else ""
        goal = next(
            (goal for goal in await goal_service.list_goals(ctx.session, ctx.user) if goal.name.casefold() == wanted),
            None,
        )
        if goal is None:
            raise goal_service.GoalNotFound(args.target_goal_name or "")
        goal_id = goal.id
    view = await goal_service.update_goal(
        ctx.session,
        ctx.user,
        goal_id,
        name=args.name,
        target_sen=args.target_sen,
        monthly_sen=args.monthly_sen,
        saved_sen=args.saved_sen,
        note=args.note,
    )
    return ToolResult(
        {"id": str(view.id), "name": view.name, "months_left": view.months_left}, ()
    )


def _summarise_create(args: CreateGoalArgs) -> str:
    return (
        f"Create the goal “{args.name}”: RM{Money(args.target_sen).ringgit_str()} target, "
        f"RM{Money(args.monthly_sen).ringgit_str()} a month."
    )


def _summarise_update(args: UpdateGoalArgs) -> str:
    changes = []
    if args.name is not None:
        changes.append(f"rename to “{args.name}”")
    if args.target_sen is not None:
        changes.append(f"target RM{Money(args.target_sen).ringgit_str()}")
    if args.monthly_sen is not None:
        changes.append(f"RM{Money(args.monthly_sen).ringgit_str()} a month")
    if args.saved_sen is not None:
        changes.append(f"saved RM{Money(args.saved_sen).ringgit_str()}")
    if args.note is not None:
        changes.append("change the note")
    target = args.target_goal_name or str(args.goal_id)
    return f"Update goal {target}: {', '.join(changes) or 'no change'}."


SPECS = (
    ToolSpec(
        name="list_goals",
        module=MODULE,
        kind="read",
        label="Reading your goals",
        description=(
            "Every goal with its target, what is saved, the monthly contribution and how "
            "many months remain."
        ),
        args_model=NoArgs,
        handler=_list,
    ),
    ToolSpec(
        name="project_goal",
        module=MODULE,
        kind="read",
        label="Projecting a goal",
        description=(
            "Answer 'what if I put aside this much' for one goal, reporting how the "
            "finish date moves. Changes nothing."
        ),
        args_model=ProjectArgs,
        handler=_project,
    ),
    ToolSpec(
        name="create_goal",
        module=MODULE,
        kind="write",
        label="Creating a goal",
        description=(
            "Start a new savings goal. Its monthly contribution is reserved before "
            "safe-to-spend."
        ),
        args_model=CreateGoalArgs,
        handler=_create,
        summarise=_summarise_create,
    ),
    ToolSpec(
        name="update_goal",
        module=MODULE,
        kind="write",
        label="Updating a goal",
        description="Change a goal's name, target, monthly contribution, saved amount or note.",
        args_model=UpdateGoalArgs,
        handler=_update,
        summarise=_summarise_update,
    ),
)
