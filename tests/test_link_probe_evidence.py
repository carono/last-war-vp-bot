r"""«Не смогли спросить» — это не «сервер ответил» (задача #1976).

Green means ONE thing in this panel: the game server answered a question only it could
answer (#1911). The probe that asks it can fail to be SENT — the client is busy with an
errand, the panel is booting — and that is not evidence in either direction.

It used to be written down as a SUCCESS, and a success is exactly what green is made of:
a panel too busy to ask painted itself «сервер отвечает» and held that for five minutes,
over a client nobody had heard from. This pins the three answers apart:

  * answered      → proof, and green may be earned;
  * did not answer→ a strike, and enough of them are a reason to act;
  * never asked   → nothing at all, and the next poll asks again without waiting out the
                    gap that separates two REAL probes.

    C:\Python312\python.exe tests\test_link_probe_evidence.py
    python3 tests/test_link_probe_evidence.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

# By path, so the window (`tkinter`) is not dragged in for a rule about the game link.
_spec = importlib.util.spec_from_file_location(
    "lw_recovery", ROOT / "panel" / "runtime" / "recovery.py")
rec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rec)

import profile_health  # noqa: E402

NOW = 10_000.0


def _fresh():
    return rec.Recovery()


def test_a_question_nobody_asked_never_earns_green():
    r = _fresh()
    r.probe_started(NOW)
    r.probe_unstarted(NOW)
    assert r.link_confirmed(NOW) is False
    assert r.server_state(NOW) == profile_health.SERVER_UNASKED


def test_an_answer_still_earns_green():
    r = _fresh()
    r.probe_started(NOW)
    r.note_probe(True, NOW)
    assert r.link_confirmed(NOW) is True
    assert r.server_state(NOW) == profile_health.ANSWERING


def test_a_question_nobody_asked_is_not_a_strike_either():
    r = _fresh()
    r.probe_started(NOW)
    r.probe_unstarted(NOW)
    assert r.server_state(NOW) != profile_health.SILENT


def test_a_refusal_is_a_strike():
    r = _fresh()
    for i in range(rec.PROBE_FAILS):
        r.probe_started(NOW + i)
        r.note_probe(False, NOW + i)
    assert r.server_state(NOW + rec.PROBE_FAILS) == profile_health.SILENT


def test_asking_again_does_not_wait_out_the_gap_between_real_probes():
    """The gap exists so two REAL questions are not asked back to back."""
    r = _fresh()
    r.probe_started(NOW)
    r.probe_unstarted(NOW)
    assert r.probe_idle_due(NOW + 1.0) is True


def test_a_probe_in_flight_is_still_in_flight():
    r = _fresh()
    r.probe_started(NOW)
    assert r.probe_idle_due(NOW + 1.0) is False


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
