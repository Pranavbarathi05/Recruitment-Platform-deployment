#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 4 — APP-2 shutdown
#
# Stops: app-2, challenge-2
# Does NOT touch: app-1, challenge-1, compiler-1/2/3, Gateway
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

APP2_DIR="$REPO_ROOT/gateway/app-2"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM 4 — APP-2 SHUTDOWN"
echo "═══════════════════════════════════════════════════════════════════"

cd "$APP2_DIR"
docker compose down

# Verify no app-2 containers remain
remaining=$(docker ps --filter "label=com.docker.compose.project=app-2" --format '{{.Names}}' 2>/dev/null)
if [ -n "$remaining" ]; then
    log_error "Unexpected remaining containers: $remaining"
    exit 1
fi

# Monitoring is part of this machine's deployment; stop it last so the
# watchful services outlive the workload they were measuring. No-op when it
# is already down.
"$SCRIPT_DIR/down-monitoring.sh" app2

log_ok "System 4 (App-2) stopped."
