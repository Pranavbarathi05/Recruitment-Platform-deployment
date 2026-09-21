#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 6 — COMPILER-3
#
# Starts: Judge0 server, worker, database, Redis
# Published API: 2360 -> container 2358
#
# Usage:
#   ./deploy-system6-compiler3.sh
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Monitoring runs on every physical system, so it is part of THIS machine's
# lifecycle too. Idempotent: harmless if the stack is already up.
"$SCRIPT_DIR/deploy-monitoring.sh" compiler3

exec "$SCRIPT_DIR/deploy-compiler.sh" compiler-3 2360
