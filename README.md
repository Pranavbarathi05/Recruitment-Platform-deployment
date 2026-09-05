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
   GATEWAY machine  ── the front door (website pages + login/questions traffic)
        │
        ▼
   APP-01 machine   ── the application brain (login, questions, submissions) ⇄ Supabase (cloud database)
        │
        ▼
   EXECUTION machine ── runs candidate code safely (Judge0 service)
```

- Candidates **only need a browser**. Nothing is installed on their computers.
- The website is served by the **Gateway** machine at `http://<gateway-LAN-IP>/`.
- Login and all data go through **App-01**, which talks to **Supabase** (a cloud database
  you configure with keys — see section 5).
- Candidate code is executed by **Judge0** on the execution machine (the repository's
  older documents call this "System 3").

**Implemented today vs. planned (do not expect the planned ones to work):**

| Machine in the target design | Status in this repository |
|---|---|
| Machine 1 — Gateway | ✅ Implemented (`gateway/docker-compose.yml`) |
| Machine 2 — App-01 | ✅ Implemented (`gateway/app-1/`) |
| Machine 3 — App-02 | ❌ Not implemented — future |
| Machine 4 — Compiler-01 | ⚠️ Exists as the **legacy** execution service (`gateway/compiler-1/`), not used by default |
| Machines 5–6 — Compiler-02/03 | ❌ Not implemented — future |
| Execution service (Judge0) | ✅ Implemented and the default (`gateway/judge0/`) |

The minimum working deployment needs **3 machines** (or just 1 for a demo — section 6).

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

Three configuration files are needed. They hold keys and addresses and are **never
committed to Git** (the repo already ignores them).

| File | Create it from | What it configures |
|---|---|---|
| `gateway/.env` | `gateway/.env.example` | the Gateway stack + addresses of the other machines |
| `gateway/app-1/.env` | `gateway/app-1/.env.example` | App-01 + its Supabase keys |
| `gateway/judge0/judge0.conf` | `gateway/judge0/judge0.conf.example` | the Judge0 code-execution service |

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
| `gateway-api-local` | helper API (health, sessions) and forwards code execution to Judge0 |
| `app-1-local` | the application brain — login, questions, submissions (talks to Supabase) |
| `compiler-1-local` | the simple built-in code runner used when Judge0 is not running |

For the demo, tell the helper API to use the built-in runner (Judge0 is not part of the
demo stack): in `gateway/.env` set
```
EXECUTION_BACKEND=compiler1
```
then start again (`docker compose -f docker-compose.local.yml up -d`). Without Judge0
**Run/Submit of code will not work** unless you do this.

**Check it worked:**
```bash
curl -s http://localhost/ | head -c 100        # website HTML → looks like "<!DOCTYPE html..."
curl -s http://localhost/api/health            # → {"status":"ok","service":"gateway-api",...}
curl -s -X POST http://localhost/auth/login \
     -H "Content-Type: application/json" -d '{}'   # → a JSON error mentioning "email" (422) proves the login path reaches the app brain
```

The website is at **http://localhost/** (`/login` is the sign-in page).

---

## 7. Start everything — Option B: the real LAN deployment

This is the setup for the actual recruitment drive: separate machines on the college
network. Full machine-by-machine details are in [`gateway/DEPLOYMENT.md`](gateway/DEPLOYMENT.md);
here is the short version.

**Machine roles and commands:**

| Machine | Folder to work in | Command to start | Port others use |
|---|---|---|---|
| Gateway | `<repo>/gateway/` | `docker compose up -d --build` | **80** (candidates), 8080 (dashboard) |
| App-01 | `<repo>/gateway/app-1/` | `docker compose up -d --build` | 8002 (Gateway only) |
| Execution (Judge0) | `<repo>/gateway/judge0/` | `docker compose up -d` | 2358 (Gateway only) |

Order matters — **start App-01 first, then the execution machine, then the Gateway**
(the Gateway needs to know the other machines' LAN IPs in `gateway/.env`).

On **every** machine, once:
```bash
docker network create system3
```

On **App-01** (assumes the repo layout from section 3):
```bash
cd Recruitment-Platform-deployment/gateway/app-1
cp .env.example .env            # then fill in the Supabase keys (section 5)
docker compose up -d --build
curl -s http://localhost:8002/  # → {"status":"Healthy","message":"API is working"}
```
Find this machine's LAN IP — you will paste it into the Gateway's `.env`:
```bash
hostname -I | awk '{print $1}'   # Linux; example output: 192.168.1.23
```

On the **execution machine (Judge0)**:
```bash
cd Recruitment-Platform-deployment/gateway/judge0
# make sure judge0.conf exists and has real random values (section 5)
docker compose up -d
docker compose ps               # wait until all four judge0-* containers are healthy
```

On the **Gateway**:
```bash
cd Recruitment-Platform-deployment/gateway
cp .env.example .env
# edit .env:  APP1_URL=http://<APP-01-LAN-IP>:8002
#             JUDGE0_AUTH_TOKEN=<same as AUTHN_TOKEN in judge0.conf>
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
need Internet access — everything is served from the Gateway machine. (The App-01 and
execution machines are the ones that may need Internet, for Supabase and container images.)

---

## 9. "Is everything working?" — the checklist

Run these from the **Gateway machine** (works the same for the demo stack):

```bash
cd gateway   # (demo: add -f docker-compose.local.yml to every docker compose command)

docker compose ps                        # every container should say "healthy"
curl -s http://localhost/api/health      # Gateway helper API
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/     # 200 = website OK
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/login # 200 = login page OK
curl -s http://localhost/api/execute/health    # code execution service (Judge0)
```

Then walk through it like a candidate: open `http://<gateway-LAN-IP>/login`, log in,
open a coding question, press **Run**, then **Submit**.

Checklist:
- [ ] Gateway running (`docker compose ps` shows traefik/frontend/gateway-api healthy)
- [ ] App-01 running and healthy (`curl http://<APP-01-IP>:8002/` from the Gateway machine)
- [ ] Execution service healthy (`/api/execute/health` says `"status":"ok"`)
- [ ] Supabase reachable (a real login succeeds — see section 5 for the keys)
- [ ] Candidate can open the platform from another computer
- [ ] Login works
- [ ] Coding page loads
- [ ] Run works
- [ ] Submit works

App-02 and Compiler-02/03 are **not implemented** — no checks exist for them yet.

---

## 10. Stop / restart / update

All commands run from the folder of the stack you are touching
(`gateway/`, `gateway/app-1/`, `gateway/judge0/` — demo adds `-f docker-compose.local.yml`).

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

# 3. Confirm the new version is live
curl -s http://localhost/api/info       # shows version + uptime (restart time)
docker compose ps
```

What needs rebuilding after a change:
| You changed... | Rebuild... |
|---|---|
| Website code (`dsc-recruit/apps/frontend/`) | `frontend` (from `gateway/`) |
| Application backend (`dsc-recruit/apps/backend/`) | `app-1` (from `gateway/app-1/`) |
| Deployment config in `gateway/` | that stack (`docker compose up -d --build`) |
| `gateway/.env` or `app-1/.env` | just restart: `docker compose up -d` (no `--build`) |

Nothing needs rebuilding for `gateway/judge0/` config changes — `docker compose up -d` there.

---

## 11. When something goes wrong

**PROBLEM: candidate cannot open the website at all**
→ CHECK: Is the Gateway machine on and `docker compose ps` showing `traefik` healthy?
→ CHECK: Did you use the right LAN IP? Run `hostname -I | awk '{print $1}'` on the Gateway.
→ FIX: `cd gateway && docker compose up -d --build` on the Gateway machine. Check the
  firewall allows port 80 (`sudo ufw allow 80/tcp` on Ubuntu).

**PROBLEM: website opens, but login says "Failed to fetch"**
→ CHECK: Is App-01 running? On the App-01 machine: `cd gateway/app-1 && docker compose ps`.
→ CHECK: From the Gateway machine, can you reach App-01? `curl http://<APP-01-IP>:8002/`
→ CHECK: Is `APP1_URL` in `gateway/.env` set to App-01's current LAN IP?
→ FIX: Correct `APP1_URL`, then `cd gateway && docker compose up -d` (no rebuild needed).

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
  placeholders)? Does the App-01 machine have Internet access to reach Supabase?
→ FIX: Fix the keys, then `cd gateway/app-1 && docker compose up -d` (restart only).

**PROBLEM: code "Run" or "Submit" fails with a gateway/execution error**
→ CHECK: `curl -s http://localhost/api/execute/health` from the Gateway machine.
→ CHECK: Is the Judge0 stack up on the execution machine, and does `JUDGE0_AUTH_TOKEN`
  in `gateway/.env` match `AUTHN_TOKEN` in `judge0.conf`?
→ FIX: see `gateway/judge0/README.md` for detailed Judge0 troubleshooting.

More troubleshooting: [`gateway/DEPLOYMENT.md`](gateway/DEPLOYMENT.md).

---

## 12. Where to go deeper

| Document | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | how a request travels, every container, every port, what's implemented vs. future |
| [`gateway/DEPLOYMENT.md`](gateway/DEPLOYMENT.md) | the full multi-machine LAN guide (firewall, ports, per-machine checks) |
| [`gateway/README.md`](gateway/README.md) | technical reference for the Gateway stack (env vars, routing, tests) |
| [`gateway/judge0/README.md`](gateway/judge0/README.md) | the Judge0 code-execution service in detail |
| [`gateway/monitoring/README.md`](gateway/monitoring/README.md) | optional server-monitoring dashboards (Grafana) |
| [`gateway/app-1/README.md`](gateway/app-1/README.md) | the App-01 application backend container |

## 13. Map of this repository

```
Recruitment-Platform-deployment/
├── README.md                  ← you are here — the only guide you need to start
├── docs/ARCHITECTURE.md       ← how the system works inside
├── dsc-recruit/               ← the application repo (you clone it here; see section 3)
├── gateway/
│   ├── docker-compose.yml         ← Gateway machine start file (traefik + website + helper API)
│   ├── docker-compose.local.yml   ← one-laptop DEMO start file (everything included)
│   ├── .env / .env.example        ← Gateway configuration (never commit .env)
│   ├── app-1/                     ← App-01 machine (application backend container)
│   ├── gateway-api/               ← helper API: health, sessions, forwards code execution
│   ├── frontend/                  ← builds the website from dsc-recruit/apps/frontend
│   ├── traefik/                   ← front-door routing rules
│   ├── judge0/                    ← execution machine: safe candidate-code runner (default)
│   ├── compiler-1/                ← legacy simple code runner (not used by default)
│   ├── compiler_client/           ← small library for the legacy runner
│   ├── monitoring/                ← optional dashboards (Grafana/Prometheus)
│   └── tests/                     ← deployment tests that run against a live stack
└── load-tests/                ← (untracked) local load-testing leftovers; ignore
```
