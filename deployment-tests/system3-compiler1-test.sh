#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM 3 — COMPILER-1 test (Judge0)
#
# Checks: the four judge0 containers (server/worker/db/redis), the published API
# port, /about and /languages, API authentication (unauthorized rejected,
# authorized accepted), REAL code execution in C++ / Java / Python, the failure
# modes (compilation error, runtime error, time limit), that PostgreSQL and
# Redis are NOT published, the firewall guard and its allowlist, and — when run
# from the Gateway — that the node is reachable over the LAN.
#
#   ./deployment-tests/system3-compiler1-test.sh                 # on Compiler-1
#   APP1_IP=.. COMPILER1_IP=10.0.0.13 ./system3-compiler1-test.sh   # from the Gateway
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="SYSTEM 3 — Compiler-1 (Judge0)"
if [ -z "${COMPILER1_IP:-}" ]; then
  COMPILER1_IP="$(dt_detect_ip)"
  ASSUMED_LOCAL=1
fi
system_header "$NAME"
[ "${ASSUMED_LOCAL:-0}" = "1" ] && info "COMPILER1_IP was not configured — assuming this machine IS Compiler-1"

check_compiler_system "Compiler-1" "$COMPILER1_IP" "$COMPILER1_API_PORT" "$COMPILER1_NAME"

if [ "$(dt_perspective "$COMPILER1_IP")" = "local" ] && dt_have docker; then
  if [ -n "${GATEWAY_IP:-}${APP1_IP:-}${APP2_IP:-}" ]; then
    check_guard_allowlist "$COMPILER1_API_PORT" "${GATEWAY_IP:-}" "${APP1_IP:-}" "${APP2_IP:-}"
  else
    skip "guard allowlist verified" "set GATEWAY_IP/APP1_IP/APP2_IP in deployment-tests/.env"
  fi
  check_no_container_conflicts "$COMPILER1_NAME"
fi

dt_summary "$NAME"
