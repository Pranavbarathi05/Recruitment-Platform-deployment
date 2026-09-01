# Recruitment Platform — LAN Deployment Guide

## Architecture Overview

### Phase 3 Topology (Current)

```
Client
  │
  ▼  :80
SYSTEM 1 (Gateway Machine)
┌──────────────────────────────────────────┐
│  Traefik              :80 (HTTP)         │
│  Traefik Dashboard    :8080 (dev)        │
│  Gateway API          :8000 (internal)   │
│    └── /api/execute → Compiler 1         │
│  App 1 (dsc-recruit)  :8000 (internal)   │
└───────────────┬──────────────────────────┘
                │
                │  LAN TCP
                │  COMPILER_URL
                ▼
SYSTEM 2 (Compiler Machine)
┌──────────────────────────────────────────┐
│  Compiler 1           :8001 (HTTP)       │
│  Python / C / C++ / Java / SQL / JS      │
│  Sandboxed execution with resource limits│
└──────────────────────────────────────────┘
```

### Request Flows

**Code Execution Flow:**
```
Client → POST /api/execute → Gateway API → Compiler 1 → Result → Client
```

**Application Flow:**
```
Client → GET /* → Traefik → App 1 → Response → Client
```

**Session Flow:**
```
Client → POST /api/session/* → Gateway API → Response → Client
```

---

## System 1 — Gateway / Application Host

### Required Software

- Docker Engine 20.10+
- Docker Compose v2.20+
- Free host ports: **80** (HTTP), **8080** (Traefik dashboard, optional)

### Environment Variables

Create `gateway/.env` from the template:

```bash
cd gateway
cp .env.example .env
```

Edit `.env` and set:

```bash
# App 1 address (for LAN deployment)
APP1_URL=http://<APP1_LAN_IP>:8002

# Compiler 1 address (REQUIRED for code execution)
COMPILER_URL=http://<COMPILER_1_LAN_IP>:8001

# Supabase credentials (REQUIRED for App 1)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret
```

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

# Verify code execution
curl -s -X POST http://localhost/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "language": "python",
    "source_code": "print(42)",
    "test_cases": [{"input": "", "expected_output": "42"}]
  }'

# Watch logs
docker compose logs -f

# Stop
docker compose down
```

---

## System 2 — Compiler Host

### Required Software

- Docker Engine 20.10+
- Docker Compose v2.20+
- Free host port: **8001** (Compiler API)

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

---

## Local Single-Machine Development

For testing everything on one machine:

```bash
cd gateway

# Copy and configure environment
cp .env.example .env
# Edit .env with Supabase credentials

# Start all services (including Compiler 1)
docker compose -f docker-compose.local.yml up -d --build

# Verify
curl -s http://localhost/api/health     # Gateway API
curl -s http://localhost/               # App 1 via Gateway
curl -s http://localhost:8001/health    # Compiler 1 (direct)

# Test code execution
curl -s -X POST http://localhost/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "language": "python",
    "source_code": "print(\"hello\")",
    "test_cases": [{"input": "", "expected_output": "hello"}]
  }'

# Stop
docker compose -f docker-compose.local.yml down
```

---

## Network / Port Requirements

| Connection | From | To | Port | Protocol | Purpose |
|---|---|---|---|---|---|
| Client → Gateway | Any | System 1 | 80 | TCP/HTTP | User traffic |
| Gateway → Compiler | System 1 | System 2 | 8001 | TCP/HTTP | Code execution |
| Gateway API → Compiler | System 1 | System 2 | 8001 | TCP/HTTP | /api/execute proxy |
| Dashboard (dev) | Any | System 1 | 8080 | TCP/HTTP | Traefik dashboard |

### Firewall Rules

**System 1 (Gateway):**
- Allow inbound TCP port 80 (HTTP) from client machines
- Allow inbound TCP port 8080 (optional, for Traefik dashboard)
- Allow outbound TCP port 8001 to System 2 (Compiler)

**System 2 (Compiler):**
- Allow inbound TCP port 8001 from System 1 only
- No other ports need to be exposed

---

## API Contract

### POST /api/execute

Execute code via Compiler 1.

**Request:**
```json
{
  "language": "python",
  "source_code": "print('hello')",
  "test_cases": [
    {"input": "", "expected_output": "hello"}
  ],
  "limits": {
    "time_limit_seconds": 10.0,
    "memory_limit_mb": 256,
    "max_output_bytes": 65536
  },
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
  "tests": [
    {
      "test_case": 1,
      "passed": true,
      "execution_time_ms": 20,
      "stdout": "hello",
      "stderr": ""
    }
  ],
  "total_tests": 1,
  "passed_tests": 1,
  "session_id": "optional-session-id",
  "attempt_id": "optional-attempt-id",
  "question_id": "optional-question-id"
}
```

**Status Values:**
- `accepted` — All tests passed
- `wrong_answer` — Output doesn't match expected
- `compilation_error` — Code failed to compile
- `runtime_error` — Code crashed during execution
- `time_limit_exceeded` — Execution timed out
- `invalid_language` — Language not supported
- `capacity_exceeded` — Server at max concurrent executions
- `compiler_unavailable` — Compiler 1 is unreachable
- `internal_error` — Unexpected error

**Supported Languages:**
- `python` — Python 3
- `c` — C (gcc, C11)
- `cpp` — C++ (g++, C++17)
- `java` — Java (OpenJDK 21)
- `sql` — SQL (SQLite)

### GET /api/execute/health

Check Compiler 1 health.

### GET /api/execute/languages

List available languages from Compiler 1.

---

## Known Limitations

1. **Application-level evaluation is not integrated.** The `evaluate_code()` function
   in dsc-recruit is a synchronous stub. The `/api/execute` gateway endpoint
   provides code execution independently of the app's internal evaluator.
   To fully integrate, the app's evaluator needs to call the gateway's
   `/api/execute` endpoint.

2. **No TLS.** All communication is over plain HTTP. For production, TLS
   termination should be added at the Traefik layer.

3. **No authentication on Compiler 1.** The compiler API is open. For LAN-only
   deployment this is acceptable; for public deployment, add API key auth.

4. **Single Compiler instance.** Only one Compiler 1 is deployed. If it fails,
   code execution is unavailable. Compiler 2/3 will be added later.

5. **SQL uses SQLite.** SQL execution is sandboxed to SQLite. For production
   SQL evaluation, consider adding PostgreSQL support.

---

## Environment Variable Reference

| Variable | Default | Description |
|---|---|---|
| `COMPILER_URL` | `http://compiler-1:8000` | Compiler 1 base URL. For LAN: `http://<IP>:8001` |
| `COMPILER_TIMEOUT` | `60.0` | Compiler request timeout in seconds |
| `APP1_URL` | `http://host.docker.internal:8002` | App 1 address. For LAN: `http://<IP>:8002` |
| `COMPILER_PORT` | `8001` | Host-side port for Compiler 1 |
| `MAX_CONCURRENT` | `4` | Max concurrent code executions |
| `SUPABASE_URL` | — | Supabase project URL (required for App 1) |
| `SUPABASE_SERVICE_ROLE_KEY` | — | Supabase service key (required for App 1) |
| `SUPABASE_JWT_SECRET` | — | Supabase JWT secret (required for App 1) |
| `TRAEFIK_HTTP_PORT` | `80` | Traefik HTTP port |
| `TRAEFIK_DASHBOARD_PORT` | `8080` | Traefik dashboard port |
| `APP_ENV` | `development` | Application environment tag |

---

## Troubleshooting

### Compiler Unavailable (502 from /api/execute)

```bash
# Check if Compiler 1 is running
docker ps | grep compiler

# Check Compiler 1 health
curl http://<COMPILER_IP>:8001/health

# Check COMPILER_URL in .env
echo $COMPILER_URL
```

### Connection Refused

```bash
# Test basic connectivity
nc -zv <COMPILER_IP> 8001

# If blocked, on System 2:
sudo ufw allow from <GATEWAY_IP> to any port 8001 proto tcp
```

### App 1 Not Responding

```bash
# Check if App 1 is running
docker ps | grep app

# Check App 1 health
curl http://<APP1_IP>:8002/

# Check APP1_URL in .env
echo $APP1_URL
```

### Code Execution Timeout

```bash
# Check Compiler 1 logs
docker logs compiler-1 --tail 20

# Increase timeout
COMPILER_TIMEOUT=120.0
```

### SQL Execution Issues

```bash
# Verify SQLite is installed in compiler container
docker exec compiler-1 sqlite3 --version

# Test SQL directly
docker exec compiler-1 sqlite3 /tmp/test.db "SELECT 1;"
```
