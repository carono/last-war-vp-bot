r"""The daemon proves its own link, and leaves when it cannot (task #1287).

Four properties, and each of them is a thing that went wrong live:

  * **a real errand is the proof.** Every run that comes back stamps the pulse, so a
    working daemon never probes at all and the guarantee costs nothing while the panel is
    busy;
  * **an idle daemon probes itself** — one trivial chunk — because «nothing has been asked
    of me» and «nothing I send arrives» look identical from outside, and for half an hour
    on 2026-08-07 they were the same reading;
  * **it never waits for the run lock to do it.** A call in flight is the ordinary case
    and its own success is the same proof; a call WEDGED holds the lock for ever, and a
    probe queued behind it would simply stop reporting — the age must grow instead;
  * **three failures in a row and it lets go of the port.** A daemon that cannot drive
    its client stops being a daemon rather than staying on as one that lies, which is
    what makes «the port answers» true again for every caller that only asks that much.

And the lock property the whole thing rides on: the injection is serialised, the WAIT is
not. Two calls whose answers take half a second each take half a second together.

No game and no Windows: the evaluator is a stand-in, exactly as in
`tests/test_daemon_lease.py`.

    C:\Python312\python.exe tests\test_daemon_heartbeat.py
    python3 tests/test_daemon_heartbeat.py
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import lua_daemon  # noqa: E402


class _Pending:
    def __init__(self, lines, delay: float = 0.0) -> None:
        self.lines, self.delay = lines, delay

    def harvest(self) -> list:
        if self.delay:
            time.sleep(self.delay)
        return self.lines


class _Eval:
    """A stand-in LuaEval. `fail` makes the injection raise, `answer` what comes back."""

    def __init__(self, answer=("X ok",), delay: float = 0.0) -> None:
        self.chunks: list = []
        self.answer, self.delay = list(answer), delay
        self.fail: "BaseException | None" = None

    def send(self, chunk, marker=None, settle=1.2, early=False, sentinel=None,
             private=False):
        if self.fail is not None:
            raise self.fail
        self.chunks.append(chunk)
        return _Pending(list(self.answer), self.delay)

    def close(self) -> None:
        pass


def _daemon(answer=("X ok",), delay: float = 0.0, client: bool = True):
    """A Daemon with the game stubbed out and no thread of its own running."""
    daemon = lua_daemon.Daemon()
    ev = _Eval(answer, delay)
    daemon._ev = ev
    # `_ensure`, not just `_ev`: the retry drops the evaluator and rebuilds, and a real
    # rebuild here goes looking for a game client — which is how an offline test ends up
    # reporting a dead link on a machine that has no game at all (#1282).
    daemon._ensure = lambda: ev                             # noqa: SLF001
    daemon._client_present = staticmethod(lambda: client)   # noqa: SLF001
    daemon._verdict = lambda exc: exc                       # noqa: SLF001
    return daemon, ev


# ---------------------------------------------------------------------------
# a real errand is the proof
# ---------------------------------------------------------------------------

def test_a_run_that_comes_back_stamps_the_pulse() -> None:
    daemon, _ = _daemon()
    assert daemon.pulse.age() is None, "nothing has landed yet"
    assert daemon.run("x()", "X", 0.1) == ["X ok"]
    assert daemon.pulse.age() is not None and daemon.pulse.age() < 1.0


def test_a_run_that_comes_back_empty_proves_nothing() -> None:
    """#1555: an empty run is not evidence, and it used to be stamped as success.

    The client hot-updated to encrypted Lua chunks; every `SafeDoString` failed and
    nothing ran for three hours, while the panel's own errands went on resetting the
    landing clock and the ping answered `warm, misses 0`. An empty run must leave the
    age exactly where it was — and must not be counted as a failure either, because a
    chunk that logs nothing legitimately returns nothing.
    """
    daemon, _ = _daemon(answer=[])
    assert daemon.run("silent()", "X", 0.1) == []
    assert daemon.pulse.age() is None, "nothing landed, so nothing may be stamped"
    assert daemon.pulse.misses() == 0, "…and an empty answer is not a strike either"


def test_an_empty_run_leaves_the_self_probe_due() -> None:
    """…so the one reading that CAN tell goes and asks. That is the whole cure."""
    daemon, ev = _daemon(answer=[])
    daemon.run("silent()", "X", 0.1)
    assert daemon.pulse.due(), "the age never moved, so a probe is owed"
    assert daemon.heartbeat() is False, "the probe knows what its own chunk prints"
    assert daemon.pulse.misses() == 1
    assert ev.chunks == ["silent()", lua_daemon.PROBE_CHUNK]


def test_a_working_daemon_never_probes() -> None:
    daemon, ev = _daemon()
    daemon.run("errand()", "X", 0.1)
    assert daemon.heartbeat() is True
    assert ev.chunks == ["errand()"], "the errand was the proof; no probe was needed"


def test_a_run_that_fails_twice_over_is_a_strike() -> None:
    daemon, ev = _daemon()
    ev.fail = RuntimeError("snapshot failed err=5")
    try:
        daemon.run("x()", "X", 0.1)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a failing injection must still raise")
    assert daemon.pulse.misses() == 1
    assert "snapshot" in (daemon.pulse.state().get("probe_error") or "")


# ---------------------------------------------------------------------------
# the self-probe
# ---------------------------------------------------------------------------

def test_an_idle_daemon_probes_itself() -> None:
    daemon, ev = _daemon(answer=["PULSE ok"])
    assert daemon.pulse.due(), "nothing has ever landed"
    assert daemon.heartbeat() is True
    assert ev.chunks == [lua_daemon.PROBE_CHUNK]
    assert daemon.pulse.age() is not None


def test_a_probe_that_cannot_be_sent_is_a_strike() -> None:
    daemon, ev = _daemon()
    ev.fail = RuntimeError("not running")
    assert daemon.heartbeat() is False
    assert daemon.pulse.misses() == 1


def test_a_probe_that_is_sent_and_answers_nothing_is_a_strike() -> None:
    """The injection worked and the game wrote nothing back — as unusable as a refusal."""
    daemon, _ = _daemon(answer=[])
    assert daemon.heartbeat() is False
    assert daemon.pulse.misses() == 1


def test_no_client_at_all_is_never_a_strike() -> None:
    """Otherwise a machine with the game closed collects strikes and the daemon loops."""
    daemon, ev = _daemon(client=False)
    assert daemon.heartbeat() is True
    assert ev.chunks == []
    assert daemon.pulse.misses() == 0


def test_a_probe_never_waits_for_the_lock() -> None:
    """A wedged call holds the lock for ever; a probe behind it would stop reporting."""
    daemon, ev = _daemon()
    daemon._lock.acquire()                                  # noqa: SLF001
    try:
        started = time.monotonic()
        assert daemon.heartbeat() is True
        assert time.monotonic() - started < 0.2, "it waited for the lock"
    finally:
        daemon._lock.release()                              # noqa: SLF001
    assert ev.chunks == [], "nothing was sent"
    assert daemon.pulse.misses() == 0, "a busy daemon is not a failing one"


# ---------------------------------------------------------------------------
# letting go of the port
# ---------------------------------------------------------------------------

def test_three_failed_probes_and_the_daemon_should_leave() -> None:
    daemon, ev = _daemon()
    ev.fail = RuntimeError("cannot attach")
    for _ in range(2):
        daemon.heartbeat()
    assert not daemon.pulse.should_leave(), "two is a client that may be restarting"
    daemon.heartbeat()
    assert daemon.pulse.should_leave()


def test_one_answer_in_between_clears_the_count() -> None:
    daemon, ev = _daemon()
    ev.fail = RuntimeError("cannot attach")
    daemon.heartbeat()
    daemon.heartbeat()
    ev.fail = None
    daemon._ev = ev                                         # the rebuild would do this
    assert daemon.heartbeat() is True
    assert daemon.pulse.misses() == 0 and not daemon.pulse.should_leave()


def test_the_watch_leaves_when_the_pulse_says_so() -> None:
    """`_watch_client` is what acts on it — the pulse only ever says."""
    daemon, ev = _daemon()
    ev.fail = RuntimeError("cannot attach")
    left: list = []
    real_leave, lua_daemon._leave = lua_daemon._leave, left.append
    real_sleep, lua_daemon.time.sleep = lua_daemon.time.sleep, lambda _s: None
    try:
        watch = threading.Thread(
            target=lua_daemon._watch_client, args=(daemon, 0.0), daemon=True)
        watch.start()
        deadline = time.monotonic() + 5.0
        while not left and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        lua_daemon._leave = real_leave
        lua_daemon.time.sleep = real_sleep
    assert left, "the watch never let go of the port"


# ---------------------------------------------------------------------------
# the wire
# ---------------------------------------------------------------------------

class _Server:
    """The real daemon dispatch on a real socket, with the game stubbed out."""

    def __init__(self, answer=("X ok",), delay: float = 0.0) -> None:
        self.daemon, self.ev = _daemon(answer, delay)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=lua_daemon._handle,
                             args=(conn, self.daemon), daemon=True).start()

    def ask(self, req: dict) -> dict:
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall((json.dumps(req) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                part = sock.recv(65536)
                if not part:
                    break
                buf += part
        return json.loads(buf.decode().splitlines()[0])

    def close(self) -> None:
        self.sock.close()


def test_the_ping_carries_the_age_of_the_last_landed_chunk() -> None:
    srv = _Server()
    try:
        first = srv.ask({"op": "ping"})
        assert first["ok"] and first["last_ok_age"] is None, first
        assert "misses" in first and "probe_error" in first, first
        srv.ask({"op": "run", "chunk": "x()", "marker": "X", "settle": 0.1})
        after = srv.ask({"op": "ping"})
        assert isinstance(after["last_ok_age"], float), after
        assert after["last_ok_age"] < 1.0, after
    finally:
        srv.close()


def test_the_wait_is_outside_the_lock() -> None:
    """Two calls whose answers take half a second each take half a second together."""
    srv = _Server(delay=0.5)
    try:
        done: list = []

        def call() -> None:
            srv.ask({"op": "run", "chunk": "x()", "marker": "X", "settle": 0.1})
            done.append(time.monotonic())

        started = time.monotonic()
        threads = [threading.Thread(target=call) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        spent = max(done) - started
        assert len(done) == 3, done
        assert spent < 1.0, (
            f"three half-second waits took {spent:.2f}s — the settle is back "
            f"inside the lock")
    finally:
        srv.close()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
