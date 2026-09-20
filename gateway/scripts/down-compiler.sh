#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Shared compiler shutdown logic
#
# Usage:  down-compiler.sh <compiler-name>
# Example: down-compiler.sh compiler-1
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

TARGET_COMPILER="${1:?Usage: down-compiler.sh <compiler-name>}"

JUDGE0_DIR="$REPO_ROOT/gateway/judge0"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM — ${TARGET_COMPILER^^} SHUTDOWN"
echo "═══════════════════════════════════════════════════════════════════"

# ── Load .env for required settings (network, bind, etc.) ────────────────────
if [ -f "$JUDGE0_DIR/.env" ]; then
    set -a
    source "$JUDGE0_DIR/.env"
    set +a
fi

# ── Override COMPILER_NAME with the requested identity ───────────────────────
# The .env file may contain a different COMPILER_NAME (e.g. compiler-1).
# We override it here so docker compose -p targets the correct project.
export COMPILER_NAME="$TARGET_COMPILER"

cd "$JUDGE0_DIR"
docker compose -p "$COMPILER_NAME" down

# Verify no containers from this project remain
remaining=$(docker ps --filter "label=com.docker.compose.project=${COMPILER_NAME}" --format '{{.Names}}' 2>/dev/null)
if [ -n "$remaining" ]; then
    log_error "Unexpected remaining containers: $remaining"
    exit 1
fi

log_ok "System (${TARGET_COMPILER^^}) stopped."
