"""Request-scoped dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import User
from kira.db.session import get_session
from kira.services.auth import AuthError, decode_access_token

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

UNAUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None:
        raise UNAUTHORISED
    try:
        user_id = decode_access_token(credentials.credentials)
    except AuthError as exc:
        raise UNAUTHORISED from exc
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise UNAUTHORISED
    return user


CurrentUser = Annotated[User, Depends(current_user)]
