# Infrastructure Monitoring (LAN/admin only)

Self-hosted, deployment-side monitoring for the recruitment platform LAN. It
watches **infrastructure** (host + containers) only — no application code is
modified and no custom application metrics are invented.

```
 System 1 / System 2 / System 3 (Docker containers + one host)
        │                        │
        │ node-exporter         │ cAdvisor
        │ (host CPU/RAM/disk)   │ (per-container CPU/RAM/net, incl. Judge0)
        ▼                        ▼
        └───────────▶ Prometheus (scrape_interval 15s, retention 15d)
                          │
                          ▼
                     Grafana  (provisioned datasource + dashboard)
```

## Components

| Service         | Image                          | Port / binding            | Purpose                          |
|-----------------|--------------------------------|---------------------------|----------------------------------|
| `node-exporter` | `prom/node-exporter:v1.7.0`    | internal (9100)           | Host CPU / RAM / disk / load     |
| `cadvisor`      | `gcr.io/cadvisor/cadvisor:v0.47.2` | internal (8080)       | Per-container metrics (all containers) |
| `prometheus`    | `prom/prometheus:v2.53.0`      | `127.0.0.1:9090`          | Scrape + store (15d retention)   |
| `grafana`       | `grafana/grafana:10.4.2`       | `0.0.0.0:3001` (LAN/admin) | Dashboards                       |

- Grafana is the only LAN-facing port (`http://<LAN_IP>:3001`). Prometheus is
  loopback-only. node-exporter / cAdvisor are internal Docker-network only and
  are **not** routed through Traefik.
- The security boundary for `:3001` is the LAN/firewall policy; change the
  admin password from the `.env` defaults (see `.env.example`).
- Anonymous sign-up is disabled (`GF_USERS_ALLOW_SIGN_UP=false`).

## Start / stop

```bash
cd gateway/monitoring
cp .env.example .env   # optional; set a strong GRAFANA_ADMIN_PASSWORD
docker compose up -d
docker compose ps                 # all healthy
docker compose down               # stop (keeps metric data)
docker compose down -v            # stop and wipe metric data
```

## Access

| What        | URL                                        |
|-------------|--------------------------------------------|
| Grafana     | `http://<LAN_IP>:3001` (admin / password from `.env`) |
| Prometheus  | `http://127.0.0.1:9090` (host-local only)  |

The datasource (`Prometheus`) and the dashboard
(**Platform Infrastructure Overview** under the *Infrastructure* folder) are
auto-provisioned — no manual setup.

## Dashboard panels

- **Host**: CPU %, RAM %, RAM available, disk % (root), disk free, load/cores, uptime.
- **Containers**: CPU by compose project, memory by compose project, network
  RX/TX, top-15 container CPU share, top-15 container memory, containers-up count.

Judge0 and platform containers appear automatically via cAdvisor
(`judge0-server`, `judge0-worker`, `judge0-db`, `judge0-redis`,
`traefik`, `frontend`, `gateway-api`, `app-1`). No Judge0-internal queue
metrics exist without adding a metrics endpoint to Judge0 itself; container
resource usage is the visibility provided here.

## Current local simulation vs. real multi-machine

**Now** — one physical host runs the whole simulation: the `node` job covers
that host; `cadvisor` covers every container on it (System 1, App 1/compiler-1,
Judge0, monitoring). Labels are therefore the *compose project / container
name*, not physical machine identities.

**Later** — when System 2 and System 3 become separate physical machines:

1. On each machine install node-exporter (and cAdvisor if it hosts Docker),
   e.g. as systemd units or a tiny compose file, bound to the LAN interface.
2. Record the LAN addresses in `.env` (`SYSTEM1_EXPORTER` / `SYSTEM2_EXPORTER` /
   `SYSTEM3_EXPORTER`, see `.env.example`).
3. Add them to `prometheus/systems.yml` (file_sd, re-read every 60 s) with
   `system`/`role` labels — see the template in that file. No restart of
   Prometheus is required.
4. The provisioned dashboard queries are instance-agnostic, so the new series
   appear automatically; add a `system` template variable later if per-machine
   filtering is wanted.

## Verification

```bash
# targets (loopback Prometheus API)
curl -s http://127.0.0.1:9090/api/v1/targets | python3 -m json.tool

# real data
curl -s 'http://127.0.0.1:9090/api/v1/query?query=100%20-%20avg(rate(node_cpu_seconds_total%5B1m%5D))%2A100'
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum(container_memory_working_set_bytes%7Bname%3D%22judge0-server%22%7D)'
```

Availability monitoring of application endpoints (`/api/health`, Judge0 API)
is intentionally left to Docker healthchecks + container status in cAdvisor.
A Prometheus blackbox-exporter can be added later if endpoint-level probes are
wanted (documented, not required now).