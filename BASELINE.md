# Baseline — audited state of the six-system deployment

Recorded **before** the App-2 / Compiler-2 / Compiler-3 build-out was validated,
and re-confirmed afterwards. Every row was measured on a running deployment, not
inferred from configuration.

Machine IPs are placeholders (`10.0.0.x`); nothing here is hard-coded to a
particular network. On the verification host all six systems were simulated on
one machine, which is why several rows share an address.

---

## 1. Service / port / access map

| System | Service (container) | Address : port | Access from | Health | Status |
|---|---|---|---|---|---|
| 1 Gateway | `traefik` | `GATEWAY:80` | **LAN (candidates)** | healthy | ✅ |
| 1 Gateway | `traefik` (dashboard) | `GATEWAY:8080` | LAN (operator; 18081 when all systems share one host) | healthy | ✅ |
| 1 Gateway | `frontend` | `frontend:8080` | Docker-internal only (Traefik) | healthy | ✅ |
| 1 Gateway | `gateway-api` | `gateway-api:8000` | Docker-internal only (Traefik); joins `system3` | healthy | ✅ |
| 2 App-1 | `app-1` | `APP1:8002` → container 8000 | Gateway-only (DOCKER-USER guard) | healthy | ✅ |
| 2 App-1 | `challenge-1` | `APP1:8080` → container 8080 | Gateway-only (DOCKER-USER guard) | healthy | ✅ |
| 3 Compiler-1 | `compiler-1-server` | `COMPILER1:2358` | Gateway + App machines only (guard) | healthy | ✅ |
| 3 Compiler-1 | `compiler-1-worker` | — (internal) | — | healthy | ✅ |
| 3 Compiler-1 | `compiler-1-redis` | `6379` container-internal | Docker-internal only | healthy | ✅ |
| 3 Compiler-1 | `compiler-1-db` | `5432` container-internal | Docker-internal only | healthy | ✅ |
| 4 App-2 | `app-2` | `APP2:8002` → container 8000 | Gateway-only (guard) | healthy | ✅ |
| 4 App-2 | `challenge-2` | `APP2:8080` → container 8080 | Gateway-only (guard) | healthy | ✅ |
| 5 Compiler-2 | `compiler-2-server` | `COMPILER2:2358` | Gateway + App machines only | healthy | ✅ |
| 5 Compiler-2 | `compiler-2-worker/-redis/-db` | internal | Docker-internal only | healthy | ✅ |
| 6 Compiler-3 | `compiler-3-server` | `COMPILER3:2358` | Gateway + App machines only | healthy | ✅ |
| 6 Compiler-3 | `compiler-3-worker/-redis/-db` | internal | Docker-internal only | healthy | ✅ |
| — | Supabase | `https://<project>.supabase.co` | App-1/App-2 → Internet | reachable (`/auth/v1/health` → 401 without a key = reached) | ✅ |

Reachability classes:

* **LAN-exposed:** Gateway `80` only. Compiler `2358` and App `8002`/`8080` are
  published on their own machines but **firewalled to the Gateway** by the
  DOCKER-USER guard, i.e. not reachable from candidate machines.
* **Gateway-only:** App `8002`, App `8080`.
* **Gateway + App machines only:** Compiler `2358`.
* **Docker-internal only:** `frontend:8080`, `gateway-api:8000`, Judge0 workers,
  PostgreSQL `5432`, Redis `6379`, the challenge container's `8080`.
* **External:** Supabase (the only Internet dependency).

---

## 2. Routing baseline (Traefik file provider)

| Path | Target | Priority |
|---|---|---|
| `/api/*` | `gateway-api` | 10 |
| `/auth/*`, `/questions/*`, `/submission/*`, `/assessment/*`, `/coding/*`, `/admin/*` | App pool `[APP1_URL, APP2_URL]` | 5 |
| `/challenge/*` (`/challenge` too) | Challenge pool `[APP1_CHALLENGE_URL, APP2_CHALLENGE_URL]` + `StripPrefix /challenge` | 8 |
| `/*` | `frontend` | 1 |

Candidate-visible URLs are always Gateway-relative (`/`, `/api/*`, `/challenge/`).
No internal address is ever sent to a browser.

---

## 3. Pool baseline (measured)

| Pool | Members | Distribution measured | Failover |
|---|---|---|---|
| App backends | `APP1_URL`, `APP2_URL` | 6 requests → **3 / 3** (Traefik access log) | both members verified serving individually |
| Challenge servers | `APP1_CHALLENGE_URL`, `APP2_CHALLENGE_URL` | 8 requests → **4 / 4** (Traefik access log) | `200` with either member stopped |
| Compiler nodes | `COMPILER_1..3_URL` | 6 executions → **+2 / +2 / +2** (per-node submission counts) | failover implemented in the pool client |

Pool membership is generated at container start from the environment, so a
machine that is not configured is simply absent from the list.

---

## 4. Functional baseline

| Area | Check | Result |
|---|---|---|
| Website | `/` serves the React SPA | 200 |
| Gateway API | `/api/health` | 200 `{"status":"ok"}` |
| Hands-On | `/challenge/` and `/challenge` → `<title>Employee Portal</title>` (not the Traefik dashboard) | 200 |
| Hands-On | `POST /challenge/login` through Traefik | 200 authenticated page; bad credentials rejected |
| Hands-On | one-shot submission, 409 on the second, no correctness leaked to the candidate | unchanged (logic untouched) |
| Push-to-iframe | iframe + "open in new tab" use same-origin `/challenge/` | verified in the frontend test suite |
| Assessment | MCQ / coding / descriptive / Hands-On logic, timer, auth, scoring | untouched (no changes to those code paths) |
| Pyodide | local runtime assets, worker execution | unchanged |
| Compiler | Python / C++ / Java / SQL on every node, compilation error, runtime error, time limit | verified per node |
| Isolation | challenge containers: no Supabase/platform credentials, no Docker socket, no host mounts, not privileged, `unless-stopped` | verified |
| Firewall | foreign LAN source vs. published ports | reachable without the guard, **all blocked** with it, allowlist still works |

---

## 5. Test baseline

| Suite | Result |
|---|---|
| `deployment-tests/system1-gateway-test.sh` | PASS |
| `deployment-tests/system2-app1-test.sh` | PASS |
| `deployment-tests/system3-compiler1-test.sh` | PASS |
| `deployment-tests/system4-app2-test.sh` | PASS |
| `deployment-tests/system5-compiler2-test.sh` | PASS |
| `deployment-tests/system6-compiler3-test.sh` | PASS |
| `deployment-tests/full-lan-test.sh` | PASS |
| `deployment-tests/firewall-kernel-test.sh` | PASS (13 passed, 0 failed) |
| Frontend (vitest) | 93/93 pass |
| Frontend build | succeeds |
| Frontend lint | my files: 0 errors (6 pre-existing warnings). Repo-wide: 4 pre-existing errors in `cpp-runner.worker.js` and `Instructions.test.jsx` |
| Backend (pytest) | 365 passed, **9 pre-existing failures** (`TestCompilerServiceIntegration`) |
| Gateway integration (`gateway/tests/test_phase3.py`) | 26 passed, **6 pre-existing failures** — proven pre-existing by re-running them against the previous (single-node) code |

### Pre-existing failures (not caused by this work, not "fixed" to go green)

1. **`test_c_accepted`** — the test sends malformed C: `\n` inside a non-raw
   Python string becomes a real newline, so `printf("hello` is unterminated
   (`missing terminating " character`).
2. **`test_java_accepted`** — Judge0 compiles `Main.java`; the test declares
   `public class Solution`. Identical on every node.
3. **`test_sql_accepted`, `test_sql_wrong_answer`, `test_sql_syntax_error`,
   `test_sql_multiple_queries`** — SQL expectations do not match the SQLite
   language configuration.
4. **`test_hostile_infinite_loop`** — Judge0's wall clock exceeds the test's
   10 s assertion.
5. **`TestCompilerServiceIntegration`** (backend, 9 tests) — mocks of the old
   single-compiler gateway contract; the platform now uses Judge0.

---

## 6. Known limitations carried into the baseline

* Compiler nodes run Judge0 with `privileged: true` and the Docker socket **on
  the worker** — required by Judge0's isolate sandbox design. The *challenge*
  containers have neither.
* Java needs per-node tuning; it is now applied automatically on every
  `docker compose up` (see `gateway/judge0/java-tuning.sql`).
* challenge-1/challenge-2 keep *separate* copies of the seeded database (both
  byte-identical), so neither can affect the other.
