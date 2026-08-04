"""The link to the game: the warm daemon, and the right to drive it.

Everything that talks to the client goes through one object, so a tab asks the runtime
for the game instead of building its own client out of a port number it read off the app
(nine places did exactly that).

Two responsibilities, and they belong together because the second is about the first:

* **The connection.** Which daemon this profile drives (a profile naming a non-default
  port drives the client of ANOTHER Windows session — tools/rdp_instance.py), whether it
  is up, starting it if it is not, and handing out the warm evaluator. A tab never
  touches `lua_client` directly.
* **The claim.** One action at a time, held in THREE locks, each covering what the next
  one cannot see: this link's own flag, because the panel's buttons run on the Tk thread
  while the timer scheduler runs on its own; the PROCESS-wide registry keyed by the
  client (panel/runtime/claims.py), because one window may hold four profiles and two of
  them may be pointed at one client; and the DAEMON's lease
  (tools/lib/game_lease.py), because a tab launched as its own process is a second panel
  with a second flag against one game.

The daemon's answer is authoritative wherever there is a daemon to ask. A failed claim
releases everything it took on the way in, so nothing is left held.

The middle lock is there for the case the other two miss. «No daemon reachable means
nothing else can be driving the game either» was honest while a panel was one profile in
one process, and it stopped being true the moment a window could hold several: with one
daemon down, every session pointed at that client passed the lease check and the local
flag could not see them, because the flag is per link (#1226,
docs/research/multi-profile-panel.md §4.4).

THE TOKEN BELONGS TO THE LINK, NOT TO THE PROCESS. It used to live in `os.environ`, and
that was fine while a panel meant one profile. It is not fine with two profiles open at
once (#1206): the second link to claim overwrote the first one's token, the first to
release deleted the second one's live one, and a child spawned in between inherited
whichever happened to be there. So the token is `self.token` and is handed explicitly to
the three places that need it —

* the evaluator this link builds (`evaluator()`), which is how a chunk run mid-action
  renews the claim rather than being refused by it;
* every child spawned by the same runtime (`ChildFactory.env` asks for it) — auto-loot
  claims and *then* spawns the tool that does the robbing;
* the scenario interpreter, through `Context.game_token`, which is where a recipe
  building an evaluator for itself gets one that carries the lease.

`LW_GAME_LEASE` is still what a tool started from a shell inherits; it simply stopped
being how the panel talks to itself.
"""
from __future__ import annotations

import subprocess
import threading
import time

import coords
import lua_actions
import lua_client

from . import claims
from .activity import Activity

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
                 on_state=None, debug=None, on_settled=None, activity=None,
                 user=None, name=None) -> None:
        self._port = port                 # callable: this profile's daemon port
        self._python = python             # callable: the interpreter to start it with
        self._log = log                   # the LogBus
        self._env = env                   # callable: the child environment
        self._cwd = cwd
        self._script = daemon_script
        # callable: the login of the Windows session this profile's CLIENT lives in,
        # or None for this desktop. A daemon has to be started beside the client it
        # hijacks — `il2cpp_probe.find_game_pid` looks in the session the daemon
        # itself runs in — so a daemon started here for a profile whose client is in
        # session 4 comes up on the right port and finds the wrong game, or no game.
        self._user = user if user is not None else (lambda: None)
        # callable: the profile this link belongs to, or None for a link that is not one
        # profile's (a bare harness). It goes in front of every claim owner, so a
        # refusal in the log says WHICH profile is holding the client rather than only
        # that something is — which is the whole difference between «занято» and a
        # readable answer once more than one profile is open (§4.3, #1226).
        self._name = name if name is not None else (lambda: None)
        #: "the daemon went warm / is starting / failed", said in one word. PUBLIC
        #: and reassignable like `on_settled`: the shell rebinds it per session, so
        #: the indicator that gets painted is the one on THAT profile's page (#1206).
        self.on_state = on_state or (lambda state, ok: None)
        #: "an action has just let go of the game" — the shell re-reads its status strip
        #: there. A tab launched on its own has no strip and leaves it a no-op.
        self.on_settled = on_settled or (lambda: None)
        self._dbg = debug
        #: What this link is doing, for the strip along the bottom of the window
        #: (panel/runtime/activity.py). Everything here that blocks says so: starting
        #: a daemon takes up to half a minute and a jump takes a round trip, and a
        #: window that goes quiet for either of them looks exactly like one that hung.
        #: Its own when nobody handed one over, so a link built bare still works.
        self._activity = activity if activity is not None else Activity()
        self._busy = False
        self._busy_lock = threading.Lock()
        #: The process-wide claim this link is holding (`panel/runtime/claims.py`), or
        #: ``None``. Remembered rather than re-derived — see :meth:`_claim_client`.
        self._claimed = None
        # `token=""` — explicitly unleased, rather than "whatever this process
        # inherited". A panel process may hold two profiles' leases at once, so a
        # client that picked one up out of the environment would be carrying the
        # other profile's right to drive the other profile's client.
        self._client = lua_client.DaemonClient(port=self.port(), token="")
        #: Which port :attr:`_client` was BUILT for, so the property below can tell
        #: that the profile's answer has moved since. ``None`` for a client somebody
        #: handed in (a test's double): not ours to re-point.
        self._client_port = self.port()

    # -- the connection -----------------------------------------------------
    def port(self) -> int:
        return int(self._port())

    @property
    def client(self):
        """This profile's daemon client, ON THE PORT THE PROFILE NAMES NOW.

        The port is a CALLABLE for a reason — it follows a profile switch and an edited
        setting — and everything else here re-reads it on every use. The client was the
        one thing that did not: it was built once, in the runtime's constructor, and
        stayed on whatever the answer was at that instant. During a boot that instant is
        before the profile's saved values have reached the widgets, so a second account
        on 47655 got a client on 47654 and kept it. Nothing said so, because the client
        still answered — it was simply answering about the OTHER account's game: the
        lease was claimed there while the scenario ran on 47655 and came back «lease
        lost» (#1224).

        So the check is here, where it cannot be forgotten, rather than in the callers
        that happen to remember `rebind()`.
        """
        if self._client_port is not None and self._client_port != self.port():
            self._repoint()
        return self._client

    @client.setter
    def client(self, value) -> None:
        self._client = value
        # A double without a port is nobody's to follow; a real client says which
        # daemon it was made for and the property keeps it honest from here on.
        self._client_port = getattr(value, "port", None)

    def _repoint(self) -> None:
        """Build a client for the port the profile names now, and let the old one go.

        The lease does NOT come along, and that is the whole point: a token is one
        daemon's word, meaningless to another and actively harmful there — a `run`
        carrying it is refused as «lease lost» instead of simply running. So the claim
        is handed back to the daemon that granted it (a lease left behind would hold
        that client for its whole ttl) and the new client starts unleased. The panel's
        own `_busy` flag is untouched: whoever holds the claim still holds it, and its
        `release()` finds a client with nothing to give back.
        """
        old, port = self._client, self.port()
        self._client = lua_client.DaemonClient(port=port, token="")
        self._client_port = port
        if old is not None and getattr(old, "token", ""):
            try:
                old.release()
            except Exception:                         # noqa: BLE001 — a courtesy, not the move
                pass

    @property
    def token(self) -> str:
        """The lease this link holds, or ``""``. What a child and a run are handed."""
        client = self.client
        return str(getattr(client, "token", "") or "") if client is not None else ""

    def up(self) -> bool:
        """Is THIS profile's daemon reachable? (Not "a daemon somewhere".)"""
        return lua_client.is_running(port=self.port())

    def evaluator(self):
        """The warm evaluator, on this profile's port and under THIS link's lease.

        A chunk run through it during an action renews the claim rather than being
        refused by it — and it renews the claim of the profile that took it, which is
        the part an environment variable could not get right with two of them open.
        """
        return lua_client.get_evaluator(port=self.port(), token=self.token)

    def rebind(self) -> bool:
        """Point the client at the profile's port. ``True`` if it actually moved.

        Kept as the SPOKEN version of what :attr:`client` now does by itself: a profile
        switch and a port edit say so in the log, and the shell wants to know whether
        there was anything to say. The move itself, and what happens to the lease of the
        daemon being left, is :meth:`_repoint`.
        """
        port = self.port()
        if getattr(self._client, "port", None) == port:
            return False
        self._repoint()
        return True

    def user(self) -> "str | None":
        """The login of the session this profile's client lives in, or ``None``."""
        try:
            found = self._user()
        except Exception:                             # noqa: BLE001 — a read, not the run
            return None
        return (str(found).strip() or None) if found else None

    def _start_in_session(self, user: str, port: int) -> None:
        """Start the daemon INSIDE ``user``'s Windows session, beside its client.

        A daemon hijacks a thread of the client it drives, and it finds that client in
        the session it is itself running in — so one started here would listen on the
        right port and drive the wrong game, or none at all. `tools/rdp_instance.py`
        already owns the hop that gets a process into somebody else's session (SYSTEM,
        then the session's own logon token); this only hands it the port and a place to
        say what it is doing, since a windowed panel has no console for its prints.

        Raises `LookupError` when nobody is logged on there — a session that does not
        exist has nothing to start a daemon in, and saying so is better than half a
        minute of silence followed by a timeout.
        """
        import game_client
        import rdp_instance

        session = game_client.session_of(user)
        if session is None:
            raise LookupError(f"nobody is logged on as {user}")
        rdp_instance.start_daemon(session, port,
                                  say=lambda msg: self._log.put(f"[daemon] {msg}"))

    def ensure(self) -> bool:
        """Make sure the daemon is up, starting it if not. Blocks; call off the Tk thread."""
        port = self.port()
        if self.up():
            self._note("already warm on port %s", port)
            self.on_state("warm", True)
            return True
        user = self.user()
        self._log.say("daemon", "log.daemon.starting")
        self._note("starting on port %s (session %s)", port, user or "this desktop")
        self.on_state("starting", None)
        # Up to START_TRIES × START_WAIT of waiting — thirty seconds of a window with
        # nothing to say for itself unless it says this.
        with self._activity.step("activity.daemon.start", port=port):
            try:
                if user:
                    self._start_in_session(user, port)
                else:
                    subprocess.Popen(
                        [self._python(), self._script], cwd=self._cwd,
                        creationflags=NO_WINDOW | DETACHED, env=self._env(),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL)
            except Exception as exc:                  # noqa: BLE001
                self._log.say("daemon", "log.daemon.launch_failed", error=exc)
                self._note_error("launch failed")
                self.on_state("error", False)
                return False
            for _ in range(START_TRIES):
                if self.up():
                    self._log.say("daemon", "log.daemon.ready")
                    self._note("ready on port %s", port)
                    self.on_state("warm", True)
                    return True
                time.sleep(START_WAIT)
        self._log.say("daemon", "log.daemon.timeout")
        self._note_warn("did not come up on port %s within timeout", port)
        self.on_state("none", False)
        return False

    def restart(self) -> bool:
        """Shut the daemon down and bring it back. Blocks; call off the Tk thread.

        The shutdown is asked for politely (the daemon answers the op and exits); a
        daemon too wedged to answer is reported and the start still runs, because a
        fresh one binding the port is the outcome either way.
        """
        self._log.say("daemon", "log.daemon.restarting")
        self.on_state("starting", None)
        with self._activity.step("activity.daemon.restart", port=self.port()):
            try:
                self.client.shutdown()
            except Exception as exc:                  # noqa: BLE001
                self._log.say("daemon", "log.daemon.shutdown_failed", error=exc)
            for _ in range(FREE_TRIES):               # let the port come free
                if not self.up():
                    break
                time.sleep(FREE_WAIT)
            # No token carried over: the daemon that granted it is gone, so the lease
            # died with it. A fresh one starts unleased rather than waving a dead token
            # about.
            self.client = lua_client.DaemonClient(port=self.port(), token="")
            return self.ensure()

    # -- the claim ----------------------------------------------------------
    def claim(self, owner: str = "panel") -> bool:
        """Take the right to drive the game, or say it is already taken.

        THREE LOCKS NOW, not two, and the middle one is the whole of #1226's half of
        this: this link's own flag, then the process-wide registry keyed by the CLIENT
        (:mod:`panel.runtime.claims`), then the daemon's lease. See
        :func:`_claim_client` for the hole the middle one closes.
        """
        owner = self._owned(owner)
        with self._busy_lock:
            if self._busy:
                return False
            self._busy = True
        if not self._claim_client(owner):
            with self._busy_lock:
                self._busy = False
            return False
        if not self._claim_lease(owner):
            self._drop_client()
            with self._busy_lock:
                self._busy = False
            return False
        return True

    def _owned(self, owner: str) -> str:
        """``timer`` → ``<profile>/timer`` — the profile in front of what it is doing.

        Both halves matter to somebody reading a refusal: WHOSE errand is holding the
        client, and which errand. Without the profile the log of a four-account panel
        says «занято: timer» four different ways and means four different accounts.
        """
        try:
            profile = self._name()
        except Exception:                             # noqa: BLE001 — a label, not the run
            profile = None
        name = str(owner or "panel")
        return f"{profile}/{name}" if profile else name

    def _endpoint(self) -> tuple:
        """Which CLIENT this link drives, as the registry keys it: ``(host, port)``."""
        return (lua_client.HOST, self.port())

    def _claim_client(self, owner: str) -> bool:
        """Take the process-wide claim on this client. ``False`` if a profile holds it.

        THE HOLE THIS CLOSES. `_claim_lease` answers ``True`` when the daemon cannot be
        reached — "nothing else can be driving the game either" — and that was honest
        while a panel was one profile in one process. With several profiles in ONE
        process and one daemon down, every one of them passed: two sessions pointed at
        the same client (the copy-a-profile-and-forget-the-port accident, §4.3) would
        both walk into it, and the local flag could not see it because the flag is per
        link. Keyed by the client rather than by the profile, so two links on one port
        take turns and two links on two ports do not wait for each other at all.
        """
        key = self._endpoint()
        held = claims.acquire(key, owner)
        if held is not None:
            self._log.say("panel", "busy.elsewhere", owner=held, sec=0)
            return False
        # WHICH key, remembered — never re-derived at release time. `release()` is
        # called by callers that never claimed (a runtime shutting down always lets go),
        # and by then the port may have moved with a profile switch. Either way, a link
        # that drops a key it did not take drops ANOTHER profile's claim on the client
        # they share, which is the one failure this registry exists to prevent.
        self._claimed = key
        return True

    def _drop_client(self) -> None:
        """Let go of the process-wide claim, if this link is the one holding it."""
        key, self._claimed = getattr(self, "_claimed", None), None
        if key is not None:
            claims.release(key)

    def _claim_lease(self, owner: str) -> bool:
        """Claim the daemon's lease. True also when there is no daemon to claim it from.

        `acquire` stores the token on the client itself, which is this link's own state
        and nobody else's — see the module docstring on why that matters.
        """
        client = self.client
        if client is None or not hasattr(client, "acquire"):
            return True
        try:
            token = client.acquire(owner, ttl=LEASE_TTL_SEC)
        except OSError:            # no daemon — nothing else can be driving the game
            return True
        if token:
            return True
        try:
            held = client.lease_state()
        except OSError:                               # noqa: BLE001 — a diagnostic
            held = {}
        self._log.say("panel", "busy.elsewhere",
                      owner=held.get("owner", "?"), sec=int(held.get("held_sec", 0)))
        return False

    def release(self) -> None:
        # `client.release()` clears the token on the way out even when the daemon is
        # unreachable, so a child spawned after this can never carry a token the daemon
        # has already given away — every run it made would be refused as a lost lease.
        client = self.client
        if client is not None and hasattr(client, "release"):
            try:
                client.release()
            except OSError:
                pass
        # …and the process-wide one, whatever happened above: a claim this link cannot
        # let go of is a client no other profile can ever take.
        self._drop_client()
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
            handle = self._activity.begin("activity.game.jump", x=x, y=y)
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
                self._activity.end(handle)
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
