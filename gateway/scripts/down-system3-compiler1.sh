#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Monitoring belongs to this system's lifecycle as well. No-op if it is
# already down (which is what makes `dockerdemodown.sh all` idempotent).
"$SCRIPT_DIR/down-monitoring.sh" compiler1

exec "$SCRIPT_DIR/down-compiler.sh" compiler-1
