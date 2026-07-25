#!/usr/bin/env bash
# Watch results/ for new or updated captures and decode them automatically.
#
# Wireshark writes the file incrementally, so a capture is only parsed once its
# size has stopped changing — otherwise we would decode a half-written file and
# report a truncated stream.
#
# Usage:  tools/watch_captures.sh [interval_seconds]

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WATCH_DIR="$REPO/results"
INTERVAL="${1:-10}"
PARSER="$REPO/tools/lastwar_proto.py"

mkdir -p "$WATCH_DIR"
declare -A SEEN   # path -> "size:mtime" already decoded

stamp() { date '+%H:%M:%S'; }

decode() {
    local pcap="$1" name
    name="$(basename "$pcap")"
    local out="${pcap%.*}.transcript.json"

    echo
    echo "=================================================================="
    echo "[$(stamp)] decoding $name ($(du -h "$pcap" | cut -f1))"
    echo "=================================================================="

    if ! python3 "$PARSER" "$pcap" --json "$out" > /tmp/lw_decode.log 2>&1; then
        echo "  !! parser failed:"
        tail -5 /tmp/lw_decode.log | sed 's/^/     /'
        return 1
    fi

    # Endpoints actually speaking the game protocol.
    grep -E '^\s+GAME' /tmp/lw_decode.log | sed 's/^/  /'
    grep -E '^capture spans' /tmp/lw_decode.log | sed 's/^/  /'

    # Message totals plus the busiest commands in each direction.
    awk '
        /^== client -> server/ { dir="client -> server"; n=0; print "  " $0; next }
        /^== server -> client/ { dir="server -> client"; n=0; print "  " $0; next }
        /^== unknown TLV/      { dir=""; print "  " $0; next }
        dir != "" && /^  [0-9]/ && n < 6 { print "  " $0; n++ }
    ' /tmp/lw_decode.log

    # Things worth surfacing without being asked.
    local chat
    chat=$(grep -cE '"command": "(lw\.user\.push\.chat\.msg|push\.chat|chat\.stat)"' "$out" 2>/dev/null || echo 0)
    # Quote the path — the repo lives under a directory containing a space.
    [ "$chat" -gt 0 ] && echo "  >> $chat chat frame(s) — inspect with: python3 tools/lastwar_proto.py \"$pcap\" --grep chat"
    grep -qE '^\s+[0-9]+\s+init$' /tmp/lw_decode.log && echo "  >> login captured (init frame present)"

    echo "  transcript -> $out   (gitignored: holds device credentials)"
}

echo "watching $WATCH_DIR for *.pcap / *.pcapng every ${INTERVAL}s — Ctrl-C to stop"

while true; do
    shopt -s nullglob
    for pcap in "$WATCH_DIR"/*.pcapng "$WATCH_DIR"/*.pcap; do
        size=$(stat -c %s "$pcap" 2>/dev/null) || continue
        mtime=$(stat -c %Y "$pcap" 2>/dev/null) || continue
        key="$size:$mtime"

        [ "${SEEN[$pcap]:-}" = "$key" ] && continue

        # Wait for the file to settle before decoding.
        sleep 2
        size2=$(stat -c %s "$pcap" 2>/dev/null) || continue
        if [ "$size2" != "$size" ]; then
            echo "[$(stamp)] $(basename "$pcap") still growing (${size} -> ${size2} B), waiting…"
            continue
        fi

        decode "$pcap"
        SEEN[$pcap]="$size2:$(stat -c %Y "$pcap")"
    done
    shopt -u nullglob
    sleep "$INTERVAL"
done
