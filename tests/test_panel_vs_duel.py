r"""The «Дуэль VS» tab (panel/tabs/vs_duel.py) — the week, the boxes and what it keeps.

The tab is the duel PLAN: a group per weekday, a box per action that day scores, and a
ceiling beside the two Monday actions that spend something scarce. Nothing is played
from it yet, so what is worth pinning is the part a later wiring will trust:

* **the week starts on Monday and runs to Saturday** — the order the groups are drawn
  in is the order the operator reads the duel in, and it is data, not layout;
* **`plan()` answers with the ceilings, not with the raw text** — an empty box, junk
  and a zero all mean «no ceiling», never an exception in the middle of a run;
* **a profile round-trips**, and one that never set a ceiling gets the DEFAULT back
  rather than the number the previously open account was left on.

Needs Tk and a display; says SKIP under the WSL python3.

    C:\Python312\python.exe tests\test_panel_vs_duel.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "tools", ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else "  SKIP no tkinter")


def _tab():
    """A built «Дуэль VS» tab on a cold runtime, plus the root to destroy afterwards."""
    import tkinter as tk
    from tkinter import ttk
    import fake_runtime
    from panel.tabs.vs_duel import VsDuelTab

    root = tk.Tk()
    root.withdraw()
    rt = fake_runtime.cold_runtime(root)
    tab = VsDuelTab(rt, ttk.Frame(root))
    rt.tabs.add(tab)
    tab.build()
    return root, tab


# ---------------------------------------------------------------------------
# the week
# ---------------------------------------------------------------------------

def test_the_week_is_monday_first_and_ends_on_saturday():
    """Six groups, in the order the duel runs — the tab's whole shape, in one line."""
    from panel.tabs import vs_duel

    assert [day for day, _actions in vs_duel.DAYS] == [
        "mon", "tue", "wed", "thu", "fri", "sat"]
    # Monday is the one written out; the rest are placeholders a later task fills.
    filled = [day for day, actions in vs_duel.DAYS if actions]
    assert filled == ["mon"], filled


def test_monday_holds_the_three_actions_and_their_two_ceilings():
    from panel.tabs import vs_duel

    monday = dict(vs_duel.DAYS)["mon"]
    assert [a.key for a in monday] == ["drone_parts", "hero_level", "drone_level"]
    ceilings = {a.key: (a.amount.key if a.amount else None) for a in monday}
    assert ceilings == {"drone_parts": None, "hero_level": "hero_exp_m",
                        "drone_level": "drone_gears"}


def test_every_label_is_translated_in_both_shipped_locales():
    """A key only one locale has is a tab that reads half in English (#1199 rule)."""
    from panel.tabs import vs_duel

    keys = {"tab.vs_duel", "vsduel.hint", "vsduel.later"}
    for day, actions in vs_duel.DAYS:
        keys.add(f"vsduel.day.{day}")
        for action in actions:
            keys.add(action.label)
            if action.amount is not None:
                keys.add(action.amount.label)
    for lang in ("en", "ru"):
        table = json.loads((ROOT / "panel" / "locales" / f"{lang}.json")
                           .read_text(encoding="utf-8"))
        missing = sorted(k for k in keys if not table.get(k))
        assert not missing, f"{lang}.json is missing {missing}"


# ---------------------------------------------------------------------------
# what the wiring will read
# ---------------------------------------------------------------------------

def test_plan_lists_only_what_is_ticked_with_its_ceiling():
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        assert tab.plan("mon") == {}, "a fresh tab plans nothing"

        tab._flags["mon.hero_level"].set(True)
        tab._amounts["mon.hero_exp_m"].set("30")
        assert tab.plan("mon") == {"hero_level": 30}

        # An action with nothing countable to spend is ticked with no ceiling at all.
        tab._flags["mon.drone_parts"].set(True)
        assert tab.plan("mon") == {"drone_parts": None, "hero_level": 30}

        # A day nobody has written actions for plans nothing, and is not an error.
        assert tab.plan("tue") == {}
        assert tab.plan("nonesuch") == {}
    finally:
        root.destroy()


def test_an_empty_or_junk_ceiling_reads_as_no_ceiling():
    """The field aims a spend, so it always answers — never raises mid-run."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._flags["mon.drone_level"].set(True)
        for text in ("", "   ", "0", "abc"):
            tab._amounts["mon.drone_gears"].set(text)
            assert tab.plan("mon") == {"drone_level": None}, text
        tab._amounts["mon.drone_gears"].set("150")
        assert tab.plan("mon") == {"drone_level": 150}
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# what it keeps
# ---------------------------------------------------------------------------

def test_the_choices_round_trip_through_a_profile():
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._flags["mon.hero_level"].set(True)
        tab._amounts["mon.hero_exp_m"].set("12")
        saved = tab.config()
        assert saved["mon.hero_level"] is True
        assert saved["mon.hero_exp_m"] == "12"

        tab.apply_config({})                       # a profile that has never seen it
        assert tab.plan("mon") == {}
        assert tab._amounts["mon.hero_exp_m"].get() == "", "a default was inherited"

        tab.apply_config(saved)
        assert tab.plan("mon") == {"hero_level": 12}
        # Every variable a change of which must be written is offered to the container.
        # (By identity: a Tk variable is unhashable and compares by its VALUE.)
        offered = {id(v) for v in tab.persist_vars()}
        assert offered == {id(v) for v in
                           list(tab._flags.values()) + list(tab._amounts.values())}
    finally:
        root.destroy()


def test_a_ceiling_is_greyed_out_while_its_action_is_off():
    """It has nothing to limit — and a number in a dead field reads as being obeyed."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        entry, _flag = tab._entries["mon.hero_exp_m"]
        assert str(entry.cget("state")) == "disabled"
        tab._flags["mon.hero_level"].set(True)
        tab._sync_amounts()
        assert str(entry.cget("state")) == "normal"
    finally:
        root.destroy()


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
