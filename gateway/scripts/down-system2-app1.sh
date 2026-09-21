#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 2 — APP-1 shutdown
#
# Stops: app-1, challenge-1
# Does NOT touch: app-2, challenge-2, compiler-1/2/3, Gateway
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

APP1_DIR="$REPO_ROOT/gateway/app-1"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM 2 — APP-1 SHUTDOWN"
echo "═══════════════════════════════════════════════════════════════════"

cd "$APP1_DIR"
docker compose down

# Verify no app-1 containers remain
remaining=$(docker ps --filter "label=com.docker.compose.project=app-1" --format '{{.Names}}' 2>/dev/null)
if [ -n "$remaining" ]; then
    log_error "Unexpected remaining containers: $remaining"
    exit 1
fi

# Monitoring is part of this machine's deployment; stop it last so the
# watchful services outlive the workload they were measuring. No-op when it
# is already down.
"$SCRIPT_DIR/down-monitoring.sh" app1

log_ok "System 2 (App-1) stopped."
