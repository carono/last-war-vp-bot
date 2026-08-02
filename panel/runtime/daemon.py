"""The link to the game: the warm daemon, and the right to drive it.

Everything that talks to the client goes through one object, so a tab asks the runtime
for the game instead of building its own client out of a port number it read off the app
(nine places did exactly that).

Two responsibilities, and they belong together because the second is about the first:

* **The connection.** Which daemon this profile drives (a profile naming a non-default
  port drives the client of ANOTHER Windows session — tools/rdp_instance.py), whether it
  is up, starting it if it is not, and handing out the warm evaluator. A tab never
  touches `lua_client` directly.
* **The claim.** One action at a time, held in TWO locks: an in-process one, because the
  panel's buttons run on the Tk thread while the timer scheduler runs on its own; and
  the DAEMON's lease (tools/lib/game_lease.py), because a tab launched as its own
  process is a second panel with a second flag against one game.

The daemon's answer is authoritative. A failed claim releases the local flag again, so
nothing is left held. No daemon reachable means nothing else can be driving the game
either, so the local flag alone is enough there — the fallback is honest, not a hole.

The token lives in `os.environ` for exactly as long as the claim does. That is what
reaches the two places this object does not: an evaluator a recipe builds for itself
mid-action (which is how the lease gets renewed at all), and every child spawned
meanwhile — auto-loot claims and *then* spawns the tool that does the robbing.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

import coords
import lua_actions
import lua_client

#: The server a jump falls back to when the game cannot say which one it is on.
DEFAULT_SERVER = str(lua_actions.HOME_SERVER)

# How long the daemon holds this process's claim without hearing from it. Every chunk an
# action runs renews it, so this only ever fires for a holder that died mid-action — and
# then the next window may take the game instead of finding it wedged.
LEASE_TTL_SEC = 120

# Windows process-creation flags: no console window, and detached so the daemon outlives
# the panel that started it.
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW
DETACHED = 0x00000008         # DETACHED_PROCESS

# How long `ensure()` waits for a daemon it just started, and how often it looks.
START_TRIES, START_WAIT = 60, 0.5
# How long `restart()` waits for the old one to let go of the port.
FREE_TRIES, FREE_WAIT = 20, 0.25


class GameLink:
    """The warm daemon for one profile, plus the one-action-at-a-time claim."""

    def __init__(self, port, python, log, env, cwd: str, daemon_script: str,
                 on_state=None, debug=None, on_settled=None) -> None:
        self._port = port                 # callable: this profile's daemon port
        self._python = python             # callable: the interpreter to start it with
        self._log = log                   # the LogBus
        self._env = env                   # callable: the child environment
        self._cwd = cwd
        self._script = daemon_script
        self._on_state = on_state or (lambda state, ok: None)
        #: "an action has just let go of the game" — the shell re-reads its status strip
        #: there. A tab launched on its own has no strip and leaves it a no-op.
        self.on_settled = on_settled or (lambda: None)
        self._dbg = debug
        self._busy = False
        self._busy_lock = threading.Lock()
        self.client = lua_client.DaemonClient(port=self.port())

    # -- the connection -----------------------------------------------------
    def port(self) -> int:
        return int(self._port())

    def up(self) -> bool:
        """Is THIS profile's daemon reachable? (Not "a daemon somewhere".)"""
        return lua_client.is_running(port=self.port())

    def evaluator(self):
        """The warm evaluator, on this profile's port.

        Carries whatever lease this process is running under, so a chunk run through it
        during an action renews the claim rather than being refused by it.
        """
        return lua_client.get_evaluator(port=self.port())

    def rebind(self) -> bool:
        """Point the client at the profile's port. ``True`` if it actually moved."""
        port = self.port()
        if getattr(self.client, "port", None) == port:
            return False
        self.client = lua_client.DaemonClient(port=port)
        return True

    def ensure(self) -> bool:
        """Make sure the daemon is up, starting it if not. Blocks; call off the Tk thread."""
        port = self.port()
        if self.up():
            self._note("already warm on port %s", port)
            self._on_state("warm", True)
            return True
        self._log.say("daemon", "log.daemon.starting")
        self._note("starting on port %s", port)
        self._on_state("starting", None)
        try:
            subprocess.Popen(
                [self._python(), self._script], cwd=self._cwd,
                creationflags=NO_WINDOW | DETACHED, env=self._env(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL)
        except Exception as exc:                      # noqa: BLE001
            self._log.say("daemon", "log.daemon.launch_failed", error=exc)
            self._note_error("launch failed")
            self._on_state("error", False)
            return False
        for _ in range(START_TRIES):
            if self.up():
                self._log.say("daemon", "log.daemon.ready")
                self._note("ready on port %s", port)
                self._on_state("warm", True)
                return True
            time.sleep(START_WAIT)
        self._log.say("daemon", "log.daemon.timeout")
        self._note_warn("did not come up on port %s within timeout", port)
        self._on_state("none", False)
        return False

    def restart(self) -> bool:
        """Shut the daemon down and bring it back. Blocks; call off the Tk thread.

        The shutdown is asked for politely (the daemon answers the op and exits); a
        daemon too wedged to answer is reported and the start still runs, because a
        fresh one binding the port is the outcome either way.
        """
        self._log.say("daemon", "log.daemon.restarting")
        self._on_state("starting", None)
        try:
            self.client.shutdown()
        except Exception as exc:                      # noqa: BLE001
            self._log.say("daemon", "log.daemon.shutdown_failed", error=exc)
        for _ in range(FREE_TRIES):                   # let the port come free
            if not self.up():
                break
            time.sleep(FREE_WAIT)
        self.client = lua_client.DaemonClient(port=self.port())
        return self.ensure()

    # -- the claim ----------------------------------------------------------
    def claim(self, owner: str = "panel") -> bool:
        """Take the right to drive the game, or say it is already taken."""
        with self._busy_lock:
            if self._busy:
                return False
            self._busy = True
        if not self._claim_lease(owner):
            with self._busy_lock:
                self._busy = False
            return False
        return True

    def _claim_lease(self, owner: str) -> bool:
        """Claim the daemon's lease. True also when there is no daemon to claim it from."""
        client = self.client
        if client is None or not hasattr(client, "acquire"):
            return True
        try:
            token = client.acquire(owner, ttl=LEASE_TTL_SEC)
        except OSError:            # no daemon — nothing else can be driving the game
            return True
        if token:
            os.environ[lua_client.LEASE_ENV_VAR] = token
            return True
        try:
            held = client.lease_state()
        except OSError:                               # noqa: BLE001 — a diagnostic
            held = {}
        self._log.say("panel", "busy.elsewhere",
                      owner=held.get("owner", "?"), sec=int(held.get("held_sec", 0)))
        return False

    def release(self) -> None:
        # Clear the environment FIRST: a child spawned between the release and the pop
        # would carry a token the daemon has already given away, and every run it made
        # would be refused as a lost lease.
        os.environ.pop(lua_client.LEASE_ENV_VAR, None)
        client = self.client
        if client is not None and hasattr(client, "release"):
            try:
                client.release()
            except OSError:
                pass
        with self._busy_lock:
            self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    # -- the two reads every caller of the game needs ------------------------
    def current_server(self) -> str:
        """Which server the client is on right now, or the home one if it will not say.

        Here rather than in the shell because a jump needs it and a tab may be the only
        window there is (docs/research/panel-tabs-refactor.md §4.2).
        """
        try:
            for line in self.client.run(lua_actions.current_server(),
                                        marker="ACT", settle=0.5):
                if "curserver=" in line:
                    return line.split("curserver=")[1].split()[0]
        except Exception as exc:                      # noqa: BLE001
            self._log.say("server", "log.server.read_failed", error=exc)
        return DEFAULT_SERVER

    def jump(self, x: int, y: int, server, quiet: bool = False) -> bool:
        """Jump the camera to a tile, on a worker thread. Serialised with every action.

        The claim is the ordinary one, so a coordinate clicked in the log and a timer
        coming due in the same instant cannot both walk into the game VM.

        ``quiet`` is for the map sweep, which jumps dozens of times a pass: its own
        progress line is enough, and a «занят» every few seconds while an errand runs
        would be worse still.

        Returns whether the jump was STARTED — ``False`` means the claim was taken by
        something else. The sweep uses that to keep its place instead of losing the
        waypoint it was refused on.
        """
        if not self.claim():
            if not quiet:
                self._log.say("panel", "busy")
            return False

        def work() -> None:
            try:
                if not self.up() and not self.ensure():
                    self._log.say("coord", "log.no_daemon")
                    return
                target = int(server) if server is not None else int(self.current_server())
                if not quiet:
                    self._log.say("coord", "log.coord.jumping",
                                  where=coords.fmt(x, y, target))
                for line in self.client.run(lua_actions.jump_to_coord(x, y, target),
                                            marker="ACT", settle=1.6):
                    self._log.put(f"[coord] {line}")
                if not quiet:
                    self._log.say("coord", "log.done")
            except Exception as exc:                  # noqa: BLE001
                self._log.say("coord", "log.error", error=exc)
            finally:
                self.release()
                self.on_settled()

        threading.Thread(target=work, daemon=True).start()
        return True

    # -- diagnostics --------------------------------------------------------
    def _note(self, msg, *args) -> None:
        if self._dbg is not None:
            self._dbg.info(msg, *args)

    def _note_warn(self, msg, *args) -> None:
        if self._dbg is not None:
            self._dbg.warning(msg, *args)

    def _note_error(self, msg) -> None:
        if self._dbg is not None:
            self._dbg.error(msg, exc_info=True)
