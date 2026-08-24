# Kira — AI Money Butler

Kira is a privacy-conscious money assistant built for the AI competition. It
answers one practical question: **what can I safely spend today?**

The answer is derived from a user's account opening balances, confirmed spend,
upcoming commitments, emergency buffer, savings goals, and payday. Every
monetary amount is an exact integer number of Malaysian sen—never a float.

## Current status

The backend and the web foundation are implemented through the first 11 tasks
of the development plan. The working API has authentication and a seeded
dashboard; the React/Vite client has its design system, generated API types,
query layer, and money formatting in place. The interactive application shell
and Today screen are the next implementation tasks.

Implemented:

- Exact `Money` value object with integer-sen arithmetic, currency checking,
  half-up rounding, and display formatting.
- Pure finance engine with golden-file tests. It calculates commitments,
  goal accrual, per-day allowance, and today's safe-to-spend amount.
- Database schema and Alembic migration for users, accounts, commitments,
  goals, transactions, and refresh tokens.
- JWT authentication with Argon2 password hashes, short-lived access tokens,
  httpOnly refresh cookies, refresh-token rotation, and logout revocation.
- Strict transaction workflow: `draft` transactions never affect balances or
  safe-to-spend; only `confirmed` transactions do.
- Deterministic offline OCR, voice, maps, storage, and LLM adapters for
  testing and unreliable competition-venue networks.
- Versioned, idempotent demo seed matching the prototype figures.
- `GET /v1/dashboard/today`, backed by the pure engine and returning only
  integer-sen monetary values.
- OpenAPI-generated TypeScript contracts consumed by the web workspace.
- React/Vite web scaffold, TanStack Query API layer, formatter tests, and the
  full visual stylesheet extracted from the design prototype.

## The demo financial picture

The included demo user is `demo@kira.app` with password `demo-money-butler`.
On the pinned demo date, 2026-09-03, it produces:

| Measure | Value |
| --- | ---: |
| Account balance | RM4,180.40 |
| Protected commitments before payday | RM2,003.00 |
| Emergency buffer | RM800.00 |
| Accrued goal reserve | RM212.00 |
| Safe to spend today | **RM52.97** |

Two receipt/voice transactions are deliberately left as drafts. They appear
as waiting confirmations but do not lower the RM52.97 figure.

## Architecture

```text
HTTP API  →  services  →  pure finance engine
                ↓
             adapters

Postgres ← SQLAlchemy models and Alembic migration
React    ← generated TypeScript contracts from FastAPI OpenAPI
```

The engine has no I/O, database, network, or clock dependency. It imports only
the standard library and Kira's `Money` type. CI tests enforce that boundary,
ban floats and true division in the engine, and verify that imports point one
way.

No endpoint, service, adapter, or tool moves money. Kira only calculates and
explains a user's financial picture.

## Repository layout

```text
apps/api/                 FastAPI application, engine, database, and tests
apps/web/                 React + Vite client foundation
packages/contracts/       Generated OpenAPI TypeScript declarations
scripts/gen-contracts.sh  Regenerates contracts without starting a server
docs/                     Architecture specification and implementation plan
docker-compose.yml        Local PostgreSQL service
```

## Run the backend locally

Prerequisites: Python 3.12+, Node.js 22+, npm, and Docker.

Start PostgreSQL:

```bash
docker compose up -d db
```

Install the API package, migrate the database, and seed the demo user:

```bash
cd apps/api
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
DATABASE_URL=postgresql+asyncpg://kira:kira@localhost:5432/kira .venv/bin/alembic upgrade head
DATABASE_URL=postgresql+asyncpg://kira:kira@localhost:5432/kira .venv/bin/python -m kira.seed
```

Run the API with the reproducible demo date:

```bash
DATABASE_URL=postgresql+asyncpg://kira:kira@localhost:5432/kira \
DEMO_TODAY=2026-09-03 \
.venv/bin/uvicorn kira.api.app:app --reload --port 8000
```

Available endpoints:

- `GET /v1/health`
- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`
- `GET /v1/auth/me`
- `GET /v1/dashboard/today`
- Interactive OpenAPI docs at `http://localhost:8000/v1/docs`

## Run checks

Backend:

```bash
cd apps/api
DEMO_TODAY=2026-09-03 .venv/bin/pytest -q
.venv/bin/ruff check kira tests alembic/env.py alembic/versions/0001_initial.py
.venv/bin/lint-imports
```

Web formatter test:

```bash
npm --workspace @kira/web run test -- src/lib/money.test.ts
```

Regenerate the TypeScript contract after an API-schema change:

```bash
bash scripts/gen-contracts.sh
```

## Development notes

- `.env.example` uses the Docker service hostname `db`, which is correct from
  inside a future app container. Local backend commands should use `localhost`
  as shown above.
- The web app's App shell and Today screen are not yet implemented, so complete
  web typechecking/building follows the next frontend task.
- `docker compose` currently starts PostgreSQL only. The one-container API +
  web production image is a later planned task.

For the full rationale and implementation sequence, see the
[architecture design](docs/superpowers/specs/2026-08-24-kira-architecture-design.md)
and [week-one implementation plan](docs/superpowers/plans/2026-08-24-kira-week-1-base.md).
