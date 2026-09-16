#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM 6 — COMPILER-3 test (Judge0)
#
# Identical checks to Compiler-1/2, for the third execution node.
#
#   COMPILER3_IP=10.0.0.15 ./deployment-tests/system6-compiler3-test.sh
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="SYSTEM 6 — Compiler-3 (Judge0)"
system_header "$NAME"

if [ -z "${COMPILER3_IP:-}" ]; then
  section "Compiler-3 not deployed yet"
  skip "Compiler-3 checks" "COMPILER3_IP is not configured in deployment-tests/.env"
  info "Deploy it: cd gateway/judge0, set COMPILER_NAME=compiler-3 + JUDGE0_BIND=0.0.0.0 in .env,"
  info "           then add COMPILER_3_URL=http://<COMPILER3_LAN_IP>:2358 to the Gateway and App .env files."
  dt_summary "$NAME"
  exit $?
fi

check_compiler_system "Compiler-3" "$COMPILER3_IP" "$COMPILER3_API_PORT" "$COMPILER3_NAME"

if [ "$(dt_perspective "$COMPILER3_IP")" = "local" ] && dt_have docker; then
  if [ -n "${GATEWAY_IP:-}${APP1_IP:-}${APP2_IP:-}" ]; then
    check_guard_allowlist "$COMPILER3_API_PORT" "${GATEWAY_IP:-}" "${APP1_IP:-}" "${APP2_IP:-}"
  else
    skip "guard allowlist verified" "set GATEWAY_IP/APP1_IP/APP2_IP in deployment-tests/.env"
  fi
  check_no_container_conflicts "$COMPILER3_NAME"
fi

dt_summary "$NAME"
