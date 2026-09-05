# How the deployment works (architecture)

Plain-language reference for the deployment in this repository. Everything here is read
from the actual files — compose files, Dockerfiles, Traefik rules, and application
routes. Nothing is aspirational: if it is not implemented, it says so.

---

## 1. The big picture

```
Candidate computers (browser only)
        │   http://<gateway-LAN-IP>/
        ▼
┌───────────────────────────────┐
│ GATEWAY machine               │
│  traefik      — the front door│
│  frontend     — website pages │
│  gateway-api  — helper API    │
└───────────────┬───────────────┘
                │ HTTP over the LAN
                ▼
┌───────────────────────────────┐     ┌──────────────────────────────┐
│ APP-01 machine                │     │ Supabase (cloud, Internet)   │
│  app-1 — application backend  │ ⇄── │ accounts, questions, results │
└───────────────────────────────┘     └──────────────────────────────┘
                │
                │ HTTP over the LAN (code execution only)
                ▼
┌───────────────────────────────┐
│ EXECUTION machine (Judge0)    │
│  judge0-server / worker /     │
│  db / redis                   │
└───────────────────────────────┘
```

- The **Gateway** is the only machine candidates talk to.
- The **Gateway → App-01** connection carries login, questions, submissions.
- The **Gateway → Judge0** connection carries only "run this code" requests.
- **App-01 → Supabase** needs Internet. Candidates do **not** need Internet.

Target six-machine design and status:

| Target machine | Status | Where in this repo |
|---|---|---|
| Machine 1 — Gateway | ✅ implemented | `gateway/docker-compose.yml` |
| Machine 2 — App-01 | ✅ implemented | `gateway/app-1/` |
| Machine 3 — App-02 | ❌ not implemented (future) | — |
| Machine 4 — Compiler-01 | ⚠️ legacy runner, off by default | `gateway/compiler-1/` |
| Machines 5–6 — Compiler-02/03 | ❌ not implemented (future) | — |
| Judge0 execution service | ✅ implemented, default | `gateway/judge0/` |

---

## 2. Every container, in one table

| Container | Machine | Image / built from | What it does in one line | Ports (host) |
|---|---|---|---|---|
| `traefik` | Gateway | `traefik:v3.1` | the front door; forwards each request to the right place | **80** → candidates, 8080 → dashboard |
| `frontend` | Gateway | built by `gateway/frontend/Dockerfile` | serves the website pages (built from the app repo's frontend) | none (internal 8080) |
| `gateway-api` | Gateway | built by `gateway/gateway-api/Dockerfile` | health, session bookkeeping, forwards code execution | none (internal 8000) |
| `app-1` | App-01 | built by `gateway/app-1/Dockerfile` | the application brain: login, questions, submissions; talks to Supabase | 8002 (Gateway only) |
| `judge0-server` | Execution | `judge0/judge0:1.13.1` | receives "run this code" requests | 2358, localhost-only (Gateway uses the Docker network) |
| `judge0-worker` | Execution | same image | runs code in isolated sandboxes | none |
| `judge0-db` | Execution | `postgres:16.2` | Judge0's own records | none |
| `judge0-redis` | Execution | `redis:7.2.4` | Judge0's work queue | none |
| `compiler-1` | (legacy) | built by `gateway/compiler-1/Dockerfile` | older simpler code runner; used only if `EXECUTION_BACKEND=compiler1` | 8001 (host, optional) |

All containers restart automatically after a reboot/crash (`restart: unless-stopped`).

## 3. The networks between containers

| Network | Who joins | Purpose |
|---|---|---|
| `gateway_net` | traefik, frontend, gateway-api (created automatically by the Gateway stack) | Gateway-internal traffic |
| `system3` | gateway-api + all judge0 containers (external; create once with `docker network create system3`) | Gateway ⇄ Judge0 |

App-01 is **not** on a shared Docker network with the Gateway. The Gateway reaches it
through the address in `APP1_URL` (gateway/.env):

- App-01 on its **own machine**: `APP1_URL=http://<APP-01-LAN-IP>:8002`
- App-01 on the **same machine** (easiest full setup): `APP1_URL=http://host.docker.internal:8002`
  (this special address means "the machine I am running on"; port 8002 is App-01's published port)

The same applies to the legacy compiler: `COMPILER_URL` points at it (LAN IP or
`host.docker.internal`). Judge0, however, is reached through the shared `system3`
Docker network, which only works when Judge0 runs **on the same machine as the
Gateway stack** — see section 11 for the multi-machine manual step.

## 4. Where each request goes (routing)

`traefik` reads its rules from `gateway/docker-compose.yml` and
`gateway/traefik/traefik.yml`. Priorities decide which rule wins:

| Path the browser asks for | Goes to | Why |
|---|---|---|
| `/api/...` | gateway-api (helper API) | priority 10 |
| `/auth/*`, `/questions/*`, `/submission/*`, `/assessment/start`, `/assessment/current`, `/assessment/attempt/*`, `/coding/*`, `/admin/*` | **app-1** (application backend) | priority 5 |
| everything else (`/`, `/login`, `/dashboard`, …) | frontend (website pages) | priority 1 |

These prefixes are exactly the application backend's routers (verified in
`dsc-recruit/apps/backend/routers/`): `auth.py` → `/auth`, `assessment.py` → `/assessment`,
`coding.py` → `/coding`, `admin.py` + `coding_admin.py` → `/admin`,
`submission.py` → `/submission`, `domains.py`/`questions.py` → `/questions/*`.

**Login request, step by step:**

```
1. Candidate opens http://<gateway-LAN-IP>/login        → traefik → frontend (page loads)
2. The page sends POST http://<gateway-LAN-IP>/auth/login → traefik → app-1 (via APP1_URL)
3. app-1 checks the password with Supabase (Internet)     → result back the same way
```

The website is built with its API address set to "." (same website, same address), so it
always calls the Gateway — never Supabase directly, never a hardcoded port.

## 5. Code execution ("Run" / "Submit")

```
browser → POST /api/execute → traefik → gateway-api → execution backend
```

The backend is chosen by `EXECUTION_BACKEND` in `gateway/.env`:

| Value | Backend | Status |
|---|---|---|
| `judge0` (**default**) | Judge0 on the execution machine, via the shared `system3` Docker network (`JUDGE0_URL=http://judge0-server:2358`, token auth) | implemented, verified |
| `compiler1` (legacy) | the old `compiler-1` service (`COMPILER_URL`, default `http://host.docker.internal:8001`) | still works; simpler, fewer features |

The result statuses (`accepted`, `wrong_answer`, `compilation_error`, `runtime_error`,
`time_limit_exceeded`, …) are identical for both backends. Judge0's own details are in
`gateway/judge0/README.md`.

## 6. How the containers get the application code

The deployment does not contain the application; it is **cloned inside** this repo as
`dsc-recruit/` and copied into container images at build time:

| Image | Dockerfile | What it copies from the app repo | Build context |
|---|---|---|---|
| `frontend` | `gateway/frontend/Dockerfile` | `dsc-recruit/apps/frontend/` (Node builds it, nginx serves it) | repo root |
| `app-1` | `gateway/app-1/Dockerfile` | `dsc-recruit/apps/backend/requirements-dev.txt` + `dsc-recruit/apps/backend/` | repo root |
| `gateway-api` | `gateway/gateway-api/Dockerfile` | — (deployment-only code, lives in the repo) | `gateway/gateway-api/` |
| `compiler-1` | `gateway/compiler-1/Dockerfile` | — (deployment-only code) | `gateway/` |

Because the first two copy from `dsc-recruit/...` at the **repo root**, the application
repo must be cloned inside this repo, named `dsc-recruit` (or the `COPY` lines must be
adjusted). The root `.dockerignore` keeps secrets (`.env` files, `judge0.conf`) and
irrelevant folders out of those builds.

## 7. The demo stack vs. the real stack

| | Demo (`docker-compose.local.yml`, one laptop) | Real (`docker-compose.yml` + standalone stacks) |
|---|---|---|
| Traefik routing | same path rules, but app-1/compiler-1 run as containers on the same Docker network | app-1 is found via `APP1_URL` (a LAN IP) |
| App-01 | container `app-1-local` | container `app-1` on its own machine, port 8002 |
| Execution | `compiler-1-local` (set `EXECUTION_BACKEND=compiler1`) | Judge0 via the `system3` Docker network |
| Front door port | 80 (`traefik-local`) | 80 (`traefik`) |

## 8. Ports summary

| Port | Machine | Bound to | Who may connect |
|---|---|---|---|
| 80 | Gateway | traefik | everyone on the LAN (candidates) |
| 8080 | Gateway | traefik dashboard | admin only (dev tool) |
| 8002 | App-01 | app-1 | Gateway machine only |
| 2358 | Execution | judge0-server | localhost only on that machine (Gateway connects via the Docker network; see section 11) |
| 8001 | (legacy) | compiler-1 | Gateway machine only, optional |
| 3001 | Gateway (optional) | Grafana monitoring | admin, LAN |

## 9. Environment variables

Full reference with defaults: `gateway/.env.example` (Gateway), `gateway/app-1/.env.example`
(App-01), `gateway/judge0/judge0.conf.example` (execution). The ones that matter day-to-day:

| Variable | File | Meaning |
|---|---|---|
| `APP1_URL` | gateway/.env | App-01's address (`http://<APP-01-LAN-IP>:8002`) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` | app-1/.env | Supabase keys — required for real logins |
| `EXECUTION_BACKEND` | gateway/.env | `judge0` (default) or `compiler1` (legacy) |
| `JUDGE0_URL`, `JUDGE0_AUTH_TOKEN` | gateway/.env | Judge0 address + shared token |
| `AUTHN_TOKEN` | judge0.conf | must equal `JUDGE0_AUTH_TOKEN` |
| `TRAEFIK_HTTP_PORT` | gateway/.env | front-door port (default 80) |
| `CORS_ORIGINS` | app-1/.env | website addresses the backend accepts calls from |

Never commit `.env` or `judge0.conf` — only the `.example` templates are in Git.

## 10. Tests that verify this deployment

- `gateway/gateway-api/tests/` — unit tests for the helper API (no stack needed).
- `gateway/compiler-1/tests/` — unit tests for the legacy runner (no stack needed).
- `gateway/tests/` — **live** tests that need a running stack
  (`test_app1_deployment.py`, `test_phase3.py`, `test_integration.py`, `test_lan_connectivity.py`).
  Run them from `gateway/` with the venv described in `gateway/README.md`.

## 11. Not implemented / manual steps

- **App-02 and Compiler-02/03** — the six-machine design is the target, but only the
  machines listed as implemented exist in this repository. Nothing to start for them yet.
- **Judge0 on a separate machine from the Gateway** — in the current configuration
  Judge0's API accepts connections only from its own machine (`127.0.0.1:2358` in
  `gateway/judge0/docker-compose.yml`), and the `system3` Docker network cannot span
  two machines. To put Judge0 on its own machine you must (a) change that binding to
  allow the Gateway machine (for example `"2358:2358"`), and (b) set
  `JUDGE0_URL=http://<judge0-LAN-IP>:2358` in `gateway/.env`. Judge0 is token-protected,
  but expose it only on a trusted LAN. Same-machine Gateway + Judge0 needs no changes.
- **TLS/HTTPS** — everything is plain HTTP on the LAN.
- **Monitoring** is optional (`gateway/monitoring/README.md`) and not part of start-up.
- **Load testing** — `load-tests/` at the repo root is untracked local tooling, not
  documented as part of the deployment.
