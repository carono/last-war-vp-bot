r"""The panel's own hold on the game — there is no daemon process any more (#1911).

**The panel IS the link.** A `LuaEval` — the thread hijack and the il2cpp resolution that
let a chunk run inside the client — is built HERE, in the panel's own process, on a
worker thread, and it stays warm for as long as the panel is open. Nothing starts it,
nothing supervises it, nothing elects a watcher for it, and there is no port to be «up»
without a client behind it. What used to be a whole lifecycle — `ensure` / `restart` /
`stop` / `_kill` / «warm, stale, none» — is now the ordinary question of whether a chunk
lands, asked of an object this process owns.

THE DOOR IS STILL A SOCKET, and that is not a leftover. Two dozen tools under `tools/`
are spawned as CHILD processes by the panel and drive the game through
`tools/lib/lua_client.py`; a child cannot share this process's evaluator, and two
hijacks of one client racing each other is exactly what the lease exists to prevent. So
the service listens on the profile's port and speaks the protocol `lua_daemon` always
spoke — the same ops, the same lease, the same pulse. From a child's side nothing has
changed. From the panel's side the socket is not used at all: panel code holds a
:class:`LocalClient`, which is the same surface with the round trip taken out.

ONE ATTACH PER PROCESS. A Windows session has one Last War client, so the panel has one
VM to hold however many profiles are open on it; the listeners are per PORT and the
evaluator behind them is shared, which is also what keeps the run lock and the lease
meaning what they say. A profile whose client lives in ANOTHER Windows session cannot be
attached to from here at all — a hijack finds its client in the session it runs in — and
that one still speaks to a small process over there (`panel/runtime/link.py`), owned by
the link that started it and supervised by nobody.

WHAT DOES NOT HAPPEN HERE, ON PURPOSE:

* **nothing exits.** `lua_daemon`'s answer to three failed probes is to let go of the
  port and die, because a fresh daemon on a free port was a state the panel knew how to
  cure. This process is the panel: it drops the evaluator and builds a new one, and if
  that fails the light goes amber and says so.
* **`shutdown` is refused.** It is an op an old tool may still send; carrying it out
  would close the panel.
* **no failure is announced more than once.** The same standing failure, said on the
  edge and then left alone — the class of defect this codebase keeps relearning (#1910).
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time

import lua_client

#: How often the watch thread looks in: follow the client across a restart, and probe
#: the link if nothing has landed lately. Five seconds — the same interval the daemon
#: used, for the same reason: a client restart takes the better part of a minute, so
#: this is never the slow part.
WATCH_SEC = 5.0

#: …and how often it looks while NOTHING IS HELD (#1976). A client that has just been
#: started is not attachable for the better part of a minute — its il2cpp module is not
#: loaded, then it has no window, then its main thread is not where a hijack can reach
#: it — and every one of those refusals is cheap. So the look is faster exactly while
#: there is something to catch, and drops back to :data:`WATCH_SEC` the moment a client
#: is held.
#:
#: TWO FIXED RATES AND NOTHING BETWEEN THEM. Not a backoff, not an escalation, not a
#: doubling: the thing this replaces is a five-second wait that turned «I started the
#: game» into «the panel picks it up when it gets round to it», and a scheme that grows
#: its own wait is how that becomes half an hour (#1910).
CATCH_SEC = 1.5

#: How long a bind is retried before the service gives up on the port. A panel that has
#: just been restarted may find its own previous listener still letting go.
BIND_TRIES, BIND_WAIT = 20, 0.25

def _caller(name: str) -> str:
    """A caller's name, grouped so a minute's calls do not scatter across 30 rows (#2404).

    Every scenario run gets a worker of its own — `lw:<profile>:<tag>:<scenario>`, made
    fresh each time — and Python's own pools name theirs `Thread-38 (work)`. Counted raw,
    sixty calls from one errand read as sixty different callers and the histogram says
    nothing. So a worker is grouped by what it is FOR: the scenario for a run, the target
    function for a pool thread, and the name itself for the panel's own named threads,
    which are already one per job.
    """
    if name.startswith("lw:"):
        parts = name.split(":")
        return "run:" + ":".join(parts[2:]) if len(parts) > 2 else name
    if name.startswith("Thread-") and "(" in name:
        return "thread:" + name.split("(", 1)[1].rstrip(")")
    return name


#: The first thing a chunk names, for telling one CHILD's traffic from another's — and
#: the words that are not a name, because every chunk begins with some of them.
_FIRST_NAME = re.compile(r"[A-Za-z_][\w.]{3,}")
_NOT_A_NAME = frozenset({
    "local", "function", "return", "pcall", "tostring", "tonumber", "then", "else",
    "elseif", "false", "true", "while", "repeat", "until", "break", "ipairs", "pairs",
    "table", "string", "math", "type", "select", "error", "assert", "unpack", "next",
})


def _child_of(chunk: str) -> str:
    """Which child tool a socket call came from, as far as the chunk can say (#2404).

    Two thirds of the calls measured came through the door the spawned tools use
    (`_serve`), and a thread name cannot tell them apart — the pool names its workers by
    number. The chunk can: every one of these starts by naming the manager or the field
    it is after, so the first identifier in it groups a tool's traffic under something a
    person can act on. Cut short deliberately: a whole chunk carries uuids and names, and
    this is a histogram key, not a record of what was asked.
    """
    for found in _FIRST_NAME.finditer(chunk or ""):
        word = found.group(0)
        if word.lower() in _NOT_A_NAME:
            continue
        return "child:" + word[:32]
    return "child:?"


#: How often the three-way split of a chunk's cost is written to `debug.log` (#2404).
#: A minute, and only when calls have been made since the last line: it is the evidence
#: behind «the claim is held for a whole run, and almost none of that is exclusive», and
#: a number nobody can read is a number nobody will check.
TIMING_SAY_SEC = 60.0


def _daemon_module():
    """`tools/lua_daemon.py`, imported lazily — it is the VM half, not the protocol.

    Lazy because it drags in the lease and the pulse, and because a test of the panel
    that never touches the game should not need either. `tools/` is on `sys.path`
    already (`panel/runtime/paths.py`); the fallback is for a bare harness.
    """
    try:
        import lua_daemon                              # noqa: PLC0415
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, os.path.join(here, "tools"))
        import lua_daemon                              # noqa: PLC0415
    return lua_daemon


class LocalClient:
    """`lua_client.DaemonClient`'s surface, served in-process by a :class:`LuaService`.

    Everything in the panel that drives the game already speaks this shape, so the whole
    change of «the panel is the daemon» reaches those callers as a different object with
    the same methods — and one that costs a function call instead of a socket.

    The token lives on the client, exactly as it does for the socket version: a panel
    holding four profiles holds four rights to drive four clients, and an environment
    variable could never get that right (#1206).
    """

    def __init__(self, service: "LuaService", token: str = "") -> None:
        self._service = service
        self.token = token or ""

    @property
    def port(self) -> int:
        return self._service.port

    # -- driving the game ----------------------------------------------------
    def run(self, chunk: str, marker=None, settle: float = 1.2, early: bool = False,
            sentinel: "str | None" = None):
        return self._service.run(chunk, marker=marker, settle=settle, early=early,
                                 sentinel=sentinel, token=self.token)

    # -- readings ------------------------------------------------------------
    def ping(self) -> bool:
        return True                     # this object cannot exist without the service

    def status(self) -> dict:
        return self._service.status()

    def target_pid(self) -> "int | None":
        return self._service.target_pid()

    # -- the lease -----------------------------------------------------------
    def acquire(self, owner: str, ttl: float = 120.0) -> "str | None":
        reply = self._service.lease.acquire(owner, ttl, self.token or None)
        self.token = (reply.get("token") or "") if reply.get("ok") else self.token
        return self.token if reply.get("ok") else None

    def renew(self) -> bool:
        return bool(self.token) and bool(self._service.lease.renew(self.token).get("ok"))

    def release(self) -> bool:
        if not self.token:
            return True
        try:
            return bool(self._service.lease.release(self.token).get("ok"))
        finally:
            self.token = ""

    def lease_state(self) -> dict:
        return self._service.lease.state() or {}

    # -- the two ops that no longer mean anything ----------------------------
    def reload(self) -> dict:
        self._service.reattach()
        return {"ok": True}

    def shutdown(self) -> dict:
        """Refused: this «daemon» is the panel, and closing it is a person's press."""
        return {"ok": False, "error": "the panel holds the link; it does not shut down"}

    def close(self) -> None:
        """No-op — the service outlives every client object made against it."""


class LuaService:
    """One warm `LuaEval` for this Windows session's client, and the door children use.

    Built lazily: nothing is attached until something asks the game a question or the
    watch thread's first probe comes due, so opening a panel on a machine with no client
    running costs nothing.
    """

    def __init__(self, host: str = "", log=None, debug=None) -> None:
        self._host = host or lua_client.HOST
        # THE SINKS ARE A LIST, NOT THE FIRST PROFILE'S (#2660). One Windows session holds
        # one client, so every profile open on it shares this service — and it used to
        # keep whichever profile happened to attach first, which meant «порт занят» about
        # a client THREE accounts drive was written into ONE account's log, and the other
        # two were told nothing. A fact about the shared link belongs in every log that
        # shares it; the machine's own debug file gets it too, because the service is the
        # window's rather than an account's (`CLAUDE.md`, «A profile is a whole panel»).
        self._logs: list = [log] if log is not None else []
        self._dbgs: list = [debug] if debug is not None else []
        self._log, self._dbg = log, debug
        self._mod = _daemon_module()
        self._daemon = self._mod.Daemon()
        # …AND ITS DIAGNOSIS GOES INTO THE LOG, NOT INTO A CLOSED HANDLE (#2060). The
        # `Daemon` says why an attach or a probe failed by printing, which is right for
        # the standalone connector and worthless here: a panel started detached has no
        # stdout, so live on 2026-08-28 a profile said «45 probes in a row … attaching
        # again» 859 times across 6.9 hours while the sentence naming the cause was
        # thrown away every single time.
        self._daemon.say = self._relay
        self._ports: dict = {}                    # port -> the listening socket
        self._lock = threading.Lock()
        self._watching = False
        #: The last thing an attach said, for the amber that has to name a cause.
        self._error = ""
        #: …and what has already been said about it, so a standing failure is one line.
        self._said = ""
        #: WHEN A CLIENT WAS FIRST SEEN WITH NOTHING HELD (#1976) — the start of the one
        #: number the person judges this panel by: «I started the game, how long until it
        #: works». Stamped by the watch, read once by whoever announces green.
        self._seen_at: "float | None" = None
        #: The last `CallTimes` snapshot written to the log, and when (#2404).
        self._timing_was: dict = {}
        self._timing_at = time.monotonic()
        #: …and the same for the hijack's own phases (:meth:`_say_hijack`).
        self._hijack_was: dict = {}

    # -- the connection ------------------------------------------------------
    @property
    def port(self) -> int:
        """Any port this service answers on — the first one bound. For an endpoint key."""
        return next(iter(self._ports), 0)

    @property
    def lease(self):
        return self._daemon.lease

    @property
    def pulse(self):
        return self._daemon.pulse

    def listen(self, port: int) -> bool:
        """Bind ``port`` for the child tools, and start the watch. Idempotent.

        A port that cannot be bound is not fatal and never was: the panel drives the game
        in-process either way, and what is lost is the children's door. It is said once.
        """
        port = int(port)
        with self._lock:
            if port in self._ports:
                return True
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # SO_REUSEADDR on Windows lets a second bind STEAL a live port, which would
            # route one profile's calls into another account's game.
            srv.setsockopt(socket.SOL_SOCKET,
                           getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
            bound = self._bind(srv, port)
            if not bound:
                # SOMETHING IS ALREADY ON IT, and after #1911 that is almost always a
                # daemon of the OLD architecture: it outlived the panel that started it,
                # exactly as it was built to, and it is now an orphan holding the door
                # this profile's child tools come through. It answers the protocol, so
                # it can be asked to go — politely, once — and the bind retried.
                self._retire(port)
                bound = self._bind(srv, port)
            if not bound:
                srv.close()
                self._say_once(f"port {port} is held by something else",
                               "log.link.port_taken", port=port)
                return False
            srv.listen(8)
            self._ports[port] = srv
        threading.Thread(target=self._accept, args=(srv,), daemon=True).start()
        self._watch()
        self._note("listening on %s:%s for the child tools", self._host, port)
        return True

    def _bind(self, srv: socket.socket, port: int) -> bool:
        """Take the port, waiting out a listener that is on its way out."""
        for _ in range(BIND_TRIES):
            try:
                srv.bind((self._host, port))
                return True
            except OSError:
                time.sleep(BIND_WAIT)
        return False

    def _retire(self, port: int) -> None:
        """Ask whatever is on this port to go. Best effort, and never an error.

        The one thing that CAN be there and should not: a daemon from before the panel
        held its own link. It speaks this protocol and its `shutdown` is honoured, so
        the door comes free without anybody killing a process by hand — and a listener
        that is something else entirely simply ignores an unknown line.
        """
        try:
            lua_client.DaemonClient(port=port, token="").shutdown()
        except Exception:                             # noqa: BLE001 — a courtesy
            return
        self._note("asked the listener on port %s to let it go", port)
        time.sleep(BIND_WAIT)

    def forget(self, port: int) -> None:
        """Let a port go — a profile was closed, or its port setting moved."""
        with self._lock:
            srv = self._ports.pop(int(port), None)
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass

    def stop(self) -> None:
        """Close every door and let the client go. The panel is shutting down."""
        for port in list(self._ports):
            self.forget(port)
        try:
            self._daemon.close()
        except BaseException:                         # noqa: BLE001 — leaving anyway
            pass

    # -- driving the game ----------------------------------------------------
    def run(self, chunk: str, marker=None, settle: float = 1.2, early: bool = False,
            sentinel: "str | None" = None, token: "str | None" = None):
        """One chunk, through the same lock and the same lease a child's `run` uses."""
        refused = self.lease.check_run(token)
        if refused:
            raise lua_client.LeaseLost(refused)
        times = self._daemon.times
        who = _caller(threading.current_thread().name)
        if who == "thread:_serve":
            who = _child_of(chunk)
        times.who[who] = times.who.get(who, 0) + 1
        if not (token or "").strip():
            # AN UNLEASED CALL IS LET THROUGH — that is the gate's own rule, and it is
            # the one way a chunk reaches the client beside whoever holds the claim
            # (`tools/lib/game_lease.py::check_run`). Counted rather than stopped: this
            # is a measurement of who is in the queue, not a new refusal (#2404).
            times.unleased += 1
            times.by[who] = times.by.get(who, 0) + 1
        try:
            lines = self._daemon.run(chunk, marker, float(settle), early=early,
                                     sentinel=sentinel)
        except self._mod.ClientUnreachable as exc:
            self._error = str(exc)
            raise lua_client.ClientGone(str(exc)) from exc
        except BaseException as exc:                  # noqa: BLE001 — the caller's chunk
            self._error = f"{type(exc).__name__}: {exc}"
            raise
        self._error = ""
        return lines

    def reattach(self) -> bool:
        """Let the client go and take hold of it again. ``True`` if it worked."""
        try:
            self._daemon.reload()
        except BaseException as exc:                  # noqa: BLE001 — a state, not a crash
            self._error = f"{type(exc).__name__}: {exc}"
            self._note_warn("could not attach: %s", exc)
            return False
        self._error = ""
        return True

    # -- readings ------------------------------------------------------------
    def status(self) -> dict:
        """What a `{"op":"ping"}` used to answer, from the object rather than the wire."""
        return {"ok": True, "warm": self._daemon.is_warm(),
                "pid": self._daemon.target_pid(), "self": os.getpid(),
                "panel": True, "lease": self.lease.state(),
                "calls": self._daemon.times.state(), **self.pulse.state()}

    def target_pid(self) -> "int | None":
        return self._daemon.target_pid()

    def traffic_age(self) -> "float | None":
        """Seconds since a chunk last came back out of the game, or ``None``."""
        return self.pulse.age()

    def error(self) -> str:
        """Why nothing lands, in the words of whatever refused it. ``""`` while it does."""
        return self._error or str(self.pulse.state().get("probe_error") or "")

    # -- the watch -----------------------------------------------------------
    def _watch(self) -> None:
        if self._watching:
            return
        self._watching = True
        threading.Thread(target=self._watch_loop, daemon=True).start()

    def _watch_loop(self) -> None:
        """Follow the client, prove the link, and rebuild when it cannot be proved.

        The daemon's own watch, minus the one thing it did that a panel may not: leaving.
        Three failed probes there meant «let go of the port and die, the panel will start
        a fresh one»; here it means «drop the evaluator and attach again», which is the
        same cure with the process kept.
        """
        while True:
            time.sleep(CATCH_SEC if self.catching() else WATCH_SEC)
            try:
                self._daemon.follow_client()
                self._daemon.heartbeat()
                if self.pulse.should_leave():
                    self._note_warn("%s probes in a row did not reach the client — "
                                    "attaching again", self.pulse.misses())
                    self.reattach()
            except BaseException as exc:              # noqa: BLE001 — never the last word
                self._note_warn("watch: %s", exc)
            self._mark_seen()
            try:
                self._say_timing()
            except BaseException as exc:              # noqa: BLE001 — a diagnostic
                # A LINE ABOUT THE WORK MAY NEVER STOP THE WORK. This runs OUTSIDE the
                # try above, on the thread that follows the client, probes the link and
                # rebuilds the attach — so a counter that raised would take the whole
                # watch down and the panel would sit there with a client it never
                # re-attached to.
                self._note_warn("timing line failed: %s", exc)

    def _say_timing(self) -> None:
        """Write the last minute's calls to `debug.log`, split three ways (#2404).

        A DELTA, not a total: the interesting question is what a call costs NOW, and a
        cumulative mean over a panel that has been open for a day answers a different one.
        Silent when nothing was called, so an idle profile does not write a line a minute
        saying it did nothing.
        """
        now = time.monotonic()
        was, at = self._timing_was, self._timing_at
        if now - at < TIMING_SAY_SEC:
            return
        self._timing_at = now
        state = self._daemon.times.state()
        self._timing_was = state
        n = state["n"] - (was.get("n", 0) if was else 0)
        if n <= 0:
            return
        def moved(key: str) -> float:
            return state[key] - (was.get(key, 0.0) if was else 0.0)
        wait, inject, harvest = moved("wait"), moved("inject"), moved("harvest")
        total = wait + inject + harvest
        queued = state["queued"] - (was.get("queued", 0) if was else 0)
        unleased = state["unleased"] - (was.get("unleased", 0) if was else 0)
        self._note("calls %d in %.0fs: %.2fs total (%.3f s/call) = "
                   "wait %.2f + inject %.2f + harvest %.2f; exclusive %.0f%%; "
                   "found %.2f already in flight, %d unleased, busiest %d",
                   n, now - at, total, total / n, wait, inject, harvest,
                   100.0 * (inject / total) if total else 0.0,
                   queued / n, unleased, state["busiest"])
        self._say_hijack(now - at)
        self._note("callers: %s", ", ".join(
            f"{who}={n}" for who, n in sorted(
                self._delta(state, was, "who").items(), key=lambda kv: -kv[1])[:12]))
        if unleased:
            self._note("…of which unleased: %s", ", ".join(
                f"{who}={n}" for who, n in sorted(
                    self._delta(state, was, "by").items(),
                    key=lambda kv: -kv[1])[:8]))

    def _say_hijack(self, secs: float) -> None:
        """Where the seconds of the INJECTION went, phase by phase (#2404).

        The injection is the only genuinely exclusive part of a call and it costs five to
        ten times what the chain is supposed to — two frames per hijack, ~34 ms at the 60
        fps this client reports. So the hijack counts its own phases
        (`tools/lib/hijack_call.py::STATS`) and this prints the minute's delta beside the
        call line: parking the target thread, waiting for the shellcode to start, the
        managed call itself, and letting the RWX region go.

        `tries` is the number of times the game's MAIN THREAD was suspended and resumed
        to look at its RIP. It is the one number here that costs the CLIENT something as
        well as us, and if the park is where the seconds are, it is also the count that
        says why.
        """
        try:
            import hijack_call                        # noqa: PLC0415
            now = hijack_call.stats()
        except Exception:                             # noqa: BLE001 — a reading
            return
        was, self._hijack_was = self._hijack_was, now
        if not was:
            return
        n = now["n"] - was["n"]
        if n <= 0:
            return
        def moved(key: str):
            return now[key] - was[key]
        park, start = moved("park_sec"), moved("start_sec")
        call, free = moved("call_sec"), moved("free_sec")
        total = park + start + call + free
        self._note("hijacks %d in %.0fs: %.2fs (%.3f s/hijack) = park %.2f + start %.2f "
                   "+ call %.2f + free %.2f; %.1f park tries each, %d gave up",
                   n, secs, total, total / n, park, start, call, free,
                   moved("park_tries") / n, moved("misses"))
        # …AND WHOSE THEY WERE (#2656). The line above sizes the exposure; this one
        # addresses it. Every label, not a top few: the tail is where a caller that
        # attaches three times for one answer hides, and `tools/hijack_tally.py` adds a
        # day of these up. The whole line is one debug entry a minute.
        by = self._delta(now, was, "by_label")
        if by:
            self._note("hijack labels %.0fs: %s", secs, " ".join(
                f"{name}={count}" for name, count in
                sorted(by.items(), key=lambda kv: -kv[1])))

    @staticmethod
    def _delta(state: dict, was: dict, key: str) -> dict:
        """Which callers appear in ``key`` SINCE the last line, and how often."""
        before = (was or {}).get(key) or {}
        now = state.get(key) or {}
        return {who: n - before.get(who, 0) for who, n in now.items()
                if n - before.get(who, 0) > 0}

    def catching(self) -> bool:
        """Is there something to catch — i.e. is nothing held? Then look again soon."""
        return not self._daemon.is_warm()

    def _mark_seen(self) -> None:
        """Keep the stamp the «how long did it take» line is measured from.

        Set when a client is there and nothing is held; cleared when the client is not
        there at all, so a client that comes back an hour later is timed from ITS OWN
        appearance rather than from the last one. Never cleared merely by attaching: the
        number is about GREEN, and green is the game server answering, which happens some
        seconds after the hold is taken.
        """
        if self._daemon.is_warm():
            return
        try:
            there = self._daemon.client_present()
        except BaseException:                         # noqa: BLE001 — a reading
            return
        if not there:
            self._seen_at = None
        elif self._seen_at is None:
            self._seen_at = time.monotonic()

    def take_wait(self) -> "float | None":
        """Seconds since the client appeared — ONCE, then ``None`` until it appears again.

        Consumed by whoever says the line, so «связь поднялась за N с» is said once per
        appearance however many times the light is repainted.
        """
        at, self._seen_at = self._seen_at, None
        return None if at is None else time.monotonic() - at

    # -- the door the child tools come through -------------------------------
    def _accept(self, srv: socket.socket) -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return                                # the port was let go
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        """`lua_daemon._handle`, with `shutdown` refused and nothing that can exit."""
        f = conn.makefile("rwb")
        try:
            for raw in f:
                try:
                    req = json.loads(raw.decode("utf-8", "replace"))
                except Exception:                     # noqa: BLE001
                    f.write(b'{"ok":false,"error":"bad json"}\n')
                    f.flush()
                    continue
                f.write((json.dumps(self._answer(req)) + "\n").encode("utf-8"))
                f.flush()
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _answer(self, req: dict) -> dict:
        op = req.get("op", "run")
        try:
            if op == "ping":
                return self.status()
            if op == "run":
                lines = self.run(req.get("chunk", ""), req.get("marker"),
                                 float(req.get("settle", 1.2)),
                                 early=bool(req.get("early")),
                                 sentinel=req.get("sentinel"), token=req.get("token"))
                return {"ok": True, "lines": lines}
            if op == "acquire":
                return self.lease.acquire(req.get("owner", "?"),
                                          req.get("ttl", self._mod.DEFAULT_LEASE_TTL),
                                          req.get("token"))
            if op == "renew":
                return self.lease.renew(req.get("token"))
            if op == "release":
                return self.lease.release(req.get("token"))
            if op == "reload":
                return {"ok": self.reattach(), "warm": self._daemon.is_warm()}
            if op == "shutdown":
                return {"ok": False,
                        "error": "the panel holds the link; it does not shut down"}
            return {"ok": False, "error": f"unknown op {op!r}"}
        except lua_client.LeaseLost as exc:
            return {"ok": False, "error": str(exc), "lease_lost": True}
        except lua_client.ClientGone as exc:
            return {"ok": False, "error": str(exc), "client_gone": True}
        except BaseException as exc:                  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # -- diagnostics ---------------------------------------------------------
    def add_sinks(self, log=None, debug=None) -> None:
        """Another profile started driving this client: it hears about it too."""
        if log is not None and log not in self._logs:
            self._logs.append(log)
            if self._log is None:
                self._log = log
        if debug is not None and debug not in self._dbgs:
            self._dbgs.append(debug)
            if self._dbg is None:
                self._dbg = debug

    def _say_once(self, fingerprint: str, key: str, **fmt) -> None:
        logs = tuple(getattr(self, "_logs", None) or ())
        if not logs and getattr(self, "_log", None) is not None:
            logs = (self._log,)
        if self._said == fingerprint or not logs:
            return
        self._said = fingerprint
        for log in logs:
            try:
                log.say("link", key, **fmt)
            except Exception:            # noqa: BLE001 — one closed profile, never the link
                pass

    def _relay(self, msg: str) -> None:
        """One line the `Daemon` wanted to print, put where a person can read it (#2060).

        Warning rather than info: everything it says is a refusal or a hand-over, and the
        one thing this had to end is a standing failure with no cause anywhere in the log.
        """
        self._note_warn("%s", str(msg).replace("[daemon] ", ""))

    def _sinks(self) -> tuple:
        """Every debug sink this link writes to — the window's own when there is none.

        `getattr` because a service can be built without `__init__` (a test that wants
        one method), and a diagnosis is the last thing that may raise.
        """
        wired = tuple(getattr(self, "_dbgs", None) or ())
        one = getattr(self, "_dbg", None)
        if not wired and one is not None:
            wired = (one,)
        return wired or (_panel_dbg(),)

    def _note(self, msg, *args) -> None:
        for dbg in self._sinks():
            _quietly(dbg.info, msg, *args)

    def _note_warn(self, msg, *args) -> None:
        for dbg in self._sinks():
            _quietly(dbg.warning, msg, *args)


def _quietly(call, msg, *args) -> None:
    """Say it, and never let a closed profile's handler out into the link."""
    try:
        call(msg, *args)
    except Exception:                    # noqa: BLE001
        pass


def _panel_dbg():
    """The WINDOW's own debug file — where a link with no profile attached yet writes."""
    from .. import debug_log
    return debug_log.panel_logger("link")


#: The one attach this process has. A Windows session holds one client, so every profile
#: open on it shares this — and with it the run lock and the lease, which is precisely
#: what keeps two profiles pointed at one game taking turns.
_LOCAL: "LuaService | None" = None
_LOCAL_LOCK = threading.Lock()


def local(log=None, debug=None) -> LuaService:
    """This process's service, made on first use — and told about every profile.

    The sinks are ADDED rather than dropped (#2660): the second profile to drive this
    client used to be silently written out of the link's commentary, which is how «нет
    связи» could be diagnosed in a log the person was not reading.
    """
    global _LOCAL
    with _LOCAL_LOCK:
        if _LOCAL is None:
            _LOCAL = LuaService(log=log, debug=debug)
        else:
            _LOCAL.add_sinks(log=log, debug=debug)
        return _LOCAL


def current() -> "LuaService | None":
    """The process's service IF one has been made — never makes one.

    The reading half. A light, a gate or a claim asking «how long ago did a chunk land»
    must not be the thing that attaches to a client or binds a port: a reading with a
    side effect is how a test binds 47654 and how a drawer pays for an attach (#1911).
    """
    return _LOCAL


def forget_local() -> None:
    """Drop the process's service — for a test, and for a panel on its way out."""
    global _LOCAL
    with _LOCAL_LOCK:
        service, _LOCAL = _LOCAL, None
    if service is not None:
        service.stop()
