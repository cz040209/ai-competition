from contextlib import asynccontextmanager

from kira.db import session as session_module


async def test_get_session_opens_the_session_created_by_the_sessionmaker(monkeypatch):
    sentinel = object()

    @asynccontextmanager
    async def fake_session_context():
        yield sentinel

    def fake_sessionmaker():
        return fake_session_context()

    monkeypatch.setattr(session_module, "get_sessionmaker", lambda: fake_sessionmaker)

    dependency = session_module.get_session()
    assert await anext(dependency) is sentinel
    await dependency.aclose()
