#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Judge0 — one-time Java tuning (REQUIRED on every compiler node)
#
# WHY: the OpenJDK runtime reserves ~1 GiB of VIRTUAL address space for its
# compressed class space before doing anything. Under Judge0's rlimit-based
# memory enforcement (RLIMIT_AS — required on cgroup v2 hosts, see judge0.conf)
# every Java submission then dies at VM startup with:
#
#     Error occurred during initialization of VM
#     Could not allocate metaspace: 1073741824 bytes
#
# The fix is to cap the JVM's metaspace / class-space / code-cache explicitly,
# so the reservation fits inside MAX_MEMORY_LIMIT. Real heap use stays bounded
# by -Xmx: the large RLIMIT_AS is only an address-space CEILING.
#
# This runs ONE SQL UPDATE against the node's metadata database. It survives
# restarts and re-runs; only `docker compose down -v` (which wipes the volume)
# loses it — re-run this script after that.
#
# USAGE (on each compiler machine, after `docker compose up -d`):
#   ./apply-java-tuning.sh                       # node prefix `compiler-1`
#   ./apply-java-tuning.sh compiler-2            # another node on this host
#   ./apply-java-tuning.sh compiler-1 --verify   # re-check without changing
#
# Exit code 1 if the tuning could not be applied or verified.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

PREFIX="${1:-compiler-1}"
VERIFY_ONLY=0
for arg in "$@"; do
  [ "$arg" = "--verify" ] && VERIFY_ONLY=1
done

DB_CONTAINER="${PREFIX}-db"

if ! docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: database container '$DB_CONTAINER' not found." >&2
  echo "       Start the node first (docker compose up -d), or pass the right" >&2
  echo "       node prefix (COMPILER_NAME in this machine's .env)." >&2
  exit 1
fi

# The SQL lives in java-tuning.sql, which the automatic `judge0-java-tuning`
# service also applies — one definition, so the two paths cannot drift apart.
SQL_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/java-tuning.sql"

psql() { docker exec -i "$DB_CONTAINER" psql -U judge0 -d judge0 -tAc "$1"; }

if [ "$VERIFY_ONLY" -eq 0 ]; then
  if [ ! -f "$SQL_FILE" ]; then
    echo "ERROR: java-tuning.sql not found next to this script ($SQL_FILE)." >&2
    exit 1
  fi
  docker exec -i "$DB_CONTAINER" psql -U judge0 -d judge0 -q < "$SQL_FILE"
  echo "java tuning applied to $DB_CONTAINER (from $(basename "$SQL_FILE"))"
fi

applied="$(psql "SELECT compile_cmd FROM languages WHERE id = 62;")"
if printf '%s' "$applied" | grep -q 'MaxMetaspaceSize'; then
  echo "OK: Java (language id 62) is tuned on $DB_CONTAINER"
  echo "    compile_cmd: $applied"
  exit 0
fi

echo "ERROR: the Java language row is still untuned on $DB_CONTAINER." >&2
echo "       Every Java submission will fail with 'Could not allocate metaspace'." >&2
exit 1
