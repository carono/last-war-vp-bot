r"""The link to the game: the panel's own hold on the client, and the right to drive it.

**THE PANEL IS THE LINK (#1911).** There is no daemon process to start, watch, restart,
kill or re-elect a guard for. A running panel holds the client's Lua VM itself
(`panel/runtime/lua_service.py`) and answers the profile's port for the child tools that
still need a socket. What used to be a lifecycle with six states and a supervisor is now
one question — does a chunk land — and it is asked of an object in this process.

Two responsibilities, and they belong together because the second is about the first:

* **The connection.** Whether this profile's client is in THIS Windows session (then the
  panel attaches to it directly) or in another one (then a small process lives beside it
  — see :meth:`ensure` — started by this object and supervised by nobody), whether a
  chunk lands, and handing out the evaluator. A tab never touches `lua_client` directly.
* **The claim.** One action at a time, held in THREE locks, each covering what the next
  one cannot see: this link's own flag, because the panel's buttons run on the Tk thread
  while the timer scheduler runs on its own; the PROCESS-wide registry keyed by the
  client (panel/runtime/claims.py), because one window may hold four profiles and two of
  them may be pointed at one client; and the LEASE (tools/lib/game_lease.py), because a
  tab launched as its own process is a second panel with a second flag against one game.

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

WHAT THE THREE STATUSES ARE MADE OF, and which half of them lives here. The rule is
`tools/lib/profile_health.py`; this object supplies the two readings it cannot take for
itself — :meth:`plumbing` («does a chunk reach the client's VM», our own wiring, no
server involved) and :meth:`responding` («is the client's window answering Windows at
all»). The third, «does the game SERVER answer», is an active probe the status poll
makes through a scenario (`panel/__main__.py`, `actions/read_server_info.md`), because it
is the one reading that must go all the way to the far end and back.
"""
from __future__ import annotations

import threading
import time

import coords
import daemon_pulse
import lua_actions
import lua_client
import profile_health

from . import claims
from .activity import Activity
from . import lua_service

#: The server a jump falls back to when the game cannot say which one it is on.
DEFAULT_SERVER = str(lua_actions.HOME_SERVER)

#: How many times a jump asks the client «which warzone are you on» before giving up on
#: seeing its target, and how long it waits between two of those (#2593).
#:
#: THE CEILING IS NOT THE COST. A same-warzone jump answers on the FIRST read — measured
#: live, `ACT jump=…` and `curserver=` in the same second — so the ordinary press pays one
#: reading and stops. A CROSS-SERVER one is a world being loaded, and three tries (two
#: seconds) was measured too short: a jump to a neighbouring warzone whose chunk had gone
#: out perfectly well was reported «клиент не оказался на этой зоне», which is the one
#: lie this whole change exists to stop. Twelve seconds is the ceiling a person waits
#: rather than the time anything takes.
JUMP_CONFIRM_TRIES = 12
JUMP_CONFIRM_WAIT = 1.0


def _call(hook, argument) -> None:
    """Run a caller's hook without ever letting it break the run that called it."""
    if hook is None:
        return
    try:
        hook() if argument is None else hook(argument)
    except Exception:                                 # noqa: BLE001 — a caller's own
        pass                                          #   callback is never the link


# How long a lease is held without being renewed. Every chunk an action runs renews it,
# so this only ever fires for a holder that died mid-action.
LEASE_TTL_SEC = 120

# How long a check that a FOREIGN session's connector is reachable may take, and how long
# its answer is reused. A connector that is not there costs the whole timeout and one
# that is there costs 0.3 ms (#1226) — and this is only ever asked of the other session:
# the local link is an object in this process and answers instantly.
UP_TIMEOUT_SEC = 0.35
UP_CACHE_SEC = 1.0

#: How long ago a chunk must have landed for the link to count as working. The same
#: number the pulse itself uses — twice its probe interval, so one probe queued behind a
#: real call is not a verdict (`tools/lib/daemon_pulse.py`).
TRAFFIC_STALE_SEC = daemon_pulse.STALE_AFTER_SEC

# HOW LONG A PRESS WAITS FOR THE BACKGROUND TO STEP ASIDE (#1288). An ordinary errand
# holds the client for a median of 1.0 s and a p90 of 4 s (2026-08-07, three profiles'
# logs, n=11 701), so the great majority of presses get in within one checkpoint. This
# is the ceiling for the rest: past it the press says «занят» exactly as it used to.
YIELD_WAIT_SEC = 12.0

# …and how long the PARKED run waits to get the client back before giving up. Longer
# than the press it stood aside for is expected to be, because the alternative to
# waiting is a failed errand and a retry hold.
PARK_WAIT_SEC = 60.0


class GameLink:
    """One profile's hold on its client: the warm VM, and one action at a time."""

    def __init__(self, port, log, cwd: str = ".", on_state=None, debug=None,
                 on_settled=None, activity=None, user=None, name=None) -> None:
        self._port = port                 # callable: this profile's port
        self._log = log                   # the LogBus
        self._cwd = cwd
        # callable: the login of the Windows session this profile's CLIENT lives in, or
        # None for this desktop. A hijack finds its client in the session it is itself
        # running in, so a client over there cannot be attached to from here at all —
        # that profile keeps a small process beside its own client (see `ensure`).
        self._user = user if user is not None else (lambda: None)
        # callable: the profile this link belongs to, or None for a link that is not one
        # profile's (a bare harness). It goes in front of every claim owner, so a
        # refusal in the log says WHICH profile is holding the client (§4.3, #1226).
        self._name = name if name is not None else (lambda: None)
        #: "the link went green / is attaching / failed", said in one word. PUBLIC and
        #: reassignable like `on_settled`: the shell rebinds it per session (#1206).
        self.on_state = on_state or (lambda state, ok: None)
        #: EXTRA subscribers to the same event, which :attr:`on_settled` cannot hold
        #: (#2593). The attribute below is ASSIGNED by whoever wants it — the shell binds
        #: its status strip to it — so a second interested party assigning it deletes the
        #: first silently: `panel/runtime/host.py` hung the header's own «read at the first
        #: free link» there and `panel/__main__.py` overwrote it a moment later, in the one
        #: front-end that has a window. Anything that is not the shell's own strip
        #: subscribes through :meth:`add_settled` instead and cannot be unhooked by an
        #: assignment.
        self._settled_also: list = []
        #: "an action has just let go of the game" — the shell re-reads its status strip
        #: there. A tab launched on its own has no strip and leaves it a no-op.
        self.on_settled = on_settled or (lambda: None)
        #: "the camera has just been walked somewhere else" — the runtime hangs the
        #: header's `mark_stale` here (#2593), so the strip along the top re-reads WHERE
        #: the player is standing on an event rather than on a clock. A link nobody
        #: wired leaves it a no-op.
        self.on_moved = (lambda: None)
        self._dbg = debug
        #: What this link is doing, for the strip along the bottom of the window.
        self._activity = activity if activity is not None else Activity()
        self._busy = False
        self._busy_lock = threading.Lock()
        #: The last answer :meth:`up` got about a FOREIGN session's connector, and when.
        self._up_seen: tuple = (0.0, None, False)
        #: The process-wide claim this link is holding (`panel/runtime/claims.py`).
        self._claimed = None
        #: Who this link last SAID was holding the game, or ``None`` — see
        #: :meth:`_say_busy`. Not a fact about the claim: a fact about the log.
        self._said_busy = None
        #: How urgent the claim this link is holding was taken at (#1288).
        self._level = claims.BACKGROUND
        #: The standing failure of a foreign session's connector, so it is said on the
        #: edge and not on every poll — the class of defect this codebase keeps
        #: relearning (#1910).
        self._said_fail = ""
        self._said_at = 0.0
        self._fail_since = 0.0
        # `token=""` — explicitly unleased, rather than "whatever this process
        # inherited". A panel process may hold two profiles' leases at once.
        self._client = None
        self._client_for: tuple = ()      # (port, user) the client was built for

    # -- the connection ------------------------------------------------------
    def port(self) -> int:
        return int(self._port())

    def user(self) -> "str | None":
        """The login of the session this profile's client lives in, or ``None``."""
        try:
            found = self._user()
        except Exception:                             # noqa: BLE001 — a read, not the run
            return None
        return (str(found).strip() or None) if found else None

    def is_local(self) -> bool:
        """Is this profile's client in the panel's OWN Windows session?

        The whole of the difference between «the panel holds it» and «a small process
        over there holds it». Never inferred from a port: a profile says which session
        its client lives in, and a port is only how the child tools find the door.
        """
        return not self.user()

    def service(self) -> "lua_service.LuaService | None":
        """This process's Lua service, with this profile's door open. ``None`` if remote.

        Idempotent and cheap: the service is a process-wide singleton (one Windows
        session holds one client) and `listen` returns at once for a port already bound.
        """
        if not self.is_local():
            return None
        service = lua_service.local(log=self._log, debug=self._dbg)
        service.listen(self.port())
        return service

    @property
    def client(self):
        """What this link drives the game through, for the profile as it stands NOW.

        The port and the Windows session are CALLABLES for a reason — they follow a
        profile switch and an edited setting — so the client is rebuilt whenever either
        moves. It was built once in the runtime's constructor before #1224, and a second
        account on another port kept driving the first one's game.
        """
        want = (self.port(), self.user())
        if not self._client_for or self._client_for != want:
            self._repoint(want)
        return self._client

    @client.setter
    def client(self, value) -> None:
        """A double, handed in by a test — kept exactly as it is, ``None`` included.

        Filed under the profile as it stands NOW rather than under the value's own port,
        so «this link has no client» stays an answer until the profile actually moves.
        Rebuilding over it would turn every «no client» case into a live one.
        """
        self._client = value
        self._client_for = (self.port(), self.user())

    def _repoint(self, want: tuple) -> None:
        """Build the client for the profile as it stands now, and let the old one go.

        The lease does NOT come along, and that is the whole point: a token is one
        holder's word and actively harmful anywhere else — a `run` carrying it is
        refused as «lease lost» instead of simply running. So the claim is handed back
        and the new client starts unleased.
        """
        old = self._client
        port, user = want
        if user:
            self._client = lua_client.DaemonClient(port=port, token="")
        else:
            # The service OBJECT, not its door: building a client may not bind a port or
            # attach to anything. `ensure` opens the door when somebody actually drives.
            self._client = lua_service.LocalClient(
                lua_service.local(log=self._log, debug=self._dbg), token="")
        self._client_for = want
        if old is not None and getattr(old, "token", ""):
            try:
                old.release()
            except Exception:                         # noqa: BLE001 — a courtesy
                pass

    def rebind(self) -> bool:
        """Point this link at the profile as it stands now. ``True`` if it moved.

        Kept as the SPOKEN version of what :attr:`client` does by itself: a profile
        switch and a port edit say so in the log, and the shell wants to know whether
        there was anything to say.
        """
        want = (self.port(), self.user())
        if self._client is None:
            # NOTHING HAS MOVED — nothing has been built yet. A link is lazy, and a
            # first use reported as «порт: …» would say it on every boot.
            self._repoint(want)
            return False
        if self._client_for == want:
            return False
        self._repoint(want)
        return True

    @property
    def token(self) -> str:
        """The lease this link holds, or ``""``. What a child and a run are handed."""
        client = self.client
        return str(getattr(client, "token", "") or "") if client is not None else ""

    def evaluator(self):
        """The warm evaluator, under THIS link's lease.

        A chunk run through it during an action renews the claim rather than being
        refused by it — and it renews the claim of the profile that took it, which is
        the part an environment variable could not get right with two of them open.
        """
        return self.client

    def up(self, fresh: bool = False) -> bool:
        """Is there anything to take a lease from? Instant for a local link.

        A local client is driven by an object in this process, so the answer is «yes» as
        long as the door could be opened at all. A FOREIGN session's connector is another
        process and is asked over its port — with a short timeout and a cached answer,
        because a connector that is not there costs the whole timeout and this is asked
        by every claim, on the Tk thread (#1226).
        """
        if self.is_local():
            # The panel IS the link: there is always something in this process to take a
            # lease from, and asking may not be the thing that attaches to a client.
            return True
        port = self.port()
        if not fresh:
            at, was, answer = self._up_seen
            if was == port and (time.monotonic() - at) < UP_CACHE_SEC:
                return answer
        answer = lua_client.is_running(port=port, timeout=UP_TIMEOUT_SEC)
        self._up_seen = (time.monotonic(), port, answer)
        return answer

    def forget_up(self) -> None:
        """Drop the remembered answer — something just changed the far end."""
        self._up_seen = (0.0, None, False)

    def link_wait(self) -> "float | None":
        """Seconds from this client appearing to now — once per appearance (#1976).

        The number the whole panel is judged by: a person starts the game and nothing
        else, and this is how long they waited for it to work. Local clients only — a
        client in another Windows session is started over there and the panel has no
        honest moment to measure from, so it says nothing rather than a number it made
        up.
        """
        if not self.is_local():
            return None
        service = lua_service.current()
        return None if service is None else service.take_wait()

    def traffic_age(self) -> "float | None":
        """Seconds since a chunk last came back out of the game, or ``None``.

        THE ONE READING THE LINK IS JUDGED ON. Not a socket, not a port, not a pid: the
        age of the last chunk that actually ran in the client's Lua VM. Every errand the
        panel runs stamps it, and a self-probe fills the silences, so it costs nothing
        while the panel is working (`tools/lib/daemon_pulse.py`).
        """
        if self.is_local():
            service = lua_service.current()
            return service.traffic_age() if service is not None else None
        age = (self.client.status() or {}).get("last_ok_age") if self.up() else None
        return age if isinstance(age, (int, float)) else None

    def plumbing(self) -> str:
        """Does a chunk land? One of `profile_health`'s three ids — never a colour.

        Deliberately blind to the server: this is OUR wiring, and telling it apart from
        the client's own silence is what makes amber actionable (#1911).
        """
        age = self.traffic_age()
        if age is None:
            return profile_health.PLUMBING_UNASKED
        return (profile_health.LANDING if age <= TRAFFIC_STALE_SEC
                else profile_health.NOT_LANDING)

    def ready(self, fresh: bool = False) -> bool:
        """WILL A CALL MADE NOW REACH THE GAME? The one reading a caller should ask."""
        return self.plumbing() == profile_health.LANDING

    def responding(self) -> bool:
        """Is the client's own window answering Windows? The «завис» half of amber.

        A wedged client takes the attach and never runs the chunk, and so does a bug of
        ours — the two are indistinguishable from inside, which is why this is asked
        from outside. ``True`` when it cannot be told (a machine that will not answer
        the question may not convict a client of anything).
        """
        try:
            import game_client

            return game_client.responding(self.client_pid())
        except Exception:                             # noqa: BLE001 — a reading
            return True

    def client_pid(self) -> "int | None":
        """Which client this link is attached to, or ``None``."""
        try:
            client = self.client
            return client.target_pid() if client is not None else None
        except Exception:                             # noqa: BLE001 — a reading
            return None

    def error(self) -> str:
        """Why nothing lands, in the words of whatever refused it. ``""`` while it does."""
        if self.is_local():
            service = lua_service.current()
            return service.error() if service is not None else ""
        state = (self.client.status() or {}) if self.up() else {}
        return str(state.get("probe_error") or "")

    def ensure(self) -> bool:
        """Make sure a chunk can land. Blocks; call off the Tk thread.

        Local: open the door for the children and take hold of the client. There is
        nothing to «start» and nothing that can be up without a client behind it — an
        attach either works or says why, and the light is amber with that reason until
        it does.

        Foreign session: make sure the small process beside that client is answering,
        and start it if it is not. It is a CHILD of this link — nothing supervises it,
        nothing re-elects anything, and a silent one is simply started again the next
        time somebody needs it.
        """
        if not self.is_local():
            return self._ensure_remote()
        service = self.service()
        if service is None:
            return False
        if self.ready():
            return True
        with self._activity.step("activity.link.attach", port=self.port()):
            ok = service.reattach()
        self.on_state("green" if ok else "amber", ok)
        if not ok:
            self._say_failure("attach", "log.link.attach_failed", error=service.error())
        else:
            self._said_fail, self._fail_since = "", 0.0
        return ok

    def _ensure_remote(self) -> bool:
        """The client is in another Windows session: keep a connector alive beside it.

        `tools/rdp_instance.py` already owns the hop that gets a process into somebody
        else's session, and it is the only reason a separate process still exists at all:
        a hijack finds its client in the session it runs in, so this one cannot be driven
        from here however the panel is written.
        """
        if self.up(fresh=True):
            return True
        user = self.user() or ""
        with self._activity.step("activity.link.attach", port=self.port()):
            try:
                import game_client
                import rdp_instance

                session = game_client.session_of(user)
                if session is None:
                    raise LookupError(f"nobody is logged on as {user}")
                rdp_instance.start_daemon(session, self.port(),
                                          say=lambda msg: self._log.put(f"[link] {msg}"))
            except Exception as exc:                  # noqa: BLE001
                self._say_failure(str(exc), "log.link.session_failed", error=exc)
                self.on_state("amber", False)
                return False
        for _ in range(60):
            if self.up(fresh=True):
                self._said_fail, self._fail_since = "", 0.0
                self.on_state("green", True)
                return True
            time.sleep(0.5)
        self._say_failure("silent", "log.link.session_silent", port=self.port())
        self.on_state("amber", False)
        return False

    def reattach(self) -> bool:
        """Let the client go and take hold of it again — «переподключиться».

        The one cure this object has, and it costs a second: everything else the old
        daemon lifecycle could do (start, restart, kill, wait for a port) was about a
        process that no longer exists.
        """
        self._log.say("link", "log.link.reattaching")
        if not self.is_local():
            self.forget_up()
            try:
                self.client.reload()
            except Exception:                         # noqa: BLE001 — it may be gone
                pass
            return self._ensure_remote()
        service = self.service()
        if service is None:
            return False
        with self._activity.step("activity.link.attach", port=self.port()):
            ok = service.reattach()
        self.on_state("green" if ok else "amber", ok)
        return ok

    def let_go(self) -> bool:
        """Drop the hold on the client and close the door. Half of «Стоп всё» (#1393).

        The panel goes on running — it IS the link — so this is «let go», not «stop the
        daemon»: the VM is released, the children's port is closed, and nothing here
        will take hold again until something asks the game a question.
        """
        self._log.say("link", "log.link.letting_go")
        if not self.is_local():
            try:
                self.client.shutdown()
            except Exception:                         # noqa: BLE001 — already gone
                pass
            self.forget_up()
            self.on_state("amber", False)
            return True
        service = lua_service.local(log=self._log, debug=self._dbg)
        service.forget(self.port())
        lua_service.forget_local()
        self._client = None
        self._client_for = ()
        self.on_state("amber", False)
        return True

    #: HOW OFTEN A STANDING FAILURE IS REPEATED (#1910). A failure that stays true is
    #: retried on every status poll — eight seconds — and saying it each time is the
    #: noise this codebase keeps relearning. Five minutes is often enough that a person
    #: watching sees it is still true, and rare enough that the log stays readable.
    FAIL_SAY_SEC = 300.0

    #: …BUT SILENCE IS NOT THE SAME AS QUIET (#1994). Five minutes of nothing reads as
    #: «the panel is working» — during the fourteen-hour outage the log said one line at
    #: the start and then nothing at all, while the schedule stood still behind a held
    #: gate. So a standing failure is repeated once a minute in a SHORTER form that
    #: carries the one fact the first line could not: how long it has been true.
    FAIL_AGAIN_SEC = 60.0

    #: What the route puts in front of «the client is busy» so the panel can tell that
    #: case from every other reason nothing lands (`tools/lib/xlua_route.py::BUSY_MARK`).
    #: A client somebody is PLAYING is the ordinary case, not a fault, and it is the one
    #: the person needs named in their own language rather than in the mechanism's.
    BUSY_MARK = "client-busy"

    def _say_failure(self, fingerprint: str, key: str, **fmt) -> None:
        """Say why the link is amber — on the EDGE, then briefly, but never silently.

        `fingerprint` is what makes two failures the same failure: a REASON that has
        changed is news whatever the clock says, because it usually means the person has
        just fixed one thing and hit the next.

        A reason that has NOT changed is still said once a minute, as «for how long» —
        because a person reading the log is asking «is the panel doing anything», and an
        answer that stops arriving is indistinguishable from an answer of «yes».
        """
        now = time.monotonic()
        said, at = (self._said_fail, getattr(self, "_said_at", 0.0))
        since = getattr(self, "_fail_since", 0.0)
        if said == fingerprint and at:
            if (now - at) < self.FAIL_AGAIN_SEC:
                self._note_warn("still failing: %s", fingerprint)
                return
            self._said_at = now
            mins = max(1, int((now - (since or at)) // 60))
            reason = str(fmt.get("error") or "")
            busy = self.BUSY_MARK in reason
            # THE REPEAT LINE IS BUILT FROM A DIFFERENT KEY THAN THE FIRST ONE, so it
            # needs what THAT key names and nothing else (#2578). `log.link.attach_stuck`
            # wants an `{error}`, and one of the three callers above has none to give —
            # `session_silent` carries a port. Handing the key a `fmt` without `error`
            # made the whole line fall back to its own template, so the person read
            # «уже {minutes} мин: {error}» for hours: not merely ugly, it is the one line
            # that was supposed to say HOW LONG the client had been out of reach.
            if busy:
                self._log.say("link", "log.link.attach_busy", minutes=mins)
            elif reason:
                self._log.say("link", "log.link.attach_stuck",
                              minutes=mins, error=reason)
            else:
                self._log.say("link", "log.link.attach_stuck_quiet", minutes=mins)
            return
        self._said_fail, self._said_at, self._fail_since = fingerprint, now, now
        self._log.say("link", key, **fmt)

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
        """The third lock — the game lease. **A ROUND TRIP when the client is remote.**

        This is the half that can take seconds when the client is in another Windows
        session, where the lease is held by the connector over there (and for a
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

    def _yield_above(self) -> int:
        """The level a waiter must beat for THIS holder to step aside.

        Its own level, except at :data:`claims.DETACHED`, where it is one lower — so a
        detached run steps aside for another detached one (#1702).

        **Two detached runs would otherwise starve each other**, and that is not a
        theoretical worry: the golden-zombie hunt is detached and runs for hours, so the
        moment the rally auto-join was detached too, neither could ever make the other
        park and the banners would simply stop being joined. Below-background is a floor
        rather than a queue: everything outranks a detached run, and a detached run takes
        TURNS with its equals instead of holding the client against them.

        A background errand is unaffected: it still yields only to something genuinely
        more urgent, which is what keeps two ordinary timers from ping-ponging.
        """
        level = int(getattr(self, "_level", claims.BACKGROUND))
        return level - 1 if level <= claims.DETACHED else level

    def yielded_to(self) -> "str | None":
        """Who is waiting for this client that this run should step aside for.

        ``None`` — which is the answer on every ordinary checkpoint of every ordinary
        run — is one dict lookup under a lock, which is why this can sit in the path of
        every statement of every scenario.
        """
        return claims.wanted(self.endpoint(), self._yield_above())

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
        above = self._yield_above()
        key = self.endpoint()
        self.release()
        deadline = time.monotonic() + max(0.0, float(timeout))
        while claims.wanted(key, above) is not None and time.monotonic() < deadline:
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

    def add_settled(self, hook) -> None:
        """Also hear «an action has just let go of the game», without owning the hook.

        The half of :attr:`on_settled` an assignment cannot break: the shell keeps
        assigning that attribute for its own strip, and everybody else lands here.
        """
        if hook is not None:
            self._settled_also.append(hook)

    def settled(self) -> None:
        """Tell the shell's hook and every subscriber, and let none of them stop another."""
        _call(self.on_settled, None)
        for hook in list(self._settled_also):
            _call(hook, None)

    def landing(self) -> tuple:
        """Ask the client where it is standing: ``(viewed, home, in_other)``.

        One chunk, three facts (`lua_actions.jump_landing`). ``viewed`` is the number to
        SHOW and never the thing to judge by — see the chunk's own note.
        """
        try:
            for line in self.client.run(lua_actions.jump_landing(),
                                        marker="ACT", settle=0.5, early=True):
                if "landing=" not in line:
                    continue
                parts = line.split("landing=")[1].split()[0].split(",")
                if len(parts) < 3:
                    continue

                def number(raw: str) -> int:
                    try:
                        return int(str(raw).strip())
                    except (TypeError, ValueError):
                        return 0

                return (number(parts[0]), number(parts[1]),
                        str(parts[2]).strip().lower() == "true")
        except Exception as exc:                      # noqa: BLE001 — a reading, not the run
            self._log.say("server", "log.server.read_failed", error=exc)
        return (0, 0, False)

    def landed_on(self, target: "int | None") -> tuple:
        """Did the camera ARRIVE, and which warzone to show — ``(arrived, viewed)``.

        The proof a jump got there, and the reason `jump` can answer «done» instead of
        «sent» (#2593). The chunk's own `ACT jump=… srv=` line says what was ASKED FOR,
        not where the client is standing: `GotoWorldPos` tweens, and a cross-server jump
        loads the other world first, so a press that reported success off that line was
        reporting that a message had left.

        **WHAT COUNTS AS ARRIVED depends on which side of home the target is**, because
        the viewed number is not trustworthy across a cross-server jump (see
        :func:`lua_actions.jump_landing`): a foreign warzone is confirmed by
        `IsInOtherServer()` turning TRUE, and the account's own warzone by its turning
        false with `serverId` naming the target. Measured live before this: a jump to a
        neighbouring warzone whose chunk had gone out perfectly well was still called
        «клиент не оказался на этой зоне» twelve reads later.

        Read inside the claim the jump is already holding, so nothing else walks into the
        VM between the move and the check, and at most :data:`JUMP_CONFIRM_TRIES` times —
        this is one press confirming ITSELF, never a background poll.
        """
        if target is None:
            return (True, 0)
        viewed = 0
        for attempt in range(JUMP_CONFIRM_TRIES):
            viewed, home, other = self.landing()
            if other:
                # Somewhere that is not home. The client will not name WHICH while it is
                # there, so a foreign target is answered by the fact of being away.
                if home != target:
                    return (True, viewed or target)
            elif viewed == target or (home and home == target):
                return (True, viewed or target)
            if attempt + 1 < JUMP_CONFIRM_TRIES:
                time.sleep(JUMP_CONFIRM_WAIT)
        return (False, viewed)

    def jump(self, x: int, y: int, server, quiet: bool = False, on_done=None,
             human: bool = False) -> bool:
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

        ``on_done`` is called with what the jump CAME TO, once, from whichever thread
        finished it — ``{"ok": bool, "server": int | None, "reason": str}`` (#2593). It
        is what lets a press block its own button until the camera has actually arrived:
        the return value above only says a worker was started, which is why a refused
        claim looked exactly like a jump that worked, and why the person pressed «Перейти»
        several times. A refusal calls it too, and never a second time.
        """
        if not human and not self.claim():
            if not quiet:
                self._log.say("panel", "busy")
            _call(on_done, {"ok": False, "server": None, "reason": "busy"})
            return False

        def work() -> None:
            # SOMEBODY IS AT A BUTTON, SO THE JUMP WAITS FOR THE LINK RATHER THAN BOUNCING
            # OFF IT (#2593). The plain `claim` is a try, and «занят» half a second after a
            # press is the whole of «приходится иногда по несколько раз кликать» — the same
            # defect `claim_soon` was written for (#1392, «343 presses in one day turned
            # into nothing happening»). It hangs a demand on the door at :data:`claims.HUMAN`,
            # so the background errand holding the client parks between two statements, and
            # it BLOCKS — which is why it is here, on the worker, and not above.
            if human and not self.claim_soon(priority=claims.HUMAN):
                if not quiet:
                    self._log.say("panel", "busy")
                _call(on_done, {"ok": False, "server": None, "reason": "busy"})
                return
            handle = self._activity.begin("activity.game.jump", x=x, y=y)
            answer = {"ok": False, "server": None, "reason": "log.error"}
            try:
                # …and a link nothing lands through is not one to jump through
                # either. The poll's own reading first, an attach only if it is not
                # working (#1911).
                if not self.ready() and not self.ensure():
                    self._log.say("coord", "log.no_link")
                    answer = {"ok": False, "server": None, "reason": "log.no_link"}
                else:
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
                    arrived, landed = self.landed_on(target)
                    answer = {"ok": arrived, "server": landed or target,
                              "reason": "" if arrived else "log.coord.not_landed"}
                    if not quiet:
                        self._log.say("coord", "log.done")
            except Exception as exc:                  # noqa: BLE001
                self._log.say("coord", "log.error", error=exc)
                answer = {"ok": False, "server": None, "reason": str(exc)}
            finally:
                self._activity.end(handle)
                self.release()
                self.settled()
            # THE CAMERA MOVED, SO WHAT THE HEADER IS SHOWING IS OUT OF DATE (#2593). An
            # EVENT and never a clock, which is the only way a second reading is ever
            # taken (`panel/runtime/header.py::mark_stale`): the panel itself walked the
            # client, so it knows — nobody had to ask.
            if answer.get("ok"):
                # The landing already carries the confirmed warzone. Hand that FACT to
                # the header before the caller is told the jump is done; making the
                # header ask the game again left the phone's button released beside the
                # old number until an unrelated state tick (#2593).
                _call(self.on_moved, answer.get("server"))
            _call(on_done, answer)

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
