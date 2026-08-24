"""Wire shapes. Money crosses the wire as an integer sen field named *_sen."""

from __future__ import annotations

import uuid
from datetime import date

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
