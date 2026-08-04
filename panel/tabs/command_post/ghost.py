"""«Операция Призрак» as a standing order: five robberies a day, unattended.

Secret tasks needed a pcap because their tiles only arrive while the map moves. Ghost
recon does not: the client keeps the whole squad list and its own verdict on each, so
this watcher polls the GAME rather than a checkpoint. `tools/ghost_recon_steal.py --all`
does the deciding and the robbing, exactly as `steal_secret_task.py` does for the other.

The event runs ONE DAY A WEEK. Six days out of seven `IsOpenDay()` says so in one cheap
read and the answer is "look again in an hour" — a minute-by-minute poll of a shut event
is a log nobody wants and a round trip nobody needs. That is also why the switch is
EAGER on the tab: an order that only runs while somebody has the tab open would miss
the one day it matters.

It was `Panel._ghost_loop` / `_ghost_tick` / `_ghost_run`, with its checkbox drawn on a
different tab again. All three are here now, beside the page that shows the squads.
"""
from __future__ import annotations

import os
import threading

# The runtime FIRST: importing `panel.runtime` is what puts the repo's tools/lib on
# sys.path, and `lua_actions` is one of the bare-name modules that live there.
from ...runtime import game_process
from ...runtime.paths import TOOLS

import lua_actions                                   # noqa: E402  (see above)

#: How often the watcher looks while the event is open.
POLL = 60.0
#: …and while it is shut. Six days a week that is the whole of it.
CLOSED_PAUSE = 3600.0


class GhostOrder:
    """The watcher, the read that gates it, and the child that does the robbing."""

    def __init__(self, rt, pane) -> None:
        self.rt = rt
        self.pane = pane          # the page whose checkbox switches this on
        self._stop = None         # threading.Event while watching, else None
        self._proc = None         # one robbery child at a time

    @property
    def running(self) -> bool:
        return self._stop is not None

    def limit(self) -> int:
        return self.rt.settings.opt_int("autoloot_limit", low=1, high=50)

    # -- start / stop --------------------------------------------------------
    def toggle(self) -> None:
        if self.pane.autoloot_var.get():
            self.start()
        else:
            self.stop()

    def ensure_started(self) -> None:
        """Start it if this profile had it ticked. Idempotent."""
        if self.pane.autoloot_var.get():
            self.start()

    def start(self) -> None:
        if self._stop is not None:
            return
        self._stop = threading.Event()
        self.rt.say("ghost", "ghost.on")
        threading.Thread(target=self._loop, args=(self._stop,), daemon=True).start()

    def stop(self) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            stop.set()
            self.rt.say("ghost", "ghost.off")

    # -- the watch -----------------------------------------------------------
    def _loop(self, stop: threading.Event) -> None:
        """Poll the event's budget; rob when it is open and something is robbable."""
        last_err = ""
        while not stop.is_set():
            wait = POLL
            try:
                wait = self.tick()
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — one tick, not the loop
                err = f"{type(exc).__name__}: {exc}"
                if err != last_err:
                    last_err = err
                    self.rt.say("ghost", "log.ghost.error", error=err)
            if stop.wait(wait):
                return

    def tick(self) -> float:
        """One look. Returns how long to wait before the next one."""
        if self._proc is not None:            # a robbery is still running
            return POLL
        if self.rt.game.busy or not self.rt.game.up():
            return POLL
        running, _text = game_process.profile_status(self.rt.settings)
        if not running:
            return POLL
        chunk = ('CS.UnityEngine.Debug.LogError("GHOST open=" .. tostring(%s) '
                 '.. " left=" .. tostring(%s))'
                 % (lua_actions.ghost_recon_is_open(),
                    lua_actions.ghost_recon_steals_left()))
        text = " ".join(self.rt.game.client.run(chunk, marker="GHOST", settle=0.6,
                                                early=True))
        if "open=1" not in text:
            return CLOSED_PAUSE
        left = 0
        if "left=" in text:
            try:
                left = int(float(text.split("left=")[1].split()[0]))
            except (ValueError, IndexError):
                left = 0
        if left <= 0:
            # Open, but today's five are spent. The reset is at the server's day
            # boundary, so the same pause the secret-task watcher uses fits.
            return self.rt.settings.opt_int("autoloot_pause_min",
                                            low=1, high=1440) * 60.0
        self.rob(left)
        return POLL

    # -- the robbery ---------------------------------------------------------
    def rob(self, left: int) -> None:
        """Hand the robbable set to the standalone tool. Also what «ограбить всё» presses."""
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "ghost_recon_steal.py"),
               "--all", "--limit", str(min(left, self.limit()))]
        self.rt.say("ghost", "ghost.robbing", n=left)
        proc = self.rt.children.spawn_raw(cmd, "ghost")
        if proc is None:
            return
        self._proc = proc
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()

    def _reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if line:
                    self.rt.put(f"[ghost] {line}")
        except Exception:                     # noqa: BLE001 — the pipe closed
            pass
        if self._proc is proc:
            self._proc = None
