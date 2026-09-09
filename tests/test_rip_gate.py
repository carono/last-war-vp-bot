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
    rip_gate.sample_rip = lambda pid, tid, n=40, gap=0.05, stop_at=None: counts
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


# --- when a learn may stop asking (#2667) -----------------------------------

def test_a_decided_park_stops_the_sweep_early():
    """Both parks proven, or one park proven twice over: the answer is in.

    Every sample is a suspend and a resume of the client's main thread, so a sweep that
    goes on to forty after the parks are known is interference bought for nothing.

    THE BAR ROSE WITH #2678 and it is deliberate. Stopping the moment ONE address led
    the field answers «which is the park» and can never see the second wait, so the gate
    it fed was aimed at one of two — which is the eighteen minutes of «client-busy» this
    file's neighbour records. So one address stops the sweep only when it has been seen
    twice the bar and nothing else has reached the bar at all.
    """
    g = _rip_gate(Counter())
    span = (NTDLL_BASE, NTDLL_SIZE)
    assert g._decided(Counter({PARK: 3, PARK + 0xC0: 3}), span, 3), \
        "both of the client's waits are proven — there is nothing left to learn"
    assert g._decided(Counter({PARK: 6}), span, 3), \
        "one wait, seen twice over, with no rival: this client parks in one place"
    assert g._decided(Counter({PARK: 6, BUSY_RIP: 9}), span, 3), \
        "a busy render loop is not a rival — only ntdll addresses are"


def test_an_undecided_park_keeps_sampling():
    """Not enough evidence yet — the sweep goes on to its full count."""
    g = _rip_gate(Counter())
    span = (NTDLL_BASE, NTDLL_SIZE)
    assert not g._decided(Counter({PARK: 2}), span, 3), "two sightings is a coincidence"
    assert not g._decided(Counter({PARK: 3}), span, 3), \
        "one proven wait is not proof there is no second one — keep looking"
    assert not g._decided(Counter({PARK: 5, PARK + 0x400: 2}), span, 3), \
        "the runner-up is still unproven and the leader has not doubled the bar"
    assert not g._decided(Counter({BUSY_RIP: 30}), span, 3)
    assert not g._decided(Counter(), span, 3)


# --- the gate aims at EVERY park the client has (#2678) ---------------------

def test_both_parks_are_learned_busiest_first():
    """The measured shape: two ntdll waits 192 bytes apart, taking turns.

    A gate aimed at whichever of them won the sweep waits out every visit to the other,
    and on 2026-09-09 that was one profile answering «the client's main thread is busy —
    it did not reach its park once in 67s» from 12:39 to 12:57, on a client somebody was
    playing at the time.
    """
    other = PARK + 0xC0
    g = _rip_gate(Counter({PARK: 12, other: 9, BUSY_RIP: 20}))
    assert g.learn_parks(1, 2) == [(PARK, 12), (other, 9)]


def test_a_single_sighting_is_never_a_park():
    """Noise stays out — the #1994 rule, unchanged by the gate being plural."""
    g = _rip_gate(Counter({PARK: 8, PARK + 0xC0: 1}))
    assert g.learn_parks(1, 2) == [(PARK, 8)]


def test_no_more_parks_than_the_gate_takes():
    counts = Counter({PARK + 0x40 * i: 9 - i for i in range(4)})
    g = _rip_gate(counts)
    assert len(g.learn_parks(1, 2)) == g.MAX_PARKS


def test_a_weak_sweep_still_answers_with_its_best():
    """Nothing reached the bar: the busiest ntdll address, alone — the old answer."""
    g = _rip_gate(Counter({PARK: 2, PARK + 0xC0: 1}))
    assert g.learn_parks(1, 2) == [(PARK, 2)]
    assert g.learn_safe_rip(1, 2) == (PARK, 2)


def test_the_gate_matches_any_learned_park_and_nothing_else():
    """Read off `hijack_call`: several addresses, the same ±16 bytes around each."""
    src = (_REPO / "tools" / "lib" / "hijack_call.py").read_text(encoding="utf-8")
    assert "any(abs(rip - one) <= rip_tol for one in parks)" in src, \
        "the gate stopped accepting every learned park"
    assert "return nt_lo <= rip < nt_hi" in src, \
        "the un-gated fallback (no park learned at all) went missing"


def test_the_route_hands_the_gate_every_park():
    src = (_REPO / "tools" / "lib" / "xlua_route.py").read_text(encoding="utf-8")
    assert "R.learn_parks(" in src, "the route went back to learning one park"
    assert "safe_rip=self.sr" in src and "rip_tol=16" in src, \
        "the tolerance around a park is not ±16 bytes any more"


def test_the_route_waits_for_a_busy_client_instead_of_dying():
    """Read off the source: a step waits, re-learns, and only then calls it busy.

    The gate is what keeps the client alive, so what is pinned here is that the WAIT
    grew and the TARGET did not: ±16 bytes of the learned park, main thread only.
    """
    src = (_REPO / "tools" / "lib" / "xlua_route.py").read_text(encoding="utf-8")
    assert "PARK_WINDOW = 15.0" in src, "a step gave up after one short look again"
    assert "STEP_BUDGET = 60.0" in src, "…and with no budget across re-learns"
    assert "park_timeout=self.PARK_WINDOW" in src, "the window is not the one being used"
    assert "rip_tol=16" in src and "only_tid=self.mt" in src, \
        "the GATE was widened — the wait is what may grow, never the target"
    assert "re-learned SAFE_RIP" in src, "a refusal no longer re-asks for the park"
    assert "gated hijack returned None" not in src, \
        "the mechanism's own words reached the person again"
    assert 'BUSY_MARK = "client-busy"' in src, \
        "the panel can no longer tell «busy» from every other reason nothing lands"


def test_the_panel_keeps_saying_how_long_it_has_been_stuck():
    """The other half of #1994: one line at the start and then five minutes of nothing."""
    src = (_REPO / "panel" / "runtime" / "link.py").read_text(encoding="utf-8")
    assert "FAIL_AGAIN_SEC = 60.0" in src, "a standing failure went quiet again"
    assert "log.link.attach_busy" in src and "log.link.attach_stuck" in src, \
        "the repeat says nothing about how long it has been true"
    assert 'BUSY_MARK = "client-busy"' in src, \
        "«the client is busy» is not told apart from a real fault"


def test_the_two_new_lines_are_in_every_shipped_locale():
    import json
    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, "the shipped set shrank — check panel/locales/"
    for path in locales:
        keys = json.loads(path.read_text(encoding="utf-8"))
        for key in ("log.link.attach_busy", "log.link.attach_stuck"):
            assert key in keys, f"{path.name} is missing {key}"
            assert "{minutes}" in keys[key], f"{path.name}:{key} lost its duration"


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
