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
from ...runtime import game_process
from ...runtime.paths import TOOLS

import coords                                        # noqa: E402  (see above)

#: How long the tab waits after a finding before re-merging the checkpoint. One capture
#: tick prints a burst of findings and a single merge covers them all.
NUDGE_MS = 800

#: The machine line the capture prints per tile — the EVENT the list is built from
#: (#1416). It MUST match `TILE_MARKER` in `tools/secret_task_capture.py`.
#:
#: WHAT IT REPLACES, and why the operator asked for it: «увидели секретку — записали в
#: базу, это должен быть небольшой хук и не должен тратить ресурсы». A find used to reach
#: the list the long way round — the child rewrote its whole checkpoint, the panel saw a
#: human line, waited out a debounce, then re-read the entire file AND asked the game VM
#: about the star. Per find. The tile is in the line now, so the hook is: parse, hand
#: over, return.
TILE_MARKER = "##TILE##"

#: The `family NNNN` token the capture prints on every finding, and the leading ` *` it
#: marks a starred one with. The family is what the rule is actually made of; the star
#: glyph is the fallback for a line shape that ever stops carrying it.
_FAMILY = re.compile(r"\bfamily\s+(\d+)\b")


def _starred(line: str, level: int) -> bool:
    """Whether a finding line is a STARRED tile — the same rule the list itself uses.

    Read off the line rather than guessed: the capture prints the tile's `cfgId` family,
    and `lastwar_proto.starred_by_digits` owns the rule — the family, with the level-99
    class taken out, because that is not a level but the one-per-player task sharing the
    encoding.

    IT IS THE FALLBACK RULE, AND HERE THAT IS THE ONLY ONE THERE IS (#1267). The star a
    live client answers with is the `is_special` column of its config row, and a capture
    has no client: it decodes a pcap in a child process of its own. So a tile whose
    digits lie — `60009903`, which the game calls level 7 and the digits call 99 — is
    filtered out of the findings log even though the tab's own list keeps it. Nothing
    here can fix that; what the tab shows comes from its VM feed, which does ask.
    """
    import lastwar_proto as proto

    found = _FAMILY.search(line)
    if found is not None:
        return proto.starred_by_digits(found.group(1), level)
    # No family token: fall back to the glyph the capture itself printed, which it took
    # from `SecretTask.starred` — the same rule, already applied, `99` already excluded.
    # Re-testing the level here was a third copy of it (#1267).
    return line.lstrip().startswith("*")


class Capture:
    """ONE capture child — its line filter, its findings log and its own switch.

    One per sniffer since #1251, not one with a dropdown. The two capture different
    things (a secret task is a hero dispatch on a player's tile; a ghost squad is the
    weekly event's) into different checkpoints, and the person watching one of them
    almost never wants the other switched off in the same breath. So each page carries
    the switch for the sniffer that feeds IT, each remembers its own interval, and
    either may run while the other does not.
    """

    def __init__(self, rt, tab, index: int = 0, switch=None, interval=None) -> None:
        self.rt = rt
        self.tab = tab
        #: Which of `captures.CAPTURE_OPTIONS` this one runs — its script, and the
        #: shape of the records it writes.
        self.index = index
        #: The tk variables this capture reads: its own checkbox and its own interval,
        #: owned by the page that draws them.
        self.switch = switch
        self.interval = interval
        self._proc = None
        #: A launch is in flight on its own thread — see :meth:`start`. Without it, two
        #: presses in the second the game takes to answer are two captures.
        self._starting = False

    @property
    def running(self) -> bool:
        return self._proc is not None or self._starting

    @property
    def wanted(self) -> bool:
        """Whether this profile asked for THIS capture."""
        return bool(self.switch.get()) if self.switch is not None else False

    # -- start / stop --------------------------------------------------------
    def toggle(self) -> None:
        if self.wanted:
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
        script = capturemod.CAPTURE_OPTIONS[self.index]["script"]
        cmd = self.command(script)
        # …and the rest — the game and the spawn — off the Tk thread. `_starting` is what
        # stops a second press (or a second `ensure_loaded`) launching a second capture
        # in the gap before `_proc` is set.
        if self._starting:
            return
        self._starting = True
        threading.Thread(target=self._launch, args=(cmd, script),
                         name="panel-capture-start", daemon=True).start()

    def command(self, script: str) -> list:
        """The child's command line — everything the TAB knows, and nothing that blocks.

        Its own method so it can be read back without spawning anything: which paths a
        capture is given decides what reaches the tab, and «this one was never given the
        share file» is exactly the kind of omission a test should catch (#1280).
        """
        # NO --all-tcp. It sets the BPF to a bare "tcp", so on a busy adapter (this box
        # sees ~280 tcp frames/s) scapy's Python callback cannot keep up and npcap's ring
        # overflows — ~98% of packets, the game's map frames among them, are dropped
        # before decode. That is exactly why the capture works when run by hand
        # (auto-detect → one narrow "tcp port N" per live conversation, filtered in the
        # kernel, no flood) but found nothing when the panel forced --all-tcp. The number
        # is deliberately not written here: it moves between builds, and this comment
        # named the one that has since become the chat channel. Let it auto-detect;
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
            # …AND THE SHARES, which this one was not being asked for (#1280). The mark
            # «уже поделились» is written by whichever child decodes the broadcast, and
            # only the GHOST capture was given a path to write it to — so a profile
            # running the ★ sniffer alone saw its own shares and never a mate's, while
            # `shared.py` said both children fed it. The two captures decode the same
            # stream; both record it now, into the same file, and appending twice is
            # what `share_marks` already deduplicates.
            cmd += ["--shared-json", self.rt.profiles.secret_shared_json()]
            # …AND THE REST OF THE MAP, in this same child (#1289). Mines come off the
            # very map responses this capture is already decoding, and trucks and
            # alliance trains off the march stream it already hears; the only thing a
            # separate capture would add is a second npcap reader on one interface,
            # which starves both (044c19f). So the second listener is a flag, not a
            # process — `tools/lib/world_index.py`.
            cmd += ["--world-json", self.rt.profiles.world_json()]
        else:
            # THE GHOST CAPTURE NEEDS A CHECKPOINT TOO (#1251). It was launched without
            # one — «--json only for the secret-task capture» — so everything it found
            # went to the log and nowhere else: a full lap of the map, hundreds of tiles
            # decoded, and not one row on any table. Its records are a different shape,
            # which is why they go to a file of their own that the secret-task reader
            # never opens.
            cmd += ["--json", self.rt.profiles.ghost_json()]
            # …and, from the same decoded stream, «who has already been shown this
            # tile» (#1245). The game announces every share an alliancemate presses in
            # the client, and hands over the standing list on login, so the capture
            # that is already reading this traffic is what lets a row on the tab say
            # «уже поделились» without the panel having done the sharing.
            cmd += ["--shared-json", self.rt.profiles.secret_shared_json()]
        # …AND ONLY THIS PROFILE'S CLIENT (#1306). Four accounts on one machine dial the
        # same two server ports, so with nothing said here this scan decoded every one
        # of them: a mate's shared task, another account's ghost tile and a stranger's
        # map all landed in THIS profile's checkpoint, which is the file auto-loot then
        # robs from. The narrowing is the profile's Windows session, not a pid read once
        # at spawn — the client is often not up yet when the panel starts the capture.
        cmd += game_process.capture_narrowing(self.rt.settings)
        # Capture tick interval from the tab (falls back to the child's own default if
        # the field is blank or non-numeric).
        interval = (self.interval.get().strip() if self.interval is not None else "")
        if interval.isdigit() and int(interval) > 0:
            cmd += ["--interval", interval]
        return cmd

    def _launch(self, cmd: list, script: str) -> None:
        """Seed the server, spawn the child, say what happened. Worker thread."""
        try:
            # Seed the on-screen server from the running game through the warm daemon, so
            # the capture prints "server N" from its first line instead of sitting on
            # "server unknown yet" until the map is scrolled (a passive capture only
            # learns the server from a map response, which arrives only while the map
            # moves). VPN-independent; the capture's own weight-of-traffic election still
            # overrides this the moment real map data disagrees.
            if self.rt.game.ready():
                srv = self.rt.game.current_server()
                if srv and str(srv).isdigit():
                    cmd += ["--seed-server", str(srv)]
                    self.tab.say("secret", "log.secret.seed_server", srv=srv)
            self.tab.say("secret", "log.secret.starting", script=script)
            mon = self.rt.children.spawn("secret", cmd, on_line=self.on_line,
                                         on_exit=self._on_exit)
            if not mon.start():
                self.tab.post(self._untick)
                return
            self._proc = mon
            # Confirm the child really started (so a silent monitor is never mistaken for
            # a crash). A passive pcap only yields tiles while the map is scrolling, and
            # nothing scrolls it by itself any more (#1272 — «Автообъезд карты» is gone),
            # so this always says which press to make: «Обойти карту», one lap, the whole
            # server in about three seconds.
            self.tab.say("secret", "log.secret.started_move_map", pid=mon.pid)
        except Exception as exc:          # noqa: BLE001 — a capture, never the window
            self.tab.say("secret", "log.secret.ended")
            self.rt.dbg("secret").error("capture start failed: %s", exc, exc_info=True)
            self.tab.post(self._untick)
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
        self._untick()

    def _untick(self) -> None:
        """Clear THIS capture's own box — never the other sniffer's (#1251)."""
        if self.switch is not None:
            self.switch.set(False)

    # -- the lines -----------------------------------------------------------
    def passes(self, line: str) -> bool:
        """Panel-side filters for a finding line. Non-task lines always pass.

        A finding looks like ` * lvl N  @[x,y|srv]  steal 0/3  family 6000  cfg …`. The
        level bounds are read live from the boxes, so typing in one affects subsequent
        lines immediately. A line counts as a finding when it has both a `lvl N` and a
        parseable coordinate.

        THE STAR IS NOT A SETTING (#1244). Three tiles in four on a real map are plain
        ones nobody will ever raid — 236 of the 277 in one live checkpoint — and every
        one of them used to print, which is what «спамим лог» was. Both feeds of the
        list are starred-only, so a plain tile in the log is a line that can never turn
        up in the table beside it: it can only be read as a row that went missing.
        """
        m = re.search(r"\blvl\s+(\d+)\b", line)
        if not m or not coords.parse(line):
            return True                 # header / progress / summary line — never filtered
        lvl = int(m.group(1))
        if not _starred(line, lvl):
            return False
        # The DISPLAY filter's own entries — not the auto-loot rule's. The two used to
        # share one pair, and a person narrowing the log silently re-aimed the robberies.
        # The very same pair governs what the TABLE shows (`SecretTasksTab._in_range`),
        # so the log and the list are one set rather than two (#1244).
        lo = self.tab.filter_from_var.get().strip()
        hi = self.tab.filter_to_var.get().strip()
        if lo.isdigit() and lvl < int(lo):
            return False
        if hi.isdigit() and lvl > int(hi):
            return False
        return True

    def on_tile(self, line: str) -> bool:
        """One TILE event: hand it to the list and get out of the way (#1416).

        The whole hook, and it is meant to read like one — a JSON parse, a dict, a call
        that appends to a buffer. No file is read, no game is asked, nothing waits. It
        runs on the child's reader thread, which must never be blocked: whatever the
        panel decides to do about the tile happens on the Tk thread, in one pass over
        whatever has arrived (`SecretTasksTab.tiles_seen`).

        Returns `False` so the reader swallows the line: it is machinery, and the human
        line for the same tile is printed right after it.
        """
        try:
            record = json.loads(line[len(TILE_MARKER):].strip())
        except ValueError:
            return False                # a torn line is not worth a word
        if isinstance(record, dict):
            self.tab.tile_seen(record)
        return False

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
        if line.startswith(TILE_MARKER):
            return self.on_tile(line)
        is_finding = bool(coords.parse(line))
        # THE CHECKPOINT MERGE IS THE FALLBACK NOW, not the feed (#1416). The tiles
        # arrive as their own events above; this keeps the old path alive for what the
        # events cannot carry — a capture built before the marker, and the progress line
        # that marks a flush after a restart, when the list starts empty and the file is
        # the only thing that remembers.
        if "on timer" in line:
            self.tab.after(self._nudge)
        if not self.passes(line):
            return False                # filtered out — handled, do not log
        if is_finding:                  # a coordinate present -> an actual finding
            self.append(line)
        return True

    def _nudge(self) -> None:
        """Re-merge the checkpoint into the list, debounced (Tk thread).

        Armed by name, so a burst of findings is one merge.

        AND IT RUNS WHETHER OR NOT ANYBODY HAS OPENED THE TAB (#1476). It used to
        return early on an unopened one — «it reads fresh when first shown anyway» —
        which was true of the checkpoint and false of the LIST: the child announces each
        tile once per state (`reported`, `secret_task_capture.py`), so a lap driven while
        the page was shut was heard by nobody and the next lap over the same tiles said
        nothing at all. The merge is a file read and a dict write; the drawing is what
        needs a window, and `_render` is the one that skips.
        """
        self.rt.tick.arm("secret_nudge", NUDGE_MS, self.tab.refresh)

    def append(self, line: str) -> None:
        """Append a finding to the active profile's log (best-effort)."""
        try:
            with open(self.rt.profiles.secret_log(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "line": line},
                                    ensure_ascii=False) + "\n")
        except OSError:
            pass
