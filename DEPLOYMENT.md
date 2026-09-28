# DSC Recruitment Platform — Six-System LAN Deployment

Operational guide for deploying the platform across **six physical LAN machines**
(Gateway, App-1, App-2, Compiler-1/2/3). Follow it top to bottom.

Everything here matches what is actually in the repository: the file paths, the
compose stacks, the environment variables, the ports and the test scripts were
all verified on a running deployment.

> **Candidates only ever use one address: `http://<GATEWAY_LAN_IP>/`.**
> Internal machine addresses and ports must never appear in a browser.

---

## 1. Architecture

```
                          Candidate browser
                                  │
                                  │  http://<GATEWAY_LAN_IP>/   ← the only entry point
                                  ▼
        ┌───────────────────────────────────────────────────────────┐
        │ SYSTEM 1 — GATEWAY            Traefik :80 (+ dashboard :8080)
        │   /            → frontend (React SPA, includes client-side routes)
        │   /api/*       → gateway-api (sessions, health, /api/execute)
        │   /_api/*      → App pool [App-1, App-2] (StripPrefix — ALL frontend
        │                  API calls: /auth, /assessment, /coding, /admin, …)
        │   /challenge/* → Challenge pool [challenge-1, challenge-2] (StripPrefix)
        └───────────────────────────────────────────────────────────┘
                    │                                  │
        ┌───────────┴───────────┐          ┌───────────┴────────────┐
        │ SYSTEM 2 — APP-1      │          │ SYSTEM 4 — APP-2       │
        │  app-1        :8002   │          │  app-2        :8002    │
        │  challenge-1  :8080   │          │  challenge-2  :8080    │
        └───────────┬───────────┘          └───────────┬────────────┘
                    │                                  │
                    └──────────────┬───────────────────┘
                                   │  round-robin + failover
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
             SYSTEM 3        SYSTEM 5        SYSTEM 6
             Compiler-1      Compiler-2      Compiler-3
             Judge0 :2358    Judge0 :2358    Judge0 :2358
             (server+worker+redis+postgres — all internal except the API port;
              2359/2360 when the nodes share one host)

        App-1 / App-2 ─────────────► Supabase (one shared project, Internet)
```

**Dependency map**

| Direction | Meaning |
|---|---|
| Gateway → Frontend | SPA is served by the `frontend` container behind Traefik |
| Gateway → App-1/App-2 | `/_api/*` (all frontend API calls including `/admin`, `/auth`, etc.) load-balanced across both App machines |
| Gateway → challenge-1/2 | `/challenge/*` load-balanced across both challenge containers |
| App-1/App-2 → Supabase | The only Internet dependency of the App machines (one recruitment database) |
| App-1/App-2 → Compiler-1/2/3 | `COMPILER_1_URL..3_URL`, round-robin with failover |
| Gateway → Compiler-1/2/3 | `/api/execute` runs through the same pool (gateway-api client) |
| challenge-1/2 → (nothing) | The challenge server is isolated: own seeded SQLite DB, no credentials, no Internet |

---

## 2. The six systems

| System | Role | Find its IP (§3) | Required services (containers) | Ports it publishes | What to configure on it |
|---|---|---|---|---|---|
| **1** | Gateway | on the Gateway | `traefik`, `frontend`, `gateway-api` | **80** (LAN, candidates), **8080** (dashboard, operator) | `APP1_URL`, `APP2_URL`, `APP1_CHALLENGE_URL`, `APP2_CHALLENGE_URL`, `COMPILER_1_URL`, `COMPILER_2_URL`, `COMPILER_3_URL`, `JUDGE0_AUTH_TOKEN` |
| **2** | App-1 | on App-1 | `app-1`, `challenge-1` | **8002**, **8080** (LAN, Gateway-only) | Supabase keys, `APP1_HOST_PORT`, `APP1_CHALLENGE_PORT`, `COMPILER_1_URL..3_URL`, `JUDGE0_AUTH_TOKEN` |
| **3** | Compiler-1 | on Compiler-1 | `compiler-1-server`, `-worker`, `-redis`, `-db` | **2358** (LAN, Gateway + Apps only) | `COMPILER_NAME=compiler-1`, `COMPILER_NETWORK`, `JUDGE0_BIND=0.0.0.0`, `JUDGE0_PORT` |
| **4** | App-2 | on App-2 | `app-2`, `challenge-2` | **8002**, **8080** (LAN, Gateway-only) | Supabase keys (same project), `APP2_HOST_PORT`, `APP2_CHALLENGE_PORT`, `COMPILER_1_URL..3_URL`, `JUDGE0_AUTH_TOKEN` |
| **5** | Compiler-2 | on Compiler-2 | `compiler-2-server`, `-worker`, `-redis`, `-db` | **2358** (LAN, Gateway + Apps only) | `COMPILER_NAME=compiler-2`, `COMPILER_NETWORK`, `JUDGE0_BIND=0.0.0.0`, `JUDGE0_PORT` |
| **6** | Compiler-3 | on Compiler-3 | `compiler-3-server`, `-worker`, `-redis`, `-db` | **2358** (LAN, Gateway + Apps only) | `COMPILER_NAME=compiler-3`, `COMPILER_NETWORK`, `JUDGE0_BIND=0.0.0.0`, `JUDGE0_PORT` |

Port numbers repeat between App-1 and App-2 (8002/8080), and between the three
Compiler machines (2358). That is safe: they are **different machines**. They
only need to differ if you deliberately run two of them on one host
(`APP2_HOST_PORT`, `APP2_CHALLENGE_PORT`, `JUDGE0_PORT`).

**Internal-only ports (never published, never reachable from the LAN):**
`gateway-api` 8000, `frontend` 8080, challenge *container* port 8080, Judge0
server/worker 2358 (inside their network), PostgreSQL 5432, Redis 6379.

---

## 3. How to find each machine's LAN IP

Run this **on the machine itself**:

```bash
# Linux
hostname -I | awk '{print $1}'      # first address — usually the LAN one
ip -4 addr                          # full detail per interface
ip route show default                # the interface that has the default route
```

```powershell
# Windows
ipconfig
```

* Use the IPv4 address of the interface that is on the **same network as the
  other five machines** (the one with the default route).
* Do **not** use a VPN/tailscale address (`100.x`), a Docker address
  (`172.17–31.x`, `192.168.16.x`) or `127.0.0.1`.
* Put the addresses into each machine's `.env` as noted below and into every
  other machine's `.env` that has to reach it.

> The scripts in `deployment-tests/` auto-detect this. If auto-detection picks
> the wrong interface, set `SYSTEM_IP` (and optionally `SYSTEM_IFACE`) in
> `deployment-tests/.env`.

---

## 4. Where the IPs go

Every value below already exists in the repository's `.env.example` files.
`.env` files are **git-ignored** and must never be committed.

### On the Gateway — `gateway/.env`

```ini
APP1_URL=http://10.0.0.11:8002              # App-1 LAN IP : APP1_HOST_PORT
APP2_URL=http://10.0.0.12:8002              # App-2 LAN IP : APP2_HOST_PORT
APP1_CHALLENGE_URL=http://10.0.0.11:8080    # App-1 LAN IP : APP1_CHALLENGE_PORT
APP2_CHALLENGE_URL=http://10.0.0.12:8080    # App-2 LAN IP : APP2_CHALLENGE_PORT
COMPILER_1_URL=http://10.0.0.21:2358        # Compiler-1 LAN IP : Judge0 API port
COMPILER_2_URL=http://10.0.0.22:2358
COMPILER_3_URL=http://10.0.0.23:2358
JUDGE0_AUTH_TOKEN=<same token as every compiler machine's judge0.conf>
JUDGE0_AUTH_HEADER=X-Judge0-Token
```

Leave `APP2_URL` / `COMPILER_3_URL` **empty** and that machine simply drops out
of the pool (the deployment keeps working with the remaining ones).

### On App-1 — `gateway/app-1/.env`

```ini
APP1_HOST_PORT=8002                 # published API port (gateway/.env APP1_URL)
APP1_CHALLENGE_PORT=8080            # published challenge port (gateway/.env APP1_CHALLENGE_URL)
SUPABASE_URL=...                    # the ONE shared project
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_ANON_KEY=...
SUPABASE_JWT_SECRET=...
COMPILER_1_URL=http://10.0.0.21:2358   # the compiler machines this App uses
COMPILER_2_URL=http://10.0.0.22:2358
COMPILER_3_URL=http://10.0.0.23:2358
JUDGE0_AUTH_TOKEN=<same token>
JUDGE0_BASE_URL=http://judge0-server:2358   # only if a compiler node runs on THIS host
```

### On App-2 — `gateway/app-2/.env`

Identical, with `APP2_*` names. **Do not copy App-1's `.env` file across** —
fill in App-2's own file (same Supabase project, no new secrets).

### On each Compiler machine — `gateway/judge0/.env`

```ini
COMPILER_NAME=compiler-1            # compiler-1 / compiler-2 / compiler-3
COMPILER_NETWORK=compiler-1-net     # this node's private Docker network
JUDGE0_BIND=0.0.0.0                 # reachable by the Gateway/Apps over the LAN
JUDGE0_PORT=2358
```

### For the tests — `deployment-tests/.env`

```ini
GATEWAY_IP=10.0.0.10
APP1_IP=10.0.0.11
APP2_IP=10.0.0.12
COMPILER1_IP=10.0.0.21
COMPILER2_IP=10.0.0.22
COMPILER3_IP=10.0.0.23
JUDGE0_AUTH_TOKEN=<same token>
```

---

## 5. System-by-system deployment

Each machine has its own copy of this repository. Run the commands **on that
machine**.

### Automated scripts (recommended)

Each system has a startup and shutdown script in `gateway/scripts/`:

| System | Startup | Shutdown |
|--------|---------|----------|
| 1 Gateway | `gateway/scripts/deploy-system1-gateway.sh` | `gateway/scripts/down-system1-gateway.sh` |
| 2 App-1 | `gateway/scripts/deploy-system2-app1.sh` | `gateway/scripts/down-system2-app1.sh` |
| 3 Compiler-1 | `gateway/scripts/deploy-system3-compiler1.sh` | `gateway/scripts/down-system3-compiler1.sh` |
| 4 App-2 | `gateway/scripts/deploy-system4-app2.sh` | `gateway/scripts/down-system4-app2.sh` |
| 5 Compiler-2 | `gateway/scripts/deploy-system5-compiler2.sh` | `gateway/scripts/down-system5-compiler2.sh` |
| 6 Compiler-3 | `gateway/scripts/deploy-system6-compiler3.sh` | `gateway/scripts/down-system6-compiler3.sh` |

Verify a system's role with:

```bash
gateway/scripts/check-system-role.sh gateway    # or app1, compiler1, etc.
```

Co-located test mode (NOT production):

```bash
./gateway/dockerdemoup.sh all      # starts all six systems on one machine
./gateway/dockerdemodown.sh all    # stops all six
```

### Manual deployment

### SYSTEM 3, 5, 6 — the Compiler machines (do these first)

Compiler-1/2/3 are the *same* stack deployed three times; only the identity/port
`.env` values differ. The scripts do this for you (they also create the node's
private Docker network and wait for health):

```bash
./gateway/scripts/deploy-system3-compiler1.sh   # compiler-1 on 2358
./gateway/scripts/deploy-system5-compiler2.sh   # compiler-2 on 2359
./gateway/scripts/deploy-system6-compiler3.sh   # compiler-3 on 2360
```

Manual equivalent:

```bash
cd gateway/judge0
cp .env.example .env
#   COMPILER_NAME=compiler-1        (compiler-2 / compiler-3 on the other machines)
#   COMPILER_NETWORK=compiler-1-net  (one PRIVATE network per node — never shared)
#   JUDGE0_BIND=0.0.0.0             (the Gateway and the App machines must reach it)
#   JUDGE0_PORT=2358                (2359 for compiler-2, 2360 for compiler-3)
docker network create compiler-1-net
docker compose -p compiler-1 up -d   # -p keeps the nodes' volumes separate
```

Each node is isolated in its **own** Docker network (`<name>-net`): `judge0.conf`
addresses the datastores by the plain service names `judge0-db` / `judge0-redis`,
so a shared network would make one node's submission get inserted into another
node's Postgres (Judge0 then answers `Couldn't find Submission` / HTTP 404).

That is all: `compiler-1-server`, `compiler-1-worker`, `compiler-1-redis`,
`compiler-1-db` and a one-shot `compiler-1-java-tuning` container, which
**tunes Java automatically** and exits 0 (see §10).

Verify:

```bash
docker compose ps
curl -s -H "X-Judge0-Token: <token>" http://localhost:2358/about
./../../deployment-tests/system3-compiler1-test.sh      # SYSTEM 5 → system5-…, SYSTEM 6 → system6-…
```

### SYSTEM 2, 4 — the App machines

```bash
cd gateway/app-1                 # App-2: cd gateway/app-2
cp .env.example .env             # fill in the Supabase keys, ports, compiler pool
docker network create system3    # shared network name the compose expects
docker compose up -d --build
```

Verify:

```bash
curl http://localhost:8002/            # {"status":"Healthy","message":"API is working"}
curl http://localhost:8080/health      # {"status": "ok"}          (challenge server)
curl -s http://localhost:8080/ | grep -o '<title>.*</title>'       # Employee Portal
./../../deployment-tests/system2-app1-test.sh    # SYSTEM 4 → system4-app2-test.sh
```

### SYSTEM 1 — the Gateway (last)

```bash
cd gateway
cp .env.example .env             # all six machine addresses (§4)
docker network create system3    # REQUIRED: gateway-api joins this network
docker compose up -d --build
```

Verify:

```bash
curl -I http://localhost/                      # 200 — the website
curl -s http://localhost/api/health            # {"status":"ok",...}
curl -s http://localhost/challenge/ | grep -o '<title>.*</title>'   # Employee Portal
curl -s http://localhost/api/execute/health    # the compiler pool: every node "ok"
./../deployment-tests/system1-gateway-test.sh
```

---

## 6. Firewall — required on every App and Compiler machine

Docker publishes ports through `PREROUTING → FORWARD`; traffic **never touches
the INPUT chain**, so `ufw deny <port>` does nothing for a published port. This
was measured on this deployment (see `deployment-tests/firewall-kernel-test.sh`).

The guard restricts published ports to specific source IPs in `DOCKER-USER`:

```bash
# App machine — its challenge + API ports, reachable only from the Gateway:
sudo ./gateway/scripts/docker-port-guard.sh \
     --gateway-ip <GATEWAY_LAN_IP> --ports "8002 8080"

# Compiler machine — the Judge0 API, reachable only from Gateway + both Apps:
sudo ./gateway/scripts/docker-port-guard.sh \
     --ports 2358 \
     --gateway-ip <GATEWAY_LAN_IP> \
     --gateway-ip <APP1_LAN_IP> --gateway-ip <APP2_LAN_IP>

sudo iptables -S DOCKER-USER        # inspect what was installed
sudo ./gateway/scripts/docker-port-guard.sh --remove    # undo
```

Make it survive a reboot by installing the unit that ships with the script:

```bash
sudo cp gateway/scripts/docker-port-guard.service /etc/systemd/system/
sudoedit /etc/systemd/system/docker-port-guard.service   # EDIT the IPs + ports
sudo systemctl daemon-reload && sudo systemctl enable --now docker-port-guard
```

Prove it (on the App/Compiler machine, as root — creates a temporary network
namespace that acts as a second LAN machine):

```bash
sudo ./deployment-tests/firewall-kernel-test.sh --ports "8002 8080" --restore-prod
sudo ./deployment-tests/firewall-kernel-test.sh --ports 2358 --restore-prod
```

It shows the port reachable *before* the guard, blocked *after*, and still
reachable from an allowlisted source.

---

## 7. Verify each system

| System | Command |
|---|---|
| 1 Gateway | `./deployment-tests/system1-gateway-test.sh` |
| 2 App-1 | `./deployment-tests/system2-app1-test.sh` |
| 3 Compiler-1 | `./deployment-tests/system3-compiler1-test.sh` |
| 4 App-2 | `./deployment-tests/system4-app2-test.sh` |
| 5 Compiler-2 | `./deployment-tests/system5-compiler2-test.sh` |
| 6 Compiler-3 | `./deployment-tests/system6-compiler3-test.sh` |

Every script prints PASS/FAIL/SKIP, exits non-zero when something fails, and
adapts to where it runs (on the machine itself, on the Gateway, or on a
candidate machine — where it verifies the ports are **blocked**).

## 8. Run the full LAN test

From the Gateway or an admin machine:

```bash
cd deployment-tests
cp .env.example .env      # fill in the six IPs + the Judge0 token (git-ignored)
./full-lan-test.sh
```

It walks the whole chain — candidate → Gateway → App → Supabase,
candidate → Gateway → App → challenge, candidate → Gateway → App → compiler pool
→ result — and names the dependency that failed.

---

## 9. Order to bring the systems online

1. **Compiler-1, Compiler-2, Compiler-3** (no dependencies).
2. **App-1, App-2** (need the compilers, Supabase, Internet).
3. **Gateway** last (its pools then find live backends immediately).

Shutdown is the reverse order.

---

## 10. Operating notes and troubleshooting

**Java on a compiler node.** The OpenJDK image reserves ~1 GiB of virtual
address space, so an uncapped JVM dies with
`Could not allocate metaspace: 1073741824 bytes`. The `judge0-java-tuning`
one-shot service applies the caps automatically on **every** `docker compose up`
— a brand-new machine needs no manual step. To check or repair a running node:

```bash
./gateway/judge0/apply-java-tuning.sh compiler-1 --verify
./gateway/judge0/apply-java-tuning.sh compiler-1
```

Both paths run the same SQL (`gateway/judge0/java-tuning.sql`), so they cannot
drift apart. `docker compose down -v` (which wipes the node's database volume)
is followed by an automatic re-application on the next `up`.

**Common failures**

| Symptom | Cause / fix |
|---|---|
| `502` on `/challenge/` or `/auth/...` | That pool member is down. Check `docker compose ps` on the App machine; Traefik stops routing to a dead server within seconds and serves from the survivor. |
| `/api/execute/health` shows a node not `ok` | That compiler machine is down, or the guard there does not allowlist the caller (`--gateway-ip` / `--gateway-ip <APPn_LAN_IP>`). |
| `docker compose up` fails: external network `system3` missing | `docker network create system3` (Gateway and both App machines). Compiler machines use their own `COMPILER_NETWORK`. |
| `Bind for 0.0.0.0:8080 failed: port is already allocated` | Another container on that machine already uses 8080 — change `APPn_CHALLENGE_PORT`/`TRAEFIK_DASHBOARD_PORT`. This only happens when two systems share one host. |
| Java `OutOfMemoryError: Metaspace` | Host memory pressure. Each compiler machine should have enough RAM for its JVM sandboxes; a single host running all six systems will starve. |
| Supabase probe answers `HTTP 401` | **Reachable** — that endpoint needs an API key. Only connection errors mean a problem. |
| A candidate sees an `http://10.x.x.x:8080` URL | Regression: the Hands-On iframe must always use the Gateway-relative `/challenge/`. |

**Shutdown / restart**

```bash
docker compose down            # stop (keeps volumes: submission history, java tuning)
docker compose up -d           # start again
docker compose restart         # restart containers in place
docker compose down -v         # DESTRUCTIVE: wipes compiler metadata + java tuning
```

---

## 11. What the candidate can reach

| From a candidate machine | Result |
|---|---|
| `http://<GATEWAY_LAN_IP>/` | ✅ the website |
| `http://<GATEWAY_LAN_IP>/challenge/` | ✅ the Employee Portal (same-origin iframe) |
| `http://<GATEWAY_LAN_IP>/api/*`, `/_api/*`, `/auth/*`, `/questions/*`, … | ✅ through Traefik (`/auth/*` and friends are client-side SPA routes; their API calls go via `/_api/*`) |
| `http://<APP1_LAN_IP>:8002` / `:8080` | ❌ blocked by the DOCKER-USER guard |
| `http://<APP2_LAN_IP>:8002` / `:8080` | ❌ blocked by the DOCKER-USER guard |
| `http://<COMPILERN_LAN_IP>:2358` | ❌ blocked by the DOCKER-USER guard |

Verified with a network namespace acting as a second LAN machine — see
`deployment-tests/firewall-kernel-test.sh`.
