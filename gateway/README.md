# Gateway Stack — Technical Reference

The Gateway is the machine candidates talk to. It runs three containers:

| Container | Image | Role |
|---|---|---|
| `traefik` | `traefik:v3.1` | front door on port 80 — forwards each request to the right place |
| `frontend` | built from `frontend/Dockerfile` | serves the website (React SPA built from `dsc-recruit/apps/frontend`) |
| `gateway-api` | built from `gateway-api/Dockerfile` | FastAPI helper: health/info, session tracking, code-execution proxy |

The application backend (**App-01**, from `dsc-recruit/apps/backend`) is **not** part of
this stack — it is a separate deployment (`app-1/`), found via `APP1_URL`. Code execution
is proxied to the active execution backend (Judge0 by default, legacy Compiler-1 via
`EXECUTION_BACKEND=compiler1`). See `DEPLOYMENT.md` for the multi-machine LAN setup and
`../README.md` for the beginner guide.

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
| `APP1_URL` | `http://host.docker.internal:8002` | App-01 address. LAN deployment: `http://<APP1_LAN_IP>:8002` |
| `TRAEFIK_HTTP_PORT` | `80` | front-door port published on the host |
| `TRAEFIK_DASHBOARD_PORT` | `8080` | Traefik dashboard port (dev convenience) |
| `APP_ENV` | `development` | shown by `/api/info` |
| `APP_VERSION` | — | shown by `/api/info` |
| `SESSION_TIMEOUT_SECONDS` | `300` | idle seconds before a session is marked inactive |
| `STALE_CHECK_INTERVAL_SECONDS` | `60` | how often the background checker runs |
| `EXECUTION_BACKEND` | `judge0` | `judge0` (System 3) or `compiler1` (legacy) |
| `JUDGE0_URL` | `http://judge0-server:2358` | Judge0 API (via the `system3` Docker network) |
| `JUDGE0_AUTH_TOKEN` | — | must equal `AUTHN_TOKEN` in `judge0/judge0.conf` |
| `JUDGE0_TIMEOUT` | `60.0` | Judge0 request timeout (seconds) |
| `COMPILER_URL` | `http://host.docker.internal:8001` | legacy Compiler-1 address (only if `EXECUTION_BACKEND=compiler1`) |
| `COMPILER_TIMEOUT` | `60.0` | Compiler-1 request timeout (seconds) |

The frontend build receives `VITE_API_URL="."` — the website always calls the Gateway
itself (same origin). It never talks to Supabase directly.

## Routing (Traefik)

Traefik's routing table is generated at container start (inline in
`docker-compose.yml`); static settings live in `traefik/traefik.yml`. Highest priority wins:

| Priority | Path | Destination |
|---|---|---|
| 10 | `/api/*` | `gateway-api` (internal :8000) |
| 5 | `/auth/*`, `/questions/*`, `/submission/*`, `/assessment/start`, `/assessment/current`, `/assessment/attempt/*`, `/coding/*`, `/admin/*` | App-01 (`APP1_URL`) |
| 1 | everything else | `frontend` (internal :8080) |

The `/auth`, `/assessment`, `/coding`, `/admin`, `/submission`, `/questions` prefixes are
the application backend's routers; the frontend is a single-page app and uses these same
paths for its API calls.

Traefik dashboard (dev only): http://localhost:8080 — HTTP → Routers shows the live table.

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

Open the firewall for the front door (Ubuntu example):

```bash
sudo ufw allow 80/tcp
```

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

Live tests (need a running stack + App-01/execution configured):

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

**/auth/* returns the website HTML instead of JSON**
App-01 is not reachable at `APP1_URL`. Check:
```bash
curl -s http://<APP1_HOST>:8002/      # from the gateway machine
docker compose logs traefik | tail    # "502 Bad Gateway" from app1-backend routes means App-01 is down
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
├── docker-compose.local.yml  ← one-machine demo (adds app-1 + compiler-1)
├── .env.example              ← configuration template (copy to .env; never commit .env)
├── DEPLOYMENT.md             ← multi-machine LAN guide
├── traefik/traefik.yml       ← Traefik static settings (entry points, providers, logs)
├── frontend/                 ← website container (builds dsc-recruit/apps/frontend)
│   ├── Dockerfile
│   └── nginx.conf
├── gateway-api/              ← FastAPI helper (health, sessions, /api/execute proxy)
│   ├── Dockerfile
│   ├── app/                  ← main.py, routers/, judge0_proxy.py, compiler_proxy.py
│   └── tests/
├── app-1/                    ← App-01 standalone deployment (application backend)
│   ├── Dockerfile            ← packages dsc-recruit/apps/backend as-is
│   ├── docker-compose.yml
│   └── .env.example
├── judge0/                   ← Judge0 execution service (System 3; default backend)
├── compiler-1/               ← legacy code runner (off by default)
├── compiler_client/          ← small Python client for the legacy runner
├── monitoring/               ← optional Grafana/Prometheus dashboards
└── tests/                    ← live integration tests (need a running stack)
```
