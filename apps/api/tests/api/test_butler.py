"""The Butler over HTTP: the stream, the approval round trip, and memory."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest

from kira.api.deps import stream_session_factory
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


@pytest.fixture
async def butler_client(client, session):
    """Point the streaming endpoints at the same in-memory session."""

    @asynccontextmanager
    async def shared():
        yield session

    client._transport.app.dependency_overrides[stream_session_factory] = lambda: shared
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


def parse(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


class TestThread:
    async def test_it_requires_a_token(self, client):
        assert (await client.get("/v1/butler/thread")).status_code == 401

    async def test_it_creates_the_conversation_on_first_read(self, butler_client):
        body = (await butler_client.get("/v1/butler/thread")).json()
        assert body["messages"] == []
        assert body["pending_approvals"] == []
        assert body["id"]


class TestAsking:
    async def test_the_stream_ends_with_done(self, butler_client):
        response = await butler_client.post(
            "/v1/butler/messages", json={"text": "Can I afford RM20 lunch?"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        stream = parse(response.text)
        assert stream[-1]["type"] == "done"

    async def test_the_events_arrive_in_order(self, butler_client):
        stream = parse(
            (
                await butler_client.post(
                    "/v1/butler/messages", json={"text": "Can I afford RM20 lunch?"}
                )
            ).text
        )
        kinds = [event["type"] for event in stream]
        assert kinds[0] == "message"
        assert "thinking" in kinds
        assert kinds.index("tool") < kinds.index("evidence")
        assert kinds.index("evidence") < kinds.index("token")
        assert kinds.count("done") == 1

    async def test_the_evidence_is_the_tools_own_rows(self, butler_client):
        stream = parse(
            (
                await butler_client.post(
                    "/v1/butler/messages", json={"text": "Can I afford RM20 lunch?"}
                )
            ).text
        )
        done = stream[-1]
        assert ["Safe to spend today", "RM52.97"] in done["evidence"]
        assert done["tools_used"] == ["calculate_safe_to_spend"]

    async def test_both_turns_are_persisted(self, butler_client):
        await butler_client.post(
            "/v1/butler/messages", json={"text": "Can I afford RM20 lunch?"}
        )
        body = (await butler_client.get("/v1/butler/thread")).json()
        assert [message["role"] for message in body["messages"]] == ["user", "kira"]
        assert body["messages"][1]["evidence"]

    async def test_an_attachment_is_read_and_kept_with_the_turn(self, butler_client):
        attachment = {
            "kind": "receipt",
            "merchant": "Nasi Kandar Pelita",
            "amount_sen": 1890,
            "confidence": 94,
            "fields": [{"label": "Total", "value": "RM18.90", "confidence": 94}],
        }
        stream = parse(
            (
                await butler_client.post(
                    "/v1/butler/messages",
                    json={"text": "What does this receipt do to my day?",
                          "attachment": attachment},
                )
            ).text
        )
        assert "inspect_attachment" in stream[-1]["tools_used"]
        body = (await butler_client.get("/v1/butler/thread")).json()
        assert body["messages"][0]["attachment"]["merchant"] == "Nasi Kandar Pelita"


class TestMemories:
    async def test_a_learned_fact_is_listed_and_correctable(self, butler_client):
        await butler_client.post(
            "/v1/butler/messages", json={"text": "I split rent with my housemate."}
        )
        memories = (await butler_client.get("/v1/butler/memories")).json()
        assert len(memories) == 1
        assert memories[0]["kind"] == "person"

        fixed = await butler_client.patch(
            f"/v1/butler/memories/{memories[0]['id']}",
            json={"fact": "Splits rent with Aida, RM900 each."},
        )
        assert fixed.status_code == 200
        assert fixed.json()["fact"] == "Splits rent with Aida, RM900 each."
        assert fixed.json()["confidence"] == 100

    async def test_a_fact_can_be_deleted(self, butler_client):
        await butler_client.post(
            "/v1/butler/messages", json={"text": "I split rent with my housemate."}
        )
        memories = (await butler_client.get("/v1/butler/memories")).json()
        assert (
            await butler_client.delete(f"/v1/butler/memories/{memories[0]['id']}")
        ).status_code == 204
        assert (await butler_client.get("/v1/butler/memories")).json() == []

    async def test_deleting_something_else_is_a_404(self, butler_client):
        response = await butler_client.delete(
            "/v1/butler/memories/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404


class TestApprovals:
    async def test_a_write_surfaces_as_a_pending_approval(self, butler_client):
        stream = parse(
            (
                await butler_client.post(
                    "/v1/butler/messages",
                    json={"text": "Remember that I split rent with Aida."},
                )
            ).text
        )
        approval = [event for event in stream if event["type"] == "approval"]
        assert len(approval) == 1
        assert approval[0]["tool"] == "remember"

        thread = (await butler_client.get("/v1/butler/thread")).json()
        assert len(thread["pending_approvals"]) == 1
        assert thread["pending_approvals"][0]["summary"].startswith("Remember:")

    async def test_accepting_applies_it(self, butler_client):
        await butler_client.post(
            "/v1/butler/messages", json={"text": "Remember that I split rent with Aida."}
        )
        thread = (await butler_client.get("/v1/butler/thread")).json()
        approval_id = thread["pending_approvals"][0]["id"]

        response = await butler_client.post(
            f"/v1/butler/approvals/{approval_id}/respond", json={"action": "accept"}
        )
        assert response.status_code == 200
        assert parse(response.text)[-1]["type"] == "done"

        assert (await butler_client.get("/v1/butler/memories")).json()
        assert (await butler_client.get("/v1/butler/thread")).json()["pending_approvals"] == []

    async def test_rejecting_changes_nothing_and_closes_the_card(self, butler_client):
        await butler_client.post(
            "/v1/butler/messages", json={"text": "Remember that I split rent with Aida."}
        )
        thread = (await butler_client.get("/v1/butler/thread")).json()
        approval_id = thread["pending_approvals"][0]["id"]

        await butler_client.post(
            f"/v1/butler/approvals/{approval_id}/respond", json={"action": "reject"}
        )
        assert (await butler_client.get("/v1/butler/memories")).json() == []
        assert (await butler_client.get("/v1/butler/thread")).json()["pending_approvals"] == []

    async def test_deciding_twice_is_refused(self, butler_client):
        await butler_client.post(
            "/v1/butler/messages", json={"text": "Remember that I split rent with Aida."}
        )
        thread = (await butler_client.get("/v1/butler/thread")).json()
        approval_id = thread["pending_approvals"][0]["id"]
        await butler_client.post(
            f"/v1/butler/approvals/{approval_id}/respond", json={"action": "accept"}
        )
        again = await butler_client.post(
            f"/v1/butler/approvals/{approval_id}/respond", json={"action": "accept"}
        )
        assert again.status_code == 409
