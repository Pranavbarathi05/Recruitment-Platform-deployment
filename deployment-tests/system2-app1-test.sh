#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM 2 — APP-1 test
#
# Checks: Docker, the app-1 and challenge-1 containers, backend + challenge
# health, Supabase reachability (probed from inside the container), the
# DOCKER-USER firewall guard, challenge isolation (no platform credentials, no
# Docker socket, no host mounts), the compiler pool reachable from App-1, and —
# depending on where you run it — that the Gateway CAN reach App-1 and that a
# candidate machine CANNOT.
#
# Run on the App-1 machine:
#   ./deployment-tests/system2-app1-test.sh
# Run on the Gateway (verifies App-1 is reachable from the allowed source):
#   APP1_IP=10.0.0.11 ./deployment-tests/system2-app1-test.sh
# Run on a candidate laptop (verifies App-1 is NOT directly reachable):
#   GATEWAY_IP=10.0.0.10 APP1_IP=10.0.0.11 ./deployment-tests/system2-app1-test.sh
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="SYSTEM 2 — App-1"
if [ -z "${APP1_IP:-}" ]; then
  APP1_IP="$(dt_detect_ip)"
  ASSUMED_LOCAL=1
fi
system_header "$NAME"
[ "${ASSUMED_LOCAL:-0}" = "1" ] && info "APP1_IP was not configured — assuming this machine IS App-1 ($APP1_IP)"

check_app_system "App-1" "$APP1_IP" "$APP1_HOST_PORT" "$APP1_CHALLENGE_PORT" app-1 challenge-1

# ── App-1 specific configuration checks ──────────────────────────────────────
if [ "$(dt_perspective "$APP1_IP")" = "local" ] && dt_have docker; then
  section "App-1 configuration"
  env_dump="$(dt_container_env app-1)"
  supabase_url="$(printf '%s\n' "$env_dump" | awk -F= '/^SUPABASE_URL=/{sub(/^SUPABASE_URL=/,""); print; exit}')"
  if [ -z "$supabase_url" ]; then
    fail "Supabase project configured" "no SUPABASE_URL in the app-1 container"
  elif printf '%s' "$supabase_url" | grep -q 'your-project'; then
    fail "Supabase project configured" "SUPABASE_URL is still the placeholder value"
  else
    pass "Supabase project configured" "$supabase_url (one shared recruitment database)"
  fi

  if printf '%s' "$env_dump" | grep -qiE '^APP2_|app-2'; then
    fail "App-1 does not reference App-2" "found an App-2 reference in App-1's configuration"
  else
    pass "App-1 does not reference App-2"
  fi

  pool="$(printf '%s\n' "$env_dump" | grep -E '^COMPILER_[123]_URL=' | sed 's/^COMPILER_[123]_URL=//' | grep -v '^$' | tr '\n' ' ')"
  if [ -n "$pool" ]; then
    pass "compiler pool configured for App-1" "$pool"
  else
    single="$(printf '%s\n' "$env_dump" | awk -F= '/^JUDGE0_BASE_URL=/{print $2}')"
    if [ -n "$single" ]; then
      pass "single compiler node configured for App-1" "$single"
      info "add COMPILER_1_URL..COMPILER_3_URL in app-1/.env to use the full pool"
    else
      fail "compiler endpoint configured for App-1" "neither COMPILER_n_URL nor JUDGE0_BASE_URL is set"
    fi
  fi
fi

dt_summary "$NAME"
