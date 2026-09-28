# Troubleshooting runbook

Failure modes that actually exist in this system, and the checks that locate
them. Commands run on the machine named in each section.

Quick triage:

```bash
# Gateway machine
cd gateway && docker compose ps                 # traefik / frontend / gateway-api healthy?
curl -s http://localhost/api/health             # helper API
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/            # 200 = SPA
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/login       # 200 = SPA route
curl -s http://localhost/api/execute/health      # compiler pool: every node "ok"
docker compose logs traefik --tail 50           # pool health-check messages
```

---

## 1. Website loads but every API call fails

**Symptom**: SPA opens, login/`fetch` says "Failed to fetch", or API URLs
return `index.html` instead of JSON.

- `POST /_api/auth/login` must reach the app pool. From the Gateway:
  `curl -s -X POST http://localhost/_api/auth/login -H 'Content-Type: application/json' -d '{}'`
  → a JSON 422 mentioning `email` means routing is fine; **HTML** means the
  `/_api` route lost its backend (see §2).
- Check `APP1_URL` / `APP2_URL` in `gateway/.env` (LAN IP, port 8002), then
  `cd gateway && docker compose up -d` (no rebuild needed for env changes).
- From the Gateway, probe each App machine directly:
  `curl -m 3 http://<APP_IP>:8002/` → `{"status":"Healthy",...}`.
  A timeout from the Gateway means the **DOCKER-USER guard** on that App
  machine is missing or allowlists the wrong IP:
  `sudo iptables -S DOCKER-USER` and re-run
  `sudo ./gateway/scripts/docker-port-guard.sh --ports "8002 8080" --gateway-ip <GATEWAY_IP>`.

## 2. 502 Bad Gateway (Traefik)

- On `/challenge/...` → challenge pool member down: check `challenge-1`/
  `challenge-2` on the App machines (`docker compose ps`), `APP1/2_CHALLENGE_URL`
  in `gateway/.env`, and `/health` on each: `curl http://<APP_IP>:8080/health`.
- On `/_api/...` → app pool member down: same checks with port 8002.
- Traefik health-checks every 10 s; a dead member leaves rotation within
  seconds. If **everything** 502s, `docker compose logs traefik` — an empty
  pool (all URLs unset) degrades to a deliberately closed port by design.
- The frontend nginx returns **404** for `/challenge` by design — seeing the
  SPA where the Employee Portal should be means Traefik's `/challenge` route
  is not active (reload the Gateway stack).

## 3. CORS errors (development only)

Through the Gateway everything is same-origin — CORS is not involved. CORS
only matters when the SPA runs on `:5173` against a backend on `:8000`:

- the backend allows origins listed in `CORS_ORIGINS`
  (default `http://localhost:5173`) — a mismatched trailing slash or port
  fails;
- auth is cookie-based: the origin must be listed **and** requests use
  `credentials: 'include'`. Fix the variable, restart the backend; never
  "fix" it with `*` (cookies would be rejected anyway).

## 4. Backend container not running / unhealthy

```bash
cd gateway/app-1 && docker compose ps            # or app-2
docker compose logs app-1 --tail 100
```

- Immediate exit / restart loop → read the logs first line: usually a bad or
  missing env value. The backend refuses to start when neither
  `SUPABASE_URL` nor `SUPABASE_JWT_SECRET` is set (`core/auth.py` raises at
  import).
- Healthcheck failing but logs quiet → `curl -s http://localhost:8002/` from
  the App machine; if that works, the host port is blocked or firewalled (§1).

## 5. Supabase connectivity

- From an App machine: `curl -s -o /dev/null -w "%{http_code}\n" https://<project>.supabase.co/auth/v1/health`
  → **401 means reachable** (the endpoint needs a key); only connection
  errors/000 are a problem. App machines need outbound Internet.
- 401 on every API call despite a login page that loads → wrong
  `SUPABASE_*` values (example placeholders left in `.env`) or the JWT
  verification path failing. Check `SUPABASE_JWT_SECRET` matches the project,
  and that the Supabase "Access Token (JWT) expiry" setting is `7200` (the
  backend caps sessions at 2 h but cannot extend the token).
- Migrations not applied → endpoints answer 500 naming a missing column.
  Apply the numbered SQL files in order (Supabase SQL Editor). Migrations
  `013` and `023` columns have code-level fallbacks: the platform keeps
  working on a database that has not yet had them applied.

## 6. Judge0 / compiler pool

Check the pool end to end from the Gateway:

```bash
curl -s http://localhost/api/execute/health          # backend + per-node status
curl -s http://localhost/api/execute/languages
curl -s -H "X-Judge0-Token: $TOKEN" http://<COMPILER_IP>:2358/about   # 200 authed, 401 no token
```

- **401 from `/about`** → `JUDGE0_AUTH_TOKEN` (gateway/.env **and** each
  app's `.env`) does not equal `AUTHN_TOKEN` in that node's
  `judge0/judge0.conf`. Fix and restart the affected containers
  (`docker compose up -d` — no rebuild).
- **Timeout/connection refused** → node down (`docker compose -p compiler-1 ps`),
  wrong `COMPILER_n_URL`/port, or the DOCKER-USER guard on the compiler
  machine not allowlisting the caller:
  `sudo ./gateway/scripts/docker-port-guard.sh --ports 2358 --gateway-ip <GATEWAY_IP> --gateway-ip <APP1_IP> --gateway-ip <APP2_IP>`.
- **`Couldn't find Submission` / HTTP 404 while polling** → a node's datastores
  are cross-wired: several Judge0 stacks sharing one Docker network. Each node
  needs its own private network (`deploy-compiler.sh` sets
  `COMPILER_NETWORK=<name>-net`); recreate with the script.
- **Java submissions fail to start** (`Could not allocate metaspace`) → the
  Java tuning was wiped by `down -v`; run
  `./gateway/judge0/apply-java-tuning.sh compiler-1` (or any `up`, which
  re-applies automatically) and confirm
  `./gateway/judge0/apply-java-tuning.sh compiler-1 --verify`.
- **`enable_per_process_and_thread_*` must not be forced to `false`** — this
  Judge0 build returns Internal Error (status 13). The backend omits those
  flags deliberately (`services/compiler.py`).
- Detailed Judge0 notes (cgroup v2, rlimits, memory semantics):
  `gateway/judge0/README.md`.

## 7. Docker networking

- `network system3 declared as external, but could not be found` →
  `docker network create system3` on that machine (Gateway, App machines, and
  any co-located Judge0 node).
- `Bind for 0.0.0.0:8080 failed: port is already allocated` → two stacks share
  one host: change `APPn_CHALLENGE_PORT` / `TRAEFIK_DASHBOARD_PORT` /
  `JUDGE0_PORT` (this only happens in the co-located setup; ports repeat
  harmlessly across machines).
- `COPY dsc-recruit/... not found` → the app repo is missing or misnamed at
  the repo root (see root `README.md` §3).

## 8. Challenge server (SQL-injection Hands-On)

```bash
curl -s http://localhost:8080/health            # on the App machine → {"status":"ok"}
curl -s http://localhost/challenge/ | grep -o '<title>[^<]*</title>'   # via Gateway → Employee Portal
curl -s -X POST http://localhost/challenge/login -d 'username=x&password=x' # bad creds rejected
```

- `challenge-1`/`challenge-2` are isolated on purpose: no credentials, no
  Internet, own SQLite copy. Do not expect them to reach Supabase.
- The candidate iframe must always use the Gateway-relative `/challenge/` —
  an `http://<APP_IP>:8080/...` URL in the browser is a regression (the App
  ports are firewalled from candidates anyway).
- One-shot semantics are intentional: a second submission answers **409**.

## 9. WASM challenges and client-side Run

- **Pyodide/duckdb 404** → the frontend image was built without the copied
  assets. Run `npm install` (postinstall copies them) and **rebuild** the
  frontend image; check `curl -s -o /dev/null -w "%{http_code}\n"
  http://localhost/pyodide/pyodide.js` → 200.
- **Run never finishes** → first-time runtime initialisation has a generous
  timeout; a terminated run reports TLE by design and the worker is recreated.
  Refresh and retry; persistent hangs → check browser console and
  `VITE_NETWORK_MONITOR_URL`-style env misconfigurations in the built SPA.
- **Pandas/SQL run locally**: no server is involved — "server unavailable"
  errors on these challenges are not possible; they are validation failures.
- **Network monitor helper errors** are logged but never candidate-facing and
  never terminate an assessment (by design).

## 10. Stale images / code not live

| Changed | Rebuild |
|---|---|
| `dsc-recruit/apps/frontend/` | `cd gateway && docker compose up -d --build frontend` |
| `dsc-recruit/apps/backend/` | `cd gateway/app-1 && docker compose up -d --build` (and `app-2`) |
| compose/Traefik files | that stack: `docker compose up -d --build` |
| `.env` / `judge0.conf` | restart only: `docker compose up -d` |
| Judge0 node config | `docker compose -p compiler-N up -d` |

Confirm the live version: `curl -s http://localhost/api/info` (version +
uptime = restart time). Containers show their image id in `docker ps` if you
need to compare with `docker images`.

## 11. Migrations

- Apply files **in numeric order**; all are idempotent (`IF NOT EXISTS`).
- A partially applied file can be re-run; nothing relies on a single
  transaction across files.
- Symptom of a missed migration: 500 with `column ... does not exist` in
  `docker compose logs app-1`.
- Never edit an applied migration — append `026_…`, `027_…`.

## 12. Wrong or missing environment variables

Fast checks:

```bash
grep -E "^(APP1_URL|APP2_URL|COMPILER_[123]_URL|JUDGE0_AUTH_TOKEN|EXECUTION_BACKEND)" gateway/.env
grep -E "^(SUPABASE_URL|COMPILER_[123]_URL|JUDGE0_AUTH_TOKEN)" gateway/app-1/.env
grep -E "^(COMPILER_NAME|COMPILER_NETWORK|JUDGE0_BIND|JUDGE0_PORT)" gateway/judge0/.env
grep "^AUTHN_TOKEN=" gateway/judge0/judge0.conf
docker compose config    # in the stack folder: renders the effective config
```

Typical mistakes: token mismatch across `.env` files, `APP2_URL` set on the
Gateway but App-2's `.env` never filled in, `COMPILER_n_URL` pointing at
`judge0-server` (only resolvable on the same host) from a remote machine, and
`.env` edits without `docker compose up -d`.

## 13. Sessions and auth oddities

- **401 mid-assessment after ~2 h** should NOT interrupt a running attempt —
  the `dsc_assessment` capability cookie keeps the mid-assessment endpoints
  alive. If a candidate *is* bounced to login, they can log back in and
  resume: `/auth/assessment-access` returns the attempt id, and
  `POST /assessment/start` resumes the frozen attempt.
- **403 "Admin access required"** → `profiles.is_admin` is false for that user.
- **CSRF failures on writes** → the SPA must receive `/auth/csrf` first and
  echo the cookie in `X-CSRF-Token`; a stale cookie pair is fixed by logging
  out and back in.

## 14. Known pre-existing test failures

Not production bugs — recorded so they are not rediscovered as new:
6 frontend selector failures in `AdminModules.test.jsx` /
`AdminPanel.test.jsx` (see [`TESTING.md`](TESTING.md) §2).
