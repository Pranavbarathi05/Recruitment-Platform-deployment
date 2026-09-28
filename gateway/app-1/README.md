# App-01 — Application Backend Container

Standalone Docker deployment for the existing **dsc-recruit** backend
(`dsc-recruit/apps/backend`). The application code is packaged **as-is** — this
deployment layer only wraps it in a container.

The application repository must be cloned **inside the deployment repository** as
`dsc-recruit/` (see the root `README.md`) — the Dockerfile copies
`dsc-recruit/apps/backend/` from the build context (the repository root).

## What it does

```
App-01 machine
┌──────────────────────────────────┐
│  app-1 container                 │
│  FastAPI backend (dsc-recruit)   │
│  8000 inside the container       │
│  → published on host port 8002   │
│  → talks to Supabase (Internet)  │
│                                  │
│  challenge-1 container           │
│  SQL-injection Hands-On server   │
│  → published on host port 8080   │
│  → isolated (own SQLite seed,    │
│    no credentials, no Internet)  │
└──────────────────────────────────┘
```

App-01 runs independently. It does **not** require the Gateway, Traefik, the execution
service, or any other service to be up first. The Gateway reaches it via `APP1_URL`
(gateway/.env) on port 8002; candidates never talk to App-01 directly — only through
the Gateway's front door.

## Prerequisites

- Docker Engine 20.10+ and Docker Compose v2.20+
- Free host port: **8002** (or configured via `APP1_HOST_PORT`)
- Internet access (to pull base images on first build, and at runtime for Supabase)

## Quick start

```bash
cd gateway/app-1

# Copy and configure environment variables
cp .env.example .env
# Edit .env with real Supabase credentials (required for real logins)

# Build and start
docker compose up -d --build

# Verify health
curl -s http://localhost:8002/
# Expected: {"status":"Healthy","message":"API is working"}

# Watch logs / stop
docker compose logs -f
docker compose down
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SUPABASE_URL` | Yes | — | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | — | Supabase public anon key (used server-side for auth) |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | — | Supabase service role key |
| `SUPABASE_JWT_SECRET` | Yes | — | Supabase JWT secret |
| `CORS_ORIGINS` | No | `http://localhost:80,http://localhost:5173` | Allowed CORS origins |
| `APP1_HOST_PORT` | No | `8002` | Host-side API port |
| `APP1_CHALLENGE_PORT` | No | `8080` | Host-side challenge port |
| `APP1_API_BIND` | No | `0.0.0.0` | Interface the API port binds to |
| `COMPILER_1_URL` / `COMPILER_2_URL` / `COMPILER_3_URL` | No | empty | Judge0 pool for coding Run/Submit (round-robin + failover) |
| `JUDGE0_BASE_URL` | No | `http://judge0-server:2358` | single-node fallback when the pool is empty |
| `JUDGE0_AUTH_TOKEN` | No | empty | must equal `AUTHN_TOKEN` in every node's `judge0.conf` |
| `JUDGE0_AUTH_HEADER` | No | `X-Judge0-Token` | header Judge0 checks |
| `JUDGE0_JAVA_MEMORY_LIMIT_KB` | No | `2097152` | address-space floor for Java submissions |

Never commit the real `.env` — only `.env.example` is in Git.

## Networking

- **Container port:** 8000 (uvicorn inside the container)
- **Host port:** 8002 (mapped via `ports:` in docker-compose.yml)

### Where the Gateway fits

```
browser → Gateway (traefik :80) → APP1_URL → this machine :8002 → app-1 container
```

The Gateway routes the `/_api/*` prefix (stripped) to the App pool — which serves
every backend route (`/auth/*`, `/assessment/*`, `/coding/*`, `/admin/*`,
`/questions/*`, `/submission/*`, …) — and `/challenge/*` (stripped) to the
challenge pool. App-1 is reached **only** on ports 8002 (API) and 8080
(challenge-1).

### Firewall

Docker-published ports are **not** filtered by UFW/INPUT rules (they are DNAT'ed
in PREROUTING and forwarded through the FORWARD chain). Restrict ports 8002 and
8080 to the Gateway machine with the provided DOCKER-USER guard instead:

```bash
sudo ../scripts/docker-port-guard.sh --ports "8002 8080" --gateway-ip <GATEWAY_IP>
sudo iptables -S DOCKER-USER      # verify
```

Persist it with `../scripts/docker-port-guard.service` (see the root
`DEPLOYMENT.md` §6). No other ports need to be open.

## Health check

App-01 uses the application's **real** health endpoint:

```
GET /
→ {"status": "Healthy", "message": "API is working"}
```

Docker healthcheck polls this every 15 seconds.

## Security measures

- ✅ Runs as non-root user (`appuser`)
- ✅ No Docker socket mounted, no privileged mode, no host networking
- ✅ No secrets in Dockerfile or docker-compose.yml (they come from `.env`)
- ✅ Only port 8002 exposed
- ✅ Official Python slim base image, multi-stage build
- ✅ `restart: unless-stopped` for resilience

### Remaining limitations

- ⚠️ Supabase credentials are passed as environment variables (visible in `docker inspect`)
- ⚠️ No TLS (plain HTTP) — acceptable for the LAN deployment
- ⚠️ No authentication on the health endpoint
- ⚠️ Not production-hardened (no resource limits, no seccomp profiles)

## Supported endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | No | Health check |
| GET | `/questions/domains`, `/questions/domains/{id}` | No | Catalogue of active domains |
| GET/POST | `/auth/*` (`csrf`, `signup`, `login`, `logout`, `me`, `assessment-access`) | — | Cookie-based authentication (Supabase Auth) |
| GET/POST | `/assessment/*` (`available-domains`, `start`, `current`, `attempt/…`) | Yes (candidate) | Assessment lifecycle |
| GET/POST | `/coding/attempt/{id}/*` (`problems`, `draft`, `run`, `submit`) | Yes (candidate) | Coding section |
| GET/POST/PUT/DELETE | `/admin/*` | Yes (admin) | Domains, MCQs, config, results, remarks, resets |
| * | `/admin/coding/*`, `/admin/descriptive-questions/*`, `/admin/hands-on-questions/*`, `/admin/assessment/modules/*` | Yes (admin) | Content authoring |
| POST | `/submission/` | Yes | Legacy submission endpoint (still mounted) |

Full endpoint reference: [`../../docs/API.md`](../../docs/API.md). Most endpoints
require the `dsc_session` cookie; admin endpoints additionally require
`profiles.is_admin`. The health check and domain catalogue work without credentials.

## Testing

```bash
# 1. Config validation
docker compose config

# 2. Build
docker compose build

# 3. Start
docker compose up -d

# 4. Container status
docker compose ps

# 5. Health endpoint
curl -s http://localhost:8002/

# 6. Application logs
docker compose logs app-1

# 7. Restart behavior
docker compose restart app-1
curl -s http://localhost:8002/

# 8. Stop
docker compose down
```

## LAN deployment (separate machine)

On the **App-01 machine** (repository layout per the root README):

```bash
# 1. Configure App-01 (the repos are already cloned inside each other)
cd Recruitment-Platform-deployment/gateway/app-1
cp .env.example .env
# Edit .env with real Supabase credentials

# 2. Build and start
docker compose up -d --build

# 3. Verify health
curl -s http://localhost:8002/
# Expected: {"status":"Healthy","message":"API is working"}

# 4. Find the LAN IP for the Gateway configuration
hostname -I | awk '{print $1}'
# Example output: 192.168.1.23  → goes into gateway/.env as APP1_URL=http://192.168.1.23:8002
```

On the **Gateway machine**:

```bash
cd Recruitment-Platform-deployment/gateway
# edit .env: APP1_URL=http://<APP1_LAN_IP>:8002
docker compose up -d

# Verify routing — should return App-01's health response:
curl -s http://localhost/auth/me
# or watch the traefik logs while a browser logs in
```

## LAN deployment checklist

- [ ] Docker and Docker Compose installed on both machines
- [ ] `.env` file configured with real Supabase credentials
- [ ] Container builds and starts successfully
- [ ] Health endpoint returns 200
- [ ] Port 8002 is accessible from the Gateway machine (firewall)
- [ ] `APP1_URL` on the Gateway machine points at this machine's LAN IP
