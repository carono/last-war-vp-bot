r"""The panel's «Автопомощь» watcher — what it makes of what the scenario says (#1292).

The DECISION is not here: which task is helped, which is waited for and how the day's
five are split between a ripening star and the URs beneath it is Lua over the alliance's
own table, and it is run in a real VM in `tests/test_assist_star_priority.py`. This file
is the layer above — the standing order that plays the scenario and then has to tell a
person, in one line on a tab and one row on a phone, what just happened.

Which is exactly where the same feature went wrong before. «Автолут не работает
совершенно» (#1227) was four silent states wearing one face, and a budget deliberately
HELD BACK is the fifth: nothing is pressed, nothing is spent, and from outside it is
indistinguishable from a watcher that has stopped. So:

  * a tick that helped nothing because a star is ripening says «придерживаю помощь под
    звезду до <часы>», with the star's level beside it;
  * that reading beats «помог N» when both are true in one tick — the URs under the
    reserve are spent while the star is still counting down, and it is the HOLDING that
    a person needs on screen;
  * the rule the log announces carries both halves — the priority and the wait bound —
    because a rule the log stops mentioning is one the next person has to read the
    source to find;
  * the wait bound travels to the scenario as an argument, so shortening it late in the
    day takes effect on the next look rather than on the next restart.

Driven against a stub tab: no Tk window, no game, no daemon. **tkinter must be
importable** (the panel runtime imports it), so under the WSL python3 this says SKIP and
passes. Run it under the Windows Python to actually exercise it::

    C:\Python312\python.exe tests\test_panel_autoassist.py
    python3 tests/test_panel_autoassist.py        # SKIP without tkinter
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_runtime  # noqa: E402

try:
    import tkinter  # noqa: F401
    _HAS_TK = True
except Exception:       # noqa: BLE001 — no display is fine, no module is not
    _HAS_TK = False


#: What `actions/assist_secret_task.md` prints on a tick that helped two URs while a
#: level-7 star was still ninety minutes off. Copied from the recipe's own `LOG` lines,
#: because that wording is the contract between the two — reword it there and the panel
#: goes back to saying «наблюдаю» about a budget it is deliberately holding.
WAITING_RUN = [
    'READ_LUA helps_left = 5',
    'IF helps_left == 0 -> False',
    'LOG "waiting for star 7 (ready in 90 min) — holding 1 of 5 help(s) back"',
    'TAP Help a secret task (alliance) (1; 4 available)',
    '  ACT assist_sent uuid=1000000000000001 srv=300',
    'TAP Help a secret task (alliance) (2; 3 available)',
    '  ACT assist_sent uuid=1000000000000002 srv=300',
]

#: …and an ordinary one: no star anywhere, the URs taken.
UR_RUN = [
    'LOG "no star ripening today — taking UR (4 ready)"',
    'TAP Help a secret task (alliance) (1; 4 available)',
    '  ACT assist_sent uuid=1000000000000003 srv=300',
]

#: …and the day's five gone.
SPENT_RUN = [
    'READ_LUA helps_left = 0',
    'LOG "no assists left today"',
]


class _Tab:
    """The stub tab: the level box, the checkbox, and the words the order says."""

    def __init__(self, level_min="", t=None, say=None):
        self.assist_level_var = types.SimpleNamespace(get=lambda: level_min)
        self.autoassist_var = types.SimpleNamespace(get=lambda: True)
        self.t = t
        self.say = say


def _order(level_min="", star_wait_min=None, lines=()):
    """The «Автопомощь» standing order over a stub tab, playing a recorded run."""
    from panel import runtime as rtmod
    from panel.tabs.secret_tasks.autoassist import AutoAssist

    import panel.__main__ as pm

    logs: list = []
    i18n = rtmod.Translator("ru")
    bus = fake_runtime.RecordingBus(translate=i18n.t, lines=logs)
    settings = rtmod.SettingsBinder(profiles=None, defaults=pm.SETTINGS_DEFAULTS)
    if star_wait_min is not None:
        settings.values = {"autoassist_star_wait_min": star_wait_min}
    played: list = []

    def play(name, args=None, on_event=None, **_kw):
        played.append((name, dict(args or {})))
        for line in lines:
            on_event(line)
        from panel.runtime.actions import Outcome
        return Outcome(True, "")

    rt = types.SimpleNamespace(
        settings=settings, log=bus, put=bus.put,
        actions=types.SimpleNamespace(play=play),
        game=types.SimpleNamespace(evaluator=lambda: None))
    tab = _Tab(level_min=level_min, t=i18n.t, say=bus.say)
    order = AutoAssist(rt, tab)
    order.logs, order.played = logs, played
    order.session_ready = lambda: True
    return order


def test_a_tick_that_holds_the_budget_for_a_star_says_so_on_screen():
    """The state a person reads when nothing was pressed on purpose."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    order = _order(lines=['LOG "waiting for star 7 (ready in 90 min) — '
                          'holding 5 of 5 help(s) back"'])
    order._play()
    key, datum = order.state()
    from panel.tabs.secret_tasks.autoassist import STATE_WAITING
    assert key == STATE_WAITING, (key, datum)
    assert "★7" in datum, datum
    assert ":" in datum, ("the wall clock the star is due at is missing", datum)


def test_the_holding_is_shown_even_when_urs_were_helped_in_the_same_tick():
    """Both are true at once — the reserve holds one help, the rest go on URs — and it
    is the holding that has to be on screen. «Помог 2» about a budget that is keeping
    its last one back reads as an order that has finished for the day."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    order = _order(lines=WAITING_RUN)
    order._play()
    from panel.tabs.secret_tasks.autoassist import STATE_WAITING
    assert order.state()[0] == STATE_WAITING, order.state()
    # …and the two helps are not swallowed: they are still said, in the log.
    assert any("2" in ln for ln in order.logs if "помог" in ln), order.logs


def test_a_tick_with_no_star_at_all_reports_the_helps_it_made():
    """«Звёзд нет — довольствуемся UR»: nothing is being held, so the ordinary state
    comes back — and the log says WHY the help went where it did."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    order = _order(lines=UR_RUN)
    order._play()
    from panel.tabs.secret_tasks.autoassist import STATE_HELPED
    assert order.state() == (STATE_HELPED, "1"), order.state()
    assert any("звёзд нет" in ln.lower() for ln in order.logs), order.logs


def test_the_waiting_is_announced_once_and_not_on_every_poll():
    """The scenario says it on every look — it is a branch, not a report — and a line
    every five minutes about the same star waiting the same wait buries the ones that
    matter. So the panel says it in the operator's language when the fact MOVES."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    order = _order(lines=WAITING_RUN)
    order._play()
    said = [ln for ln in order.logs if "жду звезду" in ln]
    assert len(said) == 1, order.logs
    assert "7" in said[0] and "90" in said[0], said         # the star and its countdown
    order.logs.clear()
    order._play()                                          # the same look again
    assert not [ln for ln in order.logs if "жду звезду" in ln], order.logs
    # …and a star that has come closer is a new fact, so it is said again.
    order.logs.clear()
    order.rt.actions.play = _order(lines=[
        'LOG "waiting for star 7 (ready in 30 min) — holding 1 of 5 help(s) back"',
    ]).rt.actions.play
    order._play()
    assert [ln for ln in order.logs if "жду звезду" in ln], order.logs


def test_a_spent_budget_still_pauses_rather_than_waiting_for_a_star():
    """The day's five gone outranks everything: there is no help left to hold."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    order = _order(lines=SPENT_RUN)
    order._play()
    from panel.tabs.secret_tasks.autoassist import STATE_PAUSED
    assert order.state()[0] == STATE_PAUSED, order.state()


def test_the_wait_bound_travels_to_the_scenario_with_the_level():
    """Both halves of the rule are arguments, read live, so a change takes effect on the
    next look rather than on the next restart."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    order = _order(level_min="6", star_wait_min=45, lines=UR_RUN)
    order._play()
    assert order.played == [("assist_secret_task",
                             {"level": 6, "star_wait_min": 45})], order.played


def test_the_announced_rule_carries_the_priority_and_the_bound():
    """What «Автопомощь включена: …» says, in the operator's own language."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    said = _order(level_min="6", star_wait_min=45).rule_text()
    assert "звезда" in said, said               # the priority, named
    assert "UR" in said, said
    assert "6" in said and "45" in said, said   # both numbers of the rule
    # …and zero is a different rule, not a duration of zero minutes.
    forever = _order(star_wait_min=0).rule_text()
    assert "0 мин" not in forever, forever
    assert "сброс" in forever, forever


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
