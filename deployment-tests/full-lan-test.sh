#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# FULL LAN TEST — the complete chain, end to end
#
# Run this from the Gateway (or an admin machine) once all six systems are up.
# It exercises exactly what a candidate does, and nothing else:
#
#   candidate → Gateway             → frontend                (the website)
#   candidate → Gateway → App-1/2   → Supabase                (login path)
#   candidate → Gateway → challenge pool                      (Hands-On)
#   candidate → Gateway → App-1/2   → Compiler pool → result   (code execution)
#
# It also proves the negative: an App machine's API/challenge port and every
# compiler's API port must NOT be reachable from a candidate machine, and the
# internal address must never be handed to the browser.
#
# The final section names the layer that broke when something fails.
#
#   cp deployment-tests/.env.example deployment-tests/.env   # fill in the IPs
#   ./deployment-tests/full-lan-test.sh
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="FULL LAN TEST"
system_header "$NAME"

if [ -z "${GATEWAY_IP:-}" ]; then
  fail "GATEWAY_IP configured" "set it in deployment-tests/.env (copy from .env.example)"
  dt_summary "$NAME"
  exit $?
fi

GATEWAY="http://$GATEWAY_IP:$GATEWAY_HTTP_PORT"
FAILED_LAYERS=""

note_layer_failure() {  # layer description
  case " $FAILED_LAYERS " in
    *" $1 "*) ;;
    *) FAILED_LAYERS="$FAILED_LAYERS $1" ;;
  esac
}

# ── 1. Candidate → Gateway → frontend ────────────────────────────────────────
section "CHAIN 1 — candidate → Gateway → frontend"
check_http "website (/) loads through the Gateway" "$GATEWAY/" 200
check_http "login page (/login) loads" "$GATEWAY/login" 200
check_http "gateway-api health (/api/health)" "$GATEWAY/api/health" 200 "ok"

# ── 2. Candidate → Gateway → App backend → Supabase ─────────────────────────
section "CHAIN 2 — candidate → Gateway → App machine → Supabase"
TMP_BODY="$(mktemp)"
login_code="$(curl -s -o "$TMP_BODY" -w '%{http_code}' -m "$HTTP_TIMEOUT" \
             -X POST -H 'Content-Type: application/json' -d '{}' \
             "$GATEWAY/auth/login" 2>/dev/null || printf '000')"
if [ "$login_code" = "000" ]; then
  fail "POST /auth/login reaches an App machine" "no HTTP response (Traefik could not reach APP1_URL/APP2_URL)"
  note_layer_failure "App backend (App-1/App-2)"
elif grep -q '"detail"' "$TMP_BODY"; then
  pass "POST /auth/login reaches an App machine" "HTTP $login_code, FastAPI error body (validation, as expected for an empty body)"
else
  fail "POST /auth/login reaches an App machine" "HTTP $login_code but no FastAPI body — the request did not reach the app"
  note_layer_failure "App backend (App-1/App-2)"
fi
rm -f "$TMP_BODY"
info "a real login also proves Supabase: use the browser, or run system2-app1-test.sh on the App-1 machine"

# ── 3. Candidate → Gateway → challenge pool ─────────────────────────────────
section "CHAIN 3 — candidate → Gateway → challenge pool (Hands-On)"
check_http "/challenge/ returns the Employee Portal" "$GATEWAY/challenge/" 200 "Employee Portal"
challenge_body="$(dt_http_body "$GATEWAY/challenge/")"
if printf '%s' "$challenge_body" | grep -qiE 'Traefik|Dashboard'; then
  fail "/challenge/ is the challenge, not the Traefik dashboard" "the response looks like the dashboard"
  note_layer_failure "challenge routing (Traefik /challenge/*)"
else
  pass "/challenge/ is the challenge, not the Traefik dashboard"
fi
if printf '%s' "$challenge_body" | grep -qE '(10|192\.168)\.[0-9]+\.[0-9]+\.[0-9]+:8080'; then
  fail "no internal challenge address leaks to the candidate" "the page contains an App-machine host:port"
  note_layer_failure "candidate URL hygiene"
else
  pass "no internal challenge address leaks to the candidate"
fi
form_code="$(curl -s -o /dev/null -w '%{http_code}' -m "$HTTP_TIMEOUT" \
            -X POST -d 'username=alice&password=alice123' \
            "$GATEWAY/challenge/login" 2>/dev/null || printf '000')"
if [ "$form_code" = "200" ]; then
  pass "the Hands-On login form round-trips through the Gateway" "HTTP 200"
else
  fail "the Hands-On login form round-trips through the Gateway" "HTTP $form_code (expected 200)"
  note_layer_failure "challenge routing (Traefik /challenge/*)"
fi

# ── 4. Candidate → Gateway → App → compiler pool → result ───────────────────
section "CHAIN 4 — candidate → Gateway → /api/execute → compiler pool → result"
EXEC_BODY="$(mktemp)"
exec_code="$(curl -s -o "$EXEC_BODY" -w '%{http_code}' -m 90 \
  -X POST -H 'Content-Type: application/json' \
  -d '{"language":"python","source_code":"print(6*7)","test_cases":[{"input":"","expected_output":"42"}],"limits":{"time_limit_seconds":5,"memory_limit_mb":256,"max_output_bytes":4096}}' \
  "$GATEWAY/api/execute" 2>/dev/null || printf '000')"
if [ "$exec_code" = "000" ]; then
  fail "code execution works through the Gateway" "no HTTP response from /api/execute"
  note_layer_failure "gateway-api (/api/execute)"
elif dt_have python3 && python3 -c "
import json,sys
try:
    d=json.load(open('$EXEC_BODY'))
except Exception:
    sys.exit(2)
print('status=', d.get('status'), 'passed=', d.get('passed_tests'), '/', d.get('total_tests'), 'error=', (d.get('error') or '')[:120])
sys.exit(0 if d.get('status')=='accepted' and d.get('passed_tests')==1 else 1)
" ; then
  pass "code execution works through the Gateway" "HTTP $exec_code, Python test case accepted"
else
  detail="$(head -c 300 "$EXEC_BODY" 2>/dev/null)"
  if printf '%s' "$detail" | grep -q 'compiler_unavailable'; then
    fail "code execution works through the Gateway" "compiler_unavailable — no compiler node answered (/api/execute/health has the per-node detail)"
    note_layer_failure "compiler pool"
  else
    fail "code execution works through the Gateway" "HTTP $exec_code: $detail"
    note_layer_failure "gateway-api (/api/execute)"
  fi
fi
rm -f "$EXEC_BODY"

check_compiler_pool_health "$GATEWAY_IP" "$GATEWAY_HTTP_PORT"

# ── 5. Dependency reachability (Gateway → everything it needs) ──────────────
section "DEPENDENCY REACHABILITY (Gateway → App and Compiler machines)"
for pair in "App-1 API:$APP1_IP:$APP1_HOST_PORT" "App-1 challenge:$APP1_IP:$APP1_CHALLENGE_PORT" \
            "App-2 API:${APP2_IP:-}:$APP2_HOST_PORT" "App-2 challenge:${APP2_IP:-}:$APP2_CHALLENGE_PORT" \
            "Compiler-1:${COMPILER1_IP:-}:$COMPILER1_API_PORT" \
            "Compiler-2:${COMPILER2_IP:-}:$COMPILER2_API_PORT" \
            "Compiler-3:${COMPILER3_IP:-}:$COMPILER3_API_PORT"; do
  label="${pair%%:*}"; rest="${pair#*:}"; host="${rest%%:*}"; port="${rest##*:}"
  if [ -z "$host" ]; then
    skip "$label reachable from here" "not configured (not deployed yet)"
    continue
  fi
  if dt_tcp_open "$host" "$port"; then
    pass "$label reachable from here" "$host:$port"
  else
    # Only the Gateway may reach these ports, so a failure here is a real break.
    if dt_is_local "$GATEWAY_IP"; then
      fail "$label reachable from here" "$host:$port — the Gateway cannot reach it (firewall rule missing, wrong IP, or the machine is down)"
      case "$label" in App-*) note_layer_failure "App machine $label" ;; Compiler-*) note_layer_failure "compiler node $label" ;; esac
    else
      info "$label ($host:$port) not reachable from this machine — expected from a candidate machine"
    fi
  fi
done

# ── 6. Candidate must not bypass the Gateway ────────────────────────────────
section "CANDIDATE BYPASS CHECK (must be blocked)"
if dt_is_local "$GATEWAY_IP"; then
  skip "direct access blocked" "this machine IS the Gateway (an allowed source) — run this test from a candidate laptop"
else
  check_tcp_blocked "App-1 API" "$APP1_IP" "$APP1_HOST_PORT"
  check_tcp_blocked "App-1 challenge" "$APP1_IP" "$APP1_CHALLENGE_PORT"
  [ -n "${APP2_IP:-}" ] && check_tcp_blocked "App-2 API" "$APP2_IP" "$APP2_HOST_PORT"
  [ -n "${APP2_IP:-}" ] && check_tcp_blocked "App-2 challenge" "$APP2_IP" "$APP2_CHALLENGE_PORT"
  check_tcp_blocked "Compiler-1 API" "${COMPILER1_IP:-}" "$COMPILER1_API_PORT"
  [ -n "${COMPILER2_IP:-}" ] && check_tcp_blocked "Compiler-2 API" "$COMPILER2_IP" "$COMPILER2_API_PORT"
  [ -n "${COMPILER3_IP:-}" ] && check_tcp_blocked "Compiler-3 API" "$COMPILER3_IP" "$COMPILER3_API_PORT"
fi

# ── 7. Per-system summaries, if the machine is reachable enough to say ──────
section "POOL LOAD DISTRIBUTION"
pool_body="$(dt_http_body "$GATEWAY/api/execute/languages")"
if [ -n "$pool_body" ] && dt_have python3; then
  printf '%s' "$pool_body" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print('  (could not parse /api/execute/languages)'); raise SystemExit(0)
langs=d.get('languages', {})
ok=[k for k,v in langs.items() if v.get('judge0_id')]
bad=[k for k,v in langs.items() if not v.get('judge0_id')]
print(f'  backend={d.get(\"backend\")}  languages available: {\", \".join(ok) or \"none\"}')
if bad: print(f'  languages NOT available: {\", \".join(bad)}')
"
fi
info "round-robin across nodes is verified by the unit tests (gateway-api + app backend) and"
info "by repeated submissions while watching each compiler node's container logs."

# ── 8. What broke ───────────────────────────────────────────────────────────
section "DEPENDENCY REPORT"
if [ -z "$FAILED_LAYERS" ]; then
  info "no dependency failures detected"
else
  info "failed layer(s):$FAILED_LAYERS"
  info "start with the first one listed — later layers depend on it"
fi

dt_summary "$NAME"
