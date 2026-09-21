#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Monitoring stack shutdown — shared by ALL SIX physical systems
#
# Stops and removes the LAN-only monitoring stack that deploy-monitoring.sh
# started (Compose project `monitoring`). Named volumes are KEPT unless
# `--volumes` is passed, so Prometheus/Grafana history survives a redeploy.
#
# Safe to call from every per-system down script, and therefore six times during
# `dockerdemodown.sh all`: after the first call there is nothing left to remove
# and the script exits 0.
#
# Usage:
#   ./down-monitoring.sh [role] [--volumes]
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

ROLE="${1:-this system}"
WIPE_VOLUMES=""
for arg in "$@"; do
    [ "$arg" = "--volumes" ] && WIPE_VOLUMES="--volumes"
done

MONITORING_DIR="$REPO_ROOT/gateway/monitoring"
PROJECT="monitoring"

echo "───────────────────────────────────────────────────────────────────"
echo " MONITORING — $ROLE SHUTDOWN"
echo "───────────────────────────────────────────────────────────────────"

if [ ! -f "$MONITORING_DIR/docker-compose.yml" ]; then
    log_warn "No $MONITORING_DIR/docker-compose.yml — nothing to stop"
    exit 0
fi

# ── Nothing running? Nothing to do (keeps `down all` idempotent) ─────────────
running=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Names}}' 2>/dev/null)
if [ -z "$running" ]; then
    log_ok "Monitoring (project '$PROJECT') is not running — nothing to stop."
    exit 0
fi

cd "$MONITORING_DIR"
docker compose -p "$PROJECT" down $WIPE_VOLUMES || {
    log_error "Failed to stop the monitoring stack"
    exit 1
}

# ── Verify ───────────────────────────────────────────────────────────────────
remaining=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Names}}' 2>/dev/null)
if [ -n "$remaining" ]; then
    log_error "Unexpected remaining monitoring containers: $remaining"
    exit 1
fi

log_ok "Monitoring stopped."
