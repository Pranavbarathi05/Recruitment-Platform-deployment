# Recruitment Platform – Phase 1: Gateway Foundation

A minimal, fully Dockerized gateway stack. No external services, no auth, no monitoring – just
Traefik + a FastAPI gateway API + two dummy backends ready for LAN / laptop-to-laptop access.

```
Internet / LAN
      │
      ▼  :80
   Traefik  ────  /api/*  ──▶  gateway-api  (FastAPI :8000)
      │
      └──────────  /       ──▶  backend-1  ┐  (round-robin)
                                backend-2  ┘
```

---

## Prerequisites

| Requirement | Version tested |
|---|---|
| Docker Engine | 20.10 + |
| Docker Compose v2 | 2.20 + |
| Free host ports | 80, 8080 |

No Python, no Traefik, no other tools needed on the host.

---

## Quick start

```bash
# 1 – enter the project directory
cd gateway

# 2 – copy and review environment variables (edit if needed)
cp .env.example .env

# 3 – build images and start all services in the background
docker compose up --build -d

# 4 – watch logs (optional)
docker compose logs -f
```

---

## Shutdown

```bash
# Stop and remove containers (data is stateless, nothing is lost)
docker compose down

# Stop + remove images built by this project
docker compose down --rmi local
```

---

## Health test commands

```bash
# Gateway API health
curl -s http://localhost/api/health | python3 -m json.tool

# Gateway API info
curl -s http://localhost/api/info | python3 -m json.tool

# Backend pool (hit root path)
curl -s http://localhost/ | python3 -m json.tool

# Docker-level health status for every container
docker compose ps
```

Expected responses:

```jsonc
// GET /api/health
{ "status": "ok", "service": "gateway-api", "timestamp": "..." }

// GET /api/info
{ "service": "gateway-api", "version": "0.1.0", "environment": "development", ... }

// GET /
{ "message": "Hello from backend-1", "backend": "backend-1", ... }
```

---

## Verify load balancing

Send several requests and observe the `backend` field alternating:

```bash
for i in $(seq 1 10); do
  curl -s http://localhost/ | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['backend'])"
done
```

You should see output like:

```
backend-1
backend-2
backend-1
backend-2
...
```

Traefik uses round-robin by default. The `X-Served-By` response header also identifies the backend:

```bash
curl -sI http://localhost/ | grep -i x-served-by
```

---

## Traefik dashboard

Open **http://localhost:8080** in a browser.  
Navigate to **HTTP → Routers** and **HTTP → Services** to inspect routing rules and backend health.

---

## Finding your LAN IP

```bash
# Linux / macOS
ip route get 1 | awk '{print $7; exit}'
# or
hostname -I | awk '{print $1}'

# macOS (alternative)
ipconfig getifaddr en0
```

---

## Accessing from another machine on the same LAN

1. Find your host LAN IP using the command above (e.g. `192.168.1.42`).
2. Ensure port **80** is open in your firewall:

```bash
# Ubuntu / Debian (ufw)
sudo ufw allow 80/tcp

# RHEL / Fedora / CentOS (firewalld)
sudo firewall-cmd --permanent --add-port=80/tcp && sudo firewall-cmd --reload
```

3. From the other machine:

```bash
curl http://192.168.1.42/api/health
curl http://192.168.1.42/api/info
curl http://192.168.1.42/
```

---

## Troubleshooting

### Port 80 already in use

```bash
sudo lsof -i :80          # find the process
# Then either stop that process or change TRAEFIK_HTTP_PORT in .env:
#   TRAEFIK_HTTP_PORT=8888
```

### Containers not starting / unhealthy

```bash
docker compose ps                   # check status column
docker compose logs traefik         # Traefik errors
docker compose logs gateway-api     # FastAPI errors
docker compose logs backend-1       # backend errors
```

### Docker socket permission denied

```bash
# Add your user to the docker group (log out + back in required)
sudo usermod -aG docker $USER
```

### Firewall blocking LAN access

Check both the OS firewall **and** Docker's iptables rules:

```bash
sudo iptables -L -n | grep 80
```

If you use `ufw`, also ensure Docker's FORWARD rules aren't blocked:

```bash
sudo ufw status verbose
```

### Rebuild after code changes

```bash
docker compose up --build -d
```

### Reset everything

```bash
docker compose down --volumes --rmi local
```

---

## Project layout

```
gateway/
├── .env.example          # env var template (safe to commit)
├── docker-compose.yml    # orchestration
├── README.md             # this file
├── traefik/
│   └── traefik.yml       # Traefik static config
├── gateway-api/
│   ├── Dockerfile        # multi-stage Python build
│   ├── requirements.txt  # FastAPI + Uvicorn (pinned)
│   └── app/
│       └── main.py       # /api/health + /api/info endpoints
└── test-backend/
    ├── Dockerfile        # stdlib-only Python image
    └── server.py         # self-identifying HTTP server
```

---

## Design decisions (Phase 1)

| Decision | Rationale |
|---|---|
| Traefik v3.1 | Stable LTS, Docker-label routing avoids a separate config file per route |
| FastAPI / Uvicorn | Standard async Python API framework; zero boilerplate for JSON endpoints |
| Stdlib HTTP server for backends | No pip install; fastest possible image build; easy to swap later |
| Multi-stage build for gateway-api | Smaller runtime image; builder layer not shipped |
| Non-root users in all containers | Principle of least privilege; production-safe default |
| `exposedByDefault: false` in Traefik | Containers must opt-in with `traefik.enable=true`; safer default |
| No hardcoded IPs | All ports/env vars via `.env`; portable across any machine |

---

## Phase 2: Session / Control Plane

### New endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/session/start` | Create a new session; returns `session_id` |
| POST | `/api/session/heartbeat` | Refresh `last_seen` for an active session |
| POST | `/api/session/end` | Mark a session inactive (soft delete) |
| GET | `/api/session/{id}` | Retrieve a session by ID |
| GET | `/api/admin/sessions` | List all sessions (any status) |
| GET | `/api/admin/health` | Gateway uptime + session counts + node stubs |

### Running the unit tests (local, no Docker)

```bash
cd gateway/gateway-api

# Install dependencies (use a venv if preferred)
pip install -r requirements.txt

# Run all tests with verbose output
pytest -v
```

Expected output: **14 tests pass, 0 failures**.

### Session endpoint examples

```bash
# Start a session
SESSION=$(curl -s -X POST http://localhost/api/session/start | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session ID: $SESSION"

# Heartbeat
curl -s -X POST http://localhost/api/session/heartbeat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION\"}" | python3 -m json.tool

# Retrieve session
curl -s http://localhost/api/session/$SESSION | python3 -m json.tool

# End session
curl -s -X POST http://localhost/api/session/end \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION\"}" | python3 -m json.tool
```

### Admin endpoint examples

```bash
# List all sessions
curl -s http://localhost/api/admin/sessions | python3 -m json.tool

# System health (gateway uptime + session counts + 5 node stubs)
curl -s http://localhost/api/admin/health | python3 -m json.tool
```

### Phase 2 environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_TIMEOUT_SECONDS` | `300` | Idle seconds before a session is marked inactive |
| `STALE_CHECK_INTERVAL_SECONDS` | `60` | How often the background checker runs |

### Updated project layout

```
gateway/
├── .env.example
├── docker-compose.yml
├── README.md
├── traefik/
│   └── traefik.yml
├── gateway-api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py              # all endpoints + lifespan
│   │   ├── session.py           # SessionRegistry (in-memory)
│   │   ├── node_health.py       # NodeRegistry stubs
│   │   ├── stale_checker.py     # background daemon thread
│   │   └── routers/
│   │       ├── session.py       # /api/session/*
│   │       └── admin.py         # /api/admin/*
│   └── tests/
│       └── test_sessions.py     # 14 unit / integration tests
└── test-backend/
    ├── Dockerfile
    └── server.py
```

