# Deployment tests — one script per physical machine

Each system in the six-machine deployment has its own test script. They are
read-only probes: they never change a service's configuration, and they skip
anything that is not deployed yet instead of failing.

| Script | System | Run it on |
|---|---|---|
| `system1-gateway-test.sh` | 1 — Gateway (Traefik, frontend, gateway-api) | the Gateway |
| `system2-app1-test.sh` | 2 — App-1 (backend + challenge-1) | App-1 |
| `system3-compiler1-test.sh` | 3 — Compiler-1 (Judge0) | Compiler-1 |
| `system4-app2-test.sh` | 4 — App-2 (backend + challenge-2) | App-2 |
| `system5-compiler2-test.sh` | 5 — Compiler-2 (Judge0) | Compiler-2 |
| `system6-compiler3-test.sh` | 6 — Compiler-3 (Judge0) | Compiler-3 |
| `full-lan-test.sh` | all six, end to end | the Gateway |

Plus two helpers used by the scripts: `lib.sh` (shared checks) and
`judge0_check.py` (real C++/Java/Python executions against one compiler node).

## Configure once

```bash
cp deployment-tests/.env.example deployment-tests/.env
# edit it: GATEWAY_IP, APP1_IP, COMPILER1_IP, ... and JUDGE0_AUTH_TOKEN
```

Find each machine's LAN IP **on that machine**:

```bash
hostname -I | awk '{print $1}'     # Linux — first IPv4 address
ip -4 addr                          # Linux — if there are several interfaces
ipconfig                            # Windows — IPv4 Address of the active adapter
```

Use the address of the interface on the **same network as the other machines**.
Do not use a VPN/tailscale (`100.x`) or Docker (`172.x`) address: those cannot be
reached by the other machines.

Any value can also be given inline, which is handy for a one-off check:

```bash
GATEWAY_IP=10.0.0.10 APP1_IP=10.0.0.11 ./deployment-tests/system1-gateway-test.sh
```

## Run

```bash
# everything, from the Gateway
./deployment-tests/full-lan-test.sh

# or one machine at a time (on that machine)
./deployment-tests/system2-app1-test.sh
```

Every script prints `PASS` / `FAIL` / `SKIP` per check and a summary, and exits
non-zero when something failed — so they can be chained in CI or a drive-day
script:

```bash
for s in system1-gateway system2-app1 system3-compiler1; do
  ./deployment-tests/$s-test.sh || echo "!! $s FAILED"
done
```

## What the scripts adapt to

The App and Compiler scripts detect **where they are running** and check the
right thing from that vantage point:

- **on the machine itself** → Docker, containers, health, local ports, the
  firewall guard, challenge isolation, Supabase reachability;
- **on the Gateway** → that the machine is reachable (it is an allowed source);
- **on any other machine (a candidate)** → that the machine is **blocked**.

That is how one script proves both halves of "the Gateway can reach App-1, and a
candidate cannot". Run the App/Compiler scripts from a candidate laptop as well
as from the Gateway to cover the whole matrix.

## Notes

- Some checks need `sudo` (the firewall guard inspection). Without root they
  report `SKIP` with a hint rather than a failure.
- `RESTART_TESTS=1` enables an intrusive check that restarts a challenge
  container to prove it comes back healthy and keeps serving the Employee
  Portal. It is off by default.
- `JUDGE0_AUTH_TOKEN` is only needed for the API-authentication checks; without
  it those are skipped.
- The tests add load to the platform (each compiler execution check runs six
  real submissions). Do not run them on a compiler node during a live drive.
