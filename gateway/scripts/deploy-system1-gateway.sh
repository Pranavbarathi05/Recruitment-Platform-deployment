#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 1 — GATEWAY
#
# Starts: traefik, frontend, gateway-api
# Does NOT start: app-1/2, challenge-1/2, compiler-1/2/3
#
# Usage:
#   ./deploy-system1-gateway.sh
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

GATEWAY_DIR="$REPO_ROOT/gateway"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM 1 — GATEWAY"
echo "═══════════════════════════════════════════════════════════════════"

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$GATEWAY_DIR/.env" ]; then
    log_info "Loading $GATEWAY_DIR/.env"
    set -a
    source "$GATEWAY_DIR/.env"
    set +a
else
    log_error "Missing $GATEWAY_DIR/.env — copy .env.example and configure it"
    exit 1
fi

# ── Validate required variables ──────────────────────────────────────────────
log_info "Validating required environment variables..."
require_env APP1_URL || exit 1
require_env APP1_CHALLENGE_URL || exit 1

# Optional but recommended
for var in APP2_URL APP2_CHALLENGE_URL COMPILER_1_URL COMPILER_2_URL COMPILER_3_URL; do
    val="${!var:-}"
    if [ -n "$val" ]; then
        log_ok "$var=$val"
    else
        log_warn "$var not set (system will not be in pool)"
    fi
done

# ── Check ports ─────────────────────────────────────────────────────────────
log_info "Checking port availability..."
check_port_owned_or_free "${TRAEFIK_HTTP_PORT:-80}" gateway || exit 1

# ── Create external network if needed ───────────────────────────────────────
docker network create system3 2>/dev/null || true

# ── Start gateway stack ─────────────────────────────────────────────────────
log_info "Starting gateway stack..."
cd "$GATEWAY_DIR"
docker compose up -d --build

# ── Wait for health ─────────────────────────────────────────────────────────
log_info "Waiting for containers to become healthy..."
wait_healthy traefik 60 || exit 1
wait_healthy frontend 60 || exit 1
wait_healthy gateway-api 60 || exit 1

# ── Verify routing ──────────────────────────────────────────────────────────
log_info "Verifying routing..."

# Frontend loads
if curl -sf "http://localhost:${TRAEFIK_HTTP_PORT:-80}/" > /dev/null 2>&1; then
    log_ok "Frontend loads at /"
else
    log_error "Frontend not reachable at /"
    exit 1
fi

# Gateway API health (gateway-api serves /api/health; /_api is the APP backend)
if curl -sf "http://localhost:${TRAEFIK_HTTP_PORT:-80}/api/health" > /dev/null 2>&1; then
    log_ok "Gateway API health OK"
else
    log_error "Gateway API health check failed at /api/health"
    exit 1
fi

# App backend pool root (the App machines' health endpoint)
if curl -sf "http://localhost:${TRAEFIK_HTTP_PORT:-80}/_api/" > /dev/null 2>&1; then
    log_ok "App backend pool reachable at /_api/"
else
    log_warn "App backend pool not reachable at /_api/ (is an App machine up?)"
fi

# ── Verify remote systems ──────────────────────────────────────────────────
log_info "Checking remote system connectivity..."

check_remote() {
    local name="$1"
    local url="$2"
    if [ -z "$url" ]; then
        log_warn "$name URL not configured — skipping"
        return 0
    fi
    # This probe runs on the HOST, but the .env addresses are what the Traefik
    # CONTAINER uses. host.docker.internal only resolves inside a container, so
    # rewrite it for the host-side check (single-host simulation mode only).
    url="${url//host.docker.internal/localhost}"
    if curl -sf --connect-timeout 5 "$url" > /dev/null 2>&1; then
        log_ok "$name reachable at $url"
    else
        log_warn "$name NOT reachable at $url (may be firewall or not started yet)"
    fi
}

check_remote "App-1" "${APP1_URL:-}"
check_remote "App-2" "${APP2_URL:-}"
check_remote "Compiler-1" "${COMPILER_1_URL:-}"
check_remote "Compiler-2" "${COMPILER_2_URL:-}"
check_remote "Compiler-3" "${COMPILER_3_URL:-}"

# ── Monitoring (part of this system's lifecycle) ─────────────────────────────
"$SCRIPT_DIR/deploy-monitoring.sh" gateway

# ── Final status ────────────────────────────────────────────────────────────
print_status "SYSTEM 1 — Gateway" \
    traefik frontend gateway-api \
    monitoring-node-exporter monitoring-cadvisor monitoring-prometheus monitoring-grafana

echo
log_ok "System 1 (Gateway) is running."
echo "  Frontend:     http://localhost:${TRAEFIK_HTTP_PORT:-80}/"
echo "  Dashboard:    http://localhost:${TRAEFIK_DASHBOARD_PORT:-8080}/"
echo "  App API:      curl http://localhost:${TRAEFIK_HTTP_PORT:-80}/_api/          (App backend, /_api prefix stripped)"
echo "  Gateway API:  curl http://localhost:${TRAEFIK_HTTP_PORT:-80}/api/health   (gateway-api)"
echo "  Monitoring:   Grafana on the configured MONITOR_PORT (default 3001)"
