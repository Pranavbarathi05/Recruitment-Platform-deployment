#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Docker Compose demo/development shutdown
#
# USAGE:
#   ./dockerdemodown.sh <system>     Stop a specific system
#   ./dockerdemodown.sh all          Stop ALL systems
#
# Production: Use the individual system scripts in scripts/ instead.
# ══════════════════════════════════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$SCRIPT_DIR/scripts"

usage() {
    cat <<EOF
Usage: $0 <system>

Systems:
  gateway     System 1 — Traefik, frontend, gateway-api
  app1        System 2 — App-1 backend, challenge-1
  compiler1   System 3 — Judge0 compiler-1 (port 2358)
  app2        System 4 — App-2 backend, challenge-2
  compiler2   System 5 — Judge0 compiler-2 (port 2359)
  compiler3   System 6 — Judge0 compiler-3 (port 2360)
  all         ALL systems
EOF
    exit 1
}

SYSTEM="${1:-}"
[ -z "$SYSTEM" ] && usage

case "$SYSTEM" in
    gateway)    exec "$SCRIPTS/down-system1-gateway.sh" ;;
    app1)       exec "$SCRIPTS/down-system2-app1.sh" ;;
    compiler1)  exec "$SCRIPTS/down-system3-compiler1.sh" ;;
    app2)       exec "$SCRIPTS/down-system4-app2.sh" ;;
    compiler2)  exec "$SCRIPTS/down-system5-compiler2.sh" ;;
    compiler3)  exec "$SCRIPTS/down-system6-compiler3.sh" ;;
    all)
        echo "Stopping all systems..."
        "$SCRIPTS/down-system1-gateway.sh"  || true
        "$SCRIPTS/down-system2-app1.sh"     || true
        "$SCRIPTS/down-system4-app2.sh"     || true
        "$SCRIPTS/down-system3-compiler1.sh" || true
        "$SCRIPTS/down-system5-compiler2.sh" || true
        "$SCRIPTS/down-system6-compiler3.sh" || true
        echo "All systems stopped."
        ;;
    *)
        echo "Unknown system: $SYSTEM"
        usage
        ;;
esac
