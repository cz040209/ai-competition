"""Memory: extraction, supersede, retrieval order, use, and deletion."""

from __future__ import annotations

from sqlalchemy import select

from kira.agent.run import run_turn
from kira.db.models import MEMORY_ACTIVE, MEMORY_DELETED, MEMORY_SUPERSEDED, ButlerMemory
from kira.services.butler_memory import correct, forget, list_memories, remember
from tests.agent.conftest import offline_factory


async def say(session, butler, today, text):
    user, thread = butler
    return await run_turn(
        session, user, thread, text=text, today=today, model_factory=offline_factory
    )


class TestExtraction:
    async def test_a_standing_rule_is_kept(self, session, butler, today):
        await say(session, butler, today, "I never take a taxi before payday.")
        memories = await list_memories(session, butler[0])
        assert [memory.kind for memory in memories] == ["constraint"]
        assert "taxi before payday" in memories[0].fact

    async def test_asking_to_be_remembered_is_a_write_and_waits(
        self, session, butler, today
    ):
        """Passive extraction is free; being told to remember is a proposal."""
        result = await say(session, butler, today, "Remember that I split rent with Aida.")
        assert result.approval is not None
        assert result.approval["tool"] == "remember"
        assert await list_memories(session, butler[0]) == ()

    async def test_a_person_is_kept_as_a_sentence(self, session, butler, today):
        await say(session, butler, today, "I split rent with my housemate every month.")
        memories = await list_memories(session, butler[0])
        assert memories[0].kind == "person"
        assert memories[0].subject == "housemate"
        assert memories[0].fact.startswith("I split rent")

    async def test_an_ordinary_question_is_not_remembered(self, session, butler, today):
        await say(session, butler, today, "Can I afford RM60 dinner tonight?")
        assert await list_memories(session, butler[0]) == ()

    async def test_the_fact_points_back_at_the_message(self, session, butler, today):
        user, thread = butler
        import uuid

        message_id = uuid.uuid4()
        await run_turn(
            session,
            user,
            thread,
            text="I prefer blunt numbers over encouragement.",
            message_id=message_id,
            today=today,
            model_factory=offline_factory,
        )
        memories = await list_memories(session, user)
        assert memories[0].source_message_id == message_id


class TestSupersede:
    async def test_the_same_subject_supersedes_rather_than_overwrites(self, session, butler):
        user, _ = butler
        first = await remember(
            session, user, kind="preference", subject="tone", fact="Wants encouragement."
        )
        second = await remember(
            session, user, kind="preference", subject="tone", fact="Wants blunt numbers."
        )
        rows = {
            row.id: row
            for row in (await session.execute(select(ButlerMemory))).scalars().all()
        }
        assert rows[first.id].status == MEMORY_SUPERSEDED
        assert rows[first.id].superseded_by == second.id
        assert rows[second.id].status == MEMORY_ACTIVE
        assert len(await list_memories(session, user)) == 1

    async def test_a_different_subject_coexists(self, session, butler):
        user, _ = butler
        await remember(session, user, kind="preference", subject="tone", fact="Blunt.")
        await remember(session, user, kind="preference", subject="timing", fact="Mornings.")
        assert len(await list_memories(session, user)) == 2


class TestRetrieval:
    async def test_constraints_come_before_context(self, session, butler):
        user, _ = butler
        await remember(session, user, kind="context", subject="work", fact="Works in KL.")
        await remember(session, user, kind="constraint", subject="rule", fact="Never cut rent.")
        assert [memory.kind for memory in await list_memories(session, user)] == [
            "constraint",
            "context",
        ]

    async def test_the_cap_is_respected(self, session, butler):
        user, _ = butler
        for index in range(6):
            await remember(
                session, user, kind="context", subject=f"fact {index}", fact=f"Number {index}."
            )
        assert len(await list_memories(session, user, limit=4)) == 4

    async def test_a_fact_the_answer_leans_on_is_marked_used(self, session, butler, today):
        user, _ = butler
        await remember(
            session,
            user,
            kind="pattern",
            subject="goal progress",
            fact="Tracks the wedding goal closely every month.",
        )
        assert (await list_memories(session, user))[0].last_used_at is None
        await say(session, butler, today, "How is my wedding goal doing?")
        assert (await list_memories(session, user))[0].last_used_at is not None


class TestUserControl:
    async def test_correcting_a_fact_makes_it_certain(self, session, butler):
        user, _ = butler
        memory = await remember(
            session, user, kind="context", subject="work", fact="Works in Penang.", confidence=40
        )
        fixed = await correct(session, user, memory.id, "Works in KL.")
        assert fixed.fact == "Works in KL."
        assert fixed.confidence == 100

    async def test_deleting_removes_it_from_retrieval(self, session, butler):
        user, _ = butler
        memory = await remember(session, user, kind="context", subject="work", fact="Works in KL.")
        await forget(session, user, memory.id)
        assert await list_memories(session, user) == ()
        row = (
            await session.execute(select(ButlerMemory).where(ButlerMemory.id == memory.id))
        ).scalar_one()
        assert row.status == MEMORY_DELETED
