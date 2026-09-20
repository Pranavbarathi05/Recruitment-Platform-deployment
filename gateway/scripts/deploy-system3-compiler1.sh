#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# System 3 — COMPILER-1
#
# Starts: Judge0 server, worker, database, Redis
# Published API: 2358 -> container 2358
#
# Usage:
#   ./deploy-system3-compiler1.sh
# ══════════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/deploy-compiler.sh" compiler-1 2358
