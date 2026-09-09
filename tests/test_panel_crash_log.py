r"""The black box: what the panel was doing when the client died (#2678).

The person's instruction was «давай расширенное логирование веди», after a day in which
«клиент падает» could only be answered by arithmetic over `debug.log` — how many fresh
pids in an hour — which says how often and never why.

What is pinned here, and the first one is the rule the rest are written under:

  * **it never asks the game anything.** Every figure in the block is a counter the panel
    already keeps or a stamp it already wrote. A diagnostic that costs a chunk is a chunk
    the errand did not get, and one that costs a chunk while the client is dying is worse
    than useless (`CLAUDE.md`, «Read once, then LISTEN»);
  * the block is written on the DEATH edge, into the profile's own `debug.log`;
  * it carries the last chunk, the attach counters as a DELTA, and the run-up;
  * `LW_CRASH_LOG` switches the detail, `off` means nothing at all, and the per-chunk
    note costs only a deque append and only at `full`;
  * a recorder is per PROFILE NAME, and the LINK's is deliberately machine-wide because
    one Windows session holds one client;
  * nothing in it can raise into the caller — a status poll that dies on its diagnostic
    is a panel that stops watching.

    python3 tests/test_panel_crash_log.py
    C:\Python312\python.exe tests\test_panel_crash_log.py
"""
from __future__ import annotations

TIER = "offline"   # no Tk, no game, no Windows — a stub runtime and a fake logger

import importlib
import os
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_pkg = sys.modules.setdefault("panel", types.ModuleType("panel"))
_pkg.__path__ = [str(_REPO / "panel")]
if not hasattr(_pkg, "__version__"):
    _pkg.__version__ = "0.0.0-test"
_rt = sys.modules.setdefault("panel.runtime", types.ModuleType("panel.runtime"))
_rt.__path__ = [str(_REPO / "panel" / "runtime")]
cl = importlib.import_module("panel.runtime.crash_log")


class Log:
    def __init__(self) -> None:
        self.lines: list = []

    def info(self, fmt, *a) -> None:
        self.lines.append(str(fmt) % a if a else str(fmt))

    warning = info


class Game:
    def up(self):
        return True

    def ready(self):
        return False

    def client_pid(self):
        return 4242

    def error(self):
        return "OpenThread(...) failed err=87"


class Rt:
    def __init__(self, profile="acct") -> None:
        self.log = Log()
        self.game = Game()
        self.profiles = types.SimpleNamespace(active=profile)
        self.recovery = types.SimpleNamespace(state=lambda: {"strikes": 5, "restarts": 1})

    def dbg(self, _tag):
        return self.log


def _fresh(level: str = "on"):
    """A clean registry at ``level`` — the recorders are module-wide by design."""
    os.environ["LW_CRASH_LOG"] = level
    cl._BY_PROFILE.clear()
    return Rt()


def test_a_death_writes_one_block_into_the_profiles_debug_log():
    rt = _fresh()
    rec = cl.for_rt(rt)
    rec.saw_pid(4242)
    rec.chunk("run:heal_units", "ACT")
    rec.note("attach", "took hold of pid 4242")
    rec.died(rt)
    said = "\n".join(rt.log.lines)
    assert "КЛИЕНТ УМЕР" in said, said
    assert "pid=4242" in said
    assert "run:heal_units" in said and "marker=ACT" in said
    assert "took hold of pid 4242" in said
    assert "end of the crash block" in said


def test_off_writes_nothing_at_all():
    rt = _fresh("off")
    assert cl.for_rt(rt) is None
    cl.of("acct").died(rt)
    assert rt.log.lines == [], rt.log.lines


def test_only_full_records_every_chunk():
    rt = _fresh("on")
    rec = cl.for_rt(rt)
    for _ in range(5):
        rec.chunk("run:x", "ACT")
    assert not [n for n in rec._notes() if "[chunk]" in n], \
        "the default level pays a deque append per call"
    rt = _fresh("full")
    rec = cl.for_rt(rt)
    rec.chunk("run:x", "ACT")
    assert any("[chunk]" in n for n in rec._notes())


def test_the_last_chunk_is_a_slot_and_costs_one_assignment():
    rt = _fresh("on")
    rec = cl.for_rt(rt)
    rec.chunk("run:steal", "ACT")
    who, marker, when = rec.last_chunk
    assert (who, marker) == ("run:steal", "ACT") and when > 0


def test_the_ring_is_bounded():
    rt = _fresh()
    rec = cl.for_rt(rt)
    for i in range(cl.KEEP * 3):
        rec.note("x", str(i))
    assert len(rec._notes()) == cl.KEEP


def test_a_recorder_is_per_profile_and_the_link_is_the_machines():
    rt = _fresh()
    cl.of("one").note("x", "belongs to one")
    cl.of("two").note("x", "belongs to two")
    assert "belongs to one" not in "\n".join(cl.of("two")._notes())
    assert cl.LINK.startswith(":"), \
        "the link's key must not collide with a profile name"


def test_the_block_carries_the_links_own_notes_too():
    """One session holds one client, so the chunks are the machine's, not an account's."""
    rt = _fresh()
    cl.of(cl.LINK).chunk("child:DataCenter.__lw_chat", "ACT")
    cl.of(cl.LINK).note("refused", "client-busy: DoString(bytes)")
    cl.for_rt(rt).died(rt)
    said = "\n".join(rt.log.lines)
    assert "client-busy" in said and "child:DataCenter.__lw_chat" in said


def test_the_hijack_counters_are_a_delta_not_a_lifetime_total():
    rt = _fresh()
    rec = cl.for_rt(rt)
    fake = types.ModuleType("hijack_call")
    state = {"n": 100, "park_tries": 200, "misses": 1, "abandoned": 0,
             "by_label": {"DoString(bytes)": 90}}
    fake.stats = lambda: dict(state, by_label=dict(state["by_label"]))
    sys.modules["hijack_call"] = fake
    try:
        assert "first block" in rec._hijacks()
        state.update(n=110, park_tries=222, misses=2)
        state["by_label"]["DoString(bytes)"] = 99
        line = rec._hijacks()
        assert "10 since the last block" in line, line
        assert "2.2 park tries each" in line, line
        assert "DoString(bytes)=9" in line, line
    finally:
        sys.modules.pop("hijack_call", None)


def test_nothing_here_asks_the_game_anything():
    """The rule the module is written under, read off its own source.

    `run_action`, `play_async`, `evaluator` and `READ_LUA` are the four ways a chunk
    leaves the panel; none of them may appear in a diagnostic.
    """
    src = (_REPO / "panel" / "runtime" / "crash_log.py").read_text(encoding="utf-8")
    body = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in ("run_action(", "play_async(", ".evaluator(", "READ_LUA"):
        assert forbidden not in body, \
            f"the crash block asks the game something ({forbidden})"


def test_a_broken_runtime_does_not_take_the_poll_down():
    """A status poll that dies on its own diagnostic is a panel that stops watching."""
    rt = _fresh()
    rec = cl.for_rt(rt)

    class Broken:
        profiles = types.SimpleNamespace(active="acct")

        def dbg(self, _tag):
            raise RuntimeError("no logger here")

    rec.died(Broken())                      # must not raise
    cl.note(Broken(), "x", "y")             # nor must this


def test_the_windows_evidence_is_throttled():
    assert cl.REPORT_EVERY_SEC >= 300, \
        "a client dying five times in ten minutes would spawn five PowerShells"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    os.environ.pop("LW_CRASH_LOG", None)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
