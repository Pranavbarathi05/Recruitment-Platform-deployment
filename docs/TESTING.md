# Testing

Every suite in the repository, how to run it, and what it covers. Counts below
were re-measured on **2026-09-28** (unit suites; the live suites need a
running stack — see the note at the bottom).

## 1. Backend — `dsc-recruit/apps/backend` (pytest)

```bash
cd dsc-recruit/apps/backend
.venv/bin/python -m pytest test_main.py test_assessment_planner.py \
    test_assessment_planning.py test_module_config_admin.py utils/ -q
# → 846 passed
```

| File | ~Tests | Covers |
|---|---|---|
| `test_main.py` | 546 | FastAPI app: auth (cookie session, 2-hour ceiling, CSRF), assessment capability cookie, assessment start/questions/answers/submit, **coding Run/Submit incl. harness typing-import and `error`/`harness_error` surfacing**, admin endpoints, network-integrity termination, `TestCompilerServiceIntegration` (Judge0 mock contract) |
| `test_assessment_planner.py` | 138 | The pure planner: scope/tier rules, exclusivity, MCQ split, exact descriptive/hands-on allocation, shared-module dedup, seeds/fingerprints, error kinds |
| `test_assessment_planning.py` | 106 | The orchestration layer around the planner (DB row resolution, config families, no-legacy-fallback guarantees) |
| `test_module_config_admin.py` | 39 | Module-config endpoints incl. pool preflight validation |
| `utils/` | 9 | Compiler-pool round-robin/failover and time helpers |

The backend suite runs entirely offline (Supabase and Judge0 are mocked).

## 2. Frontend — `dsc-recruit/apps/frontend` (Vitest)

```bash
cd dsc-recruit/apps/frontend
npm test            # vitest run
# → 33 files, 337 tests: 331 pass, 6 pre-existing failures (below)
npm run test:watch  # watch mode
```

Covers: harness/runner logic (worker lifecycle, timeouts, stale-result
protection), coding UI, MCQ/descriptive/hands-on workspace, fullscreen entry
and exit-countdown behaviour, network-integrity monitor, WASM runners and
validators, local Pyodide/DuckDB asset verification, admin pages
(domains/MCQ/coding/descriptive/hands-on/modules/results/remarks),
eligibility and exclusivity on the selection page.

**Pre-existing failures (6, in files recent work did not touch):**

- `AdminModules.test.jsx` — 4: selector ambiguity in the module-config form
  tests after tier/network controls were added.
- `AdminPanel.test.jsx` — 2: `getByRole('button', {name:'Save'})` matches
  multiple buttons in the remark dialog.

They are recorded, not silently skipped — see `BASELINE.md` §5.

## 3. Network monitor agent — `dsc-recruit/apps/network-monitor-agent`

```bash
cd dsc-recruit/apps/network-monitor-agent
../backend/.venv/bin/python -m pytest test_agent.py -q   # → 23 passed
```

Ping is mocked; the tests never emit real ICMP.

## 4. Gateway helper API — `gateway/gateway-api/tests`

```bash
cd gateway/gateway-api
python3 -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements.txt
pytest -q            # → 49 passed
```

Sessions, health/info, the `/api/execute` contract and the Judge0
language/pool proxy logic — no running stack needed.

## 5. Legacy runner — `gateway/compiler-1/tests`

```bash
cd gateway/compiler-1
python3 -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements.txt     # includes pytest
pytest -q            # → 37 passed
```

Unit tests for the legacy execution service (off by default).

## 6. Live integration tests — `gateway/tests` (needs a running stack)

```bash
cd gateway
python3 -m venv .venv-integration && source .venv-integration/bin/activate
pip install -r requirements-integration.txt
pytest tests -v      # test_app1_deployment, test_phase3, test_integration, test_lan_connectivity
```

These exercise the real Traefik → gateway-api → compiler path (they call
`POST /api/execute`). File names still carry old "phase" labels; they test
today's endpoints. Requirements: the Gateway stack up, `.env` configured, and
the execution backend reachable.

## 7. Deployment probes — `deployment-tests/` (needs a running stack)

```bash
cp deployment-tests/.env.example deployment-tests/.env   # six IPs + token
./deployment-tests/system1-gateway-test.sh               # … through system6-compiler3-test.sh
./deployment-tests/full-lan-test.sh                      # end-to-end from the Gateway
sudo ./deployment-tests/firewall-kernel-test.sh --ports "8002 8080" --restore-prod
```

Read-only probes (PASS/FAIL/SKIP per check, non-zero exit on failure) that
adapt to where they run: on the machine itself (containers, health, firewall
guard, challenge isolation, Supabase reachability), on the Gateway
(reachability), or on a candidate machine (verifies the ports are **blocked**).
Some checks need `sudo`; `RESTART_TESTS=1` enables an intrusive challenge
restart check. They add real load — do not run them on a compiler node during
a live drive. Details: `deployment-tests/README.md`.

## 8. Lint / build

```bash
cd dsc-recruit/apps/frontend
npm run lint     # eslint
npm run build    # vite build (runs the Pyodide/DuckDB copy first)
```

Known lint noise: pre-existing warnings/errors in files unrelated to recent
work (recorded in `BASELINE.md` §5).

## What is *not* covered

- No end-to-end browser test (Playwright/Cypress) exists in the repository —
  the candidate journey is covered by component tests plus the live
  deployment probes.
- The legacy `gateway/tests` suite and the deployment probes are **not** run
  in CI; they require pre-configured infrastructure.
