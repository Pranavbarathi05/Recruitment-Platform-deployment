#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Docker Compose demo/development launcher
#
# USAGE:
#   ./dockerdemoup.sh <system>       Start a specific system
#   ./dockerdemoup.sh all            Start ALL systems (co-located test only!)
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
  all         ALL systems (co-located test/development only — NOT production!)

The monitoring stack (project 'monitoring') is started by every system script
and is idempotent: `all` starts it exactly once, never twice.

Production deployment: use the individual scripts in scripts/ directory.
Each script starts only the containers belonging to that physical machine.
EOF
    exit 1
}

SYSTEM="${1:-}"
[ -z "$SYSTEM" ] && usage

case "$SYSTEM" in
    gateway)    exec "$SCRIPTS/deploy-system1-gateway.sh" ;;
    app1)       exec "$SCRIPTS/deploy-system2-app1.sh" ;;
    compiler1)  exec "$SCRIPTS/deploy-system3-compiler1.sh" ;;
    app2)       exec "$SCRIPTS/deploy-system4-app2.sh" ;;
    compiler2)  exec "$SCRIPTS/deploy-system5-compiler2.sh" ;;
    compiler3)  exec "$SCRIPTS/deploy-system6-compiler3.sh" ;;
    all)
        echo "═══════════════════════════════════════════════════════════════════"
        echo " ALL SYSTEMS — CO-LOCATED TEST/DEVELOPMENT MODE"
        echo " This is NOT production. Production uses separate physical machines."
        echo "═══════════════════════════════════════════════════════════════════"
        echo

        "$SCRIPTS/deploy-system3-compiler1.sh"
        "$SCRIPTS/deploy-system5-compiler2.sh"
        "$SCRIPTS/deploy-system6-compiler3.sh"
        "$SCRIPTS/deploy-system2-app1.sh"
        "$SCRIPTS/deploy-system4-app2.sh"
        "$SCRIPTS/deploy-system1-gateway.sh"

        echo
        echo "═══════════════════════════════════════════════════════════════════"
        echo " ALL SYSTEMS STARTED (co-located test mode)"
        echo "═══════════════════════════════════════════════════════════════════"
        docker ps
        echo
        echo "Compose projects owned by this deployment:"
        docker compose ls -a 2>/dev/null \
            | grep -E '^(NAME|gateway|app-1|app-2|compiler-1|compiler-2|compiler-3|monitoring)' \
            || true
        ;;
    *)
        echo "Unknown system: $SYSTEM"
        usage
        ;;
esac
