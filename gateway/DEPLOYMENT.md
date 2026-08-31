# Recruitment Platform — LAN Deployment Guide

## Architecture Overview

```
SYSTEM 1 (Gateway Machine)
┌──────────────────────────────────┐
│  Traefik         :80 (HTTP)      │
│  Traefik Dashboard :8080 (dev)   │
│  Gateway API     :8000 (internal)│
│  App 1           :8000 (internal)│
└───────────────┬──────────────────┘
                │
                │  LAN TCP
                │  COMPILER_URL
                ▼
SYSTEM 2 (Compiler Machine)
┌──────────────────────────────────┐
│  Compiler 1      :8001 (HTTP)    │
│  C / C++ / Java / Python / JS    │
└──────────────────────────────────┘
```

**Note:** For the current demo, System 1 runs Traefik + Gateway API + App 1.
System 2 runs Compiler 1 independently. App 2, Compiler 2, and Compiler 3
are not yet deployed.

---

## System 1 — Gateway / Application Host

### Required Software

- Docker Engine 20.10+
- Docker Compose v2.20+
- Free host port: **80** (HTTP), **8080** (Traefik dashboard, optional)

### Environment Variables

Create `gateway/.env` from the template:

```bash
cd gateway
cp .env.example .env
```

Edit `.env` and set:

```bash
# Compiler 1 LAN address (REQUIRED for distributed deployment)
COMPILER_URL=http://<COMPILER_1_LAN_IP>:8001

# Supabase credentials (REQUIRED for App 1 to function)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret
```

Replace `<COMPILER_1_LAN_IP>` with the actual LAN IP of the Compiler 1 machine.

### Commands

```bash
cd gateway

# Build and start all services
docker compose up -d --build

# Verify all containers are healthy
docker compose ps

# Verify Gateway API health
curl -s http://localhost/api/health

# Verify App 1 health
curl -s http://localhost/

# Verify Traefik dashboard (optional)
curl -s http://localhost:8080/api/overview

# Watch logs
docker compose logs -f

# Stop
docker compose down
```

### Verification

All three containers should show `(healthy)` status:

```
NAME          IMAGE                 STATUS                    PORTS
gateway-api   gateway-gateway-api   Up (healthy)              8000/tcp
recruit-app   gateway-recruit-app   Up (healthy)              8000/tcp
traefik       traefik:v3.1          Up (healthy)              0.0.0.0:80->80/tcp
```

---

## System 2 — Compiler Host

### Required Software

- Docker Engine 20.10+
- Docker Compose v2.20+
- Free host port: **8001** (Compiler API)

### Environment Variables

Create `gateway/compiler-1/.env` (optional, defaults work):

```bash
cd gateway/compiler-1
cp ../.env.example .env  # or create manually
```

```bash
# Compiler API port (host-side)
COMPILER_PORT=8001

# Maximum concurrent executions
MAX_CONCURRENT=4
```

### Commands

```bash
cd gateway/compiler-1

# Build and start
docker compose up -d --build

# Verify health
curl -s http://localhost:8001/health

# List available languages
curl -s http://localhost:8001/languages

# Test execution
curl -s -X POST http://localhost:8001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "language": "python",
    "source_code": "print(42)",
    "test_cases": [{"input": "", "expected_output": "42"}]
  }'

# Stop
docker compose down
```

### Verification

```bash
# Health check should return:
curl -s http://localhost:8001/health | python3 -m json.tool
# {
#     "status": "ok",
#     "service": "compiler-1",
#     "available_languages": [...],
#     "max_concurrent": 4
# }

# Supported languages:
# C, C++, Java, Python, JavaScript
```

---

## Network / Port Requirements

| Connection | From | To | Port | Protocol | Purpose |
|---|---|---|---|---|---|
| Client → Gateway | Any | System 1 | 80 | TCP/HTTP | User traffic |
| Gateway → Compiler | System 1 | System 2 | 8001 | TCP/HTTP | Code execution |
| Dashboard (dev) | Any | System 1 | 8080 | TCP/HTTP | Traefik dashboard |

### Firewall Rules

**System 1 (Gateway):**
- Allow inbound TCP port 80 (HTTP) from client machines
- Allow inbound TCP port 8080 (optional, for Traefik dashboard)
- Allow outbound TCP port 8001 to System 2 (Compiler)

**System 2 (Compiler):**
- Allow inbound TCP port 8001 from System 1 only
- No other ports need to be exposed

### Example (Ubuntu/ufw)

**System 2 (Compiler host):**
```bash
# Allow Compiler API from Gateway machine only
sudo ufw allow from <GATEWAY_LAN_IP> to any port 8001 proto tcp
sudo ufw enable
```

**System 1 (Gateway host):**
```bash
# Allow HTTP from clients
sudo ufw allow 80/tcp
sudo ufw allow 8080/tcp
sudo ufw enable
```

---

## Connectivity Test

After both systems are running, verify connectivity from System 1 to System 2:

```bash
# From System 1 (Gateway machine):
curl -s http://<COMPILER_1_LAN_IP>:8001/health

# Should return:
# {"status":"ok","service":"compiler-1",...}
```

If this fails, see the Troubleshooting section below.

---

## LAN Deployment Checklist

- [ ] System 1: Docker and Docker Compose installed
- [ ] System 2: Docker and Docker Compose installed
- [ ] System 2: Compiler 1 running and healthy on port 8001
- [ ] System 1: `COMPILER_URL` set to `http://<COMPILER_IP>:8001`
- [ ] System 1: Gateway containers running and healthy
- [ ] System 1: Can reach Compiler 1 health endpoint over LAN
- [ ] System 1: Firewall allows outbound TCP 8001 to System 2
- [ ] System 2: Firewall allows inbound TCP 8001 from System 1

---

## Known Limitations

1. **Application evaluation is not integrated.** The `evaluate_code()` function
   in dsc-recruit is a synchronous stub. The compiler client library exists in
   `gateway/compiler_client/` but is not yet called by the application. This
   requires a minimal change to dsc-recruit (converting `evaluate_code` to async
   and injecting the HTTP client), which is pending approval.

2. **No TLS.** All communication is over plain HTTP. For production, TLS
   termination should be added at the Traefik layer.

3. **No authentication on Compiler 1.** The compiler API is open. For LAN-only
   deployment this is acceptable; for public deployment, add API key auth.

4. **Single Compiler instance.** Only one Compiler 1 is deployed. If it fails,
   code execution is unavailable. Compiler 2/3 will be added later.

---

## Troubleshooting

### Connection Refused

```
curl: (7) Failed to connect to <IP> port 8001: Connection refused
```

**Causes:**
- Compiler 1 container is not running: `docker compose ps`
- Compiler 1 is not listening on `0.0.0.0`: check Dockerfile CMD
- Port mapping is wrong: verify `ports: "8001:8000"` in docker-compose.yml
- Firewall blocking: check `sudo ufw status`

**Fix:**
```bash
# On System 2:
cd gateway/compiler-1
docker compose ps           # Should show "healthy"
docker compose logs         # Check for startup errors
curl http://localhost:8001/health  # Test locally first
```

### Timeout

```
httpx.ConnectTimeout: Timed out connecting to <IP>
```

**Causes:**
- Network route between machines is broken
- Firewall silently dropping packets (not rejecting)
- Wrong IP address in COMPILER_URL

**Fix:**
```bash
# Test basic connectivity
ping <COMPILER_IP>
nc -zv <COMPILER_IP> 8001   # netcat test
```

### Wrong LAN IP

```bash
# Find the correct LAN IP on System 2:
ip route get 1 | awk '{print $7; exit}'
# or
hostname -I | awk '{print $1}'
```

### Firewall Blocking Port 8001

```bash
# Check if port is open from System 1:
nc -zv <COMPILER_IP> 8001

# If blocked, on System 2:
sudo ufw allow from <GATEWAY_IP> to any port 8001 proto tcp
```

### Compiler Container Not Listening on 0.0.0.0

The Dockerfile must use `--host 0.0.0.0` in the CMD. Verify:

```bash
docker exec compiler-1 ps aux | grep uvicorn
# Should show: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Docker Port Mapping

Verify the host-side port mapping:

```bash
docker port compiler-1
# Should show: 8000/tcp -> 0.0.0.0:8001
```

### Incorrect COMPILER_URL

```bash
# Verify the env var is set correctly:
echo $COMPILER_URL

# Should be: http://<COMPILER_IP>:8001
# NOT: http://compiler-1:8000  (Docker service name — only works inside Docker network)
# NOT: http://localhost:8001    (only works on the same machine)
```

### DNS / Service-Name Assumptions

Docker service names (like `compiler-1`) only resolve inside Docker networks.
For LAN deployment, use the actual IP address:

```bash
# WRONG (only works inside Docker):
COMPILER_URL=http://compiler-1:8000

# CORRECT (works over LAN):
COMPILER_URL=http://192.168.1.100:8001
```

### Compiler Health Check Failures

```bash
# Check compiler logs:
docker logs compiler-1 --tail 20

# Check if compilers are installed:
docker exec compiler-1 g++ --version
docker exec compiler-1 python3 --version
docker exec compiler-1 node --version
docker exec compiler-1 javac --version
```

---

## Environment Variable Reference

| Variable | Default | Description |
|---|---|---|
| `COMPILER_URL` | `http://compiler-1:8000` | Compiler 1 base URL. For LAN: `http://<IP>:8001` |
| `COMPILER_PORT` | `8001` | Host-side port for Compiler 1 |
| `MAX_CONCURRENT` | `4` | Max concurrent code executions |
| `SUPABASE_URL` | — | Supabase project URL (required for App 1) |
| `SUPABASE_SERVICE_ROLE_KEY` | — | Supabase service key (required for App 1) |
| `SUPABASE_JWT_SECRET` | — | Supabase JWT secret (required for App 1) |
| `TRAEFIK_HTTP_PORT` | `80` | Traefik HTTP port |
| `TRAEFIK_DASHBOARD_PORT` | `8080` | Traefik dashboard port |
| `APP_ENV` | `development` | Application environment tag |
