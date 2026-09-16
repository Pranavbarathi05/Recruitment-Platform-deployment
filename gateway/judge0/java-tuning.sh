#!/bin/sh
# ══════════════════════════════════════════════════════════════════════════════
# Judge0 — automatic Java tuning (runs INSIDE the `judge0-java-tuning` service)
#
# Started by `docker compose up -d` on every compiler machine (Compiler-1/2/3).
# It waits until the API has seeded the `languages` table, then applies
# java-tuning.sql (the same SQL that apply-java-tuning.sh uses) and exits.
#
# Why it exists: the OpenJDK image reserves ~1 GiB of *virtual* address space
# before doing anything, so under Judge0's rlimit-based enforcement (required on
# cgroup v2 hosts) every Java submission dies at VM startup with
# "Could not allocate metaspace: 1073741824 bytes". Capping language id 62
# fixes it. Doing it here means a brand-new node needs no manual step.
#
# Environment (from env_file: judge0.conf, set by the compose service):
#   POSTGRES_PASSWORD — the database password
#   PGHOST=judge0-db  PGUSER=judge0  PGDATABASE=judge0
# Exits 0 when the row is tuned, 1 when the database never became ready.
# ══════════════════════════════════════════════════════════════════════════════
set -eu

SQL_FILE="${SQL_FILE:-/java-tuning.sql}"
export PGPASSWORD="${POSTGRES_PASSWORD:-judge0}"

attempt=0
while :; do
  seeded="$(psql -tAc "SELECT count(*) FROM languages WHERE id = 62" 2>/dev/null | tr -d '[:space:]')"
  [ "$seeded" = "1" ] && break
  attempt=$((attempt + 1))
  if [ "$attempt" -gt 60 ]; then
    echo "java tuning: Judge0 never seeded the languages table (waited ~2 min)" >&2
    exit 1
  fi
  sleep 2
done

psql -q -f "$SQL_FILE"
echo "java tuning applied (language id 62)"
