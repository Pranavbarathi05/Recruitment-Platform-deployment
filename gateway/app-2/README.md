# App 2 — the second application backend (SYSTEM 4)

App-2 is the **same application as App-1**, deployed on its own physical
machine so the Gateway can distribute candidate traffic across both. Every
request still enters through the Gateway; candidates never reach App-2
directly.

```
                    ┌──────────────┐
candidate ────────▶ │ GATEWAY :80  │
                    └──────┬───────┘
                 ┌─────────┴─────────┐
                 ▼                   ▼
        APP-1 (8002/8080)     APP-2 (8002/8080)   ── firewall: Gateway IP only
                 │                   │
                 └────────┬──────────┘
                          ▼
              Compiler-1 / Compiler-2 / Compiler-3
```

## What runs here

| Container     | Host port (default) | Purpose                                     |
|---------------|---------------------|---------------------------------------------|
| `app-2`       | `8002` → 8000       | FastAPI backend (login, questions, coding, Hands-On scoring) |
| `challenge-2` | `8080` → 8080       | the SQLi "Employee Portal" Hands-On challenge |

`challenge-2` is built from `Dockerfile.challenge`, which packages exactly the
same challenge implementation and seeded database as `challenge-1`, with **no
platform credentials, no Docker socket, no privileged mode and no host mounts**.
The two challenge containers keep separate copies of the challenge database.

The port numbers match App-1's on purpose: they are on different machines, so
they cannot collide. Both are configurable (`APP2_HOST_PORT`,
`APP2_CHALLENGE_PORT`) if this host needs something else.

## Deploy

```bash
cd gateway/app-2
cp .env.example .env        # Supabase keys + the compiler pool addresses
docker compose up -d --build
docker compose ps           # wait until both containers are "healthy"
```

Machine-wide, once:

```bash
docker network create system3     # only needed if a compiler node runs on THIS host
```

Verify locally:

```bash
curl -s http://localhost:8002/        # {"status":"Healthy","message":"API is working"}
curl -s http://localhost:8080/health  # challenge-2 → {"status":"ok",...}
```

Find this machine's LAN IP — the Gateway needs it:

```bash
hostname -I | awk '{print $1}'       # Linux, e.g. 192.168.1.24
ipconfig                             # Windows
```

## Firewall (required)

Docker-published ports are **not** filtered by UFW/INPUT rules: they are
DNAT'ed in PREROUTING and forwarded through the FORWARD chain, never touching
INPUT. Restrict them with the shared DOCKER-USER guard instead:

```bash
sudo install -m 755 ../scripts/docker-port-guard.sh /opt/recruit/
sudo /opt/recruit/docker-port-guard.sh --gateway-ip <GATEWAY_LAN_IP>
sudo iptables -S DOCKER-USER      # verify
```

Persist it so the rules survive a reboot:

```bash
sudo install -m 644 ../scripts/docker-port-guard.service /etc/systemd/system/
# edit ExecStart in that unit: --gateway-ip <GATEWAY_LAN_IP>
sudo systemctl daemon-reload && sudo systemctl enable --now docker-port-guard
```

Expected result: both published ports answer the **Gateway** and time out for
everyone else (`curl -m 3 http://<APP2_LAN_IP>:8002/` from a candidate laptop
must fail).

## Register App-2 with the Gateway

On the **Gateway** machine, in `gateway/.env`:

```bash
APP2_URL=http://<APP2_LAN_IP>:8002
APP2_CHALLENGE_URL=http://<APP2_LAN_IP>:8080
```

then `cd gateway && docker compose up -d` (no rebuild needed). Traefik now
load-balances the application backend and `/challenge/*` across App-1 and
App-2. Check the routing table at `http://<GATEWAY_LAN_IP>:8080`.

## Points to be careful about

- **One database.** App-2 uses the same `SUPABASE_URL` project as App-1. Never
  create a second recruitment project, and never copy App-1's `.env` file here —
  fill in this machine's `.env` from `.env.example`.
- **Compiler addresses.** `COMPILER_1_URL`..`COMPILER_3_URL` must be the
  compiler machines' **LAN** addresses (`http://<COMPILERn_LAN_IP>:2358`).
  `http://judge0-server:2358` only resolves if a compiler runs on this host.
- **Same token.** `JUDGE0_AUTH_TOKEN` must equal `AUTHN_TOKEN` in every
  compiler machine's `gateway/judge0/judge0.conf`.
- **`.env` is never committed** (`gateway/.gitignore` covers it).

See the repository-root `DEPLOYMENT.md` for the full six-system runbook and
`../app-1/README.md` for the App-1 equivalent.
