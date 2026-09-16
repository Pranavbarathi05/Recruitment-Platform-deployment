#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM 4 — APP-2 test
#
# Same checks as the App-1 script, using the App-2 variables, plus the things
# that are specific to App-2:
#   * it must not reference App-1 (its .env is independent);
#   * it must use the SAME Supabase project (not a second database);
#   * challenge-2 must keep its own database — no shared volume with challenge-1;
#   * the Gateway must be able to reach App-2, and candidates must not.
#
#   APP2_IP=10.0.0.12 ./deployment-tests/system4-app2-test.sh      # from anywhere
#   ./deployment-tests/system4-app2-test.sh                        # on App-2 itself
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dt_load_env

NAME="SYSTEM 4 — App-2"
if [ -z "${APP2_IP:-}" ]; then
  skip_app2=1
fi
system_header "$NAME"

if [ "${skip_app2:-0}" = "1" ]; then
  section "App-2 not deployed yet"
  skip "App-2 checks" "APP2_IP is not configured in deployment-tests/.env — App-2 is not part of this deployment"
  info "Deploy it (gateway/app-2/), add APP2_URL + APP2_CHALLENGE_URL to the Gateway's .env, then set APP2_IP here."
  dt_summary "$NAME"
  exit $?
fi

check_app_system "App-2" "$APP2_IP" "$APP2_HOST_PORT" "$APP2_CHALLENGE_PORT" app-2 challenge-2

# ── App-2 specific configuration checks ──────────────────────────────────────
if [ "$(dt_perspective "$APP2_IP")" = "local" ] && dt_have docker; then
  section "App-2 configuration"
  env_dump="$(dt_container_env app-2)"
  supabase_url="$(printf '%s\n' "$env_dump" | awk -F= '/^SUPABASE_URL=/{sub(/^SUPABASE_URL=/,""); print; exit}')"
  if [ -z "$supabase_url" ]; then
    fail "Supabase project configured" "no SUPABASE_URL in the app-2 container"
  elif printf '%s' "$supabase_url" | grep -q 'your-project'; then
    fail "Supabase project configured" "SUPABASE_URL is still the placeholder value"
  else
    pass "Supabase project configured" "$supabase_url (must be the SAME project as App-1)"
  fi
  if [ -n "${SUPABASE_URL:-}" ] && [ "$supabase_url" != "$SUPABASE_URL" ]; then
    fail "App-2 uses the same Supabase project as the platform" \
      "App-2 has '$supabase_url' but SUPABASE_URL here is '$SUPABASE_URL'"
  fi

  if printf '%s' "$env_dump" | grep -qiE '^APP1_|app-1'; then
    fail "App-2 does not reference App-1" "found an App-1 reference in App-2's configuration"
  else
    pass "App-2 does not reference App-1"
  fi

  pool="$(printf '%s\n' "$env_dump" | grep -E '^COMPILER_[123]_URL=' | sed 's/^COMPILER_[123]_URL=//' | grep -v '^$' | tr '\n' ' ')"
  if [ -n "$pool" ]; then
    pass "compiler pool configured for App-2" "$pool"
  else
    single="$(printf '%s\n' "$env_dump" | awk -F= '/^JUDGE0_BASE_URL=/{print $2}')"
    if [ -n "$single" ]; then
      pass "single compiler node configured for App-2" "$single"
    else
      fail "compiler endpoint configured for App-2" "neither COMPILER_n_URL nor JUDGE0_BASE_URL is set"
    fi
  fi

  section "Challenge database isolation"
  c2_volumes="$(docker inspect -f '{{range .Mounts}}{{.Name}}{{.Source}} {{end}}' challenge-2 2>/dev/null | xargs || true)"
  if [ -z "$c2_volumes" ] || [ "$c2_volumes" = "" ]; then
    pass "challenge-2 keeps its own database" "no shared volume mounted"
  else
    fail "challenge-2 keeps its own database" "unexpected mounts: $c2_volumes"
  fi
  if docker inspect -f '{{.Image}}' challenge-2 2>/dev/null >/dev/null; then
    img2="$(docker inspect -f '{{.Image}}' challenge-2 2>/dev/null)"
    if docker inspect -f '{{.Image}}' challenge-1 >/dev/null 2>&1; then
      img1="$(docker inspect -f '{{.Image}}' challenge-1 2>/dev/null)"
      if [ "$img1" = "$img2" ]; then
        info "challenge-1 and challenge-2 use the same image (both on this host)"
      fi
    fi
  fi
fi

# ── Gateway routing must now include App-2 ──────────────────────────────────
if [ -n "${GATEWAY_IP:-}" ] && [ "$(dt_perspective "$GATEWAY_IP")" != "local" ]; then
  section "App-2 registered with the Gateway"
  check_tcp_reachable "App-2 API from this machine" "$APP2_IP" "$APP2_HOST_PORT"
fi

dt_summary "$NAME"
