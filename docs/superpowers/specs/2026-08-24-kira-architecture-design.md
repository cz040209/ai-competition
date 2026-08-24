# Kira — AI Money Butler: Architecture Design

Date: 2026-08-24
Status: Approved (stack and architecture confirmed with product owner)
Inputs: `kira-development-plan.pdf` (11pp), `kira-prototype.jsx` (2,725 lines)

## 1. Product scope

Kira turns a user's financial picture into safe daily decisions. The MVP is
defined by the competition demo script, not by the full feature matrix in the
plan document. Anything the demo script does not exercise is post-competition.

**In scope:** ledger and manual entry; commitments and bills; safe-to-spend;
goals and scenario replanning; receipt OCR and voice capture as drafts; the
food-and-transport day planner; the Butler agent with approval interrupts;
audit trail; CSV import.

**Out of scope for MVP:** read-only bank/e-wallet adapters (CSV import is the
fallback and it is sufficient), push notifications, money movement of any kind,
investment or credit advice.

**Hard boundary:** no tool in the system moves money. `apply_plan_change` is
not exposed to the agent at all — it is a service function reachable only from
the approval endpoint after an explicit user POST. The agent is structurally
incapable of writing, rather than instructed not to.

## 2. Decisions made

| Decision | Choice | Why |
|---|---|---|
| Frontend | React + Vite + TypeScript, installable PWA | The prototype is DOM React, and a native app cannot ship in one container. |
| Backend | FastAPI + Pydantic v2 | Typed REST, SSE streaming, Python for the solver. |
| Database | PostgreSQL 16 + SQLAlchemy 2 async + Alembic | Durable ledger, auditable plan versions. |
| Auth | Own JWT in FastAPI | Full control; no third-party dependency. |
| Agent | LangGraph | `interrupt()` + checkpointer maps directly onto the approval pause. |
| LLM | Claude, behind `LlmAdapter` | Pinned for the competition; the adapter keeps it swappable. |
| Async work | None for MVP | OCR and Maps calls run in-request (2–5s). No Redis, no Celery, no worker. |
| Packaging | One app image (static bundle + API), Postgres as a compose service | `docker compose up` is the whole setup. |
| Dev mode | Vite dev server proxying `/v1` to uvicorn | HMR matters for an animation-heavy UI. |

### 2.1 Why the frontend is web, not Expo

The development plan specified Expo React Native. The prototype that defines
the product's visual design is DOM React — CSS-in-a-template-string, Leaflet,
`<input type="file">`, `MediaRecorder`, SVG icons. Porting it to React Native
means rewriting every animation into Reanimated, Leaflet into
`react-native-maps`, and the entire stylesheet into `StyleSheet` objects: weeks
of translation producing something less polished than what exists today.

The one-container requirement independently forces the same answer. A native
binary cannot be served from a container; a web bundle can.

Every device capability the MVP needs is available on mobile web:
`navigator.geolocation` (day planner), `<input capture="environment">`
(receipts), `MediaRecorder` (voice), IndexedDB (offline cache).

Accepted losses: iOS push outside an installed PWA, background sync, app-store
presence. None appear in the demo script. A future Expo client would be a
second consumer of the same API and would not change the backend.

## 3. Repository layout

```
kira/
  apps/
    web/                    Vite + React + TS  (the prototype, decomposed)
      src/
        screens/            Today, Activity, Butler, Plan, Places, More,
                            Bills, Accounts, Safety
        components/         Odometer, Reveal, Ring, ClaimLine, NavItem, …
        sheets/             VoiceSheet, ScanSheet, GoalSheet
        api/                generated client + TanStack Query hooks
        styles/             the design system extracted from STYLES
    api/
      kira/
        api/                routers, request/response schemas, auth deps
        services/           orchestration, DB transactions, ownership checks
        engine/             pure functions — no I/O, no DB, no clock
        adapters/           Ocr, Voice, Maps, Storage, Llm — Protocol + fake
        agent/              LangGraph graph, tools, policy guard
        db/                 models, session, Money type
        seed/               demo fixtures
      alembic/
      tests/
        engine/cases/       golden-file fixtures
  packages/contracts/       OpenAPI → generated TypeScript types
  docs/
  Dockerfile                multi-stage: build web → serve from API image
  docker-compose.yml        app + db
```

Monorepo. The web app never hand-writes an API type: FastAPI emits OpenAPI, a
codegen step produces `packages/contracts`, the web app imports it. Contract
drift becomes a TypeScript compile error rather than a runtime surprise.

## 4. Backend layering

Four layers with strictly one-directional dependencies:

```
api  →  services  →  engine
             ↓
          adapters
```

- **`api/`** — routers, Pydantic request/response models, the auth dependency.
  No business logic. Translates HTTP into service calls.
- **`services/`** — orchestration, transaction boundaries, ownership checks.
  The only layer that writes.
- **`engine/`** — pure functions. `safe_to_spend()`, `run_scenarios()`,
  `project_goal()`, `evaluate_option()`. No DB session, no network, no
  `datetime.now()` — the clock is a parameter. This is what makes the
  determinism claim testable.
- **`adapters/`** — `OcrAdapter`, `VoiceAdapter`, `MapsAdapter`,
  `StorageAdapter`, `LlmAdapter`. Each is a `Protocol` with a fake
  implementation, so the entire test suite and the offline demo mode run with
  zero external calls.

`engine` imports nothing from the other three layers. That constraint is
enforced by an import-linter rule in CI.

## 5. The money type

All money is integer sen with an ISO currency code. This is enforced in code,
not by convention:

- A `Money` value object wrapping `int` sen + currency. Arithmetic is only
  defined between same-currency `Money`; mixing currencies raises.
- A custom SQLAlchemy `TypeDecorator` so a `float` cannot physically reach a
  money column.
- A lint rule banning `float` in `kira/engine/`.

Rounding is `round()` to the nearest sen, applied once at the point a ratio
becomes an amount — never accumulated.

## 6. The finance engine

Adopted from the prototype, which models this more correctly than the plan
document did. A goal claims only what has **accrued so far this cycle**, not
its whole monthly contribution:

```
goal_reserve  = Σ round(goal.monthly × cycle_elapsed / cycle_days)
reserved      = Σ commitment.amount  where due_date < next_payday
unclaimed     = balance − reserved − buffer − goal_reserve
per_day       = floor(unclaimed / days_to_payday)
safe_today    = max(0, per_day − spent_today)
```

**Correction against the prototype:** the prototype reserves *all* commitments
regardless of due date. The engine reserves only those falling before the next
payday, which is the behaviour the plan document describes and the correct one.
Demo seed figures are tuned so the headline numbers stay close to the
prototype's.

**Computed on read, never cached.** `safe_to_spend` is a pure function of a
snapshot. There is no materialised column and no invalidation logic — the
entire class of stale-derived-value bugs does not exist. Every Butler answer
persists the exact snapshot it consumed, so any past answer can be re-derived
and explained.

**Draft invariant.** Every ingested transaction is written `status='draft'` and
is excluded from every engine calculation until confirmed. This is enforced in
the snapshot loader, which filters `status='confirmed'`; there is no code path
around it.

**Multiple goals.** The plan document said one savings goal; the prototype has
several, each with a horizon (`short` / `long`), target, saved, and monthly
contribution. The prototype's model is the one implemented.

## 7. Day planner

The prototype's `evaluate(place, origin, mode, room)` is the specification:
haversine distance, per-mode cost and time model
(`{base, perKm, minPerKm, wait}` for walk / transit / ride), plus a curated
per-place cost estimate with an explicit confidence label.

This is the honest answer to the pricing problem the plan document flagged:
Places APIs expose a `price_level` bucket, not menu prices. Kira shows a
labelled estimate with its confidence and never claims a real price.

The backend `MapsAdapter` mirrors `evaluate()` exactly so the numbers cannot
drift between client and server; the curated KL place set ships as seed data.
A real provider slots in behind the same Protocol later.

## 8. Butler agent

LangGraph, following the plan document's seven stages: intent extraction →
policy guard → read tools → deterministic tools → response composer → approval
interrupt → audit and resume.

The tool registry contains **read and calculate tools only**:
`get_financial_snapshot`, `calculate_safe_to_spend`, `run_goal_scenarios`,
`build_day_plan`, `create_plan_change_draft`, `request_user_approval`. Nothing
that writes financial state is registered.

`interrupt()` pauses on any proposed plan change. Resumption happens only via
`POST /v1/approvals/{id}/respond` with accept / edit / reject. On accept, the
service applies the change, writes an `audit_event`, and increments the plan
version.

Answers stream over SSE and always carry the evidence and assumptions used.

## 9. Auth

FastAPI-owned JWT: short-lived access tokens plus rotating refresh tokens.
Argon2 password hashing. Refresh tokens are stored hashed and are individually
revocable. The web client keeps them in memory plus a `httpOnly` refresh
cookie; a TanStack Query interceptor handles silent refresh.

## 10. Packaging

Multi-stage Dockerfile: stage one builds the Vite bundle, stage two installs
the Python app and copies the bundle in. Uvicorn serves the API under `/v1/*`
and the static bundle with SPA fallback at `/`.

`docker-compose.yml` runs `app` and `db` (postgres:16). Migrations run on
startup. A seed command loads the demo user.

In development, Vite runs on `:5173` with HMR and proxies `/v1` to uvicorn on
`:8000`. Production serving is unified; development is split.

## 11. Testing and quality gates

- **Golden-file suite for the engine**, from week one. Each case in
  `tests/engine/cases/*.json` holds an input snapshot and expected output. Any
  drift in the finance math fails CI. This is what backs the "same inputs
  always produce the same result" claim.
- **Adapter fakes** for every external service, so the full suite and the
  offline demo run with no network.
- **Import-linter** enforcing that `engine` depends on nothing.
- **Draft-invariant test**: an unconfirmed draft never changes safe-to-spend.
- **Agent-boundary test**: the tool registry contains no write tool; a plan
  change cannot be applied without an approval record.
- **Contract test**: the generated TypeScript client compiles against the live
  OpenAPI schema.

## 12. Offline and demo resilience

Competition venues have unreliable networks. TanStack Query persists to
IndexedDB, and a demo mode runs entirely from seeded local data. The demo user
— balance, payday, rent, phone bill, car loan, buffer, emergency-top-up goal,
wedding goal — is a versioned seed script maintained from week one, not
assembled at the end.

## 13. Build order

Revised from the plan document's eight workstreams, demo-script-first:

| Week | Deliverable gate |
|---|---|
| 1 | Monorepo, Docker, Postgres, auth, `Money` type, engine + first golden tests, adapter Protocols with fakes, demo seed, web shell with nav and Today reading `GET /v1/dashboard/today`. |
| 2 | Ledger, manual entry, commitments, bills, full safe-to-spend wired end to end. |
| 3–4 | Goals, scenario comparison, overspend replanning, engine test suite complete. |
| 5 | Receipt and voice draft capture with confirmation flow. |
| 6 | Day planner, map, curated estimates, selection and goal impact. |
| 7 | Butler graph, tools, evidence display, approval interrupt, audit events. |
| 8 | CSV import, end-to-end test, demo script rehearsal, polish, security review. |

Weeks 1–7 carry the demo. Week 8 is slack.
