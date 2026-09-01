# App 1 — dsc-recruit Backend Deployment

Standalone Docker deployment for the existing dsc-recruit backend.

## Architecture

```
App 1 System
┌──────────────────────────────────┐
│  App 1 container                 │
│  FastAPI backend                 │
│  Port 8000 (internal)            │
│  → Host port 8002                │
└──────────────────────────────────┘
```

App 1 runs independently. It does NOT require the Gateway, Traefik, Compiler, or any other service.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.20+
- Free host port: **8002** (or configured via `APP1_HOST_PORT`)

## Quick Start

```bash
cd gateway/app-1

# Copy and configure environment variables
cp .env.example .env
# Edit .env with real Supabase credentials

# Build and start
docker compose up -d --build

# Verify health
curl -s http://localhost:8002/

# Watch logs
docker compose logs -f

# Stop
docker compose down
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SUPABASE_URL` | Yes | — | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | — | Supabase service role key |
| `SUPABASE_JWT_SECRET` | Yes | — | Supabase JWT secret |
| `CORS_ORIGINS` | No | `http://localhost:80,http://localhost:5173` | Allowed CORS origins |
| `APP1_HOST_PORT` | No | `8002` | Host-side port |

## Networking

### Container Port

- **Internal:** 8000 (uvicorn inside container)
- **Host:** 8002 (mapped via `ports:` in docker-compose.yml)

### LAN Access

For the Gateway to reach App 1 over a phone hotspot LAN:

```bash
# Find App 1's LAN IP
hostname -I | awk '{print $1}'
# Example output: 192.168.43.100

# Gateway would reach App 1 at:
# http://192.168.43.100:8002/
```

### Firewall

If using `ufw`:

```bash
sudo ufw allow 8002/tcp
```

Only port 8002 needs to be open. No other ports are required.

## Health Check

App 1 uses the application's **real** health endpoint:

```
GET /
→ {"status": "Healthy", "message": "API is working"}
```

Docker healthcheck polls this every 15 seconds.

## Security Measures

- ✅ Runs as non-root user (`appuser`)
- ✅ No Docker socket mounted
- ✅ No privileged mode
- ✅ No host networking
- ✅ No secrets in Dockerfile or docker-compose.yml
- ✅ Only port 8002 exposed
- ✅ Uses official Python slim base image
- ✅ Multi-stage build minimizes image size
- ✅ `restart: unless-stopped` for resilience

### Remaining Limitations

- ⚠️ Supabase credentials passed as environment variables (visible in `docker inspect`)
- ⚠️ No TLS (plain HTTP) — acceptable for isolated LAN demo
- ⚠️ Supabase DNS resolution fails when using dummy credentials (expected)
- ⚠️ No authentication on the health endpoint
- ⚠️ Not production-hardened (no resource limits, no seccomp profiles)

## Supported Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | No | Health check |
| GET | `/questions/domains` | No | List active domains |
| POST | `/submission/` | Yes | Submit code |
| POST | `/assessment/start` | Yes | Start assessment |
| GET | `/admin/domains` | Yes (admin) | List all domains |

Most endpoints require Supabase authentication. Only the health check and domain listing work without credentials.

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

## LAN Deployment (Separate Machine)

### On System 3 (App 1 Machine)

```bash
# 1. Clone the repository
git clone <repo-url>
cd "Platform deployment"

# 2. Configure App 1
cd gateway/app-1
cp .env.example .env
# Edit .env with real Supabase credentials

# 3. Build and start
docker compose up -d --build

# 4. Verify health
curl -s http://localhost:8002/
# Expected: {"status":"Healthy","message":"API is working"}

# 5. Find LAN IP for Gateway configuration
ip route get 1 | awk '{print $7; exit}'
# Example output: 192.168.43.100
```

### On System 1 (Gateway Machine)

```bash
# Configure Gateway to reach App 1
cd gateway
cp .env.example .env
# Edit .env: set APP1_URL=http://<APP1_LAN_IP>:8002

# Start Gateway
docker compose up -d

# Verify routing
curl -s http://localhost/
# Should return App 1's health response
```

## LAN Deployment Checklist

- [ ] Docker and Docker Compose installed on both machines
- [ ] `.env` file configured with real Supabase credentials
- [ ] Container builds and starts successfully
- [ ] Health endpoint returns 200
- [ ] Port 8002 is accessible from App 1 host
- [ ] Gateway machine can reach `<APP1_IP>:8002` over LAN
