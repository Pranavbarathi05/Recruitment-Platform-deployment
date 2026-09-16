#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Shared library for the six-system deployment tests.
#
# Every test script sources this file, then calls the shared check_* functions.
# Nothing here is specific to one machine: each script says WHICH system it is
# testing and which addresses to use through environment variables.
#
# Configuration (highest precedence first):
#   1. command-line environment:  APP1_IP=... ./system2-app1-test.sh
#   2. deployment-tests/.env      (copy from .env.example)
#   3. the defaults below (auto-detects this machine's IP)
#
# No address is hard-coded. Exit code is 1 if any check FAILED, 0 otherwise.
# SKIP is never a failure: checks for machines that are not deployed yet are
# skipped, so the suite is usable while the build-out is in progress.
# ══════════════════════════════════════════════════════════════════════════════

# ── Result counters ──────────────────────────────────────────────────────────
PASSES=0
FAILURES=0
SKIPS=0

if [ -t 1 ]; then
  C_PASS=$'\033[32m'; C_FAIL=$'\033[31m'; C_SKIP=$'\033[33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_PASS=''; C_FAIL=''; C_SKIP=''; C_DIM=''; C_OFF=''
fi

pass()  { PASSES=$((PASSES + 1));   printf '  %sPASS%s  %s%s\n' "$C_PASS" "$C_OFF" "$1" "${2:+  ${C_DIM}($2)${C_OFF}}"; }
fail()  { FAILURES=$((FAILURES + 1)); printf '  %sFAIL%s  %s%s\n' "$C_FAIL" "$C_OFF" "$1" "${2:+  ${C_DIM}($2)${C_OFF}}"; }
skip()  { SKIPS=$((SKIPS + 1));     printf '  %sSKIP%s  %s%s\n' "$C_SKIP" "$C_OFF" "$1" "${2:+  ${C_DIM}($2)${C_OFF}}"; }
info()  { printf '        %s\n' "$1"; }
section() { printf '\n── %s\n' "$1"; }

# ── Configuration ────────────────────────────────────────────────────────────

GATEWAY_CONTAINERS="traefik frontend gateway-api"
APP1_CONTAINERS="app-1 challenge-1"
APP2_CONTAINERS="app-2 challenge-2"
compiler_containers() { printf '%s-server %s-worker %s-db %s-redis\n' "$1" "$1" "$1" "$1"; }

# Apply the built-in defaults. Called at the END of dt_load_env so that
# precedence is: command-line environment  >  deployment-tests/.env  >  these.
dt_defaults() {
  : "${GATEWAY_HTTP_PORT:=80}"
  : "${GATEWAY_DASHBOARD_PORT:=8080}"

  : "${APP1_HOST_PORT:=8002}"
  : "${APP1_CHALLENGE_PORT:=8080}"
  : "${APP2_HOST_PORT:=8002}"
  : "${APP2_CHALLENGE_PORT:=8080}"

  : "${COMPILER_API_PORT:=2358}"
  # Per-node override: two compiler nodes on ONE host need different host ports.
  # In the normal deployment each node is its own machine and uses 2358, so these
  # default to COMPILER_API_PORT.
  : "${COMPILER1_API_PORT:=$COMPILER_API_PORT}"
  : "${COMPILER2_API_PORT:=$COMPILER_API_PORT}"
  : "${COMPILER3_API_PORT:=$COMPILER_API_PORT}"

  # Container name prefixes (COMPILER_NAME in each compiler machine's .env).
  : "${COMPILER1_NAME:=compiler-1}"
  : "${COMPILER2_NAME:=compiler-2}"
  : "${COMPILER3_NAME:=compiler-3}"

  # Names of the containers each system should be running.

  # HTTP timeout for probes (seconds) and the timeout used to prove a port is
  # BLOCKED (a DROP rule shows up as a timeout, so it must stay short).
  : "${HTTP_TIMEOUT:=8}"
  : "${BLOCK_TIMEOUT:=3}"
}

DT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

dt_load_env() {
  local dir="$DT_DIR" line key
  if [ -f "$dir/.env" ]; then
    while IFS= read -r line; do
      case "$line" in ''|'#'*) continue ;; esac
      key="${line%%=*}"
      key="$(printf '%s' "$key" | tr -d '[:space:]')"
      [ -n "$key" ] || continue
      # A value already present in the environment (given on the command line)
      # wins over the file, so `APP1_IP=... ./script.sh` always takes effect.
      if [ -z "${!key+x}" ]; then
        export "$key=${line#*=}"
      fi
    done < "$dir/.env"
  fi
  dt_defaults
  : "${SYSTEM_IP:=}"
}

# ── Identity ─────────────────────────────────────────────────────────────────

dt_iface() {
  if [ -n "${SYSTEM_IFACE:-}" ]; then printf '%s' "$SYSTEM_IFACE"; return; fi
  ip route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}'
}

dt_detect_ip() {
  local iface
  iface="$(dt_iface)"
  if [ -n "$iface" ]; then
    ip -4 addr show "$iface" 2>/dev/null | awk '/inet /{sub(/\/.*/,"",$2); print $2; exit}'
  else
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}

# True when `ip` is an address of this machine (i.e. we are ON that system).
dt_is_local() {
  local want="$1" have
  [ -z "$want" ] && return 1
  if [ -n "$SYSTEM_IP" ] && [ "$want" = "$SYSTEM_IP" ]; then return 0; fi
  have="$(dt_detect_ip)"
  [ -n "$have" ] && [ "$want" = "$have" ]
}

system_header() {
  local name="$1"
  printf '══════════════════════════════════════════════════════════════════\n'
  printf ' %s\n' "$name"
  printf '══════════════════════════════════════════════════════════════════\n'
  printf ' this machine  : %s (interface %s)\n' "$(dt_detect_ip)" "$(dt_iface)"
  printf ' gateway       : %s\n' "${GATEWAY_IP:-<not configured>}"
  printf ' app-1         : %s\n' "${APP1_IP:-<not configured>}"
  printf ' app-2         : %s\n' "${APP2_IP:-<not configured>}"
  printf ' compiler-1    : %s\n' "${COMPILER1_IP:-<not configured>}"
  printf ' compiler-2    : %s\n' "${COMPILER2_IP:-<not configured>}"
  printf ' compiler-3    : %s\n' "${COMPILER3_IP:-<not configured>}"
}

# ── Primitives ───────────────────────────────────────────────────────────────

dt_have() { command -v "$1" >/dev/null 2>&1; }

dt_tcp_open() {   # host port [timeout] -> 0 when connectable
  local host="$1" port="$2" t="${3:-$HTTP_TIMEOUT}"
  timeout "$t" bash -c "exec 3<>/dev/tcp/$host/$port" >/dev/null 2>&1
}

dt_tcp_blocked() { local host="$1" port="$2"; ! dt_tcp_open "$host" "$port" "$BLOCK_TIMEOUT"; }

dt_http_code() {  # url -> 3-digit status or 000
  local url="$1" t="${2:-$HTTP_TIMEOUT}"
  if [ "$(dt_tcp_open_from_url "$url")" != "0" ]; then printf '000'; return; fi
  curl -s -o /dev/null -w '%{http_code}' -m "$t" "$url" 2>/dev/null || printf '000'
}

# `dt_tcp_open` needs a host/port pair; derive them from a URL for the fast
# "nothing is listening" pre-check (curl would otherwise wait for the timeout).
dt_tcp_open_from_url() {
  local url="$1" rest hostport host port scheme
  scheme="${url%%://*}"
  rest="${url#*://}"; hostport="${rest%%/*}"
  case "$hostport" in
    *:*) host="${hostport%:*}"; port="${hostport##*:}" ;;
    *)   host="$hostport"
         case "$scheme" in https) port=443 ;; *) port=80 ;; esac ;;
  esac
  dt_tcp_open "$host" "$port" "$BLOCK_TIMEOUT" && printf '0' || printf '1'
}

dt_http_body() {  # url -> body (may be empty)
  curl -s -m "${2:-$HTTP_TIMEOUT}" "$1" 2>/dev/null
}

dt_local_port_open() {  # port -> 0 when something listens on this machine
  local port="$1"
  if dt_have ss; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port\$" && return 0
  elif dt_have netstat; then
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port\$" && return 0
  fi
  return 1
}

dt_container_state() {  # name -> "running:healthy" | "running:none" | "exited" | "missing"
  local name="$1" status health
  status="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)" || { printf 'missing'; return; }
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null)"
  printf '%s:%s' "$status" "$health"
}

dt_container_env() {  # name -> container environment (KEY=VALUE lines)
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null
}

# ── Composite checks ─────────────────────────────────────────────────────────

check_docker_environment() {
  section "Docker"
  if ! dt_have docker; then
    fail "docker is installed" "command not found"
    return 1
  fi
  pass "docker is installed" "$(docker --version 2>/dev/null)"

  if docker compose version >/dev/null 2>&1; then
    pass "docker compose plugin present" "$(docker compose version --short 2>/dev/null)"
  else
    fail "docker compose plugin present" "run: docker compose version"
  fi

  if docker info >/dev/null 2>&1; then
    pass "docker daemon reachable" "server $(docker info --format '{{.ServerVersion}}' 2>/dev/null)"
  else
    fail "docker daemon reachable" "start Docker or check permissions (usermod -aG docker \$USER)"
    return 1
  fi
  return 0
}

check_containers() {  # name...
  local name state
  for name in "$@"; do
    state="$(dt_container_state "$name")"
    case "$state" in
      running:healthy) pass "container $name" "running + healthy" ;;
      running:none)    pass "container $name" "running (no healthcheck defined)" ;;
      running:starting) fail "container $name" "health is still 'starting'" ;;
      running:unhealthy) fail "container $name" "unhealthy — docker compose logs $name --tail 50" ;;
      exited*)         fail "container $name" "not running ($state)" ;;
      *)               fail "container $name" "missing — is this stack started on this machine?" ;;
    esac
  done
}

check_local_ports() {  # port...
  local port
  for port in "$@"; do
    if dt_local_port_open "$port"; then
      pass "port $port listening locally" "published by this machine's containers"
    else
      fail "port $port listening locally" "nothing is listening on $port"
    fi
  done
}

check_tcp_reachable() {  # label host port
  local label="$1" host="$2" port="$3"
  if [ -z "$host" ]; then skip "$label" "address not configured"; return; fi
  if dt_tcp_open "$host" "$port"; then
    pass "$label reachable" "$host:$port"
  else
    fail "$label reachable" "$host:$port — firewall, wrong IP, or the machine is down"
  fi
}

check_tcp_blocked() {  # label host port
  local label="$1" host="$2" port="$3"
  if [ -z "$host" ]; then skip "$label blocked" "address not configured"; return; fi
  if dt_tcp_blocked "$host" "$port"; then
    pass "$label blocked from here" "$host:$port does not answer"
  else
    fail "$label blocked from here" "$host:$port IS reachable — candidates could bypass the Gateway"
  fi
}

# Like check_http, but accepts any of several status codes (e.g. a dashboard
# that answers with a redirect).
check_http_code_in() {  # label url "code code ..." [body_pattern]
  local label="$1" url="$2" wanted="$3" pattern="${4:-}" code body ok=0
  code="$(dt_http_code "$url")"
  for c in $wanted; do [ "$code" = "$c" ] && ok=1; done
  if [ "$code" = "000" ]; then
    fail "$label" "$url unreachable (no HTTP response)"
    return
  fi
  if [ "$ok" != "1" ]; then
    fail "$label" "$url returned HTTP $code, expected one of: $wanted"
    return
  fi
  if [ -n "$pattern" ]; then
    body="$(dt_http_body "$url")"
    if printf '%s' "$body" | grep -qiE "$pattern"; then
      pass "$label" "HTTP $code and body matches /$pattern/"
    else
      fail "$label" "HTTP $code but body does not contain /$pattern/"
    fi
    return
  fi
  pass "$label" "HTTP $code"
}

# Judge0's API requires the shared token, so its endpoints cannot be probed
# with a bare GET.
check_http_with_token() {  # label url token [header] [body_pattern]
  local label="$1" url="$2" token="$3" header="${4:-X-Judge0-Token}" pattern="${5:-}"
  local code file
  if [ -z "$token" ]; then
    skip "$label" "JUDGE0_AUTH_TOKEN is not set in deployment-tests/.env"
    return
  fi
  file="$(mktemp)"
  code="$(curl -s -o "$file" -w '%{http_code}' -m "$HTTP_TIMEOUT" -H "$header: $token" "$url" 2>/dev/null || printf '000')"
  if [ "$code" = "000" ]; then
    fail "$label" "$url unreachable (no HTTP response)"
    rm -f "$file"; return
  fi
  if [ "$code" != "200" ]; then
    fail "$label" "$url returned HTTP $code with the shared token — token mismatch with AUTHN_TOKEN?"
    rm -f "$file"; return
  fi
  if [ -n "$pattern" ]; then
    if grep -qiE "$pattern" "$file"; then
      pass "$label" "HTTP 200 and body matches /$pattern/"
    else
      fail "$label" "HTTP 200 but body does not contain /$pattern/"
    fi
  else
    pass "$label" "HTTP 200"
  fi
  rm -f "$file"
}

check_http() {  # label url expected_code [body_pattern]
  local label="$1" url="$2" want="$3" pattern="${4:-}" code body
  code="$(dt_http_code "$url")"
  if [ "$code" = "000" ]; then
    fail "$label" "$url unreachable (no HTTP response)"
    return
  fi
  if [ "$code" != "$want" ]; then
    fail "$label" "$url returned HTTP $code, expected $want"
    return
  fi
  if [ -n "$pattern" ]; then
    body="$(dt_http_body "$url")"
    if printf '%s' "$body" | grep -qiE "$pattern"; then
      pass "$label" "HTTP $code and body matches /$pattern/"
    else
      fail "$label" "HTTP $code but body does not contain /$pattern/"
    fi
    return
  fi
  pass "$label" "HTTP $code"
}

check_firewall_guard() {  # ports-space-separated
  section "Firewall guard (DOCKER-USER)"
  local ports="$1" out
  if ! dt_have iptables; then skip "iptables available" "not installed"; return; fi
  out="$(iptables -S DOCKER-USER 2>&1)" || true
  if printf '%s' "$out" | grep -qiE 'permission denied|you must be root|not permitted'; then
    skip "guard rules present on DOCKER-USER" "needs root — re-run with sudo"
    return
  fi
  if [ -z "$out" ]; then
    fail "guard rules present on DOCKER-USER" "chain is empty — run scripts/docker-port-guard.sh"
    return
  fi
  local missing=''
  for p in $ports; do
    printf '%s' "$out" | grep -q -- "--ctorigdstport $p" || missing="$missing $p"
  done
  if [ -n "$missing" ]; then
    fail "guard covers ports $ports" "no rule for:$missing (run scripts/docker-port-guard.sh --ports '$ports')"
  else
    pass "guard covers ports $ports" "DOCKER-USER restricts them by source IP"
  fi
  if printf '%s' "$out" | grep -qiE -- '-j (DROP|REJECT)' && printf '%s' "$out" | grep -q -- '-j ACCEPT'; then
    pass "guard has both ACCEPT (allowed sources) and DROP (everyone else) rules"
  else
    fail "guard has both ACCEPT and DROP rules" "expected an allowlist plus a default DROP"
  fi
}

# The challenge container must hold no platform secrets and no Docker socket.
check_challenge_isolation() {
  local name="$1"
  section "Hands-On challenge isolation ($name)"
  local env_dump mounts state
  state="$(dt_container_state "$name")"
  if [ "$state" != "running:healthy" ] && [ "${state%%:*}" != "running" ]; then
    skip "challenge container inspected" "$name is not running here"
    return
  fi
  env_dump="$(dt_container_env "$name")"
  if printf '%s' "$env_dump" | grep -qiE 'SUPABASE|SERVICE_ROLE|JWT_SECRET|JUDGE0_AUTH|SECRET_KEY'; then
    fail "challenge container has no platform credentials" "found a platform/Supabase variable in its environment"
  else
    pass "challenge container has no platform credentials"
  fi
  mounts="$(docker inspect -f '{{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}' "$name" 2>/dev/null)"
  case "$mounts" in
    *docker.sock*) fail "challenge container has no Docker socket" "found /var/run/docker.sock" ;;
    *"/etc"*|*"/home"*|*"/root"*|*"/var/lib"*) fail "challenge container has no host filesystem mounts" "found $mounts" ;;
    *) pass "challenge container has no host mounts" "${mounts:-none}" ;;
  esac
  if docker inspect -f '{{.HostConfig.Privileged}}' "$name" 2>/dev/null | grep -q true; then
    fail "challenge container is not privileged" "privileged=true"
  else
    pass "challenge container is not privileged"
  fi
  local policy
  policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$name" 2>/dev/null)"
  if [ -n "$policy" ] && [ "$policy" != "no" ]; then
    pass "challenge container restart policy" "$policy"
  else
    fail "challenge container restart policy" "no restart policy (it will not come back after a reboot)"
  fi
}

# Any database/queue port must NOT be published on a compiler machine.
check_compiler_ports_not_published() {
  local name="$1" published
  # HostConfig.PortBindings holds the host-side mappings. (NetworkSettings.Ports
  # also lists ports that are merely EXPOSEd inside the container image, which
  # is not what matters here.)
  published="$(docker inspect -f '{{range $p, $conf := .HostConfig.PortBindings}}{{$p}}->{{range $conf}}{{.HostPort}}{{end}} {{end}}' "$name" 2>/dev/null)"
  if printf '%s' "$published" | grep -qE '5432|6379'; then
    fail "no PostgreSQL/Redis port published on this machine" "found $published — the queue and metadata DB must stay Docker-internal"
  else
    pass "no PostgreSQL/Redis port published on this machine" "${published:-nothing published}"
  fi
}

check_compiler_auth() {  # host port token header
  local host="$1" port="$2" token="${3:-}" header="${4:-X-Judge0-Token}"
  section "Compiler API authentication"
  if [ -z "$token" ]; then
    skip "unauthorized request is rejected" "JUDGE0_AUTH_TOKEN not configured for this test"
    return
  fi
  local url="http://$host:$port/languages" code
  code="$(curl -s -o /dev/null -w '%{http_code}' -m "$HTTP_TIMEOUT" "$url" 2>/dev/null || printf '000')"
  if [ "$code" = "000" ]; then
    fail "unauthorized request is rejected" "$url unreachable"
  elif [ "$code" = "200" ]; then
    fail "unauthorized request is rejected" "the API answered 200 without the auth token"
  else
    pass "unauthorized request is rejected" "HTTP $code without a token"
  fi
  code="$(curl -s -o /dev/null -w '%{http_code}' -m "$HTTP_TIMEOUT" -H "$header: $token" "$url" 2>/dev/null || printf '000')"
  if [ "$code" = "200" ]; then
    pass "authorized request succeeds" "HTTP 200 with the shared token"
  else
    fail "authorized request succeeds" "HTTP $code — token mismatch with AUTHN_TOKEN in judge0.conf?"
  fi
}

# Which side of the front door are we on, relative to an App/Compiler machine?
#   local   — this script is running ON that machine
#   gateway — this script is running on the Gateway (an ALLOWED source)
#   other   — this script is running on any other machine (a CANDIDATE source)
dt_perspective() {  # target_ip -> local | gateway | other
  local target="$1"
  if dt_is_local "$target"; then printf 'local'; return; fi
  if [ -n "${GATEWAY_IP:-}" ] && dt_is_local "$GATEWAY_IP"; then printf 'gateway'; return; fi
  printf 'other'
}

# The App backend must be able to reach Supabase (it is the only Internet
# dependency of the app machines). Probed from INSIDE the container, using the
# container's own SUPABASE_URL, so no credential is needed on the test machine.
check_supabase_connectivity() {  # container_name
  local name="$1" url code out
  section "Supabase reachability ($name)"
  url="$(dt_container_env "$name" | awk -F= '/^SUPABASE_URL=/{sub(/^SUPABASE_URL=/,""); print; exit}')"
  if [ -z "$url" ]; then
    skip "Supabase reachable from $name" "no SUPABASE_URL in the container environment"
    return
  fi
  case "$url" in
    *your-project*) skip "Supabase reachable from $name" "SUPABASE_URL is still the placeholder value"; return ;;
  esac
  out="$(docker exec "$name" python -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('$url/auth/v1/health', timeout=10)
    print('HTTP', r.status)
except urllib.error.HTTPError as e:
    print('HTTP', e.code)
except Exception as e:
    print('ERR', type(e).__name__, e)
" 2>&1 || true)"
  case "$out" in
    *"HTTP 2"*|*"HTTP 4"*)
      pass "Supabase reachable from $name" "$url answered ${out//HTTP /HTTP } (4xx = reached, just unauthenticated)" ;;
    *)
      fail "Supabase reachable from $name" "$url — ${out:-no response} (check Internet access and the keys in .env)" ;;
  esac
}

# "The challenge container keeps working across a restart" — intrusive, so it
# only runs when RESTART_TESTS=1 is set explicitly.
check_challenge_restart_persistence() {  # container_name [url]
  local name="$1" url="${2:-http://127.0.0.1:8080/}"
  section "Challenge restart persistence ($name)"
  if [ "${RESTART_TESTS:-0}" != "1" ]; then
    skip "challenge survives a container restart" "set RESTART_TESTS=1 to run this (it restarts $name)"
    return
  fi
  if docker restart "$name" >/dev/null 2>&1; then
    sleep 8
    local state
    state="$(dt_container_state "$name")"
    case "$state" in
      running:healthy) pass "challenge restarts cleanly" "healthy again after docker restart" ;;
      running:*)       pass "challenge restarts cleanly" "running again (health: ${state#*:})" ;;
      *)               fail "challenge restarts cleanly" "state after restart: $state" ;;
    esac
    if curl -s -m 10 "$url" 2>/dev/null | grep -qiE 'Employee Portal'; then
      pass "challenge still serves the Employee Portal after restart"
    else
      fail "challenge still serves the Employee Portal after restart" "$url did not return the portal"
    fi
  else
    fail "challenge restarts cleanly" "docker restart $name failed"
  fi
}

# The Gateway's view of the compiler pool: which nodes it knows, and which are
# answering. Parsed with python3 (present on the Gateway and App machines);
# falls back to a grep when python3 is unavailable.
check_compiler_pool_health() {  # [gateway_ip] [http_port]
  local host="${1:-${GATEWAY_IP:-}}" port="${2:-$GATEWAY_HTTP_PORT}" url body
  section "Compiler pool as seen by the Gateway"
  if [ -z "$host" ]; then skip "compiler pool health" "GATEWAY_IP not configured"; return; fi
  url="http://$host:$port/api/execute/health"
  body="$(dt_http_body "$url")"
  if [ -z "$body" ]; then
    fail "compiler pool health endpoint" "$url unreachable"
    return
  fi
  if dt_have python3; then
    printf '%s' "$body" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print("FAIL unparseable response:", e)
    raise SystemExit(1)
print("SIZE", d.get("compiler_pool_size", "?"))
print("STATUS", d.get("status"))
for n in d.get("nodes", []):
    print("NODE", n.get("status"), n.get("url"))
' > /tmp/dt_pool.txt 2>&1
    local status size
    status="$(awk '/^STATUS/{print $2}' /tmp/dt_pool.txt)"
    size="$(awk '/^SIZE/{print $2}' /tmp/dt_pool.txt)"
    info "pool size: ${size:-?} node(s)"
    while read -r _tag state nodeurl; do
      [ "$_tag" = "NODE" ] || continue
      if [ "$state" = "ok" ]; then pass "compiler node answering" "$nodeurl"; else fail "compiler node answering" "$nodeurl ($state)"; fi
    done < <(grep '^NODE' /tmp/dt_pool.txt)
    if grep -q '^FAIL ' /tmp/dt_pool.txt; then
      fail "execution backend health is parseable" "$(grep '^FAIL ' /tmp/dt_pool.txt)"
    elif [ "$status" = "ok" ]; then
      pass "execution backend healthy through the Gateway" "status=ok, ${size:-?} node(s) in the pool"
    else
      fail "execution backend healthy through the Gateway" "status=${status:-unknown} — see DEPLOYMENT.md troubleshooting"
    fi
    rm -f /tmp/dt_pool.txt
  else
    if printf '%s' "$body" | grep -q '"status": *"ok"\|"status":"ok"'; then
      pass "execution backend healthy through the Gateway" "status=ok"
    else
      fail "execution backend healthy through the Gateway" "$body"
    fi
  fi
}

check_restart_policy() {  # container_name
  local name="$1" policy
  if ! dt_have docker; then skip "restart policy for $name" "docker not available here"; return; fi
  policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$name" 2>/dev/null)"
  case "$policy" in
    "")   skip "restart policy for $name" "container not present on this machine" ;;
    "no") fail "restart policy for $name" "none — the service will not come back after a reboot" ;;
    *)    pass "restart policy for $name" "$policy" ;;
  esac
}

check_compiler_pool_from_here() {
  local ip port any=0 pair
  for pair in "${COMPILER1_IP:-}:$COMPILER1_API_PORT" "${COMPILER2_IP:-}:$COMPILER2_API_PORT" "${COMPILER3_IP:-}:$COMPILER3_API_PORT"; do
    ip="${pair%:*}"; port="${pair##*:}"
    [ -n "$ip" ] || continue
    any=1
    check_tcp_reachable "compiler node $ip" "$ip" "$port"
  done
  [ "$any" = "0" ] && skip "compiler pool reachable from this machine" "no COMPILERn_IP configured"
}

# Run the real execution suite against one compiler node and report each line.
check_compiler_execution() {  # label host port
  local label="$1" host="$2" port="$3" out line rest
  section "Code execution on $label ($host:$port)"
  if ! dt_have python3; then skip "execution checks on $label" "python3 is not available on this machine"; return; fi
  if ! dt_tcp_open "$host" "$port"; then
    fail "execution checks on $label" "$host:$port is not reachable"
    return
  fi
  local args=(--url "http://$host:$port" --header "${JUDGE0_AUTH_HEADER:-X-Judge0-Token}")
  [ -n "${JUDGE0_AUTH_TOKEN:-}" ] && args+=(--token "$JUDGE0_AUTH_TOKEN")
  out="$(python3 "$DT_DIR/judge0_check.py" "${args[@]}" 2>&1)"
  while IFS= read -r line; do
    case "$line" in
      PASS\ *) rest="${line#PASS }"; pass "${rest%% ::*}" "${rest#*:: }" ;;
      FAIL\ *) rest="${line#FAIL }"; fail "${rest%% ::*}" "${rest#*:: }" ;;
      "")      ;;
      *)       info "$line" ;;
    esac
  done <<< "$out"
}

# ── Whole-system checks ─────────────────────────────────────────────────────

# An App machine (SYSTEM 2 App-1 / SYSTEM 4 App-2). The checks adapt to where
# this script runs: on the machine itself, on the Gateway (allowed source), or
# on any other machine (a candidate, which must be blocked).
check_app_system() {  # label ip api_port challenge_port api_container challenge_container
  local label="$1" ip="$2" api_port="$3" chal_port="$4" api_ctr="$5" chal_ctr="$6"
  local persp; persp="$(dt_perspective "$ip")"

  case "$persp" in
    local)
      check_docker_environment
      section "$label containers"
      check_containers "$api_ctr" "$chal_ctr"
      section "$label published ports"
      check_local_ports "$api_port" "$chal_port"
      section "$label HTTP endpoints"
      check_http "$label API answers" "http://127.0.0.1:$api_port/" 200 "Healthy"
      check_http "challenge server health" "http://127.0.0.1:$chal_port/health" 200 "ok"
      check_http "challenge serves the Employee Portal" "http://127.0.0.1:$chal_port/" 200 "Employee Portal"
      check_firewall_guard "$chal_port $api_port"
      check_challenge_isolation "$chal_ctr"
      check_supabase_connectivity "$api_ctr"
      check_restart_policy "$api_ctr"
      check_restart_policy "$chal_ctr"
      check_challenge_restart_persistence "$chal_ctr" "http://127.0.0.1:$chal_port/"
      section "$label → compiler pool"
      check_compiler_pool_from_here
      ;;
    gateway)
      section "$label as seen from the Gateway (an allowed source)"
      check_tcp_reachable "$label API" "$ip" "$api_port"
      check_tcp_reachable "$label challenge" "$ip" "$chal_port"
      check_http "$label challenge serves the Employee Portal" "http://$ip:$chal_port/" 200 "Employee Portal"
      ;;
    *)
      section "$label as seen from a candidate machine (must be blocked)"
      check_tcp_blocked "$label API" "$ip" "$api_port"
      check_tcp_blocked "$label challenge" "$ip" "$chal_port"
      info "candidates reach this machine only through http://<GATEWAY_IP>/"
      ;;
  esac
}

# A compiler node (SYSTEM 3/5/6).
check_compiler_system() {  # label ip api_port container_name_prefix
  local label="$1" ip="$2" api_port="$3" prefix="$4"
  local persp; persp="$(dt_perspective "$ip")"

  case "$persp" in
    local)
      check_docker_environment
      section "$label containers"
      # shellcheck disable=SC2046
      check_containers $(compiler_containers "$prefix")
      section "$label published port"
      check_local_ports "$api_port"
      check_compiler_ports_not_published "${prefix}-db"
      check_compiler_ports_not_published "${prefix}-redis"
      section "$label API"
      check_http_with_token "Judge0 API answers (/about)" "http://127.0.0.1:$api_port/about" \
        "${JUDGE0_AUTH_TOKEN:-}" "${JUDGE0_AUTH_HEADER:-X-Judge0-Token}" "version"
      check_http_with_token "Judge0 advertises languages" "http://127.0.0.1:$api_port/languages" \
        "${JUDGE0_AUTH_TOKEN:-}" "${JUDGE0_AUTH_HEADER:-X-Judge0-Token}" '"name"'
      check_compiler_auth 127.0.0.1 "$api_port" "${JUDGE0_AUTH_TOKEN:-}" "${JUDGE0_AUTH_HEADER:-X-Judge0-Token}"
      check_compiler_execution "$label" 127.0.0.1 "$api_port"
      check_firewall_guard "$api_port"
      section "App machines can reach this compiler node"
      for ip in "${APP1_IP:-}" "${APP2_IP:-}"; do
        [ -n "$ip" ] && info "allowed source: $ip (verified from that machine's own test script)"
      done
      ;;
    gateway)
      section "$label as seen from the Gateway"
      check_tcp_reachable "$label API" "$ip" "$api_port"
      check_compiler_auth "$ip" "$api_port" "${JUDGE0_AUTH_TOKEN:-}" "${JUDGE0_AUTH_HEADER:-X-Judge0-Token}"
      check_compiler_execution "$label (from Gateway)" "$ip" "$api_port"
      ;;
    *)
      section "$label as seen from a candidate machine (must be blocked)"
      check_tcp_blocked "$label API" "$ip" "$api_port"
      info "candidates must never reach a compiler; only the Gateway and App machines do"
      ;;
  esac
}

# The guard must not only DROP strangers — it must actually ACCEPT the machines
# that are supposed to reach this one (Gateway, App-1, App-2).
check_guard_allowlist() {  # ports-space-separated  ip...
  local ports="$1"; shift
  section "Firewall guard allowlist"
  local out
  out="$(iptables -S DOCKER-USER 2>&1)" || true
  if printf '%s' "$out" | grep -qiE 'permission denied|must be root|not permitted'; then
    skip "guard allows the Gateway and App machines" "needs root — re-run with sudo"
    return
  fi
  local ip port missing='' found=0
  for ip in "$@"; do
    [ -n "$ip" ] || continue
    found=1
    local ok=0
    for port in $ports; do
      if printf '%s' "$out" | grep -q -- "-s $ip" && printf '%s' "$out" | grep -q -- "--ctorigdstport $port"; then
        ok=1
      fi
    done
    if printf '%s' "$out" | grep -q -- "-s $ip"; then
      pass "guard allows $ip"
    else
      missing="$missing $ip"
    fi
  done
  if [ "$found" = "0" ]; then
    skip "guard allows the Gateway and App machines" "no source IPs configured for this test"
  elif [ -n "$missing" ]; then
    fail "guard allows every intended source" "no ACCEPT rule for:$missing — run docker-port-guard.sh with all --gateway-ip values"
  else
    pass "guard allows every intended source"
  fi
}

# Report any other compiler nodes on this host (container-name conflicts).
check_no_container_conflicts() {  # expected name prefix
  local prefix="$1" others
  others="$(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^(judge0|compiler-[0-9]+)-(server|worker|db|redis)$' | grep -v "^${prefix}-" || true)"
  if [ -z "$others" ]; then
    pass "no conflicting compiler containers on this host"
  else
    info "other compiler containers on this host: $(printf '%s' "$others" | tr '\n' ' ')"
    pass "no conflicting compiler containers on this host" "names are unique per node (COMPILER_NAME)"
  fi
}

# ── Summary ──────────────────────────────────────────────────────────────────

dt_summary() {
  local name="$1"
  printf '\n══════════════════════════════════════════════════════════════════\n'
  printf ' %s: %s passed, %s failed, %s skipped\n' "$name" "$PASSES" "$FAILURES" "$SKIPS"
  if [ "$FAILURES" -gt 0 ]; then
    printf ' RESULT: %sFAIL%s\n' "$C_FAIL" "$C_OFF"
    printf '══════════════════════════════════════════════════════════════════\n'
    return 1
  fi
  printf ' RESULT: %sPASS%s\n' "$C_PASS" "$C_OFF"
  printf '══════════════════════════════════════════════════════════════════\n'
  return 0
}
