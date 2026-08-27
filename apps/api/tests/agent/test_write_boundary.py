"""The write boundary, tested from the outside: propose a write, change nothing."""

from __future__ import annotations

from sqlalchemy import func, select

from kira.agent.run import resume_approval, run_turn
from kira.db.models import (
    APPROVAL_APPLIED,
    APPROVAL_PENDING,
    TXN_CONFIRMED,
    TXN_DRAFT,
    AuditEvent,
    ButlerApproval,
    Commitment,
    Goal,
    Transaction,
)
from kira.money import Money
from tests.agent.conftest import scripted_factory


async def count(session, model, **where) -> int:
    query = select(func.count()).select_from(model)
    for column, value in where.items():
        query = query.where(getattr(model, column) == value)
    return (await session.execute(query)).scalar_one()


async def a_draft(session, user, today, amount=1890) -> Transaction:
    txn = Transaction(
        user_id=user.id,
        merchant="Nasi Kandar Pelita",
        amount=Money(amount),
        category="food",
        occurred_on=today,
        status=TXN_DRAFT,
        source="receipt",
        confidence=94,
    )
    session.add(txn)
    await session.flush()
    return txn


class TestAWriteStopsAtTheBoundary:
    async def test_it_raises_one_approval_and_changes_nothing(self, session, butler, today):
        user, thread = butler
        draft = await a_draft(session, user, today)
        confirmed_before = await count(session, Transaction, status=TXN_CONFIRMED)

        result = await run_turn(
            session,
            user,
            thread,
            text="Confirm that lunch",
            today=today,
            model_factory=scripted_factory(
                ("confirm_draft", {"transaction_id": str(draft.id)})
            ),
        )

        assert result.approval is not None
        assert result.approval["tool"] == "confirm_draft"
        assert await count(session, ButlerApproval, status=APPROVAL_PENDING) == 1
        assert await count(session, Transaction, status=TXN_CONFIRMED) == confirmed_before
        assert draft.status == TXN_DRAFT

    async def test_the_summary_is_what_the_user_will_read(self, session, butler, today):
        user, thread = butler
        draft = await a_draft(session, user, today)
        result = await run_turn(
            session,
            user,
            thread,
            text="Bin that draft",
            today=today,
            model_factory=scripted_factory(
                ("discard_draft", {"transaction_id": str(draft.id)})
            ),
        )
        assert str(draft.id) in result.approval["summary"]
        assert result.approval["summary"].startswith("Discard")

    async def test_reads_run_first_so_the_card_arrives_with_its_evidence(
        self, session, butler, today
    ):
        user, thread = butler
        draft = await a_draft(session, user, today)
        result = await run_turn(
            session,
            user,
            thread,
            text="Confirm that and tell me where it leaves me",
            today=today,
            model_factory=scripted_factory(
                ("get_financial_snapshot", {}),
                ("confirm_draft", {"transaction_id": str(draft.id)}),
            ),
        )
        assert result.approval is not None
        assert "Safe to spend today" in dict(result.evidence)


class TestDeciding:
    async def test_accepting_applies_it_and_writes_an_audit_event(
        self, session, butler, today
    ):
        user, thread = butler
        draft = await a_draft(session, user, today)
        factory = scripted_factory(("confirm_draft", {"transaction_id": str(draft.id)}))
        first = await run_turn(
            session, user, thread, text="Confirm it", today=today, model_factory=factory
        )
        approval = (
            await session.execute(select(ButlerApproval).limit(1))
        ).scalar_one()

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )

        assert first.approval is not None
        assert result.applied == {
            "tool": "confirm_draft",
            "summary": approval.summary,
        }
        assert draft.status == TXN_CONFIRMED
        assert approval.status == APPROVAL_APPLIED
        assert await count(session, AuditEvent, action="butler.confirm_draft") == 1
        assert approval.audit_event_id is not None

    async def test_rejecting_changes_nothing(self, session, butler, today):
        user, thread = butler
        draft = await a_draft(session, user, today)
        factory = scripted_factory(("confirm_draft", {"transaction_id": str(draft.id)}))
        await run_turn(
            session, user, thread, text="Confirm it", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "reject"},
            today=today,
            model_factory=factory,
        )

        assert result.applied is None
        assert draft.status == TXN_DRAFT
        assert approval.status == APPROVAL_PENDING
        assert await count(session, AuditEvent) == 0

    async def test_an_edit_is_revalidated_before_it_runs(self, session, butler, today):
        """The row is not a licence to execute whatever it happens to contain."""
        user, thread = butler
        goal = (await session.execute(select(Goal).limit(1))).scalar_one()
        factory = scripted_factory(
            ("update_goal", {"goal_id": str(goal.id), "monthly_sen": 60000})
        )
        await run_turn(
            session, user, thread, text="Put more aside", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()
        before = goal.monthly

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "edit", "args": {"goal_id": str(goal.id), "monthly_sen": -5}},
            today=today,
            model_factory=factory,
        )

        assert result.applied is None
        assert goal.monthly == before
        assert approval.status == APPROVAL_PENDING


class TestProtectedResources:
    async def test_a_protected_bill_is_refused_before_anything_runs(
        self, session, butler, today
    ):
        user, thread = butler
        rent = (
            await session.execute(select(Commitment).where(Commitment.protected.is_(True)))
        ).scalars().first()
        result = await run_turn(
            session,
            user,
            thread,
            text="Cut the rent",
            today=today,
            model_factory=scripted_factory(
                ("update_commitment", {"commitment_id": str(rent.id), "amount_sen": 1000})
            ),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0
        assert rent.amount == Money(120000)

    async def test_the_buffer_cannot_be_named_in_any_call(self, session, butler, today):
        user, thread = butler
        result = await run_turn(
            session,
            user,
            thread,
            text="Drop my buffer to nothing",
            today=today,
            model_factory=scripted_factory(("update_goal", {"buffer_sen": 0})),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0

    async def test_an_unknown_tool_is_refused(self, session, butler, today):
        user, thread = butler
        result = await run_turn(
            session,
            user,
            thread,
            text="Pay my rent",
            today=today,
            model_factory=scripted_factory(("apply_plan_change", {"amount_sen": 100})),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0

    async def test_only_one_write_is_proposed_at_a_time(self, session, butler, today):
        user, thread = butler
        first = await a_draft(session, user, today)
        second = await a_draft(session, user, today, amount=1400)
        result = await run_turn(
            session,
            user,
            thread,
            text="Confirm both",
            today=today,
            model_factory=scripted_factory(
                ("confirm_draft", {"transaction_id": str(first.id)}),
                ("confirm_draft", {"transaction_id": str(second.id)}),
            ),
        )
        assert await count(session, ButlerApproval) == 1
        assert result.approval["args"]["transaction_id"] == str(first.id)

    async def test_bad_arguments_are_refused_with_a_reason(self, session, butler, today):
        user, thread = butler
        before = await count(session, Transaction)
        result = await run_turn(
            session,
            user,
            thread,
            text="Add a transaction",
            today=today,
            model_factory=scripted_factory(
                ("add_transaction", {"merchant": "", "amount_sen": -1})
            ),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0
        assert await count(session, Transaction) == before


class TestApprovalIdempotence:
    async def test_a_replayed_node_does_not_ask_twice(self, session, butler, today):
        """A resumed graph re-runs the node from its start; one question, one row."""
        user, thread = butler
        draft = await a_draft(session, user, today)
        factory = scripted_factory(("confirm_draft", {"transaction_id": str(draft.id)}))
        await run_turn(
            session, user, thread, text="Confirm it", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()
        await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )
        assert await count(session, ButlerApproval) == 1
