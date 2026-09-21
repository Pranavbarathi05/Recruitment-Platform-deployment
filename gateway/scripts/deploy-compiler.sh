#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Shared compiler startup logic for System 3/5/6
#
# Usage:  deploy-compiler.sh <compiler-name> <host-port>
# Example: deploy-compiler.sh compiler-1 2358
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

TARGET_COMPILER="${1:?Usage: deploy-compiler.sh <compiler-name> <host-port>}"
HOST_PORT="${2:?Usage: deploy-compiler.sh <compiler-name> <host-port>}"

JUDGE0_DIR="$REPO_ROOT/gateway/judge0"

echo "═══════════════════════════════════════════════════════════════════"
echo " SYSTEM — ${TARGET_COMPILER^^}"
echo "═══════════════════════════════════════════════════════════════════"

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$JUDGE0_DIR/.env" ]; then
    log_info "Loading $JUDGE0_DIR/.env"
    set -a
    source "$JUDGE0_DIR/.env"
    set +a
else
    log_error "Missing $JUDGE0_DIR/.env — copy .env.example and configure it"
    exit 1
fi

# ── Override COMPILER_NAME with the requested identity ───────────────────────
# The .env file may contain a different COMPILER_NAME (e.g. compiler-1).
# We override it here so Compose uses the correct project/container names,
# then pass -p to docker compose for explicit project targeting.
export COMPILER_NAME="$TARGET_COMPILER"
export JUDGE0_PORT="$HOST_PORT"
# Each node gets its OWN Docker network. judge0.conf addresses its datastores
# by the plain upstream service names (judge0-db / judge0-redis) and the
# mounted /judge0.conf OVERRIDES the container environment, so the only way to
# keep several nodes on one host unambiguous is to give every node a private
# network in which those names exist exactly once. Without this, a submission
# is INSERTed into one node's Postgres and polled from another, which Judge0
# answers with "Couldn't find Submission" (HTTP 404) until the poll times out.
export COMPILER_NETWORK="${TARGET_COMPILER}-net"
log_info "Using project name: $COMPILER_NAME, host port: $JUDGE0_PORT, network: $COMPILER_NETWORK"

# ── Check ports ─────────────────────────────────────────────────────────────
log_info "Checking port availability..."
check_port_owned_or_free "$HOST_PORT" "$TARGET_COMPILER" || exit 1

# ── Create this node's private network if needed ─────────────────────────────
docker network create "$COMPILER_NETWORK" 2>/dev/null || true

# ── Start compiler stack ────────────────────────────────────────────────────
log_info "Starting ${COMPILER_NAME} stack..."
cd "$JUDGE0_DIR"
docker compose -p "$COMPILER_NAME" up -d

# ── Wait for health ─────────────────────────────────────────────────────────
log_info "Waiting for containers to become healthy..."
wait_healthy "${COMPILER_NAME}-server" 120 || exit 1
wait_healthy "${COMPILER_NAME}-worker" 120 || exit 1
wait_healthy "${COMPILER_NAME}-db" 60 || exit 1
wait_healthy "${COMPILER_NAME}-redis" 60 || exit 1

# ── Verify ──────────────────────────────────────────────────────────────────
log_info "Verifying Judge0 API..."

if curl -sf --connect-timeout 5 "http://localhost:${HOST_PORT}/" > /dev/null 2>&1; then
    log_ok "Judge0 API reachable at localhost:${HOST_PORT}"
else
    log_error "Judge0 API not reachable at localhost:${HOST_PORT}"
    exit 1
fi

# ── Final status ────────────────────────────────────────────────────────────
print_status "SYSTEM — ${COMPILER_NAME^^}" \
    "${COMPILER_NAME}-server" \
    "${COMPILER_NAME}-worker" \
    "${COMPILER_NAME}-db" \
    "${COMPILER_NAME}-redis"

echo
log_ok "System (${COMPILER_NAME^^}) is running."
echo "  Judge0 API:  http://localhost:${HOST_PORT}/"
echo "  Container port: 2358 (internal)"
echo ""
echo "  Configure other machines with:"
echo "    http://<THIS_MACHINE_IP>:${HOST_PORT}"
