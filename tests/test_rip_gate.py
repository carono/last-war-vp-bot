r"""The park the hijack gate is aimed at (#1994).

A hijack is only allowed to borrow the client's main thread while that thread is
PARKED — sitting in the message-pump wait inside ntdll, holding no runtime lock. The
address of that wait is learned by sampling, and `hijack_call` then accepts the thread
only within ±16 bytes of it.

What is pinned here is the one thing that made a fourteen-hour outage look like «the
panel does not see any traffic»: the learner used to answer with the most-sampled RIP
whatever it was, so a client the player was actively playing handed out an address in
its own render loop. The gate could never match it, every hijack failed with «returned
None», and because the address is learned once per build it stayed wrong for the life
of the process — long after the client went quiet again.

  * a candidate outside ntdll is not a park, and is never returned;
  * a thread that never reached ntdll while we watched is answered None, not a guess;
  * the most-sampled NTDLL address wins, not the most-sampled address overall;
  * and the caller re-learns once before it gives up, then says what the person should
    do about it in a sentence.

    C:\Python312\python.exe tests\test_rip_gate.py
    python3 tests/test_rip_gate.py
"""
from __future__ import annotations

TIER = "offline"   # no game, no Windows — the selection is plain arithmetic

import pathlib
import sys
import types
from collections import Counter

_REPO = pathlib.Path(__file__).resolve().parents[1]

NTDLL_BASE = 0x7FFA95550000
NTDLL_SIZE = 0x200000
PARK = NTDLL_BASE + 0xA0E84
BUSY_RIP = 0x7FF9DF4B2812      # somewhere private — the render loop


def _rip_gate(counts: Counter, *, ntdll: bool = True):
    """`rip_gate` with the Windows layer under it replaced by these samples."""
    probe = types.ModuleType("il2cpp_probe")

    def module_base(pid, name):
        if name.lower() == "ntdll.dll" and ntdll:
            return NTDLL_BASE, NTDLL_SIZE
        raise SystemExit(f"module {name} not found")

    probe.module_base = module_base
    probe.CloseHandle = lambda h: None
    probe.find_game_pid = lambda: 1
    hijack = types.ModuleType("hijack_call")
    hijack.OpenThread = lambda *a: 1
    hijack.THREAD_ALL = 0
    hijack.SuspendThread = lambda h: 0
    hijack.ResumeThread = lambda h: 0
    hijack.GetThreadContext = lambda *a: True
    hijack.OFF_FLAGS = 0
    hijack.OFF_RIP = 0
    hijack.CONTEXT_FULL = 0
    hijack._aligned_context = lambda: (bytearray(8), 0)
    sys.modules["il2cpp_probe"] = probe
    sys.modules["hijack_call"] = hijack
    sys.modules.pop("rip_gate", None)
    sys.path.insert(0, str(_REPO / "tools" / "lib"))
    import rip_gate
    rip_gate.sample_rip = lambda pid, tid, n=40, gap=0.05: counts
    return rip_gate


def test_idle_client_gives_the_park():
    """The ordinary case: the thread is nearly always in the wait."""
    g = _rip_gate(Counter({PARK: 46, BUSY_RIP: 4}))
    assert g.learn_safe_rip(1, 2) == (PARK, 46)


def test_busy_client_is_answered_none_not_a_guess():
    """No ntdll sample at all — the client is being played, and the gate is told so."""
    g = _rip_gate(Counter({BUSY_RIP: 4, BUSY_RIP + 0x100: 3, BUSY_RIP + 0x200: 2}))
    assert g.learn_safe_rip(1, 2) is None, \
        "a RIP in the render loop was handed to the gate as a park"


def test_the_park_wins_even_when_it_is_not_the_commonest():
    """The measured shape of #1994: 8% in ntdll, everything else scattered."""
    counts = Counter({BUSY_RIP: 9, PARK: 4})
    counts.update({BUSY_RIP + 0x10 * i: 1 for i in range(1, 30)})
    g = _rip_gate(counts)
    assert g.learn_safe_rip(1, 2) == (PARK, 4)


def test_no_ntdll_falls_back_to_the_old_answer():
    """If ntdll cannot be located, judge nothing — behave as before."""
    g = _rip_gate(Counter({BUSY_RIP: 9, PARK: 4}), ntdll=False)
    assert g.learn_safe_rip(1, 2) == (BUSY_RIP, 9)


def test_nothing_sampled_is_none():
    g = _rip_gate(Counter())
    assert g.learn_safe_rip(1, 2) is None


def test_the_route_relearns_once_and_says_what_to_do():
    """Read off the source: the retry and the sentence, without a game to run it."""
    src = (_REPO / "tools" / "lib" / "xlua_route.py").read_text(encoding="utf-8")
    assert "for attempt in (0, 1):" in src, "a refusal no longer re-asks for the park"
    assert "re-learned SAFE_RIP" in src, "…and never says that it did"
    assert "gated hijack returned None" not in src, \
        "the mechanism's own words reached the person again"
    assert "let the game sit in the base" in src, \
        "the sentence stopped saying what to DO about it"


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
