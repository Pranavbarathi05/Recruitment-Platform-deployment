-- ══════════════════════════════════════════════════════════════════════════════
-- Judge0 — Java (language id 62) resource caps.  SINGLE SOURCE OF TRUTH.
--
-- Applied by BOTH paths so they can never drift apart:
--   * automatic: the `judge0-java-tuning` service on every `docker compose up`
--     (gateway/judge0/docker-compose.yml, runs java-tuning.sh)
--   * manual:    ./apply-java-tuning.sh [node-prefix] [--verify]
--
-- WHY: the OpenJDK 13 runtime reserves ~1 GiB of *virtual* address space for its
-- compressed class space before doing anything. Judge0 enforces memory with
-- RLIMIT_AS on cgroup v2 hosts (ENABLE_PER_PROCESS_*_LIMIT=true in judge0.conf),
-- so an uncapped JVM dies at startup with
--     Could not allocate metaspace: 1073741824 bytes
-- Real heap usage stays bounded by -Xmx256m — the larger RLIMIT_AS is only an
-- address-space ceiling. MAX_MEMORY_LIMIT=2097152 in judge0.conf leaves room.
--
-- Idempotent: re-running only rewrites the same two strings. The row lives in
-- the node's own database volume, so it survives restarts but NOT
-- `docker compose down -v` (which is exactly when the automatic path re-applies
-- it on the next `up`).
-- ══════════════════════════════════════════════════════════════════════════════

UPDATE languages SET
  compile_cmd = '/usr/local/openjdk13/bin/javac %s -J-Xmx256m -J-XX:MaxMetaspaceSize=256m -J-XX:CompressedClassSpaceSize=64m Main.java',
  run_cmd     = '/usr/local/openjdk13/bin/java -Xmx256m -XX:ReservedCodeCacheSize=96m -XX:MaxMetaspaceSize=192m -XX:CompressedClassSpaceSize=64m Main'
WHERE id = 62;
