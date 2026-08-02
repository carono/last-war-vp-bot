r"""The «Дуэль VS» tab (panel/tabs/vs_duel.py) — the week, the boxes and what it keeps.

The tab is the duel PLAN: a group per weekday, a box per action that day scores, and —
under an action — the ceiling it spends against, the details of how it is done and the
pick of what to aim it at. Nothing is played from it yet, so what is worth pinning is
the part a later wiring will trust:

* **the week starts on Monday and runs to Saturday** — the order the groups are drawn
  in is the order the operator reads the duel in, and it is data, not layout;
* **an action that scores on two days is ONE control** — the hero (Monday, Thursday)
  and the drone components (Monday, Wednesday) read the same and behave the same, but
  keep their days' settings apart;
* **`plan()` answers with the ceilings, not with the raw text** — an empty box, junk
  and a zero all mean «no ceiling», never an exception in the middle of a run;
* **an action's own boxes belong to it** — «open experience boxes» is a detail of
  levelling the hero, so it is greyed out with it and never reaches a plan the hero
  action is not in;
* **a picker keeps the value, not the words on screen** — the research category
  survives a language change, and the list itself is re-filled in the new language;
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
    # Saturday is the one still to be written down; the five before it are filled.
    empty = [day for day, actions in vs_duel.DAYS if not actions]
    assert empty == ["sat"], empty


def test_each_day_holds_the_actions_it_scores():
    """The week, as the operator reads it — and no action listed twice inside a day."""
    from panel.tabs import vs_duel

    days = dict(vs_duel.DAYS)
    assert [a.key for a in days["mon"]] == [
        "drone_parts", "hero_level", "drone_level"]
    assert [a.key for a in days["tue"]] == [
        "build_speedup", "build_collect", "survivor_tickets", "build_start"]
    assert [a.key for a in days["wed"]] == [
        "drone_parts", "research_speedup", "research_collect", "research_start"]
    assert [a.key for a in days["thu"]] == [
        "hero_level", "hero_rank_ur", "hero_rank_ssr", "honour_wall",
        "honour_wall_chests", "exclusive_weapon"]
    assert [a.key for a in days["fri"]] == [
        "lord_rank", "lord_train", "lord_skills", "lord_level", "unit_train",
        "unit_upgrade"]
    for day, actions in vs_duel.DAYS:
        keys = [a.key for a in actions]
        assert len(keys) == len(set(keys)), f"{day} lists an action twice: {keys}"


def test_the_ceilings_and_the_details_hang_off_the_right_actions():
    from panel.tabs import vs_duel

    days = dict(vs_duel.DAYS)
    ceilings = {f"{d}.{a.key}": (a.amount.key if a.amount else None)
                for d, actions in vs_duel.DAYS for a in actions}
    assert {k: v for k, v in ceilings.items() if v} == {
        "mon.hero_level": "hero_exp_m", "mon.drone_level": "drone_gears",
        "thu.hero_level": "hero_exp_m"}
    subs = {f"{d}.{a.key}": [s.key for s in a.subs]
            for d, actions in vs_duel.DAYS for a in actions}
    assert {k: v for k, v in subs.items() if v} == {
        "mon.hero_level": ["exp_boxes"], "tue.build_start": ["ministry"],
        "wed.research_start": ["ministry"], "thu.hero_level": ["exp_boxes"]}
    # Only starting a research is aimed at something, and «any» is what it starts on.
    choices = {f"{d}.{a.key}": a.choice for d, actions in vs_duel.DAYS
               for a in actions if a.choice is not None}
    assert list(choices) == ["wed.research_start"]
    assert choices["wed.research_start"].default == vs_duel.CATEGORY_ANY
    # The categories themselves are deliberately not invented: until they are read off
    # a live client the picker offers «any» alone (see the TODO on the constant).
    assert vs_duel.RESEARCH_CATEGORIES == ()


def test_an_action_scoring_on_two_days_is_written_once():
    """The hero and the drone components are the same control on both their days —
    same words, same ceiling, same details — with the day's settings kept apart."""
    from panel.tabs import vs_duel

    days = dict(vs_duel.DAYS)
    mon_hero = [a for a in days["mon"] if a.key == "hero_level"][0]
    thu_hero = [a for a in days["thu"] if a.key == "hero_level"][0]
    assert mon_hero.label == thu_hero.label
    assert mon_hero.amount.label == thu_hero.amount.label
    assert [s.label for s in mon_hero.subs] == [s.label for s in thu_hero.subs]
    assert [a for a in days["mon"] if a.key == "drone_parts"][0].label == \
        [a for a in days["wed"] if a.key == "drone_parts"][0].label
    # …and the SETTINGS are not shared: two days, two ceilings.
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._flags["mon.hero_level"].set(True)
        tab._amounts["mon.hero_exp_m"].set("10")
        tab._flags["thu.hero_level"].set(True)
        tab._amounts["thu.hero_exp_m"].set("40")
        assert tab.plan("mon")["hero_level"]["limit"] == 10
        assert tab.plan("thu")["hero_level"]["limit"] == 40
    finally:
        root.destroy()


def test_every_label_is_translated_in_every_shipped_locale():
    """A key one locale is missing falls back to English silently — CLAUDE.md forbids
    it, and this is the tab's own half of that check."""
    from panel.tabs import vs_duel

    keys = {"tab.vs_duel", "vsduel.hint", "vsduel.later"}
    for day, actions in vs_duel.DAYS:
        keys.add(f"vsduel.day.{day}")
        for action in actions:
            keys.add(action.label)
            if action.amount is not None:
                keys.add(action.amount.label)
            keys.update(sub.label for sub in action.subs)
            if action.choice is not None:
                keys.add(action.choice.label)
                keys.update(label for _v, label in action.choice.options)
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(k for k in keys if not table.get(k))
        assert not missing, f"{path.name} is missing {missing}"


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
        assert tab.plan("mon") == {"hero_level": {"limit": 30, "exp_boxes": False}}

        # An action with nothing countable to spend is ticked with no ceiling at all.
        tab._flags["mon.drone_parts"].set(True)
        assert tab.plan("mon") == {"drone_parts": {"limit": None},
                                   "hero_level": {"limit": 30, "exp_boxes": False}}

        # Another day's boxes are its own: nothing of Monday's leaks into Tuesday.
        assert tab.plan("tue") == {}
        # A day nobody has written actions for plans nothing, and is not an error.
        assert tab.plan("sat") == {}
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
            assert tab.plan("mon") == {"drone_level": {"limit": None}}, text
        tab._amounts["mon.drone_gears"].set("150")
        assert tab.plan("mon") == {"drone_level": {"limit": 150}}
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# an action's own boxes
# ---------------------------------------------------------------------------

def test_the_experience_boxes_belong_to_levelling_the_hero():
    """It is a detail of that action, not a fourth action: it reaches a plan only
    through the hero, and it goes grey the moment the hero is unticked."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._flags["mon.hero_level.exp_boxes"].set(True)
        assert tab.plan("mon") == {}, "it planned itself with its action switched off"

        tab._flags["mon.hero_level"].set(True)
        tab._amounts["mon.hero_exp_m"].set("50")
        assert tab.plan("mon") == {"hero_level": {"limit": 50, "exp_boxes": True}}

        widget, _flag, _live = tab._dependents["mon.hero_level.exp_boxes"]
        tab._sync_dependents()
        assert str(widget.cget("state")) == "normal"
        tab._flags["mon.hero_level"].set(False)
        tab._sync_dependents()
        assert str(widget.cget("state")) == "disabled"
    finally:
        root.destroy()


def test_a_ministry_box_belongs_to_the_action_that_starts_the_work():
    """The same shape on Tuesday and Wednesday: it is HOW the work is started."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._flags["tue.build_start.ministry"].set(True)
        assert tab.plan("tue") == {}, "the ministry planned itself with no construction"
        tab._flags["tue.build_start"].set(True)
        assert tab.plan("tue") == {"build_start": {"limit": None, "ministry": True}}

        tab._flags["wed.research_start"].set(True)
        assert tab.plan("wed") == {"research_start": {
            "limit": None, "ministry": False, "category": "any"}}
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# the picker
# ---------------------------------------------------------------------------

def test_the_category_picker_keeps_a_value_and_survives_a_language_change():
    """What is stored is the VALUE, never the words that were on screen — otherwise a
    plan made in Russian aims at «любая» and no scenario knows what that is."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel.tabs import vs_duel
    try:
        name = "wed.research_start.category"
        assert tab._choices[name].get() == vs_duel.CATEGORY_ANY
        combo, choice = tab._combos[name]
        assert list(combo.cget("values")) == [tab.t(k) for _v, k in choice.options]

        # A language change re-fills the list and leaves the value where it was.
        tab.on_language_change()
        assert tab._choices[name].get() == vs_duel.CATEGORY_ANY
        assert combo.current() == 0

        # …and it is greyed out — as a readonly box, not an editable one — while the
        # action it aims is off.
        tab._sync_dependents()
        assert str(combo.cget("state")) == "disabled"
        tab._flags["wed.research_start"].set(True)
        tab._sync_dependents()
        assert str(combo.cget("state")) == "readonly", "it became a free text field"
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
        tab._flags["mon.hero_level.exp_boxes"].set(True)
        tab._amounts["mon.hero_exp_m"].set("12")
        saved = tab.config()
        assert saved["mon.hero_level"] is True
        assert saved["mon.hero_level.exp_boxes"] is True
        assert saved["mon.hero_exp_m"] == "12"

        tab.apply_config({})                       # a profile that has never seen it
        assert tab.plan("mon") == {}
        assert tab._amounts["mon.hero_exp_m"].get() == "", "a default was inherited"

        tab.apply_config(saved)
        assert tab.plan("mon") == {"hero_level": {"limit": 12, "exp_boxes": True}}
        # Every variable a change of which must be written is offered to the container.
        # (By identity: a Tk variable is unhashable and compares by its VALUE.)
        offered = {id(v) for v in tab.persist_vars()}
        assert offered == {id(v) for v in (list(tab._flags.values())
                                           + list(tab._amounts.values())
                                           + list(tab._choices.values()))}
    finally:
        root.destroy()


def test_a_picked_category_round_trips_and_defaults_back():
    from panel.tabs import vs_duel

    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        name = "wed.research_start.category"
        tab._flags["wed.research_start"].set(True)
        tab._choices[name].set("something_the_game_will_name")
        saved = tab.config()
        assert saved[name] == "something_the_game_will_name"

        # A profile that never picked one comes back to «any», not to what the last
        # account left behind.
        tab.apply_config({})
        assert tab._choices[name].get() == vs_duel.CATEGORY_ANY
        tab.apply_config(saved)
        assert tab.plan("wed")["research_start"]["category"] == \
            "something_the_game_will_name"
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
        entry, _flag, _live = tab._dependents["mon.hero_exp_m"]
        assert str(entry.cget("state")) == "disabled"
        tab._flags["mon.hero_level"].set(True)
        tab._sync_dependents()
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
