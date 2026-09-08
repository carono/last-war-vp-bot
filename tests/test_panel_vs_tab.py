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
            "vs.chips.read_at", "vs.chips.never",
            "vs.chips.open_all", "vs.drone.raise_now",
            "vs.age.sec", "vs.age.min", "vs.age.hour", "vs.age.day",
            "vsduel.survivor_tickets", "vsduel.build_collect",
            "vs.tickets.stats", "vs.tickets.have", "vs.tickets.spent_today",
            "vs.tickets.spend_now", "vs.tickets.read_at",
            "vs.tickets.never", "vs.builds.open_all", "vs.builds.open",
            "vs.builds.level", "vs.builds.read_at",
            "vs.builds.never", "vs.builds.left", "vs.builds.cost",
            "vs.builds.piece", "vs.builds.finish", "vs.builds.finish.confirm",
            "vs.builds.short")


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
        rt.store.blob_set(storemod.SURVIVOR_TICKETS, {})
        rt.store.blob_set(storemod.READY_BUILDINGS, {})
        tab._chips = tab._tickets = tab._builds = None
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
        keys = [f["key"] for g in monday["options_groups"] for f in g["fields"]]
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
                   for group in monday["options_groups"]
                   for field in group["fields"]), monday["options_groups"]
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
        assert [g["title"] for g in monday["options_groups"]] == [
            "vsduel.drone_chips", "vsduel.drone_level"]
        assert [f["key"] for g in monday["options_groups"]
                for f in g["fields"]] == ["plan.mon.drone_chips",
                                          "plan.mon.drone_level"]
        assert monday.get("pill") is None
        tuesday = items["vsduel.day.tue"]
        assert [g["title"] for g in tuesday["options_groups"]] == [
            "vsduel.survivor_tickets", "vsduel.build_collect"], (
                "Tuesday's two abilities, in the order the plan lists them (#2632)")
        assert tuesday.get("pill") is None
        for label in ("vsduel.day.wed", "vsduel.day.thu",
                      "vsduel.day.fri", "vsduel.day.sat"):
            day = items[label]
            assert not day.get("options_groups"), (label, day.get("options_groups"))
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
        # NOT ONE BUTTON ON THE CARD (#2624): the presses live inside the gear, one per
        # ability, under that ability's own switch.
        assert not monday.get("actions"), monday.get("actions")
        assert [a["label"] for g in monday["options_groups"]
                for a in g["actions"]] == ["vs.chips.open_all",
                                           "vs.drone.raise_now"]
        assert tab.web_press("run", {"key": "mon.drone_chips"}) == {"ok": True}
        assert tab.web_press("run", {"key": "mon.drone_level"}) == {"ok": True}
        assert played == ["open_drone_chips", "upgrade_drone"], played
        # …and nothing else may be started through it, whatever it is asked for.
        assert tab.web_press("run", {"key": "tue.build_speedup"}) == {"error": "unknown"}
        assert tab.web_press("run", {"key": "wed.research_start"}) == {"error": "unknown"}
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


def _groups(view: dict) -> list:
    """The blocks behind Monday's gear — one per wired ability (#2624)."""
    return _week(view)["items"][0].get("options_groups") or []


def _chip_group(view: dict) -> dict:
    for group in _groups(view):
        if group.get("title") == "vsduel.drone_chips":
            return group
    raise AssertionError("no chest block behind the gear")


def _chips(view: dict) -> dict:
    """The chest rows, as the old card-shaped tests read them."""
    group = _chip_group(view)
    return {"items": group.get("items") or [], "note": group.get("note"),
            "actions": group.get("actions") or []}


def test_the_chests_are_counted_under_the_knob_even_before_anything_is_read():
    """«Под чипами выведи статистику» (#2617) — a row per grade, from the first look.

    Nothing has been read yet on a fresh profile, so the counts are dashes and the note
    says so — a list that only appears once somebody presses «Обновить» is a list nobody
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
        assert [a["id"] for a in card["actions"]] == ["run"]
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


def test_the_bag_reading_is_taken_by_the_wire_and_the_run_carries_the_same_ids():
    """No «Обновить» anywhere: the reading is played by the push and by the start."""
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
        tab._read_bag()
        name, args, kw = seen[0]
        assert name == "read_drone_chips" and args == {"ids": ",".join(CHIP_IDS)}
        assert "on_result" in kw, "what came back has to reach the store"
        # …and the opening run carries the same list and its own tally callback.
        assert tab.web_press("run", {"key": "mon.drone_chips"}) == {"ok": True}
        name, args, kw = seen[-1]
        assert name == "open_drone_chips" and args == {"ids": ",".join(CHIP_IDS)}
        assert "on_result" in kw
        # …and the press that used to take it is not a press any more.
        assert tab.web_press("chips_read", {}) != {"ok": True}
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
        # …AND THE CARD CARRIES NOTHING OF ITS OWN (#2624) — the same shape «Таймеры»
        # draws: a switch in the corner, a gear, and no buttons stuck on the picture.
        for item in week["items"]:
            assert not item.get("actions"), item.get("actions")
        assert not [c for c in view["cards"] if c.get("title") == "vs.chips.title"], (
            "the chests are inside the gear now, not a card of their own")
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



# ---------------------------------------------------------------------------
# Tuesday (#2632): the survivors' tickets, and the buildings that have finished
# ---------------------------------------------------------------------------


def test_tuesdays_two_abilities_are_each_a_block_behind_the_gear():
    """The card carries nothing; each ability is its switch, its press, its subject."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        tuesday = _week(tab.web_view())["items"][1]
        assert tuesday["label"] == "vsduel.day.tue"
        assert not tuesday.get("actions"), tuesday.get("actions")
        groups = {g["title"]: g for g in tuesday["options_groups"]}
        tickets = groups["vsduel.survivor_tickets"]
        assert [f["key"] for f in tickets["fields"]] == ["plan.tue.survivor_tickets"]
        # NO «Обновить» anywhere on this page (#2633): the numbers are read when the
        # client gets into the game and moved by the game's own pushes after that.
        assert [a["label"] for a in tickets["actions"]] == ["vs.tickets.spend_now"]
        # …and the statistics the person asked for, in one row of two numbers.
        facts = tickets["items"][0]["facts"]
        assert [f["label"] for f in facts] == ["vs.tickets.have",
                                               "vs.tickets.spent_today"]
        assert facts[0]["value"] == "\u2014", "nothing read yet is never a zero"
        assert facts[1]["value"] == "0"

        builds = groups["vsduel.build_collect"]
        assert [f["key"] for f in builds["fields"]] == ["plan.tue.build_collect"]
        assert [a["label"] for a in builds["actions"]] == ["vs.builds.open_all"]
        # NOTHING TO OPEN -> the press is dead rather than absent (#2632).
        assert builds["actions"][0]["disabled"] is True
        assert builds["items"] == []
    finally:
        root.destroy()


def test_the_finished_buildings_are_rows_sorted_by_level_each_with_its_own_press():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        class _Outcome:
            class ctx:
                vars = {"ready_builds": "1000000000000001|10310000|12|"
                                        "UI_building_10310000|Factory ;; "
                                        "1000000000000002|10201000|30|"
                                        "UI_building_10201000|Field"}

        tab._builds_back(_Outcome())
        builds = {g["title"]: g for g in
                  _week(tab.web_view())["items"][1]["options_groups"]}["vsduel.build_collect"]
        rows = builds["items"]
        assert [r["text"] for r in rows] == ["Field", "Factory"], (
            "highest level first — «сортировка по уровню»")
        assert [r["facts"][0]["value"] for r in rows] == ["30", "12"]
        assert all(r["facts"][0]["label"] == "vs.builds.level" for r in rows)
        assert [r["actions"][0]["id"] for r in rows] == ["open_one", "open_one"]
        assert rows[0]["actions"][0]["args"]["uuid"] == "1000000000000002"
        assert builds["actions"][0].get("disabled") is False, (
            "there IS something to open now")
    finally:
        root.destroy()


def test_what_is_still_building_is_priced_before_it_is_paid_for():
    """#2634 — the running slots, what closing each would cost, and its own press.

    The parcel is NAMED on the row (CLAUDE.md: an irreversible spend is said out loud
    before it is made), the press asks first, and a bag that cannot close the build
    offers a dead button rather than a spend that buys nothing.
    """
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        class _Outcome:
            class ctx:
                vars = {"ready_builds": "",
                        "building_builds":
                            "1000000000000003|10310000|12|UI_building_10310000|"
                            "Factory|4820|1|200211:16:300:1+200201:1:900:0 ;; "
                            "1000000000000004|10201000|30|UI_building_10201000|"
                            "Field|90000|0|"}

        tab._builds_back(_Outcome())
        builds = {g["title"]: g for g in
                  _week(tab.web_view())["items"][1]["options_groups"]}["vsduel.build_collect"]
        rows = builds["items"]
        assert [r["text"] for r in rows] == ["Factory", "Field"], rows
        first = rows[0]
        assert [f["label"] for f in first["facts"]] == [
            "vs.builds.level", "vs.builds.left", "vs.builds.cost"], first["facts"]
        assert "16" in first["facts"][2]["value"] and "5" in first["facts"][2]["value"], (
            "the parcel is named before it is spent — %s" % first["facts"][2])
        press = first["actions"][0]
        assert press["id"] == "finish_one"
        assert press["args"]["uuid"] == "1000000000000003"
        assert press["label"] == "vs.builds.finish"
        assert press["confirm"] == "vs.builds.finish.confirm", (
            "speed-ups do not come back — the press asks first")
        assert press["disabled"] is False
        # …and the one the bag cannot close is dead, saying why.
        short = rows[1]
        assert short["actions"][0]["disabled"] is True
        assert short["facts"][2]["value"] == tab.t("vs.builds.short")
        # «Открыть все» is still about the FINISHED ones, and there are none.
        assert builds["actions"][0]["disabled"] is True
    finally:
        root.destroy()


def test_the_finish_press_plays_its_own_recipe_and_asks_the_game_again():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        played = []
        tab.rt.play_async = lambda name, *a, **k: (
            played.append((name, (k.get("args") or {}).get("uuid"))) or True)
        assert tab.web_press("finish_one", {"uuid": "1000000000000003"}) == {"ok": True}
        assert played == [("finish_building", "1000000000000003")], played
        assert tab.web_press("finish_one", {"uuid": "; drop"}) == {"error": "unknown"}
        assert tab.web_press("finish_one", {}) == {"error": "unknown"}
        assert len(played) == 1, played
    finally:
        root.destroy()


def test_the_finishing_recipe_exists_and_refuses_a_bag_that_falls_short():
    """The ability is one file, it spends nothing it cannot finish with, and no diamonds."""
    text = (ROOT / "src" / "lastwar_bot" / "actions" / "finish_building.md").read_text(
        encoding="utf-8")
    assert "ARGS uuid" in text
    assert "MsgDefines.BuildCcdMNew" in text, "the build queue's own speed-up message"
    assert "useGold = false" in text, "a construction is never closed with diamonds"
    assert "second(s) short of closing this construction" in text, (
        "a bag that cannot close the build spends nothing")


def test_tuesdays_presses_play_the_recipes_and_nothing_else():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        played = []
        tab.rt.play_async = lambda name, *a, **k: (
            played.append((name, (k.get("args") or {}).get("uuid"))) or True)

        assert tab.web_press("run", {"key": "tue.survivor_tickets"}) == {"ok": True}
        assert tab.web_press("run", {"key": "tue.build_collect"}) == {"ok": True}
        assert tab.web_press("open_one", {"uuid": "1000000000000001"}) == {"ok": True}
        assert played == [("spend_survivor_tickets", None),
                          ("open_ready_buildings", None),
                          ("open_ready_buildings", "1000000000000001")], played
        # A uuid that is not one is refused rather than handed to a recipe.
        assert tab.web_press("open_one", {"uuid": "; drop"}) == {"error": "unknown"}
        assert tab.web_press("open_one", {}) == {"error": "unknown"}
        # …and neither reading is a press any more (#2633).
        assert tab.web_press("tickets_read", {}) != {"ok": True}
        assert tab.web_press("builds_read", {}) != {"ok": True}
        assert len(played) == 3, played
    finally:
        root.destroy()


def test_the_ticket_tally_is_the_panels_own_fact_and_it_is_the_games_day():
    """A ticket that is spent is gone — the count of them exists nowhere but here."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        class _Read:
            class ctx:
                vars = {"worker_tickets": "42", "worker_free": "1"}

        class _Spent:
            class ctx:
                vars = {"tickets_spent": "20", "tickets_after": "22"}

        tab._tickets_back(_Read())
        assert tab._tickets_facts()[0]["value"] == "42"
        tab._tickets_spent_back(_Spent())
        facts = tab._tickets_facts()
        assert facts[0]["value"] == "22", facts
        assert facts[1]["value"] == "20", facts
        # The tally is keyed by the GAME's day, not this machine's midnight.
        assert tab._tickets_state()["day"] == tab.rt.day.day_key()
        tab._tickets_spent_back(_Spent())
        assert tab._tickets_facts()[1]["value"] == "40"
    finally:
        root.destroy()


def test_a_client_that_would_not_answer_is_never_drawn_as_a_zero():
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        class _Nothing:
            class ctx:
                vars = {"worker_tickets": "-1"}

        tab._tickets_back(_Nothing())
        assert tab._tickets_facts()[0]["value"] == "\u2014"
    finally:
        root.destroy()


def test_the_two_tuesday_recipes_exist_and_hold_their_own_gates():
    """Every gate of an ability lives in the scenario, never in the panel (CLAUDE.md)."""
    actions = ROOT / "src" / "lastwar_bot" / "actions"
    opens = (actions / "open_ready_buildings.md").read_text(encoding="utf-8")
    running = "\n".join(line for line in opens.splitlines()
                         if line.strip() and not line.lstrip().startswith("#"))
    assert "ARGS uuid =" in running, "one building or all of them, by argument"
    assert "120001" in running, "the arms race's BUILDING hour is the gate"
    assert "CheckSendBuildFinish" in running, "the claim is the client's own"
    assert "DelayInvoke" in running, "the send goes on the game's own thread"

    reads = (actions / "read_ready_buildings.md").read_text(encoding="utf-8")
    assert "INTO ready_builds" in reads
    assert "CheckSendBuildFinish" not in reads, "a read presses nothing"

    spend = (actions / "spend_survivor_tickets.md").read_text(encoding="utf-8")
    assert "TAP recruit_draw" in spend, "the press is the catalogue's own"
    assert "INTO tickets_spent" in spend, "what it cost, in the account's own numbers"
    assert "ARGS keep = 0" in spend, "how many tickets to leave untouched"

    tickets = (actions / "read_survivor_tickets.md").read_text(encoding="utf-8")
    assert "INTO worker_tickets" in tickets
    assert "TAP " not in tickets, "a read presses nothing"


def test_a_building_draws_the_games_own_picture_or_none_at_all():
    """Never a stand-in: a sprite this machine has not extracted is no picture."""
    import building_icons

    assert building_icons.file_named("../secret.png") is None
    assert building_icons.file_named("UI_building_00000000.png") is None
    assert building_icons.name_for("") == ""
    # …and the route the tab links to is the one the server answers.
    from panel.tabs.vs import VsTab

    link = VsTab._build_icon("UI_building_10310000")
    assert link is None or link.startswith("/api/buildingicon?icon="), link



# ---------------------------------------------------------------------------
# Read once, then listen (#2633)
# ---------------------------------------------------------------------------


def test_the_client_getting_into_the_game_takes_every_reading_once():
    """`bus.GAME_READY` is the first reading's only door — no button, no clock."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        from panel.runtime import bus as busmod

        played, heard = [], []
        tab.rt.play_async = lambda name, *a, **k: played.append(name) or True
        tab.rt.wire.subscribe = lambda pattern, fn: (
            heard.append(pattern) or (lambda: None))
        tab._on_game_ready()
        # …and the arms race with them since #2635: the errand's card stands on this
        # page, so the hour it draws is read where the rest of the page is read.
        assert played == ["read_drone_chips", "read_survivor_tickets",
                          "read_ready_buildings", "read_arms_race"], played
        # …and the ear is up, on the three announcements these numbers move on.
        assert busmod.GAME_READY == "game.ready"
        assert heard == ["push.resource.item.update",
                         "push.uav.skillchip.changes",
                         "push.person.arms.sc.change"], heard
        # Raised ONCE: a second ready does not open a second capture.
        tab._on_game_ready()
        assert heard == ["push.resource.item.update",
                         "push.uav.skillchip.changes",
                         "push.person.arms.sc.change"], heard
    finally:
        root.destroy()


def test_a_burst_of_pushes_costs_one_reading():
    """The debounce is re-armed by every push, so a harvest is one re-read."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        armed = []
        tab.rt.tick.arm = lambda name, delay, fn: armed.append((name, delay))
        for _ in range(25):
            tab._push_soon()
        assert len(armed) == 25, armed
        assert {name for name, _delay in armed} == {"vs_push"}, armed
        # The ear closing is not news, and it starts nothing.
        armed.clear()
        tab._on_push(None)
        assert armed == [], armed
    finally:
        root.destroy()


def test_the_build_queue_is_woken_by_its_own_end_time_and_not_by_a_clock():
    """The one reading with no push behind it — the person's answer was «по endTime»."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        import time as timemod

        armed = []
        tab.rt.tick.arm = lambda name, delay, fn: armed.append((name, delay))
        tab.rt.tick.disarm = lambda name: armed.append((name, None))

        # Nothing building: no alarm at all.
        tab._arm_build_alarm(-1)
        assert tab._build_due is None
        assert armed == [("vs_build_due", None)], armed

        # A slot due in a minute: one alarm, at that minute.
        armed.clear()
        tab._arm_build_alarm(60)
        assert armed and armed[0][0] == "vs_build_due"
        assert 55_000 < armed[0][1] <= 62_000, armed

        # A day-long construction is waited out in legs of an hour, and a leg that
        # arrives early re-arms rather than asking the game anything.
        armed.clear()
        played = []
        tab.rt.play_async = lambda name, *a, **k: played.append(name) or True
        tab._arm_build_alarm(86_400)
        assert armed[0][1] == 3_600_000, armed
        assert played == [], "an early leg reads nothing"

        # …and when the moment has actually come, the queue is read once.
        tab._build_due = timemod.time() - 1
        tab._build_tick()
        assert played == ["read_ready_buildings"], played
        assert tab._build_due is None
    finally:
        root.destroy()


def test_a_refused_reading_is_not_an_empty_queue_and_it_is_asked_again():
    """The gate can refuse the first reading; a page must not draw that as an answer."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        class _Refused:
            ok, reason, ctx = False, "action.held.link", None

        armed = []
        tab.rt.tick.arm = lambda name, delay, fn: armed.append((name, delay))
        tab.rt.play_async = lambda name, *a, **k: True
        tab._builds_back(_Refused())
        assert tab._builds_state().get("at") in (None, 0), tab._builds_state()
        assert "builds" not in tab._first_ok
        # …and the round books itself another try rather than waiting for a next login.
        tab._read_all()
        assert ("vs_first_read", 60_000) in armed, armed
    finally:
        root.destroy()


def test_being_told_ready_twice_costs_one_round_of_readings():
    """The bus is not de-duplicated, and three scenarios a telling is a link held twice."""
    try:
        root, tab = _tab()
    except Exception as exc:                       # noqa: BLE001
        print(f"  SKIP no tkinter / display: {exc}")
        return
    try:
        played = []
        tab.rt.play_async = lambda name, *a, **k: played.append(name) or True
        tab.rt.wire.subscribe = lambda pattern, fn: (lambda: None)
        tab._on_game_ready()
        tab._on_game_ready()
        assert played == ["read_drone_chips", "read_survivor_tickets",
                          "read_ready_buildings", "read_arms_race"], played
    finally:
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(_main())
