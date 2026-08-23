#!/bin/bash
# A DRAFT, kept for a rewrite — not a supported tool. See golden_energy_burner.md.
#
# Waits on a profile's log until a golden-zombie hunt has sent N marches or has ended,
# then prints what it counted. It exists because the press comes back before the run
# does, so a driver outside the panel has nothing else to wait on.
#
# That is the whole reason it is a draft: a scenario knows when its own run ended and a
# timer knows when it may start the next one, so waiting on a LOG FILE is a symptom of
# driving the panel from outside rather than a thing worth keeping.
#
#   tools/dev/golden_hunt_watch.sh <profile> <line-offset-of-the-start> <marches-wanted>
set -u

REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || exit 1
cd "$REPO" || exit 1

PROFILE=${1:-}; SKIP=${2:-0}; WANT=${3:-1}
[ -n "$PROFILE" ] || { echo "usage: $0 <profile> <line-offset> <marches-wanted>" >&2; exit 2; }
LOG="profiles/$PROFILE/panel.log"

while true; do
  sent=$(tail -n +$((SKIP + 1)) "$LOG" | grep -acE "the order is away|READ_LUA launched = 1")
  ended=$(tail -n +$((SKIP + 1)) "$LOG" | grep -acE "< action: attack_golden_zombies[0-9_a-z]* (OK|FAILED|HALTED|INTERRUPTED)")
  if [ "$sent" -ge "$WANT" ] || [ "$ended" -gt 0 ]; then
    echo "sends=$sent ended=$ended"; exit 0
  fi
  sleep 10
done
