#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# FIREWALL KERNEL TEST — prove a second LAN machine is blocked
#
# Docker-published ports are NOT filtered by UFW/INPUT rules: a packet from
# another machine is DNAT'ed in PREROUTING and forwarded through the FORWARD
# chain (DOCKER-USER → DOCKER-FORWARD → DOCKER), never touching INPUT. This
# script proves that the DOCKER-USER guard actually stops such a packet, using a
# network namespace as a *real* second machine: the traffic traverses the genuine
# PREROUTING → FORWARD → DOCKER-USER path with a foreign source address.
#
# It tests all three outcomes:
#   1. before the guard — the foreign source CAN reach the published port
#   2. after the guard  — the foreign source is BLOCKED
#   3. allowlisted source — CAN still reach it (the guard is not a blanket block)
#
# Needs root, and creates/removes a namespace + veth pair. It does not touch the
# machine's real interfaces except to (optionally) re-apply the production guard
# with --restore-prod.
#
#   sudo ./deployment-tests/firewall-kernel-test.sh --ports "2358 8080 8002"
#   sudo ./deployment-tests/firewall-kernel-test.sh --ports 2358 --restore-prod
#
# With --restore-prod it finishes by re-applying the guard on the real LAN
# interface with the allowlists from deployment-tests/.env, so the machine is
# left in the intended production posture.
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="FIREWALL KERNEL TEST"
PORTS="2358 8080 8002"
RESTORE_PROD=0
GUARD="$HERE/../gateway/scripts/docker-port-guard.sh"

NS_HOST_IP="10.99.99.1"
NS_CAND_IP="10.99.99.2"
VETH_HOST="dt-veth-host"
VETH_CAND="dt-veth-cand"
NS="dt-candidate"

while [ $# -gt 0 ]; do
  case "$1" in
    --ports) PORTS="$2"; shift 2 ;;
    --restore-prod) RESTORE_PROD=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

system_header "$NAME"
info "ports under test : $PORTS"
info "simulated candidate source: $NS_CAND_IP (a machine on the LAN, not this host)"

if [ "$(id -u)" -ne 0 ]; then
  fail "running as root" "re-run with sudo (the test creates a namespace and reads iptables)"
  dt_summary "$NAME"
  exit 1
fi
if [ ! -f "$GUARD" ]; then
  fail "guard script present" "$GUARD not found"
  dt_summary "$NAME"
  exit 1
fi

cleanup() {
  # Remove this test's rules and namespace. Never leaves the machine worse off.
  bash "$GUARD" --remove --iface "$VETH_HOST" >/dev/null 2>&1 || true
  ip netns del "$NS" >/dev/null 2>&1 || true
  ip link del "$VETH_HOST" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ── Build the simulated second machine ──────────────────────────────────────
section "Simulated candidate machine (network namespace)"
cleanup
if ! ip netns add "$NS" 2>/dev/null; then
  fail "create network namespace" "ip netns add failed (kernel support for namespaces?)"
  dt_summary "$NAME"
  exit 1
fi
ip link add "$VETH_HOST" type veth peer name "$VETH_CAND"
ip link set "$VETH_CAND" netns "$NS"
ip addr add "$NS_HOST_IP/24" dev "$VETH_HOST"
ip link set "$VETH_HOST" up
ip netns exec "$NS" ip addr add "$NS_CAND_IP/24" dev "$VETH_CAND"
ip netns exec "$NS" ip link set "$VETH_CAND" up
ip netns exec "$NS" ip link set lo up
pass "simulated machine created" "$NS at $NS_CAND_IP (host side $VETH_HOST = $NS_HOST_IP)"

probe() {  # port -> prints reachable|blocked
  if ip netns exec "$NS" timeout 3 bash -c "exec 3<>/dev/tcp/$NS_HOST_IP/$1" >/dev/null 2>&1; then
    printf 'reachable'
  else
    printf 'blocked'
  fi
}

# ── 1. Before the guard ─────────────────────────────────────────────────────
section "1. Before the guard (documents the actual hole)"
bash "$GUARD" --remove --iface "$VETH_HOST" >/dev/null 2>&1 || true
hole=0
for p in $PORTS; do
  if [ "$(probe "$p")" = "reachable" ]; then
    info "port $p reachable from the simulated machine (no guard installed)"
    hole=1
  fi
done
if [ "$hole" = "1" ]; then
  pass "the bypass is real: published ports answer a foreign source without the guard"
else
  info "none of the tested ports were reachable even before the guard"
  info "(nothing published yet, or a guard is already installed on another interface)"
fi

# ── 2. Install the guard for the simulated machine's interface ──────────────
section "2. Guard installed — a foreign source must be blocked"
bash "$GUARD" --iface "$VETH_HOST" --ports "$PORTS" --gateway-ip "$(dt_detect_ip)" >/dev/null
for p in $PORTS; do
  result="$(probe "$p")"
  if [ "$result" = "blocked" ]; then
    pass "port $p blocked from the simulated candidate machine"
  else
    fail "port $p blocked from the simulated candidate machine" "the guard did not stop the packet"
  fi
done

# ── 3. An allowlisted source must still get through ─────────────────────────
section "3. Allowlisted source must still be allowed"
bash "$GUARD" --iface "$VETH_HOST" --ports "$PORTS" --gateway-ip "$NS_CAND_IP" >/dev/null
allowed=0
denied=0
for p in $PORTS; do
  if [ "$(probe "$p")" = "reachable" ]; then allowed=$((allowed + 1)); else denied=$((denied + 1)); fi
done
if [ "$allowed" -gt 0 ]; then
  pass "an allowlisted source still reaches the ports" "$allowed of the tested ports answered"
else
  fail "an allowlisted source still reaches the ports" "all $denied tested ports stayed blocked — check the port is published"
fi

# ── 4. Idempotency + clean removal ──────────────────────────────────────────
section "4. Idempotency and removal"
before="$(iptables -S DOCKER-USER 2>/dev/null | grep -c -- "$VETH_HOST" || true)"
bash "$GUARD" --iface "$VETH_HOST" --ports "$PORTS" --gateway-ip "$(dt_detect_ip)" >/dev/null
after="$(iptables -S DOCKER-USER 2>/dev/null | grep -c -- "$VETH_HOST" || true)"
if [ "$before" = "$after" ]; then
  pass "re-running the guard does not duplicate rules" "$after rule(s) for $VETH_HOST before and after"
else
  fail "re-running the guard does not duplicate rules" "$before → $after rules"
fi
bash "$GUARD" --remove --iface "$VETH_HOST" >/dev/null
if iptables -S DOCKER-USER 2>/dev/null | grep -q -- "$VETH_HOST"; then
  fail "--remove clears this interface's rules" "rules for $VETH_HOST are still present"
else
  pass "--remove clears this interface's rules"
fi

# ── 5. Restore the production posture ───────────────────────────────────────
if [ "$RESTORE_PROD" = "1" ]; then
  section "5. Production posture on the real LAN interface"
  # Every source that must reach this machine, de-duplicated (this host's own
  # address is included so a same-host deployment keeps working).
  sources="$(printf '%s\n%s\n%s\n%s\n' "$(dt_detect_ip)" "${GATEWAY_IP:-}" "${APP1_IP:-}" "${APP2_IP:-}" \
            | grep -v '^$' | sort -u | tr '\n' ' ')"
  allow=()
  for ip in $sources; do allow+=(--gateway-ip "$ip"); done
  info "allowed sources: $sources"
  bash "$GUARD" --ports "$PORTS" "${allow[@]}"
  bash "$GUARD" --ports "$PORTS" "${allow[@]}" >/dev/null
  if iptables -S DOCKER-USER 2>/dev/null | grep -q -- "--ctorigdstport"; then
    pass "guard active on the real LAN interface" "ports: $PORTS"
  else
    fail "guard active on the real LAN interface" "no rules found — check the output above"
  fi
else
  section "5. Production posture"
  skip "re-applied on the real LAN interface" "pass --restore-prod to leave the machine in the production posture"
fi

dt_summary "$NAME"
