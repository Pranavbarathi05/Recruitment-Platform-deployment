#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# App 1 — restrict Docker-published ports to the Gateway machine only
# ══════════════════════════════════════════════════════════════════════════════
#
# WHY THIS EXISTS
# Docker-published ports (challenge-1 :8080, app-1 :8002) are NOT filtered by
# UFW/INPUT rules: traffic from another machine is DNAT'ed in PREROUTING and
# forwarded straight through the FORWARD chain (DOCKER-USER → DOCKER-FORWARD →
# DOCKER → ACCEPT), never touching INPUT. See Docker docs "Packet filtering
# and firewalls". The only reliable place to restrict them is DOCKER-USER,
# which Docker deliberately leaves for the operator and evaluates FIRST.
#
# WHAT IT DOES
#   - Forwards are only allowed to --ports from --gateway-ip sources arriving
#     on --iface (the LAN interface). Everyone else on that interface → DROP.
#   - IPv6: dropped for the same ports unless --gateway-ip6 addresses are given.
#   - Container↔container and container→LAN traffic is untouched (rules are
#     keyed on the external input interface only).
#   - Idempotent; safe to re-run. --remove undoes everything.
#
# USAGE (run as root ON THE APP-1 MACHINE, after Docker is up)
#   ./challenge-firewall.sh --gateway-ip 192.168.1.10            # allowlist
#   ./challenge-firewall.sh --gateway-ip 192.168.1.10 --remove   # undo
#
# PERSISTENCE: these rules do not survive reboot. Install the provided
# challenge-firewall.service (After=docker.service) or call this script from
# your own unit. See DEPLOYMENT.md → Firewall.

set -euo pipefail

GATEWAY_IPS=()
GATEWAY_IP6S=()
PORTS="8080 8002"
IFACE=""
REMOVE=0
COMMENT="challenge-guard"

usage() { grep -E '^# (USAGE|  \./)' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gateway-ip)  GATEWAY_IPS+=("$2"); shift 2 ;;
    --gateway-ip6) GATEWAY_IP6S+=("$2"); shift 2 ;;
    --ports)       PORTS="$2"; shift 2 ;;
    --iface)       IFACE="$2"; shift 2 ;;
    --remove)      REMOVE=1; shift ;;
    -h|--help)     usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ ${#GATEWAY_IPS[@]} -eq 0 && $REMOVE -eq 0 ]] && { echo "ERROR: --gateway-ip is required (or use --remove)" >&2; usage; }

# Default to the default-route interface (the LAN NIC) if not given.
if [[ -z $IFACE ]]; then
  IFACE=$(ip route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
fi
[[ -z $IFACE ]] && { echo "ERROR: cannot detect LAN interface, pass --iface" >&2; exit 1; }

command -v iptables >/dev/null || { echo "ERROR: iptables not found" >&2; exit 1; }
iptables -nL DOCKER-USER >/dev/null 2>&1 || {
  echo "ERROR: DOCKER-USER chain missing — is Docker running? (docker compose up -d first)" >&2
  exit 1
}

# Delete only rules we own (matched by our comment prefix) on the given
# chain/command — scoped to the interface being (re)configured so separate
# per-interface guards can coexist. Idempotent.
delete_our_rules() {
  local cmd=$1 chain=$2 iface=$3 rules line pat tries=0
  # iptables -S prints comments quoted: --comment "challenge-guard"
  pat="--comment \"?${COMMENT}"
  while true; do
    rules=$($cmd -S "$chain" 2>/dev/null | grep -E -- "$pat" || true)
    if [[ -n $iface ]]; then
      rules=$(printf '%s\n' "$rules" | grep -- "-i $iface " || true)
    else
      # No-iface pass owns only rules WITHOUT -i (the RETURN footer), so
      # per-interface guards for other interfaces are left alone.
      rules=$(printf '%s\n' "$rules" | grep -v -- ' -i ' || true)
    fi
    [[ -z $rules ]] && break
    if (( ++tries > 50 )); then
      echo "WARNING: could not fully clean $cmd $chain (iface=$iface) after 50 passes" >&2
      break
    fi
    while IFS= read -r line; do
      [[ -z $line ]] && continue
      # shellcheck disable=SC2086
      $cmd -D "$chain" ${line#-A $chain } 2>/dev/null || true
    done <<< "$rules"
  done
}

DPORTS=$(echo "$PORTS" | tr ' ' ',')

if [[ $REMOVE -eq 1 ]]; then
  delete_our_rules iptables DOCKER-USER "$IFACE"
  delete_our_rules iptables DOCKER-USER ""          # -i-less RETURN footer
  if command -v ip6tables >/dev/null; then
    delete_our_rules ip6tables DOCKER-USER "$IFACE"
    delete_our_rules ip6tables DOCKER-USER ""
  fi
  echo "challenge-firewall: rules removed ($IFACE)."
  exit 0
fi

delete_our_rules iptables DOCKER-USER "$IFACE"   # idempotency per interface
delete_our_rules iptables DOCKER-USER ""          # refresh the RETURN footer

# Rules are per-port, matched on the conntrack ORIGINAL-direction destination
# port (--ctorigdstport) — i.e. the pre-DNAT HOST port the client dialled.
# This is required because inside DOCKER-USER the packet's dst port has
# already been rewritten to the CONTAINER port (host 8080→container 8080
# matches by luck; host 8002→container 8000 would NOT match a plain --dport
# 8002 rule). --ctdir ORIGINAL restricts matching to the inbound direction
# so reply traffic is never misclassified.
add_guard_rules() {
  local ipt_cmd=$1 use6=$2 port gip
  for port in $PORTS; do
    $ipt_cmd -I DOCKER-USER 1 -i "$IFACE" -p tcp \
      -m conntrack --ctdir ORIGINAL --ctorigdstport "$port" \
      -m comment --comment "$COMMENT" -j DROP
    if [[ $use6 == 6 ]]; then
      for gip in "${GATEWAY_IP6S[@]}"; do
        $ipt_cmd -I DOCKER-USER 1 -i "$IFACE" -s "$gip" -p tcp \
          -m conntrack --ctdir ORIGINAL --ctorigdstport "$port" \
          -m comment --comment "$COMMENT" -j ACCEPT
      done
    else
      for gip in "${GATEWAY_IPS[@]}"; do
        $ipt_cmd -I DOCKER-USER 1 -i "$IFACE" -s "$gip" -p tcp \
          -m conntrack --ctdir ORIGINAL --ctorigdstport "$port" \
          -m comment --comment "$COMMENT" -j ACCEPT
      done
    fi
  done
}

# Canonical DOCKER-USER footer: everything we did not match continues to the
# normal Docker forwarding rules (container↔container, replies, etc.).
add_footer() {
  $1 -A DOCKER-USER -m comment --comment "${COMMENT}-end" -j RETURN
}

add_guard_rules iptables 4
add_footer iptables

# IPv6: published ports are closed to IPv6 unless --gateway-ip6 addresses
# are given (then they form the allowlist; with none provided the DROP-only
# rules simply close the ports).
if command -v ip6tables >/dev/null && ip6tables -nL DOCKER-USER >/dev/null 2>&1; then
  add_guard_rules ip6tables 6
  add_footer ip6tables
fi

echo "challenge-firewall: $IFACE: ports {$DPORTS} restricted to: ${GATEWAY_IPS[*]}"
echo "  verify: iptables -S DOCKER-USER"
