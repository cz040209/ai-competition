"""POST /v1/day-plan/interpret — a sentence read into the Plan screen's controls.

Almost every case here is the same rule from a different side: the filters come
back whole or they do not come back at all. A screen that applied half of what
was asked for would show a list the user reads as the answer to all of it.
"""

from __future__ import annotations

import asyncio

import pytest

from kira.agent import plan_intent
from kira.agent.plan_intent import PlanIntent
from kira.agent.tools.day_plan import PlanArgs
from kira.config import get_settings
from tests.api.test_day_plan import auth, demo_token

KLCC = {"lat": 3.1577, "lng": 101.712}

# The state the screen opens in: on foot, halal on, no ceiling of the user's
# own, balanced order. Every "unchanged" assertion below is against this.
UNTOUCHED = {
    **KLCC,
    "mode": "walk",
    "halal_only": True,
    "cap_sen": None,
    "kind": None,
    "sort": "balanced",
}


class StubModel:
    """A chat model that answers one thing, and remembers what it was asked."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.schema: type | None = None
        self.conversations: list[list] = []

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self

    async def ainvoke(self, conversation, **kwargs):
        self.conversations.append(conversation)
        if isinstance(self.answer, BaseException):
            raise self.answer
        if callable(self.answer):
            return await self.answer()
        return self.answer


@pytest.fixture
def reading(monkeypatch):
    """Install a chosen answer behind the endpoint, with a model reachable.

    ``BUTLER_OFFLINE`` is on for the whole suite, so the online path has to be
    opened deliberately here. That is also what keeps the offline case honest
    further down: it is the suite's default rather than something staged for it.
    """

    def install(answer) -> StubModel:
        model = StubModel(answer)
        monkeypatch.setattr(plan_intent, "offline_reason", lambda: None)
        monkeypatch.setattr(plan_intent, "get_chat_model", lambda **kwargs: model)
        return model

    return install


async def ask(client, token: str, sentence: str, **state):
    return await client.post(
        "/v1/day-plan/interpret",
        json={**UNTOUCHED, **state, "text": sentence},
        headers=auth(token),
    )


class TestReadingASentence:
    async def test_requires_a_token(self, client):
        response = await client.post(
            "/v1/day-plan/interpret", json={**UNTOUCHED, "text": "halal under RM15"}
        )
        assert response.status_code == 401

    async def test_a_parsed_sentence_comes_back_as_the_whole_filter_set(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        model = reading(PlanIntent(halal_only=True, cap_sen=1500, sort="closest"))

        response = await ask(
            client, token, "halal under RM15, I'd rather not walk far", halal_only=False
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["applied"] is True
        assert body["filters"] == {
            **KLCC,
            "mode": "walk",
            "halal_only": True,
            "cap_sen": 1500,
            "kind": None,
            "sort": "closest",
        }
        # The Butler's own plan schema, not a second one written for this
        # screen: one description of what a ceiling in sen means, not two.
        assert model.schema is PlanIntent
        assert issubclass(model.schema, PlanArgs)

    async def test_it_says_what_it_understood_in_one_line(self, client, session, reading):
        token = await demo_token(client, session)
        reading(PlanIntent(halal_only=True, cap_sen=1500, sort="closest"))

        response = await ask(
            client, token, "halal under RM15, I'd rather not walk far", halal_only=False
        )

        # Everything it changed, in the order the controls read, so a
        # misreading is on screen beside the chip that got it wrong.
        assert response.json()["understood"] == (
            "I read that as halal only, under RM15.00, closest first."
        )

    async def test_a_control_the_sentence_did_not_mention_is_left_as_it_was(
        self, client, session, reading
    ):
        """An omitted field is the current setting, never the schema's default.

        Pydantic would fill ``mode`` with "walk" here, which on a user who is on
        the LRT is a change they did not ask for — the same failure as a change
        half applied, in the opposite direction.
        """
        token = await demo_token(client, session)
        reading(PlanIntent(cap_sen=1500))

        response = await ask(
            client, token, "nothing over RM15", mode="transit", halal_only=False, sort="closest"
        )

        body = response.json()
        assert body["filters"] == {
            **KLCC,
            "mode": "transit",
            "halal_only": False,
            "cap_sen": 1500,
            "kind": None,
            "sort": "closest",
        }
        assert body["understood"] == "I read that as under RM15.00."

    async def test_the_ceiling_crosses_as_integer_sen(self, client, session, reading):
        token = await demo_token(client, session)
        reading(PlanIntent(cap_sen=1500))

        response = await ask(client, token, "nothing over RM15")

        assert isinstance(response.json()["filters"]["cap_sen"], int)

    async def test_the_model_is_told_where_the_controls_are_now(self, client, session, reading):
        """Without the current state a sentence about one control resets the rest."""
        token = await demo_token(client, session)
        model = reading(PlanIntent(sort="cheapest"))

        await ask(client, token, "cheapest first", mode="transit", cap_sen=2000)

        system = model.conversations[0][0].content
        assert "transit" in system
        assert "RM20.00" in system
        assert model.conversations[0][1].content == "cheapest first"

    async def test_dropping_the_ceiling_back_to_todays_room_is_a_reading_too(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        reading(PlanIntent(cap_sen=None))

        response = await ask(client, token, "forget the ceiling", cap_sen=1500)

        body = response.json()
        assert body["filters"]["cap_sen"] is None
        assert body["understood"] == "I read that as no ceiling but today's room."


class TestWhatItCouldNotRead:
    async def test_the_part_it_could_not_place_comes_back_too(self, client, session, reading):
        token = await demo_token(client, session)
        reading(PlanIntent(halal_only=True, unread="near Bangsar"))

        response = await ask(client, token, "halal, near Bangsar", halal_only=False)

        body = response.json()
        assert body["applied"] is True
        assert body["understood"] == "I read that as halal only."
        assert body["unread"] == "near Bangsar"

    async def test_a_sentence_it_read_whole_leaves_nothing_behind(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        reading(PlanIntent(halal_only=True))

        response = await ask(client, token, "halal only please", halal_only=False)

        assert response.json()["unread"] == ""


class TestReadingAKindOfFood:
    """The one control with a closed vocabulary that is not the model's.

    Asked for somewhere "hawker", a live model fills the field confidently with
    a word no place carries. Applying it would empty the list behind a chip the
    user cannot argue with — a screen showing nothing on the strength of a
    category that does not exist.
    """

    async def test_a_kind_the_places_carry_is_applied(self, client, session, reading):
        token = await demo_token(client, session)
        reading(PlanIntent(kind="Noodles"))

        response = await ask(client, token, "I want noodles")

        body = response.json()
        assert body["applied"] is True
        assert body["filters"]["kind"] == "Noodles"
        assert body["understood"] == "I read that as noodles."

    async def test_it_comes_back_in_the_spelling_the_places_use(self, client, session, reading):
        # So the chip on screen reads like the rows below it, and so the filter
        # the screen sends back matches on the first try.
        token = await demo_token(client, session)
        reading(PlanIntent(kind="japanese"))

        response = await ask(client, token, "somewhere japanese")

        assert response.json()["filters"]["kind"] == "Japanese"

    async def test_a_category_the_data_does_not_have_sets_no_filter(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        reading(PlanIntent(kind="hawker"))

        response = await ask(client, token, "somewhere hawker")

        body = response.json()
        # Nothing applied, and the word handed back as one it could not place —
        # which is what the box already does with the rest of a sentence.
        assert body["applied"] is False
        assert body["unread"] == "hawker"
        assert body["reason"] == plan_intent.NOTHING_TO_SET

    async def test_an_unreadable_kind_does_not_take_the_rest_of_the_sentence_with_it(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        reading(PlanIntent(halal_only=True, cap_sen=1500, kind="street food"))

        response = await ask(
            client, token, "halal street food under RM15", halal_only=False
        )

        body = response.json()
        assert body["applied"] is True
        assert body["filters"]["kind"] is None
        assert body["understood"] == "I read that as halal only, under RM15.00."
        assert body["unread"] == "street food"

    async def test_both_kinds_of_unread_are_kept(self, client, session, reading):
        token = await demo_token(client, session)
        reading(PlanIntent(halal_only=True, kind="hawker", unread="near Bangsar"))

        response = await ask(client, token, "halal hawker near Bangsar", halal_only=False)

        # A place to search near and a category nothing here serves are two
        # different things the box could not use, and dropping either would be
        # the screen going quiet about half of what it missed.
        assert response.json()["unread"] == "near Bangsar, hawker"

    async def test_clearing_it_is_a_reading_too(self, client, session, reading):
        token = await demo_token(client, session)
        reading(PlanIntent(kind=None))

        response = await ask(client, token, "anything, not just noodles", kind="Noodles")

        body = response.json()
        assert body["filters"]["kind"] is None
        assert body["understood"] == "I read that as any kind of food."

    async def test_a_sentence_that_says_nothing_about_food_leaves_it_alone(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        reading(PlanIntent(cap_sen=1500))

        response = await ask(client, token, "nothing over RM15", kind="Mamak")

        assert response.json()["filters"]["kind"] == "Mamak"

    async def test_the_model_is_told_which_kind_is_set(self, client, session, reading):
        token = await demo_token(client, session)
        model = reading(PlanIntent(cap_sen=1500))

        await ask(client, token, "nothing over RM15", kind="Mamak")

        assert "Mamak" in model.conversations[0][0].content


class TestTheOriginIsNotTheModelsToSet:
    """Location comes from the device or from the KLCC fallback, and from
    nowhere else. A model that could move it could move the whole list to a
    city the user never named and leave every distance on screen true of
    somewhere else."""

    async def test_coordinates_the_model_invented_are_dropped(self, client, session, reading):
        token = await demo_token(client, session)
        # George Town, Penang: 294 km from everything this search knows about.
        reading(PlanIntent(lat=5.4141, lng=100.3288, halal_only=False))

        response = await ask(client, token, "somewhere halal near Penang")

        body = response.json()
        assert body["applied"] is True
        assert body["filters"]["lat"] == 3.1577
        assert body["filters"]["lng"] == 101.712
        # And the line the screen shows says only what actually changed.
        assert body["understood"] == "I read that as halal off."

    async def test_the_origin_survives_a_reading_that_changes_everything_else(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        reading(
            PlanIntent(
                lat=5.4141, lng=100.3288, mode="ride", halal_only=False, cap_sen=3000,
                sort="cheapest",
            )
        )

        response = await ask(client, token, "cheapest by Grab under RM30, anywhere")

        filters = response.json()["filters"]
        assert (filters["lat"], filters["lng"]) == (3.1577, 101.712)
        assert filters["mode"] == "ride"


class TestNothingIsEverHalfApplied:
    async def test_offline_changes_nothing_and_says_so(self, client, session):
        """No model is installed here at all — this is the suite's own default."""
        token = await demo_token(client, session)

        response = await ask(client, token, "halal under RM15", halal_only=False)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["applied"] is False
        assert body["filters"] is None
        assert body["understood"] == ""
        assert body["reason"] == plan_intent.UNREACHABLE
        assert "Nothing below has changed" in body["reason"]

    async def test_a_slow_model_is_abandoned_rather_than_waited_on(
        self, client, session, reading, monkeypatch
    ):
        token = await demo_token(client, session)
        monkeypatch.setattr(get_settings(), "day_plan_interpret_timeout_seconds", 0.01)

        async def never():
            await asyncio.sleep(5)
            return PlanIntent(halal_only=False, cap_sen=1500)

        reading(never)

        response = await ask(client, token, "halal under RM15", halal_only=False)

        body = response.json()
        assert body["applied"] is False
        assert body["filters"] is None
        # Named, so the wait the user sat through is the one the copy admits to.
        assert body["reason"] == (
            "Reading that was taking longer than 0.01 seconds, so I stopped. "
            "Nothing below has changed."
        )

    async def test_a_malformed_answer_changes_nothing(self, client, session, reading):
        """Prose where a filled schema was asked for."""
        token = await demo_token(client, session)
        reading("Sure — halal it is!")

        response = await ask(client, token, "halal under RM15", halal_only=False)

        body = response.json()
        assert body["applied"] is False
        assert body["filters"] is None
        assert body["reason"] == plan_intent.UNREADABLE

    async def test_a_model_that_refuses_outright_changes_nothing(self, client, session, reading):
        token = await demo_token(client, session)
        reading(RuntimeError("the upstream declined to answer"))

        response = await ask(client, token, "halal under RM15", halal_only=False)

        body = response.json()
        assert body["applied"] is False
        assert body["filters"] is None
        assert body["reason"] == plan_intent.UNREADABLE

    async def test_a_sentence_that_asks_for_nothing_is_not_an_interpretation(
        self, client, session, reading
    ):
        token = await demo_token(client, session)
        reading(PlanIntent(unread="is it raining"))

        response = await ask(client, token, "is it raining")

        body = response.json()
        # Applying this would leave a line on screen claiming a reading behind
        # a list that never moved.
        assert body["applied"] is False
        assert body["filters"] is None
        assert body["reason"] == plan_intent.NOTHING_TO_SET
        assert body["unread"] == "is it raining"

    async def test_restating_the_controls_unchanged_applies_nothing(
        self, client, session, reading
    ):
        """A model that dutifully echoes every current value has read nothing."""
        token = await demo_token(client, session)
        reading(PlanIntent(mode="walk", halal_only=True, cap_sen=None, sort="balanced"))

        response = await ask(client, token, "yes")

        assert response.json()["applied"] is False
        assert response.json()["filters"] is None
