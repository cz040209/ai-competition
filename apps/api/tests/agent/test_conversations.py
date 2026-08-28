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


class TestLoggingSpending:
    """A sentence about money already spent is a proposal to log it.

    People do not speak in fields. "Grabbed lunch at the mamak, twelve fifty" has
    to reach the same approval card as a structured request, and reach it without
    touching the ledger on the way.
    """

    async def test_it_proposes_the_transaction_it_heard(self, session, butler, today):
        result = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert result.approval is not None
        assert result.approval["tool"] == "add_transaction"
        assert result.approval["args"]["amount_sen"] == 1250

    async def test_it_hears_an_amount_that_was_spoken_rather_than_typed(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "Grabbed lunch at the mamak, twelve fifty")
        assert result.approval["args"]["amount_sen"] == 1250

    async def test_it_reads_the_merchant_out_of_the_sentence(self, session, butler, today):
        result = await ask(session, butler, today, "I paid RM45 at Village Grocer")
        assert result.approval["args"]["merchant"] == "Village Grocer"

    async def test_it_infers_the_category_rather_than_hardcoding_one(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "Topped up petrol, RM60")
        assert result.approval["args"]["category"] == "transport"

    async def test_it_dates_it_today_unless_told_otherwise(self, session, butler, today):
        result = await ask(session, butler, today, "Bought roti canai for RM4")
        assert result.approval["args"]["occurred_on"] == today.isoformat()

    async def test_yesterday_means_yesterday(self, session, butler, today):
        result = await ask(session, butler, today, "I spent RM30 on groceries yesterday")
        expected = today.fromordinal(today.toordinal() - 1)
        assert result.approval["args"]["occurred_on"] == expected.isoformat()

    async def test_without_an_amount_it_asks_instead_of_inventing_one(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "I bought lunch at the mamak")
        assert result.approval is None
        assert "how much" in result.answer.lower()

    async def test_nothing_reaches_the_ledger_before_the_user_approves(
        self, session, butler, today
    ):
        from sqlalchemy import func, select

        async def rows() -> int:
            return (
                await session.execute(select(func.count()).select_from(Transaction))
            ).scalar_one()

        before = await rows()
        result = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert result.approval is not None
        assert await rows() == before

    async def test_the_summary_says_what_will_be_added(self, session, butler, today):
        result = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert "RM12.50" in result.approval["summary"]


class TestComposingWhenNoProposalWasMade:
    """The offline model also composes as a safety net for the online one.

    When the vendor returns nothing, `compose` falls back to the offline model
    for the prose alone — with no tool having run. Its answer must describe what
    actually happened, not what the route would have done.
    """

    async def test_it_does_not_claim_a_draft_that_was_never_proposed(self):
        from langchain_core.messages import HumanMessage

        from kira.agent.llm import OfflineChatModel

        reply = await OfflineChatModel().ainvoke(
            [HumanMessage("grabbed lunch at the mamak, twelve fifty")]
        )
        assert "draft" not in str(reply.content).lower()

    async def test_it_still_says_so_once_the_draft_is_real(self, session, butler, today):
        from sqlalchemy import select

        from kira.agent.run import resume_approval
        from kira.db.models import ButlerApproval

        user, thread = butler
        first = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert first.approval is not None
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=offline_factory,
        )
        assert "draft" in result.answer.lower()
