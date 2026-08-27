"""Receipt and voice capture: a proposal with confidences, and nothing written."""

from __future__ import annotations

import pytest

from kira.config import get_settings
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


@pytest.fixture
async def signed_in(client, session):
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


class TestAvailability:
    async def test_it_needs_a_token(self, client):
        assert (await client.get("/v1/capture")).status_code == 401

    async def test_it_tells_the_client_what_to_offer(self, signed_in):
        body = (await signed_in.get("/v1/capture")).json()
        assert body["receipt"] is True
        assert body["voice"] is True
        assert body["max_bytes"] == get_settings().capture_max_bytes


class TestReceipt:
    async def test_it_reads_the_fields_with_confidences(self, signed_in):
        response = await signed_in.post(
            "/v1/capture/receipt", files={"image": ("receipt.jpg", b"pretend-jpeg")}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["merchant"] == "Nasi Kandar Pelita"
        assert body["amount_sen"] == 1890
        assert body["confidence"] == 94
        assert [field["label"] for field in body["fields"]] == [
            "Merchant",
            "Total",
            "Date",
            "Category",
        ]
        assert body["fields"][3]["confidence"] < body["fields"][0]["confidence"]

    async def test_an_empty_upload_is_refused(self, signed_in):
        response = await signed_in.post(
            "/v1/capture/receipt", files={"image": ("nothing.jpg", b"")}
        )
        assert response.status_code == 422

    async def test_nothing_reaches_the_ledger(self, signed_in):
        before = (await signed_in.get("/v1/transactions")).json()
        await signed_in.post(
            "/v1/capture/receipt", files={"image": ("receipt.jpg", b"pretend-jpeg")}
        )
        assert (await signed_in.get("/v1/transactions")).json() == before


class TestVoice:
    async def test_it_returns_the_transcript_and_a_proposal(self, signed_in):
        response = await signed_in.post(
            "/v1/capture/voice", files={"audio": ("note.webm", b"pretend-audio")}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["transcript"].startswith("Grab from the office")
        assert body["amount_sen"] == 1400
        assert body["kind"] == "voice"

    async def test_a_disabled_channel_says_so(self, signed_in, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "capture_voice_enabled", False)
        response = await signed_in.post(
            "/v1/capture/voice", files={"audio": ("note.webm", b"pretend-audio")}
        )
        assert response.status_code == 503


class TestSavingWhatWasRead:
    async def test_a_capture_can_become_a_draft_and_only_a_draft(self, signed_in):
        read = (
            await signed_in.post(
                "/v1/capture/receipt", files={"image": ("receipt.jpg", b"pretend-jpeg")}
            )
        ).json()
        created = await signed_in.post(
            "/v1/transactions",
            json={
                "merchant": read["merchant"],
                "amount_sen": read["amount_sen"],
                "occurred_on": read["occurred_on"],
                "category": read["category"],
                "source": read["source"],
                "confidence": read["confidence"],
                "note": read["note"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "draft"

        ledger = (await signed_in.get("/v1/transactions")).json()
        saved = [
            draft for draft in ledger["drafts"] if draft["id"] == created.json()["id"]
        ]
        assert saved and saved[0]["source"] == "receipt"
        assert saved[0]["confidence"] == 94

    async def test_a_negative_amount_is_refused(self, signed_in):
        response = await signed_in.post(
            "/v1/transactions",
            json={"merchant": "Nowhere", "amount_sen": -1, "occurred_on": "2026-09-03"},
        )
        assert response.status_code == 422
