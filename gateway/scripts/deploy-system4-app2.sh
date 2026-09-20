#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 4 — APP-2
#
# Starts: app-2, challenge-2
# Does NOT start: app-1, challenge-1, compiler-1/2/3, Gateway
#
# Usage:
#   ./deploy-system4-app2.sh
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

APP2_DIR="$REPO_ROOT/gateway/app-2"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM 4 — APP-2"
echo "═══════════════════════════════════════════════════════════════════"

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$APP2_DIR/.env" ]; then
    log_info "Loading $APP2_DIR/.env"
    set -a
    source "$APP2_DIR/.env"
    set +a
else
    log_error "Missing $APP2_DIR/.env — copy .env.example and configure it"
    exit 1
fi

# ── Validate required variables ──────────────────────────────────────────────
log_info "Validating required environment variables..."
require_env SUPABASE_URL || exit 1
require_env SUPABASE_SERVICE_ROLE_KEY || exit 1
require_env SUPABASE_ANON_KEY || exit 1

# ── Check ports ─────────────────────────────────────────────────────────────
log_info "Checking port availability..."
APP2_PORT="${APP2_HOST_PORT:-8002}"
APP2_CHALLENGE_PORT="${APP2_CHALLENGE_PORT:-8080}"
check_port_available "$APP2_PORT" || exit 1
check_port_available "$APP2_CHALLENGE_PORT" || exit 1

# ── Create external network if needed ───────────────────────────────────────
docker network create system3 2>/dev/null || true

# ── Start App-2 stack ──────────────────────────────────────────────────────
log_info "Starting App-2 stack..."
cd "$APP2_DIR"
docker compose up -d --build

# ── Wait for health ─────────────────────────────────────────────────────────
log_info "Waiting for containers to become healthy..."
wait_healthy app-2 120 || exit 1
wait_healthy challenge-2 60 || exit 1

# ── Verify ──────────────────────────────────────────────────────────────────
log_info "Verifying services..."

if curl -sf --connect-timeout 5 "http://localhost:${APP2_PORT}/" > /dev/null 2>&1; then
    log_ok "App-2 API reachable at localhost:${APP2_PORT}"
else
    log_error "App-2 API not reachable"
    exit 1
fi

if curl -sf --connect-timeout 5 "http://localhost:${APP2_CHALLENGE_PORT}/" > /dev/null 2>&1; then
    log_ok "Challenge-2 reachable at localhost:${APP2_CHALLENGE_PORT}"
else
    log_error "Challenge-2 not reachable"
    exit 1
fi

# ── Final status ────────────────────────────────────────────────────────────
print_status "SYSTEM 4 — App-2" app-2 challenge-2

echo
log_ok "System 4 (App-2) is running."
echo "  API:        http://localhost:${APP2_PORT}/"
echo "  Challenge:  http://localhost:${APP2_CHALLENGE_PORT}/"
echo ""
echo "  Configure the GATEWAY machine with:"
echo "    APP2_URL=http://<THIS_MACHINE_IP>:${APP2_PORT}"
echo "    APP2_CHALLENGE_URL=http://<THIS_MACHINE_IP>:${APP2_CHALLENGE_PORT}"
