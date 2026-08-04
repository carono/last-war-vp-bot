r"""How long a chunk is waited for after it has been sent (task #1230).

`settle` was a plain `time.sleep` between sending a chunk and reading the game's own
log: every press paid it in full, whatever the game did. Measured on the live client,
the answer of an ordinary chunk is in `Player.log` about thirty milliseconds later — so
a jump spent 1.6 s waiting for a line that had been there since the first fiftieth of
it, and the game lease was held for all of it, which is what made the next press
«занято».

`early` makes the same number a DEADLINE. What is pinned here is the pair of promises
that makes it safe to ask for:

  * it can only be FASTER — the wait ends when the marker has landed and stopped
    growing, and never runs past `settle`;
  * it is never SHORTER than the answer — a line that arrives late (a chunk that asked
    the server something and logs when the reply lands) is still waited for, and a chunk
    that says nothing at all still costs the whole settle, exactly as before.

That last one is why `early` is opt-in: only the caller knows whether the marker line
its chunk logs IS the answer, or merely the acknowledgement of a request whose answer
comes later. The three that ask for it — the panel's jump, the scenario interpreter and
the current-server read — all log their result at the end of the chunk.

No game and no Windows: the log is a temp file a thread writes to.

    C:\Python312\python.exe tests\test_lua_settle.py
    python3 tests/test_lua_settle.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import lua_actions  # noqa: E402
import lua_daemon  # noqa: E402
import lua_eval  # noqa: E402


class _Log:
    """A stand-in Player.log a test can append to, from now or in a moment."""

    def __init__(self, seed: str = "old line\n") -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.dir.name) / "Player.log")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(seed)
        self.since = Path(self.path).stat().st_size

    def write(self, text: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(text)

    def write_in(self, delay: float, text: str) -> None:
        t = threading.Timer(delay, self.write, args=(text,))
        t.daemon = True
        t.start()

    def close(self) -> None:
        self.dir.cleanup()


#: Windows' timer granularity is ~16 ms and `time.sleep` may come back a shade early
#: against `time.monotonic` — a wait is "the whole settle" if it is within this of it.
SLACK = 0.05


def _timed(fn):
    t0 = time.monotonic()
    out = fn()
    return out, time.monotonic() - t0


# -- the answer is already there ------------------------------------------------


def test_a_patient_call_sits_out_the_whole_settle():
    log = _Log()
    try:
        log.write("ACT jump=1,2 srv=100\n")
        lines, took = _timed(lambda: lua_eval.collect(log.path, log.since, "ACT", 0.4))
        assert lines == ["ACT jump=1,2 srv=100"], lines
        assert took >= 0.4 - SLACK, took
    finally:
        log.close()


def test_an_early_call_comes_back_as_soon_as_the_marker_has_landed():
    log = _Log()
    try:
        log.write("ACT jump=1,2 srv=100\n")
        lines, took = _timed(lambda: lua_eval.collect(
            log.path, log.since, "ACT", 5.0, early=True, quiet=0.05))
        assert lines == ["ACT jump=1,2 srv=100"], lines
        assert took < 0.5, f"waited {took:.2f}s for a line that was already there"
    finally:
        log.close()


def test_only_the_marker_lines_come_back_either_way():
    log = _Log()
    try:
        log.write("noise\nACT one\nmore noise\nACT two\n")
        early = lua_eval.collect(log.path, log.since, "ACT", 2.0, early=True, quiet=0.05)
        patient = lua_eval.collect(log.path, log.since, "ACT", 0.05)
        assert early == ["ACT one", "ACT two"], early
        assert early == patient, (early, patient)
    finally:
        log.close()


# -- the answer is still coming -------------------------------------------------


def test_a_late_answer_is_waited_for():
    log = _Log()
    try:
        log.write_in(0.3, "ACT curserver=100\n")
        lines, took = _timed(lambda: lua_eval.collect(
            log.path, log.since, "ACT", 3.0, early=True, quiet=0.05))
        assert lines == ["ACT curserver=100"], lines
        assert took >= 0.3 - SLACK, took
        assert took < 1.5, f"kept waiting {took:.2f}s after the answer landed"
    finally:
        log.close()


def test_the_rest_of_a_growing_answer_is_not_cut_off():
    log = _Log()
    try:
        log.write("ACT row 1\n")
        log.write_in(0.10, "ACT row 2\n")
        log.write_in(0.20, "ACT row 3\n")
        lines = lua_eval.collect(log.path, log.since, "ACT", 3.0, early=True, quiet=0.15)
        assert lines == ["ACT row 1", "ACT row 2", "ACT row 3"], lines
    finally:
        log.close()


def test_a_silent_chunk_still_costs_the_whole_settle():
    log = _Log()
    try:
        lines, took = _timed(lambda: lua_eval.collect(
            log.path, log.since, "ACT", 0.4, early=True, quiet=0.05))
        assert lines == [], lines
        assert took >= 0.4 - SLACK, f"gave up after {took:.2f}s on a chunk that may still answer"
    finally:
        log.close()


def test_with_no_marker_there_is_nothing_to_be_early_about():
    log = _Log()
    try:
        log.write("whatever\n")
        lines, took = _timed(lambda: lua_eval.collect(
            log.path, log.since, None, 0.3, early=True))
        assert lines == ["whatever"], lines
        assert took >= 0.3 - SLACK, took
    finally:
        log.close()


# -- and it travels to the daemon ----------------------------------------------


class _Recorder:
    """Stands in for the warm LuaEval: remembers how it was asked to wait."""

    def __init__(self) -> None:
        self.calls = []

    def run(self, chunk, marker=None, settle=1.2, early=False):
        self.calls.append({"chunk": chunk, "marker": marker,
                           "settle": settle, "early": early})
        return [f"{marker or 'X'} ok"]

    def close(self) -> None:
        pass


def test_the_daemon_passes_the_deadline_on_to_the_evaluator():
    daemon = lua_daemon.Daemon()
    daemon._ev = _Recorder()
    daemon.run("chunk", "ACT", 1.6, early=True)
    daemon.run("chunk", "ACT", 1.6)
    assert [c["early"] for c in daemon._ev.calls] == [True, False], daemon._ev.calls


# -- the jump that no longer needs a read in front of it ------------------------


def test_a_jump_without_a_server_asks_the_game_inside_the_chunk():
    """The whole point of #1230's first half: one trip to the VM, not two."""
    chunk = lua_actions.jump_to_coord(561, 492)
    assert "curServerId" in chunk, chunk
    assert "GotoWorldPos" in chunk, chunk
    # …and the fallback is still the machine's own, never somebody else's number
    assert str(lua_actions.HOME_SERVER) in chunk, chunk


def test_a_jump_with_a_server_still_names_it_outright():
    chunk = lua_actions.jump_to_coord(561, 492, 300)
    assert "local srv=300 " in chunk, chunk
    assert "curServerId" not in chunk, chunk


def test_the_panel_jumps_in_one_call_and_never_reads_the_server_first():
    """What the person was waiting out: a whole call, and its settle, before the jump.

    Skipped where the runtime cannot be imported at all (the WSL python3 has no
    tkinter) — the Windows interpreter the panel runs on is the one that matters.
    """
    try:
        import panel.runtime.daemon as daemonmod
    except Exception as exc:                          # noqa: BLE001
        print(f"       (skipped: the panel runtime does not import here — {exc})")
        return

    class _Client:
        port = 47999
        token = ""

        def __init__(self) -> None:
            self.calls = []

        def run(self, chunk, marker=None, settle=1.2, early=False):
            self.calls.append({"chunk": chunk, "settle": settle, "early": early})
            return ["ACT jump=561,492 srv=935"]

        def acquire(self, owner, ttl=120.0):
            return "token"

        def release(self):
            return True

    class _Log:
        def __init__(self) -> None:
            self.said = []

        def put(self, line):
            self.said.append(line)

        def say(self, tag, key, **fmt):
            self.said.append(f"{tag}:{key}")

    was, log = daemonmod.lua_client.is_running, _Log()
    daemonmod.lua_client.is_running = lambda *a, **k: True      # a daemon is "there"
    try:
        link = daemonmod.GameLink(port=lambda: 47999, python=lambda: "python", log=log,
                                  env=dict, cwd=str(ROOT), daemon_script="x")
        link.client = _Client()
        assert link.jump(561, 492, None) is True
        for _ in range(200):                                    # it runs on a thread
            if link.client.calls and not link.busy:
                break
            time.sleep(0.01)
    finally:
        daemonmod.lua_client.is_running = was

    calls = link.client.calls
    assert len(calls) == 1, [c["chunk"][:60] for c in calls]
    assert "curServerId" in calls[0]["chunk"], calls[0]["chunk"]
    assert calls[0]["early"] is True, calls[0]


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
