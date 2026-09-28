# How the platform works — architecture

Plain-language reference for the platform in this repository. Everything here is read
from the actual files — compose files, Dockerfiles, Traefik rules, environment
templates and application routers. Nothing is aspirational: if it is not
implemented, it says so.

Companion documents:

- [`../README.md`](../README.md) — beginner start guide (demo + LAN quick start)
- [`../DEPLOYMENT.md`](../DEPLOYMENT.md) — the six-system runbook (IPs, firewall, tests)
- [`../gateway/DEPLOYMENT.md`](../gateway/DEPLOYMENT.md) — per-stack reference
- [`API.md`](API.md), [`ASSESSMENT.md`](ASSESSMENT.md), [`TESTING.md`](TESTING.md),
  [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)

---

## 1. The big picture

```
Candidate computers (browser only)
        │   http://<GATEWAY_LAN_IP>/
        ▼
┌─────────────────────────────────────────────────────────────┐
│ GATEWAY stack                                               │
│   traefik      — the front door on :80                      │
│   frontend     — website pages (React SPA, nginx)           │
│   gateway-api  — helper API: /api/health, sessions,         │
│                  /api/execute (operator/smoke-test path)    │
└───────┬──────────────────────────────┬──────────────────────┘
        │  /_api/*  (StripPrefix)      │  /challenge/* (StripPrefix)
        ▼                              ▼
┌───────────────────────┐   ┌──────────────────────────┐  ┌──────────────────────┐
│ APP pool              │   │ CHALLENGE pool           │  │ (same App machines)  │
│  app-1 :8002          │   │  challenge-1 :8080       │  │  app-2 :8002         │
│  app-2 :8002          │   │  challenge-2 :8080       │  │  challenge-2 :8080   │
│  (FastAPI backend)    │   │  (SQLi Employee Portal)  │  │                      │
└───────┬───────────────┘   └──────────────────────────┘  └──────────────────────┘
        │
        ├────────────► Supabase (cloud Postgres + Auth, the only Internet dependency)
        │
        └────────────► COMPILER pool  ── round-robin + failover ──┐
                          COMPILER_1_URL / _2_ / _3_             ▼
                          (Judge0 nodes, :2358/2359/2360)   judge0-server → worker
                                                             → isolate sandbox
```

- The **Gateway** is the only machine candidates talk to. Every candidate-visible
  URL is Gateway-relative: `/`, `/_api/*`, `/api/*`, `/challenge/*`. An internal
  machine address is never sent to a browser.
- The **App pool** carries login, domain selection, assessments, coding Run/Submit
  and all admin traffic. Both apps talk to **one shared Supabase project**.
- The **compiler pool** carries only "execute this code" requests. The app
  backends call it directly (`COMPILER_1_URL..3_URL`); the gateway-api's
  `/api/execute` reaches it too (used by smoke tests and operators).
- The **challenge pool** serves the SQL-injection Hands-On challenge, isolated:
  own seeded SQLite database, no platform credentials, no Internet.
- Hands-On **SQL/Pandas WASM challenges run entirely in the candidate's browser**
  (DuckDB-WASM / Pyodide) — no server is involved in their execution.

### Deployment topologies (do not mix them)

| Topology | What runs where | How to start |
|---|---|---|
| **Development** | backend `uvicorn` + frontend `vite` on the developer machine, pointing at Supabase; optional local compiler node | [`DEVELOPMENT.md`](DEVELOPMENT.md) |
| **Single-host simulation** | all six stacks co-located on one machine (ports 2358/2359/2360 differ per compiler node) | `./gateway/dockerdemoup.sh all` |
| **Multi-machine LAN (target)** | six physical machines: Gateway, App-1, Compiler-1, App-2, Compiler-2, Compiler-3 | [`../DEPLOYMENT.md`](../DEPLOYMENT.md) |

The compose files are identical in every topology; only the addresses in the
`.env` files (LAN IP vs `host.docker.internal`) differ.

### The six stacks (all implemented)

| Stack | Folder | Containers | Host ports |
|---|---|---|---|
| 1 Gateway | `gateway/` | `traefik`, `frontend`, `gateway-api` | **80** (candidates), 8080 (Traefik dashboard) |
| 2 App-1 | `gateway/app-1/` | `app-1`, `challenge-1` | 8002 (API), 8080 (challenge) |
| 3 Compiler-1 | `gateway/judge0/` | `compiler-1-server/-worker/-db/-redis` (+ one-shot `-java-tuning`) | 2358 |
| 4 App-2 | `gateway/app-2/` | `app-2`, `challenge-2` | 8002, 8080 |
| 5 Compiler-2 | `gateway/judge0/` | `compiler-2-*` | 2359 |
| 6 Compiler-3 | `gateway/judge0/` | `compiler-3-*` | 2360 |

An optional monitoring stack (`gateway/monitoring/`: Prometheus, Grafana,
node-exporter, cAdvisor) is documented in
[`../gateway/monitoring/README.md`](../gateway/monitoring/README.md).
The legacy single-container runner `gateway/compiler-1/` still exists but is
**off by default** (`EXECUTION_BACKEND=judge0`).

---

## 2. The networks between containers

| Network | Who joins | Purpose |
|---|---|---|
| `gateway_net` (Gateway project) | traefik, frontend, gateway-api | Gateway-internal traffic |
| `system3` (external; create once with `docker network create system3`) | gateway-api, each app container — plus a Judge0 node only when it is configured with `COMPILER_NETWORK=system3` (single co-located node) | Co-located Gateway ⇄ Judge0 and App ⇄ Judge0 traffic by service name |
| `compiler-1-net` / `compiler-2-net` / `compiler-3-net` (created by `deploy-compiler.sh`) | exactly one Judge0 node's server/worker/db/redis | Keeps several Judge0 nodes on one host unambiguous (each has its own `judge0-db`/`judge0-redis`) |
| `challenge_net` (per App project) | that app's challenge container only | The challenge container has no other network path |

Across machines there are **no shared Docker networks** — the Gateway reaches
App/Challenge/Compiler machines by LAN address from `.env`
(`APP1_URL`, `APP2_URL`, `APP1_CHALLENGE_URL`, `APP2_CHALLENGE_URL`,
`COMPILER_1_URL..3_URL`), firewalled to the right source IPs by the
DOCKER-USER guard (see [`../DEPLOYMENT.md`](../DEPLOYMENT.md) §6).

The app container also joins `system3`, so a Judge0 node on the same host can
be addressed as `http://judge0-server:2358` (`JUDGE0_BASE_URL`).

---

## 3. Where each request goes (Traefik routing)

The Gateway's Traefik routing table is **generated at container start from
environment variables** by the entrypoint in `gateway/docker-compose.yml`
(rendered to `/etc/traefik/dynamic.yml`). Highest priority wins:

| Priority | Path | Destination | Notes |
|---|---|---|---|
| 10 | `/api/*` | `gateway-api` (:8000, internal) | health, info, sessions, `/api/execute` |
| 8 | `/challenge` and `/challenge/*` | **challenge pool** `[APP1_CHALLENGE_URL, APP2_CHALLENGE_URL]` | `StripPrefix /challenge` — the challenge server sees `/`, `/login`, `/health` |
| 5 | `/_api/*` | **app pool** `[APP1_URL, APP2_URL]` | `StripPrefix /_api` — the backend sees `/auth/login`, `/admin/config`, … exactly its native routes |
| 1 | everything else (`/`, `/login`, `/domains`, `/assessment/…`, …) | `frontend` (nginx SPA) | client-side routes fall back to `index.html` |

The frontend is built with `VITE_API_URL="/_api"`, so every `fetch()` the SPA
makes is a same-origin `/_api/...` call. Traefik health-checks both pools
(`/` for apps, `/health` for challenges) every 10 s and drops unhealthy
members. An empty pool degrades to a closed port (one route answers 502) so a
misconfigured `.env` cannot take the whole site down.

**The single-host demo stack (`gateway/docker-compose.local.yml`) uses the
older direct-prefix rules instead** (`/auth/*`, `/questions/*`,
`/submission/*`, `/assessment/*`, `/coding/*`, `/admin/*` → `app-1-local`,
frontend built with `VITE_API_URL="."`, no `/challenge` route). Its app
backend and legacy `compiler-1-local` runner are on the same Docker network.
Use it only for local demos; the production rules above are the reference.

### Login request, step by step

```
1. GET  /login                      → traefik → frontend (page loads)
2. POST /_api/auth/login            → traefik (strip /_api) → app pool → app-1
   app-1 verifies credentials via Supabase Auth (Internet), sets the
   HttpOnly dsc_session cookie (JWT never returned to the browser) → back
3. GET  /_api/auth/me               → same path, returns {id, email}
```

Authentication is **cookie-only**: `dsc_session` (Supabase JWT, hard-capped at
2 h, no refresh-token flow) plus a CSRF cookie double-submit on state-changing
requests. Admin endpoints additionally require `profiles.is_admin`. Mid-
assessment endpoints accept a second, attempt-scoped `dsc_assessment`
capability cookie so an expiring login session never interrupts a running
attempt (see [`API.md`](API.md)).

---

## 4. Code execution (Run / Submit)

There are **three** execution paths; all server-side paths end at the same
Judge0 compiler pool:

```
(a) Candidate Run, Python 3          browser only — Pyodide Web Worker,
                                      public tests, never scored
(b) Candidate Run, C/C++/Java        POST /_api/coding/attempt/{id}/run
                                      → app backend → compiler pool → Judge0
(c) Candidate Submit (authoritative) POST /_api/coding/attempt/{id}/submit
                                      → app backend → compiler pool → Judge0
                                      ALL tests (public + hidden), server-scored
```

Path (a) executes in the browser from **local assets** (`/pyodide/`, copied at
`npm install` by `scripts/copy-pyodide.mjs`) — no CDN, no backend call. It is
feedback-only: Run results are never used for scoring.

Server-side execution, in `dsc-recruit/apps/backend/services/`:

| File | Role |
|---|---|
| `code_executor.py` | `run_code_public()` (Run) and `evaluate_submission()` (Submit); builds results, score, `error`/`harness_error` keys |
| `harness.py` | generates the per-language wrapper program that calls the candidate's function and compares JSON results (`python3`, `cpp`, `java`, `c`) |
| `compiler.py` | Judge0 client: **compiler pool** `COMPILER_1_URL/2/3` with a round-robin cursor and failover, token auth (`X-Judge0-Token`), base64 mode, polling |
| `assessment_planner.py` | (not execution) the pure assessment planner |

Language keys and Judge0 ids: `python3`→71, `cpp`→54, `java`→62, `c`→50
(Judge0 CE 1.13.1). SQL exists in Judge0 (id 82) but SQL questions are
Hands-On/WASM challenges, not coding problems.

The generated Python harness preamble includes
`from typing import Any, Dict, List, Optional` so seeded signatures like
`def singleNumber(self, nums: List[int]) -> int` execute without a
`NameError` — a current implementation detail of `harness.py`.

The operator/smoke-test path is separate: `POST /api/execute` on the
**gateway-api** (`gateway/gateway-api/`) with the same language/test-case
contract; it is used by `deployment-tests/` and the live gateway tests, not by
the candidate UI. Its backend is chosen by `EXECUTION_BACKEND` in
`gateway/.env` (`judge0` by default; `compiler1` for the legacy runner).

Status vocabulary (`accepted`, `wrong_answer`, `compilation_error`,
`runtime_error`, `time_limit_exceeded`, `invalid_language`, `capacity_exceeded`,
`compiler_unavailable`, `internal_error`) is shared by both paths.

---

## 5. Hands-On execution

Challenge type is stored per question (`hands_on_questions.challenge_type`,
migration `020`):

| Type | Where it runs | How it is scored |
|---|---|---|
| `sql_injection_employee_portal` | **server-side**: iframe loads same-origin `/challenge/` → Traefik → challenge pool (`challenge-1`/`challenge-2`, own SQLite seed) | candidate submits a flag; backend compares to `expected_flag` (trimmed, exact). Flag never leaves the backend |
| `sql_wasm` | **browser**: DuckDB-WASM (`src/execution/sqlWasmRunner.js`, assets copied by `scripts/copy-duckdb.mjs`) | browser validator returns a binary verdict; backend converts it to points (`points` when passed, 0 otherwise). No flag |
| `pandas_wasm` | **browser**: Pyodide + pandas (`src/execution/pandasWasmRunner.js`) | same as `sql_wasm` |

In all cases: **one submission per (attempt, question)** — a second attempt is
rejected with HTTP 409 before any scoring, and the candidate receives only
`{"status": "submitted"}` (never correctness, score or the expected flag).
Admins see the stored evidence, verification and score via the admin results
endpoint.

Run vs Submit inside a WASM challenge is a browser-local affordance (Run
validates against the sample validation spec; Submit posts the verdict). The
flag challenge has no Run — submitting the flag is the single submission.

---

## 6. Fullscreen and integrity controls

Implemented in `dsc-recruit/apps/frontend/src/pages/MCQTest.jsx` (the
assessment workspace) and documented for candidates in
[`CANDIDATE_GUIDE.md`](CANDIDATE_GUIDE.md):

- **Fullscreen entry** — requested on Start Assessment; if the browser rejects
  it (deep link, refresh), an entry gate asks for a click. The exit penalty is
  only armed after fullscreen was genuinely entered.
- **Exit detection** — leaving fullscreen mid-attempt shows a blocking overlay
  with a **15-second countdown**; returning to fullscreen cancels it, hitting
  zero auto-submits the attempt through the same authoritative submit path as
  the Finish button. The overall timer keeps running underneath.
- **Duration countdown** — at 0 the attempt auto-submits (single-submission
  guard shared by manual/timer/fullscreen/network triggers).
- **Network-integrity monitoring** (optional, admin toggle
  `assessment_config.network_integrity_monitoring`, migration `023`) — when the
  attempt's **frozen plan** enabled it, the workspace queries a local helper
  (`apps/network-monitor-agent`, loopback `127.0.0.1:8765`) once per minute.
  A **confirmed** ICMP reachability reply finalises the attempt with
  `termination_reason = 'network_integrity_violation'`. Helper failures
  (down, slow, malformed) are never treated as a violation.

These are client-side proctoring aids with server-side submit guards — they
are **not** a guarantee against a determined candidate on a second machine.
There is no screen recording, no tab-switch telemetry and no remote proctor.

---

## 7. How the containers get the application code

| Image | Dockerfile | Copies from the app repo | Build context |
|---|---|---|---|
| `frontend` | `gateway/frontend/Dockerfile` | `dsc-recruit/apps/frontend/` (Node builds it, nginx serves it) | repo root |
| `app-1` / `app-2` | `gateway/app-1/Dockerfile`, `gateway/app-2/Dockerfile` | `dsc-recruit/apps/backend/` | repo root |
| `challenge-1` / `challenge-2` | `gateway/app-1/Dockerfile.challenge`, `gateway/app-2/Dockerfile.challenge` | the challenge server + seed DB from `dsc-recruit/apps/backend/` | repo root |
| `gateway-api` | `gateway/gateway-api/Dockerfile` | — (deployment-only code) | `gateway/gateway-api/` |
| `compiler-1` (legacy) | `gateway/compiler-1/Dockerfile` | — (deployment-only code) | `gateway/` |

Because the first two copy from `dsc-recruit/...`, the application repo must be
cloned **inside** this repo named `dsc-recruit` (or the `COPY` lines adjusted).
The root `.dockerignore` keeps `.env` files, `judge0.conf` and irrelevant
folders out of those builds; `dsc-recruit/` itself is git-ignored in this
repository (it is its own repo).

---

## 8. Ports summary

| Port | Where | Bound to | Who may connect |
|---|---|---|---|
| 80 | Gateway | traefik | everyone on the LAN (candidates) |
| 8080 | Gateway | Traefik dashboard | operator only — never the challenge |
| 8002 | App-1 / App-2 | app API | Gateway only (DOCKER-USER guard) |
| 8080 | App-1 / App-2 | challenge server | Gateway only (DOCKER-USER guard) |
| 2358 / 2359 / 2360 | Compiler-1/2/3 | Judge0 API | Gateway + App machines only (guard) |
| 3001 | Gateway (optional monitoring) | Grafana | LAN/admin |
| 9090 | Gateway (optional monitoring) | Prometheus | loopback only |
| 8000 | dev machine | backend uvicorn (DEV only) | local |
| 5173 | dev machine | Vite dev server (DEV only) | local |

Internal-only (never published): `frontend:8080`, `gateway-api:8000`,
challenge container `8080`, Judge0 workers, PostgreSQL `5432`, Redis `6379`.

---

## 9. Environment variables

Full templates: `gateway/.env.example` (Gateway), `gateway/app-1/.env.example`
and `gateway/app-2/.env.example` (apps), `gateway/judge0/.env.example` +
`gateway/judge0/judge0.conf.example` (compiler nodes),
`deployment-tests/.env.example` (tests),
`dsc-recruit/apps/backend/.env.example` and
`dsc-recruit/apps/frontend/.env.example` (development).

The ones that matter day to day:

| Variable | File | Meaning |
|---|---|---|
| `APP1_URL` / `APP2_URL` | gateway/.env | app pool members (`http://<LAN-IP>:8002`); empty = out of pool |
| `APP1_CHALLENGE_URL` / `APP2_CHALLENGE_URL` | gateway/.env | challenge pool members (`http://<LAN-IP>:8080`) |
| `COMPILER_1_URL..3_URL` | gateway/.env **and** each app/.env | Judge0 nodes for `/api/execute` (gateway) and for coding Run/Submit (apps) |
| `JUDGE0_AUTH_TOKEN` + `JUDGE0_AUTH_HEADER` | gateway/.env, app/.env | shared token; must equal `AUTHN_TOKEN` in every node's `judge0.conf` |
| `EXECUTION_BACKEND` | gateway/.env | `judge0` (default) or `compiler1` (legacy) |
| `TRAEFIK_HTTP_PORT` / `TRAEFIK_DASHBOARD_PORT` | gateway/.env | front door / dashboard |
| `APP_ENV` / `APP_VERSION` | gateway/.env | shown by `/api/info` (current default: `development`) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` | app/.env | the one shared Supabase project |
| `APPn_HOST_PORT`, `APPn_CHALLENGE_PORT`, `APPn_API_BIND` | app/.env | published ports/bind |
| `COMPILER_NAME`, `COMPILER_NETWORK`, `JUDGE0_BIND`, `JUDGE0_PORT` | judge0/.env | node identity, private network, published API (`127.0.0.1` default; `0.0.0.0` on a LAN-exposed compiler machine) |

Never commit `.env` or `judge0.conf` — only the `.example` templates are in Git.

---

## 10. Database

Supabase (hosted Postgres + Auth) is the only datastore the platform uses.
Schema lives in `dsc-recruit/apps/backend/migrations/001…025_*.sql` — plain
SQL files applied **in order** via the Supabase SQL editor (each is idempotent
and documents its own safety notes). There is no Alembic in this repository.
See [`ASSESSMENT.md`](ASSESSMENT.md) for the table map and the planner.

Judge0 has its own private PostgreSQL + Redis per node (metadata/queue only,
never exposed) — unrelated to Supabase.

---

## 11. Tests that verify this deployment

See [`TESTING.md`](TESTING.md). In short:

- `gateway/gateway-api/tests/` and `gateway/compiler-1/tests/` — unit tests, no stack.
- `gateway/tests/` — live tests that need a running stack.
- `deployment-tests/system1..6-*.sh`, `full-lan-test.sh`, `firewall-kernel-test.sh` — read-only probes per machine.
- `dsc-recruit/apps/backend` pytest suites — planner, API, compiler pool.
- `dsc-recruit/apps/frontend` vitest suite — UI, execution runners, WASM validators.

---

## 12. Not implemented / deliberate limitations

- **TLS/HTTPS** — everything is plain HTTP on the LAN.
- **No Kubernetes / orchestration** — Docker Compose only.
- **Monitoring** is optional and not part of start-up.
- **Legacy runner** (`gateway/compiler-1/`, `EXECUTION_BACKEND=compiler1`) —
  kept working for the demo stack; Judge0 is the default and the tested path.
- **Screen recording / tab-switch telemetry / remote proctoring** — not
  implemented (see §6 for what *is* implemented).
- **Load testing** — `load-tests/` at the repo root is local tooling, not part
  of the deployment.
