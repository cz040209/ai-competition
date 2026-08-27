"""Golden conversations: fixed question, asserted tools, asserted evidence.

No network and no API key. What is being pinned is the graph's behaviour —
which tools ran, what they returned, and what reached the approval boundary —
not the model's prose.
"""

from __future__ import annotations

from kira.agent.run import run_turn
from kira.db.models import TXN_CONFIRMED, TXN_DRAFT, Transaction
from kira.money import Money
from tests.agent.conftest import offline_factory


async def ask(session, butler, today, text, **kwargs):
    user, thread = butler
    return await run_turn(
        session,
        user,
        thread,
        text=text,
        today=today,
        model_factory=offline_factory,
        **kwargs,
    )


def labels(result) -> list[str]:
    return [label for label, _ in result.evidence]


class TestAffordability:
    async def test_it_checks_the_amount_against_todays_room(self, session, butler, today):
        result = await ask(session, butler, today, "Can I afford RM60 dinner tonight?")
        assert result.tools_used == ["calculate_safe_to_spend"]
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"
        assert dict(result.evidence)["Dinner"] == "RM60.00"
        assert "Over by" in labels(result)

    async def test_a_smaller_amount_fits(self, session, butler, today):
        result = await ask(session, butler, today, "Can I afford RM20 lunch?")
        assert dict(result.evidence)["Left after it"] == "RM32.97"

    async def test_the_answer_carries_the_number(self, session, butler, today):
        result = await ask(session, butler, today, "Can I afford RM20 lunch?")
        assert "RM20" in result.answer
        assert result.answer.strip()


class TestWhyItMoved:
    async def test_it_reads_the_snapshot_and_the_ledger(self, session, butler, today):
        result = await ask(session, butler, today, "Why did safe-to-spend drop?")
        assert result.tools_used == ["get_financial_snapshot", "list_activity"]
        assert dict(result.evidence)["Balance"] == "RM4,180.40"
        assert dict(result.evidence)["Reserved for bills"] == "RM2,003.00"
        assert dict(result.evidence)["Buffer held back"] == "RM800.00"


class TestGoals:
    async def test_it_reads_the_goals(self, session, butler, today):
        result = await ask(session, butler, today, "How is my wedding goal doing?")
        assert result.tools_used == ["list_goals"]
        assert "Wedding" in labels(result)
        assert "Wedding" in result.answer


class TestBills:
    async def test_it_reads_the_commitments(self, session, butler, today):
        result = await ask(session, butler, today, "What bills are due?")
        assert result.tools_used == ["list_commitments"]
        assert "Rent · protected" in labels(result)


class TestEvidenceIsRecordedNotClaimed:
    async def test_every_row_came_from_a_tool_that_ran(self, session, butler, today):
        result = await ask(session, butler, today, "Where do I stand today?")
        assert result.tools_used
        assert result.evidence
        for label, value in result.evidence:
            assert isinstance(label, str) and label
            assert isinstance(value, str) and value

    async def test_the_numbers_track_the_ledger(self, session, butler, today):
        """Confirm a transaction and the evidence moves with it, not with the prose."""
        user, _ = butler
        before = await ask(session, butler, today, "Where do I stand today?")
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Zus Coffee",
                amount=Money(1200),
                category="food",
                occurred_on=today,
                status=TXN_CONFIRMED,
                source="manual",
            )
        )
        await session.flush()
        after = await ask(session, butler, today, "Where do I stand today?")
        assert dict(before.evidence)["Safe to spend today"] == "RM52.97"
        assert dict(after.evidence)["Safe to spend today"] == "RM40.42"

    async def test_a_draft_moves_nothing(self, session, butler, today):
        user, _ = butler
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Big draft",
                amount=Money(50000),
                category="food",
                occurred_on=today,
                status=TXN_DRAFT,
                source="manual",
            )
        )
        await session.flush()
        result = await ask(session, butler, today, "Where do I stand today?")
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"


class TestAttachments:
    """Receipt and voice capture reach the Butler as an attachment on the turn."""

    RECEIPT = {
        "kind": "receipt",
        "merchant": "Nasi Kandar Pelita",
        "amount_sen": 1890,
        "occurred_on": "2026-09-03",
        "category": "food",
        "confidence": 94,
        "note": "Line item total matched.",
        "fields": [
            {"label": "Merchant", "value": "Nasi Kandar Pelita", "confidence": 94},
            {"label": "Total", "value": "RM18.90", "confidence": 94},
        ],
    }

    async def test_it_reads_what_was_scanned(self, session, butler, today):
        result = await ask(
            session,
            butler,
            today,
            "What does this receipt do to my day?",
            attachment=self.RECEIPT,
        )
        assert "inspect_attachment" in result.tools_used
        assert "calculate_safe_to_spend" in result.tools_used
        assert dict(result.evidence)["Merchant"] == "Nasi Kandar Pelita · 94% sure"
        assert dict(result.evidence)["On the ledger"] == "not until you confirm it"

    async def test_the_amount_read_is_the_amount_tested(self, session, butler, today):
        result = await ask(
            session,
            butler,
            today,
            "What does this receipt do to my day?",
            attachment=self.RECEIPT,
        )
        assert dict(result.evidence)["Left after it"] == "RM34.07"

    async def test_without_an_attachment_it_says_so(self, session, butler, today):
        result = await ask(session, butler, today, "What did that receipt say?")
        assert dict(result.evidence)["Attachment"] == "none on this message"
