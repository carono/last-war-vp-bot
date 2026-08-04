"""The passive capture: the wire feed the starred-tile list is built from.

A secret task only crosses the wire while the map moves, so the tiles cannot be read
out of the game on demand — a pcap child (`tools/secret_task_capture.py`) watches the
stream and writes what it sees to the profile's checkpoint every tick. This class is
the panel's half of that: start and stop the child, decide which of its lines reach the
log, keep the profile's own findings log, and nudge the list when the checkpoint moves.

It was `Panel._start_monitor` / `_task_passes` / `_on_secret_line` / `_append_secret`.
It lives beside the list it feeds now, and reads the tab's own filter boxes rather than
variables planted on the app.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

# The runtime FIRST: importing `panel.runtime` is what puts the repo's tools/lib on
# sys.path, and `coords` is one of the bare-name modules that live there. A module here
# can be imported without the panel ever having run (the tests do exactly that), so the
# order is load-bearing rather than stylistic — see panel/runtime/paths.py.
from ...runtime import captures as capturemod
from ...runtime.paths import TOOLS

import coords                                        # noqa: E402  (see above)

#: How long the tab waits after a finding before re-merging the checkpoint. One capture
#: tick prints a burst of findings and a single merge covers them all.
NUDGE_MS = 800


class Capture:
    """The capture child, its line filter and the findings log."""

    def __init__(self, rt, tab) -> None:
        self.rt = rt
        self.tab = tab
        self._proc = None
        #: A launch is in flight on its own thread — see :meth:`start`. Without it, two
        #: presses in the second the game takes to answer are two captures.
        self._starting = False

    @property
    def running(self) -> bool:
        return self._proc is not None or self._starting

    # -- start / stop --------------------------------------------------------
    def toggle(self) -> None:
        if self.tab.monitor_var.get():
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        """Build the command from the tab, then go and start the child. Tk thread.

        SPLIT IN TWO ON PURPOSE (#1226). Everything the TAB knows is read here, where the
        widgets are; everything that touches the GAME or spawns a process happens on a
        thread, because both of them block for hundreds of milliseconds and this method
        is called while a page is being built — once per open profile. The daemon check
        alone was a third of a second of window that had not redrawn, and the server seed
        behind it is a round trip into the game VM.
        """
        if self._proc is not None:
            return
        idx = self.tab.kind_index()
        script = capturemod.CAPTURE_OPTIONS[idx]["script"]
        # NO --all-tcp. It sets the BPF to a bare "tcp", so on a busy adapter (this box
        # sees ~280 tcp frames/s) scapy's Python callback cannot keep up and npcap's ring
        # overflows — ~98% of packets, the game's map frames among them, are dropped
        # before decode. That is exactly why the capture works when run by hand
        # (auto-detect → "tcp port 17935", filtered in the kernel, no flood) but found
        # nothing when the panel forced --all-tcp. Let it auto-detect the live port;
        # --all-tcp stays a manual last resort for when detection genuinely fails.
        cmd = [self.rt.children.python(), "-u", os.path.join(TOOLS, script)]
        # Checkpoint what the capture currently sees into the profile, so auto-loot has a
        # machine-readable view of the map instead of the log lines this panel prints for
        # the human. Rewritten every tick; the reader drops anything not re-seen in the
        # scan window, so a stale file cannot send a robbery at a tile already taken.
        # Only for the secret-task capture: the ghost-recon one writes its own record
        # shape, and auto-loot must never be handed that by mistake.
        if script == capturemod.SECRET_TASK_CAPTURE:
            cmd += ["--json", self.rt.profiles.tasks_json()]
        # Capture tick interval from the tab (falls back to the child's own default if
        # the field is blank or non-numeric).
        interval = self.tab.interval_var.get().strip()
        if interval.isdigit() and int(interval) > 0:
            cmd += ["--interval", interval]
        # …and the rest — the game and the spawn — off the Tk thread. `_starting` is what
        # stops a second press (or a second `ensure_loaded`) launching a second capture
        # in the gap before `_proc` is set.
        if self._starting:
            return
        self._starting = True
        threading.Thread(target=self._launch, args=(cmd, script),
                         name="panel-capture-start", daemon=True).start()

    def _launch(self, cmd: list, script: str) -> None:
        """Seed the server, spawn the child, say what happened. Worker thread."""
        try:
            # Seed the on-screen server from the running game through the warm daemon, so
            # the capture prints "server N" from its first line instead of sitting on
            # "server unknown yet" until the map is scrolled (a passive capture only
            # learns the server from a map response, which arrives only while the map
            # moves). VPN-independent; the capture's own weight-of-traffic election still
            # overrides this the moment real map data disagrees.
            if self.rt.game.up():
                srv = self.rt.game.current_server()
                if srv and str(srv).isdigit():
                    cmd += ["--seed-server", str(srv)]
                    self.tab.say("secret", "log.secret.seed_server", srv=srv)
            self.tab.say("secret", "log.secret.starting", script=script)
            mon = self.rt.children.spawn("secret", cmd, on_line=self.on_line,
                                         on_exit=self._on_exit)
            if not mon.start():
                self.tab.post(lambda: self.tab.monitor_var.set(False))
                return
            self._proc = mon
            # Confirm the child really started (so a silent monitor is never mistaken for
            # a crash). A passive pcap only yields tiles while the map is scrolling — so
            # say so, unless «Автообъезд карты» is already doing the scrolling.
            self.tab.say("secret",
                         "log.secret.started" if self.tab.sweep.running
                         else "log.secret.started_move_map", pid=mon.pid)
        except Exception as exc:          # noqa: BLE001 — a capture, never the window
            self.tab.say("secret", "log.secret.ended")
            self.rt.dbg("secret").error("capture start failed: %s", exc, exc_info=True)
            self.tab.post(lambda: self.tab.monitor_var.set(False))
        finally:
            self._starting = False

    def stop(self) -> None:
        mon, self._proc = self._proc, None
        if mon is not None:
            self.tab.say("secret", "log.secret.stopped")
            mon.stop()

    def restart(self) -> None:
        """Bounce it so a changed --interval / server seed applies."""
        self.stop()
        self.start()

    def _on_exit(self) -> None:
        self.tab.say("secret", "log.secret.ended")
        self._proc = None
        self.tab.monitor_var.set(False)

    # -- the lines -----------------------------------------------------------
    def passes(self, line: str) -> bool:
        """Panel-side filters for a finding line. Non-task lines always pass.

        A finding looks like `[*] lvl N  #server X:x Y:y ... [PENDING]`. Filters are read
        live from the boxes, so toggling one affects subsequent lines immediately. A line
        counts as a finding when it has both a `lvl N` and a parseable coordinate.
        """
        m = re.search(r"\blvl\s+(\d+)\b", line)
        if not m or not coords.parse(line):
            return True                 # header / progress / summary line — never filtered
        lvl = int(m.group(1))
        # The DISPLAY filter's own entries — not the auto-loot rule's. The two used to
        # share one pair, and a person narrowing the log silently re-aimed the robberies.
        lo = self.tab.filter_from_var.get().strip()
        hi = self.tab.filter_to_var.get().strip()
        if lo.isdigit() and lvl < int(lo):
            return False
        if hi.isdigit() and lvl > int(hi):
            return False
        if self.tab.star_var.get() and not re.match(r"\s*\*", line):
            return False
        # PENDING and LOOTABLE are two values of one dimension — raid readiness — and the
        # capture tags a line with exactly one of them (a tile walks PENDING -> LOOTABLE,
        # never both at once). So enabling both boxes reads as "either", matching
        # `filter_tasks` in lastwar_proto: ANDing the two substrings could never match and
        # the panel simply went blank.
        want_pending, want_loot = self.tab.pending_var.get(), self.tab.can_loot_var.get()
        if want_pending or want_loot:
            tags = ("PENDING",) if want_pending and not want_loot else \
                   ("LOOTABLE",) if want_loot and not want_pending else \
                   ("PENDING", "LOOTABLE")
            if not any(t in line for t in tags):
                return False
        return True

    def on_line(self, line: str) -> bool:
        """One capture line: log it if the display filter lets it through, record a real
        finding into the profile's own log, and nudge the list to re-merge the
        freshly-written checkpoint — the wire feed it is built from.

        The nudge is independent of the log's display filter: a tile the operator hid
        from the log is still on the map and still belongs on the tab. So it runs on
        every finding line, and on the periodic "star(s) still on timer" progress line
        (no coordinate of its own, but it marks a checkpoint flush). Called on the child's
        reader thread, so it marshals onto the Tk thread, where the merge is debounced.
        """
        is_finding = bool(coords.parse(line))
        if is_finding or "on timer" in line:
            self.tab.after(self._nudge)
        if not self.passes(line):
            return False                # filtered out — handled, do not log
        if is_finding:                  # a coordinate present -> an actual finding
            self.append(line)
        return True

    def _nudge(self) -> None:
        """Re-merge the checkpoint into the list, debounced (Tk thread).

        Armed by name, so a burst of findings is one merge — and a no-op unless the tab
        has been opened, since an unopened one reads fresh when first shown anyway.
        """
        if not self.tab.loaded:
            return
        self.rt.tick.arm("secret_nudge", NUDGE_MS, self.tab.refresh)

    def append(self, line: str) -> None:
        """Append a finding to the active profile's log (best-effort)."""
        try:
            with open(self.rt.profiles.secret_log(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "line": line},
                                    ensure_ascii=False) + "\n")
        except OSError:
            pass
