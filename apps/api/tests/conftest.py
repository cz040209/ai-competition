"""Shared fixtures. Database tests run against in-memory SQLite without Docker."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

os.environ.setdefault("DEMO_TODAY", "2026-09-03")
os.environ.setdefault("JWT_SECRET", "test-secret-for-kira-auth-tests-123456")
# The suite runs against the deterministic model, always. A developer with a
# real key in their .env would otherwise send every un-stubbed turn to the
# vendor: slow, billable, and impossible to assert prose against.
os.environ.setdefault("BUTLER_OFFLINE", "1")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from kira.db.base import Base
from kira.db.session import get_session


@pytest.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
async def client(session) -> AsyncGenerator[AsyncClient, None]:
    from kira.api.app import create_app

    app = create_app()

    async def override() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
