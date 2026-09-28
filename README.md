# Recruitment Platform — Deployment (Start Here)

This repository contains everything needed to run the DSC Recruitment Platform on the
college network. **This is the one guide to follow.** It takes you from a fresh laptop to
candidates using the platform, without assuming you know Docker, Traefik, or networking.

> Words you will see, in plain English:
> - **Container** — a ready-to-run program package. Docker starts and stops containers for you.
> - **Docker Compose** — a tool that starts several containers together, from one file.
> - **Traefik** — the "front door". It receives every request and forwards it to the right container.
> - **LAN** — the local college/hotspot network. LAN IP = your machine's address on that network.

---

## 1. What this deployment is

```
Candidate computers (just a browser)
        │
        ▼
   GATEWAY machine   ── the front door (website pages + all traffic, Traefik :80)
        │
        ├─▶ APP-01 machine ──┐   the application brain (login, questions,
        └─▶ APP-02 machine ──┤   submissions, scoring) ⇄ Supabase (cloud DB)
                             │
        ├─▶ EXECUTION-1 (Judge0 :2358) ──┐  run candidate code safely
        ├─▶ EXECUTION-2 (Judge0 :2359) ──┤  (round-robin + failover)
        └─▶ EXECUTION-3 (Judge0 :2360) ──┘
```

- Candidates **only need a browser**. Nothing is installed on their computers.
- The website is served by the **Gateway** machine at `http://<gateway-LAN-IP>/`.
- Login and all data go through the **App** machines (App-1 + App-2, load-balanced),
  which talk to **Supabase** (a cloud database you configure with keys — see section 5).
- Candidate code is executed by the **Judge0 compiler nodes** (Compiler-1/2/3).
- Hands-On challenges: the SQL-injection challenge is served by isolated
  challenge servers on the App machines (at `/challenge/` on the Gateway); SQL and
  Pandas WASM challenges run entirely in the candidate's browser.

**All six systems are implemented** (they can run on six machines, or all on one
machine for a demo — section 6):

| System in the target design | Status in this repository |
|---|---|
| System 1 — Gateway (Traefik + frontend + gateway-api) | ✅ `gateway/docker-compose.yml` |
| System 2 — App-1 (+ challenge-1) | ✅ `gateway/app-1/` |
| System 3 — Compiler-1 (Judge0 :2358) | ✅ `gateway/judge0/` |
| System 4 — App-2 (+ challenge-2) | ✅ `gateway/app-2/` |
| System 5 — Compiler-2 (Judge0 :2359) | ✅ `gateway/judge0/` |
| System 6 — Compiler-3 (Judge0 :2360) | ✅ `gateway/judge0/` |
| Legacy single runner (`gateway/compiler-1/`) | ⚠️ kept for the one-laptop demo only; **off by default** (`EXECUTION_BACKEND=judge0`) |

The full machine-by-machine runbook is [`DEPLOYMENT.md`](DEPLOYMENT.md).

---

## 2. Before you start — software to install

You need exactly two things on each machine that runs containers.

**1. Docker Desktop (Windows/Mac) or Docker Engine + Compose plugin (Linux)**
Docker runs the containers. Compose comes with it and reads our start-up files.

Check it is installed:
```bash
docker --version        # should print something like: Docker version 27.x
docker compose version  # should print: Docker Compose version v2.x
```

**2. Git**
Git downloads the project files.

Check it is installed:
```bash
git --version   # should print something like: git version 2.x
```

Nothing else is needed — no Python, no Node.js, no manual Traefik setup.

---

## 3. Folder structure — where the two repositories live

The deployment repo and the application repo must be arranged **exactly** like this:

```
recruitment/                                  ← parent folder (name doesn't matter)
└── Recruitment-Platform-deployment/          ← this repo (name = whatever you cloned it as)
    ├── gateway/                              ← deployment configuration (all start files)
    ├── docs/
    ├── README.md
    └── dsc-recruit/                          ← ⚠️ the application repo goes HERE, inside this repo
```

**Why inside?** The container build files read the application code from the folder
`dsc-recruit/` next to them:
- `gateway/app-1/Dockerfile` copies `dsc-recruit/apps/backend/` (the application backend).
- `gateway/frontend/Dockerfile` copies `dsc-recruit/apps/frontend/` (the website code).

**If your application folder has a different name**, either rename the folder to
`dsc-recruit`, or change the `COPY dsc-recruit/...` lines in those two Dockerfiles to
match your folder name. Nothing else needs to change.

---

## 4. Get the files (cloning)

Open a terminal in the parent folder and run:

```bash
# 1. Download this deployment repository
git clone https://github.com/Pranavbarathi05/Recruitment-Platform-deployment.git

# 2. Go inside it — the application repo is cloned HERE (see section 3)
cd Recruitment-Platform-deployment

# 3. Download the application repository
git clone https://github.com/dsc-jssstu/dsc-recruit.git
```

Check the result — this exact layout is required:
```bash
ls
# you should see:  gateway  dsc-recruit  README.md  docs  ...
```

---

## 5. Configure the secrets (one-time)

Configuration files are needed per stack. The main three hold keys and addresses and
are **never committed to Git** (the repo already ignores them):

| File | Create it from | What it configures |
|---|---|---|
| `gateway/.env` | `gateway/.env.example` | the Gateway stack + addresses of the other machines |
| `gateway/app-1/.env` | `gateway/app-1/.env.example` | App-01 + its Supabase keys |
| `gateway/judge0/judge0.conf` | `gateway/judge0/judge0.conf.example` | the Judge0 code-execution service |

Additional git-ignored files used by the full six-system deployment (see
[`DEPLOYMENT.md`](DEPLOYMENT.md) §4): `gateway/app-2/.env`,
`gateway/judge0/.env` (per-node identity), `deployment-tests/.env`.

```bash
# from the repository root (Recruitment-Platform-deployment/)
cp gateway/.env.example gateway/.env
cp gateway/app-1/.env.example gateway/app-1/.env
cp gateway/judge0/judge0.conf.example gateway/judge0/judge0.conf
```

Now edit each file:

**`gateway/app-1/.env`** — needed for real logins:
```
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
SUPABASE_JWT_SECRET=<your-jwt-secret>
```
These values come from your Supabase project page (Project Settings → API). Without
them the platform starts but nobody can log in.

**`gateway/.env`** — needed so the Gateway can find the other machines:
```
APP1_URL=http://<APP-01-LAN-IP>:8002
JUDGE0_AUTH_TOKEN=<same value as AUTHN_TOKEN in gateway/judge0/judge0.conf>
```
Leave the rest at their defaults for a first run.

**`gateway/judge0/judge0.conf`** — replace every `change-me-...` value with a long
random string. If you have the `openssl` command:
```bash
openssl rand -hex 24   # run it 3 times; paste one value each into
                       # REDIS_PASSWORD, POSTGRES_PASSWORD, SECRET_KEY_BASE
openssl rand -hex 32   # paste into AUTHN_TOKEN and into JUDGE0_AUTH_TOKEN in gateway/.env
```
`AUTHN_TOKEN` (in judge0.conf) and `JUDGE0_AUTH_TOKEN` (in gateway/.env) **must be the
same value** — it is the shared password between the Gateway and the execution service.

> ⚠️ **Never commit the real `.env` / `judge0.conf` files to Git.** They contain keys that
> give access to your database. Only the `.example` files are committed.

---

## 6. Start everything — Option A: one laptop (demo/test)

Everything runs on a single machine. Perfect for trying the system or a small demo.
Use this **only if** candidates and the operator share one laptop or a very small network.

Open a terminal **in the repository root** (the folder containing `gateway/`), then:

```bash
# 1. One-time: create the shared Docker network the services talk over
docker network create system3

# 2. Go into the gateway folder — all start commands run from here
cd gateway

# 3. Start the demo stack (builds the website and services the first time; be patient)
docker compose -f docker-compose.local.yml up -d --build

# 4. Watch the containers come up healthy (wait until every STATUS says "healthy")
docker compose -f docker-compose.local.yml ps
```

What you just started, in plain language:

| Container | What it does |
|---|---|
| `traefik-local` | the front door — receives everything on port 80 and forwards it |
| `frontend-local` | the website pages the candidate sees |
| `gateway-api-local` | helper API (health, sessions, `/api/execute`) |
| `app-1-local` | the application brain — login, questions, submissions (talks to Supabase) |
| `compiler-1-local` | the simple built-in code runner used when Judge0 is not running |

For the demo, tell the helper API to use the built-in runner (Judge0 is not part of
the demo stack): in `gateway/.env` set
```
EXECUTION_BACKEND=compiler1
```
then start again (`docker compose -f docker-compose.local.yml up -d`). Without Judge0
**Run/Submit of code will not work** unless you do this.

Note: the demo stack routes the API directly (`/auth/*`, `/questions/*`, …) and has
no Hands-On `/challenge/` route — SQL-injection challenges need the real stack.

**Check it worked:**
```bash
curl -s http://localhost/ | head -c 100        # website HTML → looks like "<!DOCTYPE html..."
curl -s http://localhost/api/health            # → {"status":"ok","service":"gateway-api",...}
curl -s -X POST http://localhost/auth/login \
     -H "Content-Type: application/json" -d '{}'   # → a JSON error mentioning "email" (422) proves the login path reaches the app brain
```

(The real six-system stack prefixes every frontend API call with `/_api` —
`POST /_api/auth/login` there; the demo stack uses the direct paths above.)

The website is at **http://localhost/** (`/login` is the sign-in page).

---

## 7. Start everything — Option B: the real LAN deployment

This is the setup for the actual recruitment drive: separate machines on the college
network. The complete machine-by-machine runbook — all six systems, IPs, firewall
rules and the test suite — is [`DEPLOYMENT.md`](DEPLOYMENT.md); this section is the
short version.

**Machine roles and commands:**

| System | Folder to work in | Command to start | Port others use |
|---|---|---|---|
| 1 Gateway | `<repo>/gateway/` | `docker compose up -d --build` | **80** (candidates), 8080 (dashboard) |
| 2 App-1 | `<repo>/gateway/app-1/` | `docker compose up -d --build` | 8002 (API), 8080 (challenge) — Gateway only |
| 3 Compiler-1 | anywhere in the repo | `./gateway/scripts/deploy-system3-compiler1.sh` | 2358 — Gateway + Apps only |
| 4 App-2 | `<repo>/gateway/app-2/` | `docker compose up -d --build` | 8002, 8080 — Gateway only |
| 5 Compiler-2 | anywhere in the repo | `./gateway/scripts/deploy-system5-compiler2.sh` | 2359 — Gateway + Apps only |
| 6 Compiler-3 | anywhere in the repo | `./gateway/scripts/deploy-system6-compiler3.sh` | 2360 — Gateway + Apps only |

Order matters — **start the Compiler nodes first, then App-1/App-2, then the
Gateway** (the Gateway pools then find live backends immediately). Every system has
a matching script in `gateway/scripts/` (`deploy-system1-gateway.sh` …
`deploy-system6-compiler3.sh` and the `down-` twins).

On **the Gateway and App machines**, once:
```bash
docker network create system3
```
(Compiler nodes get a private network from their deploy script — the script
creates it for you.)

On **App-01** (assumes the repo layout from section 3; App-2 is identical in
`gateway/app-2/`):
```bash
cd Recruitment-Platform-deployment/gateway/app-1
cp .env.example .env            # then fill in the Supabase keys (section 5)
docker compose up -d --build
curl -s http://localhost:8002/        # → {"status":"Healthy","message":"API is working"}
curl -s http://localhost:8080/health  # → {"status": "ok"} (challenge server)
```
Find this machine's LAN IP — you will paste it into the Gateway's `.env`:
```bash
hostname -I | awk '{print $1}'   # Linux; example output: 192.168.1.23
```

On the **execution machines (Compiler-1/2/3)** — the deploy script creates the
node's private network, waits for health and verifies the API:
```bash
cd Recruitment-Platform-deployment
# judge0.conf must exist with real random values (section 5), and
# gateway/judge0/.env must carry the node's identity (COMPILER_NAME,
# JUDGE0_BIND=0.0.0.0, JUDGE0_PORT) — see DEPLOYMENT.md §4
./gateway/scripts/deploy-system3-compiler1.sh    # :2358
./gateway/scripts/deploy-system5-compiler2.sh    # :2359
./gateway/scripts/deploy-system6-compiler3.sh    # :2360
curl -s -H "X-Judge0-Token: <token>" http://localhost:2358/about   # 200 when authed
```

On the **Gateway**:
```bash
cd Recruitment-Platform-deployment/gateway
cp .env.example .env
# edit .env:  APP1_URL / APP2_URL = http://<APPn_LAN_IP>:8002
#             APP1_CHALLENGE_URL / APP2_CHALLENGE_URL = http://<APPn_LAN_IP>:8080
#             COMPILER_1_URL / COMPILER_2_URL / COMPILER_3_URL = http://<IP>:2358|2359|2360
#             JUDGE0_AUTH_TOKEN=<same as AUTHN_TOKEN in every judge0.conf>
docker compose up -d --build
docker compose ps               # wait until traefik, frontend, gateway-api are healthy
```

**Find the Gateway's LAN IP and give it to candidates:**
```bash
hostname -I | awk '{print $1}'    # on the Gateway machine; e.g. 192.168.1.10
```

---

## 8. Candidate computers

Candidates need **nothing installed**.

1. Connect the candidate computer to the same college network (LAN/Wi-Fi/hotspot) as the Gateway.
2. Open Chrome (or any modern browser).
3. Go to: `http://<gateway-LAN-IP>/` — for example `http://192.168.1.10/`
4. Sign in at `http://<gateway-LAN-IP>/login`.

Candidates do **not** need Git, Docker, Python, or any other software. They do **not**
need Internet access — everything is served from the Gateway machine. (The App and
compiler machines are the ones that may need Internet, for Supabase and container images.)

---

## 9. "Is everything working?" — the checklist

Run these from the **Gateway machine** (works the same for the demo stack):

```bash
cd gateway   # (demo: add -f docker-compose.local.yml to every docker compose command)

docker compose ps                        # every container should say "healthy"
curl -s http://localhost/api/health      # Gateway helper API
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/     # 200 = website OK
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/login # 200 = login page OK
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/challenge/health  # 200 = challenge pool OK
curl -s http://localhost/api/execute/health    # compiler pool: every node "ok"
```

Then walk through it like a candidate: open `http://<gateway-LAN-IP>/login`, log in,
open a coding question, press **Run**, then **Submit**.

Checklist:
- [ ] Gateway running (`docker compose ps` shows traefik/frontend/gateway-api healthy)
- [ ] App-1 and App-2 running and healthy (`curl http://<APPn-IP>:8002/` from the Gateway machine)
- [ ] Compiler-1/2/3 healthy (`/api/execute/health` says every node `"ok"`)
- [ ] Supabase reachable (a real login succeeds — see section 5 for the keys)
- [ ] Candidate can open the platform from another computer
- [ ] Login works
- [ ] Domain selection and assessment start work
- [ ] Coding page loads; Run works; Submit works
- [ ] Hands-On challenge opens at `/challenge/` (real stack) or WASM challenges run

For per-machine automated checks use `deployment-tests/system1..6-*.sh` and
`deployment-tests/full-lan-test.sh` (see [`DEPLOYMENT.md`](DEPLOYMENT.md) §7–8).

---

## 10. Stop / restart / update

All commands run from the folder of the stack you are touching
(`gateway/`, `gateway/app-1/`, `gateway/app-2/`, `gateway/judge0/` — demo adds
`-f docker-compose.local.yml`; compiler nodes can also be managed with
`gateway/scripts/deploy-compiler.sh` / `down-compiler.sh`).

```bash
# STOP everything (safe; nothing is deleted)
docker compose down

# START again (no rebuild needed if nothing changed)
docker compose up -d

# RESTART one container after a config change
docker compose up -d --build <service-name>    # e.g. frontend, gateway-api, app-1

# SEE LOGS of one container (useful when something fails)
docker compose logs <service-name> --tail 50
```

**Updating later:**

```bash
# 1. Get the new code (from the repository root)
git pull
cd dsc-recruit && git pull && cd ..

# 2. Rebuild what changed — from gateway/:
docker compose up -d --build           # rebuilds website + helper API
cd app-1 && docker compose up -d --build && cd ..   # after an application/backend change
# (same for app-2; compiler nodes only need `docker compose -p compiler-N up -d`)

# 3. Confirm the new version is live
curl -s http://localhost/api/info       # shows version + uptime (restart time)
docker compose ps
```

What needs rebuilding after a change:
| You changed... | Rebuild... |
|---|---|
| Website code (`dsc-recruit/apps/frontend/`) | `frontend` (from `gateway/`) |
| Application backend (`dsc-recruit/apps/backend/`) | `app-1` (from `gateway/app-1/`) and `app-2` (from `gateway/app-2/`) |
| Deployment config in `gateway/` | that stack (`docker compose up -d --build`) |
| `gateway/.env` or `app-1/.env` | just restart: `docker compose up -d` (no `--build`) |

Nothing needs rebuilding for `gateway/judge0/` config changes — `docker compose up -d` there.

---

## 11. When something goes wrong

A full runbook (CORS, Traefik 502s, Supabase, Judge0 auth, WASM, stale images,
migrations, env vars) is in [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
The everyday ones:

**PROBLEM: candidate cannot open the website at all**
→ CHECK: Is the Gateway machine on and `docker compose ps` showing `traefik` healthy?
→ CHECK: Did you use the right LAN IP? Run `hostname -I | awk '{print $1}'` on the Gateway.
→ FIX: `cd gateway && docker compose up -d --build` on the Gateway machine. Docker
  publishes port 80 itself (published ports bypass ufw — see `docs/TROUBLESHOOTING.md`
  and the DOCKER-USER guard in `DEPLOYMENT.md` §6), but any upstream firewall or
  switch policy must allow it.

**PROBLEM: website opens, but login says "Failed to fetch"**
→ CHECK: Is App-1 (and App-2, if used) running? On the App machine:
  `cd gateway/app-1 && docker compose ps`.
→ CHECK: From the Gateway machine, can you reach it? `curl http://<APP-IP>:8002/`
→ CHECK: Are `APP1_URL` / `APP2_URL` in `gateway/.env` set to the current LAN IPs?
→ FIX: Correct the `.env`, then `cd gateway && docker compose up -d` (no rebuild needed).

**PROBLEM: a container keeps stopping / says "unhealthy"**
→ CHECK: `docker compose logs <name> --tail 50` — the last lines usually say why.
→ COMMON CAUSE: a missing or wrong value in `.env` / `judge0.conf`.

**PROBLEM: "network system3 declared as external, but could not be found"**
→ FIX: run `docker network create system3` on that machine, then start again.

**PROBLEM: build fails with "COPY dsc-recruit/... not found"**
→ CHECK: Is the application repo cloned **inside** this repo, named exactly
  `dsc-recruit`? (section 3)
→ FIX: `git clone https://github.com/dsc-jssstu/dsc-recruit.git` from the repository root.

**PROBLEM: login page opens, real users can't log in (or data errors appear)**
→ CHECK: Are the Supabase keys in `gateway/app-1/.env` real values (not the example
  placeholders)? Does the App machine have Internet access to reach Supabase?
→ FIX: Fix the keys, then `cd gateway/app-1 && docker compose up -d` (restart only).

**PROBLEM: code "Run" or "Submit" fails with an execution error**
→ CHECK: `curl -s http://localhost/api/execute/health` from the Gateway machine
  (every compiler node should say `"ok"`).
→ CHECK: Are the compiler nodes up, and does `JUDGE0_AUTH_TOKEN` in `gateway/.env`
  **and** in each app's `.env` match `AUTHN_TOKEN` in every `judge0.conf`?
→ FIX: see `gateway/judge0/README.md` for detailed Judge0 troubleshooting.

More troubleshooting: [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) and
[`gateway/DEPLOYMENT.md`](gateway/DEPLOYMENT.md).

---

## 12. Where to go deeper

| Document | What it covers |
|---|---|
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | the full six-system runbook: IPs, firewall, verification, rollback |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | how a request travels, every container, every port, execution paths |
| [`docs/API.md`](docs/API.md) | backend + gateway API endpoints (method, auth, shapes) |
| [`docs/ASSESSMENT.md`](docs/ASSESSMENT.md) | how assessments are planned: domains, tiers, modules, scoring |
| [`docs/CANDIDATE_GUIDE.md`](docs/CANDIDATE_GUIDE.md) | candidate-facing flow: selection, workspace, Run/Submit, rules |
| [`docs/ADMIN_GUIDE.md`](docs/ADMIN_GUIDE.md) | admin pages: questions, modules, config, results, remarks |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | local development setup, env vars, migrations |
| [`docs/TESTING.md`](docs/TESTING.md) | every test suite and how to run it |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | failure modes and runbook |
| [`gateway/DEPLOYMENT.md`](gateway/DEPLOYMENT.md) | per-stack LAN reference (firewall, ports, per-machine checks) |
| [`gateway/README.md`](gateway/README.md) | technical reference for the Gateway stack (env vars, routing, tests) |
| [`gateway/judge0/README.md`](gateway/judge0/README.md) | the Judge0 code-execution service in detail |
| [`gateway/monitoring/README.md`](gateway/monitoring/README.md) | optional server-monitoring dashboards (Grafana) |
| [`gateway/app-1/README.md`](gateway/app-1/README.md), [`gateway/app-2/README.md`](gateway/app-2/README.md) | the application backend containers |
| [`BASELINE.md`](BASELINE.md) | measured baseline of the running deployment |
| [`deployment-tests/README.md`](deployment-tests/README.md) | the per-machine probe scripts |

## 13. Map of this repository

```
Recruitment-Platform-deployment/
├── README.md                  ← you are here — the only guide you need to start
├── DEPLOYMENT.md              ← the six-system LAN runbook
├── BASELINE.md                ← measured baseline of the running deployment
├── docs/                      ← architecture, API, assessment, candidate/admin guides,
│                                development, testing, troubleshooting
├── dsc-recruit/               ← the application repo (you clone it here; see section 3)
├── deployment-tests/          ← read-only probe scripts, one per system + full-lan-test
├── gateway/
│   ├── docker-compose.yml         ← Gateway machine start file (traefik + website + helper API)
│   ├── docker-compose.local.yml   ← one-laptop DEMO start file (older direct-prefix routing)
│   ├── dockerdemoup.sh            ← start any/all six stacks on one machine
│   ├── .env / .env.example        ← Gateway configuration (never commit .env)
│   ├── scripts/                   ← per-system deploy/down scripts, port guard, compiler launcher
│   ├── app-1/                     ← App-1 machine (backend + challenge-1)
│   ├── app-2/                     ← App-2 machine (backend + challenge-2)
│   ├── gateway-api/               ← helper API: health, sessions, /api/execute
│   ├── frontend/                  ← builds the website from dsc-recruit/apps/frontend
│   ├── traefik/                   ← Traefik static settings (routing table is rendered from .env)
│   ├── judge0/                    ← Compiler-1/2/3: Judge0 execution nodes (default backend)
│   ├── compiler-1/                ← legacy simple code runner (not used by default)
│   ├── compiler_client/           ← small library for the legacy runner
│   ├── monitoring/                ← optional dashboards (Grafana/Prometheus)
│   └── tests/                     ← live integration tests (need a running stack)
└── load-tests/                ← local load-testing tooling (not part of the deployment)
```
