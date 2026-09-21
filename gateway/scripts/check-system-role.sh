#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Verify expected containers for a given system role.
#
# Usage:
#   ./check-system-role.sh gateway
#   ./check-system-role.sh app1
#   ./check-system-role.sh compiler1
#   ./check-system-role.sh app2
#   ./check-system-role.sh compiler2
#   ./check-system-role.sh compiler3
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

ROLE="${1:?Usage: check-system-role.sh <gateway|app1|compiler1|app2|compiler2|compiler3>}"

# The monitoring stack runs on EVERY physical system (see deploy-monitoring.sh),
# so it is expected on every role rather than being another system's container.
MONITORING=(
    "monitoring-node-exporter"
    "monitoring-cadvisor"
    "monitoring-prometheus"
    "monitoring-grafana"
)

case "$ROLE" in
    gateway)
        EXPECTED=("traefik" "frontend" "gateway-api")
        DISALLOWED=("app-1" "app-2" "challenge-1" "challenge-2"
                    "compiler-1-server" "compiler-2-server" "compiler-3-server")
        ;;
    app1)
        EXPECTED=("app-1" "challenge-1")
        DISALLOWED=("app-2" "challenge-2" "traefik" "frontend" "gateway-api"
                    "compiler-1-server" "compiler-2-server" "compiler-3-server")
        ;;
    compiler1)
        EXPECTED=("compiler-1-server" "compiler-1-worker" "compiler-1-db" "compiler-1-redis")
        DISALLOWED=("app-1" "app-2" "challenge-1" "challenge-2"
                    "traefik" "frontend" "gateway-api"
                    "compiler-2-server" "compiler-3-server")
        ;;
    app2)
        EXPECTED=("app-2" "challenge-2")
        DISALLOWED=("app-1" "challenge-1" "traefik" "frontend" "gateway-api"
                    "compiler-1-server" "compiler-2-server" "compiler-3-server")
        ;;
    compiler2)
        EXPECTED=("compiler-2-server" "compiler-2-worker" "compiler-2-db" "compiler-2-redis")
        DISALLOWED=("app-1" "app-2" "challenge-1" "challenge-2"
                    "traefik" "frontend" "gateway-api"
                    "compiler-1-server" "compiler-3-server")
        ;;
    compiler3)
        EXPECTED=("compiler-3-server" "compiler-3-worker" "compiler-3-db" "compiler-3-redis")
        DISALLOWED=("app-1" "app-2" "challenge-1" "challenge-2"
                    "traefik" "frontend" "gateway-api"
                    "compiler-1-server" "compiler-2-server")
        ;;
    *)
        log_error "Unknown role: $ROLE"
        echo "Valid roles: gateway, app1, compiler1, app2, compiler2, compiler3"
        exit 1
        ;;
esac

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM ROLE CHECK: $ROLE"
echo "═══════════════════════════════════════════════════════════════════"

errors=0

# Check expected containers are present and healthy
echo
echo "Expected containers:"
for container in "${EXPECTED[@]}" "${MONITORING[@]}"; do
    status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
    health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "none")

    if [ "$status" = "running" ] && [ "$health" = "healthy" ]; then
        log_ok "$container: running (healthy)"
    elif [ "$status" = "running" ]; then
        log_warn "$container: running ($health)"
    else
        log_error "$container: $status"
        errors=$((errors + 1))
    fi
done

# Check disallowed containers are NOT running
echo
echo "Disallowed containers (should NOT be running):"
for container in "${DISALLOWED[@]}"; do
    status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
    if [ "$status" = "running" ]; then
        log_error "$container: RUNNING (should be stopped!)"
        errors=$((errors + 1))
    else
        log_ok "$container: not running"
    fi
done

echo "═══════════════════════════════════════════════════════════════════"
if [ $errors -eq 0 ]; then
    log_ok "System role '$ROLE' check PASSED."
else
    log_error "System role '$ROLE' check FAILED with $errors error(s)."
    exit 1
fi
