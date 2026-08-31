from datetime import date

from kira.api.schemas import GoalCreateRequest

from .test_auth import register


def payload(**changes):
    value = {
        "goal_type": "travel",
        "name": "Family trip",
        "target_amount_sen": 120_000,
        "current_saved_sen": 20_000,
        "target_date": "2026-12-02",
        "priority": "important",
        "funding_account_ids": [],
    }
    value.update(changes)
    return value


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestGoalContracts:
    async def test_create_detail_and_plan(self, client):
        token = await register(client)
        created = await client.post("/v1/goals", json=payload(), headers=auth(token))
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["goal"]["status"] == "draft"
        assert body["goal"]["horizon"] == "short"
        assert body["plan"]["version"] == 1
        assert body["plan"]["calculation_version"] == "goal-plan-v1"
        assert body["plan"]["evidence_refs"]
        goal_id = body["goal"]["goal_id"]

        detail = await client.get(f"/v1/goals/{goal_id}", headers=auth(token))
        plan = await client.get(f"/v1/goals/{goal_id}/plan", headers=auth(token))
        assert detail.status_code == 200
        assert detail.json()["goal_type"] == "travel"
        assert plan.status_code == 200
        assert len(plan.json()["milestones"]) == 4

    async def test_scenarios_and_purchase_impact(self, client):
        token = await register(client)
        created = await client.post("/v1/goals", json=payload(), headers=auth(token))
        goal_id = created.json()["goal"]["goal_id"]

        scenarios = await client.post(f"/v1/goals/{goal_id}/scenarios", headers=auth(token))
        assert scenarios.status_code == 200, scenarios.text
        assert [item["label"] for item in scenarios.json()["scenarios"]] == [
            "On-time target",
            "Cash-flow-safe",
            "Accelerated",
        ]

        impact = await client.post(
            f"/v1/goals/{goal_id}/impact",
            json={"proposed_spend_sen": 5_000},
            headers=auth(token),
        )
        assert impact.status_code == 200, impact.text
        assert impact.json()["proposed_spend_sen"] == 5_000
        assert impact.json()["calculation_version"] == "goal-plan-v1"

    async def test_requires_authentication(self, client):
        response = await client.post("/v1/goals", json=payload())
        assert response.status_code == 401

    async def test_rejects_float_money_and_past_target(self, client):
        token = await register(client)
        floating = await client.post(
            "/v1/goals", json=payload(target_amount_sen=1200.5), headers=auth(token)
        )
        past = await client.post(
            "/v1/goals", json=payload(target_date="2026-09-02"), headers=auth(token)
        )
        assert floating.status_code == 422
        assert past.status_code == 422


def test_request_contract_keeps_target_date_as_a_date():
    request = GoalCreateRequest.model_validate(payload())
    assert request.target_date == date(2026, 12, 2)
