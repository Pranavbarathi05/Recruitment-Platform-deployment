# Gateway Stack — Technical Reference

The Gateway is the machine candidates talk to. It runs three containers:

| Container | Image | Role |
|---|---|---|
| `traefik` | `traefik:v3.1` | front door on port 80 — forwards each request to the right place |
| `frontend` | built from `frontend/Dockerfile` | serves the website (React SPA built from `dsc-recruit/apps/frontend`) |
| `gateway-api` | built from `gateway-api/Dockerfile` | FastAPI helper: health/info, session tracking, code-execution proxy |

The application backend (**App-1 / App-2**, built from `dsc-recruit/apps/backend`) is
**not** part of this stack — they are separate deployments (`app-1/`, `app-2/`),
found via `APP1_URL` / `APP2_URL` in the app pool. Code execution is proxied to the
active execution backend (Judge0 compiler pool by default, legacy Compiler-1 via
`EXECUTION_BACKEND=compiler1`). See `DEPLOYMENT.md` for the multi-machine LAN setup,
`../DEPLOYMENT.md` for the six-system runbook and `../README.md` for the beginner
guide.

> Historical note: earlier phases of this project used dummy `backend-1`/`backend-2`
> services and a `test-backend/` folder to verify load balancing. Those are gone; the
> phase names survive only in some test-file names.

---

## Quick start

```bash
cd gateway
cp .env.example .env          # then edit .env (see Configuration below)
docker compose up -d --build
docker compose ps             # all three containers should be "healthy"
```

Point your browser at `http://localhost/` — the website should load.

The stack needs the external Docker network `system3` (shared with the Judge0 stack):

```bash
docker network create system3     # once per machine
```

### Configuration (`gateway/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `APP1_URL` / `APP2_URL` | `http://host.docker.internal:8002` / empty | app-backend pool members. LAN deployment: `http://<APPn_LAN_IP>:8002`. Empty = out of the pool |
| `APP1_CHALLENGE_URL` / `APP2_CHALLENGE_URL` | `http://host.docker.internal:8080` / empty | Hands-On challenge pool members (`http://<APPn_LAN_IP>:8080`) |
| `TRAEFIK_HTTP_PORT` | `80` | front-door port published on the host |
| `TRAEFIK_DASHBOARD_PORT` | `8080` | Traefik dashboard port (dev convenience — **not** the challenge) |
| `APP_ENV` | `development` | shown by `/api/info` |
| `APP_VERSION` | `0.3.0` | shown by `/api/info` |
| `SESSION_TIMEOUT_SECONDS` | `300` | idle seconds before a session is marked inactive |
| `STALE_CHECK_INTERVAL_SECONDS` | `60` | how often the background checker runs |
| `EXECUTION_BACKEND` | `judge0` | `judge0` (Compiler-1/2/3) or `compiler1` (legacy) |
| `COMPILER_1_URL` `COMPILER_2_URL` `COMPILER_3_URL` | empty | Judge0 nodes for `/api/execute` — round-robin + failover; all empty = use `JUDGE0_URL` |
| `JUDGE0_URL` | `http://judge0-server:2358` | single-node fallback (co-located node on the `system3` network) |
| `JUDGE0_AUTH_TOKEN` | — | must equal `AUTHN_TOKEN` in every node's `judge0/judge0.conf` |
| `JUDGE0_AUTH_HEADER` | `X-Judge0-Token` | header Judge0 checks |
| `JUDGE0_TIMEOUT` | `60.0` | Judge0 request timeout (seconds) |
| `COMPILER_URL` | `http://host.docker.internal:8001` | legacy Compiler-1 address (only if `EXECUTION_BACKEND=compiler1`) |
| `COMPILER_TIMEOUT` | `60.0` | Compiler-1 request timeout (seconds) |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | — | public Supabase credentials passed as **build args**; the SPA currently makes no direct Supabase calls (all data goes through the backend) |

The frontend build receives `VITE_API_URL="/_api"` — the website calls the Gateway at
the same origin under the `/_api` prefix, which Traefik strips before forwarding to
the app pool. It never talks to Supabase directly.

## Routing (Traefik)

Traefik's routing table is **rendered at container start** by the entrypoint in
`docker-compose.yml` (into `/etc/traefik/dynamic.yml`); static settings live in
`traefik/traefik.yml`. Highest priority wins:

| Priority | Path | Destination |
|---|---|---|
| 10 | `/api/*` | `gateway-api` (internal :8000) |
| 8 | `/challenge`, `/challenge/*` | challenge pool `[APP1_CHALLENGE_URL, APP2_CHALLENGE_URL]`, `StripPrefix /challenge` |
| 5 | `/_api/*` | app pool `[APP1_URL, APP2_URL]`, `StripPrefix /_api` |
| 1 | everything else | `frontend` (internal :8080) |

The app pool serves every backend route (`/auth/*`, `/assessment/*`, `/coding/*`,
`/admin/*`, `/questions/*`, `/submission/*`, …) because the `/_api` prefix is
removed before the request reaches the backend. Both pools are health-checked
(`/` for apps, `/health` for challenges, every 10 s) and unhealthy members are
taken out of rotation; an empty pool degrades to a single closed port (502 on
that route) rather than breaking the whole site.

The single-host demo stack (`docker-compose.local.yml`) still uses the older
direct-prefix rules and builds the frontend with `VITE_API_URL="."` — see that
file's header comment.

Traefik dashboard (dev only): http://localhost:8080 — HTTP → Routers shows the live
table (or open it via the `traefik.localhost` host rule).

## Gateway API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness (used by the Docker healthcheck) |
| GET | `/api/info` | version / environment / uptime |
| POST | `/api/session/start` | create a candidate session → `session_id` |
| POST | `/api/session/heartbeat` | refresh a session's `last_seen` |
| POST | `/api/session/end` | mark a session inactive |
| GET | `/api/session/{id}` | read one session |
| GET | `/api/admin/sessions` | list all sessions |
| GET | `/api/admin/health` | gateway uptime + session counts |
| POST | `/api/execute` | run code via the active execution backend |
| GET | `/api/execute/health` | is the execution backend reachable |
| GET | `/api/execute/languages` | which languages the backend offers |

Example:

```bash
curl -s http://localhost/api/health
curl -s http://localhost/api/info

# execute Python via Judge0 (works as soon as the execution stack is up)
curl -s -X POST http://localhost/api/execute \
  -H "Content-Type: application/json" \
  -d '{"language":"python","source_code":"print(42)","test_cases":[{"input":"","expected_output":"42"}]}'
```

`/api/execute` request/response contract (status values such as `accepted`,
`wrong_answer`, `compilation_error`, `runtime_error`, `time_limit_exceeded`) is identical
for both backends — see `DEPLOYMENT.md` → API contract.

## Single-machine demo stack

`docker-compose.local.yml` runs **everything on one machine** (traefik + frontend +
gateway-api + app-1 + compiler-1 as containers on one Docker network):

```bash
cd gateway
docker compose -f docker-compose.local.yml up -d --build
curl -s http://localhost/               # website
curl -s http://localhost/api/health     # gateway-api
docker compose -f docker-compose.local.yml \
  exec compiler-1 python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"
                                        # compiler-1 health (Docker-network internal; no host port in the demo)
docker compose -f docker-compose.local.yml down
```

Note: the demo stack has no Judge0; set `EXECUTION_BACKEND=compiler1` in `.env` so
code execution uses the bundled compiler-1.

## LAN access from other machines

```bash
hostname -I | awk '{print $1}'    # the machine's LAN IP, e.g. 192.168.1.42
```

Published ports are reachable by default — Docker inserts its own iptables rules
and UFW/INPUT rules do not apply to them (see `DEPLOYMENT.md` → Firewall). Only a
upstream firewall/switch policy would need an explicit allow for port 80.

Then from any LAN machine: `curl http://<LAN-IP>/api/health` and open
`http://<LAN-IP>/` in a browser.

## Tests

Unit tests (no running stack needed) — gateway-api and compiler-1 ship their own
dependencies and test setups:

```bash
cd gateway/gateway-api
python3 -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements.txt
pytest -v
```

Same pattern for `gateway/compiler-1` (its `requirements.txt` includes pytest).

Live tests (need a running stack + an App machine and the execution backend configured):

```bash
cd gateway
python3 -m venv .venv-integration && source .venv-integration/bin/activate
pip install -r requirements-integration.txt
pytest tests -v          # test_app1_deployment, test_phase3, test_integration, test_lan_connectivity
```

These test files still carry the old "Phase 3/4/6" names in places; they test the
current endpoints.

## Troubleshooting (technical)

**Port 80 already in use**
```bash
sudo lsof -i :80            # find the process, or change TRAEFIK_HTTP_PORT in .env
```

**"network system3 declared as external, but could not be found"**
```bash
docker network create system3
```

**/_api/auth/* returns the website HTML instead of JSON**
Either the `/_api` route lost its backend or an app pool member is down.
Check:
```bash
curl -s http://<APP_IP>:8002/          # from the gateway machine — each pool member
curl -s -X POST http://localhost/_api/auth/login -H 'Content-Type: application/json' -d '{}'
                                       # JSON 422 = routing OK; HTML = app pool empty/down
docker compose logs traefik | tail    # "502 Bad Gateway" on api-backend routes = member down
```

**Container unhealthy**
```bash
docker compose ps
docker compose logs gateway-api --tail 50
docker compose logs traefik --tail 50
```

**Docker permission denied**
```bash
sudo usermod -aG docker $USER   # then log out and back in
```

**Judge0 errors from /api/execute** — see `judge0/README.md` (token mismatch and
cgroup-v2 notes live there).

## Project layout

```
gateway/
├── docker-compose.yml        ← the Gateway machine stack (traefik + frontend + gateway-api)
├── docker-compose.local.yml  ← one-machine demo (adds app-1 + compiler-1; older routing)
├── .env.example              ← configuration template (copy to .env; never commit .env)
├── DEPLOYMENT.md             ← multi-machine LAN reference
├── dockerdemoup.sh           ← start any/all six stacks on one machine (co-located test)
├── scripts/                  ← deploy/down per system, deploy-compiler, port guard
├── traefik/traefik.yml       ← Traefik static settings (entry points, providers, logs)
├── frontend/                 ← website container (builds dsc-recruit/apps/frontend)
│   ├── Dockerfile
│   └── nginx.conf
├── gateway-api/              ← FastAPI helper (health, sessions, /api/execute proxy)
│   ├── Dockerfile
│   ├── app/                  ← main.py, routers/, judge0_proxy.py, judge0_pool.py, …
│   └── tests/
├── app-1/                    ← App-1 deployment (application backend + challenge-1)
│   ├── Dockerfile / Dockerfile.challenge
│   ├── docker-compose.yml
│   ├── README.md
│   └── .env.example
├── app-2/                    ← App-2 deployment (same backend + challenge-2)
├── judge0/                   ← Judge0 execution nodes (Compiler-1/2/3; default backend)
├── compiler-1/               ← legacy code runner (off by default)
├── compiler_client/          ← small Python client for the legacy runner
├── monitoring/               ← optional Grafana/Prometheus dashboards
└── tests/                    ← live integration tests (need a running stack)
```
