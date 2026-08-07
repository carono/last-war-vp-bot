r"""Sending a chunk and reading its answer are two acts, not one (task #1287).

`LuaEval.run` used to send and wait in one call, and the daemon held its run lock across
the whole of it. The lock is right — the hijack is not reentrant — but the WAIT needs no
lock at all: `SafeDoString` is synchronous, so by the time the injection returns the
chunk has already run and flushed, and the settle that follows is a wait for whatever
arrives later. Measured on the live client (#1287): one call is 60 ms against a free
daemon and 3 855 ms behind three background readers holding patient settles, and 95 % of
that lock occupancy is a sleep.

So `send` does the injection and hands back a :class:`Pending`; `harvest` does the
waiting and takes nothing. What is pinned here:

  * `run` is still exactly `send` + `harvest`, for every caller that never asked for the
    split;
  * `send` does not wait — that is the entire point, and it is the property that breaks
    silently if somebody moves the collect back;
  * two calls collecting at once do NOT read each other's lines. One shared answer file
    could not tell them apart (both filter by the same marker), so a caller that means
    to overlap asks for a private file;
  * a private file is folded back into the shared record and removed — the record is
    what a person reads a `lua-error` out of, and `tools/dev/check_answer_channel.py`
    checks that it is still written;
  * a file left behind by a call whose process died is swept, and one that is still
    being written is not.

No game and no Windows: `_send` is stubbed and the "game" writes the answer file itself.

    C:\Python312\python.exe tests\test_lua_answer_split.py
    python3 tests/test_lua_answer_split.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import lua_eval  # noqa: E402


class FakeEval(lua_eval.LuaEval):
    """A LuaEval with no game behind it: `_send` writes what the chunk would have.

    Built without `__init__` on purpose — that one hijacks a live client.
    """

    def __new__(cls, folder: Path, answer: str = "", delay: float = 0.0,
                to_log: str = ""):
        self = object.__new__(cls)
        self.log = str(folder / "Player.log")
        self.answers = str(folder / "lw_answers.log")
        self.sent = []
        self._answer, self._delay, self._to_log = answer, delay, to_log
        open(self.log, "ab").close()
        return self

    def __init__(self, *_args, **_kw) -> None:
        pass                      # `__new__` did it all; the real one hijacks a client

    def _send(self, chunk) -> None:
        self.sent.append(chunk)
        # The path the wrapper was told to write to — the chunk carries it as a literal.
        path = self.answers
        for piece in chunk.split("'"):
            if piece.endswith(".log") and "lw_answers" in piece:
                path = piece.replace("\\\\", "\\")
                break
        if self._to_log:
            with open(self.log, "ab") as fh:
                fh.write(self._to_log.encode())
        if not self._answer:
            return

        def write() -> None:
            time.sleep(self._delay)
            with open(path, "ab") as fh:
                fh.write(self._answer.encode())

        if self._delay:
            threading.Thread(target=write, daemon=True).start()
        else:
            write()


# ---------------------------------------------------------------------------
# run is still send + harvest
# ---------------------------------------------------------------------------

def test_run_is_send_then_harvest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), answer="ACT one\nACT two\nnoise\n")
        lines = ev.run("do_it()", marker="ACT", settle=0.2, early=True)
        assert lines == ["ACT one", "ACT two"], lines


def test_send_hands_back_what_harvest_needs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), answer="ACT one\n")
        pending = ev.send("do_it()", marker="ACT", settle=0.2, early=True)
        assert isinstance(pending, lua_eval.Pending)
        assert lua_eval.harvest(pending) == ["ACT one"]


def test_send_does_not_wait() -> None:
    """The whole point: the injection returns, the settle is somebody else's problem."""
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), answer="ACT late\n", delay=0.25)
        started = time.monotonic()
        pending = ev.send("do_it()", marker="ACT", settle=2.0)
        sending = time.monotonic() - started
        assert sending < 0.10, f"send waited {sending:.3f}s — the settle is inside it"
        assert lua_eval.harvest(pending) == ["ACT late"]
        assert time.monotonic() - started >= 0.25


# ---------------------------------------------------------------------------
# the private file, and why it exists
# ---------------------------------------------------------------------------

def test_two_calls_at_once_do_not_read_each_others_lines() -> None:
    """One shared file cannot tell two callers apart — both match the same marker."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        first = FakeEval(folder, answer="ACT first\n")
        second = FakeEval(folder, answer="ACT second\n")
        a = first.send("one()", marker="ACT", settle=0.2, early=True, private=True)
        b = second.send("two()", marker="ACT", settle=0.2, early=True, private=True)
        assert a.path != b.path, "a private call must get a file of its own"
        assert lua_eval.harvest(a) == ["ACT first"]
        assert lua_eval.harvest(b) == ["ACT second"]


def test_a_private_answer_is_folded_into_the_record_and_the_file_goes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), answer="ACT one\nlua-error: deliberate\n")
        pending = ev.send("do_it()", marker="ACT", settle=0.2, early=True,
                          private=True)
        assert lua_eval.harvest(pending) == ["ACT one"]
        assert not os.path.exists(pending.path), "the per-call file must be removed"
        with open(ev.answers, "rb") as fh:
            record = fh.read().decode()
        assert "lua-error: deliberate" in record, record
        assert "ACT one" in record, record


def test_the_shared_file_is_still_the_default() -> None:
    """Nothing that never asked for a private file gets one."""
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), answer="ACT one\n")
        pending = ev.send("do_it()", marker="ACT", settle=0.2, early=True)
        assert pending.path == ev.answers, pending.path
        assert pending.record is None
        assert lua_eval.harvest(pending) == ["ACT one"]
        assert os.path.exists(ev.answers)


def test_a_second_shared_call_reads_only_what_it_added() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), answer="ACT one\n")
        assert ev.run("a()", marker="ACT", settle=0.2, early=True) == ["ACT one"]
        ev._answer = "ACT two\n"
        assert ev.run("b()", marker="ACT", settle=0.2, early=True) == ["ACT two"]


# ---------------------------------------------------------------------------
# the fallbacks keep working
# ---------------------------------------------------------------------------

def test_an_empty_private_file_falls_back_to_the_games_own_log() -> None:
    """A client that cannot write the file logs to the game — the answer still arrives."""
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), answer="", to_log="ACT from the game log\n")
        lines = ev.run("do_it()", marker="ACT", settle=0.1, private=True)
        assert lines == ["ACT from the game log"], lines


def test_a_chunk_that_opted_out_collects_from_the_players_log() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ev = FakeEval(Path(tmp), to_log="ACT direct\n")
        chunk = f"-- {lua_eval.GAME_LOG_SENTINEL}\ndo_it()"
        pending = ev.send(chunk, marker="ACT", settle=0.2, early=True)
        assert pending.path == ev.log
        assert pending.record is None and pending.log_path is None
        assert lua_eval.harvest(pending) == ["ACT direct"]


# ---------------------------------------------------------------------------
# the sweep
# ---------------------------------------------------------------------------

def test_a_file_left_by_a_dead_call_is_swept_and_a_live_one_is_not() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = str(Path(tmp) / "lw_answers.log")
        open(base, "ab").close()
        stale = lua_eval._per_call_path(base)
        fresh = lua_eval._per_call_path(base)
        for path in (stale, fresh):
            open(path, "ab").close()
        old = time.time() - 2 * lua_eval.STALE_ANSWER_SEC
        os.utime(stale, (old, old))
        assert lua_eval._sweep_per_call(base) == 1
        assert not os.path.exists(stale), "an hour-old orphan should be gone"
        assert os.path.exists(fresh), "a call still running owns its file"
        assert os.path.exists(base), "the shared record is never swept"


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
