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
import daemon_pulse
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

# How long a check that THIS profile's daemon is reachable may take, and how long its
# answer is reused. Both exist because a daemon that is not there costs the whole timeout
# and a daemon that is there costs 0.3 ms — see `GameLink.up` (#1226).
UP_TIMEOUT_SEC = 0.35
UP_CACHE_SEC = 1.0

#: How long :meth:`GameLink.ready` reuses its answer. The same second `up()` uses, and
#: for the same reason: the reading is one loopback round trip, and a caller redrawing a
#: page must not pay one per widget. Shorter than the daemon's own probe interval on
#: purpose — the panel must never be the reason a reading is out of date.
READY_CACHE_SEC = 1.0

# How long `ensure()` waits for a daemon it just started, and how often it looks.
START_TRIES, START_WAIT = 60, 0.5
# How long `restart()` waits for the old one to let go of the port.
FREE_TRIES, FREE_WAIT = 20, 0.25
# How long a daemon that has been asked to die is given to actually go, once the polite
# route has already failed and the process is being ended from outside.
KILL_WAIT_SEC = 3.0

#: What :meth:`GameLink.health` answers, and the three states it exists to tell apart.
#:
#: A PORT THAT ACCEPTS A CONNECTION IS NOT ONE OF THEM (#1286). `up()` means «something
#: is listening», which is what `ensure` used to call warm — and on 2026-08-07 it said
#: «already warm» for half an hour over a daemon holding a client that had been
#: restarted out from under it. The three answers below are the question actually worth
#: asking, and every one of them has a different cure.
DAEMON_NONE = "none"      # nothing answered: start one
DAEMON_STALE = "stale"    # something answered, for a client that is not the one running
DAEMON_LIVE = "live"      # it answered, and it names the client that is running

# How long a `{"op":"ping"}` may take to come back. A daemon that is there answers in a
# fraction of a millisecond; one that is wedged inside a call still answers, because the
# ping is handled on its own connection thread and never touches the run lock.
PING_TIMEOUT_SEC = 2.0

# How long the last verdict is worth repeating to a front-end that must not ask for
# itself. The status poll asks every eight seconds; thirty is «the poll has stopped or
# was never running», and then a drawer says so by falling back rather than by drawing a
# verdict from a minute ago.
HEALTH_MEMORY_SEC = 30.0

# HOW LONG A PRESS WAITS FOR THE BACKGROUND TO STEP ASIDE (#1288). An ordinary errand
# holds the client for a median of 1.0 s and a p90 of 4 s (2026-08-07, three profiles'
# logs, n=11 701), so the great majority of presses get in within one checkpoint. This
# is the ceiling for the rest: past it the press says «занят» exactly as it used to,
# which is the honest answer for a run that is inside a call and has no safe moment to
# park — `restart_game` holds the client for a median of 304 s and waiting that out
# would be worse than refusing.
YIELD_WAIT_SEC = 12.0

# …and how long the PARKED run waits to get the client back before giving up. Longer
# than the press it stood aside for is expected to be, because the alternative to
# waiting is a failed errand and a retry hold. A run that loses the race says so and
# fails; it never goes on driving a client it does not hold.
PARK_WAIT_SEC = 60.0


def _as_pid(value) -> "int | None":
    """``value`` as a process id, or ``None`` — the wire says `null`, JSON says string."""
    try:
        return int(value) or None
    except (TypeError, ValueError):
        return None


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
        #: The last answer :meth:`up` got, and when: ``(at, port, answer)``. See there
        #: for why a check nobody caches is a second of frozen window per profile.
        self._up_seen: tuple = (0.0, None, False)
        #: The remembered answer of :meth:`ready` — (when, port, answer).
        self._ready_seen: tuple = (0.0, None, False)
        #: The process-wide claim this link is holding (`panel/runtime/claims.py`), or
        #: ``None``. Remembered rather than re-derived — see :meth:`_claim_client`.
        self._claimed = None
        #: Who this link last SAID was holding the game, or ``None`` — see
        #: :meth:`_say_busy`. Not a fact about the claim: a fact about the log.
        self._said_busy = None
        #: How urgent the claim this link is holding was taken at (#1288). Read by
        #: :meth:`yielded_to`, so a background errand can find out that a press is
        #: waiting and a press never finds that out about an errand.
        self._level = claims.BACKGROUND
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

    def up(self, fresh: bool = False) -> bool:
        """Is THIS profile's daemon reachable? (Not "a daemon somewhere".)

        **A daemon that is NOT there costs the whole timeout, every time** — measured on
        this machine, a connect to a port nothing is listening on never gets refused, it
        is dropped, so `is_running` sat for its full second and answered `False`. A
        daemon that IS there answers in 0.3 ms. So the honest reading of the old
        one-second default is «a second per check, but only when the answer is no».

        That is the shape that stops the panel scaling (#1226). A profile whose client
        is not up yet — the third and fourth account, most of the day — makes every
        `up()` a full second, and `up()` is asked by the status poll, the dashboard, the
        schedule's gate, a capture starting and every action. Some of those are on the
        TK THREAD, and then it is a second of window that does not redraw, per profile.

        Two changes, both cheap:

        * the timeout is :data:`UP_TIMEOUT_SEC`, because this is a LOOPBACK socket. A
          third of a second is already three orders of magnitude more than a daemon that
          is there needs, and waiting longer only makes a «no» slower to arrive;
        * the answer is reused for :data:`UP_CACHE_SEC`. A daemon does not come and go
          within a second, and the callers that would notice — `ensure`, which is
          watching for one it has just started — ask with ``fresh=True``.
        """
        port = self.port()
        if not fresh:
            at, was, answer = self._up_seen
            if was == port and (time.monotonic() - at) < UP_CACHE_SEC:
                return answer
        answer = lua_client.is_running(port=port, timeout=UP_TIMEOUT_SEC)
        self._up_seen = (time.monotonic(), port, answer)
        return answer

    def forget_up(self) -> None:
        """Drop the remembered answer — something just changed the daemon's existence."""
        self._up_seen = (0.0, None, False)
        self._ready_seen = (0.0, None, False)

    def attached_pid(self) -> "int | None":
        """Which client THIS profile's daemon is driving, or ``None``.

        One `{"op":"ping"}`, which the daemon has always answered with the pid it holds
        — nothing new on the wire, only nobody in the panel had ever asked (#1268).

        ``None`` for every «no answer»: daemon down, daemon not warm, socket refused.
        The caller compares this with the pid that is actually running, and a comparison
        against ``None`` must come out as «nothing to say» rather than as «stale» — a
        daemon that is not there is `ensure`'s business, and restarting one that does
        not exist is a loop with no bottom.

        Called from the status poll, so it is one loopback round trip every eight
        seconds — the same cost as :meth:`up`, which the poll already pays. Guarded by
        `up()` so a profile whose daemon is down does not pay a connect timeout for it
        (#1226: that is a second of frozen window, per profile).
        """
        if not self.up():
            return None
        client = self.client
        if client is None:
            return None
        try:
            return client.target_pid()
        except Exception:                             # noqa: BLE001 — a reading, never the panel
            return None

    def ping(self) -> dict:
        """The daemon's whole `{"op":"ping"}` answer, FRESH, or ``{}`` when none comes.

        Three facts in one round trip, because the three are only useful together: is it
        warm, which client it holds (``pid``), and which process it is itself (``self``,
        the pid used to end a daemon that will not end itself). Asked with
        ``fresh=True``: this is the reading that decides whether a daemon exists, and a
        cached yes is exactly how a dead one gets called warm (#1281).

        ``{}`` for every «no answer» — down, refused, timed out, or a daemon too old to
        say. Never raises: a reading of the link may not become the panel's fault.
        """
        if not self.up(fresh=True):
            return {}
        client = self.client
        if client is None:
            return {}
        try:
            if hasattr(client, "status"):
                return dict(client.status() or {})
            # A stand-in, or a client older than `status`: the one fact it can give.
            pid = client.target_pid() if hasattr(client, "target_pid") else None
            return {"ok": True, "pid": pid}
        except Exception:                             # noqa: BLE001 — a reading, never the panel
            return {}

    def daemon_pid(self) -> "int | None":
        """The pid of the daemon PROCESS itself, or ``None`` — see :meth:`_kill`."""
        return _as_pid(self.ping().get("self"))

    def _running_pid(self) -> "int | None":
        """The client that is RUNNING for this profile — never the daemon's own word.

        `game_client.target_pid` deliberately prefers the daemon's attachment, and for
        good reasons everywhere else: one daemon per client makes it the narrowest
        evidence there is. Here it is the one answer that must not be used, because the
        question is whether that attachment is still true — asking the daemon would
        compare its answer with itself and call every corpse healthy.

        ``None`` means «no client of this profile is running», which is not a fault and
        must not be treated as one.
        """
        try:
            import game_client
        except Exception:                             # noqa: BLE001 — not Windows, no psutil
            return None
        user = self.user()
        try:
            if not user:
                return game_client.running_pid()
            session = game_client.session_of(user)
            if session is None:
                return None
            found = game_client.session_pids_of(session)
            return found[0] if found else None
        except Exception:                             # noqa: BLE001 — a reading, never the panel
            return None

    def health(self, client_pid: "int | None" = None) -> str:
        """Is there a daemon, and is it holding the client that is actually running?

        THREE ANSWERS, and the whole of #1286 is that there are three of them:

        * :data:`DAEMON_NONE` — nothing answered the port. Start one.
        * :data:`DAEMON_STALE` — something answered, and the client it names is not the
          one running: a daemon whose client was restarted under it and which never let
          go, or one wedged inside a rebuild that cannot succeed — which is why the port
          is still bound at all. Restart the DAEMON, never the client (#1268).
        * :data:`DAEMON_LIVE` — it answered, and it names the client that is running.

        ``client_pid`` is the pid the caller has already found (the status poll has it
        from its own probe); ``None`` asks :meth:`_running_pid` for it.

        A machine with NO client running is not this fault, so a daemon that answers is
        LIVE there. «Could not tell» may never be a reason for a restart — the rule
        `panel/runtime/recovery.py` already keeps for `unknown` link readings.
        """
        answer = self._verdict(client_pid)
        self._health_seen = (time.monotonic(), answer)
        return answer

    def _verdict(self, client_pid) -> str:
        """THE AGE FIRST, THE PID SECOND — `tools/lib/daemon_pulse.py` (#1287).

        Comparing two pids proves that a process of that number exists, which is not
        what anybody wants to know. The daemon now says how long ago a chunk actually
        REACHED the game (`last_ok_age`), and that is a fact rather than an inference:
        a daemon wedged inside a rebuild, or holding a Lua VM that has gone, has the
        right pid and an age that stops moving.

        The pid comparison stays, because a fresh age cannot see «attached to the WRONG
        client» — and because a daemon too old to carry an age must go on being judged
        the way it always was rather than be called dead for predating this.

        The rule lives in `tools/lib/` and not here: the panel is one of its readers,
        the daemon is the other, and the last four incidents were all two readings that
        had drifted apart.
        """
        reply = self.ping()
        running = _as_pid(client_pid) if client_pid is not None else self._running_pid()
        return {"none": DAEMON_NONE, "stale": DAEMON_STALE,
                "live": DAEMON_LIVE}[daemon_pulse.verdict(reply, running_pid=running)]

    def ready(self, fresh: bool = False) -> bool:
        """WILL A CALL MADE NOW REACH THE GAME? The one reading a caller should ask.

        `up()` answers «a port accepted a connection», and fourteen callers read it as
        «the panel works». Measured over one day of one profile's logs, 194 of 2 073
        «warm» readings — 9 % — were taken while the client was not up-and-online, and
        three of them while there was no client process at all
        (`docs/research/daemon-architecture.md` §3). Every one of those was a reading a
        person or an errand acted on.

        This asks the daemon for the age of the last chunk that landed and answers on
        THAT. One round trip, measured at 0.8 ms even while the daemon's run lock is
        fully occupied — the ping is served on its own connection thread — so it is
        affordable everywhere `up()` was, including the Tk thread.

        Deliberately NOT the pid comparison of :meth:`health`: that costs a walk of the
        process list (~45 ms) and answers a different question — «is this daemon on the
        right client», which is `ensure`'s and the recovery's business, not a reader's.

        The answer is reused for :data:`READY_CACHE_SEC`, for the same reason `up()`
        reuses its own: a daemon does not come and go within a second, and a caller in
        a redraw loop must not pay a round trip per widget.
        """
        port = self.port()
        if not fresh:
            at, seen, answer = self._ready_seen
            if seen == port and (time.monotonic() - at) < READY_CACHE_SEC:
                return answer
        answer = daemon_pulse.landed_recently(self.ping())
        self._ready_seen = (time.monotonic(), port, answer)
        return answer

    def last_health(self) -> str:
        """The most recent verdict of :meth:`health`, or ``""`` if there is none recent.

        For the front-ends, and it costs nothing: the status poll asks `health` every
        eight seconds anyway, and both the window's indicator and the phone's dot have
        to say the same thing about the same daemon. Neither may ask for itself — the
        phone's page polls faster than the status thread does, and a reading that walks
        the process list per request is how a page becomes a load.

        ``""`` is «nobody has asked lately», not «healthy»: a drawer falls back to
        :meth:`up` there, which is what it drew before any of this existed.
        """
        at, answer = getattr(self, "_health_seen", (0.0, ""))
        return answer if (time.monotonic() - at) < HEALTH_MEMORY_SEC else ""

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
        """Make sure the daemon is up AND on the client that is running. Blocks; off Tk.

        ASKED FRESH, and that was #1281's second afternoon. `up()` reuses its answer for
        :data:`UP_CACHE_SEC` — right for the status poll and the schedule's gate, wrong
        for the one caller whose job is to notice a daemon that has gone. `ensure` was
        answering «already warm on port 47654» off a cached yes, doing nothing, and
        leaving the port dead.

        ASKED ABOUT THE CLIENT, which is #1286 and the half a cache could never explain.
        A daemon does not always die with the client it drives: it can answer its port
        perfectly while attached to a process that no longer exists, and it can be
        WEDGED there — `Daemon.run` rebuilds once, the rebuild fails against a dead pid,
        and the polite shutdown that follows is acknowledged before it is carried out
        (§8). So the port went on being held by a corpse, and every ask to bring the
        daemon back was answered by that corpse's own listening socket. Half an hour of
        it on 2026-08-07, with twelve of thirty rally joins reporting «связь с сервером
        пропала» and the strip reporting a warm daemon throughout.

        The question is :meth:`health` now — the ping's pid against the pid that is
        actually running — and a daemon answering for a client that is gone is RESTARTED
        here rather than reported as warm. Never the client: that is #1268's six
        pointless relaunches.
        """
        port = self.port()
        state = self.health()
        if state == DAEMON_LIVE:
            self._note("already warm on port %s", port)
            self.on_state("warm", True)
            return True
        if state == DAEMON_STALE:
            self._log.say("daemon", "log.daemon.stale")
            self._note_warn("on port %s answers for a client that is gone — restarting "
                            "the daemon", port)
            return self.restart()
        return self._start()

    def _start(self) -> bool:
        """Launch a daemon and wait for it. Asks nothing about what is already there.

        Split out of :meth:`ensure` so a restart cannot bounce between the two: `ensure`
        decides WHETHER a daemon is wanted, `restart` gets rid of the one that is in the
        way, and this one and only this one starts a process.
        """
        port = self.port()
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
                # The port first, because it is the cheap half and it is what the wait
                # is really for. A daemon binds it only AFTER it has taken hold of the
                # client (`tools/lua_daemon.py::main`), so a port that answers and a
                # health that is still STALE means the attach failed rather than that it
                # has not happened yet — but it is given the rest of the tries anyway,
                # since the daemon re-aims itself at a client that is still booting.
                if self.up(fresh=True) and self.health() == DAEMON_LIVE:
                    self._log.say("daemon", "log.daemon.ready")
                    self._note("ready on port %s", port)
                    self.on_state("warm", True)
                    return True
                time.sleep(START_WAIT)
        if self.up(fresh=True):
            # It is there and it never got hold of a client. Reported as its own fault,
            # because «did not come up» would send the next reader looking for a process
            # that is running perfectly well.
            self._log.say("daemon", "log.daemon.no_client")
            self._note_warn("came up on port %s but holds no client", port)
            self.on_state("error", False)
            return False
        self._log.say("daemon", "log.daemon.timeout")
        self._note_warn("did not come up on port %s within timeout", port)
        self.on_state("none", False)
        return False

    def restart(self) -> bool:
        """Shut the daemon down and bring it back. Blocks; call off the Tk thread.

        The shutdown is asked for politely (the daemon answers the op and exits), and
        THE ANSWER IS NOT THE ACT. That is what turned a stale daemon into a permanent
        one on 2026-08-07: the daemon replies `{"ok":true}` before it closes its
        evaluator, closing takes the run lock, and the lock was held by a call wedged
        against a client that had gone — so it acknowledged the shutdown and never
        exited. The port stayed bound, the five-second wait below expired in silence,
        and `ensure` read the corpse's socket as «already warm» (#1286).

        So the port is the verdict, never the reply: if it is still held, the process
        the ping named is ended from outside, and only a port that has actually come
        free gets a new daemon started on it. A second daemon that cannot bind is the
        same lie one process further along.
        """
        self._log.say("daemon", "log.daemon.restarting")
        self.on_state("starting", None)
        with self._activity.step("activity.daemon.restart", port=self.port()):
            if not self._shutdown():
                return False
            return self._start()

    def stop(self) -> bool:
        """End this profile's daemon and LEAVE IT DOWN. Blocks; call off the Tk thread.

        Half of «Стоп всё», which is two acts and only two: close the client, stop the
        daemon (#1393). Everything else that used to be switched off by that press is
        switched off by consequence — with no daemon there is nothing for a timer or a
        trigger to run through, and `panel/runtime/gate.py` is what turns that fact into
        «and so they do not try».

        The same shutdown :meth:`restart` uses, without the start that follows it, so
        there is exactly one description in this file of how a daemon is ended: politely
        first, from outside if the port stays bound, and the PORT is the verdict either
        way. ``False`` means the port is still held by something that would not die —
        which is worth knowing, because a gate reading that port will go on saying the
        daemon is alive.

        The state is announced as `none` rather than `error` on success: a daemon that
        was asked to go and went is not a fault, and the indicator saying «ошибка» over a
        press somebody made deliberately is how a person learns to distrust the strip.
        """
        self._log.say("daemon", "log.daemon.stopping")
        with self._activity.step("activity.daemon.stop", port=self.port()):
            if not self._shutdown():
                return False
        self._log.say("daemon", "log.daemon.stopped")
        self._note("stopped on port %s", self.port())
        self.on_state("none", False)
        return True

    def _shutdown(self) -> bool:
        """Get rid of the daemon on this port. ``False`` if the port is still held.

        Shared by :meth:`restart` and :meth:`stop`, because «how a daemon is ended» is
        one piece of knowledge and it was learned the hard way: the shutdown is asked for
        politely (the daemon answers the op and exits), and THE ANSWER IS NOT THE ACT.
        That is what turned a stale daemon into a permanent one on 2026-08-07: the daemon
        replies `{"ok":true}` before it closes its evaluator, closing takes the run lock,
        and the lock was held by a call wedged against a client that had gone — so it
        acknowledged the shutdown and never exited. The port stayed bound, the wait below
        expired in silence, and `ensure` read the corpse's socket as «already warm»
        (#1286).

        So the port is the verdict, never the reply: if it is still held, the process the
        ping named is ended from outside, and only a port that has actually come free
        counts as a daemon that is gone.
        """
        # Asked BEFORE the shutdown: a daemon that has gone answers nothing, and
        # this is the only place its own pid can still be had.
        doomed = self.daemon_pid()
        try:
            self.client.shutdown()
        except Exception as exc:                  # noqa: BLE001
            self._log.say("daemon", "log.daemon.shutdown_failed", error=exc)
        if not self._wait_free():
            self._kill(doomed)
            if not self._wait_free():
                self._log.say("daemon", "log.daemon.wont_die", port=self.port())
                self._note_warn("port %s is still held after a kill — nothing else can "
                                "bind it", self.port())
                self.on_state("error", False)
                return False
        # No token carried over: the daemon that granted it is gone, so the lease
        # died with it. A fresh one starts unleased rather than waving a dead token
        # about.
        self.client = lua_client.DaemonClient(port=self.port(), token="")
        return True

    def _wait_free(self) -> bool:
        """Has the port come free? Waits up to FREE_TRIES × FREE_WAIT for it."""
        for _ in range(FREE_TRIES):
            if not self.up(fresh=True):               # …one we have just shut down
                return True
            time.sleep(FREE_WAIT)
        return False

    def _kill(self, pid: "int | None") -> bool:
        """End the daemon PROCESS. ``True`` when it is gone.

        Reached only when a daemon acknowledged a shutdown and did not carry it out —
        never as the ordinary route, because a daemon killed mid-call leaves the game's
        Lua VM with whatever the call was in the middle of.

        The pid comes off the daemon's own `{"op":"ping"}`; nothing else on the machine
        can name it, since a second Windows session's daemon is not in this session's
        process list. That is also the case this cannot always win: a daemon belonging
        to another Windows LOGIN is not this token's to terminate, and the refusal is
        reported rather than retried.
        """
        if not pid:
            return False
        self._log.say("daemon", "log.daemon.killing", pid=int(pid))
        try:
            import psutil

            proc = psutil.Process(int(pid))
            proc.terminate()
            try:
                proc.wait(timeout=KILL_WAIT_SEC)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=KILL_WAIT_SEC)
            return True
        except Exception as exc:                      # noqa: BLE001 — gone, or not ours
            self._log.say("daemon", "log.daemon.kill_failed", error=exc)
            return False

    # -- the claim ----------------------------------------------------------
    def claim(self, owner: str = "panel", priority: int = claims.BACKGROUND,
              count: bool = True) -> bool:
        """Take the right to drive the game, or say it is already taken.

        THREE LOCKS NOW, not two, and the middle one is the whole of #1226's half of
        this: this link's own flag, then the process-wide registry keyed by the CLIENT
        (:mod:`panel.runtime.claims`), then the daemon's lease. See
        :func:`_claim_client` for the hole the middle one closes.

        ``priority`` (#1288) is filed with the claim and changes nothing about taking
        it — a free client is taken by whoever asks first, whatever they said. What it
        decides is what happens to a run ALREADY holding it when somebody more urgent
        turns up: see :meth:`demand` and :meth:`park`.

        IT BLOCKS, because the third lock is a round trip to another process. Whoever
        cannot afford that takes the two halves separately — :meth:`reserve` here and
        :meth:`lease` on a worker thread — which is what every press does now (#1331).
        """
        return self.reserve(owner, priority, count) and self.lease(owner)

    def reserve(self, owner: str = "panel", priority: int = claims.BACKGROUND,
                count: bool = True) -> bool:
        """The first two locks — this link's flag and the process-wide registry.

        NO INPUT AND NO OUTPUT: two dictionaries under two locks, microseconds, safe on
        the Tk thread. It answers the whole of «is another run of this panel driving
        this client», which is what a press has to know before it starts a thread.

        What it does NOT answer is whether the DAEMON's lease is free — that is
        :meth:`lease`, and it costs a socket. A reservation that is never followed by
        one is a client nobody else can take, so every caller pairs them: :meth:`claim`
        does both here, `panel/runtime/host.py::play_async` does the second on its
        worker.
        """
        owner = self._owned(owner)
        with self._busy_lock:
            if self._busy:
                # Counted, because nothing else can count it: this profile's own runs
                # never reach the registry's `acquire` — the flag turns them away first —
                # so «сколько нажатий ждало» read zero for the commonest refusal there is
                # (#1392, `panel/runtime/claims.py::note_refused`). `count` is what keeps
                # it a count of PRESSES: `claim_soon` asks again every 50 ms.
                if count:
                    claims.note_refused(self.endpoint())
                return False
            self._busy = True
        if not self._claim_client(owner, priority, count=count):
            with self._busy_lock:
                self._busy = False
            return False
        self._level = int(priority)
        return True

    def lease(self, owner: str = "panel") -> bool:
        """The third lock — the daemon's lease. **A ROUND TRIP: never on the Tk thread.**

        This is the half that can take seconds: the daemon is another process (and for a
        second account, in another Windows session), and asking it anything costs a
        connect and an answer. It used to sit inside :meth:`claim` on the calling thread,
        which is how a press from the phone spent 6–28 s of the event loop waiting for a
        busy daemon and then got told the press was «unknown» (#1331).

        A refusal undoes the reservation, so the pair leaves the link exactly as
        :meth:`claim` used to on the same failure — nothing half-held.
        """
        owner = self._owned(owner)
        if not self._claim_lease(owner):
            self._drop_client()
            with self._busy_lock:
                self._busy = False
            return False
        # The game was taken, so the next time it is not, that is news again.
        self._said_busy = None
        return True

    def regain(self, owner: str = "panel") -> bool:
        """Take a lease again after the DAEMON went and came back (#1411).

        NOT a claim: the two local locks are already held by the run asking for this, and
        they stay held. What has gone is the third one — the daemon's lease — and it went
        without anybody letting go of it: a restarted daemon starts with no lease at all,
        so the token this link is carrying names one that does not exist. Every `run` made
        with it is refused as «lease lost», for the rest of the run's life, and the run
        hears that as the game having gone deaf.

        The dead token is dropped before asking, so the daemon is asked for a NEW lease
        rather than being handed a re-claim of one it has never heard of. If somebody else
        got in first, the old token is put BACK, dead as it is: an empty token is not «no
        lease», it is «unleased», and an unleased run is let straight through the gate to
        drive the game beside its new owner (`tools/lib/game_lease.py::check_run`). A
        refusal that goes on being a refusal is the only safe answer here.

        ``False`` for every «could not» — no daemon on the port, a connect that failed, a
        lease that belongs to somebody else — and the caller stops, which is what a run
        that cannot hold the client has to do.
        """
        client = self.client
        if client is None or not hasattr(client, "acquire"):
            return False
        # FRESH, and for once the cost is right: this is asked at most once per refused
        # chunk, and the cached answer here is from before whatever just happened.
        self.forget_up()
        if not self.up(fresh=True):
            return False
        old = getattr(client, "token", "") or ""
        client.token = ""
        try:
            token = client.acquire(self._owned(owner), ttl=LEASE_TTL_SEC)
        except OSError:
            client.token = old
            return False
        if not token:
            client.token = old
            try:
                held = client.lease_state()
            except OSError:                           # noqa: BLE001 — a diagnostic
                held = {}
            self._say_busy(held.get("owner", "?"), held.get("held_sec", 0) or 0)
            return False
        return True

    # -- priorities: «нажал — действие» (#1288) ------------------------------
    def claim_soon(self, owner: str = "panel", priority: int = claims.HUMAN,
                   timeout: float = YIELD_WAIT_SEC, poll: float = 0.05) -> bool:
        """Take the claim, WAITING for a lesser run to step aside. Never on the Tk thread.

        The ordinary :meth:`claim` is a try: it answers «занято» and the caller gives up,
        which is what turned 343 presses in one day into nothing happening. This one
        hangs a demand on the door first (:func:`claims.demand`), so the background run
        holding the client can see that somebody it should make way for is waiting, and
        then polls until it lets go.

        ``timeout`` is a ceiling and not a promise: a run may be inside a call into the
        game with no safe moment to park, and a press that could not get in still has to
        say so rather than wait for ever. It is a WAIT, so this blocks — every caller is
        a worker thread, and `panel/runtime/host.py::play_async` is careful to reach it
        only from one.
        """
        key = self.endpoint()
        token = claims.demand(key, priority, self._owned(owner))
        try:
            deadline = time.monotonic() + max(0.0, float(timeout))
            first = True
            while True:
                # Only the FIRST attempt is a press being turned away; the twenty a
                # second after it are the same press still waiting, and counting them
                # made the debugger read «41 отказ» for one button (#1392).
                if self.claim(owner, priority, count=first):
                    return True
                first = False
                if time.monotonic() >= deadline:
                    return False
                time.sleep(poll)
        finally:
            # The demand comes off whether we got in or not: a note left on the door
            # would park every background run for ever, in the name of a press that is
            # not coming.
            claims.withdraw(key, token)

    def outranks(self, priority: int) -> bool:
        """Would a claim at ``priority`` be worth making the current holder wait?

        ``True`` for a free client too (:func:`claims.level` answers ``BACKGROUND`` for
        one), which is right: the caller is about to find it free and take it.
        """
        return int(priority) > claims.level(self.endpoint())

    def claimed_by(self) -> "str | None":
        """Who is holding this client, for a line that has to name them."""
        return claims.holder(self.endpoint())

    def yielded_to(self) -> "str | None":
        """Who is waiting for this client that this run should step aside for.

        ``None`` — which is the answer on every ordinary checkpoint of every ordinary
        run — is one dict lookup under a lock, which is why this can sit in the path of
        every statement of every scenario.
        """
        return claims.wanted(self.endpoint(), getattr(self, "_level", claims.BACKGROUND))

    def park(self, owner: str = "panel", timeout: float = PARK_WAIT_SEC) -> bool:
        """Let go for whoever is waiting, then take the claim back. ``False`` = lost it.

        The half of the priority rule that costs something. The run calling this is
        between two statements of its scenario — the coarsest join there is — so the
        client is in a state its own next statement is about to read anyway. It drops
        the claim and the lease, lets the press through, and takes both back.

        A ``False`` is honest and has to be treated as a failure by the caller: the run
        no longer holds the client and may not touch it. It happens when the press that
        pushed us out is itself long, or when a third party took the client meanwhile.
        """
        level = int(getattr(self, "_level", claims.BACKGROUND))
        key = self.endpoint()
        self.release()
        deadline = time.monotonic() + max(0.0, float(timeout))
        while claims.wanted(key, level) is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        first = True
        while True:
            # As in `claim_soon`: taking the claim BACK is one run resuming, not a stream
            # of presses, so only the first attempt is counted (#1392).
            if self.claim(owner, level, count=first):
                return True
            first = False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def _say_busy(self, owner: str, sec: int) -> None:
        """«игра занята» — ONCE per episode of contention, not once per attempt.

        A caller that WAITS for the game polls :meth:`claim`, and every refusal used to
        be a line: `panel/tabs/rally/tab.py::_join` asks every 0.15 s, so a profile
        waiting a minute for another wrote four hundred identical lines into its own
        log — and every one of them named the OTHER profile. That is what made a shared
        client read as a leak between profiles' logs (#1250): the reader saw a thousand
        records about a profile they were not looking at, in a file that is supposed to
        be about this one.

        The interesting facts are WHO is holding the game and that it has changed;
        neither is said again by the four hundredth copy. So the holder is remembered
        and a repeat of the same holder is dropped, until :meth:`claim` succeeds or
        :meth:`release` runs — after which the game being taken from under this profile
        is news once more.
        """
        who = str(owner or "?")
        if self._said_busy == who:
            return
        self._said_busy = who
        self._log.say("panel", "busy.elsewhere", owner=who, sec=int(sec))

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

    def endpoint(self) -> tuple:
        """Which CLIENT this link drives, as the registry keys it: ``(host, port)``.

        PUBLIC because it is the answer to «are these two profiles the same game»,
        which the workspace asks of every session it opens (#1250) — two of them on one
        endpoint is the copy-a-profile-and-forget-the-port accident, and the panel says
        so once instead of leaving it to be deduced from a stream of «занято».
        """
        return (lua_client.HOST, self.port())

    def _claim_client(self, owner: str, priority: int = claims.BACKGROUND,
                      count: bool = True) -> bool:
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
        key = self.endpoint()
        held = claims.acquire(key, owner, priority, count=count)
        if held is not None:
            self._say_busy(held, 0)
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
        if not self.up():
            # The same answer `acquire` is about to give, without the wait for it. This
            # matters because `claim` is called ON THE TK THREAD by every button, and a
            # daemon that is not there costs a connect to find out — so a press with no
            # daemon up froze the window for as long as the connect took, every time
            # (#1226). `up` is the cached, short-timeout check, and its answer here is
            # the honest one: nothing else can be driving a game nothing can reach.
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
        self._say_busy(held.get("owner", "?"), held.get("held_sec", 0) or 0)
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
        # …and the next refusal is a new episode, so it gets its line (`_say_busy`).
        self._said_busy = None
        # Nothing is held, so nothing is urgent: a level left behind would answer
        # `yielded_to` for the NEXT run, which may be a press that should never park.
        self._level = claims.BACKGROUND

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
                                        marker="ACT", settle=0.5, early=True):
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

        **EVERY COORDINATE JUMP LANDS AT THE TILE VIEW, AND THAT IS DECIDED HERE (#1272).**
        «При переходе по координатам всегда зум делать на уровень тайла… это для ЛЮБЫХ
        переходов.» It used to be an argument, and the «Секретки» tab passed its own
        «Зум» box into it — so a coordinate clicked in the log arrived at one height, the
        same coordinate clicked in a table at another, and nobody could say why. The
        parameter is GONE rather than defaulted: a rule that has to be remembered at four
        call sites is a rule the fifth one will not have. `jump_to_coord` with no height
        is the game's own jump, which is the tile view (`lua_actions.JUMP_ZOOM`).

        The lap is the one thing that legitimately walks the camera at another height,
        and it is not a coordinate jump at all: it schedules its own waypoints inside the
        game (`actions/scan_map.md` → `lua_actions.fast_map_sweep`) and never comes
        through here.

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
                # …and a daemon holding a client that has gone is not one to jump
                # through either. The status poll's verdict, not a fresh one: see the
                # same gate in `panel/runtime/schedule.py` (#1286).
                if (self.last_health() == DAEMON_STALE or not self.up()) \
                        and not self.ensure():
                    self._log.say("coord", "log.no_daemon")
                    return
                # ONE trip to the VM, not two. A coordinate with no server used to be
                # answered by reading `current_server()` first — a whole call, and its
                # settle, in front of a jump the game itself does the instant it is
                # asked. The chunk resolves it now (`lua_actions.jump_to_coord`), and
                # the line it logs says which server it landed on (#1230).
                target = int(server) if server is not None else None
                if not quiet:
                    self._log.say("coord", "log.coord.jumping",
                                  where=coords.fmt(x, y, target))
                for line in self.client.run(
                        lua_actions.jump_to_coord(x, y, target),
                        marker="ACT", settle=1.6, early=True):
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
