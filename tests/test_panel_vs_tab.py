r"""The «VS» tab (panel/tabs/vs.py) — the duel week as a card per day (#2617).

The person asked for the week to be read the way the errands are read: «такие же
карточки как в таймерах, первая карточка, понедельник, можно сразу 6 карточек сделать по
дням недели». So what is worth pinning is not the plan — `test_panel_vs_duel.py` owns
that, and this tab IS that one — but the SHAPE the phone is handed:

* **six cards, Monday first**, in one `layout: "cards"` card — the shape `ui/ErrandCard`
  draws, and never a second card component of its own;
* **the day's own switch is ON the card**, because a row's one switch is what the row is
  about (#2068), and everything else is behind the gear, which opens in the one modal
  this front-end has;
* **the gear's knobs are the day's own** — the actions, the ceilings, the details and
  the picks, travelling back through the screen's own `set` press;
* **there is one page of the plan**, not two: the registry has `vs` and no `vs_duel`
  beside it, and a profile that named the old id is carried over.

Needs Tk and a display; says SKIP under the WSL python3.

    C:\Python312\python.exe tests\test_panel_vs_tab.py
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

LOCALES = ROOT / "panel" / "locales"

#: What the tab adds to the words it inherits from the plan it draws.
NEW_KEYS = ("tab.vs", "vs.week", "vs.day.actions", "vs.day.set",
            "vs.day.soon", "vsduel.drone_chips", "vsduel.drone_level",
            "vs.chips.title", "vs.chips.in_bag", "vs.chips.opened",
            "vs.chips.refresh", "vs.chips.read_at", "vs.chips.never",
            "vs.age.sec", "vs.age.min", "vs.age.hour", "vs.age.day")


def _tab():
    """A «VS» tab on a cold runtime, with the shipped sets loaded, plus its root."""
    import tkinter as tk
    from tkinter import ttk
    import fake_runtime
    from panel.tabs.vs import VsTab

    root = tk.Tk()
    root.withdraw()
    rt = fake_runtime.cold_runtime(root)
    tab = VsTab(rt, ttk.Frame(root))
    rt.tabs.add(tab)
    # The store outlives one test — the chest tally is kept on purpose (#2617) — so a
    # test that is about a FRESH profile has to start from one.
    try:
        from panel.runtime import store as storemod

        rt.store.blob_set(storemod.DRONE_CHIPS, {})
        tab._chips = None
    except Exception:                     # noqa: BLE001 — no store, no tally
        pass
    return root, tab


def _week(view: dict) -> dict:
    return view["cards"][0]


# ---------------------------------------------------------------------------
def test_the_week_is_six_cards_monday_first():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001 — no display
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        card = _week(tab.web_view())
        assert card["layout"] == "cards", card.get("layout")
        assert [item["label"] for item in card["items"]] == [
            "vsduel.day.mon", "vsduel.day.tue", "vsduel.day.wed",
            "vsduel.day.thu", "vsduel.day.fri", "vsduel.day.sat"], card["items"]
        assert all(item.get("shape") == "cover" for item in card["items"]), (
            "a day is drawn as the errand card, picture and all")
    finally:
        root.destroy()


def test_the_days_switch_is_on_the_card_and_its_knobs_are_behind_the_gear():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        monday = _week(tab.web_view())["items"][0]
        assert monday["toggle"]["key"] == "plan.mon.enabled", monday["toggle"]
        assert monday["toggle"]["value"] is True
        keys = [field["key"] for field in monday["options"]]
        assert "plan.mon.enabled" not in keys, (
            "the day's own switch is on the card, never repeated behind its gear")
        assert keys == ["plan.mon.drone_chips", "plan.mon.drone_level"], (
            "only what is wired is drawn (#2617) — %s" % keys)
        assert monday["options_title"] == "vsduel.day.mon"
    finally:
        root.destroy()


def test_a_press_moves_the_plan_and_the_card_says_so():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        before = _week(tab.web_view())["items"][0]["facts"][0]["value"]
        assert before == "2 / 2", before
        assert tab.web_press("set", {"key": "plan.mon.drone_chips",
                                     "value": False}) == {"ok": True}
        after = _week(tab.web_view())["items"][0]["facts"][0]["value"]
        assert after == "1 / 2", after
        assert tab.web_press("nope", {}) == {"error": "unknown"}
    finally:
        root.destroy()


def test_the_card_says_which_set_the_day_is_played_from():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        from panel.tabs.vs_duel import PRESET_PUSH

        assert tab.web_press("set", {"key": "dayset.mon",
                                     "value": PRESET_PUSH}) == {"ok": True}
        facts = _week(tab.web_view())["items"][0]["facts"]
        assert facts[1]["label"] == "vs.day.set"
        # The name is DATA — the operator may have renamed the set — so it is the
        # words, never a key.
        assert facts[1]["value"] == tab.t("vsduel.preset.push"), facts[1]
    finally:
        root.destroy()


def test_there_is_one_page_of_the_plan_and_the_old_id_is_carried_over():
    from panel.runtime.settings import SettingsBinder
    from panel.tabs import BY_ID

    assert "vs" in BY_ID and "vs_duel" not in BY_ID, sorted(BY_ID)
    spec = BY_ID["vs"]
    assert spec.title_key == "tab.vs", spec.title_key
    assert not spec.in_development, "«VS» is a page every profile can have"
    assert SettingsBinder._TAB_ID_MERGES.get("vs_duel") == "vs", (
        "a profile that named «Дуэль VS» keeps its answer")


def test_the_words_it_adds_are_in_every_shipped_locale():
    langs = sorted(p.stem for p in LOCALES.glob("*.json"))
    assert len(langs) >= 11, langs
    for lang in langs:
        table = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for key in NEW_KEYS:
            assert table.get(key), f"{lang}.json has no {key}"


def test_a_profile_that_never_saved_this_tab_still_reads_its_plan():
    """The week is in the variables the moment the tab exists — no block, no drawing.

    `panel/headless.py` restores only a block that is not empty, and the phone has no
    `build()` to fall back on: without this the screen said «0 / 4» over a plan the
    panel would have played in full.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        monday = _week(tab.web_view())["items"][0]
        assert monday["facts"][0]["value"] == "2 / 2", monday["facts"]
        assert any(field["key"] == "plan.mon.drone_chips" and field["value"] is True
                   for field in monday["options"]), monday["options"][:3]
    finally:
        root.destroy()


def test_only_the_wired_knobs_are_drawn_and_the_rest_of_the_week_says_so():
    """«Скрой все параметры, что еще не реализованы» (#2617).

    A tick over an ability nobody has written reads as a promise the bot will keep, and
    the bot will not. So Monday shows the one knob a scenario is behind, and the other
    five days show none at all and wear a word saying why.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        from panel.tabs.vs import READY, RUNS

        items = {item["label"]: item for item in _week(tab.web_view())["items"]}
        monday = items["vsduel.day.mon"]
        assert [f["key"] for f in monday["options"]] == ["plan.mon.drone_chips",
                                                         "plan.mon.drone_level"]
        assert monday.get("pill") is None
        for label in ("vsduel.day.tue", "vsduel.day.wed", "vsduel.day.thu",
                      "vsduel.day.fri", "vsduel.day.sat"):
            day = items[label]
            assert not day.get("options"), (label, day.get("options"))
            assert day.get("pill") == "vs.day.soon", label
            assert not day.get("actions"), label
        assert set(RUNS) <= set(READY), (RUNS, READY)
    finally:
        root.destroy()


def test_the_wired_knob_carries_the_button_that_plays_its_recipe():
    """A press runs the scenario and nothing else — no gate of the ability in the tab."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        played = []
        tab.rt.play_async = lambda name, *a, **k: played.append(name) or True

        monday = _week(tab.web_view())["items"][0]
        # ONE BUTTON PER ABILITY, each named after what it runs (#2617).
        assert monday["actions"] == [
            {"id": "run", "label": "vsduel.drone_chips", "icon": "run",
             "args": {"key": "mon.drone_chips"}},
            {"id": "run", "label": "vsduel.drone_level", "icon": "run",
             "args": {"key": "mon.drone_level"}}], monday.get("actions")
        assert tab.web_press("run", {"key": "mon.drone_chips"}) == {"ok": True}
        assert tab.web_press("run", {"key": "mon.drone_level"}) == {"ok": True}
        assert played == ["open_drone_chips", "upgrade_drone"], played
        # …and nothing else may be started through it, whatever it is asked for.
        assert tab.web_press("run", {"key": "tue.build_speedup"}) == {"error": "unknown"}
        assert tab.web_press("run", {}) == {"error": "unknown"}
        assert played == ["open_drone_chips", "upgrade_drone"], played
    finally:
        root.destroy()


def test_the_recipe_the_button_plays_exists_and_opens_the_chip_chests():
    """The ability is a scenario, and the panel only plays it (CLAUDE.md)."""
    recipe = ROOT / "src" / "lastwar_bot" / "actions" / "open_drone_chips.md"
    text = recipe.read_text(encoding="utf-8")
    assert "TAP use_bag_ids" in text, "the press is the catalogue's, never inline Lua"
    assert "ARGS ids = 540201,540301,540401" in text, (
        "the chest ids travel as an argument, not written into the press")
    # The DIFFERENT box is deliberately not opened — the person was asked which (#2617).
    # The prose says so out loud, so it is the RUNNING lines that are checked.
    running = "\n".join(line for line in text.splitlines()
                        if line.strip() and not line.lstrip().startswith("#"))
    for other in ("630011", "630012", "630013"):
        assert other not in running, (
            f"the drone-component chest {other} is not what this recipe opens")


def test_the_press_it_names_is_in_the_catalogue():
    import sys as _sys

    for path in (str(ROOT / "tools"), str(ROOT / "tools" / "lib")):
        if path not in _sys.path:
            _sys.path.insert(0, path)
    from lib import game_buttons

    button = game_buttons.BUTTONS.get("use_bag_ids")
    assert button is not None, "no such press: use_bag_ids"
    lua = button.lua
    assert "__lw_use_ids" in lua, "the ids are parked by the recipe"
    assert "MsgDefines.ItemUse" in lua, "the send is the bag's own item.use"
    # One call, not one per stack: the loop is inside the chunk (#2617).
    assert lua.count("SendMessage") == 1 and "for _, st in ipairs(mine)" in lua


def test_the_drone_recipe_reads_the_price_instead_of_knowing_it():
    """`upgrade_drone.md` — the ability, and the one thing it must never do: assume.

    The cost of a level is the client's own `cost_resItem` row and it changes as the
    drone climbs, so a number written into the recipe would be right for one account at
    one level. What is pinned here is that it reads, that it stops rather than fails when
    there is nothing to raise, and that it proves the level MOVED.
    """
    text = (ROOT / "src" / "lastwar_bot" / "actions" / "upgrade_drone.md").read_text(
        encoding="utf-8")
    running = "\n".join(line for line in text.splitlines()
                        if line.strip() and not line.lstrip().startswith("#"))
    assert "TAP drone_level_up xall" in running, "it spends what the bag pays for"
    assert "cost_resItem" in running, "the price is read, never written down"
    assert "42000" not in running and "7037" not in running, (
        "one account's price is not everybody's")
    assert running.count("STOP") == 3, "a ceiling and an empty bag are states, not failures"
    assert "FAIL" in running, "a press that did not move the level is a failure"


def test_the_drone_press_is_in_the_catalogue_and_proves_itself():
    import sys as _sys

    for path in (str(ROOT / "tools"), str(ROOT / "tools" / "lib")):
        if path not in _sys.path:
            _sys.path.insert(0, path)
    from lib import game_buttons

    button = game_buttons.BUTTONS.get("drone_level_up")
    assert button is not None, "no such press: drone_level_up"
    assert "MsgDefines.TacticalWeaponLevelUpMessage" in button.lua
    assert button.count_lua, "`xall` needs to know how many levels are affordable"
    assert button.verify_lua, "a press that changed nothing must fail, not report ok"


def _chips(view: dict) -> dict:
    for card in view["cards"]:
        if card.get("title") == "vs.chips.title":
            return card
    raise AssertionError("no chest card on the screen")


def test_the_chests_are_counted_under_the_knob_even_before_anything_is_read():
    """«Под чипами выведи статистику» (#2617) — a row per grade, from the first look.

    Nothing has been read yet on a fresh profile, so the counts are dashes and the note
    says so — a card that only appears once somebody presses «Обновить» is a card nobody
    finds.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        from panel.tabs.vs import CHIP_IDS

        card = _chips(tab.web_view())
        assert len(card["items"]) == len(CHIP_IDS), card["items"]
        for item, chest in zip(card["items"], CHIP_IDS):
            assert item["text"] == chest, item          # no name read yet: the id
            labels = [f["label"] for f in item["facts"]]
            assert labels == ["vs.chips.in_bag", "vs.chips.opened"], labels
            assert item["facts"][0]["value"] == "—"
            assert item["facts"][1]["value"] == "0"
            assert "icon" not in item, "no picture is drawn rather than a wrong one"
        assert card["actions"][0]["id"] == "chips_read"
        assert card["note"] == tab.t("vs.chips.never")
    finally:
        root.destroy()


def test_a_reading_fills_the_rows_and_an_opening_adds_to_the_tally():
    """What the two scenarios say is what the card shows — never a guess of the tab's.

    The bag half can always be re-read; the tally cannot, because an open chest is gone.
    So the opened count is added from the run's own `chips_per_id` line and kept.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        class _Outcome:
            def __init__(self, **vars_):
                self.ok = True
                self.ctx = type("C", (), {"vars": dict(vars_)})()

        tab._chips_rows_back(_Outcome(chips_rows=(
            "540201|31|3|icon_item_540201|Chest R ;; "
            "540301|10|4|icon_item_540301|Chest SR ;; "
            "540401|3|5||Chest SSR")))
        card = _chips(tab.web_view())
        assert [i["text"] for i in card["items"]] == ["Chest R", "Chest SR", "Chest SSR"]
        assert [i["facts"][0]["value"] for i in card["items"]] == ["31", "10", "3"]
        assert card["note"] != tab.t("vs.chips.never"), "the age is shown once it is read"
        # An id whose icon the game did not name draws none rather than a neighbour's.
        assert "icon" not in card["items"][2]

        tab._chips_opened_back(_Outcome(chips_per_id="540201:31,540401:3"))
        card = _chips(tab.web_view())
        assert [i["facts"][1]["value"] for i in card["items"]] == ["31", "0", "3"]
        # …and a second run ADDS to it rather than replacing it.
        tab._chips_opened_back(_Outcome(chips_per_id="540401:2"))
        assert _chips(tab.web_view())["items"][2]["facts"][1]["value"] == "5"
        # A run that opened nothing changes nothing at all.
        tab._chips_opened_back(_Outcome(chips_per_id="-"))
        assert _chips(tab.web_view())["items"][2]["facts"][1]["value"] == "5"
    finally:
        root.destroy()


def test_the_refresh_press_plays_the_reading_recipe_with_the_same_ids():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        from panel.tabs.vs import CHIP_IDS

        seen = []
        tab.rt.play_async = lambda name, args=None, **k: (
            seen.append((name, args, sorted(k))) or True)
        assert tab.web_press("chips_read", {}) == {"ok": True}
        name, args, kw = seen[0]
        assert name == "read_drone_chips" and args == {"ids": ",".join(CHIP_IDS)}
        assert "on_result" in kw, "what came back has to reach the store"
        # …and the opening run carries the same list and its own tally callback.
        assert tab.web_press("run", {"key": "mon.drone_chips"}) == {"ok": True}
        name, args, kw = seen[1]
        assert name == "open_drone_chips" and args == {"ids": ",".join(CHIP_IDS)}
        assert "on_result" in kw
    finally:
        root.destroy()


def test_the_reading_recipe_asks_and_opens_nothing():
    text = (ROOT / "src" / "lastwar_bot" / "actions" / "read_drone_chips.md").read_text(
        encoding="utf-8")
    running = "\n".join(line for line in text.splitlines()
                        if line.strip() and not line.lstrip().startswith("#"))
    assert "TAP" not in running, "a counting recipe presses nothing"
    assert "INTO chips_rows" in running


def test_the_week_is_the_screen_and_its_cards_are_the_errand_card():
    """«В vs основным экраном делай неделю… карточки должны быть как в таймерах» (#2621).

    Two halves, and both are data the front-end reads: the week card says it is the one
    the screen opens on, and every press on a day wears the errand card's own «▶» rather
    than the wide text button a screen's actions used to be.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        view = tab.web_view()
        week = view["cards"][0]
        assert week["title"] == "vs.week" and week.get("main") is True, week.get("main")
        assert [c for c in view["cards"] if c.get("main")] == [week], (
            "one main card, or the screen has two subjects")
        for action in view["cards"][0]["items"][0].get("actions") or ():
            assert action.get("icon") == "run", action
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
