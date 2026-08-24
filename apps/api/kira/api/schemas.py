"""Wire shapes. Money crosses the wire as an integer sen field named *_sen."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    currency: str
    buffer_sen: int
    next_payday: date
    cycle_start: date
    cycle_days: int
