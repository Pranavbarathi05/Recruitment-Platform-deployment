# Developer setup

How to run the platform for development. Only commands that exist in this
repository are listed.

## 1. Prerequisites

- **Python 3.11+** (the checked-in backend venv runs 3.13)
- **Node.js 18+** (Vite 7, Vitest)
- **Docker + Compose v2** (containerised runs and any compiler node)
- **A Supabase project** (hosted Postgres + Auth) — the platform has no local
  database; both apps talk to one shared project over the Internet
- Git

Repository layout (the app repo lives **inside** the deployment repo):

```
Platform-deployment/
├── gateway/            # compose stacks, Traefik, gateway-api, Judge0, scripts
├── docs/               # this documentation
├── deployment-tests/   # live probe scripts
└── dsc-recruit/        # the application repo (React + FastAPI monorepo)
    └── apps/
        ├── backend/    # FastAPI, routers, planner, harness, migrations
        ├── frontend/   # React 19 + Vite + Tailwind v4
        ├── challenge_server/  # SQL-injection Hands-On server (packaged into images)
        └── network-monitor-agent/  # optional loopback ICMP helper (DEV)
```

## 2. Environment variables

### Backend — `dsc-recruit/apps/backend/.env` (from `.env.example`)

| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` | the shared Supabase project (service-role key also derives the assessment-capability signing key) |
| `CORS_ORIGINS` | default `http://localhost:5173` |
| `HOST` / `PORT` | default `0.0.0.0:8000` |
| `JUDGE0_BASE_URL` | default `http://localhost:2358` — single-node fallback when no `COMPILER_1..3_URL` is set |
| `COMPILER_1_URL` / `COMPILER_2_URL` / `COMPILER_3_URL` | optional compiler pool (round-robin + failover) |
| `JUDGE0_AUTH_TOKEN`, `JUDGE0_AUTH_HEADER` | token shared with the node's `judge0.conf` (default header `X-Judge0-Token`) |
| `JUDGE0_POLL_INTERVAL`, `JUDGE0_MAX_POLL_TIME`, `JUDGE0_MAX_FILE_SIZE_KB`, `JUDGE0_JAVA_MEMORY_LIMIT_KB` | execution tuning (defaults in `services/compiler.py`) |

### Frontend — `dsc-recruit/apps/frontend/.env.local`

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | default `http://localhost:8000` — the backend the SPA calls |
| `VITE_NETWORK_MONITOR_URL` | default `http://127.0.0.1:8765` — the network-monitor helper |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | public credentials, only if a code path needs them |

Container builds set `VITE_API_URL="/_api"` (production gateway stack) or `"."`
(demo stack) — see `gateway/docker-compose.yml` / `docker-compose.local.yml`.

**Never commit `.env`, `.env.local`, `judge0.conf`** — only the `.example`
templates are tracked.

## 3. Dependencies

```bash
# backend
cd dsc-recruit/apps/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# frontend (also copies Pyodide + DuckDB-WASM assets via postinstall)
cd dsc-recruit/apps/frontend
npm install
```

`npm install` runs `scripts/copy-pyodide.mjs` and `scripts/copy-duckdb.mjs`
(`postinstall`/`predev`/`prebuild`), which copy the ~14 MB WASM runtimes from
`node_modules` into `public/` so Run works offline — no CDN involved.

## 4. Database setup / migrations

Schema lives in `dsc-recruit/apps/backend/migrations/001…025_*.sql`. They are
plain, idempotent SQL files applied **in order** — there is no migration
runner in this repository (a pinned `alembic` package in
`requirements-dev.txt` is a leftover; no `alembic.ini` or versions directory
exists).

```bash
# per-file, in the Supabase SQL Editor (Dashboard → SQL Editor) — the
# documented path in migration 001's header — or with psql using the
# connection string from your project's Database → Connect dialog:
psql <connection-string> -f migrations/001_initial_schema.sql   # …continue in order
```

Each file documents its own safety notes (additive, rerun-safe, data-only).
Never edit a migration that has been applied — add a new numbered file.

## 5. Running locally (DEV)

```bash
# 1. backend (from apps/backend, venv active, .env present)
uvicorn main:app --reload            # http://localhost:8000  (or: python main.py)

# 2. frontend (from apps/frontend)
npm run dev                          # http://localhost:5173

# 3. compiler node (optional, needed for server-side Run/Submit of C/C++/Java
#    and for any server-side execution): start the Judge0 stack so
#    JUDGE0_BASE_URL=http://localhost:2358 resolves, with the token matching
#    JUDGE0_AUTH_TOKEN — see gateway/judge0/README.md
```

Python 3 **Run** works without any compiler node (it executes in the browser
via Pyodide). Candidate **Submit** always needs a compiler node.

Optional: the loopback network-monitor helper

```bash
dsc-recruit/apps/backend/.venv/bin/python \
  dsc-recruit/apps/network-monitor-agent/agent.py        # port 8765
```

## 6. Running with Docker

```bash
# single-host demo (all-in-one, older direct-prefix routing, legacy runner):
cd gateway && docker compose -f docker-compose.local.yml up -d --build

# production-shaped stacks on one machine (co-located test):
./gateway/dockerdemoup.sh all        # or gateway/app1/app2/compiler1/compiler2/compiler3
./gateway/dockerdemodown.sh all
```

Both need `docker network create system3` first and configured `.env` files
(root `README.md` §5). Building images requires the `dsc-recruit/` checkout
inside the repo root.

## 7. Tests

See [`TESTING.md`](TESTING.md). Quick versions:

```bash
# backend (846 tests)
cd dsc-recruit/apps/backend
.venv/bin/python -m pytest test_main.py test_assessment_planner.py \
    test_assessment_planning.py test_module_config_admin.py utils/ -q

# frontend (vitest)
cd dsc-recruit/apps/frontend && npm test

# network-monitor helper
cd dsc-recruit/apps/network-monitor-agent && ../backend/.venv/bin/python -m pytest test_agent.py -q
```

## 8. Conventions worth knowing

- **No TypeScript** in the frontend — PropTypes only; tests are Vitest +
  Testing Library (`*.test.jsx` next to the component).
- The assessment planner (`services/assessment_planner.py`) is deliberately
  **pure**: no DB access, no writes, no FastAPI imports — callers resolve rows
  and pass them in.
- Cookie-only auth: never add `Authorization: Bearer` handling for the SPA.
- Frontend API calls always go through `import.meta.env.VITE_API_URL`.
- Keep docs in this folder in sync when you change routing, endpoints or
  planning rules — documentation changes land in the same PR as the code.
