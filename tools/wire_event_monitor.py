#!/usr/bin/env python3
r"""Generic wire-event listener — say so when a matching command crosses the wire.

A *trigger* in the panel is "run this errand when the game sends that push". This is
the ear for it: it watches the *down* direction for a command whose name contains a
``--match`` substring and, on every match, prints a machine marker line the panel
keys on plus a human line for the log. It presses **nothing** — the panel's
:class:`panel.triggers.TriggerWatcher` reads the marker and puts the trigger's
scenario on the shared timer queue, so the press runs single-file with everything
else the schedule does.

    /mnt/c/Python312/python.exe tools/wire_event_monitor.py --match al.help.new
    /mnt/c/Python312/python.exe tools/wire_event_monitor.py --match al.help.new --match rally
    /mnt/c/Python312/python.exe tools/wire_event_monitor.py --match al.help.new --seconds 600

This is the ear-only, general form of ``tools/alliance_help_monitor.py`` (which is
the ear **and** the hand for the one alliance-help case, with its own coalescing).
Here the hand is the panel's queue, and a burst is coalesced there — a second push
while the errand is still queued is dropped — so this side only throttles the
*marker* it prints (``--cooldown``) to keep the log clean.

**Windows Python only** (``map_capture.check_platform``): WSL2's network namespace is
not the host's, so a capture there sits silent forever. Requirements on that
interpreter: npcap (ships with Wireshark), ``pip install scapy zstandard``.

Passive capture only — active RE is ACE-blocked (see docs/research/socket-duplication.md).
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Absolute, not "tools/lib": the shared modules resolve the same no matter what
# cwd the launcher (panel, shell) started us in.
sys.path.insert(0, os.path.join(_HERE, "lib"))
sys.path.insert(0, _HERE)

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_OK, C_RESET, LiveDecoder, summarise  # noqa: E402
from map_capture import (  # noqa: E402
    add_capture_arguments, check_platform, start_capture,
)

# The marker the panel's reader keys on. A whole line, distinctive, so a stray
# player name or summary can never be mistaken for one. Everything after it on the
# line is the command that matched, for the log; the panel swallows the marker line
# and logs its own sentence.
FIRE = "##TRIGGER##"

# How long to sit quiet after printing a marker before printing another for the
# same run. The panel's queue already coalesces the *presses*; this only stops the
# log filling with markers when a command repeats in a tight burst.
COOLDOWN = 2.0

C_FIRE = "\x1b[1;35m"  # bold magenta


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


class EventMonitor(LiveDecoder):
    """Watch the down stream; announce every command that matches a pattern.

    A plain LiveDecoder — ``map_capture.start_capture`` drives it whatever the
    subclass, since the scapy sniffer calls ``feed_packet`` regardless.
    """

    def __init__(self, patterns, cooldown: float = COOLDOWN):
        super().__init__()
        self.patterns = tuple(patterns)
        self.cooldown = cooldown
        self.matches = 0            # matching commands seen
        self.fired = 0              # markers actually printed (after the cooldown)
        self._last_fire = 0.0

    def emit(self, direction, env):  # LiveDecoder hook — scapy callback thread
        command = proto.envelope_command(env) or ""
        # Down only: the up direction carries our own answers, and firing on those
        # would be a loop waiting to happen.
        if direction != "down" or not any(p in command for p in self.patterns):
            return
        self.matches += 1
        now = time.time()
        if now - self._last_fire < self.cooldown:
            return
        self._last_fire = now
        self.fired += 1
        # Guarded, like the help monitor's ear: a print that raises in the scapy
        # callback (an un-encodable name, a closed pipe) would take the capture
        # socket down with it, and losing the line is far cheaper than that.
        try:
            payload = proto.envelope_payload(env)
            # Two lines: the marker the panel acts on, then the human line for the log.
            print(f"{FIRE}\t{command}", flush=True)
            print(f"{_stamp()} {C_FIRE}<-- {command}{C_RESET}  {summarise(payload)}",
                  flush=True)
        except Exception:            # noqa: BLE001 — never let the log kill the ear
            pass

    def report(self) -> None:
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"{C_OK}{self.matches} match(es) seen, {self.fired} marker(s) printed"
              f"{C_RESET}")
        print(f"{self.packets} packet(s) with payload")
        if not self.matches:
            print(f"{C_DIM}Nothing matched — {' / '.join(self.patterns)} only arrives "
                  f"when the game actually sends it.{C_RESET}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_capture_arguments(ap, include_dump=False)
    ap.add_argument("--match", action="append", metavar="SUBSTR", default=[],
                    help="fire when a down command name contains this (repeatable)")
    ap.add_argument("--cooldown", type=float, default=COOLDOWN, metavar="SEC",
                    help=f"quiet time between two markers (default {COOLDOWN})")
    args = ap.parse_args()
    # After parsing, so `--help` reads from the WSL interpreter rather than being
    # refused by the capture-only platform check.
    check_platform()
    if not args.match:
        ap.error("at least one --match pattern is required")

    # Redirected to a pipe (as the panel does), stdout is block-buffered, so a run
    # watched with `tail -f` shows nothing and reads as hung; and utf-8/replace keeps
    # a player name outside the ANSI code page from raising inside the scapy callback
    # (which does not crash — it silently closes the capture socket).
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    except Exception:
        pass

    monitor = EventMonitor(args.match, cooldown=args.cooldown)
    stop, bpf = start_capture(monitor, args)

    print("Wire-event listener — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    print(f"{C_DIM}watching {' / '.join(args.match)} (down) -> {FIRE}\n"
          f"listening {window}; the game has to send it for anything to happen{C_RESET}\n")

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    deadline = time.time() + args.seconds if args.seconds else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    monitor.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
