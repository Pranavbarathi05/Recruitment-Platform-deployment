#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM 1 — GATEWAY test
#
# Checks: Traefik + frontend + gateway-api, the front-door HTTP endpoints, the
# application-backend pool (App-1/App-2), the Hands-On challenge through the
# Gateway, the compiler pool as seen by the Gateway, and that the Traefik
# dashboard is NOT what /challenge/ returns.
#
# Run it ON the Gateway machine for the container/port checks. Run it on any
# other machine and it still verifies the front door over the network, and
# additionally proves that App/Compiler machines are NOT directly reachable
# from a candidate machine.
#
#   cp deployment-tests/.env.example deployment-tests/.env   # fill in the IPs
#   ./deployment-tests/system1-gateway-test.sh
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="SYSTEM 1 — Gateway"
system_header "$NAME"

GATEWAY="http://${GATEWAY_IP:-127.0.0.1}:$GATEWAY_HTTP_PORT"

# ── This machine's own stack ─────────────────────────────────────────────────
if [ "$(dt_perspective "${GATEWAY_IP:-127.0.0.1}")" = "local" ]; then
  check_docker_environment
  section "Gateway containers"
  # shellcheck disable=SC2086
  check_containers $GATEWAY_CONTAINERS
  section "Published ports on this machine"
  check_local_ports "$GATEWAY_HTTP_PORT" "$GATEWAY_DASHBOARD_PORT"
else
  section "Local checks skipped"
  skip "Docker / container / port checks" "this script is running on $(dt_detect_ip), not on the Gateway"
fi

# ── Front door ───────────────────────────────────────────────────────────────
section "Gateway front door (the only candidate entry point)"
if [ -z "${GATEWAY_IP:-}" ]; then
  fail "GATEWAY_IP configured" "set it in deployment-tests/.env"
else
  check_http "website loads at /" "$GATEWAY/" 200
  check_http "login page loads at /login" "$GATEWAY/login" 200
  check_http "gateway API health" "$GATEWAY/api/health" 200 "ok"
  # The dashboard answers / with a redirect to /dashboard/ (Traefik default),
  # so accept 2xx or 3xx rather than requiring 200.
  check_http_code_in "Traefik dashboard still available (operator only)" \
    "http://$GATEWAY_IP:$GATEWAY_DASHBOARD_PORT/" "200 301 302 307 308"
fi

# ── Application backend pool ─────────────────────────────────────────────────
section "Application backend pool (Gateway → App machines)"
check_tcp_reachable "App-1 API" "$APP1_IP" "$APP1_HOST_PORT"
if [ -n "${APP2_IP:-}" ]; then
  check_tcp_reachable "App-2 API" "$APP2_IP" "$APP2_HOST_PORT"
else
  skip "App-2 API reachable" "APP2_IP not configured (App-2 not deployed)"
fi

if [ -n "${GATEWAY_IP:-}" ]; then
  # A POST to /auth/login with an empty body must reach FastAPI (a JSON error),
  # NOT the SPA's index.html — that proves the app-backend route is wired to an
  # application machine rather than falling through to the frontend.
  TMP_BODY="$(mktemp)"
  code="$(curl -s -o "$TMP_BODY" -w '%{http_code}' -m "$HTTP_TIMEOUT" \
          -X POST -H 'Content-Type: application/json' -d '{}' \
          "$GATEWAY/auth/login" 2>/dev/null || printf '000')"
  if [ "$code" = "000" ]; then
    fail "POST /auth/login reaches an App machine" "no HTTP response from $GATEWAY/auth/login"
  elif grep -q '"detail"' "$TMP_BODY"; then
    pass "POST /auth/login reaches an App machine" "HTTP $code with a FastAPI error body (not the SPA)"
  else
    fail "POST /auth/login reaches an App machine" "HTTP $code but the body is not a FastAPI response — is App-1 down?"
  fi
  rm -f "$TMP_BODY"
fi

# ── Hands-On challenge through the Gateway ───────────────────────────────────
section "Hands-On SQLi challenge through the Gateway"
if [ -n "${GATEWAY_IP:-}" ]; then
  check_http "/challenge/ returns the Employee Portal" "$GATEWAY/challenge/" 200 "Employee Portal"
  check_http "/challenge (no trailing slash) also works" "$GATEWAY/challenge" 200 "Employee Portal"

  # Distinct from the dashboard: the dashboard must NOT appear at /challenge/.
  dashbody="$(dt_http_body "$GATEWAY/challenge/")"
  if printf '%s' "$dashbody" | grep -qiE 'Traefik|Dashboard'; then
    fail "/challenge/ is not the Traefik dashboard" "the response looks like the dashboard"
  else
    pass "/challenge/ is not the Traefik dashboard"
  fi

  # The Hands-On login form must round-trip through the prefix (StripPrefix).
  formcode="$(curl -s -o /dev/null -w '%{http_code}' -m "$HTTP_TIMEOUT" \
              -X POST -d 'username=alice&password=alice123' \
              "$GATEWAY/challenge/login" 2>/dev/null || printf '000')"
  case "$formcode" in
    200) pass "POST /challenge/login works through the Gateway" "HTTP 200" ;;
    000) fail "POST /challenge/login works through the Gateway" "no response" ;;
    *)   fail "POST /challenge/login works through the Gateway" "HTTP $formcode (expected 200)" ;;
  esac

  # The challenge container must never be addressed directly by a candidate.
  if printf '%s' "$dashbody" | grep -qE '10\.[0-9]+\.[0-9]+\.[0-9]+:8080|192\.168\.[0-9.]+:8080'; then
    fail "no App machine address is exposed to the candidate" "the challenge page leaks an internal host:port"
  else
    pass "no App machine address is exposed to the candidate"
  fi
fi

# ── Compiler pool ────────────────────────────────────────────────────────────
check_compiler_pool_health "${GATEWAY_IP:-}" "$GATEWAY_HTTP_PORT"

# ── Candidate must not bypass the Gateway ────────────────────────────────────
section "Direct access from this machine"
if [ "$(dt_perspective "${GATEWAY_IP:-127.0.0.1}")" = "gateway" ] || [ "$(dt_perspective "${GATEWAY_IP:-127.0.0.1}")" = "local" ]; then
  skip "App/Compiler machines blocked from here" \
    "this IS the Gateway — an allowed source. Re-run this script on a candidate machine to verify the block"
else
  check_tcp_blocked "App-1 API" "$APP1_IP" "$APP1_HOST_PORT"
  check_tcp_blocked "App-1 challenge" "$APP1_IP" "$APP1_CHALLENGE_PORT"
  [ -n "${APP2_IP:-}" ] && check_tcp_blocked "App-2 API" "$APP2_IP" "$APP2_HOST_PORT"
  [ -n "${APP2_IP:-}" ] && check_tcp_blocked "App-2 challenge" "$APP2_IP" "$APP2_CHALLENGE_PORT"
  check_tcp_blocked "Compiler-1 API" "${COMPILER1_IP:-}" "$COMPILER1_API_PORT"
  [ -n "${COMPILER2_IP:-}" ] && check_tcp_blocked "Compiler-2 API" "$COMPILER2_IP" "$COMPILER2_API_PORT"
  [ -n "${COMPILER3_IP:-}" ] && check_tcp_blocked "Compiler-3 API" "$COMPILER3_IP" "$COMPILER3_API_PORT"
fi

dt_summary "$NAME"
