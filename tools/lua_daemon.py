r"""Persistent warm-LuaEval daemon — keeps the hijack/il2cpp resolution hot.

`LuaEval.__init__` resolves the xLua facade through a thread hijack (~seconds); running
every panel click as a new process pays that each time. This daemon builds ONE `LuaEval`
and serves `run` requests over a local TCP socket, so a client executes a Lua chunk in the
time of a single SafeDoString invoke.

Protocol — newline-delimited JSON on 127.0.0.1:47654 (see tools/lua_client.py):
    {"op":"run","chunk":"<lua>","marker":"X","settle":1.2}  -> {"ok":true,"lines":[...]}
    …plus optional "early":true — `settle` becomes a DEADLINE and the answer comes
    back as soon as the marker has landed (tools/lib/lua_eval.py `collect`)
    {"op":"ping"}     -> {"ok":true,"warm":<bool>,"pid":<client pid>,"self":<own pid>}
    {"op":"reload"}   -> rebuild the LuaEval (after a game restart) -> {"ok":true}
    {"op":"shutdown"} -> {"ok":true} then exit
    {"op":"acquire","owner":"panel/rally","ttl":120} -> {"ok":true,"token":"…"}
                                                     |  {"ok":false,"busy":"…","held_sec":8.2}
    {"op":"renew","token":"…"}    -> {"ok":true}
    {"op":"release","token":"…"}  -> {"ok":true}

Calls are serialized by a lock (the game hijack is not reentrant). A failing invoke — e.g.
the game restarted and the cached per-pid addresses are stale — triggers one automatic
rebuild-and-retry.

THE LEASE (acquire/renew/release) is a coarser thing than that per-call lock: an *action*
is many chunks over seconds, and two of them must not interleave in the game. The panel
used to hold that as a process-wide flag, which stopped being enough the moment a single
tab could be launched as its own process (docs/research/panel-tabs-refactor.md §7) — two
windows, two flags, one game. Four properties, each load-bearing:

  * A lease excludes other LEASES, never a plain `run`. The read-only tabs and the account
    poll drive the VM without claiming anything and always have; making them wait behind a
    recipe would freeze the dashboard for the length of every action.
  * A lease EXPIRES. `ttl` seconds without a renew and it is dropped, so a client that
    died mid-action cannot wedge the game until someone restarts this daemon. Every `run`
    carrying the token renews it, so a working action never expires under itself.
  * A `run` carrying a token that is NOT the live lease is REFUSED. That is the case where
    an action's lease expired and somebody else took it: the right answer is to stop, not
    to interleave with whoever holds it now.
  * Re-acquiring with a token that is already yours returns it unchanged, so a nested
    claim inside one owner cannot deadlock against itself. Children inherit the token
    through LW_GAME_LEASE, which is what keeps auto-loot from deadlocking against the
    tool it spawns.

Run under the Windows Python:

    C:\Python312\python.exe tools\lua_daemon.py
    C:\Python312\python.exe tools\lua_daemon.py --port 47655   # second client, own session

One daemon per client: a second Windows session runs its own daemon on its own port and
attaches to the client of *that* session (`LW_GAME_PID` / same-session preference in
`il2cpp_probe.find_game_pid`). See tools/rdp_instance.py and
docs/research/multi-instance-rdp.md.

IT FOLLOWS ITS CLIENT ACROSS A RESTART BY ITSELF (#1286). A client is restarted several
times an hour here — by the watchdog, by `actions/restart_game.md`, by a person — and
every restart leaves this daemon holding a process id that no longer exists. It used to
sit there until something drove it into a call that failed twice over; measured live,
that state lasted half an hour at a time while the panel reported a warm daemon. So
`follow_client` watches the pid it holds and, the moment that process is gone, lets go
and takes hold of the client that replaced it. Nothing outside has to notice, ask or
restart anything.
"""
from __future__ import annotations
import argparse
import json
import os
import socket
import sys
import threading
import time

# Absolute, not "tools/lib": resolve regardless of the launcher's cwd.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import lua_client  # HOST/PORT only — lightweight
from game_lease import DEFAULT_TTL as DEFAULT_LEASE_TTL, Lease


#: How often the daemon checks that the client it holds is still a running process.
#: Five seconds: a client restart takes the better part of a minute to come back, so
#: this is never the slow part, and the check itself is one `psutil.Process` lookup.
CLIENT_WATCH_SEC = 5.0

#: How long a shutdown is given to close the evaluator tidily before the process leaves
#: anyway. THE ANSWER TO `shutdown` USED TO BE THE ONLY THING GUARANTEED TO HAPPEN: the
#: close takes the run lock, and a call wedged against a dead client holds it for ever,
#: so the daemon acknowledged the shutdown and never exited — leaving the port bound and
#: the panel reading a corpse as «already warm» (#1286).
EXIT_GRACE_SEC = 1.0

class ClientUnreachable(RuntimeError):
    """This daemon cannot get at the client it is meant to drive (#1266).

    NOT a bad chunk and not a game that refused something — the far end of the link is
    gone. It is raised after the rebuild has already been tried, so by the time a caller
    sees it the daemon has done everything it can by itself.

    It exists because of what the panel used to be told instead: `SystemExit: snapshot
    failed err=5`, the raw words of a Windows call inside `il2cpp_probe`, which reads as
    a bug in the toolkit rather than as «the client is not there any more». A whole
    evening's timers reported that and nothing anywhere concluded the obvious
    (docs/research/server-link-status.md §2.2). The wire carries a `client_gone` flag
    beside the text so `lua_client` does not have to recognise a sentence.
    """


class Daemon:
    def __init__(self):
        self._lock = threading.Lock()
        self._ev = None
        self.lease = Lease(on_expire=lambda owner, held: print(
            f"[daemon] lease of {owner!r} expired after {held:.0f}s — dropped",
            flush=True))

    def _ensure(self):
        # LuaEval is imported here, not at module scope: it drags the il2cpp stack in,
        # which keeps this module out of reach of anything that only wants to speak the
        # protocol (the lease test, a tool checking whether a daemon is up).
        if self._ev is None:
            self._repin()
            from lua_eval import LuaEval
            self._ev = LuaEval()
        return self._ev

    @staticmethod
    def _repin() -> None:
        """Follow the pinned client across a restart, without ever crossing sessions.

        ``--pid`` / ``LW_GAME_PID`` say WHICH client this daemon serves. That pin is a
        process id, and a restarted client is a NEW process id — after which
        `find_game_pid` refuses outright ("LW_GAME_PID=… is not running") and this
        daemon can never attach to anything again. A daemon pinned by hand was
        therefore a daemon that could not survive actions/restart_game.md at all.

        Dropping the pin outright would be worse than the disease: with two accounts
        on one box, `find_game_pid` falls back to "any client" and would attach this
        daemon to the OTHER session's game. So the pin is re-aimed rather than
        removed — at the client of this daemon's own Windows session, which is the
        same client one process later — and when there is no such client, or more
        than one, the stale pin is left exactly where it is. Failing loudly beats
        driving somebody else's account.
        """
        pinned = os.environ.get("LW_GAME_PID")
        if not pinned:
            return
        try:
            import game_client
            if game_client.alive(int(pinned)):
                return                                # still there — nothing to do
            same = game_client.session_pids()
        except BaseException as exc:                  # noqa: BLE001 — a best effort
            print(f"[daemon] could not re-aim the pinned pid: {exc}", flush=True)
            return
        if len(same) != 1:
            print(f"[daemon] pinned pid {pinned} is gone and this session has "
                  f"{len(same)} clients — leaving the pin alone", flush=True)
            return
        os.environ["LW_GAME_PID"] = str(same[0])
        print(f"[daemon] pinned pid {pinned} is gone — following this session's "
              f"client to pid {same[0]}", flush=True)

    def _drop(self):
        if self._ev is not None:
            try:
                self._ev.close()
            except BaseException:
                pass
            self._ev = None

    def reload(self):
        with self._lock:
            self._drop()
            self._ensure()

    def is_warm(self) -> bool:
        return self._ev is not None

    def target_pid(self) -> int | None:
        """Which client this daemon is attached to — the thing to check when two run."""
        return getattr(getattr(self._ev, "x", None), "pid", None)

    @staticmethod
    def _client_present() -> bool:
        """Is there a client of this session to attach to at all?

        Asked before an attach is attempted, so a daemon started on a machine with no
        game running does not build a `LuaEval` every few seconds for nothing. The pin
        answers first when there is one, and a pin that is dead does NOT mean absent:
        `_repin` re-aims it at this session's client, which is the whole case this
        watches for.
        """
        import game_client

        pinned = (os.environ.get("LW_GAME_PID") or "").strip()
        if pinned.isdigit() and game_client.alive(int(pinned)):
            return True
        return bool(game_client.session_pids())

    def follow_client(self) -> bool:
        """Let go of a client that has gone, and take hold of the one replacing it.

        `True` when this call attached to something. The daemon is pinned to a process
        id and a restarted client is a NEW one, so without this the daemon holds a dead
        pid until a call drives it into `run`'s rebuild — and if that rebuild fails, for
        ever after that (#1286). The panel could restart the daemon for it, and does as
        a last resort, but a daemon that follows its own client needs nobody's help and
        is right within five seconds rather than within two status polls.

        NEVER WAITS FOR THE RUN LOCK. A call in flight is the ordinary case and its
        client is by definition alive; a call WEDGED holds the lock for ever, and the
        one thing this must not become is a second thread stuck behind it. It simply
        tries again on the next tick, and the panel's `_kill` is what ends a daemon that
        is past helping.
        """
        try:
            import game_client

            pid = self.target_pid()
            if pid is not None and game_client.alive(pid):
                return False                          # the ordinary case: nothing to do
            if not self._client_present():
                return False                          # no client yet: nothing to hold
        except BaseException:                         # noqa: BLE001 — cannot ask ⇒ leave it
            return False
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if pid is not None:
                print(f"[daemon] the client at pid {pid} is gone — letting go", flush=True)
            self._drop()
            self._ensure()
        except BaseException as exc:                  # noqa: BLE001 — it may still be booting
            print(f"[daemon] no client to attach to yet: {exc}", flush=True)
            return False
        finally:
            self._lock.release()
        print(f"[daemon] attached to pid {self.target_pid()}", flush=True)
        return True

    def run(self, chunk: str, marker, settle: float, early: bool = False,
            sentinel: "str | None" = None):
        with self._lock:
            for attempt in (1, 2):
                try:
                    return self._ensure().run(chunk, marker=marker, settle=settle,
                                              early=early, sentinel=sentinel)
                except BaseException as exc:
                    # Stale handle (game restarted?) or transient hijack failure —
                    # drop the warm state and rebuild once before giving up.
                    self._drop()
                    if attempt == 2:
                        raise self._verdict(exc) from exc

    def _verdict(self, exc: BaseException) -> BaseException:
        """The failure to hand back once the rebuild has failed too.

        THE CLIENT IS ASKED ABOUT, not guessed at from the words of the error. A run that
        fails twice over is either a chunk this VM would not run — which is the author's
        problem and must keep its own message — or a client that cannot be reached, which
        is nobody's chunk and everybody's link. The pin says which process this daemon
        serves and the machine says whether it is still there; between them there is no
        need to read `err=5` and hope.

        An unanswerable question stays the original error: this may only ever ADD a
        verdict, never replace a real one with a guess.
        """
        pin = (os.environ.get("LW_GAME_PID") or "").strip()
        try:
            import game_client
            # The pin is the answer when there is one — it names THIS daemon's client,
            # and on a box with two accounts the other session's is not a substitute.
            gone = (not game_client.alive(int(pin))) if pin.isdigit() \
                else (not game_client.session_pids())
        except BaseException:                         # noqa: BLE001 — cannot ask ⇒ keep it
            return exc
        if not gone:
            # A client that IS there and still cannot be attached to is a different
            # fault — rights, a hijack that lost its race — and calling it «the client
            # is gone» would be the same kind of lie in the other direction.
            return exc
        return ClientUnreachable(
            f"the client this daemon drives is gone (pid {pin or '?'}); the link is "
            f"dead, not the chunk — restart the client, then this daemon "
            f"[{type(exc).__name__}: {exc}]")

    def close(self):
        with self._lock:
            self._drop()


def _leave(daemon: Daemon) -> None:
    """Exit. Tidily if the evaluator can be closed, and regardless if it cannot.

    THE PROCESS LEAVING IS THE POINT, and closing the evaluator is only good manners on
    the way out. `Daemon.close` takes the run lock, and a call wedged against a client
    that has gone holds that lock for ever — so the polite path used to reply
    `{"ok":true}`, block on the close, and never reach `os._exit`. From outside that is
    indistinguishable from a healthy daemon: the port stays bound and answers, which is
    all `up()` ever meant, and the panel reported «already warm» over it for half an
    hour (#1286).

    The timer is what makes the guarantee unconditional: whatever the close does, this
    process is gone :data:`EXIT_GRACE_SEC` later. It is armed BEFORE the close for the
    same reason — a promise made after the thing that can block is not a promise.
    """
    threading.Timer(EXIT_GRACE_SEC, os._exit, args=(0,)).start()
    try:
        daemon.close()
    except BaseException:                             # noqa: BLE001 — leaving either way
        pass
    os._exit(0)


def _watch_client(daemon: Daemon, every: float = CLIENT_WATCH_SEC) -> None:
    """Ask `follow_client` every few seconds, for ever. Started as a daemon thread."""
    while True:
        time.sleep(every)
        try:
            daemon.follow_client()
        except BaseException as exc:                  # noqa: BLE001 — never the last word
            print(f"[daemon] client watch: {exc}", flush=True)


def _handle(conn: socket.socket, daemon: Daemon) -> None:
    f = conn.makefile("rwb")
    try:
        for raw in f:
            try:
                req = json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                f.write(b'{"ok":false,"error":"bad json"}\n'); f.flush(); continue
            op = req.get("op", "run")
            try:
                if op == "ping":
                    # `self` is this daemon's OWN pid, and it is here because nothing
                    # outside can work it out: a daemon in another Windows session is
                    # not in the asker's process list. It is what ends a daemon that
                    # acknowledges a shutdown without carrying it out (#1286).
                    resp = {"ok": True, "warm": daemon.is_warm(),
                            "pid": daemon.target_pid(),
                            "self": os.getpid(),
                            "lease": daemon.lease.state()}
                elif op == "run":
                    # The lease gate runs BEFORE the evaluator: a caller whose lease
                    # went away must be told so, not quietly executed beside its
                    # successor.
                    refused = daemon.lease.check_run(req.get("token"))
                    if refused:
                        resp = {"ok": False, "error": refused, "lease_lost": True}
                    else:
                        lines = daemon.run(req.get("chunk", ""), req.get("marker"),
                                           float(req.get("settle", 1.2)),
                                           early=bool(req.get("early")),
                                           sentinel=req.get("sentinel"))
                        resp = {"ok": True, "lines": lines}
                elif op == "acquire":
                    resp = daemon.lease.acquire(req.get("owner", "?"),
                                                req.get("ttl", DEFAULT_LEASE_TTL),
                                                req.get("token"))
                elif op == "renew":
                    resp = daemon.lease.renew(req.get("token"))
                elif op == "release":
                    resp = daemon.lease.release(req.get("token"))
                elif op == "reload":
                    daemon.reload(); resp = {"ok": True, "warm": daemon.is_warm()}
                elif op == "shutdown":
                    f.write(b'{"ok":true}\n'); f.flush(); _leave(daemon)
                else:
                    resp = {"ok": False, "error": f"unknown op {op!r}"}
            except ClientUnreachable as exc:
                # A flag beside the text, exactly as `lease_lost` is: the caller must be
                # able to tell «the link is gone» from «your chunk is wrong» without
                # matching sentences, and a sentence is what it had to match before.
                resp = {"ok": False, "error": str(exc), "client_gone": True}
            except BaseException as exc:
                resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            f.write((json.dumps(resp) + "\n").encode("utf-8")); f.flush()
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="warm-LuaEval daemon for one game client")
    ap.add_argument("--host", default=lua_client.HOST, help="bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=lua_client.PORT,
                    help=f"bind port (default {lua_client.DEFAULT_PORT}; "
                         f"a second session's client gets its own)")
    ap.add_argument("--pid", type=int, default=None,
                    help="attach to this LastWar.exe pid instead of picking one "
                         "(same as the LW_GAME_PID environment variable)")
    args = ap.parse_args()
    if args.pid:
        os.environ["LW_GAME_PID"] = str(args.pid)

    daemon = Daemon()
    try:
        daemon._ensure()
        print("[daemon] warm — LuaEval resolved", flush=True)
    except BaseException as exc:
        print(f"[daemon] not warm yet (game offline?): {exc}", flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR on Windows lets a second bind *steal* a live port — with one daemon
    # per client that would silently route a session's calls into the wrong game.
    srv.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE",
                                              socket.SO_REUSEADDR), 1)
    try:
        srv.bind((args.host, args.port))
    except OSError as exc:
        print(f"[daemon] cannot bind {args.host}:{args.port}: {exc} "
              f"(already running?)", file=sys.stderr)
        return 1
    srv.listen(8)
    print(f"[daemon] listening {args.host}:{args.port}", flush=True)
    # Started only once the port is ours: a daemon that could not bind is about to exit
    # and has no business re-aiming anything at a client it will never drive.
    threading.Thread(target=_watch_client, args=(daemon,), daemon=True).start()
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=_handle, args=(conn, daemon), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
