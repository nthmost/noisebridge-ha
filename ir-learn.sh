#!/usr/bin/env bash
#
# ir-learn.sh — Guided IR learning for the "Front Hall IR Blaster"
#               (Broadlink RM4 mini, HA entity remote.ir_blaster_1)
#
# Usage:
#   ./ir-learn.sh                       Interactive guided session (easiest)
#   ./ir-learn.sh learn DEVICE CMD...   Learn one or more buttons for a device
#   ./ir-learn.sh send  DEVICE CMD      Replay a learned command (test it)
#   ./ir-learn.sh list                  List everything learned so far
#   ./ir-learn.sh delete DEVICE CMD     Forget a learned command
#
# "DEVICE" = the appliance you're teaching it (e.g. tv, soundbar, projector)
# "CMD"    = the button name (e.g. power, vol_up, input, mute)
#
set -euo pipefail

ENV_FILE="/home/nthmost/.claude/projects/-home-nthmost-projects-sysadmin/.ha_env"
ENTITY="remote.ir_blaster_1"
MAC="348e892dc50d"
BLASTER_IP="10.21.1.54"   # RM4 mini sleeps its WiFi radio when idle; we ping it
                          # continuously during a learn so HA's commands land fast.
CODES_FILE="/config/.storage/broadlink_remote_${MAC}_codes"
SSH="ssh -p 2222 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 hassio@homeassistant.local"

# shellcheck disable=SC1090
source "$ENV_FILE"

c_bold=$'\033[1m'; c_grn=$'\033[32m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_cyan=$'\033[36m'; c_off=$'\033[0m'

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓ %s%s\n' "$c_grn" "$*" "$c_off"; }
err()  { printf '%s✗ %s%s\n' "$c_red" "$*" "$c_off" >&2; }
note() { printf '%s%s%s\n'  "$c_cyan" "$*" "$c_off"; }

# Pull the full codes blob from the HA Pi (or "{}" if nothing learned yet).
_codes() {
  $SSH "cat $CODES_FILE 2>/dev/null" 2>/dev/null || echo '{}'
}

# Extract the stored code for DEVICE/CMD ("" if absent).
_code_for() {
  local dev="$1" cmd="$2"
  _codes | python3 -c '
import sys, json
try: d = json.load(sys.stdin).get("data", {})
except Exception: d = {}
print(d.get(sys.argv[1], {}).get(sys.argv[2], ""))
' "$dev" "$cmd"
}

cmd_list() {
  note "Learned commands on the Front Hall IR Blaster:"
  _codes | python3 -c '
import sys, json
try: d = json.load(sys.stdin).get("data", {})
except Exception: d = {}
if not d:
    print("  (nothing learned yet)"); raise SystemExit
for dev in sorted(d):
    print(f"  {dev}:")
    for c in sorted(d[dev]):
        print(f"     - {c}")
'
}

# Learn a single button. Returns 0 on confirmed capture.
learn_one() {
  local dev="$1" cmd="$2"
  local before after
  before="$(_code_for "$dev" "$cmd")"

  say ""
  note "── Learning  ${c_bold}${dev} / ${cmd}${c_off}${c_cyan} ──${c_off}"

  # Wake + hold the blaster's WiFi radio awake for the whole learn window,
  # otherwise HA's "enter learn mode" / poll-for-code calls hit a sleeping
  # radio and blow past the 5 s Broadlink timeout.
  ping -i 0.2 -W 2 "$BLASTER_IP" >/dev/null 2>&1 &
  local ping_pid=$!
  trap 'kill "$ping_pid" 2>/dev/null || true' RETURN

  say "Point your physical remote at the ${c_bold}Front Hall IR Blaster${c_off},"
  say "about ${c_bold}2 inches (5 cm)${c_off} away, and get ready to press ${c_bold}${cmd}${c_off}."
  printf '  waking blaster radio'
  for n in 3 2 1; do printf '.'; sleep 1; done; printf '\n'
  printf '\r  %sBlaster is listening — press the button NOW%s          \n' "$c_yel" "$c_off"

  # remote.learn_command blocks until the code is captured or it times out.
  local http
  http="$(curl -s -o /tmp/ir_learn_resp -w '%{http_code}' --max-time 45 \
    -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
    -X POST "$HA_URL/api/services/remote/learn_command" \
    -d "{\"entity_id\":\"$ENTITY\",\"device\":\"$dev\",\"command\":\"$cmd\",\"command_type\":\"ir\"}" )" || true

  if [[ "$http" != "200" ]]; then
    err "HA rejected the request (HTTP $http). Response: $(cat /tmp/ir_learn_resp 2>/dev/null)"
    return 1
  fi

  after="$(_code_for "$dev" "$cmd")"
  if [[ -n "$after" && "$after" != "$before" ]]; then
    ok "Captured ${dev}/${cmd}."
    return 0
  elif [[ -n "$after" && "$after" == "$before" ]]; then
    err "No new code captured (the old one is still there). Try again — hold the remote closer and press once, firmly."
    return 1
  else
    err "Nothing captured (timed out). Re-aim, get within ~2 inches, and press the button right when it says 'listening'."
    return 1
  fi
}

cmd_send() {
  local dev="$1" cmd="$2"
  if [[ -z "$(_code_for "$dev" "$cmd")" ]]; then
    err "'$dev/$cmd' isn't learned yet."; return 1
  fi
  curl -s --max-time 15 -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
    -X POST "$HA_URL/api/services/remote/send_command" \
    -d "{\"entity_id\":\"$ENTITY\",\"device\":\"$dev\",\"command\":\"$cmd\"}" >/dev/null
  ok "Sent ${dev}/${cmd} — did the device react?"
}

cmd_delete() {
  local dev="$1" cmd="$2"
  curl -s --max-time 15 -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
    -X POST "$HA_URL/api/services/remote/delete_command" \
    -d "{\"entity_id\":\"$ENTITY\",\"device\":\"$dev\",\"command\":\"$cmd\"}" >/dev/null
  ok "Deleted ${dev}/${cmd} (if it existed)."
}

cmd_learn() {
  local dev="$1"; shift
  for c in "$@"; do
    until learn_one "$dev" "$c"; do
      read -r -p "  Retry '$c'? [Y/n] " a
      [[ "${a:-y}" =~ ^[Nn] ]] && { say "  skipped $c"; break; }
    done
    read -r -p "  Test '$c' now by firing it back? [y/N] " t
    [[ "${t:-n}" =~ ^[Yy] ]] && cmd_send "$dev" "$c"
  done
  say ""; cmd_list
}

interactive() {
  note "=== Front Hall IR Blaster — guided learning ==="
  say "Tip: keep the remote 2 in / 5 cm from the blaster and press buttons once, firmly."
  read -r -p $'\nWhat device are you teaching it? (e.g. tv, soundbar): ' dev
  dev="$(echo "$dev" | tr '[:upper:]' '[:lower:]' | xargs)"
  [[ -z "$dev" ]] && { err "Need a device name."; exit 1; }
  say "Now enter button names one at a time (e.g. power, vol_up, mute)."
  say "Press Enter on an empty line when you're done."
  while true; do
    read -r -p $'\nButton name (blank = finish): ' cmd
    cmd="$(echo "$cmd" | tr '[:upper:]' '[:lower:]' | xargs)"
    [[ -z "$cmd" ]] && break
    until learn_one "$dev" "$cmd"; do
      read -r -p "  Retry '$cmd'? [Y/n] " a
      [[ "${a:-y}" =~ ^[Nn] ]] && break
    done
    read -r -p "  Fire it back to test? [y/N] " t
    [[ "${t:-n}" =~ ^[Yy] ]] && cmd_send "$dev" "$cmd"
  done
  say ""; cmd_list
  say ""; note "Replay any time with:  ./ir-learn.sh send $dev <button>"
}

case "${1:-}" in
  ""|menu|interactive) interactive ;;
  learn)  shift; [[ $# -ge 2 ]] || { err "usage: ir-learn.sh learn DEVICE CMD..."; exit 1; }; cmd_learn "$@" ;;
  send|test) shift; [[ $# -eq 2 ]] || { err "usage: ir-learn.sh send DEVICE CMD"; exit 1; }; cmd_send "$@" ;;
  list)   cmd_list ;;
  delete) shift; [[ $# -eq 2 ]] || { err "usage: ir-learn.sh delete DEVICE CMD"; exit 1; }; cmd_delete "$@" ;;
  *) err "Unknown command '$1'"; sed -n '2,16p' "$0"; exit 1 ;;
esac
