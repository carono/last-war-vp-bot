r"""One relaunch at a time, whoever asks — the lock in `PanelRuntime.play_async` (#1296).

«У действия по кику должен быть ровно один исполнитель.» Four different things put this
client back and none of them knows about the others: the process watchdog
(`panel/__main__.py::_watchdog_check`), the recovery verdict (`recovery.RESTARTS`), the
`restart_game` errand on its clock, and a person's button in the window or on the phone.

Everything that kept them apart until now was TIMING — a hold here, a cooldown there —
and timing is what fails on the day it matters: a kicked account had six kicks in one
morning, and each kick is a moment when two detectors see the same «down» in the same
second. The game claim does not help: it is held for the length of a scenario and
released when it ends, so «launch_game finished» and «the client is up» are different
moments, and the second detector takes the freed claim to launch a client that is already
starting.

So the lock lives at the one door every caller comes through, and this file pins what it
must do:

  * a relaunch in flight REFUSES the next one, and says which is running;
  * a relaunch that has just finished refuses for a settle, because a client told to
    start is not up yet and the reading that started the first is still true;
  * **a refused claim gives the lock straight back** — the hole this author put in it and
    then found: the lock was taken before the claim was asked for, so a claim refused by
    a busy game would have left it held for ever and no relaunch would ever run again.
    A lock taken and not given back is worse than no lock at all;
  * anything that is not a relaunch passes through untouched;
  * every refusal is SAID. A watchdog that quietly did nothing is what this whole area
    keeps relearning (#1259, #1296).

    C:\Python312\python.exe tests\test_panel_relaunch_lock.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_runtime                                  # noqa: E402
from panel.runtime import host as hostmod            # noqa: E402


class _WarmLink(fake_runtime.ColdGameLink):
    """A link that GRANTS the claim, so a run actually starts.

    The cold one refuses — which is the other half of this file, and exactly the case the
    early-exit hole was in.
    """

    def claim(self, owner="panel", priority: int = 0) -> bool:
        self.asked.append("claim")
        return True

    def reserve(self, owner="panel", priority: int = 0) -> bool:
        self.asked.append("claim")
        return True

    def lease(self, owner="panel") -> bool:
        self.asked.append("claim")
        return True

    def claim_soon(self, owner="panel", priority: int = 2, timeout: float = 0.0,
                   poll: float = 0.0) -> bool:
        self.asked.append("claim")
        return True

    def on_settled(self) -> None: ...


class _Runner:
    """Stands in for `rt.actions`: records what was played and can block on demand."""

    def __init__(self) -> None:
        self.played = []
        self.hold = None          # an Event the run waits on, when set

    def run(self, name, args=None, **kw):
        self.played.append(name)
        if self.hold is not None:
            self.hold.wait(5.0)

    def play(self, name, args=None, **kw):
        self.run(name, args, **kw)
        return hostmod.Outcome(True, "")


def _skip(reason) -> None:
    print(f"  skip: {reason}")


def _runtime(app, warm: bool = True):
    rt = fake_runtime.cold_runtime(app)
    if warm:
        rt.game = _WarmLink()
    rt.actions = _Runner()
    return rt


def _said(rt) -> str:
    """Every log line this runtime has produced, as one string."""
    return " | ".join(str(x) for x in getattr(rt.log, "lines", []))


def _with_tk(body):
    """Run `body(app)` under a withdrawn Tk root, or skip on a headless box."""
    try:
        import tkinter as tk
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        app = tk.Tk()
    except Exception as exc:                # noqa: BLE001 — headless
        return _skip(exc)
    try:
        app.withdraw()
        body(app)
    finally:
        try:
            app.destroy()
        except Exception:                   # noqa: BLE001
            pass


def test_a_second_relaunch_is_refused_while_the_first_is_running():
    """The whole point. Two detectors seeing the same «down» in the same second must not
    put two clients back — and the refusal names WHICH relaunch is holding it, because
    «занято» with no owner is how a person ends up restarting the panel to find out."""
    def body(app):
        import threading

        rt = _runtime(app)
        rt.actions.hold = threading.Event()
        assert rt.play_async("launch_game", tag="watchdog") is True
        # …the first is inside its scenario now; the second must not get through
        for _ in range(50):
            if rt.actions.played:
                break
            time.sleep(0.02)
        assert rt.play_async("restart_game", tag="recovery") is False
        assert rt.actions.played == ["launch_game"], rt.actions.played
        assert "relaunch_busy" in _said(rt) or "launch_game" in _said(rt), _said(rt)
        rt.actions.hold.set()

    _with_tk(body)


def test_a_refused_claim_gives_the_lock_straight_back():
    """THE HOLE THIS AUTHOR PUT IN AND THEN FOUND. The lock is taken before the claim is
    asked for, so a claim refused by a busy game left it held — and from then on NO
    relaunch could ever run: the watchdog, the recovery and the button would all be
    refused for the life of the panel, and the client would stay down for good.

    A lock taken and not given back is worse than no lock at all."""
    def body(app):
        rt = _runtime(app, warm=False)          # the cold link refuses every claim
        assert rt.play_async("launch_game", tag="watchdog") is False
        assert rt.actions.played == [], "nothing should have been played"
        assert rt._relaunching == "", "the lock was kept after a refused claim"
        #: …and the next relaunch is free to go, with a link that grants the claim
        rt.game = _WarmLink()
        assert rt.play_async("launch_game", tag="watchdog") is True

    _with_tk(body)


def test_a_finished_relaunch_still_refuses_for_the_settle():
    """A client told to start is not up yet. The reading that triggered the first — «no
    process», «link down» — is still true for a detector looking a second later, so the
    lock outlives the run."""
    def body(app):
        rt = _runtime(app)
        assert rt.play_async("restart_game", tag="recovery") is True
        for _ in range(100):
            if rt._relaunching == "" and rt._relaunch_at:
                break
            time.sleep(0.02)
        assert rt._relaunch_at, "the run never marked itself finished"
        assert rt.play_async("launch_game", tag="watchdog") is False
        assert "relaunch_settling" in _said(rt) or "launch_game" in _said(rt), _said(rt)
        #: …and once the settle is over, the next one goes
        rt._relaunch_at = time.monotonic() - hostmod.RELAUNCH_SETTLE_SEC - 1
        assert rt.play_async("launch_game", tag="watchdog") is True

    _with_tk(body)


def test_an_ordinary_scenario_is_not_locked_at_all():
    """The lock is for the four things that put the client back and nothing else. An
    errand is not a relaunch, and two of them running back to back must not be refused."""
    def body(app):
        rt = _runtime(app)
        assert rt.play_async("collect_base", tag="timer") is True
        assert rt.play_async("help_ally", tag="timer") is True
        assert rt._relaunching == "", "an ordinary scenario took the relaunch lock"
        assert rt._relaunch_at == 0.0, "an ordinary scenario started the settle"

    _with_tk(body)


def test_the_set_names_every_way_of_putting_the_client_back():
    """A fifth way is one line in `RELAUNCHES`. `recover_from_kick` is in the set although
    nothing plays it yet: the day it is switched on it must already be inside the lock
    rather than added to it afterwards (`docs/research/session-kick.md`)."""
    assert hostmod.RELAUNCHES == frozenset({"launch_game", "restart_game",
                                            "recover_from_kick"}), hostmod.RELAUNCHES
    assert hostmod.RELAUNCH_SETTLE_SEC > 0


def test_the_refusals_are_translated_in_every_shipped_locale():
    """Both refusals are things a person reads, so they are keys — and a key missing from
    a locale falls back to English silently, which is how a gap survives for months."""
    import json

    keys = ("log.game.relaunch_busy", "log.game.relaunch_settling")
    locales = sorted((_REPO_ROOT / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, [p.name for p in locales]
    for path in locales:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in table, f"{path.name} is missing {key}"
            assert table[key].strip(), f"{path.name}: {key} is empty"
        assert "{running}" in table[keys[0]], path.name
        assert "{secs}" in table[keys[1]], path.name


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
