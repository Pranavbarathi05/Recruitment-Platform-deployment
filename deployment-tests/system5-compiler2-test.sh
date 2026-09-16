#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM 5 — COMPILER-2 test (Judge0)
#
# Identical checks to Compiler-1, but for the second execution node. Also
# verifies that this node coexists with the others: unique container names,
# its own project/volume, and no port or name conflict.
#
#   COMPILER2_IP=10.0.0.14 ./deployment-tests/system5-compiler2-test.sh
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="SYSTEM 5 — Compiler-2 (Judge0)"
system_header "$NAME"

if [ -z "${COMPILER2_IP:-}" ]; then
  section "Compiler-2 not deployed yet"
  skip "Compiler-2 checks" "COMPILER2_IP is not configured in deployment-tests/.env"
  info "Deploy it: cd gateway/judge0, set COMPILER_NAME=compiler-2 + JUDGE0_BIND=0.0.0.0 in .env,"
  info "           then add COMPILER_2_URL=http://<COMPILER2_LAN_IP>:2358 to the Gateway and App .env files."
  dt_summary "$NAME"
  exit $?
fi

check_compiler_system "Compiler-2" "$COMPILER2_IP" "$COMPILER2_API_PORT" "$COMPILER2_NAME"

if [ "$(dt_perspective "$COMPILER2_IP")" = "local" ] && dt_have docker; then
  if [ -n "${GATEWAY_IP:-}${APP1_IP:-}${APP2_IP:-}" ]; then
    check_guard_allowlist "$COMPILER2_API_PORT" "${GATEWAY_IP:-}" "${APP1_IP:-}" "${APP2_IP:-}"
  else
    skip "guard allowlist verified" "set GATEWAY_IP/APP1_IP/APP2_IP in deployment-tests/.env"
  fi
  check_no_container_conflicts "$COMPILER2_NAME"
fi

dt_summary "$NAME"
