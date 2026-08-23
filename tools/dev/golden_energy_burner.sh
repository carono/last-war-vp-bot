#!/bin/bash
# A DRAFT, kept for a rewrite — not a supported tool. See golden_energy_burner.md.
#
# What it does: burns an account's stamina on golden zombies by pressing the panel's web
# API in a loop — start `attack_golden_zombies_pair`, watch the profile's log for
# marches that actually went out, cut a run that has stopped producing them, re-walk the
# map every so often, and restart the client when the game link drops.
#
# What is WRONG with it, and must change before any of this is used again: it is an
# EXTERNAL loop. It holds the gates of an ability (is a march going out, has the run
# stalled, is it time to re-scan) outside every scenario, it reads a log file to decide
# what the game did, and it calls /api/interrupt — so it cuts runs that belong to
# somebody else. The project's rule is that an ability is ONE scenario and a repeat is a
# TIMER; this file is neither. Keep it only as a description of the behaviour wanted.
#
#   LW_PANEL_URL=http://<host>:<port> LW_PANEL_TOKEN=<token> \
#       tools/dev/golden_energy_burner.sh <profile> [--supervise]
#
# Nothing here has a default that names a machine or an account: the panel's address,
# its token and the profile are all asked for, and an unset one stops the script.
set -u

REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || exit 1
cd "$REPO" || exit 1

PANEL=${LW_PANEL_URL:-}
TOKEN=${LW_PANEL_TOKEN:-}
PROFILE=${1:-}
[ -n "$PANEL" ]   || { echo "set LW_PANEL_URL to the panel's web address" >&2; exit 2; }
[ -n "$TOKEN" ]   || { echo "set LW_PANEL_TOKEN to the panel's web token" >&2; exit 2; }
[ -n "$PROFILE" ] || { echo "usage: $0 <profile> [--supervise]" >&2; exit 2; }

# The supervisor the original had as a second script: it kept the loop alive across a
# kill, which is exactly why nobody could find where the runs were coming from. Kept
# behind a flag, off by default, so it can never be the surprising part again.
if [ "${2:-}" = "--supervise" ]; then
  while true; do
    pgrep -f "$0 $PROFILE\$" >/dev/null || "$0" "$PROFILE" &
    sleep 120
  done
fi

LOG="profiles/$PROFILE/panel.log"
SQUAD_A=${LW_GOLDEN_SQUAD_A:-2}
SQUAD_B=${LW_GOLDEN_SQUAD_B:-3}
RESCAN_LAPS=${LW_GOLDEN_RESCAN_LAPS:-0}     # 0 = never re-walk the map

say()   { echo "$(date +%H:%M:%S) $*"; }
post()  { curl -s -m 40 -X POST "$PANEL/$1?token=$TOKEN" \
            -H 'Content-Type: application/json' -d "$2"; }
# The marches the log says really left — the count the original trusted instead of the
# press, because a press that came back "ok" still sends nothing when a squad is busy.
attacks() { grep -c "READ_LUA launched = 1" "$LOG"; }

bad=0; stall=0; lap=0; last=$(attacks)
while true; do
  lap=$((lap + 1))
  link=$(curl -s -m 10 "$PANEL/api/state?token=$TOKEN&profile=$PROFILE" | python3 -c "import json,sys
try: print(json.load(sys.stdin)['game']['link'])
except Exception: print('unknown')")
  now=$(attacks)

  if [ "$link" != "online" ]; then
    bad=$((bad + 1)); stall=0
    say "link=$link bad=$bad attacks=$now"
    if [ "$bad" -ge 3 ]; then
      say "restarting the client"
      post api/interrupt "{\"profile\":\"$PROFILE\"}" >/dev/null; sleep 3
      post api/game "{\"profile\":\"$PROFILE\",\"action\":\"restart\"}" >/dev/null
      bad=0; sleep 150
    fi
    sleep 60; continue
  fi

  bad=0
  if [ "$now" -gt "$last" ]; then stall=0; last=$now; else stall=$((stall + 1)); fi

  # A run that has produced no march for twelve laps is standing in front of something.
  if [ "$stall" -ge 12 ]; then
    say "stalled at $now attacks — cutting the run"
    post api/interrupt "{\"profile\":\"$PROFILE\"}" >/dev/null; sleep 5; stall=0
  fi

  # The near ground gets farmed out, and the refresh ring only covers what is already
  # loaded — so «the nearest» drifts to ninety tiles and every kill costs four minutes.
  if [ "$RESCAN_LAPS" -gt 0 ] && [ $((lap % RESCAN_LAPS)) -eq 0 ]; then
    say "re-walking the map"
    post api/interrupt "{\"profile\":\"$PROFILE\"}" >/dev/null; sleep 4
    post api/actions/run "{\"profile\":\"$PROFILE\",\"name\":\"scan_map\"}" >/dev/null
    sleep 25
  fi

  # NO BUYING, deliberately: the bag's stamina items are not this script's to spend.
  say "online attacks=$now stall=$stall $(post api/actions/run \
      "{\"profile\":\"$PROFILE\",\"name\":\"attack_golden_zombies_pair\",\
        \"args\":{\"squad_a\":$SQUAD_A,\"squad_b\":$SQUAD_B}}")"
  sleep 60
done
