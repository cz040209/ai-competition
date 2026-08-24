"""Locks the finance math. A change to any number here must be deliberate."""

import pytest

from kira.engine import safe_to_spend
from tests.engine.case_loader import actual_output, build_snapshot, load_cases

CASES = load_cases()


def test_cases_exist():
    assert CASES, "no golden cases found — the engine is unprotected"


@pytest.mark.parametrize("name,case", CASES, ids=[n for n, _ in CASES])
def test_golden_case(name, case):
    result = safe_to_spend(build_snapshot(case["input"]))
    assert actual_output(result) == case["expected"], case["name"]
