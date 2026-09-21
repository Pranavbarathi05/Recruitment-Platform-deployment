#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Common helper functions for the six-system deployment scripts
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Get the repository root (parent of gateway/)
# scripts/ is inside gateway/, so go up two levels from the script directory
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Wait for a container to become healthy
wait_healthy() {
    local container="$1"
    local timeout="${2:-120}"
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        local status
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "missing")
        if [ "$status" = "healthy" ]; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    log_error "Container '$container' did not become healthy within ${timeout}s"
    return 1
}

# Wait for a container to be running. Unlike wait_healthy() this also accepts
# containers that declare no HEALTHCHECK (their health is reported as
# "none"), which is how upstream monitoring images behave.
wait_up() {
    local container="$1"
    local timeout="${2:-120}"
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        local status
        status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
        if [ "$status" = "running" ]; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    log_error "Container '$container' did not start within ${timeout}s"
    return 1
}

# Check if a port is already in use by an unrelated process
check_port_available() {
    local port="$1"
    if ss -ltn | grep -q ":${port} "; then
        local pid
        pid=$(ss -ltnp 2>/dev/null | grep ":${port} " | head -1 | sed 's/.*pid=\([0-9]*\).*/\1/')
        local proc_name
        proc_name=$(ps -p "${pid:-0}" -o comm= 2>/dev/null || echo "unknown")
        log_error "Port $port is already in use by PID ${pid:-?} ($proc_name)"
        return 1
    fi
    return 0
}

# A port is acceptable when it is free, OR when it is already published by the
# Compose project we are about to (re)start. Re-running a deploy script must be
# a no-op rather than "port already allocated" — see dockerdemoup.sh.
#   check_port_owned_or_free <port> <compose-project>
check_port_owned_or_free() {
    local port="$1"
    local project="${2:-}"

    if ! ss -ltn | grep -q ":${port} "; then
        return 0
    fi

    if [ -n "$project" ]; then
        local owned
        owned=$(docker ps \
            --filter "label=com.docker.compose.project=${project}" \
            --format '{{.Ports}}' 2>/dev/null \
            | grep -c "[.:]${port}->" || true)
        if [ "${owned:-0}" -gt 0 ]; then
            log_info "Port $port is already published by project '$project' — reusing it"
            return 0
        fi
    fi

    check_port_available "$port"
}

# Validate that a required env var is set
require_env() {
    local var_name="$1"
    local var_value="${!var_name:-}"
    if [ -z "$var_value" ]; then
        log_error "Required environment variable $var_name is not set"
        return 1
    fi
    return 0
}

# Print container status for a set of expected containers
print_status() {
    local system_name="$1"
    shift
    local expected=("$@")

    echo
    echo "═══════════════════════════════════════════════════════════════════"
    echo " $system_name — Container Status"
    echo "═══════════════════════════════════════════════════════════════════"

    local all_ok=true
    for container in "${expected[@]}"; do
        local status
        status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
        local health
        health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "none")

        if [ "$status" = "running" ]; then
            if [ "$health" = "healthy" ]; then
                log_ok "$container: running (healthy)"
            else
                log_warn "$container: running ($health)"
            fi
        else
            log_error "$container: $status"
            all_ok=false
        fi
    done

    echo "═══════════════════════════════════════════════════════════════════"
    if $all_ok; then
        log_ok "All expected containers healthy."
    else
        log_error "Some containers are not healthy!"
        return 1
    fi
}
