# LAN Deployment Guide — multi-machine setup

This guide is for the real deployment: separate machines on the college network.
Single-laptop demo: see the root `README.md` (section 6). Technical reference for the
Gateway stack: `README.md` in this folder.

## What runs where

```
Candidate computers (browser only)
        │  http://<GATEWAY_LAN_IP>/
        ▼
GATEWAY machine                APP-01 machine              EXECUTION machine (Judge0)
  traefik      :80    ───────▶  app-1  :8002 (internal)  ⇄  Supabase (Internet)
  frontend            │  LAN   ▲                            ▲
  gateway-api         │        │ APP1_URL                   │ JUDGE0_URL + shared
  (sessions, /api/*)  └────────┘                            ▼ token (system3 network)
                        code execution ──────────▶  judge0-server :2358 (+ worker/db/redis)
```

| Machine | Runs | Repo folder | Start command |
|---|---|---|---|
| Gateway | traefik + frontend + gateway-api | `gateway/` | `docker compose up -d --build` |
| App-01 | the application backend (dsc-recruit) | `gateway/app-1/` | `docker compose up -d --build` |
| Execution | Judge0 (code execution) | `gateway/judge0/` | `docker compose up -d` |

Not yet implemented: **App-02** and **Compiler-02/03**. Only the machines above exist in
this repository.

## Prerequisites (every machine)

- Docker Engine 20.10+ and the Compose plugin (v2.20+): `docker --version && docker compose version`
- Ports: Gateway frees **80** (and 8080 if you want the dashboard); App-01 frees **8002**;
  execution machine: nothing extra (Judge0's port stays local to that machine).
- The application repository cloned **inside** the deployment repository as `dsc-recruit/`
  on the machines that build images (Gateway and App-01). See the root `README.md`.
- Every machine, once: `docker network create system3`

> Judge0 must currently run **on the same machine as the Gateway stack** — the shared
> `system3` Docker network does not span machines, and Judge0's API is bound to its own
> machine's localhost. See ARCHITECTURE.md §11 for the manual changes needed to separate
> them. App-01 can be anywhere on the LAN.

## Machine 1 — Gateway

### Environment

```bash
cd gateway
cp .env.example .env
```

Edit `.env`:

```bash
APP1_URL=http://<APP1_LAN_IP>:8002      # App-01's LAN IP, port 8002
JUDGE0_AUTH_TOKEN=<same as AUTHN_TOKEN in judge0/judge0.conf>
# TRAEFIK_HTTP_PORT=80                  # change only if port 80 is taken
```

### Start and verify

```bash
cd gateway
docker network create system3                 # once
docker compose up -d --build
docker compose ps                             # wait for healthy
curl -s http://localhost/api/health           # {"status":"ok",...}
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/    # 200
```

Find the LAN IP candidates will use:

```bash
hostname -I | awk '{print $1}'        # e.g. 192.168.1.10
```

## Machine 2 — App-01

### Environment

```bash
cd gateway/app-1
cp .env.example .env
```

Edit `.env` with the real Supabase credentials:

```bash
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
SUPABASE_JWT_SECRET=<your-jwt-secret>
# CORS_ORIGINS default is fine: through the Gateway every browser call is
# same-origin, so CORS is not involved in the LAN deployment.
```

### Start and verify

```bash
cd gateway/app-1
docker compose up -d --build
curl -s http://localhost:8002/     # {"status":"Healthy","message":"API is working"}
hostname -I | awk '{print $1}'     # its LAN IP → goes into gateway/.env as APP1_URL
```

The Gateway reaches App-01 only on **port 8002** (map: host 8002 → container 8000).

## Machine 3 — Execution (Judge0)

Judge0 runs candidate code in isolated sandboxes. Its details, memory/cgroup notes and
Java tuning live in `judge0/README.md` — read it before changing `judge0.conf`.

### Environment

```bash
cd gateway/judge0
cp judge0.conf.example judge0.conf
# replace every change-me value with long random strings, e.g. `openssl rand -hex 24`
# AUTHN_TOKEN here MUST equal JUDGE0_AUTH_TOKEN in gateway/.env
```

### Start and verify

```bash
cd gateway/judge0
docker network create system3        # once (same network as gateway-api)
docker compose up -d
docker compose ps                    # all four judge0-* containers healthy
```

Verify from the Gateway (default backend is Judge0):

```bash
curl -s http://localhost/api/execute/health
curl -s http://localhost/api/execute/languages
```

## Firewall

**Gateway:** allow inbound 80 (and 8080 if the dashboard is wanted):
```bash
sudo ufw allow 80/tcp        # (Ubuntu/Debian) or firewalld equivalent on RHEL
```
**App-01:** allow inbound 8002 **only from the Gateway's IP**:
```bash
sudo ufw allow from <GATEWAY_IP> to any port 8002 proto tcp
```
**Execution machine:** no inbound ports — the Gateway reaches Judge0 over the shared
Docker network (same host), and its API port is bound to that machine's localhost only.

## Request flows (what to expect)

**Application flow:** `browser → GET /login → traefik → frontend` (website pages)
**Login flow:** `browser → POST /auth/login → traefik → APP1_URL (app-1) → Supabase → back`
**Execution flow:** `browser → POST /api/execute → traefik → gateway-api → Judge0 → back`

The full path/prefix table is in `README.md` → Routing.

## Health checks

```bash
# Gateway machine
cd gateway && docker compose ps
curl -s http://localhost/api/health
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/login

# App-01 machine
cd gateway/app-1 && docker compose ps
curl -s http://localhost:8002/

# Execution machine
cd gateway/judge0 && docker compose ps          # all four judge0-* healthy

# From the Gateway: end-to-end execution health
curl -s http://localhost/api/execute/health
```

Full pre-drive checklist: root `README.md` → section 9.

## API contract — POST /api/execute

Identical regardless of execution backend.

**Request:**
```json
{
  "language": "python",
  "source_code": "print('hello')",
  "test_cases": [{"input": "", "expected_output": "hello"}],
  "limits": {"time_limit_seconds": 10.0, "memory_limit_mb": 256, "max_output_bytes": 65536},
  "session_id": "optional-session-id",
  "attempt_id": "optional-attempt-id",
  "question_id": "optional-question-id"
}
```

**Response (200):**
```json
{
  "status": "accepted",
  "language": "python",
  "execution_time_ms": 123,
  "tests": [{"test_case": 1, "passed": true, "execution_time_ms": 20, "stdout": "hello", "stderr": ""}],
  "total_tests": 1, "passed_tests": 1,
  "session_id": "optional-session-id",
  "attempt_id": "optional-attempt-id",
  "question_id": "optional-question-id"
}
```

**Status values:** `accepted`, `wrong_answer`, `compilation_error`, `runtime_error`,
`time_limit_exceeded`, `invalid_language`, `capacity_exceeded` (→ HTTP 503),
`compiler_unavailable` (→ HTTP 502), `internal_error`.

**Languages:** `python`, `c`, `cpp`, `java`, `sql` (SQLite).

## Environment variable reference (gateway/.env)

| Variable | Default | Description |
|---|---|---|
| `APP1_URL` | `http://host.docker.internal:8002` | App-01 base URL |
| `TRAEFIK_HTTP_PORT` | `80` | front-door HTTP port |
| `TRAEFIK_DASHBOARD_PORT` | `8080` | Traefik dashboard (dev) |
| `APP_ENV` / `APP_VERSION` | `development` / — | shown by /api/info |
| `SESSION_TIMEOUT_SECONDS` | `300` | idle seconds before a session goes inactive |
| `STALE_CHECK_INTERVAL_SECONDS` | `60` | stale-checker wake-up interval |
| `EXECUTION_BACKEND` | `judge0` | `judge0` or `compiler1` (legacy) |
| `JUDGE0_URL` | `http://judge0-server:2358` | Judge0 API (system3 network) |
| `JUDGE0_TIMEOUT` | `60.0` | Judge0 request timeout (s) |
| `JUDGE0_AUTH_TOKEN` | — | must equal `AUTHN_TOKEN` in judge0.conf |
| `JUDGE0_AUTH_HEADER` | `X-Judge0-Token` | header Judge0 checks |
| `COMPILER_URL` | `http://host.docker.internal:8001` | legacy Compiler-1 (only for EXECUTION_BACKEND=compiler1) |
| `COMPILER_TIMEOUT` | `60.0` | Compiler-1 timeout (s) |

App-01 variables: see `app-1/.env.example`. Judge0 variables: see `judge0/judge0.conf.example`.

## Stopping and updating

```bash
# stop a machine's stack (from its folder)
docker compose down

# update the deployment + application repos (repo root), then rebuild per machine
git pull && (cd dsc-recruit && git pull)
cd gateway && docker compose up -d --build            # Gateway machine
cd ../gateway/app-1 && docker compose up -d --build   # App-01 machine (after backend changes)
# judge0: only `docker compose up -d` needed after judge0.conf changes
```

## Troubleshooting

**502 from /auth/*, /questions/*, /coding/* (App-01 unreachable)**
```bash
docker ps | grep app-1                 # on the App-01 machine
curl http://<APP1_IP>:8002/            # from the Gateway machine — is it reachable?
grep APP1_URL gateway/.env             # is the IP/port right?
docker compose logs traefik | tail     # on the Gateway
```

**Execution returns compiler_unavailable (HTTP 502)**
```bash
docker compose -f gateway/judge0/docker-compose.yml ps    # judge0 containers healthy?
curl -s http://localhost/api/execute/health               # from the Gateway
# token mismatch shows up as Judge0 auth errors in gateway-api logs:
docker compose logs gateway-api | tail
```

**Connection refused between machines**
```bash
nc -zv <APP1_IP> 8002                  # from the Gateway — firewall test
sudo ufw allow from <GATEWAY_IP> to any port 8002 proto tcp   # on App-01
```

**Container keeps stopping**
```bash
docker compose logs <service> --tail 50
```

**SQL note:** with Judge0, SQL runs in SQLite (Judge0 language id 82). The legacy
compiler-1 also sandboxes SQL to SQLite.

## Known limitations

1. **No TLS.** Plain HTTP on the LAN; acceptable for the recruitment scenario.
2. **Judge0 co-located with the Gateway.** Judge0's API is localhost-bound and the
   `system3` network is host-local; separating them needs the manual changes in
   ARCHITECTURE.md §11.
3. **No authentication on the legacy Compiler-1 API.** Off by default; fine on a trusted
   LAN. Judge0, the default, is token-protected.
4. **Single execution backend instance.** No Compiler-02/03 yet.
5. **Supabase requires Internet** on the App-01 machine (keys + network reachable).
6. **App-02** is not implemented.

---

*This document describes the repository as it is. Older versions described a two-backend
load-balancing demo (`backend-1`/`backend-2`) and a `System 2` compiler host — those
descriptions are obsolete.*
