"""Password hashing, access tokens, and rotating refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.config import get_settings
from kira.db.models import RefreshToken, User

_hasher = PasswordHasher()

REFRESH_COOKIE = "kira_refresh"


class AuthError(Exception):
    """A failure to prove identity. The API turns it into a 401 response."""


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError):
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("invalid access token") from exc
    if payload.get("typ") != "access":
        raise AuthError("wrong token type")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthError("malformed subject") from exc


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_refresh_token(session: AsyncSession, user: User) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_digest(raw),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await session.flush()
    return raw


async def _load_live_token(session: AsyncSession, raw: str) -> RefreshToken:
    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == _digest(raw)))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise AuthError("unknown or revoked refresh token")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise AuthError("expired refresh token")
    return row


async def rotate_refresh_token(session: AsyncSession, raw: str) -> tuple[User, str]:
    row = await _load_live_token(session, raw)
    row.revoked_at = datetime.now(UTC)
    user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one()
    replacement = await issue_refresh_token(session, user)
    await session.commit()
    return user, replacement


async def revoke_refresh_token(session: AsyncSession, raw: str) -> None:
    try:
        row = await _load_live_token(session, raw)
    except AuthError:
        return
    row.revoked_at = datetime.now(UTC)
    await session.commit()
