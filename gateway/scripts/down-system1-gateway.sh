#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 1 — GATEWAY shutdown
#
# Stops: traefik, frontend, gateway-api
# Does NOT touch: app-1/2, challenge-1/2, compiler-1/2/3
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

GATEWAY_DIR="$REPO_ROOT/gateway"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM 1 — GATEWAY SHUTDOWN"
echo "═══════════════════════════════════════════════════════════════════"

cd "$GATEWAY_DIR"
docker compose down

# Verify no gateway containers remain
remaining=$(docker ps --filter "label=com.docker.compose.project=gateway" --format '{{.Names}}' 2>/dev/null)
if [ -n "$remaining" ]; then
    log_error "Unexpected remaining containers: $remaining"
    exit 1
fi

# Monitoring is part of this machine's deployment; stop it last so the
# watchful services outlive the workload they were measuring. No-op when it
# is already down.
"$SCRIPT_DIR/down-monitoring.sh" gateway

log_ok "System 1 (Gateway) stopped."
