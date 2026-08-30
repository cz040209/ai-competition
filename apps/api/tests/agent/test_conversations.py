"""Golden conversations: fixed question, asserted tools, asserted evidence.

No network and no API key. What is being pinned is the graph's behaviour —
which tools ran, what they returned, and what reached the approval boundary —
not the model's prose.
"""

from __future__ import annotations

import pytest

from kira.agent.llm import _amount_sen
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


class TestWhereToEat:
    """The day planner, reached by asking rather than by tapping.

    The offline model is the one the demo runs on -- the container carries no
    API key -- so without a route here the Butler answers "where can I eat"
    with today's balance and never touches the planner at all.
    """

    async def test_it_reaches_the_day_planner(self, session, butler, today):
        result = await ask(session, butler, today, "Where can I eat nearby today?")
        assert result.tools_used == ["build_day_plan"]

    async def test_a_question_naming_an_amount_still_goes_to_affordability(
        self, session, butler, today
    ):
        # "Can I afford RM60 dinner" is a question about money, not a request
        # for somewhere to go, and must not be answered with a list of shops.
        result = await ask(session, butler, today, "Can I afford RM60 dinner tonight?")
        assert result.tools_used == ["calculate_safe_to_spend"]

    async def test_the_evidence_states_the_room_it_judged_against(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "Where should I eat?")
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"

    async def test_the_answer_names_a_place_and_a_price(self, session, butler, today):
        result = await ask(session, butler, today, "I'm hungry, where should I go?")
        assert "RM" in result.answer
        assert "estimate" in result.answer.lower()


class TestWhatTheOfflinePlannerDoesWithTheRequest:
    """"Somewhere halal under RM15" used to reach the planner as no arguments.

    The list came back unfiltered and the answer read as though the whole
    sentence had been understood, which on halal is a wrong answer rather than
    a wide one. These run against the fixed world rather than the shipped KL
    set: two of its five places are not halal, which is what makes a dropped
    filter something a test can see instead of something to take on trust.
    """

    async def test_a_halal_request_leaves_the_others_out(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat somewhere halal nearby?")
        assert place_world.near_non_halal.name not in result.answer
        assert place_world.far_non_halal.name not in result.answer

    async def test_the_same_search_without_the_word_returns_them(
        self, session, butler, today, place_world
    ):
        # The other half of the pair. Without it, a filter that had quietly
        # stopped working would still pass the test above.
        result = await ask(session, butler, today, "Where can I eat nearby?")
        assert place_world.near_non_halal.name in result.answer

    async def test_a_price_in_the_request_becomes_the_ceiling(
        self, session, butler, today, place_world
    ):
        # RM10 is a hundred times 10, and the gap between the two survivors is
        # RM3.50 -- so a ceiling read in ringgit, or not read at all, changes
        # which names come back.
        result = await ask(session, butler, today, "Where can I eat for under RM10?")
        assert place_world.cheap.name in result.answer
        assert place_world.mid.name not in result.answer

    async def test_it_states_what_it_read_and_that_it_read_nothing_else(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat somewhere halal under RM15?")
        assert "I read halal only and a ceiling of RM15, and nothing else" in result.answer
        assert "any other condition in it went unread" in result.answer

    async def test_a_request_it_cannot_read_is_answered_as_one_it_could_not_read(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat somewhere quiet with a view?")
        assert "I found neither in what you asked" in result.answer
        assert "nothing in it narrowed this" in result.answer

    async def test_a_ceiling_it_was_given_is_not_narrated_as_todays_room(
        self, session, butler, today, place_world
    ):
        # RM1 admits nothing, and the reason it admits nothing is the user's own
        # ceiling. Today has RM52.97, and saying otherwise would be a claim
        # about their money that no figure here supports.
        result = await ask(session, butler, today, "Where can I eat for under RM1?")
        assert "the ceiling I read out of what you asked" in result.answer
        assert "today itself has room for RM52.97" in result.answer

    async def test_it_names_a_place_it_actually_found(
        self, session, butler, today, place_world
    ):
        # Kopi Kaki is RM9 and 50 m away, so walking is free and the whole
        # outing is the meal. A price range with no name attached is the answer
        # this is here to rule out.
        result = await ask(session, butler, today, "Where can I eat somewhere halal nearby?")
        assert f"{place_world.cheap.name} — RM9 " in result.answer


class TestReadingAnAmountOutOfASentence:
    """The offline parser against the way this app writes ringgit at the user.

    ``Money.ringgit_str`` groups thousands and the house style in
    ``kira.agent.prompt`` says RM1,234.56, so a user quoting a figure back at
    the Butler is quoting one with a group separator in it. Reading that comma
    as a decimal point divides the amount by a thousand, which offline made
    "can I afford RM1,500" a question about RM1.50 — answered yes, in earnest.
    """

    @pytest.mark.parametrize(
        ("text", "sen"),
        [
            ("can I afford RM15?", 1500),
            ("can I afford RM15.50?", 1550),
            ("can I afford RM 15?", 1500),
            ("can I afford 15 ringgit?", 1500),
            # The group separator, which is the one that was wrong.
            ("can I afford RM1,500?", 150_000),
            ("can I afford RM1,200.00?", 120_000),
            ("can I afford RM1,234,567?", 123_456_700),
            # And the decimal comma it has to stay told apart from.
            ("can I afford RM15,50?", 1550),
            ("can I afford RM1,5?", 150),
        ],
    )
    def test_what_a_written_amount_is_worth(self, text, sen):
        assert _amount_sen(text) == sen

    async def test_a_grouped_ceiling_is_not_divided_by_a_thousand(
        self, session, butler, today, place_world
    ):
        # Every place in the fixed world is under RM1,500 and none is under
        # RM1.50, so which of the two the parser read is the difference between
        # a full list and an empty one.
        result = await ask(session, butler, today, "Where can I eat under RM1,500?")
        assert "a ceiling of RM1,500" in result.answer
        assert place_world.cheap.name in result.answer
