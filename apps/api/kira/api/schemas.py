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


class PlaceResponse(ResponseModel):
    """One outing, priced on the distance named by ``distance_basis``.

    A fare is charged on the road, so ``km`` is the road distance whenever the
    router answered for this place. Where it did not, ``km`` falls back to the
    great circle, ``road_km`` is null, and ``distance_basis`` says
    ``straight_line`` -- which the screen has to show, because a straight-line
    ride fare in Kuala Lumpur can be half of the real one. The basis is
    per-place: one search routes some destinations and fails on others.
    """

    id: str
    name: str
    kind: str
    address: str
    # The point itself, because the address alone does not always find it: a
    # quarter of them name a locality rather than a doorstep, and several names
    # in the set belong to two branches. A client sending the user to a map has
    # to be able to send them to this one.
    lat: float
    lng: float
    km: float
    road_km: float | None
    distance_basis: Literal["road", "straight_line"]
    travel_sen: int
    minutes: int
    total_sen: int
    # Null on a day with no room left, so no client can turn a stand-in ratio
    # into a percentage or divide its way back to a room that is not there.
    share: float | None
    band: Literal["ok", "tight", "over"]
    confidence: str
    halal: bool
    note: str


class DayPlanResponse(ResponseModel):
    """The places, and the figures they were judged against.

    ``room_sen`` is stated rather than left to be inferred from ``share``: it
    is zero on a day already spent out, and a client dividing to recover it
    would turn that zero into a number the user never had.

    ``nearby_count`` is how many places the radius held before the halal and
    cap filters ran, and ``matching_count`` how many were still standing after
    the halal filter but before the ceiling. Without both, an empty ``places``
    is unreadable: a client would have to guess which of three causes emptied
    it, and would blame the ceiling for a distance no ceiling can close or for
    a halal toggle no ceiling can reach. The counts nest, so the first of them
    that is nil is the cause.
    """

    room_sen: int
    cap_sen: int
    nearby_count: int
    matching_count: int
    places: list[PlaceResponse]


class PlanDraftRequest(BaseModel):
    """A place the user tapped "Add to today" on, as the row showed it.

    ``total_sen`` is the whole outing — meal plus travel — because that is the
    single figure on the row and in the sheet's total. Sending the meal alone
    would put a draft on screen that is not the thing the user added.

    ``confidence`` is the place's own band, not a percentage: what "high" is
    worth is the server's to decide, so two clients cannot come to different
    answers about it. It is typed as a plain string rather than an enum because
    the bands come from a curated data file that is regenerated, and a word this
    build has not seen should cost the user their tap the least — the service
    reads an unfamiliar one as the least certain band.
    """

    name: str = Field(min_length=1, max_length=120)
    total_sen: int = Field(gt=0)
    confidence: str = Field(min_length=1, max_length=16)


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


class CorrectTransactionRequest(BaseModel):
    """What the user says a draft should have read. Every field is optional.

    Omitted means "leave it alone", which is why nothing here defaults to a
    value: a body carrying only ``amount_sen`` must not blank the merchant.
    ``confidence`` is absent on purpose — it is the reader's own figure, and a
    corrected amount clears it rather than letting a client restate it.
    """

    merchant: str | None = Field(default=None, min_length=1, max_length=120)
    amount_sen: int | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=280)
