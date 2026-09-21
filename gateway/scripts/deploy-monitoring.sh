#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Monitoring stack startup — shared by ALL SIX physical systems
#
# Every machine in the deployment runs the same LAN-only monitoring stack
# (gateway/monitoring/docker-compose.yml):
#
#   monitoring-node-exporter   host CPU / RAM / disk
#   monitoring-cadvisor        per-container CPU / RAM / network
#   monitoring-prometheus      scrapes the two exporters
#   monitoring-grafana         dashboards (LAN only, host port MONITOR_PORT)
#
# The stack owns exactly ONE Compose project (`monitoring`) with FIXED container
# names, so calling this script repeatedly — from every per-system script, or
# six times during `dockerdemoup.sh all` — is a no-op after the first call. It
# can never create a duplicate monitoring stack.
#
# Usage:
#   ./deploy-monitoring.sh [role]      role is for log output only
#                                      (gateway|app1|compiler1|app2|compiler2|compiler3)
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

ROLE="${1:-this system}"
MONITORING_DIR="$REPO_ROOT/gateway/monitoring"
PROJECT="monitoring"

MONITORING_CONTAINERS=(
    monitoring-node-exporter
    monitoring-cadvisor
    monitoring-prometheus
    monitoring-grafana
)

echo "───────────────────────────────────────────────────────────────────"
echo " MONITORING — $ROLE"
echo "───────────────────────────────────────────────────────────────────"

if [ ! -f "$MONITORING_DIR/docker-compose.yml" ]; then
    log_error "Missing $MONITORING_DIR/docker-compose.yml"
    exit 1
fi

# ── Idempotency guard ────────────────────────────────────────────────────────
# The stack is host-level and identical on every machine, so if it is already
# up we are done. This is what keeps `dockerdemoup.sh all` from stacking six
# copies of it.
if docker inspect --format='{{.State.Status}}' monitoring-grafana 2>/dev/null | grep -q '^running$'; then
    log_ok "Monitoring already running (project '$PROJECT') — leaving it as is."
    exit 0
fi

# ── Config file ──────────────────────────────────────────────────────────────
if [ ! -f "$MONITORING_DIR/.env" ]; then
    if [ -f "$MONITORING_DIR/.env.example" ]; then
        cp "$MONITORING_DIR/.env.example" "$MONITORING_DIR/.env"
        log_warn "Created $MONITORING_DIR/.env from .env.example — review the Grafana credentials"
    else
        log_warn "No $MONITORING_DIR/.env — using compose defaults"
    fi
fi

# ── Start ────────────────────────────────────────────────────────────────────
log_info "Starting monitoring stack (project '$PROJECT')..."
cd "$MONITORING_DIR"
docker compose -p "$PROJECT" up -d || {
    log_error "Failed to start the monitoring stack"
    exit 1
}

# ── Wait for the stack ───────────────────────────────────────────────────────
log_info "Waiting for monitoring containers..."
for container in "${MONITORING_CONTAINERS[@]}"; do
    wait_up "$container" 120 || exit 1
done

# Prometheus and Grafana declare HEALTHCHECKs; the two exporters may not.
for container in monitoring-prometheus monitoring-grafana; do
    if ! wait_healthy "$container" 120; then
        log_warn "$container is running but not reporting healthy yet"
    fi
done

# ── Final status ─────────────────────────────────────────────────────────────
print_status "MONITORING — $ROLE" "${MONITORING_CONTAINERS[@]}" || true

MONITOR_PORT_VAL="$(grep -E '^MONITOR_PORT=' "$MONITORING_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
echo
log_ok "Monitoring started for $ROLE."
echo "  Grafana:     http://<THIS_MACHINE_IP>:${MONITOR_PORT_VAL:-3001}/"
echo "  Prometheus:  http://127.0.0.1:9090/  (loopback only)"
