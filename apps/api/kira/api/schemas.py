"""Wire shapes. Money crosses the wire as an integer sen field named *_sen."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(ResponseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(ResponseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    currency: str
    buffer_sen: int
    next_payday: date
    cycle_start: date
    cycle_days: int


class NextCommitmentResponse(ResponseModel):
    id: uuid.UUID
    name: str
    amount_sen: int
    due_date: date
    days_until: int
    protected: bool


class GoalSummaryResponse(ResponseModel):
    id: uuid.UUID
    name: str
    horizon: str
    target_sen: int
    saved_sen: int
    monthly_sen: int
    months_left: int
    note: str


class DashboardTodayResponse(ResponseModel):
    date: date
    display_name: str
    currency: str
    balance_sen: int
    reserved_sen: int
    buffer_sen: int
    goal_reserve_sen: int
    unclaimed_sen: int
    per_day_sen: int
    spent_today_sen: int
    safe_today_sen: int
    days_to_payday: int
    cycle_elapsed: int
    commitment_count: int
    drafts_waiting: int
    next_commitment: NextCommitmentResponse | None
    goals: list[GoalSummaryResponse]


class TransactionResponse(ResponseModel):
    id: uuid.UUID
    merchant: str
    amount_sen: int
    category: str
    category_label: str
    occurred_on: date
    status: str
    source: str
    confidence: int | None
    note: str


class ActivityDayResponse(ResponseModel):
    date: date
    total_sen: int
    transactions: list[TransactionResponse]


class CategorySummaryResponse(ResponseModel):
    slug: str
    label: str
    spent_this_cycle_sen: int
    count: int


class ActivityResponse(ResponseModel):
    drafts: list[TransactionResponse]
    draft_total_sen: int
    days: list[ActivityDayResponse]
    spent_this_cycle_sen: int
    categories: list[CategorySummaryResponse]


class ButlerMessageResponse(ResponseModel):
    id: uuid.UUID
    role: str
    content: str
    evidence: list[tuple[str, str]]
    attachment: dict | None
    created_at: datetime


class ButlerApprovalResponse(ResponseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    tool: str
    args: dict
    summary: str
    evidence: list[tuple[str, str]]
    status: str
    created_at: datetime


class ButlerThreadResponse(ResponseModel):
    id: uuid.UUID
    title: str
    messages: list[ButlerMessageResponse]
    pending_approvals: list[ButlerApprovalResponse]


class ButlerAskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # A receipt or voice read from /v1/capture, passed back verbatim. It is a
    # proposal the Butler can look at, never a ledger entry.
    attachment: dict | None = None


class ApprovalDecisionRequest(BaseModel):
    action: Literal["accept", "edit", "reject"]
    args: dict | None = None


class CategoryResponse(BaseModel):
    slug: str
    label: str


class MemoryResponse(ResponseModel):
    id: uuid.UUID
    kind: str
    subject: str
    fact: str
    confidence: int
    source_message_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None


class MemoryCorrectionRequest(BaseModel):
    fact: str = Field(min_length=1, max_length=280)


class CaptureFieldResponse(ResponseModel):
    label: str
    value: str
    confidence: int


class CaptureResponse(ResponseModel):
    """What a reader made of a photo or a recording. Nothing is on the ledger."""

    kind: str
    source: str
    merchant: str
    amount_sen: int
    occurred_on: date
    category: str
    confidence: int
    note: str
    transcript: str
    fields: list[CaptureFieldResponse]


class CaptureAvailability(ResponseModel):
    """Whether the affordances should be offered at all."""

    receipt: bool
    voice: bool
    max_bytes: int


class CreateTransactionRequest(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    amount_sen: int = Field(gt=0)
    occurred_on: date
    category: str = Field(default="uncategorised", max_length=40)
    source: str = Field(default="manual", max_length=12)
    confidence: int | None = Field(default=None, ge=0, le=100)
    note: str = Field(default="", max_length=280)


class MoneyOut(ResponseModel):
    sen: int
    currency: str


class GoalOutlookOut(ResponseModel):
    goal_id: str
    target_date: date
    probability_bp: int
    median_shortfall: MoneyOut


class LeverIn(BaseModel):
    kind: Literal["goal_monthly", "commitment_amount", "daily_spend"]
    target_id: str
    delta_sen: int


class LeverOut(ResponseModel):
    kind: str
    target_id: str
    delta: MoneyOut


class DriverOut(ResponseModel):
    lever: LeverOut
    probability_bp_before: int
    probability_bp_after: int
    bp_per_ringgit: int


class ForesightResponse(ResponseModel):
    horizon_days: int
    dates: list[date]
    p10: list[MoneyOut]
    p50: list[MoneyOut]
    p90: list[MoneyOut]
    outlooks: list[GoalOutlookOut]
    drivers: list[DriverOut]
    profile_days: int
    assumption: str


class ScenarioRequest(BaseModel):
    horizon_days: int = Field(default=180, ge=1, le=365)
    levers: list[LeverIn]


class ScenarioResultOut(ResponseModel):
    lever: LeverOut
    outlooks: list[GoalOutlookOut]
    safe_today_after: MoneyOut


class ScenarioComparisonResponse(ResponseModel):
    results: list[ScenarioResultOut]
