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

TIER = "ui"        # Tk and a display — see tools/run_tests.py

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


def _actions(items):
    """The actions of a day — a day also holds picks of its own, and groups."""
    from panel.tabs.vs_duel import _Choice, walk_items

    return [i for i in walk_items(items) if not isinstance(i, _Choice)]


def _picks(items):
    """The picks the DAY makes, with no box above them (Saturday's shield)."""
    from panel.tabs.vs_duel import _Choice, walk_items

    return [i for i in walk_items(items) if isinstance(i, _Choice)]


def _tab(blank=True):
    """A built «Дуэль VS» tab on a cold runtime, plus the root to destroy afterwards.

    ``blank`` puts it on an EMPTY set — nothing ticked — because that is what most of
    these tests are about: what one box does. The shipped sets, which arrive with the
    week already ticked, have tests of their own below.
    """
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
    # …and shown, because that is when the week is drawn (#1211). Everything below is
    # about a tab somebody is looking at; the one test about the OTHER state — a built
    # but never-shown tab, which is every tab of a page that has just been opened —
    # builds its own.
    tab.on_show()
    if blank:
        tab.apply_config({"presets": [{"id": "blank", "name": "Blank", "values": {}}],
                          "days": {}})
    return root, tab


# ---------------------------------------------------------------------------
# the week
# ---------------------------------------------------------------------------

def test_the_week_is_monday_first_and_ends_on_saturday():
    """Six groups, in the order the duel runs — the tab's whole shape, in one line."""
    from panel.tabs import vs_duel

    assert [day for day, _items in vs_duel.DAYS] == [
        "mon", "tue", "wed", "thu", "fri", "sat"]
    # The whole week is written down now — no day is a placeholder any more.
    empty = [day for day, items in vs_duel.DAYS if not items]
    assert empty == [], empty


def test_each_day_holds_the_actions_it_scores():
    """The week, as the operator reads it — and no action listed twice inside a day."""
    from panel.tabs import vs_duel

    days = dict(vs_duel.DAYS)
    assert [a.key for a in _actions(days["mon"])] == [
        "drone_parts", "hero_level", "drone_level", "mines_before_reset"]
    assert [a.key for a in _actions(days["tue"])] == [
        "build_speedup", "build_collect", "survivor_tickets", "build_start"]
    assert [a.key for a in _actions(days["wed"])] == [
        "drone_parts", "research_speedup", "research_collect", "research_start"]
    assert [a.key for a in _actions(days["thu"])] == [
        "hero_level", "hero_rank_ur", "hero_rank_ssr", "honour_wall",
        "exclusive_weapon"]
    assert [a.key for a in _actions(days["fri"])] == [
        "lord_rank", "lord_train", "lord_skills", "lord_level", "unit_train",
        "unit_upgrade"]
    assert [a.key for a in _actions(days["sat"])] == ["shield_buy", "mine_points"]
    for day, items in vs_duel.DAYS:
        keys = [i.key for i in vs_duel.walk_items(items)]
        assert len(keys) == len(set(keys)), f"{day} lists something twice: {keys}"


def test_wednesdays_two_routines_are_two_groups():
    """The research that runs at any hour and the loop inside the minister's window are
    not one list of boxes: «speed it up» and «start one and hurry it» only stop reading
    as the same box because a frame with its own line separates them."""
    from panel.tabs import vs_duel

    wed = dict(vs_duel.DAYS)["wed"]
    groups = [i for i in wed if isinstance(i, vs_duel._Group)]
    assert [g.label for g in groups] == ["vsduel.wed.running", "vsduel.wed.ministry"]
    # Each says WHEN it applies — the five-minute window is the whole point of the
    # second one, and it is on screen rather than in a commit message.
    assert all(g.hint for g in groups), "a group with no line saying when it applies"

    always, window = groups
    assert [a.key for a in always.items] == ["research_speedup", "research_collect"]
    assert [a.key for a in window.items] == ["research_start"]
    # The category belongs to the loop in the window, not to the day's ordinary work.
    assert window.items[0].choice is not None
    assert all(a.choice is None for a in always.items)
    # Opening the drone components is neither routine — it stays the day's own box.
    assert [i.key for i in wed if not isinstance(i, vs_duel._Group)] == ["drone_parts"]


def test_the_ceilings_and_the_details_hang_off_the_right_actions():
    from panel.tabs import vs_duel

    days = dict(vs_duel.DAYS)
    ceilings = {f"{d}.{a.key}": (a.amount.key if a.amount else None)
                for d, items in vs_duel.DAYS for a in _actions(items)}
    assert {k: v for k, v in ceilings.items() if v} == {
        "mon.hero_level": "hero_exp_m", "mon.drone_level": "drone_gears",
        "thu.hero_level": "hero_exp_m"}
    subs = {f"{d}.{a.key}": [s.key for s in a.subs]
            for d, items in vs_duel.DAYS for a in _actions(items)}
    assert {k: v for k, v in subs.items() if v} == {
        "mon.hero_level": ["exp_boxes"], "tue.build_start": ["ministry"],
        "thu.hero_level": ["exp_boxes"], "thu.honour_wall": ["extra_chests"]}
    # Only starting a research is aimed at something, and «any» is what it starts on.
    choices = {f"{d}.{a.key}": a.choice for d, items in vs_duel.DAYS
               for a in _actions(items) if a.choice is not None}
    assert list(choices) == ["wed.research_start"]
    assert choices["wed.research_start"].default == vs_duel.CATEGORY_ANY


def test_an_action_scoring_on_two_days_is_written_once():
    """The hero and the drone components are the same control on both their days —
    same words, same ceiling, same details — with the day's settings kept apart."""
    from panel.tabs import vs_duel

    days = dict(vs_duel.DAYS)
    mon_hero = [a for a in _actions(days["mon"]) if a.key == "hero_level"][0]
    thu_hero = [a for a in _actions(days["thu"]) if a.key == "hero_level"][0]
    assert mon_hero.label == thu_hero.label
    assert mon_hero.amount.label == thu_hero.amount.label
    assert [s.label for s in mon_hero.subs] == [s.label for s in thu_hero.subs]
    assert [a for a in _actions(days["mon"]) if a.key == "drone_parts"][0].label == \
        [a for a in _actions(days["wed"]) if a.key == "drone_parts"][0].label
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

    keys = {"tab.vs_duel", "vsduel.hint"}
    for day, items in vs_duel.DAYS:
        keys.add(f"vsduel.day.{day}")
        for item in items:
            if isinstance(item, vs_duel._Group):
                keys.add(item.label)
                if item.hint:
                    keys.add(item.hint)
        for pick in _picks(items):
            keys.add(pick.label)
            keys.update(label for _v, label in pick.options)
        for action in _actions(items):
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
        # A day that is not in the week at all plans nothing, and is not an error.
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
    """Tuesday's ministry is a detail of starting a construction: it is HOW it starts."""
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
    finally:
        root.destroy()


def test_the_extra_chests_belong_to_the_wall_of_honour():
    """Same shape as the hero's experience boxes: it is how far the wall is pushed once
    what is in the bag runs out, not a sixth thing to do on Thursday."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._flags["thu.honour_wall.extra_chests"].set(True)
        assert tab.plan("thu") == {}, "the chests planned themselves with no wall"

        tab._flags["thu.honour_wall"].set(True)
        assert tab.plan("thu") == {"honour_wall": {"limit": None,
                                                   "extra_chests": True}}
        widget, _flag, _live = tab._dependents["thu.honour_wall.extra_chests"]
        tab._sync_dependents()
        assert str(widget.cget("state")) == "normal"
        tab._flags["thu.honour_wall"].set(False)
        tab._sync_dependents()
        assert str(widget.cget("state")) == "disabled"
    finally:
        root.destroy()


def test_wednesday_plans_flat_across_its_two_groups():
    """A group is a frame and a scope, not a namespace: an action keeps its own key
    wherever it is drawn, so the wiring reads one dict per day."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._flags["wed.research_speedup"].set(True)
        tab._flags["wed.research_start"].set(True)
        assert tab.plan("wed") == {
            "research_speedup": {"limit": None},
            "research_start": {"limit": None, "category": "any"}}
        # Either routine can be wanted without the other.
        tab._flags["wed.research_start"].set(False)
        assert list(tab.plan("wed")) == ["research_speedup"]
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# the day's own decision
# ---------------------------------------------------------------------------

def test_saturdays_shield_is_a_pick_the_day_always_answers():
    """Not «whether» but «which»: two twelve-hour shields or one that lasts a day. So
    it is in the plan even when nothing on Saturday is ticked."""
    from panel.tabs import vs_duel

    sat = dict(vs_duel.DAYS)["sat"]
    picks = _picks(sat)
    assert [p.key for p in picks] == ["shield"]
    assert [v for v, _label in picks[0].options] == ["twice_12h", "once_24h"]
    assert picks[0].radio, "a two-way decision drawn as a list hides one of its ways"

    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        assert tab.plan("sat") == {"shield": {"pick": "twice_12h"}}
        tab._choices["sat.shield"].set("once_24h")
        tab._flags["sat.shield_buy"].set(True)
        tab._flags["sat.mine_points"].set(True)
        assert tab.plan("sat") == {"shield": {"pick": "once_24h"},
                                   "shield_buy": {"limit": None},
                                   "mine_points": {"limit": None}}

        # It round-trips inside the day's set, like everything else on the day.
        saved = tab.config()
        assert saved["presets"][0]["values"]["sat.shield"] == "once_24h"
        tab.apply_config(saved)
        assert tab.plan("sat")["shield"] == {"pick": "once_24h"}
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# the picker
# ---------------------------------------------------------------------------

def test_the_categories_are_the_games_own_tabs():
    """The eighteen tabs of the Tech Center, read off the client's own config
    (docs/research/tech-center-tabs.md) — ids, not words, because that is what a
    scenario will aim with."""
    from panel.tabs import vs_duel

    cats = vs_duel.RESEARCH_CATEGORIES
    assert len(cats) == 18, len(cats)
    ids = [value for value, _key in cats]
    assert len(set(ids)) == 18, "a tab id is listed twice"
    assert all(v.isdigit() for v in ids), ids
    assert set(ids) == {str(n) for n in range(1, 19)}, "the eighteen tabs are not all there"
    # Display order, which is NOT id order: the truck tab is drawn tenth.
    assert ids[:9] == ["1", "2", "3", "4", "5", "6", "7", "8", "9"], ids
    assert ids[9] == "13", ids
    assert ids[-1] == "18", ids
    # «any» is not one of them — it is the picker's own first option.
    assert vs_duel.CATEGORY_ANY not in ids
    picker = vs_duel._research_category()
    assert picker.options[0] == (vs_duel.CATEGORY_ANY,
                                 "vsduel.research_category.any")
    assert len(picker.options) == 19
    # Each carries its own key, and no key is shared between two tabs.
    keys = [key for _v, key in cats]
    assert len(set(keys)) == 18
    assert all(k.startswith("vsduel.research_category.") for k in keys)

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
    """What is on screen belongs to the day's SET, and the set is what is written."""
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
        values = saved["presets"][0]["values"]
        assert values["mon.hero_level"] is True
        assert values["mon.hero_level.exp_boxes"] is True
        assert values["mon.hero_exp_m"] == "12"
        assert set(saved["days"]) == {"mon", "tue", "wed", "thu", "fri", "sat"}

        tab.apply_config(saved)
        assert tab.plan("mon") == {"hero_level": {"limit": 12, "exp_boxes": True}}
        # Every variable a change of which must be written is offered to the container —
        # the day's own set-picker among them. (By identity: a Tk variable is
        # unhashable and compares by its VALUE.)
        offered = {id(v) for v in tab.persist_vars()}
        assert offered == {id(v) for v in (list(tab._flags.values())
                                           + list(tab._amounts.values())
                                           + list(tab._choices.values())
                                           + list(tab._day_set.values()))}
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
        assert saved["presets"][0]["values"][name] == "something_the_game_will_name"

        # A profile that has never seen the tab gets the shipped sets, on «any».
        tab.apply_config({})
        assert tab._choices[name].get() == vs_duel.CATEGORY_ANY
        tab.apply_config(saved)
        assert tab.plan("wed")["research_start"]["category"] == \
            "something_the_game_will_name"
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# the sets
# ---------------------------------------------------------------------------

def test_the_two_shipped_sets_differ_in_what_they_spend():
    """«Hoarding» and «Push» do the same things — what tells them apart is whether they
    break into what the account is storing."""
    from panel.tabs import vs_duel

    sets = {p["id"]: p for p in vs_duel.default_presets()}
    assert list(sets) == [vs_duel.PRESET_HOARD, vs_duel.PRESET_PUSH]
    # Named by a locale key, so they read in the panel's own language.
    assert all(p["name_key"] and not p["name"] for p in sets.values())

    hoard = sets[vs_duel.PRESET_HOARD]["values"]
    push = sets[vs_duel.PRESET_PUSH]["values"]
    # Both DO the week: push ticks every box there is, and hoarding skips only the one
    # whose whole purpose is to spend — buying shields.
    for day, items in vs_duel.DAYS:
        for action in _actions(items):
            key = f"{day}.{action.key}"
            assert push[key] is True, f"push skips {key}"
            assert hoard[key] is (key != "sat.shield_buy"), f"hoarding is wrong on {key}"
    # …and they differ exactly where something stored would be spent.
    differs = {k for k in push if hoard.get(k) != push.get(k)}
    assert differs == {"mon.hero_level.exp_boxes", "thu.hero_level.exp_boxes",
                       "sat.shield_buy", "sat.shield"}, differs
    assert push["mon.hero_level.exp_boxes"] is True
    assert hoard["mon.hero_level.exp_boxes"] is False
    assert hoard["sat.shield_buy"] is False and push["sat.shield_buy"] is True
    # One shield covering the day costs one; two half-days cost two.
    assert hoard["sat.shield"] == "once_24h" and push["sat.shield"] == "twice_12h"


def test_each_day_is_played_from_the_set_its_own_picker_names():
    """Monday hoarding while Saturday pushes — and neither day's numbers leak into the
    other's set."""
    from panel.tabs import vs_duel

    try:
        root, tab = _tab(blank=False)
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        assert {v.get() for v in tab._day_set.values()} == {vs_duel.PRESET_HOARD}
        # Saturday moves to «Push»: what it shows changes, Monday's does not.
        tab._day_set["sat"].set(vs_duel.PRESET_PUSH)
        tab._load_day("sat")
        assert tab.plan("sat")["shield"] == {"pick": "twice_12h"}
        assert tab.plan("sat")["shield_buy"] == {"limit": None}
        assert tab.plan("mon")["hero_level"]["exp_boxes"] is False

        # Editing Saturday writes into PUSH, and hoarding is left as it was.
        tab._flags["sat.mine_points"].set(False)
        saved = tab.config()
        by_id = {p["id"]: p["values"] for p in saved["presets"]}
        assert by_id[vs_duel.PRESET_PUSH]["sat.mine_points"] is False
        assert by_id[vs_duel.PRESET_HOARD]["sat.mine_points"] is True
        assert saved["days"]["sat"] == vs_duel.PRESET_PUSH
        assert saved["days"]["mon"] == vs_duel.PRESET_HOARD
    finally:
        root.destroy()


def test_a_day_switched_to_another_set_keeps_the_first_ones_numbers():
    """Switching is not editing: the set left behind still holds what was typed into
    it, and coming back shows it again."""
    from panel.tabs import vs_duel

    try:
        root, tab = _tab(blank=False)
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._amounts["mon.hero_exp_m"].set("25")
        tab._store_day("mon")                      # what the picker does before it moves
        tab._day_set["mon"].set(vs_duel.PRESET_PUSH)
        tab._load_day("mon")
        assert tab._amounts["mon.hero_exp_m"].get() == ""

        tab._amounts["mon.hero_exp_m"].set("999")
        tab._store_day("mon")
        tab._day_set["mon"].set(vs_duel.PRESET_HOARD)
        tab._load_day("mon")
        assert tab._amounts["mon.hero_exp_m"].get() == "25"
    finally:
        root.destroy()


def test_a_profile_written_before_the_sets_keeps_its_choices():
    """One flat week is what the tab used to save. It becomes the first set, and every
    day is played from it — the operator finds their own choices where they left them."""
    try:
        root, tab = _tab(blank=False)
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab.apply_config({"mon.hero_level": True, "mon.hero_exp_m": "7",
                          "mon.drone_level": False})
        assert tab.plan("mon")["hero_level"]["limit"] == 7
        assert "drone_level" not in tab.plan("mon")
        assert len({v.get() for v in tab._day_set.values()}) == 1
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# making, renaming and dropping a set — the store, with no Tk in the way
# ---------------------------------------------------------------------------

def test_the_store_makes_renames_and_drops_sets():
    from panel.tabs import vs_duel

    def t(key):                       # a stand-in translator: the key IS the name
        return key

    store = vs_duel.PresetStore()
    assert store.ids() == [vs_duel.PRESET_HOARD, vs_duel.PRESET_PUSH]
    assert store.name(vs_duel.PRESET_HOARD, t) == "vsduel.preset.hoard"

    mine = store.add("Week of the boss", {"mon.hero_level": True})
    assert store.name(mine, t) == "Week of the boss"
    assert store.values(mine)["mon.hero_level"] is True

    # A rename replaces the shipped key: from then on it is the person's name, in
    # every language.
    store.rename(vs_duel.PRESET_HOARD, "Quiet week")
    assert store.name(vs_duel.PRESET_HOARD, t) == "Quiet week"

    assert store.remove(vs_duel.PRESET_PUSH)
    assert vs_duel.PRESET_PUSH not in store.ids()
    assert not store.remove("nonesuch")

    # The last one cannot go — a day has to be played from something.
    store.remove(mine)
    assert len(store.ids()) == 1
    assert not store.remove(store.first())
    assert store.ids() == [vs_duel.PRESET_HOARD]


def test_the_store_survives_a_hand_edited_profile():
    """Junk in the file is «the shipped sets», never a crash on start-up."""
    from panel.tabs import vs_duel

    for junk in (None, [], "sets", [{"no": "id"}], [{"id": ""}], 17):
        store = vs_duel.PresetStore(junk)
        assert store.ids() == [vs_duel.PRESET_HOARD, vs_duel.PRESET_PUSH], junk
    # A record missing everything but its id is still a set, with nothing in it.
    store = vs_duel.PresetStore([{"id": "bare"}])
    assert store.ids() == ["bare"]
    assert store.values("bare") == {}


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


def test_a_day_that_is_switched_off_plans_nothing():
    """The box in a group's title is the day's master switch: unticked, the day is not
    played at all — not «played with whatever happens to be ticked inside it»."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        from panel.tabs.vs_duel import DAY_ENABLED

        tab._flags["mon.hero_level"].set(True)
        assert tab.plan("mon") == {"hero_level": {"limit": None, "exp_boxes": False}}

        tab._flags[f"mon.{DAY_ENABLED}"].set(False)
        assert tab.plan("mon") == {}, "a day nobody plays still handed out actions"
        # Saturday's shield is the one thing a day always answers with — unless the
        # day is not played.
        assert "shield" in tab.plan("sat")
        tab._flags[f"sat.{DAY_ENABLED}"].set(False)
        assert tab.plan("sat") == {}

        # The boxes are NOT cleared: switching the day back on brings the plan back.
        tab._flags[f"mon.{DAY_ENABLED}"].set(True)
        assert tab.plan("mon") == {"hero_level": {"limit": None, "exp_boxes": False}}
    finally:
        root.destroy()


def test_a_day_switched_off_greys_out_everything_but_its_own_two_controls():
    """Its actions, their ceilings, its radio buttons and its groups all go grey. The
    switch stays live, obviously — and so does the picker that says which set the switch
    itself is read from, or a day switched off in one week could never be moved to
    another."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        from panel.tabs.vs_duel import DAY_ENABLED

        day_on = tab._flags[f"mon.{DAY_ENABLED}"]
        mine = [w for w, var, _live in tab._day_gated if var is day_on]
        assert len(mine) >= 4, f"only {len(mine)} widgets follow Monday's switch"

        tab._flags["mon.hero_level"].set(True)
        tab._sync_dependents()
        ceiling = tab._dependents["mon.hero_exp_m"][0]
        assert str(ceiling.cget("state")) == "normal"

        day_on.set(False)
        tab._sync_dependents()
        assert all(str(w.cget("state")) == "disabled" for w in mine)
        # A ticked action inside a day that is off greys out with it, ceiling and all.
        assert str(ceiling.cget("state")) == "disabled"
        # Not the picker: it chooses the set the switch above it lives in.
        assert str(tab._day_combos["mon"].cget("state")) == "readonly"
        # And not another day.
        others = [w for w, var, _l in tab._day_gated
                  if var is tab._flags[f"tue.{DAY_ENABLED}"]]
        assert all(str(w.cget("state")) == "normal" for w in others)

        day_on.set(True)
        tab._sync_dependents()
        assert all(str(w.cget("state")) == "normal" for w in mine)
        assert str(ceiling.cget("state")) == "normal"
    finally:
        root.destroy()


def test_whether_a_day_is_played_belongs_to_the_set_and_survives_a_profile():
    """It is a setting like any other: «hoard» may sit a day out that «push» plays, and
    it round-trips. A set written before the switch existed says nothing about it — and
    that has to read as ON, because those weeks were played in full."""
    try:
        root, tab = _tab(blank=False)
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        from panel.tabs import vs_duel

        # Both shipped sets play the whole week to begin with.
        for record in vs_duel.default_presets():
            for day, _items in vs_duel.DAYS:
                assert record["values"][f"{day}.{vs_duel.DAY_ENABLED}"] is True

        hoard, push = vs_duel.PRESET_HOARD, vs_duel.PRESET_PUSH
        tab._day_set["thu"].set(hoard)
        tab._load_day("thu")
        tab._flags[f"thu.{vs_duel.DAY_ENABLED}"].set(False)
        saved = json.loads(json.dumps(tab.config()))

        root.destroy()
        root, tab = _tab(blank=False)
        tab.apply_config(saved)
        assert tab._flags[f"thu.{vs_duel.DAY_ENABLED}"].get() is False
        # The other set still plays Thursday — the switch went into ONE week.
        tab._day_set["thu"].set(push)
        tab._load_day("thu")
        assert tab._flags[f"thu.{vs_duel.DAY_ENABLED}"].get() is True

        # A profile from before the switch: no key at all, and the day is played.
        tab.apply_config({"presets": [{"id": "old", "name": "Old", "values": {}}],
                          "days": {}})
        assert all(tab._flags[f"{day}.{vs_duel.DAY_ENABLED}"].get() is True
                   for day, _items in vs_duel.DAYS)
    finally:
        root.destroy()


def test_the_week_is_drawn_two_days_to_a_row_starting_at_monday():
    """Six groups in one column is a page the week cannot be seen on. Two columns, read
    left to right and then down, so Monday is still the first thing on it."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        import tkinter as tk
        from tkinter import ttk
        from panel.tabs import vs_duel

        assert vs_duel.DAY_COLUMNS == 2
        placed = {}
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.LabelFrame):
                    try:
                        info = child.grid_info()
                    except tk.TclError:
                        info = {}
                    if info:
                        placed[(int(info["row"]), int(info["column"]))] = child
                walk(child)
        walk(tab.parent)

        assert sorted(placed) == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
        # The order on screen is the order of DAYS, row by row.
        titles = [str(root.nametowidget(placed[cell].cget("labelwidget")).cget("text"))
                  for cell in sorted(placed)]
        assert titles == [tab.t(f"vsduel.day.{day}") for day, _items in vs_duel.DAYS]
    finally:
        root.destroy()


def test_the_text_wraps_to_the_column_it_is_drawn_in():
    """Half a panel is not wide enough for the longest labels, so they wrap to whatever
    the day's frame is — and a ttk box takes that through a STYLE, since `wraplength` is
    an option a Checkbutton has never had.

    The width is fed in by hand: a withdrawn window applies no geometry, so asking Tk to
    resize one and believing the answer would be a test of nothing.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        from panel.tabs.vs_duel import DAYS

        assert tab._wrapped, "no day registered anything that wraps"
        boxes = list(tab._wrapped)
        assert len(boxes) == len(DAYS), "a day whose text does not wrap"
        box = boxes[0]
        # The wrap follows the frame, so the frame has to be watched for resizes.
        assert box.bind("<Configure>"), "nothing re-wraps when the column changes"

        # A box carries its wrap on a style of its own; a Label takes it as an option.
        styled = [(w, s) for w, _i, s in tab._wrapped[box] if s]
        assert styled and all(str(w.cget("style")) == s for w, s in styled)

        def wraps_at(width):
            # Mapped as well as sized: a page nobody is looking at is not re-wrapped at
            # all (see the test below), and a withdrawn window maps nothing.
            box.winfo_width = lambda w=width: w
            box.winfo_ismapped = lambda: 1
            tab._rewrap(box)
            return dict(tab._wrap_at)

        narrow, wide = wraps_at(360), wraps_at(700)
        assert all(wide[k] > narrow[k] for k in narrow), f"{narrow} -> {wide}"
        # The deeper a widget sits, the less room it has left. The styles are named per
        # tab and per day frame (#1211), so they are looked up by the indent they were
        # registered with rather than by a name spelled out here.
        by_indent = {indent: style for _w, indent, style in tab._wrapped[box] if style}
        deep, shallow = max(by_indent), min(by_indent)
        assert deep > shallow, "nothing in a day is indented under anything else"
        assert wide[by_indent[deep]] < wide[by_indent[shallow]]
        # Below the floor the words would break one per line, which is worse than a
        # little clipping — so the wrap stops shrinking.
        assert set(wraps_at(60).values()) == {tab._WRAP_FLOOR}
    finally:
        root.destroy()


def test_a_wrap_reaches_this_tab_only_and_this_day_only():
    """A ttk style belongs to the INTERPRETER, so a shared style name is a shared
    layout: while `VsDuelWrap<indent>` was the name, re-wrapping Monday re-laid Tuesday
    out — and re-laid out the same tab in every other open profile, page not even on
    screen, which is a switch that freezes for seconds (#1211).

    Two things are asserted, and they are the whole of the fix: no two day frames share
    a style, and no two tabs do either.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        from tkinter import ttk
        import fake_runtime
        from panel.tabs.vs_duel import VsDuelTab

        per_box = {box: {s for _w, _i, s in items if s}
                   for box, items in tab._wrapped.items()}
        assert all(per_box.values()), "a day whose boxes carry no style at all"
        for one, mine in per_box.items():
            for other, theirs in per_box.items():
                if one is not other:
                    assert not (mine & theirs), f"two days share {mine & theirs}"

        second = VsDuelTab(fake_runtime.cold_runtime(root), ttk.Frame(root))
        second.build()
        second.on_show()                       # its week is drawn on show, as ours was
        ours = {s for items in tab._wrapped.values() for _w, _i, s in items if s}
        theirs = {s for items in second._wrapped.values() for _w, _i, s in items if s}
        assert ours and theirs and not (ours & theirs), "two tabs share a wrap style"
    finally:
        root.destroy()


def test_the_week_is_drawn_on_first_show_and_not_before():
    """Building the week cost the PAGE 2.3 seconds against 67–210 ms for every other
    tab (#1211), and a page is built when the panel opens and when a profile is switched
    to for the first time. So `build()` leaves it undrawn — and everything that is not
    the widgets must answer exactly the same meanwhile: the plan the scenarios read, the
    settings the profile saves, the sets those live in.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
        import fake_runtime
        from panel.tabs.vs_duel import VsDuelTab, DAYS

        root = tk.Tk(); root.withdraw()
        rt = fake_runtime.cold_runtime(root)
        tab = VsDuelTab(rt, ttk.Frame(root))
        tab.build()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        assert not tab._week_built, "the week was drawn at build time"
        assert tab._wrapped == {}, "a day frame exists before anybody looked"

        # …and the tab answers for its whole week regardless.
        day = DAYS[0][0]
        tab.apply_config({"presets": [{"id": "s", "name": "S",
                                       "values": {f"{day}.hero_level": True}}],
                          "days": {day: "s"}})
        assert tab.plan(day).get("hero_level") is not None, "an undrawn week has no plan"
        assert tab.config()["presets"], "an undrawn week saves nothing"
        assert tab.persist_vars(), "an undrawn week binds no variables"

        tab.on_show()
        assert tab._week_built and len(tab._wrapped) == len(DAYS)
        shown = tab.plan(day)
        tab.on_show()                                   # idempotent: no second week
        assert len(tab._wrapped) == len(DAYS) and tab.plan(day) == shown
    finally:
        root.destroy()


def test_a_page_nobody_is_looking_at_is_not_re_wrapped():
    """…and is wrapped the moment somebody does look.

    A tab being built gets <Configure> for every width its column passes through, and
    so does one belonging to a profile whose page is behind another. Answering them
    re-lays out a page nobody can see — in the middle of building the page they can.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        box = list(tab._wrapped)[0]
        box.winfo_width = lambda: 700
        box.winfo_ismapped = lambda: 0
        tab._wrap_at.clear()
        tab._rewrap(box)
        assert tab._wrap_at == {}, "an unseen page was re-wrapped anyway"

        # `on_show` is the moment it becomes worth answering — and the moment the width
        # is the real one rather than whatever the build was passing through.
        box.winfo_ismapped = lambda: 1
        tab.on_show()
        assert tab._wrap_at, "showing the tab did not wrap it"
    finally:
        root.destroy()


def test_a_storm_of_resizes_is_one_re_wrap():
    """Building the page walks each frame through several widths, and wrapping on every
    one of them re-lays the whole page out again — which is a second of half-drawn lines
    over half-drawn lines. The burst has to collapse into a single idle-time pass."""
    try:
        root, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        box = list(tab._wrapped)[0]
        passes = []
        real = tab._rewrap
        tab._rewrap = lambda b, _r=real: (passes.append(b), _r(b))[1]
        for _ in range(4):                  # let the build's own layout finish first
            root.update()
        passes.clear()

        for _ in range(20):
            tab._rewrap_soon(box)
        assert passes == [], "a resize re-wrapped on the spot instead of at idle time"
        assert len(tab._rewrap_due) == 1, "a pass queued per event, not per burst"

        root.update()                                   # idle time arrives
        mine = [b for b in passes if b is box]
        assert len(mine) == 1, f"{len(mine)} passes for one burst of twenty resizes"
        assert box not in tab._rewrap_due, "the queued pass was never cleared"

        # And the next burst queues again — this is a coalescer, not a one-shot.
        passes.clear()
        tab._rewrap_soon(box)
        root.update()
        assert [b for b in passes if b is box] == [box]
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
