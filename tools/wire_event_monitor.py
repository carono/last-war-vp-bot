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

# The SECOND machine line, and the reason it exists (#1323). A marker says «that
# command arrived»; some abilities need a handful of the push's own fields as well,
# and there is exactly one such case: which monster a rally banner is going for.
# `targetContentId` rides on `push.alliance.march.*` and on nothing the client keeps
# (docs/research/rally-join.md), so a profile that hears the push and not its payload
# cannot name a single banner — and the per-kind daily budgets, which are keyed on
# exactly that name, all collapse into one bucket without a word being said.
#
# So a `--fields` pattern makes the child print this line beside the marker, carrying
# ONLY the fields named in `_FIELD_BUILDERS` below. It is swallowed by the panel's
# reader exactly as the marker is, and it is NAME-FREE by construction: numbers and
# ids of things, never a person — which is the rule #1293 set for this child's output.
FIELDS = "##FIELDS##"

# How long to sit quiet after printing a marker before printing another for the
# same run. The panel's queue already coalesces the *presses*; this only stops the
# log filling with markers when a command repeats in a tight burst.
COOLDOWN = 2.0

C_FIRE = "\x1b[1;35m"  # bold magenta


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def _march_fields(payload) -> str:
    """`team=… content=… slots=…/… join=…/…` off an alliance-march push, or `""`.

    THE SAME FOUR WORDS `tools/rally_monitor.py` PRINTS, and read out of the payload by
    that tool's own helpers rather than by a second copy of them: which banner
    (`teamUuid`, and on a `create` it is only on the envelope), what it is going for
    (`targetContentId` — the whole point of this line), how many seats it has and where
    a joiner is sent. Everything the join needs from the wire and not one field more.

    NOT A PLAYER IN SIGHT, on purpose: the push carries `ownerName`, `ownerUid` and an
    alliance id, and none of them is here. A line that can only ever hold numbers of
    THINGS is what makes this safe to print from a child whose output a parent logs
    (#1293).

    Empty for a push that is not about a banner, and never raises: this runs in the
    scapy callback, where an exception closes the capture socket.
    """
    try:
        import rally_monitor                       # tools/ is on the path already
    except Exception:                              # noqa: BLE001 — no fields, not a crash
        return ""
    if not isinstance(payload, dict):
        return ""
    out = []
    try:
        team = rally_monitor._banner_uuid(payload)
        if not team:
            return ""                              # a solo march is not a banner
        out.append(f"team={team}")
        content = payload.get("targetContentId") or payload.get("targetUid")
        if content:
            out.append(f"content={content}")
        cap = payload.get("assemblyMarchMax")
        if cap:
            out.append(f"slots={len(list(rally_monitor._iter_marches(payload)))}/{cap}")
        aim = rally_monitor._join_point(payload)
        if aim:
            out.append(f"join={aim[0]}/{aim[1]}")
    except Exception:                              # noqa: BLE001 — a field, never the ear
        return ""
    return " ".join(out)


#: Which commands get a fields line, and what builds it. One entry, and the shape is
#: the point: a new one is a named command family plus a function that may only ever
#: return numbers of THINGS.
_FIELD_BUILDERS = (("alliance.march", _march_fields),)


def _fields_for(command: str, payload) -> str:
    """The fields line for one command, or `""` when nothing knows how to build it.

    A command the parent asked for but nobody can describe yields nothing rather than
    a guess — `summarise()` would answer, and what it answers with is the payload,
    player names and all (#1293).
    """
    for family, build in _FIELD_BUILDERS:
        if family in command:
            return build(payload)
    return ""


class EventMonitor(LiveDecoder):
    """Watch the down stream; announce every command that matches a pattern.

    A plain LiveDecoder — ``map_capture.start_capture`` drives it whatever the
    subclass, since the scapy sniffer calls ``feed_packet`` regardless.
    """

    def __init__(self, patterns, cooldown: float = COOLDOWN, quiet: bool = False,
                 fields=()):
        super().__init__()
        self.patterns = tuple(patterns)
        # The commands whose payload fields the parent asked for (`--fields`). A
        # subset of what is already being matched: this decodes nothing extra and
        # opens no second capture — it reads the payload of a frame the ear had in
        # its hands anyway (#1323).
        self.fields = tuple(f for f in (fields or ()) if f)
        self.field_lines = 0        # how many fields lines went out (the report says)
        self.cooldown = cooldown
        # `quiet`: print the marker and NOT the human line. The summary beside a
        # command is the push's own payload — `uid`, `senderName`, `allianceId` — and
        # a parent that logs this child's lines writes all of it into a file people
        # send each other when something goes wrong (#1293). The panel runs quiet and
        # says what it heard in its own words, by counts.
        self.quiet = quiet
        self.matches = 0            # matching commands seen
        self.fired = 0              # markers actually printed (after the cooldown)
        # PER COMMAND, not one clock for the whole ear. With a single `--match` the two
        # are the same thing; with several — which is how the panel's hub runs this now,
        # one capture carrying every subscribed pattern — a shared clock would let a
        # chatty command swallow the marker of a quiet one that arrived inside its two
        # seconds, and the trigger waiting on that quiet one would simply never fire.
        self._last_fire: dict = {}

    def emit(self, direction, env):  # LiveDecoder hook — scapy callback thread
        command = proto.envelope_command(env) or ""
        # Down only: the up direction carries our own answers, and firing on those
        # would be a loop waiting to happen.
        if direction != "down" or not any(p in command for p in self.patterns):
            return
        self.matches += 1
        # THE FIELDS LINE IS NOT COOLED DOWN, and that is deliberate (#1323). The
        # cooldown exists so a burst of one command cannot fill a log with markers —
        # a press is coalesced by the panel's queue anyway. This line is not a press
        # and never reaches a log: it is one banner's own numbers, and during an event
        # ten banners announce themselves inside one throttle window. Cooling it would
        # leave nine of them unnamed, which is the very state this exists to end.
        if self.fields and any(p in command for p in self.fields):
            try:
                built = _fields_for(command, proto.envelope_payload(env))
                if built:
                    print(f"{FIELDS}\t{command}\t{built}", flush=True)
                    self.field_lines += 1
            except Exception:        # noqa: BLE001 — never let a field kill the ear
                pass
        now = time.time()
        if now - self._last_fire.get(command, 0.0) < self.cooldown:
            return
        self._last_fire[command] = now
        self.fired += 1
        # Guarded, like the help monitor's ear: a print that raises in the scapy
        # callback (an un-encodable name, a closed pipe) would take the capture
        # socket down with it, and losing the line is far cheaper than that.
        try:
            # Two lines: the marker the panel acts on, then the human line for the log
            # — the second one only when somebody is reading this in a terminal.
            print(f"{FIRE}\t{command}", flush=True)
            if not self.quiet:
                payload = proto.envelope_payload(env)
                print(f"{_stamp()} {C_FIRE}<-- {command}{C_RESET}  {summarise(payload)}",
                      flush=True)
        except Exception:            # noqa: BLE001 — never let the log kill the ear
            pass

    def report(self) -> None:
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        if self.fields:
            print(f"{self.field_lines} fields line(s) printed "
                  f"for {' / '.join(self.fields)}")
        print(f"{C_OK}{self.matches} match(es) seen, {self.fired} marker(s) printed"
              f"{C_RESET}")
        print(f"{self.packets} packet(s) with payload")
        # What `--client-pid` actually cost, in packets. Printed whenever the ear was
        # pinned — including as zero — because «0 dropped» is the reading that says the
        # separation is not quietly eating this account's own traffic, and there is no
        # way to tell that from a silent run otherwise.
        if self.own_ports is not None:
            print(f"{self.foreign} packet(s) dropped as another client's")
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
    ap.add_argument("--fields", action="append", metavar="SUBSTR", default=[],
                    help="also print a machine-only fields line for a matched command "
                         "whose name contains this (repeatable). Only the fields the "
                         "panel needs, never a player: see FIELDS above")
    ap.add_argument("--quiet", action="store_true",
                    help="print the markers only — no human line per match. That line "
                         "carries the push's payload (uid, sender name, alliance id), "
                         "so a parent logging this child's output would write player "
                         "identifiers into its log; the panel runs with this on")
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

    monitor = EventMonitor(args.match, cooldown=args.cooldown, quiet=args.quiet,
                           fields=args.fields)
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
