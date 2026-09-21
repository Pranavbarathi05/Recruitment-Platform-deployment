#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 5 — COMPILER-2
#
# Starts: Judge0 server, worker, database, Redis
# Published API: 2359 -> container 2358
#
# Usage:
#   ./deploy-system5-compiler2.sh
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Monitoring runs on every physical system, so it is part of THIS machine's
# lifecycle too. Idempotent: harmless if the stack is already up.
"$SCRIPT_DIR/deploy-monitoring.sh" compiler2

exec "$SCRIPT_DIR/deploy-compiler.sh" compiler-2 2359
