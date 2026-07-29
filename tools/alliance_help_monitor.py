#!/usr/bin/env python3
r"""Live alliance-help monitor — answer ``push.al.help.new`` the moment it lands.

An alliancemate's help request is worth points only while it is open, and it is
answered by exactly one message (``al.help.all``, see docs/research/alliance-help.md).
So the useful thing is not a periodic sweep but a standing ear on the wire: the push
arrives, and the help goes out in the same second, with nobody watching.

    /mnt/c/Python312/python.exe tools/alliance_help_monitor.py
    /mnt/c/Python312/python.exe tools/alliance_help_monitor.py --seconds 600
    /mnt/c/Python312/python.exe tools/alliance_help_monitor.py --dry-run
    /mnt/c/Python312/python.exe tools/alliance_help_monitor.py --list-ifaces

The panel drives this as a child process behind the «Авто-помощь альянсу» checkbox
(panel/__main__.py), which is why every line it prints is a finished sentence.

Two halves:

* **the ear** — a plain ``LiveDecoder`` (like ``rally_monitor.py``: alliance help rides
  a push stream, not the ``world.get.block`` map traffic, so none of the map-scan
  machinery applies) that watches the *down* direction for ``push.al.help.new``;
* **the hand** — a worker thread that presses "Help All" through the warm Lua daemon
  (``tools/lib/alliance_help.py``, which owns the gate and the retry).

They are separate threads on purpose. ``emit`` runs on the scapy callback: a daemon
round trip there would stall the capture and npcap would start dropping frames, so the
ear only sets an event.

**Bursts are coalesced.** Ten requests arriving together are still one ``al.help.all``
— the message answers the whole list — so the worker waits ``--coalesce`` seconds after
a wake-up and presses once for everything that landed in the window, and never presses
twice inside ``--cooldown`` (5 s) however hard the alliance is asking.

**This must run under the Windows Python, not the WSL one** (``map_capture.check_platform``):
WSL2's network namespace is not the host's, so a capture there would sit silent forever.
Requirements on that interpreter: npcap (ships with Wireshark), ``pip install scapy
zstandard``. The press also needs the game running and, for it to be instant rather than
~5s, the warm daemon (``tools/lua_daemon.py``) — without it every press pays a fresh
``LuaEval`` hijack.

Passive capture only — active RE is ACE-blocked (see docs/research/socket-duplication.md).
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Absolute, not "tools/lib": the shared modules resolve the same no matter what
# cwd the launcher (panel, daemon, shell) started us in.
sys.path.insert(0, os.path.join(_HERE, "lib"))
sys.path.insert(0, _HERE)

import alliance_help  # noqa: E402
import lastwar_proto as proto  # noqa: E402
import lua_client  # noqa: E402
from live_sniffer import C_DIM, C_OK, C_RESET, LiveDecoder, summarise  # noqa: E402
from map_capture import (  # noqa: E402
    add_capture_arguments, check_platform, start_capture,
)

# The request stream. Matched as a substring of the decoded command name, so the
# push.-prefixed form is what actually arrives (`push.al.help.new`).
#
# `al.help.update` is deliberately NOT a trigger by default: it fires when an
# existing request changes (somebody else helped, the counter moved), and the
# request it refers to was already answered by the press the *new* push caused.
# Reacting to it would re-read the gate for nothing several times per request.
# --with-updates turns it on for the one case it helps: joining an alliance
# mid-request, where the `new` push was missed and only updates are left.
TRIGGER_NEW = "al.help.new"
TRIGGER_UPDATE = "al.help.update"

# Burst handling, in two parts. `COALESCE` is how long a wake-up waits for its
# neighbours before the press goes out — one `al.help.all` answers the whole list, so
# ten requests landing together should cost one message, not ten. `COOLDOWN` is the
# floor between two presses: even if pushes keep coming, the client sends at most one
# help-all every five seconds. Requests observed live arrive ~20 s apart, so the floor
# never binds in ordinary play; it exists so a noisy minute cannot turn into a flood of
# up-frames. Both are `--coalesce` / `--cooldown` overridable.
COALESCE = 0.4
COOLDOWN = 5.0

C_HELP = "\x1b[1;32m"  # bold green


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


class AllianceHelpMonitor(LiveDecoder):
    """Watch the help pushes; press "Help All" as soon as one arrives.

    A plain LiveDecoder, not a MapIndex — ``map_capture.start_capture`` drives it all
    the same, since the scapy sniffer calls ``LiveDecoder.feed_packet`` regardless of
    the subclass.
    """

    def __init__(self, dry_run: bool = False, coalesce: float = COALESCE,
                 cooldown: float = COOLDOWN, with_updates: bool = False):
        super().__init__()
        self.dry_run = dry_run
        self.coalesce = coalesce
        self.cooldown = cooldown
        self.triggers = (TRIGGER_NEW, TRIGGER_UPDATE) if with_updates else (TRIGGER_NEW,)
        self.pushes = 0          # help pushes seen on the wire
        self.presses = 0         # al.help.all messages we sent
        self.helped = 0          # requests those presses answered
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._eval = None        # created on first use, then kept warm
        self._worker = threading.Thread(target=self._run_worker, daemon=True)

    # -- the ear ------------------------------------------------------------
    def emit(self, direction, env):  # LiveDecoder hook — scapy callback thread
        command = proto.envelope_command(env) or ""
        # Down only: the up direction carries our own `al.help.all`, and helping
        # in response to our own help is a loop waiting to happen.
        if direction != "down" or not any(t in command for t in self.triggers):
            return
        self.pushes += 1
        self._wake.set()         # hand the work to the worker; never block here
        # Logging comes after the wake and is guarded: a print that raises in the scapy
        # callback (an un-encodable name, a closed pipe) would take the capture socket
        # down with it, and losing the log line is a great deal cheaper than that.
        try:
            payload = proto.envelope_payload(env)
            print(f"{_stamp()} {C_HELP}<-- {command}{C_RESET}  {summarise(payload)}",
                  flush=True)
        except Exception:        # noqa: BLE001 — never let the log kill the ear
            pass

    # -- the hand -----------------------------------------------------------
    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()         # let the worker notice the stop at once

    def _run(self, chunk, marker=None, settle: float = 1.0):
        """Evaluator call, with the evaluator created lazily on the first press.

        Lazily, because a monitor that starts before the game (the panel launches both)
        must not fail at start-up — and because with no request ever arriving it never
        needs the game at all.
        """
        if self._eval is None:
            self._eval = lua_client.get_evaluator()
        return self._eval.run(chunk, marker, settle)

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            if not self._wake.wait(0.5):
                continue
            if self._stop.is_set():
                return
            time.sleep(self.coalesce)   # let a burst collect into one press
            # Cleared AFTER the window: anything that arrived inside it is
            # answered by the press we are about to make (one al.help.all covers
            # the whole list), while anything arriving during the press itself
            # re-sets the event and gets its own round.
            self._wake.clear()
            self.help_now()
            time.sleep(self.cooldown)

    def help_now(self) -> int:
        """One "Help All" press, gated. Returns the number of requests answered."""
        if self.dry_run:
            print(f"{_stamp()} {C_DIM}dry-run: would press Help All{C_RESET}", flush=True)
            return 0
        try:
            answered = alliance_help.answer_pending(
                self._run, log=lambda m: print(f"{_stamp()} {m}", flush=True))
        except Exception as exc:        # noqa: BLE001 — one bad press must not end the watch
            print(f"{_stamp()} help failed: {type(exc).__name__}: {exc}", flush=True)
            self._eval = None           # a dead daemon client is re-made next time
            return 0
        if answered:
            self.presses += 1
            self.helped += answered
        return answered

    def report(self) -> None:
        print(f"\n{C_DIM}{'-' * 64}{C_RESET}")
        print(f"{C_OK}{self.pushes} help push(es) seen, {self.presses} press(es) sent, "
              f"{self.helped} request(s) answered{C_RESET}")
        print(f"{self.packets} packet(s) with payload")
        if not self.pushes:
            print(f"{C_DIM}No help push decoded — push.al.help.new only arrives when an "
                  f"alliancemate actually asks for help while capturing.{C_RESET}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # The shared transport flags (--iface, --list-ifaces, --seconds, --port,
    # --all-tcp). --dump is a MapIndex-only transcript feature, so it is not
    # offered here — this decoder's emit() would write nothing to it.
    add_capture_arguments(ap, include_dump=False)
    ap.add_argument("--dry-run", action="store_true",
                    help="log the pushes, never send al.help.all")
    ap.add_argument("--no-sweep", action="store_true",
                    help="do not help the requests that are already pending at start-up")
    ap.add_argument("--with-updates", action="store_true",
                    help="also react to push.al.help.update (for requests whose "
                         "'new' push was missed, e.g. joining mid-request)")
    ap.add_argument("--coalesce", type=float, default=COALESCE, metavar="SEC",
                    help=f"collect a burst of pushes for this long, then press once "
                         f"(default {COALESCE})")
    ap.add_argument("--cooldown", type=float, default=COOLDOWN, metavar="SEC",
                    help=f"minimum quiet time between two presses (default {COOLDOWN})")
    args = ap.parse_args()
    # After parsing, so `--help` is readable from the WSL interpreter rather than
    # refused by the capture-only platform check.
    check_platform()

    # Redirected to a file (or a pipe, as the panel does), stdout is block-buffered,
    # so a run watched with `tail -f` shows nothing for minutes and reads as hung.
    #
    # utf-8/replace is not cosmetic: piped stdout falls back to the ANSI code page, and
    # a player name outside it (a `ů` did this) raises UnicodeEncodeError *inside the
    # scapy callback* — which does not crash the process, it closes the capture socket
    # and leaves a monitor that looks alive and hears nothing ever again.
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    except Exception:
        pass

    monitor = AllianceHelpMonitor(dry_run=args.dry_run, coalesce=args.coalesce,
                                  cooldown=args.cooldown, with_updates=args.with_updates)
    stop, bpf = start_capture(monitor, args)
    monitor.start()

    print("Alliance auto-help — scapy/npcap, no dumpcap")
    print(f"filter: '{bpf}'   interface: {args.iface or 'default'}")
    window = f"{args.seconds}s" if args.seconds else "until Ctrl+C"
    warm = "warm daemon" if lua_client.is_running() else "NO daemon (each press pays a fresh LuaEval)"
    print(f"{C_DIM}watching push.{TRIGGER_NEW} -> al.help.all — {warm}\n"
          f"listening {window}; an alliancemate has to ask for anything to happen{C_RESET}\n")

    # The requests already waiting when the ear opens have no push coming — their
    # push was sent before we started. Answer them once, then go quiet.
    if not args.no_sweep:
        monitor.help_now()

    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    # None means run until interrupted, so the deadline test tolerates not having one.
    deadline = time.time() + args.seconds if args.seconds else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        monitor.stop()

    monitor.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
