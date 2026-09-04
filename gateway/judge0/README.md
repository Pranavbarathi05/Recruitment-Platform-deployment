# Judge0 – System 3 (Code Execution Service)

Self-hosted [Judge0 CE v1.13.1](https://github.com/judge0/judge0) running as an
independent LAN-internal service for safely executing untrusted candidate code.

```
Browser ──> Traefik ──> Gateway API ──> judge0-server ──> Redis queue
                                                    └──> judge0-worker ──> isolate sandbox
                                                    └──> judge0-db (PostgreSQL, metadata only)
```

## Architecture

| Service        | Image                  | Purpose                                    |
|----------------|------------------------|--------------------------------------------|
| `judge0-server`| `judge0/judge0:1.13.1` | HTTP API (submissions, languages, status)  |
| `judge0-worker`| `judge0/judge0:1.13.1` | Pops the Redis queue, runs isolate sandboxes (STOCK image on purpose – see below) |
| `judge0-db`    | `postgres:16.2`        | Submission metadata (NOT exposed)          |
| `judge0-redis` | `redis:7.2.4`          | Execution queue (NOT exposed)              |

- Only the Judge0 API is reachable: `127.0.0.1:2358` (host-local, developer
  curl) and `http://judge0-server:2358` on the shared `system3` Docker network
  (used by the gateway — no host port involved).
- PostgreSQL / Redis expose **no** host ports. Judge0 is **not** routed through
  Traefik; candidates can never call it directly.
- The API requires `X-Judge0-Token: <AUTHN_TOKEN>` (token lives in
  `judge0.conf`; the gateway sends the same token via `JUDGE0_AUTH_TOKEN` in
  `gateway/.env`).
- Worker concurrency: `COUNT=4` resque workers (verified live inside the
  container); queue depth `MAX_QUEUE_SIZE=100` (`judge0.conf`).
- Judge0 CE v1.13.1 in this image **does include SQL (SQLite 3.27.2)**, id 82
  (verified via `GET /languages`).

## cgroup v2 hosts — REQUIRED configuration (read this)

Judge0 CE 1.13.1 bundles an isolate fork that only understands the **cgroup v1**
layout (`/sys/fs/cgroup/<controller>/...`). On a cgroup v2-only kernel any
submission executed with isolate's `--cg` flag fails instantly:

```
Failed to create control group /sys/fs/cgroup/memory/box-<id>/...
```

Judge0 passes `--cg` **only when per-process/thread limits are disabled**
(`/api/app/jobs/isolate_job.rb`). This deployment therefore keeps, in
`judge0.conf`:

```
ENABLE_PER_PROCESS_AND_THREAD_TIME_LIMIT=true
ENABLE_PER_PROCESS_AND_THREAD_MEMORY_LIMIT=true
```

With both enabled, Judge0 enforces CPU/memory via **rlimits** (`-t`, `-m`)
instead of cgroups — the stock setuid isolate binary handles that correctly on
cgroup v2 hosts, so the worker runs the **unmodified stock image**. Do not
disable these flags, and do not build a custom isolate, unless the host is
cgroup v1.

The gateway sends the same flags on every submission (see
`gateway-api/app/judge0_proxy.py`) and talks to Judge0 exclusively in
`base64_encoded=true` mode (Judge0 1.13.1's plaintext response path can 400 on
valid compiler output).

## Memory semantics note

With rlimit-based enforcement, memory usage is measured via `max-rss` and the
limit is `RLIMIT_AS`. There is no distinct "Memory Limit Exceeded" status in
Judge0 CE 1.13.1 (ids 15/16 exist only in newer releases); an allocation
failure under the rlimit surfaces as a runtime error, which the gateway maps
honestly instead of pretending it is an MLE.

### Java (one-time database tuning)

The OpenJDK 13 runtime reserves ~1 GiB of *virtual* address space for the
compressed class space even with a small heap, so it needs
`MAX_MEMORY_LIMIT >= 2 GiB` (set to `2097152` in `judge0.conf`) **and** an
explicitly capped JVM. After `docker compose up -d`, run once (survives
restarts; only `down -v` wipes it):

```sql
-- inside judge0-db:  psql -U judge0 -d judge0
UPDATE languages SET
  compile_cmd = '/usr/local/openjdk13/bin/javac %s -J-Xmx256m -J-XX:MaxMetaspaceSize=256m -J-XX:CompressedClassSpaceSize=64m Main.java',
  run_cmd     = '/usr/local/openjdk13/bin/java -Xmx256m -XX:ReservedCodeCacheSize=96m -XX:MaxMetaspaceSize=192m -XX:CompressedClassSpaceSize=64m Main'
WHERE id = 62;
```

Real Java heap usage stays bounded by `-Xmx256m`; the larger RLIMIT_AS is only
the JVM's address-space *ceiling*.

## Prerequisites

The gateway joins the same external network, so create it once:

```bash
docker network create system3
```

## Start / stop

```bash
docker compose up -d            # start (from gateway/judge0)
docker compose ps               # status
docker compose logs -f          # logs
docker compose down             # stop (keeps data volume)
docker compose down -v          # stop AND wipe submission metadata + Java tuning
```

## Test the API directly (from the host)

Judge0 CE 1.13.1 stores attributes base64-encoded; use `base64_encoded=true`
for predictable results:

```bash
TOKEN=$(grep '^AUTHN_TOKEN=' judge0.conf | cut -d= -f2)
curl -fsS -H "X-Judge0-Token: $TOKEN" http://localhost:2358/languages | head -c 400
curl -fsS -H "X-Judge0-Token: $TOKEN" http://localhost:2358/statuses   | head -c 400
curl -fsS -H "X-Judge0-Token: $TOKEN" http://localhost:2358/about

# Hello world (base64 body, synchronous):
python3 - <<'EOF' | curl -fsS -X POST -H "X-Judge0-Token: $TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @- 'http://localhost:2358/submissions?base64_encoded=true&wait=true'
import base64, json
print(json.dumps({"source_code": base64.b64encode(b"print(21*2)").decode(),
                  "language_id": 71, "cpu_time_limit": 2, "memory_limit": 262144}))
EOF
```

## Languages (verified against the live instance)

| Platform | Judge0 id | Runtime                     |
|----------|-----------|-----------------------------|
| python   | 71        | Python (3.8.1)              |
| c        | 50        | C (GCC 9.2.0)               |
| cpp      | 54        | C++ (GCC 9.2.0)             |
| java     | 62        | Java (OpenJDK 13.0.1)       |
| sql      | 82        | SQL (SQLite 3.27.2)         |

The gateway resolves ids dynamically from `GET /languages` (highest version
match, cached 5 min) — ids above are informational, not hard-coded.

## End-to-end path

```
Browser/API ── POST /api/execute (platform contract, stdin/stdout test cases)
   └── Traefik /api/* ──> gateway-api ──> judge0-server (system3 network)
        └── one Judge0 submission per test case (isolation)
        └── result normalized to the platform ExecuteResponse vocabulary
```
