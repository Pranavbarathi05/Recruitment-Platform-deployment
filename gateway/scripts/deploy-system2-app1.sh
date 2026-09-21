#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 2 — APP-1
#
# Starts: app-1, challenge-1
# Does NOT start: app-2, challenge-2, compiler-1/2/3, Gateway
#
# Usage:
#   ./deploy-system2-app1.sh
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

APP1_DIR="$REPO_ROOT/gateway/app-1"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM 2 — APP-1"
echo "═══════════════════════════════════════════════════════════════════"

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$APP1_DIR/.env" ]; then
    log_info "Loading $APP1_DIR/.env"
    set -a
    source "$APP1_DIR/.env"
    set +a
else
    log_error "Missing $APP1_DIR/.env — copy .env.example and configure it"
    exit 1
fi

# ── Validate required variables ──────────────────────────────────────────────
log_info "Validating required environment variables..."
require_env SUPABASE_URL || exit 1
require_env SUPABASE_SERVICE_ROLE_KEY || exit 1
require_env SUPABASE_ANON_KEY || exit 1

# ── Check ports ─────────────────────────────────────────────────────────────
log_info "Checking port availability..."
APP1_PORT="${APP1_HOST_PORT:-8002}"
APP1_CHALLENGE_PORT="${APP1_CHALLENGE_PORT:-8080}"
check_port_owned_or_free "$APP1_PORT" app-1 || exit 1
check_port_owned_or_free "$APP1_CHALLENGE_PORT" app-1 || exit 1

# ── Create external network if needed ───────────────────────────────────────
docker network create system3 2>/dev/null || true

# ── Start App-1 stack ──────────────────────────────────────────────────────
log_info "Starting App-1 stack..."
cd "$APP1_DIR"
docker compose up -d --build

# ── Wait for health ─────────────────────────────────────────────────────────
log_info "Waiting for containers to become healthy..."
wait_healthy app-1 120 || exit 1
wait_healthy challenge-1 60 || exit 1

# ── Verify ──────────────────────────────────────────────────────────────────
log_info "Verifying services..."

if curl -sf --connect-timeout 5 "http://localhost:${APP1_PORT}/" > /dev/null 2>&1; then
    log_ok "App-1 API reachable at localhost:${APP1_PORT}"
else
    log_error "App-1 API not reachable"
    exit 1
fi

if curl -sf --connect-timeout 5 "http://localhost:${APP1_CHALLENGE_PORT}/" > /dev/null 2>&1; then
    log_ok "Challenge-1 reachable at localhost:${APP1_CHALLENGE_PORT}"
else
    log_error "Challenge-1 not reachable"
    exit 1
fi

# ── Monitoring (part of this system's lifecycle) ─────────────────────────────
"$SCRIPT_DIR/deploy-monitoring.sh" app1

# ── Final status ────────────────────────────────────────────────────────────
print_status "SYSTEM 2 — App-1" \
    app-1 challenge-1 \
    monitoring-node-exporter monitoring-cadvisor monitoring-prometheus monitoring-grafana

echo
log_ok "System 2 (App-1) is running."
echo "  API:        http://localhost:${APP1_PORT}/"
echo "  Challenge:  http://localhost:${APP1_CHALLENGE_PORT}/"
echo ""
echo "  Configure the GATEWAY machine with:"
echo "    APP1_URL=http://<THIS_MACHINE_IP>:${APP1_PORT}"
echo "    APP1_CHALLENGE_URL=http://<THIS_MACHINE_IP>:${APP1_CHALLENGE_PORT}"
