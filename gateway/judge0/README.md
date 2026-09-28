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

- The API is published on the host as `${JUDGE0_BIND}:${JUDGE0_PORT}`
  (compose default `127.0.0.1:2358` — machine-local curl only). Compiler
  machines in the LAN deployment set `JUDGE0_BIND=0.0.0.0` so the Gateway and
  the App machines reach `http://<COMPILERn_LAN_IP>:<JUDGE0_PORT>` through the
  `COMPILER_1_URL..3_URL` pool; the DOCKER-USER guard restricts that port to
  those machines (root `DEPLOYMENT.md` §6). A node co-located with the Gateway
  can instead keep the loopback bind and be addressed as
  `http://judge0-server:2358` over the shared `system3` Docker network.
- **One node per network.** Several nodes on one host each get a private
  network (`compiler-1-net`, `compiler-2-net`, `compiler-3-net`, created by
  `gateway/scripts/deploy-compiler.sh`) because `judge0.conf` addresses the
  datastores by the plain names `judge0-db` / `judge0-redis` — sharing a
  network would cross-wire one node's Postgres with another's submissions.
- PostgreSQL / Redis expose **no** host ports. Judge0 is **not** routed through
  Traefik; candidates can never call it directly.
- The API requires `X-Judge0-Token: <AUTHN_TOKEN>` (token lives in
  `judge0.conf`; the Gateway and the App machines send the same token via
  `JUDGE0_AUTH_TOKEN` in their `.env` files).
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

### Java (automatic per-node tuning)

The OpenJDK 13 runtime reserves ~1 GiB of *virtual* address space for the
compressed class space even with a small heap, so it needs
`MAX_MEMORY_LIMIT >= 2 GiB` (set to `2097152` in `judge0.conf`) **and** an
explicitly capped JVM. The one-shot `judge0-java-tuning` service applies the
caps automatically on **every** `docker compose up` — a brand-new node needs no
manual step, and only `docker compose down -v` (which wipes the node's database
volume) requires the next `up` to redo it. To check or repair a running node:

```bash
./gateway/judge0/apply-java-tuning.sh compiler-1 --verify
./gateway/judge0/apply-java-tuning.sh compiler-1
```

Both paths run the same SQL (`gateway/judge0/java-tuning.sql`), so they cannot
drift apart. The tuning sets the capped compile/run commands for language id 62:

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

Create the node's Docker network once (the deploy scripts do this for you):

```bash
docker network create compiler-1-net   # or system3 for a co-located single node
```

## Start / stop

Recommended — via the per-system scripts (create the network, set identity,
wait for health):

```bash
./gateway/scripts/deploy-system3-compiler1.sh    # compiler-1 on 2358
./gateway/scripts/deploy-system5-compiler2.sh    # compiler-2 on 2359
./gateway/scripts/deploy-system6-compiler3.sh    # compiler-3 on 2360
./gateway/scripts/down-compiler.sh compiler-1    # stop one node
```

Manual (from `gateway/judge0`, with `COMPILER_NAME`/`COMPILER_NETWORK`/
`JUDGE0_BIND`/`JUDGE0_PORT` set in `.env`):

```bash
docker compose -p compiler-1 up -d    # -p keeps the nodes' volumes separate
docker compose -p compiler-1 ps       # status (server/worker/db/redis/java-tuning)
docker compose -p compiler-1 logs -f  # logs
docker compose -p compiler-1 down     # stop (keeps data volume)
docker compose -p compiler-1 down -v  # stop AND wipe submission metadata + Java tuning
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
