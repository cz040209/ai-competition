"""The Butler under test runs the real graph against the deterministic model."""

from __future__ import annotations

import pytest

from kira.agent.llm import OfflineChatModel
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.butler_thread import ensure_thread


def offline_factory(**kwargs):
    """Every test drives the same model the venue-network fallback uses."""
    return OfflineChatModel(attachment=kwargs.get("attachment"))


@pytest.fixture
async def butler(session):
    user = await seed_demo_user(session)
    thread = await ensure_thread(session, user)
    return user, thread


@pytest.fixture
def today():
    return DEMO_TODAY


class ScriptedModel(OfflineChatModel):
    """Emits exactly the tool calls a test names, then composes as usual.

    Subclassing the offline model rather than mocking keeps the graph, the
    guard and the approval flow on their real code paths.
    """

    calls: list = []

    def bind_tools(self, tools, **kwargs):
        bound = super().bind_tools(tools, **kwargs)
        return bound.model_copy(update={"calls": self.calls})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage, ToolMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        if not self.bound_tools:
            return super()._generate(messages, stop, run_manager, **kwargs)
        if any(isinstance(message, ToolMessage) for message in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])
        tool_calls = [
            {"name": name, "args": args, "id": f"scripted-{index}", "type": "tool_call"}
            for index, (name, args) in enumerate(self.calls)
        ]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="", tool_calls=tool_calls))]
        )


def scripted_factory(*calls):
    def factory(**kwargs):
        return ScriptedModel(attachment=kwargs.get("attachment"), calls=list(calls))

    return factory
