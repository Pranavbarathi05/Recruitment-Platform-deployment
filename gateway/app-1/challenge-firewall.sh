#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# MOVED — this guard is now shared by every system in the deployment.
#
#   new location: gateway/scripts/docker-port-guard.sh
#
# It is the same DOCKER-USER guard (conntrack --ctorigdstport matching, per
# interface, idempotent, --remove), renamed so App-1, App-2 and the Compiler
# machines all install one implementation instead of several copies.
#
# Install the new script:
#   sudo install -m 755 gateway/scripts/docker-port-guard.sh /opt/recruit/
#   sudo ./gateway/scripts/docker-port-guard.sh --gateway-ip <GATEWAY_LAN_IP>
#
# This file remains only so that existing instructions and already-copied
# installs keep working. It forwards every argument to the new script.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in \
  "${here}/../scripts/docker-port-guard.sh" \
  "${here}/docker-port-guard.sh" \
  "/opt/recruit/docker-port-guard.sh"
do
  if [[ -x $candidate || -f $candidate ]]; then
    exec bash "$candidate" "$@"
  fi
done

cat >&2 <<'EOF'
ERROR: docker-port-guard.sh was not found next to this file.

This guard moved to gateway/scripts/docker-port-guard.sh. Copy it with this
file, or run it directly:

  sudo install -m 755 gateway/scripts/docker-port-guard.sh /opt/recruit/
  sudo /opt/recruit/docker-port-guard.sh --gateway-ip <GATEWAY_LAN_IP>
EOF
exit 1
