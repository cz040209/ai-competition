# Kira Week 1 Base — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Kira monorepo end to end — one `docker compose up` brings up Postgres and a single app container that serves a React PWA at `/` and a FastAPI at `/v1`, with a working login and a Today screen whose numbers come from the pure finance engine.

**Architecture:** Four backend layers with one-directional dependencies (`api → services → engine`, plus `adapters`). The `engine` package is pure — no I/O, no DB session, no clock — which is what makes the finance math testable by golden file. All money is an integer-sen `Money` value object that physically cannot be a float, enforced by a SQLAlchemy `TypeDecorator` and an AST lint. The web app is the existing prototype decomposed into screens and components; it never hand-writes an API type.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, asyncpg, PyJWT, argon2-cffi, pytest + pytest-asyncio, import-linter, ruff. React 19, Vite 6, TypeScript 5, TanStack Query 5, npm workspaces, openapi-typescript. PostgreSQL 16, Docker multi-stage.

**Spec:** `docs/superpowers/specs/2026-08-24-kira-architecture-design.md`

## Global Constraints

These apply to every task. Do not restate them per task; do not violate them.

- **Money is integer sen.** Every monetary value in the system is an `int` count of sen plus an ISO 4217 currency code. `float` never touches money, anywhere, at any layer.
- **Currency for the MVP is `MYR`.** The code carries the currency field so a second currency is possible later; no task adds multi-currency behaviour now.
- **`kira/engine/` imports nothing from `kira.api`, `kira.services`, `kira.adapters`, `kira.db`, or `kira.agent`.** It may import only the standard library and `kira.money`. Enforced by import-linter in CI.
- **`kira/engine/` contains no `float`.** No float literals, no `float()` calls, no `float` annotations. Enforced by an AST test.
- **Rounding is half-up, not banker's.** Python's built-in `round()` rounds halves to even (`round(0.5) == 0`); the prototype uses JavaScript `Math.round`, which rounds halves up. Use the shared `round_half_up` helper for every ratio-to-amount conversion. Never use built-in `round()` on money.
- **Rounding happens once**, at the point a ratio becomes an amount. Never accumulate rounded intermediates.
- **Draft invariant.** A transaction with `status='draft'` is excluded from every engine calculation. The snapshot loader filters `status='confirmed'`; there is no code path around it.
- **No money-moving capability exists.** No task in this plan creates an endpoint, service, or tool that transfers funds, cancels a subscription, or writes to an external financial provider.
- **Timestamps are stored UTC**, in `TIMESTAMP WITH TIME ZONE` columns. Dates used by the engine (`today`, `next_payday`, `cycle_start`) are plain `date` values passed in as parameters — the engine never calls `date.today()`.
- **Python version floor: 3.12.** Node version floor: 22.
- **Every task ends with a commit.** Conventional commit prefixes (`feat:`, `test:`, `chore:`, `build:`).

---

## File Structure

```text
kira/                            (repo root — the existing ai-competition repo)
  apps/
    api/
      pyproject.toml             deps, ruff, pytest, import-linter config
      kira/
        __init__.py
        money.py                 Money value object + round_half_up  (importable by engine)
        config.py                pydantic-settings Settings
        engine/
          __init__.py            public exports
          types.py               Snapshot / GoalInput / CommitmentInput / SafeToSpend
          safe_to_spend.py       the one pure function
        adapters/
          __init__.py
          protocols.py           OcrAdapter, VoiceAdapter, MapsAdapter, StorageAdapter, LlmAdapter
          fakes.py               deterministic fake for each
          registry.py            get_adapters() — fakes unless configured otherwise
        db/
          __init__.py
          types.py               MoneyType TypeDecorator
          base.py                DeclarativeBase + naming convention
          models.py              User, RefreshToken, Account, Commitment, Goal, Transaction
          session.py             async engine + sessionmaker + get_session dependency
        services/
          __init__.py
          auth.py                register / authenticate / issue / rotate / revoke
          snapshot.py            DB rows -> engine Snapshot (filters status='confirmed')
          dashboard.py           snapshot + engine -> DashboardToday DTO
        api/
          __init__.py
          app.py                 FastAPI app factory, SPA static mount
          deps.py                current_user dependency
          schemas.py             Pydantic request/response models
          routers/
            __init__.py
            auth.py              /v1/auth/*
            dashboard.py         /v1/dashboard/today
        seed/
          __init__.py
          demo.py                the demo user and their financial picture
          __main__.py            python -m kira.seed
      alembic.ini
      alembic/
        env.py
        versions/0001_initial.py
      tests/
        conftest.py
        engine/
          test_safe_to_spend.py
          test_golden.py
          test_engine_purity.py
          cases/*.json
        test_money.py
        db/test_money_type.py
        services/test_snapshot_draft_invariant.py
        api/test_auth.py
        api/test_dashboard.py
  apps/
    web/
      package.json
      vite.config.ts
      tsconfig.json
      index.html
      src/
        main.tsx
        App.tsx                  device frame, boot, nav, tab routing
        styles/kira.css          the design system lifted from the prototype STYLES
        lib/money.ts             fmt()
        lib/queryClient.ts
        api/client.ts            fetch wrapper + auth header + silent refresh
        api/hooks.ts             useDashboardToday()
        components/Icons.tsx
        components/Reveal.tsx
        components/Odometer.tsx
        components/Ring.tsx
        components/ClaimLine.tsx
        components/NavItem.tsx
        components/Motes.tsx
        screens/Today.tsx
        screens/Placeholder.tsx  Activity / Butler / Plan / More stubs for week 1
  packages/contracts/
    package.json
    src/schema.d.ts              generated — never hand-edited
  package.json                   npm workspaces root
  Dockerfile                     multi-stage: web build -> python runtime
  docker-compose.yml             app + db
  .dockerignore
  .env.example
  scripts/gen-contracts.sh
```

Each backend file has one responsibility. `engine/safe_to_spend.py` holds the formula and nothing else; `services/snapshot.py` is the only place that turns rows into engine inputs; `api/routers/*` translate HTTP and do no arithmetic.

---

## Task 1: Monorepo skeleton, Python package, tooling

**Files:**
- Create: `apps/api/pyproject.toml`, `apps/api/kira/__init__.py`, `apps/api/tests/__init__.py`, `apps/api/tests/test_smoke.py`
- Create: `package.json`, `.gitignore`, `.env.example`, `docker-compose.yml`

**Interfaces:**
- Consumes: nothing
- Produces: an installed `kira` package importable as `kira`, a `pytest` run that passes, and a `db` service reachable at `postgresql+asyncpg://kira:kira@localhost:5432/kira`.

- [ ] **Step 1: Create the directory skeleton**

```bash
mkdir -p apps/api/kira apps/api/tests apps/web/src packages/contracts/src scripts
touch apps/api/kira/__init__.py apps/api/tests/__init__.py
```

- [ ] **Step 2: Write `apps/api/pyproject.toml`**

```toml
[project]
name = "kira"
version = "0.1.0"
description = "Kira — AI money butler"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "sqlalchemy[asyncio]>=2.0.36",
  "asyncpg>=0.30",
  "alembic>=1.14",
  "pyjwt>=2.10",
  "argon2-cffi>=23.1",
  "python-multipart>=0.0.17",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "httpx>=0.28",
  "aiosqlite>=0.20",
  "import-linter>=2.1",
  "ruff>=0.8",
]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["kira*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
filterwarnings = ["error::DeprecationWarning:kira.*"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]

[tool.importlinter]
root_package = "kira"

[[tool.importlinter.contracts]]
name = "engine is pure"
type = "forbidden"
source_modules = ["kira.engine"]
forbidden_modules = ["kira.api", "kira.services", "kira.adapters", "kira.db", "kira.agent", "kira.seed"]

[[tool.importlinter.contracts]]
name = "layers point one way"
type = "layers"
layers = ["kira.api", "kira.services", "kira.engine"]
```

- [ ] **Step 3: Write `apps/api/kira/__init__.py`**

```python
"""Kira — AI money butler."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Write the smoke test at `apps/api/tests/test_smoke.py`**

```python
import kira


def test_package_imports():
    assert kira.__version__ == "0.1.0"
```

- [ ] **Step 5: Create the virtualenv and install**

```bash
cd apps/api && python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
```

- [ ] **Step 6: Run the test suite**

Run: `cd apps/api && .venv/bin/pytest -q`
Expected: PASS — 1 passed.

- [ ] **Step 7: Write `.gitignore` at the repo root**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
node_modules/
dist/
.env
apps/api/openapi.json
```

- [ ] **Step 8: Write `.env.example` at the repo root**

```dotenv
DATABASE_URL=postgresql+asyncpg://kira:kira@db:5432/kira
JWT_SECRET=change-me-in-production
ACCESS_TOKEN_TTL_MINUTES=15
REFRESH_TOKEN_TTL_DAYS=30
CORS_ORIGINS=http://localhost:5173
```

- [ ] **Step 9: Write `docker-compose.yml` at the repo root**

The `app` service is added in Task 14; week 1 development runs against `db` alone.

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: kira
      POSTGRES_PASSWORD: kira
      POSTGRES_DB: kira
    ports:
      - "5432:5432"
    volumes:
      - kira-db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U kira -d kira"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  kira-db:
```

- [ ] **Step 10: Write the workspace root `package.json`**

```json
{
  "name": "kira",
  "private": true,
  "workspaces": ["apps/web", "packages/contracts"],
  "scripts": {
    "dev": "npm --workspace apps/web run dev",
    "build": "npm --workspace apps/web run build",
    "gen:contracts": "bash scripts/gen-contracts.sh"
  }
}
```

- [ ] **Step 11: Verify Postgres comes up**

Run: `docker compose up -d db && docker compose ps`
Expected: the `db` service is `healthy`. Leave it running — later tasks use it.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "chore: scaffold monorepo, python package, tooling, postgres service"
```

---

## Task 2: The Money value object

**Files:**
- Create: `apps/api/kira/money.py`
- Test: `apps/api/tests/test_money.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `round_half_up(numerator: int, denominator: int) -> int`
  - `class CurrencyMismatch(ValueError)`
  - `class Money` — frozen dataclass with `sen: int`, `currency: str = "MYR"`; classmethod `zero(currency: str = "MYR") -> Money`; classmethod `sum(items: Iterable[Money], currency: str = "MYR") -> Money`; operators `+ - * (int only)` and `< <= > >=`; `divide_floor(divisor: int) -> Money`; `ringgit_str() -> str` producing `"1,200.00"`.

- [ ] **Step 1: Write the failing test at `apps/api/tests/test_money.py`**

```python
import pytest

from kira.money import CurrencyMismatch, Money, round_half_up


class TestRoundHalfUp:
    def test_exact_division(self):
        assert round_half_up(216000, 30) == 7200

    def test_half_rounds_up(self):
        assert round_half_up(5, 2) == 3

    def test_below_half_rounds_down(self):
        assert round_half_up(4, 3) == 1

    def test_negative_half_rounds_toward_positive_infinity(self):
        # Matches JavaScript Math.round(-2.5) === -2, which the prototype relies on.
        assert round_half_up(-5, 2) == -2

    def test_rejects_non_positive_denominator(self):
        with pytest.raises(ValueError):
            round_half_up(1, 0)


class TestMoneyConstruction:
    def test_holds_integer_sen_and_currency(self):
        m = Money(1250)
        assert m.sen == 1250
        assert m.currency == "MYR"

    def test_rejects_float(self):
        with pytest.raises(TypeError):
            Money(12.5)  # type: ignore[arg-type]

    def test_rejects_bool(self):
        with pytest.raises(TypeError):
            Money(True)  # type: ignore[arg-type]

    def test_rejects_malformed_currency(self):
        with pytest.raises(ValueError):
            Money(100, "myr")

    def test_is_hashable_and_frozen(self):
        m = Money(100)
        assert {m: 1}[Money(100)] == 1
        with pytest.raises(AttributeError):
            m.sen = 200  # type: ignore[misc]


class TestMoneyArithmetic:
    def test_addition(self):
        assert Money(100) + Money(250) == Money(350)

    def test_subtraction_can_go_negative(self):
        assert Money(100) - Money(250) == Money(-150)

    def test_multiplication_by_int(self):
        assert Money(100) * 3 == Money(300)

    def test_multiplication_by_float_is_rejected(self):
        with pytest.raises(TypeError):
            Money(100) * 1.5  # type: ignore[operator]

    def test_divide_floor_rounds_toward_negative_infinity(self):
        assert Money(116540).divide_floor(22) == Money(5297)
        assert Money(-201500).divide_floor(22) == Money(-9160)

    def test_divide_floor_rejects_zero(self):
        with pytest.raises(ValueError):
            Money(100).divide_floor(0)

    def test_mixing_currencies_raises(self):
        with pytest.raises(CurrencyMismatch):
            Money(100, "MYR") + Money(100, "SGD")

    def test_comparison_respects_currency(self):
        assert Money(100) < Money(200)
        assert max(Money(0), Money(-500)) == Money(0)
        with pytest.raises(CurrencyMismatch):
            Money(100, "MYR") < Money(100, "SGD")

    def test_sum_of_empty_is_zero(self):
        assert Money.sum([]) == Money.zero()

    def test_sum_of_many(self):
        assert Money.sum([Money(120000), Money(8900), Money(52000)]) == Money(180900)


class TestMoneyFormatting:
    def test_ringgit_str_groups_thousands(self):
        assert Money(120000).ringgit_str() == "1,200.00"

    def test_ringgit_str_pads_sen(self):
        assert Money(5).ringgit_str() == "0.05"

    def test_ringgit_str_negative(self):
        assert Money(-1890).ringgit_str() == "-18.90"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/test_money.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.money'`.

- [ ] **Step 3: Write `apps/api/kira/money.py`**

```python
"""Money as integer sen. No float ever participates in a monetary calculation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


class CurrencyMismatch(ValueError):
    """Raised when two Money values of different currencies are combined."""


def round_half_up(numerator: int, denominator: int) -> int:
    """Divide two integers, rounding halves toward positive infinity.

    This matches JavaScript's ``Math.round``, which the UI prototype uses.
    Python's built-in ``round`` rounds halves to even and must not be used on
    money. The arithmetic here is entirely integral, so no float is involved.
    """
    if not isinstance(numerator, int) or isinstance(numerator, bool):
        raise TypeError("numerator must be an int")
    if not isinstance(denominator, int) or isinstance(denominator, bool):
        raise TypeError("denominator must be an int")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (2 * numerator + denominator) // (2 * denominator)


def _check_sen(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Money.sen must be an int number of sen, got {type(value).__name__}")


def _check_currency(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 3 or not value.isalpha() or not value.isupper():
        raise ValueError(f"currency must be a three-letter uppercase ISO code, got {value!r}")


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount, held as an integer count of the currency's minor unit."""

    sen: int
    currency: str = "MYR"

    def __post_init__(self) -> None:
        _check_sen(self.sen)
        _check_currency(self.currency)

    @classmethod
    def zero(cls, currency: str = "MYR") -> Money:
        return cls(0, currency)

    @classmethod
    def sum(cls, items: Iterable[Money], currency: str = "MYR") -> Money:
        total = cls.zero(currency)
        for item in items:
            total = total + item
        return total

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(f"cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.sen + other.sen, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.sen - other.sen, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.sen, self.currency)

    def __mul__(self, factor: int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise TypeError("Money can only be multiplied by an int")
        return Money(self.sen * factor, self.currency)

    __rmul__ = __mul__

    def divide_floor(self, divisor: int) -> Money:
        """Split into ``divisor`` parts, rounding toward negative infinity.

        Floor, not truncation: a negative amount spread over days must round
        away from zero so the daily allowance never flatters an overdraft.
        """
        if isinstance(divisor, bool) or not isinstance(divisor, int):
            raise TypeError("divisor must be an int")
        if divisor <= 0:
            raise ValueError("divisor must be positive")
        return Money(self.sen // divisor, self.currency)

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen < other.sen

    def __le__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen <= other.sen

    def __gt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen > other.sen

    def __ge__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen >= other.sen

    def ringgit_str(self) -> str:
        """Format as a grouped major-unit string, e.g. ``1,200.00``."""
        sign = "-" if self.sen < 0 else ""
        major, minor = divmod(abs(self.sen), 100)
        return f"{sign}{major:,}.{minor:02d}"

    def __str__(self) -> str:
        return f"{self.currency} {self.ringgit_str()}"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/api && .venv/bin/pytest tests/test_money.py -q`
Expected: PASS — all tests green.

- [ ] **Step 5: Commit**

```bash
git add apps/api/kira/money.py apps/api/tests/test_money.py
git commit -m "feat: add Money value object with half-up rounding"
```

---

## Task 3: The finance engine and its golden-file suite

**Files:**
- Create: `apps/api/kira/engine/__init__.py`, `apps/api/kira/engine/types.py`, `apps/api/kira/engine/safe_to_spend.py`
- Test: `apps/api/tests/engine/__init__.py`, `apps/api/tests/engine/test_safe_to_spend.py`, `apps/api/tests/engine/case_loader.py`, `apps/api/tests/engine/test_golden.py`, `apps/api/tests/engine/cases/*.json`

**Interfaces:**
- Consumes: `kira.money.Money`, `kira.money.round_half_up`.
- Produces:
  - `kira.engine.types.GoalInput(id: str, monthly: Money)`
  - `kira.engine.types.CommitmentInput(id: str, amount: Money, due_date: date)`
  - `kira.engine.types.Snapshot(balance, buffer, spent_today, commitments: tuple[CommitmentInput, ...], goals: tuple[GoalInput, ...], today: date, next_payday: date, cycle_start: date, cycle_days: int)`
  - `kira.engine.types.SafeToSpend(days_to_payday: int, cycle_elapsed: int, goal_reserve, reserved, unclaimed, per_day, spent_today, safe_today)` — all money fields are `Money`
  - `kira.engine.safe_to_spend(snapshot: Snapshot) -> SafeToSpend`, re-exported as `from kira.engine import safe_to_spend`

- [ ] **Step 1: Write the failing test at `apps/api/tests/engine/test_safe_to_spend.py`**

```python
from datetime import date

import pytest

from kira.engine import safe_to_spend
from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import CurrencyMismatch, Money

TODAY = date(2026, 9, 3)
PAYDAY = date(2026, 9, 25)
CYCLE_START = date(2026, 8, 26)

DEMO_COMMITMENTS = (
    CommitmentInput("rent", Money(120000), date(2026, 9, 5)),
    CommitmentInput("phone", Money(8900), date(2026, 9, 8)),
    CommitmentInput("loan", Money(52000), date(2026, 9, 10)),
    CommitmentInput("sub", Money(5500), date(2026, 9, 14)),
    CommitmentInput("net", Money(13900), date(2026, 9, 18)),
)

DEMO_GOALS = (
    GoalInput("g1", Money(27000)),
    GoalInput("g2", Money(52500)),
)


def snapshot(**overrides) -> Snapshot:
    base = dict(
        balance=Money(418040),
        buffer=Money(80000),
        spent_today=Money(0),
        commitments=DEMO_COMMITMENTS,
        goals=DEMO_GOALS,
        today=TODAY,
        next_payday=PAYDAY,
        cycle_start=CYCLE_START,
        cycle_days=30,
    )
    base.update(overrides)
    return Snapshot(**base)


class TestDemoBaseline:
    def test_matches_the_prototype_numbers(self):
        r = safe_to_spend(snapshot())
        assert r.days_to_payday == 22
        assert r.cycle_elapsed == 8
        assert r.reserved == Money(200300)
        assert r.goal_reserve == Money(21200)
        assert r.unclaimed == Money(116540)
        assert r.per_day == Money(5297)
        assert r.safe_today == Money(5297)


class TestCommitmentWindow:
    def test_commitment_due_after_payday_is_not_reserved(self):
        later = DEMO_COMMITMENTS[:-1] + (
            CommitmentInput("net", Money(13900), date(2026, 9, 30)),
        )
        r = safe_to_spend(snapshot(commitments=later))
        assert r.reserved == Money(186400)

    def test_commitment_due_on_payday_is_not_reserved(self):
        on_payday = (CommitmentInput("rent", Money(120000), PAYDAY),)
        r = safe_to_spend(snapshot(commitments=on_payday))
        assert r.reserved == Money.zero()

    def test_commitment_already_past_is_still_reserved(self):
        # Week 1 has no payment tracking; anything dated before payday is held.
        past = (CommitmentInput("rent", Money(120000), date(2026, 9, 1)),)
        r = safe_to_spend(snapshot(commitments=past))
        assert r.reserved == Money(120000)


class TestGoalReserve:
    def test_accrues_only_the_elapsed_part_of_the_cycle(self):
        r = safe_to_spend(snapshot(goals=(GoalInput("g", Money(30000)),)))
        # 30000 * 8 / 30 = 8000
        assert r.goal_reserve == Money(8000)

    def test_rounds_halves_up(self):
        r = safe_to_spend(
            snapshot(
                goals=(GoalInput("g", Money(100)),),
                cycle_start=date(2026, 8, 31),  # 3 days elapsed
                cycle_days=8,
            )
        )
        # 100 * 3 / 8 = 37.5 -> 38
        assert r.goal_reserve == Money(38)

    def test_rounds_each_goal_separately_and_once(self):
        r = safe_to_spend(
            snapshot(
                goals=(GoalInput("a", Money(100)), GoalInput("b", Money(100))),
                cycle_start=date(2026, 8, 31),
                cycle_days=8,
            )
        )
        assert r.goal_reserve == Money(76)

    def test_no_goals_reserves_nothing(self):
        assert safe_to_spend(snapshot(goals=())).goal_reserve == Money.zero()

    def test_cycle_elapsed_is_clamped_to_the_cycle_length(self):
        r = safe_to_spend(snapshot(cycle_start=date(2026, 6, 1)))
        assert r.cycle_elapsed == 30
        assert r.goal_reserve == Money(79500)

    def test_cycle_elapsed_is_never_negative(self):
        r = safe_to_spend(snapshot(cycle_start=date(2026, 9, 10)))
        assert r.cycle_elapsed == 0
        assert r.goal_reserve == Money.zero()


class TestSpentToday:
    def test_spending_reduces_the_room_left(self):
        r = safe_to_spend(snapshot(spent_today=Money(1890)))
        assert r.safe_today == Money(3407)

    def test_overspending_floors_at_zero(self):
        r = safe_to_spend(snapshot(spent_today=Money(6000)))
        assert r.per_day == Money(5297)
        assert r.safe_today == Money.zero()


class TestDeficit:
    def test_negative_unclaimed_floors_toward_negative_infinity(self):
        r = safe_to_spend(snapshot(balance=Money(100000)))
        assert r.unclaimed == Money(-201500)
        assert r.per_day == Money(-9160)
        assert r.safe_today == Money.zero()


class TestDaysToPayday:
    def test_payday_today_still_divides_by_one_day(self):
        r = safe_to_spend(snapshot(next_payday=TODAY, commitments=(), goals=()))
        assert r.days_to_payday == 1
        assert r.per_day == Money(338040)

    def test_payday_in_the_past_still_divides_by_one_day(self):
        r = safe_to_spend(snapshot(next_payday=date(2026, 9, 1), commitments=(), goals=()))
        assert r.days_to_payday == 1


class TestDeterminism:
    def test_same_input_gives_the_same_result(self):
        assert safe_to_spend(snapshot()) == safe_to_spend(snapshot())


class TestValidation:
    def test_mixed_currencies_are_rejected_at_construction(self):
        with pytest.raises(CurrencyMismatch):
            snapshot(buffer=Money(80000, "SGD"))

    def test_cycle_days_must_be_positive(self):
        with pytest.raises(ValueError):
            snapshot(cycle_days=0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && mkdir -p tests/engine && touch tests/engine/__init__.py && .venv/bin/pytest tests/engine -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.engine'`.

- [ ] **Step 3: Write `apps/api/kira/engine/types.py`**

```python
"""Inputs and outputs of the finance engine. Plain data, no behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kira.money import CurrencyMismatch, Money


@dataclass(frozen=True, slots=True)
class GoalInput:
    """A savings goal's claim on the cycle, expressed as its monthly contribution."""

    id: str
    monthly: Money


@dataclass(frozen=True, slots=True)
class CommitmentInput:
    """A known bill and the day it falls due."""

    id: str
    amount: Money
    due_date: date


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything the engine needs. Assembled by the caller; the engine reads no clock."""

    balance: Money
    buffer: Money
    spent_today: Money
    commitments: tuple[CommitmentInput, ...]
    goals: tuple[GoalInput, ...]
    today: date
    next_payday: date
    cycle_start: date
    cycle_days: int

    def __post_init__(self) -> None:
        if self.cycle_days <= 0:
            raise ValueError("cycle_days must be positive")
        currency = self.balance.currency
        others = [self.buffer, self.spent_today]
        others += [c.amount for c in self.commitments]
        others += [g.monthly for g in self.goals]
        for amount in others:
            if amount.currency != currency:
                raise CurrencyMismatch(
                    f"snapshot mixes {currency} with {amount.currency}"
                )

    @property
    def currency(self) -> str:
        return self.balance.currency


@dataclass(frozen=True, slots=True)
class SafeToSpend:
    """The engine's answer, with every intermediate the UI shows in 'the working'."""

    days_to_payday: int
    cycle_elapsed: int
    balance: Money
    reserved: Money
    buffer: Money
    goal_reserve: Money
    unclaimed: Money
    per_day: Money
    spent_today: Money
    safe_today: Money
```

- [ ] **Step 4: Write `apps/api/kira/engine/safe_to_spend.py`**

```python
"""How much of today's money is genuinely free to spend.

Pure: no I/O, no database, no clock. Every date arrives on the Snapshot.
"""

from __future__ import annotations

from kira.engine.types import SafeToSpend, Snapshot
from kira.money import Money, round_half_up


def safe_to_spend(snapshot: Snapshot) -> SafeToSpend:
    currency = snapshot.currency

    days_to_payday = max(1, (snapshot.next_payday - snapshot.today).days)
    cycle_elapsed = min(
        snapshot.cycle_days,
        max(0, (snapshot.today - snapshot.cycle_start).days),
    )

    # A goal claims what has accrued so far this cycle, not its whole contribution.
    # Each goal is rounded once, on its own; rounded parts are never re-divided.
    goal_reserve = Money.sum(
        (
            Money(round_half_up(goal.monthly.sen * cycle_elapsed, snapshot.cycle_days), currency)
            for goal in snapshot.goals
        ),
        currency,
    )

    # Only bills that land before the next payday compete with today's money.
    reserved = Money.sum(
        (c.amount for c in snapshot.commitments if c.due_date < snapshot.next_payday),
        currency,
    )

    unclaimed = snapshot.balance - reserved - snapshot.buffer - goal_reserve
    per_day = unclaimed.divide_floor(days_to_payday)
    safe_today = max(Money.zero(currency), per_day - snapshot.spent_today)

    return SafeToSpend(
        days_to_payday=days_to_payday,
        cycle_elapsed=cycle_elapsed,
        balance=snapshot.balance,
        reserved=reserved,
        buffer=snapshot.buffer,
        goal_reserve=goal_reserve,
        unclaimed=unclaimed,
        per_day=per_day,
        spent_today=snapshot.spent_today,
        safe_today=safe_today,
    )
```

- [ ] **Step 5: Write `apps/api/kira/engine/__init__.py`**

```python
"""Pure finance calculations. This package imports nothing from the rest of Kira."""

from kira.engine.safe_to_spend import safe_to_spend
from kira.engine.types import CommitmentInput, GoalInput, SafeToSpend, Snapshot

__all__ = ["CommitmentInput", "GoalInput", "SafeToSpend", "Snapshot", "safe_to_spend"]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd apps/api && .venv/bin/pytest tests/engine -q`
Expected: PASS — all tests green.

- [ ] **Step 7: Write the golden-case loader at `apps/api/tests/engine/case_loader.py`**

```python
"""Turns a JSON golden case into engine inputs and an expected-output dict."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import Money

CASES_DIR = Path(__file__).parent / "cases"


def load_cases() -> list[tuple[str, dict[str, Any]]]:
    return [(path.stem, json.loads(path.read_text())) for path in sorted(CASES_DIR.glob("*.json"))]


def build_snapshot(spec: dict[str, Any]) -> Snapshot:
    currency = spec.get("currency", "MYR")
    return Snapshot(
        balance=Money(spec["balance"], currency),
        buffer=Money(spec["buffer"], currency),
        spent_today=Money(spec["spent_today"], currency),
        commitments=tuple(
            CommitmentInput(c["id"], Money(c["amount"], currency), date.fromisoformat(c["due_date"]))
            for c in spec["commitments"]
        ),
        goals=tuple(
            GoalInput(g["id"], Money(g["monthly"], currency)) for g in spec["goals"]
        ),
        today=date.fromisoformat(spec["today"]),
        next_payday=date.fromisoformat(spec["next_payday"]),
        cycle_start=date.fromisoformat(spec["cycle_start"]),
        cycle_days=spec["cycle_days"],
    )


def actual_output(result) -> dict[str, int]:
    """Flatten a SafeToSpend into the plain-int shape the golden files record."""
    return {
        "days_to_payday": result.days_to_payday,
        "cycle_elapsed": result.cycle_elapsed,
        "reserved": result.reserved.sen,
        "goal_reserve": result.goal_reserve.sen,
        "unclaimed": result.unclaimed.sen,
        "per_day": result.per_day.sen,
        "safe_today": result.safe_today.sen,
    }
```

- [ ] **Step 8: Write the golden case files**

`apps/api/tests/engine/cases/demo_baseline.json`:

```json
{
  "name": "The demo user, nothing confirmed yet today",
  "input": {
    "currency": "MYR",
    "balance": 418040,
    "buffer": 80000,
    "spent_today": 0,
    "today": "2026-09-03",
    "next_payday": "2026-09-25",
    "cycle_start": "2026-08-26",
    "cycle_days": 30,
    "commitments": [
      {"id": "rent", "amount": 120000, "due_date": "2026-09-05"},
      {"id": "phone", "amount": 8900, "due_date": "2026-09-08"},
      {"id": "loan", "amount": 52000, "due_date": "2026-09-10"},
      {"id": "sub", "amount": 5500, "due_date": "2026-09-14"},
      {"id": "net", "amount": 13900, "due_date": "2026-09-18"}
    ],
    "goals": [
      {"id": "g1", "monthly": 27000},
      {"id": "g2", "monthly": 52500}
    ]
  },
  "expected": {
    "days_to_payday": 22,
    "cycle_elapsed": 8,
    "reserved": 200300,
    "goal_reserve": 21200,
    "unclaimed": 116540,
    "per_day": 5297,
    "safe_today": 5297
  }
}
```

`apps/api/tests/engine/cases/receipt_confirmed.json` — the demo baseline after the RM18.90 receipt is confirmed. Balance drops and the same amount is recorded as spent today, which is what confirming a draft does:

```json
{
  "name": "After confirming the RM18.90 receipt",
  "input": {
    "currency": "MYR",
    "balance": 416150,
    "buffer": 80000,
    "spent_today": 1890,
    "today": "2026-09-03",
    "next_payday": "2026-09-25",
    "cycle_start": "2026-08-26",
    "cycle_days": 30,
    "commitments": [
      {"id": "rent", "amount": 120000, "due_date": "2026-09-05"},
      {"id": "phone", "amount": 8900, "due_date": "2026-09-08"},
      {"id": "loan", "amount": 52000, "due_date": "2026-09-10"},
      {"id": "sub", "amount": 5500, "due_date": "2026-09-14"},
      {"id": "net", "amount": 13900, "due_date": "2026-09-18"}
    ],
    "goals": [
      {"id": "g1", "monthly": 27000},
      {"id": "g2", "monthly": 52500}
    ]
  },
  "expected": {
    "days_to_payday": 22,
    "cycle_elapsed": 8,
    "reserved": 200300,
    "goal_reserve": 21200,
    "unclaimed": 114650,
    "per_day": 5211,
    "safe_today": 3321
  }
}
```

`apps/api/tests/engine/cases/bill_after_payday.json` — the internet bill moves past payday and stops competing for this cycle's money:

```json
{
  "name": "A bill falling after payday is not reserved",
  "input": {
    "currency": "MYR",
    "balance": 418040,
    "buffer": 80000,
    "spent_today": 0,
    "today": "2026-09-03",
    "next_payday": "2026-09-25",
    "cycle_start": "2026-08-26",
    "cycle_days": 30,
    "commitments": [
      {"id": "rent", "amount": 120000, "due_date": "2026-09-05"},
      {"id": "phone", "amount": 8900, "due_date": "2026-09-08"},
      {"id": "loan", "amount": 52000, "due_date": "2026-09-10"},
      {"id": "sub", "amount": 5500, "due_date": "2026-09-14"},
      {"id": "net", "amount": 13900, "due_date": "2026-09-30"}
    ],
    "goals": [
      {"id": "g1", "monthly": 27000},
      {"id": "g2", "monthly": 52500}
    ]
  },
  "expected": {
    "days_to_payday": 22,
    "cycle_elapsed": 8,
    "reserved": 186400,
    "goal_reserve": 21200,
    "unclaimed": 130440,
    "per_day": 5929,
    "safe_today": 5929
  }
}
```

`apps/api/tests/engine/cases/overspent.json` — the overspend scenario from the demo script:

```json
{
  "name": "Overspent today, room floors at zero",
  "input": {
    "currency": "MYR",
    "balance": 406040,
    "buffer": 80000,
    "spent_today": 12000,
    "today": "2026-09-03",
    "next_payday": "2026-09-25",
    "cycle_start": "2026-08-26",
    "cycle_days": 30,
    "commitments": [
      {"id": "rent", "amount": 120000, "due_date": "2026-09-05"},
      {"id": "phone", "amount": 8900, "due_date": "2026-09-08"},
      {"id": "loan", "amount": 52000, "due_date": "2026-09-10"},
      {"id": "sub", "amount": 5500, "due_date": "2026-09-14"},
      {"id": "net", "amount": 13900, "due_date": "2026-09-18"}
    ],
    "goals": [
      {"id": "g1", "monthly": 27000},
      {"id": "g2", "monthly": 52500}
    ]
  },
  "expected": {
    "days_to_payday": 22,
    "cycle_elapsed": 8,
    "reserved": 200300,
    "goal_reserve": 21200,
    "unclaimed": 104540,
    "per_day": 4751,
    "safe_today": 0
  }
}
```

`apps/api/tests/engine/cases/deficit.json` — commitments exceed the balance:

```json
{
  "name": "Commitments exceed the balance",
  "input": {
    "currency": "MYR",
    "balance": 100000,
    "buffer": 80000,
    "spent_today": 0,
    "today": "2026-09-03",
    "next_payday": "2026-09-25",
    "cycle_start": "2026-08-26",
    "cycle_days": 30,
    "commitments": [
      {"id": "rent", "amount": 120000, "due_date": "2026-09-05"},
      {"id": "phone", "amount": 8900, "due_date": "2026-09-08"},
      {"id": "loan", "amount": 52000, "due_date": "2026-09-10"},
      {"id": "sub", "amount": 5500, "due_date": "2026-09-14"},
      {"id": "net", "amount": 13900, "due_date": "2026-09-18"}
    ],
    "goals": [
      {"id": "g1", "monthly": 27000},
      {"id": "g2", "monthly": 52500}
    ]
  },
  "expected": {
    "days_to_payday": 22,
    "cycle_elapsed": 8,
    "reserved": 200300,
    "goal_reserve": 21200,
    "unclaimed": -201500,
    "per_day": -9160,
    "safe_today": 0
  }
}
```

`apps/api/tests/engine/cases/no_goals_first_day.json` — a brand-new user on day one of their cycle:

```json
{
  "name": "New user, no goals, first day of the cycle",
  "input": {
    "currency": "MYR",
    "balance": 250000,
    "buffer": 50000,
    "spent_today": 0,
    "today": "2026-09-03",
    "next_payday": "2026-09-25",
    "cycle_start": "2026-09-03",
    "cycle_days": 30,
    "commitments": [],
    "goals": []
  },
  "expected": {
    "days_to_payday": 22,
    "cycle_elapsed": 0,
    "reserved": 0,
    "goal_reserve": 0,
    "unclaimed": 200000,
    "per_day": 9090,
    "safe_today": 9090
  }
}
```

- [ ] **Step 9: Write the golden test at `apps/api/tests/engine/test_golden.py`**

```python
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
```

- [ ] **Step 10: Run the golden suite**

Run: `cd apps/api && .venv/bin/pytest tests/engine -q`
Expected: PASS — 6 golden cases plus the unit tests. If a golden case fails, the expected values in the JSON are authoritative: fix the engine, not the file.

- [ ] **Step 11: Commit**

```bash
git add apps/api/kira/engine apps/api/tests/engine
git commit -m "feat: add pure finance engine with golden-file test suite"
```

---

## Task 4: Purity gates — import-linter and the float ban

**Files:**
- Create: `apps/api/tests/engine/test_engine_purity.py`
- Modify: `apps/api/pyproject.toml` (contracts were added in Task 1 — verify they pass)

**Interfaces:**
- Consumes: `kira.engine` package from Task 3.
- Produces: two CI gates. No importable API.

- [ ] **Step 1: Write the failing test at `apps/api/tests/engine/test_engine_purity.py`**

```python
"""The engine's purity is a property of the code, not a promise in a comment."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import kira.engine

ENGINE_DIR = Path(kira.engine.__file__).parent
ENGINE_FILES = sorted(ENGINE_DIR.glob("*.py"))

FORBIDDEN_CALLS = {"round", "float", "open", "print", "input"}
FORBIDDEN_IMPORT_ROOTS = {
    "kira.api",
    "kira.services",
    "kira.adapters",
    "kira.db",
    "kira.agent",
    "kira.seed",
    "sqlalchemy",
    "fastapi",
    "httpx",
    "requests",
    "asyncio",
    "random",
    "time",
}


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def test_engine_has_files():
    assert ENGINE_FILES


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_float_anywhere(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"{path.name}:{node.lineno} contains the float literal {node.value!r}")
        if isinstance(node, ast.Name) and node.id == "float":
            pytest.fail(f"{path.name}:{node.lineno} references float")


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_true_division(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            pytest.fail(
                f"{path.name}:{node.lineno} uses '/', which produces a float. "
                "Use round_half_up or Money.divide_floor."
            )


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_builtin_round_or_io(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                pytest.fail(
                    f"{path.name}:{node.lineno} calls {node.func.id}(). "
                    "The engine is pure and rounds half-up via round_half_up."
                )


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_clock_reads(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"today", "now", "utcnow"}:
                pytest.fail(
                    f"{path.name}:{node.lineno} reads the clock. "
                    "Dates arrive on the Snapshot."
                )


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_imports_only_stdlib_and_money(path: Path):
    for node in ast.walk(parsed(path)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            for forbidden in FORBIDDEN_IMPORT_ROOTS:
                if name == forbidden or name.startswith(forbidden + "."):
                    pytest.fail(f"{path.name}:{node.lineno} imports {name}")
            if name.startswith("kira.") and name not in {"kira.money"} and not name.startswith(
                "kira.engine"
            ):
                pytest.fail(f"{path.name}:{node.lineno} imports {name}")


def test_import_linter_contracts_hold():
    result = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint"],
        cwd=Path(kira.engine.__file__).parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the test**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_engine_purity.py -q`
Expected: PASS. If `test_no_true_division` fails, the engine used `/` somewhere — replace it with `round_half_up` or `Money.divide_floor`. If `test_import_linter_contracts_hold` fails, read the reported contract and remove the offending import.

- [ ] **Step 3: Prove the gate actually bites**

Temporarily append `_BAD = 1.5` to `apps/api/kira/engine/safe_to_spend.py`, then:

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_engine_purity.py -q`
Expected: FAIL with "contains the float literal 1.5". Remove the line and re-run; expected PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/api/tests/engine/test_engine_purity.py
git commit -m "test: enforce engine purity with AST and import-linter gates"
```

---

## Task 5: Database layer — MoneyType, models, session, first migration

**Files:**
- Create: `apps/api/kira/config.py`, `apps/api/kira/db/__init__.py`, `apps/api/kira/db/types.py`, `apps/api/kira/db/base.py`, `apps/api/kira/db/models.py`, `apps/api/kira/db/session.py`
- Create: `apps/api/alembic.ini`, `apps/api/alembic/env.py`, `apps/api/alembic/script.py.mako`, `apps/api/alembic/versions/0001_initial.py`
- Test: `apps/api/tests/conftest.py`, `apps/api/tests/db/__init__.py`, `apps/api/tests/db/test_money_type.py`

**Interfaces:**
- Consumes: `kira.money.Money`.
- Produces:
  - `kira.config.Settings` with `database_url`, `jwt_secret`, `access_token_ttl_minutes`, `refresh_token_ttl_days`, `cors_origins: list[str]`, `demo_today: date | None`; and `get_settings() -> Settings` (cached).
  - `kira.db.types.MoneyType(currency="MYR")` — a `TypeDecorator` over `BigInteger`.
  - `kira.db.base.Base` — the declarative base.
  - `kira.db.models`: `User`, `RefreshToken`, `Account`, `Commitment`, `Goal`, `Transaction`, and the constants `TXN_DRAFT = "draft"`, `TXN_CONFIRMED = "confirmed"`.
  - `kira.db.session.get_session()` — an async generator FastAPI dependency yielding `AsyncSession`.
  - Test fixtures `session` (an `AsyncSession` on in-memory SQLite) and `client` (an `httpx.AsyncClient` bound to the app with `get_session` overridden).

**Model notes:** a user's balance is never a stored, mutable number. Each `Account` holds an `opening_balance`; the live balance is `opening_balance` minus every **confirmed** transaction. That is what makes the draft invariant structural rather than remembered.

- [ ] **Step 1: Write `apps/api/kira/config.py`**

```python
"""Runtime configuration. Everything is overridable by environment variable."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kira:kira@localhost:5432/kira"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]

    # Pins "today" so the seeded demo produces the same numbers on any date.
    # Unset in real use, in which case the server's UTC date is used.
    demo_today: date | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Write the failing test at `apps/api/tests/db/test_money_type.py`**

```python
from datetime import date

import pytest
import sqlalchemy as sa

from kira.db.models import Account, User
from kira.money import Money


async def make_user(session) -> User:
    user = User(
        email="a@example.com",
        password_hash="x",
        display_name="A",
        buffer=Money(80000),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
    )
    session.add(user)
    await session.flush()
    return user


class TestMoneyType:
    async def test_round_trips_money(self, session):
        user = await make_user(session)
        session.add(Account(user_id=user.id, name="Main", kind="bank", opening_balance=Money(418040)))
        await session.flush()
        session.expunge_all()

        account = (await session.execute(sa.select(Account))).scalar_one()
        assert account.opening_balance == Money(418040)
        assert isinstance(account.opening_balance, Money)

    async def test_stores_integer_sen_in_the_column(self, session):
        user = await make_user(session)
        session.add(Account(user_id=user.id, name="Main", kind="bank", opening_balance=Money(418040)))
        await session.flush()

        raw = (await session.execute(sa.text("SELECT opening_balance FROM accounts"))).scalar_one()
        assert raw == 418040

    async def test_rejects_a_float(self, session):
        user = await make_user(session)
        session.add(Account(user_id=user.id, name="Main", kind="bank", opening_balance=4180.40))
        with pytest.raises(TypeError):
            await session.flush()

    async def test_rejects_a_bare_int(self, session):
        user = await make_user(session)
        session.add(Account(user_id=user.id, name="Main", kind="bank", opening_balance=418040))
        with pytest.raises(TypeError):
            await session.flush()

    async def test_rejects_the_wrong_currency(self, session):
        user = await make_user(session)
        session.add(
            Account(user_id=user.id, name="Main", kind="bank", opening_balance=Money(1, "SGD"))
        )
        with pytest.raises(ValueError):
            await session.flush()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd apps/api && mkdir -p tests/db && touch tests/db/__init__.py && .venv/bin/pytest tests/db -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.db'`.

- [ ] **Step 4: Write `apps/api/kira/db/types.py`**

```python
"""The SQLAlchemy boundary for money. A float cannot physically reach a column."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Dialect
from sqlalchemy.types import TypeDecorator

from kira.money import Money


class MoneyType(TypeDecorator):
    """Stores a Money as an integer count of sen.

    The currency is fixed per column rather than stored per row: the MVP is
    MYR-only, and a column that could silently hold two currencies is a bug
    waiting to happen. Widening this means adding a sibling currency column.
    """

    impl = BigInteger
    cache_ok = True

    def __init__(self, currency: str = "MYR") -> None:
        super().__init__()
        self.currency = currency

    def process_bind_param(self, value: Any, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if not isinstance(value, Money):
            raise TypeError(
                f"money columns take a Money, got {type(value).__name__}: {value!r}"
            )
        if value.currency != self.currency:
            raise ValueError(
                f"column holds {self.currency}, got {value.currency}"
            )
        return value.sen

    def process_result_value(self, value: Any, dialect: Dialect) -> Money | None:
        if value is None:
            return None
        return Money(int(value), self.currency)
```

- [ ] **Step 5: Write `apps/api/kira/db/base.py`**

```python
"""Declarative base with an explicit constraint naming convention.

Named constraints keep Alembic autogenerate deterministic across databases.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

- [ ] **Step 6: Write `apps/api/kira/db/models.py`**

```python
"""The persistent shape of a user's financial picture.

Balance is derived, never stored: an account holds an opening balance, and the
live balance is that minus every confirmed transaction. Drafts cannot affect it
because they are excluded by status, not by remembering to filter.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kira.db.base import Base
from kira.db.types import MoneyType
from kira.money import Money

TXN_DRAFT = "draft"
TXN_CONFIRMED = "confirmed"
TXN_STATUSES = (TXN_DRAFT, TXN_CONFIRMED)

SOURCE_MANUAL = "manual"
SOURCE_RECEIPT = "receipt"
SOURCE_VOICE = "voice"
SOURCE_IMPORT = "import"

HORIZON_SHORT = "short"
HORIZON_LONG = "long"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3), default="MYR")
    buffer: Mapped[Money] = mapped_column(MoneyType(), default=lambda: Money(0))
    next_payday: Mapped[date] = mapped_column(Date)
    cycle_start: Mapped[date] = mapped_column(Date)
    cycle_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list[Account]] = relationship(back_populates="user", lazy="selectin")
    commitments: Mapped[list[Commitment]] = relationship(back_populates="user", lazy="selectin")
    goals: Mapped[list[Goal]] = relationship(back_populates="user", lazy="selectin")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(24))  # bank | ewallet | cash
    opening_balance: Mapped[Money] = mapped_column(MoneyType())

    user: Mapped[User] = relationship(back_populates="accounts")


class Commitment(Base):
    __tablename__ = "commitments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Money] = mapped_column(MoneyType())
    due_date: Mapped[date] = mapped_column(Date, index=True)
    protected: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="commitments")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    horizon: Mapped[str] = mapped_column(String(8))  # short | long
    target: Mapped[Money] = mapped_column(MoneyType())
    saved: Mapped[Money] = mapped_column(MoneyType())
    monthly: Mapped[Money] = mapped_column(MoneyType())
    note: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(back_populates="goals")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    merchant: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Money] = mapped_column(MoneyType())
    category: Mapped[str] = mapped_column(String(40), default="Uncategorised")
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(12), default=TXN_DRAFT, index=True)
    source: Mapped[str] = mapped_column(String(12), default=SOURCE_MANUAL)
    # Whole percent, 0-100. Deliberately not a float: confidence is displayed,
    # and a displayed number should not carry binary rounding error.
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 7: Write `apps/api/kira/db/session.py`**

```python
"""One async engine per process, one session per request."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from kira.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        yield session
```

- [ ] **Step 8: Write `apps/api/kira/db/__init__.py`**

```python
from kira.db.base import Base
from kira.db.session import get_session

__all__ = ["Base", "get_session"]
```

- [ ] **Step 9: Write `apps/api/tests/conftest.py`**

```python
"""Tests run against in-memory SQLite so the suite needs no network and no docker.

The schema comes from the same metadata Postgres uses; the migration itself is
verified against real Postgres in the Docker task.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from kira.db.base import Base
from kira.db.session import get_session


@pytest.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
async def client(session) -> AsyncGenerator[AsyncClient, None]:
    from kira.api.app import create_app

    app = create_app()

    async def override() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

- [ ] **Step 10: Run the MoneyType test**

Run: `cd apps/api && .venv/bin/pytest tests/db -q`
Expected: PASS — five tests green. If `test_rejects_a_float` errors with a SQLAlchemy `StatementError` wrapping the `TypeError` rather than a bare `TypeError`, change the two rejection tests to `pytest.raises((TypeError, sa.exc.StatementError))` and assert on `str(excinfo.value)` containing "money columns take a Money". Do not weaken the type check itself.

- [ ] **Step 11: Write `apps/api/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 12: Write `apps/api/alembic/env.py`**

```python
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from kira.config import get_settings
from kira.db.base import Base
from kira.db import models  # noqa: F401  — imported for its side effect of registering tables

target_metadata = Base.metadata


def run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async())
```

- [ ] **Step 13: Write `apps/api/alembic/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 14: Write `apps/api/alembic/versions/0001_initial.py`**

```python
"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("buffer", sa.BigInteger(), nullable=False),
        sa.Column("next_payday", sa.Date(), nullable=False),
        sa.Column("cycle_start", sa.Date(), nullable=False),
        sa.Column("cycle_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("opening_balance", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_accounts_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
    )
    op.create_index("ix_accounts_user_id", "accounts", ["user_id"])

    op.create_table(
        "commitments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("protected", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_commitments_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_commitments"),
    )
    op.create_index("ix_commitments_user_id", "commitments", ["user_id"])
    op.create_index("ix_commitments_due_date", "commitments", ["due_date"])

    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("horizon", sa.String(length=8), nullable=False),
        sa.Column("target", sa.BigInteger(), nullable=False),
        sa.Column("saved", sa.BigInteger(), nullable=False),
        sa.Column("monthly", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_goals_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_goals"),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_transactions_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_status", "transactions", ["status"])
    op.create_index("ix_transactions_occurred_on", "transactions", ["occurred_on"])


def downgrade() -> None:
    for table in ("transactions", "goals", "commitments", "accounts", "refresh_tokens", "users"):
        op.drop_table(table)
```

- [ ] **Step 15: Run the migration against real Postgres**

```bash
cd apps/api && DATABASE_URL=postgresql+asyncpg://kira:kira@localhost:5432/kira .venv/bin/alembic upgrade head
```

Expected: exits 0. Verify: `docker compose exec db psql -U kira -d kira -c '\dt'` lists all six tables plus `alembic_version`.

- [ ] **Step 16: Confirm the migration matches the models**

```bash
cd apps/api && DATABASE_URL=postgresql+asyncpg://kira:kira@localhost:5432/kira .venv/bin/alembic check
```

Expected: "No new upgrade operations detected." If it reports differences, the hand-written migration has drifted from `models.py` — fix the migration to match the models.

- [ ] **Step 17: Commit**

```bash
git add apps/api/kira/config.py apps/api/kira/db apps/api/alembic apps/api/alembic.ini apps/api/tests/conftest.py apps/api/tests/db
git commit -m "feat: add database layer with MoneyType, models, and initial migration"
```

---

## Task 6: Authentication

**Files:**
- Create: `apps/api/kira/services/__init__.py`, `apps/api/kira/services/auth.py`, `apps/api/kira/api/__init__.py`, `apps/api/kira/api/app.py`, `apps/api/kira/api/deps.py`, `apps/api/kira/api/schemas.py`, `apps/api/kira/api/routers/__init__.py`, `apps/api/kira/api/routers/auth.py`
- Test: `apps/api/tests/api/__init__.py`, `apps/api/tests/api/test_auth.py`

**Interfaces:**
- Consumes: `kira.db.models.User`, `kira.db.models.RefreshToken`, `kira.db.session.get_session`, `kira.config.get_settings`.
- Produces:
  - `kira.services.auth`: `hash_password(raw) -> str`; `verify_password(raw, hashed) -> bool`; `create_access_token(user_id: uuid.UUID) -> str`; `decode_access_token(token) -> uuid.UUID`; `async issue_refresh_token(session, user) -> str`; `async rotate_refresh_token(session, raw) -> tuple[User, str]`; `async revoke_refresh_token(session, raw) -> None`; `class AuthError(Exception)`.
  - `kira.api.app.create_app() -> FastAPI`.
  - `kira.api.deps.current_user` — a FastAPI dependency returning a `User`.
  - `kira.api.schemas`: `RegisterRequest`, `LoginRequest`, `TokenResponse`, `UserResponse`.
  - Endpoints: `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/refresh`, `POST /v1/auth/logout`, `GET /v1/auth/me`, `GET /v1/health`.
  - The refresh token lives in an `httpOnly` cookie named `kira_refresh`.

- [ ] **Step 1: Write the failing test at `apps/api/tests/api/test_auth.py`**

```python
import pytest

REGISTER = {
    "email": "demo@kira.app",
    "password": "correct horse battery staple",
    "display_name": "Floyd",
}


async def register(client) -> str:
    response = await client.post("/v1/auth/register", json=REGISTER)
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


class TestHealth:
    async def test_health_needs_no_auth(self, client):
        response = await client.get("/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestRegister:
    async def test_returns_an_access_token_and_sets_a_refresh_cookie(self, client):
        response = await client.post("/v1/auth/register", json=REGISTER)
        assert response.status_code == 201
        assert response.json()["access_token"]
        assert response.json()["token_type"] == "bearer"
        assert "kira_refresh" in response.cookies

    async def test_never_returns_the_password_hash(self, client):
        response = await client.post("/v1/auth/register", json=REGISTER)
        assert "password" not in response.text
        assert "hash" not in response.text

    async def test_duplicate_email_is_rejected(self, client):
        await client.post("/v1/auth/register", json=REGISTER)
        response = await client.post("/v1/auth/register", json=REGISTER)
        assert response.status_code == 409

    async def test_short_password_is_rejected(self, client):
        response = await client.post("/v1/auth/register", json={**REGISTER, "password": "short"})
        assert response.status_code == 422


class TestLogin:
    async def test_correct_password_succeeds(self, client):
        await register(client)
        response = await client.post(
            "/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    async def test_wrong_password_fails(self, client):
        await register(client)
        response = await client.post(
            "/v1/auth/login", json={"email": REGISTER["email"], "password": "wrong"}
        )
        assert response.status_code == 401

    async def test_unknown_email_fails_the_same_way(self, client):
        response = await client.post(
            "/v1/auth/login", json={"email": "nobody@kira.app", "password": "whatever"}
        )
        assert response.status_code == 401


class TestMe:
    async def test_returns_the_authenticated_user(self, client):
        token = await register(client)
        response = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["email"] == REGISTER["email"]
        assert response.json()["display_name"] == "Floyd"

    async def test_missing_token_is_401(self, client):
        response = await client.get("/v1/auth/me")
        assert response.status_code == 401

    async def test_garbage_token_is_401(self, client):
        response = await client.get("/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
        assert response.status_code == 401


class TestRefresh:
    async def test_rotates_the_token(self, client):
        await register(client)
        first_cookie = client.cookies["kira_refresh"]
        response = await client.post("/v1/auth/refresh")
        assert response.status_code == 200
        assert response.json()["access_token"]
        assert client.cookies["kira_refresh"] != first_cookie

    async def test_a_used_token_cannot_be_reused(self, client):
        await register(client)
        used = client.cookies["kira_refresh"]
        await client.post("/v1/auth/refresh")
        response = await client.post("/v1/auth/refresh", cookies={"kira_refresh": used})
        assert response.status_code == 401

    async def test_without_a_cookie_is_401(self, client):
        response = await client.post("/v1/auth/refresh")
        assert response.status_code == 401


class TestLogout:
    async def test_revokes_the_refresh_token(self, client):
        await register(client)
        response = await client.post("/v1/auth/logout")
        assert response.status_code == 204
        assert (await client.post("/v1/auth/refresh")).status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && mkdir -p tests/api && touch tests/api/__init__.py && .venv/bin/pytest tests/api -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.api'`.

- [ ] **Step 3: Write `apps/api/kira/services/auth.py`**

```python
"""Password hashing, access tokens, and rotating refresh tokens.

Refresh tokens are stored only as SHA-256 digests: a stolen database dump does
not yield usable sessions. Every refresh rotates — the presented token is
revoked as it is exchanged — so a replayed token is always rejected.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.config import get_settings
from kira.db.models import RefreshToken, User

_hasher = PasswordHasher()

REFRESH_COOKIE = "kira_refresh"


class AuthError(Exception):
    """Any failure to prove identity. The caller turns this into a 401."""


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError):
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("invalid access token") from exc
    if payload.get("typ") != "access":
        raise AuthError("wrong token type")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthError("malformed subject") from exc


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_refresh_token(session: AsyncSession, user: User) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_digest(raw),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await session.flush()
    return raw


async def _load_live_token(session: AsyncSession, raw: str) -> RefreshToken:
    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == _digest(raw)))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise AuthError("unknown or revoked refresh token")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise AuthError("expired refresh token")
    return row


async def rotate_refresh_token(session: AsyncSession, raw: str) -> tuple[User, str]:
    row = await _load_live_token(session, raw)
    row.revoked_at = datetime.now(UTC)
    user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one()
    replacement = await issue_refresh_token(session, user)
    await session.commit()
    return user, replacement


async def revoke_refresh_token(session: AsyncSession, raw: str) -> None:
    try:
        row = await _load_live_token(session, raw)
    except AuthError:
        return  # Logging out an already-dead token is a success, not an error.
    row.revoked_at = datetime.now(UTC)
    await session.commit()
```

- [ ] **Step 4: Write `apps/api/kira/api/schemas.py`**

```python
"""Wire shapes. Money crosses the wire as an integer sen field named *_sen."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    currency: str
    buffer_sen: int
    next_payday: date
    cycle_start: date
    cycle_days: int
```

`EmailStr` needs `pydantic[email]`. Add `"pydantic[email]>=2.9"` to the `dependencies` list in `pyproject.toml`, replacing the plain `pydantic` entry, and re-run `pip install -e ".[dev]"`.

- [ ] **Step 5: Write `apps/api/kira/api/deps.py`**

```python
"""Request-scoped dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import User
from kira.db.session import get_session
from kira.services.auth import AuthError, decode_access_token

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

UNAUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None:
        raise UNAUTHORISED
    try:
        user_id = decode_access_token(credentials.credentials)
    except AuthError as exc:
        raise UNAUTHORISED from exc
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise UNAUTHORISED
    return user


CurrentUser = Annotated[User, Depends(current_user)]
```

- [ ] **Step 6: Write `apps/api/kira/api/routers/auth.py`**

```python
"""Registration, login, rotation, revocation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from kira.api.deps import CurrentUser, SessionDep, UNAUTHORISED
from kira.api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from kira.config import get_settings
from kira.db.models import User
from kira.money import Money
from kira.services.auth import (
    REFRESH_COOKIE,
    AuthError,
    create_access_token,
    hash_password,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from kira.services.clock import today_for

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        httponly=True,
        samesite="lax",
        secure=False,  # The app is served over http in local development.
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/v1/auth",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
async def register(body: RegisterRequest, response: Response, session: SessionDep) -> TokenResponse:
    today = today_for()
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        buffer=Money(0),
        next_payday=today,
        cycle_start=today,
        cycle_days=30,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already registered") from exc

    raw = await issue_refresh_token(session, user)
    await session.commit()
    _set_refresh_cookie(response, raw)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, session: SessionDep) -> TokenResponse:
    user = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    # Verify regardless, so a missing account and a wrong password cost the same.
    ok = verify_password(body.password, user.password_hash) if user else False
    if not user or not ok:
        raise UNAUTHORISED
    raw = await issue_refresh_token(session, user)
    await session.commit()
    _set_refresh_cookie(response, raw)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, session: SessionDep) -> TokenResponse:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise UNAUTHORISED
    try:
        user, replacement = await rotate_refresh_token(session, raw)
    except AuthError as exc:
        raise UNAUTHORISED from exc
    _set_refresh_cookie(response, replacement)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await revoke_refresh_token(session, raw)
    response.delete_cookie(REFRESH_COOKIE, path="/v1/auth")


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        currency=user.currency,
        buffer_sen=user.buffer.sen,
        next_payday=user.next_payday,
        cycle_start=user.cycle_start,
        cycle_days=user.cycle_days,
    )
```

- [ ] **Step 7: Write `apps/api/kira/services/clock.py`**

The engine takes dates as parameters; something above it has to decide what "today" is. That decision lives here, in one place, and can be pinned for the demo.

```python
"""The one place the system reads a calendar."""

from __future__ import annotations

from datetime import UTC, date, datetime

from kira.config import get_settings


def today_for() -> date:
    """Today's date, or the pinned demo date when one is configured."""
    settings = get_settings()
    if settings.demo_today is not None:
        return settings.demo_today
    return datetime.now(UTC).date()
```

- [ ] **Step 8: Write `apps/api/kira/api/app.py`**

The static-file mount is added in Task 14; for now the app is API-only.

```python
"""Application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kira.api.routers import auth
from kira.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Kira API", version="0.1.0", docs_url="/v1/docs", openapi_url="/v1/openapi.json")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/v1/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    return app


app = create_app()
```

Also create empty `apps/api/kira/api/__init__.py`, `apps/api/kira/api/routers/__init__.py`, and `apps/api/kira/services/__init__.py`.

- [ ] **Step 9: Run the auth tests**

Run: `cd apps/api && .venv/bin/pytest tests/api -q`
Expected: PASS — all auth tests green.

- [ ] **Step 10: Check the layering contracts still hold**

Run: `cd apps/api && .venv/bin/lint-imports`
Expected: "Contracts: 2 kept, 0 broken."

- [ ] **Step 11: Commit**

```bash
git add apps/api/kira/api apps/api/kira/services apps/api/tests/api
git commit -m "feat: add JWT auth with rotating refresh tokens"
```

---

## Task 7: Adapter protocols and their fakes

**Files:**
- Create: `apps/api/kira/adapters/__init__.py`, `apps/api/kira/adapters/protocols.py`, `apps/api/kira/adapters/fakes.py`, `apps/api/kira/adapters/registry.py`
- Test: `apps/api/tests/adapters/__init__.py`, `apps/api/tests/adapters/test_fakes.py`

**Interfaces:**
- Consumes: `kira.money.Money`.
- Produces:
  - `kira.adapters.protocols`: `ReceiptRead(merchant: str, amount: Money, occurred_on: date, confidence: int, note: str)`; `VoiceRead(transcript: str, merchant: str, amount: Money, confidence: int, note: str)`; `Place(id, name, kind, lat, lng, estimate: Money, confidence: str, halal: bool, note: str)`; and the Protocols `OcrAdapter.read_receipt(image: bytes) -> ReceiptRead`, `VoiceAdapter.transcribe(audio: bytes) -> VoiceRead`, `MapsAdapter.places_near(lat: float, lng: float, radius_km: float) -> list[Place]`, `StorageAdapter.put(key: str, data: bytes) -> str` / `get(key: str) -> bytes`, `LlmAdapter.complete(system: str, messages: list[dict[str, str]]) -> str`.
  - `kira.adapters.fakes`: `FakeOcr`, `FakeVoice`, `FakeMaps`, `InMemoryStorage`, `ScriptedLlm`.
  - `kira.adapters.registry.get_adapters() -> Adapters` — a frozen dataclass with one field per adapter, all fakes in week 1.

**Note:** latitude and longitude are `float` here and that is correct — they are coordinates, not money. The float ban applies to `kira/engine/` and to monetary values everywhere.

- [ ] **Step 1: Write the failing test at `apps/api/tests/adapters/test_fakes.py`**

```python
from datetime import date

from kira.adapters.fakes import FakeMaps, FakeOcr, FakeVoice, InMemoryStorage, ScriptedLlm
from kira.adapters.protocols import LlmAdapter, MapsAdapter, OcrAdapter, StorageAdapter, VoiceAdapter
from kira.adapters.registry import get_adapters
from kira.money import Money


class TestProtocolConformance:
    def test_every_fake_satisfies_its_protocol(self):
        assert isinstance(FakeOcr(), OcrAdapter)
        assert isinstance(FakeVoice(), VoiceAdapter)
        assert isinstance(FakeMaps(), MapsAdapter)
        assert isinstance(InMemoryStorage(), StorageAdapter)
        assert isinstance(ScriptedLlm(["hello"]), LlmAdapter)


class TestFakeOcr:
    def test_reads_the_demo_receipt_deterministically(self):
        first = FakeOcr().read_receipt(b"any bytes")
        second = FakeOcr().read_receipt(b"different bytes")
        assert first == second
        assert first.merchant == "Nasi Kandar Pelita"
        assert first.amount == Money(1890)
        assert first.confidence == 94
        assert isinstance(first.occurred_on, date)


class TestFakeVoice:
    def test_returns_the_demo_transcript(self):
        read = FakeVoice().transcribe(b"audio")
        assert read.amount == Money(1400)
        assert read.confidence == 71
        assert "fourteen" in read.transcript.lower()


class TestFakeMaps:
    def test_returns_the_curated_kl_set(self):
        places = FakeMaps().places_near(3.1577, 101.7120, 3.0)
        assert len(places) == 8
        assert places[0].name == "Nasi Kandar Pelita"
        assert places[0].estimate == Money(1250)
        assert {p.confidence for p in places} <= {"high", "medium", "low"}

    def test_radius_filters(self):
        near = FakeMaps().places_near(3.1577, 101.7120, 0.5)
        assert 0 < len(near) < 8


class TestInMemoryStorage:
    def test_round_trips_bytes(self):
        storage = InMemoryStorage()
        key = storage.put("receipts/1.jpg", b"\xff\xd8\xff")
        assert storage.get(key) == b"\xff\xd8\xff"


class TestScriptedLlm:
    def test_replays_its_script_in_order(self):
        llm = ScriptedLlm(["one", "two"])
        assert llm.complete("s", []) == "one"
        assert llm.complete("s", []) == "two"
        assert llm.complete("s", []) == "two"  # the last line repeats rather than raising


class TestRegistry:
    def test_defaults_to_fakes(self):
        adapters = get_adapters()
        assert isinstance(adapters.ocr, FakeOcr)
        assert isinstance(adapters.maps, FakeMaps)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && mkdir -p tests/adapters && touch tests/adapters/__init__.py && .venv/bin/pytest tests/adapters -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.adapters'`.

- [ ] **Step 3: Write `apps/api/kira/adapters/protocols.py`**

```python
"""What Kira needs from the outside world, stated as narrowly as possible.

Every external service is reached through one of these. Nothing else in the
codebase knows a provider's name, which is what lets the whole test suite and
the offline demo run with no network at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from kira.money import Money


@dataclass(frozen=True, slots=True)
class ReceiptRead:
    merchant: str
    amount: Money
    occurred_on: date
    confidence: int  # whole percent, 0-100
    note: str


@dataclass(frozen=True, slots=True)
class VoiceRead:
    transcript: str
    merchant: str
    amount: Money
    confidence: int  # whole percent, 0-100
    note: str


@dataclass(frozen=True, slots=True)
class Place:
    id: str
    name: str
    kind: str
    lat: float
    lng: float
    estimate: Money
    confidence: str  # high | medium | low — a label, never presented as a real price
    halal: bool
    note: str


@runtime_checkable
class OcrAdapter(Protocol):
    def read_receipt(self, image: bytes) -> ReceiptRead: ...


@runtime_checkable
class VoiceAdapter(Protocol):
    def transcribe(self, audio: bytes) -> VoiceRead: ...


@runtime_checkable
class MapsAdapter(Protocol):
    def places_near(self, lat: float, lng: float, radius_km: float) -> list[Place]: ...


@runtime_checkable
class StorageAdapter(Protocol):
    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...


@runtime_checkable
class LlmAdapter(Protocol):
    def complete(self, system: str, messages: list[dict[str, str]]) -> str: ...
```

- [ ] **Step 4: Write `apps/api/kira/adapters/fakes.py`**

```python
"""Deterministic stand-ins. These are production code, not test helpers: the
offline demo mode runs on them when a venue's network fails."""

from __future__ import annotations

import math
from datetime import date

from kira.adapters.protocols import Place, ReceiptRead, VoiceRead
from kira.money import Money

DEMO_DATE = date(2026, 9, 3)

# The curated KL set the day planner uses. Estimates are labelled, never quoted
# as real menu prices — Places APIs expose a price band, not a menu.
KL_PLACES: tuple[Place, ...] = (
    Place("p1", "Nasi Kandar Pelita", "Mamak", 3.1596, 101.7181, Money(1250), "high", True,
          "Fast counter service, open late."),
    Place("p2", "Zus Coffee, Jln Ampang", "Cafe", 3.1589, 101.7145, Money(900), "high", True,
          "Coffee and a pastry, not a full meal."),
    Place("p3", "Suria KLCC food court", "Food court", 3.1577, 101.7120, Money(1800), "medium", True,
          "Widest choice, busiest at 12:30."),
    Place("p4", "Chee Meng Chicken Rice", "Chinese", 3.1571, 101.7156, Money(1600), "medium", False,
          "Small shop, queue moves quickly."),
    Place("p5", "Nasi Lemak Antarabangsa", "Malay", 3.1652, 101.7042, Money(1100), "high", True,
          "Kampung Baru institution."),
    Place("p6", "Sushi Zanmai KLCC", "Japanese", 3.1580, 101.7118, Money(4600), "low", True,
          "Menu prices aren't published online."),
    Place("p7", "Lot 10 Hutong", "Hawker hall", 3.1465, 101.7106, Money(2200), "medium", False,
          "Heritage stalls in one basement."),
    Place("p8", "Village Grocer KLCC", "Groceries", 3.1575, 101.7124, Money(3500), "low", True,
          "Cook at home instead of eating out."),
)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance. Coordinates, not money — float is correct here."""
    radius = 6371.0
    rad = math.pi / 180
    d_lat = (lat2 - lat1) * rad
    d_lng = (lng2 - lng1) * rad
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))


class FakeOcr:
    """Always reads the demo receipt, whatever bytes it is handed."""

    def read_receipt(self, image: bytes) -> ReceiptRead:
        return ReceiptRead(
            merchant="Nasi Kandar Pelita",
            amount=Money(1890),
            occurred_on=DEMO_DATE,
            confidence=94,
            note="Line item total matched, tax line ignored.",
        )


class FakeVoice:
    def transcribe(self, audio: bytes) -> VoiceRead:
        return VoiceRead(
            transcript="Grab from the office to KLCC, fourteen ringgit",
            merchant="Grab — office to KLCC",
            amount=Money(1400),
            confidence=71,
            note="Heard 'fourteen ringgit'. Amount is worth a second look.",
        )


class FakeMaps:
    def places_near(self, lat: float, lng: float, radius_km: float) -> list[Place]:
        return [
            place
            for place in KL_PLACES
            if haversine_km(lat, lng, place.lat, place.lng) <= radius_km
        ]


class InMemoryStorage:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self._blobs[key] = data
        return key

    def get(self, key: str) -> bytes:
        return self._blobs[key]


class ScriptedLlm:
    """Replays a fixed script. The last line repeats so a longer conversation
    than the script degrades gracefully instead of exploding mid-demo."""

    def __init__(self, script: list[str]) -> None:
        if not script:
            raise ValueError("ScriptedLlm needs at least one line")
        self._script = list(script)
        self._index = 0

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        line = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return line
```

- [ ] **Step 5: Write `apps/api/kira/adapters/registry.py`**

```python
"""One place that decides which implementation each adapter uses."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from kira.adapters.fakes import FakeMaps, FakeOcr, FakeVoice, InMemoryStorage, ScriptedLlm
from kira.adapters.protocols import LlmAdapter, MapsAdapter, OcrAdapter, StorageAdapter, VoiceAdapter


@dataclass(frozen=True, slots=True)
class Adapters:
    ocr: OcrAdapter
    voice: VoiceAdapter
    maps: MapsAdapter
    storage: StorageAdapter
    llm: LlmAdapter


@lru_cache
def get_adapters() -> Adapters:
    """Week 1 wires the fakes for every adapter. Real providers land in weeks
    5-7 behind these same Protocols; nothing above this function changes."""
    return Adapters(
        ocr=FakeOcr(),
        voice=FakeVoice(),
        maps=FakeMaps(),
        storage=InMemoryStorage(),
        llm=ScriptedLlm(["I can only answer from what you've confirmed."]),
    )
```

Also create `apps/api/kira/adapters/__init__.py` re-exporting `get_adapters`:

```python
from kira.adapters.registry import Adapters, get_adapters

__all__ = ["Adapters", "get_adapters"]
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/adapters -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/kira/adapters apps/api/tests/adapters
git commit -m "feat: add adapter protocols with deterministic fakes"
```

---

## Task 8: The demo seed

**Files:**
- Create: `apps/api/kira/seed/__init__.py`, `apps/api/kira/seed/demo.py`, `apps/api/kira/seed/__main__.py`
- Test: `apps/api/tests/test_seed.py`

**Interfaces:**
- Consumes: `kira.db.models`, `kira.money.Money`, `kira.services.auth.hash_password`.
- Produces: `kira.seed.demo.seed_demo_user(session) -> User`, `DEMO_EMAIL = "demo@kira.app"`, `DEMO_PASSWORD = "demo-money-butler"`, and `python -m kira.seed` as a CLI.

The figures come straight from the prototype, so the seeded app shows the numbers the design was drawn around: balance RM4,180.40, buffer RM800, five commitments totalling RM2,003.00, two goals reserving RM212.00 this cycle, giving RM52.97 safe to spend.

- [ ] **Step 1: Write the failing test at `apps/api/tests/test_seed.py`**

```python
from datetime import date

import sqlalchemy as sa

from kira.db.models import TXN_DRAFT, Account, Commitment, Goal, Transaction, User
from kira.money import Money
from kira.seed.demo import DEMO_EMAIL, seed_demo_user


class TestSeed:
    async def test_creates_the_demo_user_and_their_picture(self, session):
        user = await seed_demo_user(session)
        assert user.email == DEMO_EMAIL
        assert user.display_name == "Floyd"
        assert user.buffer == Money(80000)
        assert user.next_payday == date(2026, 9, 25)
        assert user.cycle_start == date(2026, 8, 26)
        assert user.cycle_days == 30

    async def test_seeds_the_prototype_figures(self, session):
        await seed_demo_user(session)
        balance = (await session.execute(sa.select(sa.func.sum(Account.opening_balance)))).scalar_one()
        assert balance == 418040
        commitments = (await session.execute(sa.select(Commitment))).scalars().all()
        assert sum(c.amount.sen for c in commitments) == 200300
        assert {c.name for c in commitments} == {
            "Rent", "Phone bill", "Car loan minimum", "Streaming bundle", "Home internet"
        }
        goals = (await session.execute(sa.select(Goal))).scalars().all()
        assert {g.name for g in goals} == {"Emergency top-up", "Wedding"}
        assert sum(g.monthly.sen for g in goals) == 79500

    async def test_seeds_two_waiting_drafts_and_no_confirmed_spend(self, session):
        await seed_demo_user(session)
        txns = (await session.execute(sa.select(Transaction))).scalars().all()
        assert len(txns) == 2
        assert all(t.status == TXN_DRAFT for t in txns)

    async def test_is_idempotent(self, session):
        first = await seed_demo_user(session)
        second = await seed_demo_user(session)
        assert first.id == second.id
        assert (await session.execute(sa.select(sa.func.count()).select_from(User))).scalar_one() == 1
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(Commitment))
        ).scalar_one() == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/test_seed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.seed'`.

- [ ] **Step 3: Write `apps/api/kira/seed/demo.py`**

```python
"""The demo user. Maintained from week one so the competition demo is never
assembled the night before.

Every figure here matches the design prototype, which means the running app
shows the numbers the screens were drawn around.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    HORIZON_LONG,
    HORIZON_SHORT,
    SOURCE_RECEIPT,
    SOURCE_VOICE,
    TXN_DRAFT,
    Account,
    Commitment,
    Goal,
    Transaction,
    User,
)
from kira.money import Money
from kira.services.auth import hash_password

DEMO_EMAIL = "demo@kira.app"
DEMO_PASSWORD = "demo-money-butler"
DEMO_TODAY = date(2026, 9, 3)
DEMO_PAYDAY = date(2026, 9, 25)
DEMO_CYCLE_START = date(2026, 8, 26)

COMMITMENTS = (
    ("Rent", 120000, date(2026, 9, 5), True),
    ("Phone bill", 8900, date(2026, 9, 8), False),
    ("Car loan minimum", 52000, date(2026, 9, 10), True),
    ("Streaming bundle", 5500, date(2026, 9, 14), False),
    ("Home internet", 13900, date(2026, 9, 18), False),
)

GOALS = (
    ("Emergency top-up", HORIZON_SHORT, 250000, 115000, 27000,
     "Three weeks of expenses, kept separate from the buffer."),
    ("Wedding", HORIZON_LONG, 800000, 329000, 52500,
     "Deposit and banquet, split with Aida."),
)

DRAFTS = (
    ("Nasi Kandar Pelita", 1890, "Food", SOURCE_RECEIPT, 94,
     "Line item total matched, tax line ignored."),
    ("Grab — office to KLCC", 1400, "Transport", SOURCE_VOICE, 71,
     "Heard 'fourteen ringgit'. Amount is worth a second look."),
)


async def seed_demo_user(session: AsyncSession) -> User:
    """Create the demo user, replacing any financial data they already have."""
    user = (
        await session.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name="Floyd",
            currency="MYR",
            buffer=Money(80000),
            next_payday=DEMO_PAYDAY,
            cycle_start=DEMO_CYCLE_START,
            cycle_days=30,
        )
        session.add(user)
        await session.flush()
    else:
        for model in (Transaction, Goal, Commitment, Account):
            await session.execute(delete(model).where(model.user_id == user.id))

    session.add(Account(user_id=user.id, name="Maybank current", kind="bank",
                        opening_balance=Money(418040)))

    for name, sen, due, protected in COMMITMENTS:
        session.add(Commitment(user_id=user.id, name=name, amount=Money(sen),
                               due_date=due, protected=protected))

    for name, horizon, target, saved, monthly, note in GOALS:
        session.add(Goal(user_id=user.id, name=name, horizon=horizon, target=Money(target),
                         saved=Money(saved), monthly=Money(monthly), note=note))

    # Drafts, deliberately unconfirmed: they are visible in Activity and are
    # invisible to every number on Today until the user confirms them.
    for merchant, sen, category, source, confidence, note in DRAFTS:
        session.add(Transaction(user_id=user.id, merchant=merchant, amount=Money(sen),
                                category=category, occurred_on=DEMO_TODAY, status=TXN_DRAFT,
                                source=source, confidence=confidence, note=note))

    await session.flush()
    return user
```

- [ ] **Step 4: Write `apps/api/kira/seed/__init__.py`**

```python
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user

__all__ = ["DEMO_EMAIL", "DEMO_PASSWORD", "seed_demo_user"]
```

- [ ] **Step 5: Write `apps/api/kira/seed/__main__.py`**

```python
"""python -m kira.seed — load the demo user into the configured database."""

from __future__ import annotations

import asyncio

from kira.db.session import get_sessionmaker
from kira.seed.demo import DEMO_EMAIL, seed_demo_user


async def main() -> None:
    async with get_sessionmaker()() as session:
        await seed_demo_user(session)
        await session.commit()
    print(f"Seeded {DEMO_EMAIL}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/test_seed.py -q`
Expected: PASS.

- [ ] **Step 7: Seed the real database and check it**

```bash
cd apps/api && DATABASE_URL=postgresql+asyncpg://kira:kira@localhost:5432/kira .venv/bin/python -m kira.seed
```

Expected: prints `Seeded demo@kira.app`. Verify: `docker compose exec db psql -U kira -d kira -c 'SELECT name, amount FROM commitments ORDER BY due_date;'` shows five rows summing to 200300.

- [ ] **Step 8: Commit**

```bash
git add apps/api/kira/seed apps/api/tests/test_seed.py
git commit -m "feat: add versioned demo seed matching the prototype figures"
```

---

## Task 9: The Today dashboard endpoint

**Files:**
- Create: `apps/api/kira/engine/goals.py`, `apps/api/kira/services/snapshot.py`, `apps/api/kira/services/dashboard.py`, `apps/api/kira/api/routers/dashboard.py`
- Modify: `apps/api/kira/engine/__init__.py` (export `months_to_goal`), `apps/api/kira/api/schemas.py` (add the dashboard models), `apps/api/kira/api/app.py` (include the router)
- Test: `apps/api/tests/engine/test_goals.py`, `apps/api/tests/services/__init__.py`, `apps/api/tests/services/test_snapshot.py`, `apps/api/tests/api/test_dashboard.py`

**Interfaces:**
- Consumes: `kira.engine.safe_to_spend`, `kira.db.models`, `kira.api.deps.CurrentUser`, `kira.services.clock.today_for`.
- Produces:
  - `kira.engine.goals.months_to_goal(target: Money, saved: Money, monthly: Money) -> int`
  - `kira.services.snapshot.load_snapshot(session, user, today: date) -> Snapshot`
  - `kira.services.dashboard.today_dashboard(session, user, today: date) -> DashboardToday`
  - `GET /v1/dashboard/today` returning the `DashboardToday` schema below.

- [ ] **Step 1: Write the failing test at `apps/api/tests/engine/test_goals.py`**

```python
import pytest

from kira.engine import months_to_goal
from kira.money import Money


class TestMonthsToGoal:
    def test_rounds_up_to_the_next_whole_month(self):
        assert months_to_goal(Money(250000), Money(115000), Money(27000)) == 5

    def test_a_goal_already_met_still_reports_one_month(self):
        assert months_to_goal(Money(100), Money(500), Money(1000)) == 1

    def test_exact_division_is_not_rounded_up(self):
        assert months_to_goal(Money(30000), Money(0), Money(10000)) == 3

    def test_zero_contribution_is_rejected(self):
        with pytest.raises(ValueError):
            months_to_goal(Money(100), Money(0), Money(0))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_goals.py -q`
Expected: FAIL — `ImportError: cannot import name 'months_to_goal'`.

- [ ] **Step 3: Write `apps/api/kira/engine/goals.py`**

```python
"""Goal projections. Pure, like everything else in this package."""

from __future__ import annotations

from kira.money import Money


def months_to_goal(target: Money, saved: Money, monthly: Money) -> int:
    """Whole months until a goal is funded, rounding any part-month up.

    A part-month is a whole month to the person saving, so ceiling division is
    the honest answer. At least one month is always reported.
    """
    if monthly.sen <= 0:
        raise ValueError("monthly contribution must be positive")
    remaining = (target - saved).sen
    if remaining <= 0:
        return 1
    return max(1, -(-remaining // monthly.sen))
```

Then add to `apps/api/kira/engine/__init__.py`:

```python
from kira.engine.goals import months_to_goal
```

and add `"months_to_goal"` to `__all__`.

- [ ] **Step 4: Run the goals test**

Run: `cd apps/api && .venv/bin/pytest tests/engine -q`
Expected: PASS — including the purity gates, which now also scan `goals.py`.

- [ ] **Step 5: Write the draft-invariant test at `apps/api/tests/services/test_snapshot.py`**

```python
from datetime import date

from kira.db.models import TXN_CONFIRMED, TXN_DRAFT, Transaction
from kira.engine import safe_to_spend
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.snapshot import load_snapshot


async def snapshot_for(session):
    user = await seed_demo_user(session)
    return user, await load_snapshot(session, user, DEMO_TODAY)


class TestLoadSnapshot:
    async def test_reads_the_seeded_picture(self, session):
        _, snapshot = await snapshot_for(session)
        assert snapshot.balance == Money(418040)
        assert snapshot.buffer == Money(80000)
        assert len(snapshot.commitments) == 5
        assert len(snapshot.goals) == 2
        assert snapshot.today == DEMO_TODAY
        assert snapshot.next_payday == date(2026, 9, 25)

    async def test_produces_the_golden_baseline(self, session):
        _, snapshot = await snapshot_for(session)
        result = safe_to_spend(snapshot)
        assert result.safe_today == Money(5297)


class TestDraftInvariant:
    async def test_a_draft_changes_nothing(self, session):
        user, before = await snapshot_for(session)
        session.add(
            Transaction(
                user_id=user.id, merchant="Big draft", amount=Money(50000),
                category="Food", occurred_on=DEMO_TODAY, status=TXN_DRAFT, source="manual",
            )
        )
        await session.flush()
        after = await load_snapshot(session, user, DEMO_TODAY)
        assert after.balance == before.balance
        assert after.spent_today == before.spent_today
        assert safe_to_spend(after) == safe_to_spend(before)

    async def test_confirming_moves_both_balance_and_spent_today(self, session):
        user, before = await snapshot_for(session)
        session.add(
            Transaction(
                user_id=user.id, merchant="Nasi Kandar Pelita", amount=Money(1890),
                category="Food", occurred_on=DEMO_TODAY, status=TXN_CONFIRMED, source="receipt",
            )
        )
        await session.flush()
        after = await load_snapshot(session, user, DEMO_TODAY)
        assert after.balance == before.balance - Money(1890)
        assert after.spent_today == Money(1890)
        # This is the receipt_confirmed golden case.
        assert safe_to_spend(after).safe_today == Money(3321)

    async def test_a_confirmed_transaction_on_another_day_is_not_spent_today(self, session):
        user, _ = await snapshot_for(session)
        session.add(
            Transaction(
                user_id=user.id, merchant="Yesterday's groceries", amount=Money(6215),
                category="Groceries", occurred_on=date(2026, 9, 2), status=TXN_CONFIRMED,
                source="manual",
            )
        )
        await session.flush()
        after = await load_snapshot(session, user, DEMO_TODAY)
        assert after.spent_today == Money.zero()
        assert after.balance == Money(418040) - Money(6215)
```

- [ ] **Step 6: Write `apps/api/kira/services/snapshot.py`**

```python
"""Turns database rows into the engine's Snapshot.

This is the only place that decides what counts. The draft invariant lives in
the ``status == TXN_CONFIRMED`` filter below and nowhere else — there is no
second query that could forget it.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import TXN_CONFIRMED, Account, Commitment, Goal, Transaction, User
from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import Money


async def load_snapshot(session: AsyncSession, user: User, today: date) -> Snapshot:
    currency = user.currency

    accounts = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalars().all()
    opening = Money.sum((a.opening_balance for a in accounts), currency)

    confirmed = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.status == TXN_CONFIRMED,
            )
        )
    ).scalars().all()

    spent_all_time = Money.sum((t.amount for t in confirmed), currency)
    spent_today = Money.sum(
        (t.amount for t in confirmed if t.occurred_on == today), currency
    )

    commitments = (
        await session.execute(select(Commitment).where(Commitment.user_id == user.id))
    ).scalars().all()
    goals = (
        await session.execute(select(Goal).where(Goal.user_id == user.id))
    ).scalars().all()

    return Snapshot(
        balance=opening - spent_all_time,
        buffer=user.buffer,
        spent_today=spent_today,
        commitments=tuple(
            CommitmentInput(str(c.id), c.amount, c.due_date) for c in commitments
        ),
        goals=tuple(GoalInput(str(g.id), g.monthly) for g in goals),
        today=today,
        next_payday=user.next_payday,
        cycle_start=user.cycle_start,
        cycle_days=user.cycle_days,
    )
```

- [ ] **Step 7: Run the snapshot tests**

Run: `cd apps/api && mkdir -p tests/services && touch tests/services/__init__.py && .venv/bin/pytest tests/services -q`
Expected: PASS.

- [ ] **Step 8: Write the endpoint test at `apps/api/tests/api/test_dashboard.py`**

```python
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


async def demo_token(client, session) -> str:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


class TestDashboardAuth:
    async def test_requires_a_token(self, client):
        assert (await client.get("/v1/dashboard/today")).status_code == 401


class TestDashboardToday:
    async def test_returns_the_seeded_numbers(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["currency"] == "MYR"
        assert body["display_name"] == "Floyd"
        assert body["balance_sen"] == 418040
        assert body["reserved_sen"] == 200300
        assert body["buffer_sen"] == 80000
        assert body["goal_reserve_sen"] == 21200
        assert body["unclaimed_sen"] == 116540
        assert body["per_day_sen"] == 5297
        assert body["spent_today_sen"] == 0
        assert body["safe_today_sen"] == 5297
        assert body["days_to_payday"] == 22

    async def test_lists_the_next_commitment(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"})
        ).json()
        assert body["next_commitment"]["name"] == "Rent"
        assert body["next_commitment"]["amount_sen"] == 120000
        assert body["next_commitment"]["due_date"] == "2026-09-05"
        assert body["next_commitment"]["days_until"] == 2
        assert body["next_commitment"]["protected"] is True
        assert body["commitment_count"] == 5

    async def test_reports_goals_with_their_projection(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"})
        ).json()
        goals = {g["name"]: g for g in body["goals"]}
        assert goals["Emergency top-up"]["target_sen"] == 250000
        assert goals["Emergency top-up"]["saved_sen"] == 115000
        assert goals["Emergency top-up"]["months_left"] == 5
        assert goals["Wedding"]["horizon"] == "long"

    async def test_counts_waiting_drafts_without_counting_their_money(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"})
        ).json()
        assert body["drafts_waiting"] == 2
        assert body["safe_today_sen"] == 5297  # unchanged by the two drafts

    async def test_never_leaks_a_float(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"}
        )
        def assert_no_floats(node):
            if isinstance(node, float):
                raise AssertionError(f"float in the response: {node}")
            if isinstance(node, dict):
                for value in node.values():
                    assert_no_floats(value)
            if isinstance(node, list):
                for value in node:
                    assert_no_floats(value)
        assert_no_floats(response.json())
```

- [ ] **Step 9: Add the dashboard schemas to `apps/api/kira/api/schemas.py`**

```python
class NextCommitmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    amount_sen: int
    due_date: date
    days_until: int
    protected: bool


class GoalSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    horizon: str
    target_sen: int
    saved_sen: int
    monthly_sen: int
    months_left: int
    note: str


class DashboardTodayResponse(BaseModel):
    date: date
    display_name: str
    currency: str
    balance_sen: int
    reserved_sen: int
    buffer_sen: int
    goal_reserve_sen: int
    unclaimed_sen: int
    per_day_sen: int
    spent_today_sen: int
    safe_today_sen: int
    days_to_payday: int
    cycle_elapsed: int
    commitment_count: int
    drafts_waiting: int
    next_commitment: NextCommitmentResponse | None
    goals: list[GoalSummaryResponse]
```

- [ ] **Step 10: Write `apps/api/kira/services/dashboard.py`**

```python
"""Assembles everything the Today screen shows, in one round trip."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.api.schemas import (
    DashboardTodayResponse,
    GoalSummaryResponse,
    NextCommitmentResponse,
)
from kira.db.models import TXN_DRAFT, Commitment, Goal, Transaction, User
from kira.engine import months_to_goal, safe_to_spend
from kira.services.snapshot import load_snapshot


async def today_dashboard(
    session: AsyncSession, user: User, today: date
) -> DashboardTodayResponse:
    snapshot = await load_snapshot(session, user, today)
    result = safe_to_spend(snapshot)

    drafts_waiting = (
        await session.execute(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_DRAFT)
        )
    ).scalar_one()

    commitments = (
        await session.execute(
            select(Commitment)
            .where(Commitment.user_id == user.id)
            .order_by(Commitment.due_date)
        )
    ).scalars().all()

    upcoming = next((c for c in commitments if c.due_date >= today), None)
    next_commitment = (
        NextCommitmentResponse(
            id=upcoming.id,
            name=upcoming.name,
            amount_sen=upcoming.amount.sen,
            due_date=upcoming.due_date,
            days_until=(upcoming.due_date - today).days,
            protected=upcoming.protected,
        )
        if upcoming
        else None
    )

    goals = (
        await session.execute(select(Goal).where(Goal.user_id == user.id).order_by(Goal.name))
    ).scalars().all()

    return DashboardTodayResponse(
        date=today,
        display_name=user.display_name,
        currency=user.currency,
        balance_sen=result.balance.sen,
        reserved_sen=result.reserved.sen,
        buffer_sen=result.buffer.sen,
        goal_reserve_sen=result.goal_reserve.sen,
        unclaimed_sen=result.unclaimed.sen,
        per_day_sen=result.per_day.sen,
        spent_today_sen=result.spent_today.sen,
        safe_today_sen=result.safe_today.sen,
        days_to_payday=result.days_to_payday,
        cycle_elapsed=result.cycle_elapsed,
        commitment_count=len(commitments),
        drafts_waiting=drafts_waiting,
        next_commitment=next_commitment,
        goals=[
            GoalSummaryResponse(
                id=g.id,
                name=g.name,
                horizon=g.horizon,
                target_sen=g.target.sen,
                saved_sen=g.saved.sen,
                monthly_sen=g.monthly.sen,
                months_left=months_to_goal(g.target, g.saved, g.monthly),
                note=g.note,
            )
            for g in goals
        ],
    )
```

- [ ] **Step 11: Write `apps/api/kira/api/routers/dashboard.py`**

```python
"""One read endpoint. No arithmetic happens here."""

from __future__ import annotations

from fastapi import APIRouter

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import DashboardTodayResponse
from kira.services.clock import today_for
from kira.services.dashboard import today_dashboard

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


@router.get("/today", response_model=DashboardTodayResponse)
async def get_today(user: CurrentUser, session: SessionDep) -> DashboardTodayResponse:
    return await today_dashboard(session, user, today_for())
```

Register it in `apps/api/kira/api/app.py`: add `from kira.api.routers import auth, dashboard` and `app.include_router(dashboard.router)`.

- [ ] **Step 12: Run the whole suite**

```bash
cd apps/api && DEMO_TODAY=2026-09-03 .venv/bin/pytest -q && .venv/bin/lint-imports
```

Expected: everything green, "Contracts: 2 kept, 0 broken."

The dashboard tests depend on `DEMO_TODAY=2026-09-03`; make that automatic by adding to the top of `apps/api/tests/conftest.py`, before any `kira` import:

```python
import os

os.environ.setdefault("DEMO_TODAY", "2026-09-03")
os.environ.setdefault("JWT_SECRET", "test-secret")
```

- [ ] **Step 13: See it end to end**

```bash
cd apps/api && DATABASE_URL=postgresql+asyncpg://kira:kira@localhost:5432/kira DEMO_TODAY=2026-09-03 .venv/bin/uvicorn kira.api.app:app --port 8000
```

In another terminal:

```bash
TOKEN=$(curl -s localhost:8000/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"demo@kira.app","password":"demo-money-butler"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/v1/dashboard/today -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `"safe_today_sen": 5297` and `"drafts_waiting": 2`.

- [ ] **Step 14: Commit**

```bash
git add apps/api/kira apps/api/tests
git commit -m "feat: add GET /v1/dashboard/today backed by the pure engine"
```

---

## Task 10: Generated TypeScript contracts

**Files:**
- Create: `scripts/gen-contracts.sh`, `packages/contracts/package.json`, `packages/contracts/index.d.ts`
- Generated (never hand-edited): `packages/contracts/src/schema.d.ts`

**Interfaces:**
- Consumes: the live OpenAPI schema at `/v1/openapi.json`.
- Produces: `@kira/contracts` exporting `components["schemas"]["DashboardTodayResponse"]` and friends, plus the convenience aliases `DashboardToday`, `GoalSummary`, `NextCommitment`, `TokenResponse`, `UserResponse`.

- [ ] **Step 1: Write `scripts/gen-contracts.sh`**

Generation runs against the app's schema dumped in-process, so it needs no running server and no database.

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/packages/contracts/src/schema.d.ts"

cd "$ROOT/apps/api"
.venv/bin/python -c '
import json
from kira.api.app import create_app
print(json.dumps(create_app().openapi()))
' > openapi.json

cd "$ROOT"
npx --yes openapi-typescript@7 "$ROOT/apps/api/openapi.json" -o "$OUT"
echo "wrote $OUT"
```

Then `chmod +x scripts/gen-contracts.sh`.

- [ ] **Step 2: Write `packages/contracts/package.json`**

```json
{
  "name": "@kira/contracts",
  "version": "0.1.0",
  "private": true,
  "types": "index.d.ts"
}
```

- [ ] **Step 3: Write `packages/contracts/index.d.ts`**

```typescript
import type { components } from "./src/schema";

export type Schemas = components["schemas"];
export type DashboardToday = Schemas["DashboardTodayResponse"];
export type GoalSummary = Schemas["GoalSummaryResponse"];
export type NextCommitment = Schemas["NextCommitmentResponse"];
export type TokenResponse = Schemas["TokenResponse"];
export type UserResponse = Schemas["UserResponse"];
export type { components, paths } from "./src/schema";
```

- [ ] **Step 4: Generate and inspect**

Run: `bash scripts/gen-contracts.sh`
Expected: writes `packages/contracts/src/schema.d.ts`. Verify the money fields survived as numbers:

```bash
grep -A2 'safe_today_sen' packages/contracts/src/schema.d.ts
```

Expected: `safe_today_sen: number;`.

- [ ] **Step 5: Commit**

```bash
git add scripts/gen-contracts.sh packages/contracts
git commit -m "build: generate TypeScript contracts from the OpenAPI schema"
```

---

## Task 11: Web app scaffold, design system, API client

**Files:**
- Create: `apps/web/package.json`, `apps/web/vite.config.ts`, `apps/web/tsconfig.json`, `apps/web/tsconfig.node.json`, `apps/web/index.html`, `apps/web/src/main.tsx`, `apps/web/src/vite-env.d.ts`
- Create: `apps/web/src/styles/kira.css`, `apps/web/src/lib/money.ts`, `apps/web/src/lib/queryClient.ts`, `apps/web/src/api/client.ts`, `apps/web/src/api/hooks.ts`
- Test: `apps/web/src/lib/money.test.ts`

**Interfaces:**
- Consumes: `@kira/contracts`, the API at `/v1`.
- Produces:
  - `fmt(sen: number): string` — the prototype's formatter, `418040 → "4,180.40"`.
  - `api.get<T>(path)`, `api.post<T>(path, body)`, `api.setAccessToken(token)`, `api.clearAccessToken()` from `src/api/client.ts`.
  - `useDashboardToday()` — a TanStack Query hook returning `DashboardToday`.
  - `useLogin()` — a mutation posting to `/v1/auth/login` and storing the access token.

- [ ] **Step 1: Write `apps/web/package.json`**

```json
{
  "name": "@kira/web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc -b --noEmit",
    "test": "vitest run"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.62.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@kira/contracts": "*",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.1",
    "typescript": "^5.7.2",
    "vite": "^6.0.0",
    "vitest": "^2.1.8"
  }
}
```

Install from the repo root: `npm install`.

- [ ] **Step 2: Write `apps/web/vite.config.ts`**

```typescript
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Development is split: Vite serves the UI with HMR and forwards the API to
// uvicorn. Production is unified — one container serves both from one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
```

And `apps/web/src/test-setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 3: Write `apps/web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUncheckedIndexedAccess": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vite/client", "vitest/globals"]
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Write `apps/web/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="theme-color" content="#0F1C1A" />
    <title>Kira — AI money butler</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Extract the design system into `apps/web/src/styles/kira.css`**

The prototype holds its stylesheet in a template literal. Lift it verbatim — this is a move, not a rewrite:

```bash
sed -n '11,562p' kira-prototype.jsx > apps/web/src/styles/kira.css
```

That range is the body of the `STYLES` template string: line 10 is `const STYLES = \`` and line 563 is the closing backtick. Open the result and check the first line is the `@import url('https://fonts.googleapis.com/...')` and the last is the closing `}` of the responsive media query. Do not reformat, rename, or "tidy" any of it — the animation timings are the design.

Then append the two rules the prototype got for free from being a single file:

```css
/* --- app shell: the prototype rendered inside a page; this is the page --- */
html, body, #root { height: 100%; margin: 0; }
body { background: #E7EAE5; }
```

- [ ] **Step 6: Write the failing test at `apps/web/src/lib/money.test.ts`**

```typescript
import { describe, expect, it } from "vitest";

import { fmt } from "./money";

describe("fmt", () => {
  it("formats sen as grouped ringgit", () => {
    expect(fmt(418040)).toBe("4,180.40");
  });

  it("always shows two decimals", () => {
    expect(fmt(5)).toBe("0.05");
    expect(fmt(100)).toBe("1.00");
  });

  it("formats the demo safe-to-spend", () => {
    expect(fmt(5297)).toBe("52.97");
  });

  it("handles zero", () => {
    expect(fmt(0)).toBe("0.00");
  });

  it("handles negatives", () => {
    expect(fmt(-1890)).toBe("-18.90");
  });
});
```

- [ ] **Step 7: Run it and watch it fail**

Run: `cd apps/web && npx vitest run src/lib/money.test.ts`
Expected: FAIL — cannot resolve `./money`.

- [ ] **Step 8: Write `apps/web/src/lib/money.ts`**

```typescript
/**
 * Money crosses the wire as an integer count of sen and stays that way in
 * memory. This function is the only place it becomes a display string, and it
 * is the prototype's formatter unchanged.
 */
export function fmt(sen: number): string {
  return (sen / 100).toLocaleString("en-MY", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
```

- [ ] **Step 9: Run the test again**

Run: `cd apps/web && npx vitest run src/lib/money.test.ts`
Expected: PASS.

- [ ] **Step 10: Write `apps/web/src/api/client.ts`**

```typescript
/**
 * The access token lives in memory only — never in localStorage, where any
 * injected script could read it. Durability comes from the httpOnly refresh
 * cookie, which JavaScript cannot touch: a page reload silently re-authenticates.
 */

let accessToken: string | null = null;

export function setAccessToken(token: string): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function raw(path: string, init: RequestInit): Promise<Response> {
  return fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "content-type": "application/json",
      ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
      ...(init.headers ?? {}),
    },
  });
}

async function refresh(): Promise<boolean> {
  const response = await fetch("/v1/auth/refresh", {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    clearAccessToken();
    return false;
  }
  const body = (await response.json()) as { access_token: string };
  setAccessToken(body.access_token);
  return true;
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response = await raw(path, init);

  // One silent retry: an expired access token should never reach the user.
  if (response.status === 401 && !path.startsWith("/v1/auth/")) {
    if (await refresh()) {
      response = await raw(path, init);
    }
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail || response.statusText);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  setAccessToken,
  clearAccessToken,
  hasAccessToken,
};
```

- [ ] **Step 11: Write `apps/web/src/lib/queryClient.ts`**

```typescript
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Financial figures are cheap to fetch and expensive to be wrong about.
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});
```

- [ ] **Step 12: Write `apps/web/src/api/hooks.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { DashboardToday, TokenResponse } from "@kira/contracts";

import { api } from "./client";

export const dashboardTodayKey = ["dashboard", "today"] as const;

export function useDashboardToday(enabled: boolean) {
  return useQuery({
    queryKey: dashboardTodayKey,
    queryFn: () => api.get<DashboardToday>("/v1/dashboard/today"),
    enabled,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api.post<TokenResponse>("/v1/auth/login", credentials),
    onSuccess: (token) => {
      api.setAccessToken(token.access_token);
      void queryClient.invalidateQueries({ queryKey: dashboardTodayKey });
    },
  });
}
```

- [ ] **Step 13: Write `apps/web/src/main.tsx`**

```typescript
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { queryClient } from "./lib/queryClient";
import "./styles/kira.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
```

Rename it `main.tsx` (JSX inside), and add `apps/web/src/vite-env.d.ts`:

```typescript
/// <reference types="vite/client" />
```

- [ ] **Step 14: Commit**

```bash
git add apps/web package-lock.json package.json
git commit -m "feat: scaffold web app with design system, API client, and query setup"
```

---

## Task 12: The app shell — device frame, boot, navigation

**Files:**
- Create: `apps/web/src/App.tsx`, `apps/web/src/components/Icons.tsx`, `apps/web/src/components/Motes.tsx`, `apps/web/src/components/NavItem.tsx`, `apps/web/src/components/Reveal.tsx`, `apps/web/src/screens/Login.tsx`, `apps/web/src/screens/Placeholder.tsx`
- Test: `apps/web/src/App.test.tsx`

**Interfaces:**
- Consumes: `api`, `useLogin`, `fmt`, the CSS classes from `kira.css`.
- Produces:
  - `App` — the device frame, boot sequence, scroll-parallax wiring, five-tab nav, and the login gate.
  - `Tab = "today" | "activity" | "butler" | "plan" | "more"`, exported from `App.tsx`.
  - `ScrollContext` — a `React.Context<React.RefObject<HTMLDivElement | null> | null>` exported from `components/Reveal.tsx`, used by `Reveal` and by any screen needing the scroll container.
  - `NavItem({ id, tab, go, Icon, label, active })`.
  - `Placeholder({ title, blurb })` — the stub each unbuilt tab renders in week 1.

**Porting rule:** every component below is the prototype's component with types added and its data source changed. Copy the JSX and the `className` strings exactly. If a class name in your port does not appear in `kira.css`, you mistyped it.

- [ ] **Step 1: Write the failing test at `apps/web/src/App.test.tsx`**

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const DASHBOARD = {
  date: "2026-09-03",
  display_name: "Floyd",
  currency: "MYR",
  balance_sen: 418040,
  reserved_sen: 200300,
  buffer_sen: 80000,
  goal_reserve_sen: 21200,
  unclaimed_sen: 116540,
  per_day_sen: 5297,
  spent_today_sen: 0,
  safe_today_sen: 5297,
  days_to_payday: 22,
  cycle_elapsed: 8,
  commitment_count: 5,
  drafts_waiting: 2,
  next_commitment: {
    id: "c1",
    name: "Rent",
    amount_sen: 120000,
    due_date: "2026-09-05",
    days_until: 2,
    protected: true,
  },
  goals: [
    {
      id: "g1",
      name: "Emergency top-up",
      horizon: "short",
      target_sen: 250000,
      saved_sen: 115000,
      monthly_sen: 27000,
      months_left: 5,
      note: "Three weeks of expenses.",
    },
  ],
};

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/auth/refresh")) {
        return new Response("", { status: 401 });
      }
      if (url.endsWith("/v1/auth/login")) {
        return new Response(JSON.stringify({ access_token: "t", token_type: "bearer" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/dashboard/today")) {
        return new Response(JSON.stringify(DASHBOARD), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response("", { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("App", () => {
  it("shows the login gate before authentication", async () => {
    renderApp();
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("renders the five navigation tabs once signed in", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));

    for (const label of ["Today", "Activity", "Butler", "Plan", "More"]) {
      expect(await screen.findByRole("button", { name: new RegExp(label, "i") })).toBeInTheDocument();
    }
  });

  it("switches tabs without losing the shell", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Plan$/i }));

    await waitFor(() => expect(screen.getByText(/Coming in week/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^Today$/i })).toBeInTheDocument();
  });
});
```

Add `@testing-library/user-event` to `apps/web` devDependencies and re-run `npm install`.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && npx vitest run src/App.test.tsx`
Expected: FAIL — cannot resolve `./App`.

- [ ] **Step 3: Write `apps/web/src/components/Icons.tsx`**

Port the prototype's icon set (`kira-prototype.jsx` lines 678-700) with types. The paths are copied verbatim:

```typescript
import type { ReactNode } from "react";

type IconProps = { size?: number; w?: number };

function Svg({ d, size = 20, w = 1.6 }: IconProps & { d: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={w}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {d}
    </svg>
  );
}

export const IcToday = (p: IconProps) => (
  <Svg {...p} d={<><path d="M4 13.5 12 6l8 7.5" /><path d="M6.5 12v6.5h11V12" /></>} />
);
export const IcActivity = (p: IconProps) => <Svg {...p} d={<path d="M4 12h4l2.5-5 3 10 2.5-5h4" />} />;
export const IcPlan = (p: IconProps) => (
  <Svg {...p} d={<><circle cx="12" cy="12" r="7.6" /><path d="M12 7.6V12l3 2" /></>} />
);
export const IcMore = (p: IconProps) => (
  <Svg
    {...p}
    d={<>
      <circle cx="6" cy="12" r="1.1" fill="currentColor" />
      <circle cx="12" cy="12" r="1.1" fill="currentColor" />
      <circle cx="18" cy="12" r="1.1" fill="currentColor" />
    </>}
  />
);
export const IcBell = (p: IconProps) => (
  <Svg {...p} d={<><path d="M8 15V11a4 4 0 0 1 8 0v4l1.5 2.2h-11L8 15Z" /><path d="M10.6 19.4a1.7 1.7 0 0 0 2.8 0" /></>} />
);
export const IcChev = (p: IconProps) => <Svg {...p} d={<path d="m9.5 6 6 6-6 6" />} />;
export const IcLock = (p: IconProps) => (
  <Svg {...p} d={<><rect x="5.5" y="10.5" width="13" height="9" rx="2.4" /><path d="M8.6 10.5V8.4a3.4 3.4 0 0 1 6.8 0v2.1" /></>} />
);
export const IcCheck = (p: IconProps) => <Svg {...p} w={2} d={<path d="m5.5 12.5 4.2 4.2 8.8-9.4" />} />;
export const IcSpark = (p: IconProps) => (
  <Svg {...p} d={<path d="M12 4.5 13.7 10 19 12l-5.3 2-1.7 5.5L10.3 14 5 12l5.3-2Z" />} />
);
export const IcArrow = (p: IconProps) => <Svg {...p} d={<path d="M5 12h13m-5-5 5 5-5 5" />} />;
```

- [ ] **Step 4: Write `apps/web/src/components/Reveal.tsx`**

Ported from the prototype's `ScrollCtx` and `Reveal` (lines 825-850):

```typescript
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";

export const ScrollContext = createContext<RefObject<HTMLDivElement | null> | null>(null);

export function useScrollContainer() {
  return useContext(ScrollContext);
}

type RevealProps = {
  children: ReactNode;
  delay?: number;
  style?: CSSProperties;
};

/** Fades a block in as it enters the viewport, once. */
export function Reveal({ children, delay = 0, style }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);
  const container = useScrollContainer();
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || shown) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true);
          observer.disconnect();
        }
      },
      { root: container?.current ?? null, rootMargin: "0px 0px -8% 0px", threshold: 0.05 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [container, shown]);

  return (
    <div
      ref={ref}
      className={`rv ${shown ? "in" : ""}`}
      style={{ transitionDelay: `${delay}ms`, ...style }}
    >
      {children}
    </div>
  );
}
```

`IntersectionObserver` does not exist in jsdom. Add a stub to `apps/web/src/test-setup.ts` that immediately reports every observed element as visible, so tests see final rendered content:

```typescript
import "@testing-library/jest-dom/vitest";

class ImmediateIntersectionObserver {
  constructor(private readonly callback: IntersectionObserverCallback) {}
  observe(target: Element) {
    this.callback(
      [{ isIntersecting: true, target } as unknown as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

vi.stubGlobal("IntersectionObserver", ImmediateIntersectionObserver);
```

- [ ] **Step 5: Write `apps/web/src/components/Motes.tsx`**

Ported from the prototype (lines 889-912). The drift layer is decorative and deterministic:

```typescript
import { useMemo } from "react";

const COUNT = 14;

export function Motes() {
  const motes = useMemo(
    () =>
      Array.from({ length: COUNT }, (_, i) => ({
        left: `${(i * 37) % 100}%`,
        top: `${(i * 61) % 100}%`,
        size: 3 + (i % 5) * 2,
        duration: 14 + (i % 7) * 3,
        delay: -(i * 1.7),
      })),
    [],
  );

  return (
    <div className="motes" aria-hidden="true">
      {motes.map((mote, i) => (
        <i
          key={i}
          className="mote"
          style={{
            left: mote.left,
            top: mote.top,
            width: mote.size,
            height: mote.size,
            animation: `drift ${mote.duration}s linear ${mote.delay}s infinite`,
          }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Write `apps/web/src/components/NavItem.tsx`**

```typescript
import type { ComponentType } from "react";

import type { Tab } from "../App";

type NavItemProps = {
  id: Tab;
  tab: Tab;
  go: (next: Tab) => void;
  Icon: ComponentType<{ size?: number }>;
  label: string;
  active?: boolean;
};

export function NavItem({ id, tab, go, Icon, label, active }: NavItemProps) {
  const on = active ?? tab === id;
  return (
    <button className={`nav-item ${on ? "active" : ""}`} onClick={() => go(id)}>
      <Icon />
      <span>{label}</span>
      {on && <i className="nav-dot" />}
    </button>
  );
}
```

- [ ] **Step 7: Write `apps/web/src/screens/Placeholder.tsx`**

Honest stubs. Each names the week it arrives, so a demo never shows an empty screen with no explanation.

```typescript
type PlaceholderProps = { title: string; blurb: string; week: string };

export function Placeholder({ title, blurb, week }: PlaceholderProps) {
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>{title}</p>
          <h1>{title}</h1>
        </div>
      </div>
      <div className="pad">
        <section className="card">
          <p className="voice" style={{ margin: 0, fontSize: 16, lineHeight: 1.45 }}>{blurb}</p>
          <p style={{ margin: "12px 0 0", fontSize: 12.5, color: "var(--muted)" }}>
            Coming in week {week}.
          </p>
        </section>
      </div>
    </>
  );
}
```

- [ ] **Step 8: Write `apps/web/src/screens/Login.tsx`**

The demo credentials are prefilled so a rehearsal is one tap, but they are ordinary form values the user can change — the client holds no hardcoded secret.

```typescript
import { useState, type FormEvent } from "react";

import { useLogin } from "../api/hooks";
import { IcArrow } from "../components/Icons";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("demo@kira.app");
  const [password, setPassword] = useState("demo-money-butler");
  const login = useLogin();

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate({ email, password }, { onSuccess: onSignedIn });
  }

  return (
    <div className="pad" style={{ paddingTop: 80 }}>
      <p className="eyebrow" style={{ margin: 0 }}>Welcome back</p>
      <h1 style={{ marginTop: 6 }}>Sign in to Kira</h1>
      <form onSubmit={submit} style={{ marginTop: 24, display: "grid", gap: 12 }}>
        <input
          className="field"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-label="Email"
          autoComplete="username"
        />
        <input
          className="field"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-label="Password"
          autoComplete="current-password"
        />
        <button className="btn btn-primary" type="submit" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"} <IcArrow size={15} />
        </button>
        {login.isError && (
          <p style={{ margin: 0, fontSize: 13, color: "var(--clay)" }}>
            That email and password don't match.
          </p>
        )}
      </form>
    </div>
  );
}
```

The prototype has no login form, so `.field` does not exist in `kira.css`. Append it, matching the existing input styling:

```css
.field{width:100%;padding:13px 15px;border-radius:14px;border:1px solid var(--line-2);
  background:var(--surface);font-family:inherit;font-size:15px;color:var(--ink);}
.field:focus{outline:2px solid var(--brass);outline-offset:2px;}
```

- [ ] **Step 9: Write `apps/web/src/App.tsx`**

Ported from the prototype's `App` (lines 913-1168), with server state replacing `useState` and the unbuilt tabs stubbed.

```typescript
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useDashboardToday } from "./api/hooks";
import { IcActivity, IcMore, IcPlan, IcSpark, IcToday } from "./components/Icons";
import { Motes } from "./components/Motes";
import { NavItem } from "./components/NavItem";
import { ScrollContext } from "./components/Reveal";
import { Login } from "./screens/Login";
import { Placeholder } from "./screens/Placeholder";
import { Today } from "./screens/Today";

export type Tab = "today" | "activity" | "butler" | "plan" | "more";

const TABS: Tab[] = ["today", "activity", "butler", "plan", "more"];

export function App() {
  const [tab, setTab] = useState<Tab>("today");
  const [dir, setDir] = useState(0);
  const [boot, setBoot] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const viewRef = useRef<HTMLDivElement>(null);
  const screenRef = useRef<HTMLDivElement>(null);

  const dashboard = useDashboardToday(signedIn);

  useEffect(() => {
    const timer = setTimeout(() => setBoot(false), 2500);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    viewRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [tab]);

  // Scroll-linked parallax: write a CSS variable, never re-render.
  useEffect(() => {
    const view = viewRef.current;
    const screen = screenRef.current;
    if (!view || !screen) return;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        screen.style.setProperty("--sy", String(view.scrollTop));
        frame = 0;
      });
    };
    view.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      view.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, [tab]);

  const go = (next: Tab) => {
    if (next === tab) return;
    const from = TABS.indexOf(tab);
    const to = TABS.indexOf(next);
    setDir(next === "butler" || tab === "butler" ? 0 : to > from ? 1 : -1);
    setTab(next);
  };

  const dark = tab === "butler";

  return (
    <div className="kira-root">
      <div className="stage-head">
        <div className="lockup">
          <b>Kira</b>
          <span>AI money butler</span>
        </div>
      </div>

      <div className="device">
        <div
          className={`screen ${dark ? "dim" : ""}`}
          ref={screenRef}
          style={{ "--dir": dir } as CSSProperties}
        >
          <Motes />

          {boot && (
            <div className="boot">
              <div style={{ textAlign: "center" }}>
                <div className="boot-mark">
                  {"KIRA".split("").map((c, i) => (
                    <span key={i} style={{ animationDelay: `${0.07 * i}s` }}>{c}</span>
                  ))}
                </div>
                <div className="boot-rule" />
                <p className="boot-sub">AI money butler</p>
              </div>
            </div>
          )}

          <div className="statusbar">
            <span>12:47</span>
            <span style={{ display: "flex", gap: 7, alignItems: "center" }}>
              <span className="sb-dots"><i /><i /><i /><i /></span>
              <span className="sb-batt" />
            </span>
          </div>

          <ScrollContext.Provider value={viewRef}>
            <div className="viewport" ref={viewRef}>
              <div className="page" key={signedIn ? tab : "login"}>
                {!signedIn && <Login onSignedIn={() => setSignedIn(true)} />}
                {signedIn && tab === "today" && (
                  <Today
                    data={dashboard.data}
                    isLoading={dashboard.isLoading}
                    isError={dashboard.isError}
                    go={go}
                  />
                )}
                {signedIn && tab === "activity" && (
                  <Placeholder
                    title="Activity"
                    blurb="Drafts from receipts and voice notes wait here until you confirm them. Nothing enters your ledger unconfirmed."
                    week="2"
                  />
                )}
                {signedIn && tab === "butler" && (
                  <Placeholder
                    title="Butler"
                    blurb="Ask about affordability, why a number moved, or how to recover an overspend. Every answer shows its working."
                    week="7"
                  />
                )}
                {signedIn && tab === "plan" && (
                  <Placeholder
                    title="Plan"
                    blurb="Goals, scenarios, and the day planner."
                    week="3"
                  />
                )}
                {signedIn && tab === "more" && (
                  <Placeholder
                    title="More"
                    blurb="Bills, accounts, and the safety and audit trail."
                    week="2"
                  />
                )}
              </div>
            </div>
          </ScrollContext.Provider>

          {signedIn && (
            <nav className="nav">
              <NavItem id="today" tab={tab} go={go} Icon={IcToday} label="Today" />
              <NavItem id="activity" tab={tab} go={go} Icon={IcActivity} label="Activity" />
              <button
                className={`nav-butler ${tab === "butler" ? "active" : ""}`}
                onClick={() => go("butler")}
              >
                <span className="butler-orb"><IcSpark size={25} /></span>
                <span>Butler</span>
              </button>
              <NavItem id="plan" tab={tab} go={go} Icon={IcPlan} label="Plan" />
              <NavItem id="more" tab={tab} go={go} Icon={IcMore} label="More" />
            </nav>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 10: Run the shell test**

Run: `cd apps/web && npx vitest run src/App.test.tsx`
Expected: FAIL — cannot resolve `./screens/Today`, which Task 13 creates. Create a one-line stub now so the shell is testable on its own:

```typescript
// apps/web/src/screens/Today.tsx — replaced in full by Task 13.
export function Today(_: { data: unknown; isLoading: boolean; isError: boolean; go: (t: never) => void }) {
  return <div className="pad">Today</div>;
}
```

Re-run: expected PASS.

- [ ] **Step 11: Commit**

```bash
git add apps/web/src
git commit -m "feat: add app shell with device frame, boot, and five-tab navigation"
```

---

## Task 13: The Today screen

**Files:**
- Create: `apps/web/src/components/Odometer.tsx`, `apps/web/src/components/Ring.tsx`, `apps/web/src/components/ClaimLine.tsx`
- Modify: `apps/web/src/screens/Today.tsx` (replace the stub in full)
- Test: `apps/web/src/screens/Today.test.tsx`

**Interfaces:**
- Consumes: `DashboardToday` from `@kira/contracts`, `fmt`, `Reveal`, the icons.
- Produces:
  - `Odometer({ sen, size })` — the rolling-digit display.
  - `Ring({ pct, size, stroke })` — the goal progress arc; `pct` is 0-1.
  - `ClaimLine({ data, picked, onPick })` — the four-band breakdown of the balance.
  - `Today({ data, isLoading, isError, go })`.

- [ ] **Step 1: Write the failing test at `apps/web/src/screens/Today.test.tsx`**

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DashboardToday } from "@kira/contracts";

import { Today } from "./Today";

const DATA = {
  date: "2026-09-03",
  display_name: "Floyd",
  currency: "MYR",
  balance_sen: 418040,
  reserved_sen: 200300,
  buffer_sen: 80000,
  goal_reserve_sen: 21200,
  unclaimed_sen: 116540,
  per_day_sen: 5297,
  spent_today_sen: 0,
  safe_today_sen: 5297,
  days_to_payday: 22,
  cycle_elapsed: 8,
  commitment_count: 5,
  drafts_waiting: 2,
  next_commitment: {
    id: "c1",
    name: "Rent",
    amount_sen: 120000,
    due_date: "2026-09-05",
    days_until: 2,
    protected: true,
  },
  goals: [
    {
      id: "g1",
      name: "Emergency top-up",
      horizon: "short",
      target_sen: 250000,
      saved_sen: 115000,
      monthly_sen: 27000,
      months_left: 5,
      note: "Three weeks of expenses.",
    },
  ],
} as unknown as DashboardToday;

function renderToday(overrides: Partial<Parameters<typeof Today>[0]> = {}) {
  return render(
    <Today data={DATA} isLoading={false} isError={false} go={vi.fn()} {...overrides} />,
  );
}

describe("Today", () => {
  it("shows the safe-to-spend figure", () => {
    renderToday();
    // The odometer splits its value into one span per character, so the
    // accessible label is the only place the whole number appears as text.
    expect(screen.getByLabelText("RM52.97")).toBeInTheDocument();
  });

  it("greets the user by name", () => {
    renderToday();
    expect(screen.getByText(/Floyd/)).toBeInTheDocument();
  });

  it("names the next commitment with its amount and countdown", () => {
    renderToday();
    expect(screen.getByText("Rent")).toBeInTheDocument();
    expect(screen.getByText("1,200.00")).toBeInTheDocument();
    expect(screen.getByText(/in 2 days/i)).toBeInTheDocument();
  });

  it("surfaces waiting drafts and says they are not counted", () => {
    renderToday();
    expect(screen.getByText(/2 captures waiting on you/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing enters your ledger until you confirm it/i)).toBeInTheDocument();
  });

  it("shows the working on request, and it reconciles", async () => {
    renderToday();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /show the working/i }));

    expect(screen.getByText("4,180.40")).toBeInTheDocument();   // in hand
    expect(screen.getByText("−2,003.00")).toBeInTheDocument();  // bills before payday
    expect(screen.getByText("−800.00")).toBeInTheDocument();    // buffer
    expect(screen.getByText("−212.00")).toBeInTheDocument();    // goals accrued
    // Also shown in the claim legend, hence getAllByText.
    expect(screen.getAllByText("1,165.40").length).toBeGreaterThan(0); // unclaimed
    expect(screen.getByText("52.97/day")).toBeInTheDocument();
  });

  it("names the goal and its projection", () => {
    renderToday();
    expect(screen.getByText("Emergency top-up")).toBeInTheDocument();
    expect(screen.getByText("46%")).toBeInTheDocument();
  });

  it("shows a loading state rather than a wrong number", () => {
    renderToday({ data: undefined, isLoading: true });
    expect(screen.getByText(/working out your day/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("RM52.97")).not.toBeInTheDocument();
  });

  it("shows an error state rather than a stale number", () => {
    renderToday({ data: undefined, isLoading: false, isError: true });
    expect(screen.getByText(/couldn't reach your numbers/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/web && npx vitest run src/screens/Today.test.tsx`
Expected: FAIL — the stub renders only "Today".

- [ ] **Step 3: Write `apps/web/src/components/Odometer.tsx`**

Ported from the prototype (lines 851-872). Digits roll into place; the value is a plain integer sen throughout.

```typescript
import { useEffect, useState } from "react";

import { fmt } from "../lib/money";

type OdometerProps = { sen: number; size?: number; rm?: boolean };

export function Odometer({ sen, size = 52, rm = true }: OdometerProps) {
  const text = fmt(sen);
  const [shown, setShown] = useState(text);

  useEffect(() => {
    setShown(text);
  }, [text]);

  return (
    <div className="odo" style={{ fontSize: size }} aria-label={`RM${text}`}>
      {rm && <span className="odo-rm">RM</span>}
      {shown.split("").map((char, i) => (
        <span
          key={`${i}-${char}`}
          className={`odo-d ${char === "," || char === "." ? "odo-sep" : ""}`}
          style={{ animationDelay: `${i * 45}ms` }}
        >
          {char}
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Write `apps/web/src/components/Ring.tsx`**

Ported verbatim from the prototype (lines 1226-1241):

```typescript
import { useEffect, useState } from "react";

type RingProps = { pct: number; size?: number; stroke?: string };

export function Ring({ pct, size = 96, stroke = "#A9853F" }: RingProps) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  const [on, setOn] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setOn(true), 260);
    return () => clearTimeout(timer);
  }, []);

  return (
    <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(15,28,26,.09)" strokeWidth="6" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={stroke}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={on ? c - c * pct : c}
        style={{ transition: "stroke-dashoffset 1.4s cubic-bezier(.22,1,.36,1)" }}
      />
    </svg>
  );
}
```

- [ ] **Step 5: Write `apps/web/src/components/ClaimLine.tsx`**

Ported from the prototype (lines 1183-1224). Every figure now comes from the server rather than module constants:

```typescript
import type { DashboardToday } from "@kira/contracts";

import { fmt } from "../lib/money";

export type Band = "free" | "goal" | "commit" | "buffer";

const SWATCH: Record<Band, string> = {
  free: "linear-gradient(180deg,#FBF7EC,#DFCFA4)",
  goal: "linear-gradient(180deg,#E0BB74,#B58F45)",
  commit: "linear-gradient(180deg,#7FA298,#5B7C74)",
  buffer: "#43635C",
};

type ClaimLineProps = {
  data: DashboardToday;
  picked: Band | null;
  onPick: (band: Band | null) => void;
};

export function ClaimLine({ data, picked, onPick }: ClaimLineProps) {
  const goalCount = data.goals.length;
  const segments: { k: Band; v: number; cls: string; label: string; sub: string }[] = [
    {
      k: "free",
      v: data.unclaimed_sen,
      cls: "seg-free",
      label: "Unclaimed",
      sub: "Yours to decide",
    },
    {
      k: "goal",
      v: data.goal_reserve_sen,
      cls: "seg-goal",
      label: "Goal reserve",
      sub: `${goalCount} goal${goalCount === 1 ? "" : "s"}, accrued this cycle`,
    },
    {
      k: "commit",
      v: data.reserved_sen,
      cls: "seg-commit",
      label: "Committed",
      sub: `${data.commitment_count} bills before payday`,
    },
    {
      k: "buffer",
      v: data.buffer_sen,
      cls: "seg-buffer",
      label: "Buffer",
      sub: "Protected, not spendable",
    },
  ];

  return (
    <div>
      <div className="claim" role="img" aria-label="How your balance is claimed">
        {segments.map((s, i) => (
          <button
            key={s.k}
            className={`claim-seg ${s.cls}`}
            style={{
              flexGrow: Math.max(s.v, 0),
              animationDelay: `${0.35 + i * 0.09}s`,
              opacity: picked && picked !== s.k ? 0.45 : 1,
            }}
            onClick={() => onPick(picked === s.k ? null : s.k)}
            aria-label={`${s.label} RM${fmt(s.v)}`}
          />
        ))}
      </div>
      <div className="claim-legend">
        {segments.map((s) => (
          <button
            key={s.k}
            className="leg"
            onClick={() => onPick(picked === s.k ? null : s.k)}
            style={{ opacity: picked && picked !== s.k ? 0.38 : 1 }}
          >
            <i style={{ background: SWATCH[s.k] }} />
            <span>
              <span className="leg-l">{s.label}</span>
              <span className="leg-v">{fmt(s.v)}</span>
            </span>
          </button>
        ))}
      </div>
      {picked && (
        <p
          className="voice"
          style={{
            margin: "13px 0 0",
            fontSize: 13.5,
            color: "rgba(233,237,233,.7)",
            animation: "fadeUp .5s var(--spring) both",
          }}
        >
          {segments.find((s) => s.k === picked)!.sub}.
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Write `apps/web/src/screens/Today.tsx`, replacing the stub**

```typescript
import { useState } from "react";

import type { DashboardToday } from "@kira/contracts";

import type { Tab } from "../App";
import { ClaimLine, type Band } from "../components/ClaimLine";
import { IcArrow, IcBell, IcChev, IcLock } from "../components/Icons";
import { Odometer } from "../components/Odometer";
import { Reveal } from "../components/Reveal";
import { Ring } from "../components/Ring";
import { fmt } from "../lib/money";

const HORIZON_STROKE: Record<string, string> = { short: "#4E8F79", long: "#A9853F" };

const LONG_DATE = new Intl.DateTimeFormat("en-MY", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

type TodayProps = {
  data: DashboardToday | undefined;
  isLoading: boolean;
  isError: boolean;
  go: (tab: Tab) => void;
};

export function Today({ data, isLoading, isError, go }: TodayProps) {
  const [picked, setPicked] = useState<Band | null>(null);
  const [maths, setMaths] = useState(false);

  // A wrong number is worse than no number, so neither state guesses.
  if (isLoading || !data) {
    return (
      <div className="pad" style={{ paddingTop: 90 }}>
        <p className="voice" style={{ fontSize: 17 }}>
          {isError ? "I couldn't reach your numbers just now." : "Working out your day…"}
        </p>
        {isError && (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            Nothing has changed on your ledger. Pull down to try again.
          </p>
        )}
      </div>
    );
  }

  const next = data.next_commitment;
  const rows: [string, string, boolean?][] = [
    ["In hand", fmt(data.balance_sen)],
    ["Bills due before payday", `−${fmt(data.reserved_sen)}`],
    ["Emergency buffer", `−${fmt(data.buffer_sen)}`],
    ["Goals, accrued this cycle", `−${fmt(data.goal_reserve_sen)}`],
    ["Unclaimed until payday", fmt(data.unclaimed_sen), true],
    [`÷ ${data.days_to_payday} days`, `${fmt(data.per_day_sen)}/day`],
    ...(data.spent_today_sen > 0
      ? ([["Confirmed today", `−${fmt(data.spent_today_sen)}`]] as [string, string][])
      : []),
    ["Safe to spend today", fmt(data.safe_today_sen), true],
  ];

  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>
            {LONG_DATE.format(new Date(`${data.date}T00:00:00`))}
          </p>
          <h1>{greeting()}, {data.display_name}</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <div className="hero-parallax">
            <section className="hero">
              <p className="eyebrow on-ink" style={{ margin: 0 }}>Safe to spend today</p>
              <div style={{ marginTop: 11 }}>
                <Odometer sen={data.safe_today_sen} size={52} />
              </div>
              <p
                className="voice"
                style={{ margin: "12px 0 0", fontSize: 15, color: "rgba(233,237,233,.78)" }}
              >
                Your bills and the RM{fmt(data.buffer_sen)} buffer are already set aside. This is
                what's left over, spread evenly across the {data.days_to_payday} days to payday.
              </p>

              <div style={{ marginTop: 20 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    marginBottom: 10,
                  }}
                >
                  <span className="eyebrow on-ink">Where your RM{fmt(data.balance_sen)} stands</span>
                  <span style={{ fontSize: 11.5, color: "rgba(233,237,233,.5)", fontWeight: 600 }}>
                    tap a band
                  </span>
                </div>
                <ClaimLine data={data} picked={picked} onPick={setPicked} />
              </div>

              <button
                className="btn btn-sm"
                style={{
                  marginTop: 16,
                  background: "rgba(233,237,233,.17)",
                  color: "#F4F7F3",
                  border: "1px solid rgba(233,237,233,.26)",
                  width: "100%",
                }}
                onClick={() => setMaths((m) => !m)}
              >
                {maths ? "Hide the working" : "Show the working"}
              </button>

              {maths && (
                <div className="maths">
                  {rows.map(([k, v, total], i) => (
                    <div
                      className={`maths-row ${total ? "total" : ""}`}
                      key={k}
                      style={{ animationDelay: `${i * 55}ms` }}
                    >
                      <span>{k}</span>
                      <b>{v}</b>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        </Reveal>

        {data.drafts_waiting > 0 && (
          <Reveal delay={40} style={{ marginTop: 16 }}>
            <button
              className="card tapp"
              style={{ display: "flex", gap: 13, alignItems: "center", width: "100%", textAlign: "left" }}
              onClick={() => go("activity")}
            >
              <span
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 13,
                  background: "rgba(169,133,63,.14)",
                  color: "var(--brass)",
                  display: "grid",
                  placeItems: "center",
                  flex: "none",
                }}
              >
                <IcBell size={19} />
              </span>
              <span style={{ flex: 1 }}>
                <b style={{ fontSize: 14.5, display: "block", letterSpacing: "-.01em" }}>
                  {data.drafts_waiting} capture{data.drafts_waiting === 1 ? "" : "s"} waiting on you
                </b>
                <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                  Nothing enters your ledger until you confirm it.
                </span>
              </span>
              <IcChev size={17} />
            </button>
          </Reveal>
        )}

        {next && (
          <Reveal delay={60} style={{ marginTop: 16 }}>
            <section className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <p className="eyebrow" style={{ margin: "0 0 6px" }}>Next commitment</p>
                  <b style={{ fontSize: 17, letterSpacing: "-.02em" }}>{next.name}</b>
                  <p style={{ margin: "3px 0 0", fontSize: 12.5, color: "var(--muted)" }}>
                    Due {LONG_DATE.format(new Date(`${next.due_date}T00:00:00`))} · in{" "}
                    {next.days_until} day{next.days_until === 1 ? "" : "s"}
                  </p>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="money" style={{ fontSize: 21 }}>{fmt(next.amount_sen)}</div>
                  {next.protected && (
                    <span className="pill" style={{ marginTop: 7, fontSize: 9.5, padding: "4px 9px" }}>
                      <IcLock size={11} /> Reserved
                    </span>
                  )}
                </div>
              </div>
            </section>
          </Reveal>
        )}

        <Reveal delay={40} style={{ marginTop: 16 }}>
          <button className="card tapp" style={{ width: "100%", textAlign: "left" }} onClick={() => go("plan")}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginBottom: 14,
              }}
            >
              <p className="eyebrow" style={{ margin: 0 }}>Your goals</p>
              <span className="tag" style={{ color: "var(--brass)" }}>
                RM{fmt(data.goal_reserve_sen)} held
              </span>
            </div>
            <div style={{ display: "flex", gap: 14 }}>
              {data.goals.map((g) => (
                <span key={g.id} style={{ flex: 1, display: "flex", gap: 11, alignItems: "center", minWidth: 0 }}>
                  <span className="ringwrap" style={{ width: 46, height: 46, flex: "none" }}>
                    <Ring
                      pct={Math.min(1, g.saved_sen / g.target_sen)}
                      size={46}
                      stroke={HORIZON_STROKE[g.horizon] ?? "#A9853F"}
                    />
                    <figcaption>
                      <b style={{ fontSize: 11, letterSpacing: "-.03em" }}>
                        {Math.round((g.saved_sen / g.target_sen) * 100)}%
                      </b>
                    </figcaption>
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <b
                      style={{
                        fontSize: 12.5,
                        letterSpacing: "-.01em",
                        display: "block",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {g.name}
                    </b>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>
                      {g.months_left} month{g.months_left === 1 ? "" : "s"} to go
                    </span>
                  </span>
                </span>
              ))}
              {data.goals.length === 0 && (
                <span style={{ fontSize: 13, color: "var(--muted)" }}>No goals set. Tap to add one.</span>
              )}
            </div>
          </button>
        </Reveal>

        <Reveal delay={40} style={{ marginTop: 16 }}>
          <section
            className="card"
            style={{
              background: "linear-gradient(150deg,#F6F3EA,#EFEFE7)",
              border: "1px solid rgba(169,133,63,.24)",
            }}
          >
            <p className="eyebrow" style={{ margin: "0 0 7px", color: "var(--brass)" }}>Lunch</p>
            <p className="voice" style={{ margin: 0, fontSize: 17, lineHeight: 1.4 }}>
              Shall I plan lunch and the trip to KLCC before your next meeting?
            </p>
            <button className="btn btn-primary btn-sm" style={{ marginTop: 14 }} onClick={() => go("plan")}>
              Plan my day <IcArrow size={15} />
            </button>
          </section>
        </Reveal>
      </div>
    </>
  );
}
```

The prototype's `Odometer` markup uses `.odo`, `.odo-rm`, `.odo-d`, `.odo-sep` — confirm those exist in `kira.css` with `grep -c 'odo-d' apps/web/src/styles/kira.css`. If the count is 0, the extraction range in Task 11 Step 5 was wrong; redo it.

- [ ] **Step 7: Run the Today tests**

Run: `cd apps/web && npx vitest run`
Expected: PASS — money, App, and Today suites all green.

- [ ] **Step 8: Typecheck**

Run: `cd apps/web && npm run typecheck`
Expected: no errors. If `@kira/contracts` cannot be resolved, run `npm install` from the repo root so the workspace link exists, and confirm `packages/contracts/src/schema.d.ts` was generated in Task 10.

- [ ] **Step 9: See it in a browser**

With `uvicorn` running on `:8000` and the demo seeded:

```bash
npm --workspace apps/web run dev
```

Open `http://localhost:5173`, sign in with the prefilled credentials. Expected: the boot animation plays, Today shows **RM52.97**, the claim line splits into four bands, "Show the working" reconciles to 52.97, the drafts card reads "2 captures waiting on you", and all five tabs switch.

- [ ] **Step 10: Commit**

```bash
git add apps/web/src
git commit -m "feat: add Today screen reading live safe-to-spend from the API"
```

---

## Task 14: One container

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `apps/api/docker-entrypoint.sh`
- Modify: `docker-compose.yml` (add the `app` service), `apps/api/kira/api/app.py` (mount the built bundle)

**Interfaces:**
- Consumes: everything above.
- Produces: an image serving the SPA at `/` and the API at `/v1`, plus `docker compose up` bringing up `db` and `app` together with migrations and the seed applied on start.

- [ ] **Step 1: Add the static mount to `apps/api/kira/api/app.py`**

Append inside `create_app()`, after `app.include_router(dashboard.router)`:

```python
    # In the shipped image the built bundle sits beside the package. In
    # development it is absent and Vite serves the UI instead, so this is
    # conditional rather than required.
    static_dir = Path(__file__).resolve().parents[1] / "static"
    if static_dir.is_dir():
        app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="spa")
```

and above `create_app`:

```python
class SpaStaticFiles(StaticFiles):
    """Serves the built bundle, falling back to index.html for client routes.

    Mounted last, so it never shadows /v1. A missing asset under a client
    route must return the app shell, not a 404, or a deep link breaks.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
```

with the imports `from pathlib import Path`, `from fastapi.staticfiles import StaticFiles`, and `from starlette.exceptions import HTTPException as StarletteHTTPException`.

- [ ] **Step 2: Add a test for the fallback at `apps/api/tests/api/test_spa.py`**

```python
class TestApiIsNotShadowed:
    async def test_health_still_answers(self, client):
        assert (await client.get("/v1/health")).status_code == 200

    async def test_unknown_api_route_is_a_404_not_the_app_shell(self, client):
        response = await client.get("/v1/nope")
        assert response.status_code == 404
        assert "<!doctype html>" not in response.text.lower()
```

Run: `cd apps/api && .venv/bin/pytest tests/api/test_spa.py -q`
Expected: PASS (no `static/` directory exists in a dev checkout, so the mount is skipped — which is exactly the behaviour being asserted).

- [ ] **Step 3: Write `.dockerignore`**

```gitignore
**/node_modules
**/.venv
**/__pycache__
**/dist
**/.pytest_cache
.git
docs
*.pdf
kira-prototype.jsx
```

- [ ] **Step 4: Write `apps/api/docker-entrypoint.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "Applying migrations…"
alembic upgrade head

if [ "${SEED_DEMO:-1}" = "1" ]; then
  echo "Seeding the demo user…"
  python -m kira.seed
fi

exec uvicorn kira.api.app:app --host 0.0.0.0 --port 8000
```

Then `chmod +x apps/api/docker-entrypoint.sh`.

- [ ] **Step 5: Write the `Dockerfile`**

```dockerfile
# ---- stage 1: build the web bundle -------------------------------------
FROM node:22-alpine AS web

WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN npm ci

COPY packages/contracts packages/contracts
COPY apps/web apps/web
RUN npm --workspace apps/web run build

# ---- stage 2: the app image --------------------------------------------
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY apps/api/pyproject.toml ./
COPY apps/api/kira ./kira
RUN pip install --no-cache-dir .

COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/docker-entrypoint.sh ./docker-entrypoint.sh

# The bundle lands beside the package, where create_app() looks for it.
COPY --from=web /build/apps/web/dist ./kira/static

RUN adduser --system --no-create-home kira && chown -R kira /app
USER kira

EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
```

- [ ] **Step 6: Add the `app` service to `docker-compose.yml`**

```yaml
  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://kira:kira@db:5432/kira
      JWT_SECRET: ${JWT_SECRET:-dev-secret-change-me}
      DEMO_TODAY: "2026-09-03"
      SEED_DEMO: "1"
    ports:
      - "8000:8000"
```

- [ ] **Step 7: Build and run the whole thing**

```bash
docker compose down -v && docker compose up --build
```

Expected: `db` becomes healthy, `app` logs "Applying migrations…", "Seeding the demo user…", then uvicorn starts.

- [ ] **Step 8: Verify the single container serves both halves**

```bash
curl -s localhost:8000/v1/health
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/some/deep/link
TOKEN=$(curl -s localhost:8000/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"demo@kira.app","password":"demo-money-butler"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/v1/dashboard/today -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["safe_today_sen"])'
```

Expected: `{"status":"ok"}`, then `200`, then `200` (the SPA fallback), then `5297`.

Then open `http://localhost:8000` in a browser and sign in — the same Today screen, now served entirely from one container.

- [ ] **Step 9: Prove a restart does not duplicate the demo data**

```bash
docker compose restart app
docker compose exec db psql -U kira -d kira -c 'SELECT count(*) FROM commitments;'
```

Expected: `5`. If it reads `10`, `seed_demo_user` is not clearing prior rows — fix the seed, not the test.

- [ ] **Step 10: Run every gate one last time**

```bash
cd apps/api && .venv/bin/pytest -q && .venv/bin/lint-imports && .venv/bin/ruff check .
cd ../.. && npm --workspace apps/web run test && npm --workspace apps/web run typecheck
```

Expected: all green.

- [ ] **Step 11: Write the README**

Replace the repo `README.md` with what someone needs to run this:

```markdown
# Kira — AI Money Butler

Turns a financial picture into safe daily decisions. Malaysia-first: money is
integer sen, the day planner knows KL.

## Run it

    docker compose up --build

Then open http://localhost:8000 and sign in as `demo@kira.app` /
`demo-money-butler`. Today should read **RM52.97**.

## Develop

    docker compose up -d db
    cd apps/api && .venv/bin/uvicorn kira.api.app:app --reload --port 8000
    npm --workspace apps/web run dev        # http://localhost:5173, proxies /v1

## Check it

    cd apps/api && .venv/bin/pytest && .venv/bin/lint-imports
    npm --workspace apps/web run test

## Layout

- `apps/api/kira/engine` — pure finance math. No I/O, no clock, no float.
- `apps/api/kira/services` — the only layer that writes.
- `apps/api/kira/adapters` — every external service, behind a Protocol with a fake.
- `apps/web` — the PWA, decomposed from `kira-prototype.jsx`.
- `packages/contracts` — TypeScript types generated from the OpenAPI schema.

## Design

- Spec: `docs/superpowers/specs/2026-08-24-kira-architecture-design.md`
- Week 1 plan: `docs/superpowers/plans/2026-08-24-kira-week-1-base.md`

No part of this system can move money. There is no transfer endpoint, no
provider write path, and the agent has no write tool.
```

- [ ] **Step 12: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml apps/api README.md
git commit -m "build: serve API and web bundle from a single container"
```

---

## Week 1 gate

The week is done when all of the following are true:

- [ ] `docker compose up --build` serves a working Today screen at `http://localhost:8000`.
- [ ] Today's headline reads **RM52.97**, and "Show the working" reconciles to it.
- [ ] `cd apps/api && pytest` is green, including six golden cases and the draft-invariant tests.
- [ ] `lint-imports` reports 2 contracts kept, 0 broken.
- [ ] The engine purity tests pass, and adding a float to `kira/engine/` makes them fail.
- [ ] `npm --workspace apps/web run test && npm --workspace apps/web run typecheck` is green.
- [ ] Every adapter has a Protocol and a fake, and the whole suite runs with no network.
- [ ] `python -m kira.seed` is idempotent.
- [ ] No endpoint, service, or tool anywhere in the codebase moves money.
