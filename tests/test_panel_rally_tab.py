"""The «Ралли» tab (panel/tabs_extra.py RallyTab) and its engine (tools/rally_create.py).

Two halves. The engine's decision logic — press the «лупа» search for a level, read back the
monster popup the game opens, press its «Стягивание» button, wait for the squad screen, pick
the squad and launch — is pure once the game is replaced by a scripted fake evaluator, so it
is tested directly and always runs. The four states the flow walks through are exactly where
it used to go wrong (pressing before the popup was up, launching before the squad was picked),
so the fake refuses to skip one: no popup, no press; no squad screen, no launch. The tab widget
needs Tk, so it is built on a tkinter root and only checked to construct and read its controls
without raising; skips without a Tk display.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import rally_create as rc  # noqa: E402


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else "  SKIP no tkinter")


# --- a scripted evaluator: serve canned Player.log lines per chunk kind ------
class FakeEv:
    """Stands in for the live Lua evaluator, walking the same four states the game does.

    ``result`` is the monster the search returns — a dict (pid/uuid/server/level/canAttack/btn),
    or ``None`` to model a search that came back empty (no monster of that level). The popup is
    only served once the search has been "fired"; the squad screen only opens once the popup's
    rally button was pressed; the launch only counts once the squad was picked. So a step taken
    out of order reads exactly as it does in the game — nothing there.

    ``opens_panel`` / ``takes_squad`` / ``raises`` turn off one step each, to model the three
    ways the flow can stall in the live game (a confirm dialog swallowing the press, the screen
    refusing the squad, the server dropping the send).
    """

    def __init__(self, result, formation="F123",
                 opens_panel=True, takes_squad=True, raises=True):
        self._result = result
        self._formation = formation
        self._opens_panel = opens_panel
        self._takes_squad = takes_squad
        self._raises = raises
        self._fired = False
        self.popup_open = False
        self.panel_open = False
        self.selected = None        # the formation uuid the squad screen ended up holding
        self.launched = False       # the launch button was pressed
        self.rallies = 0            # own marches carrying a teamUuid — the game's own answer
        self.closed = False
        self.search = None          # (tab type, level) the «лупа» was actually pressed with

    def run(self, chunk, marker=None, settle=None):
        if "OpenWindow" in chunk and "UISearch" in chunk:             # _OPEN_SEARCH
            return ["EL search-open"]
        if "OnSearchClick" in chunk:                                  # _FIRE_SEARCH
            self._fired = True
            # `c:SetCurNumBySearchType(<type>, <level>, 0)` — read back what was asked for.
            args = chunk.split("SetCurNumBySearchType(")[1].split(")")[0].split(",")
            self.search = (int(args[0]), int(args[1]))
            return ["EL search-fired level=? type=?"]
        if "GetMonsterData" in chunk:                                 # _READ_POPUP
            if self._fired and self._result is not None:
                e = self._result
                self.popup_open = True
                return ["EL popup pid=%s uuid=%s server=%s level=%s canAttack=%s btn=%s"
                        % (e["pid"], e["uuid"], e["server"], e["level"], e["canAttack"],
                           e.get("btn", rc.RALLY_BTN))]
            return ["EL popup waiting win=UISearch"]
        if "OnClickStartMarch" in chunk:                              # _PRESS_RALLY
            if not self.popup_open:                                   # pressed at thin air
                return ["EL press-nopopup win=nil"]
            self.popup_open = False
            self.panel_open = self._opens_panel
            return ["EL press ok=true err=nil"]
        if "panel none" in chunk:                                     # _READ_PANEL
            if not self.panel_open:
                return ["EL panel waiting win=UIWorldPoint"]
            return ["EL panel win=UIFormationSelectListV2 targetType=7 point=7 uuid=77 "
                    "server=935 timeIndex=5 sel=0"]
        if "OnSelectClick" in chunk:                                  # _PICK_SQUAD
            if not self.panel_open:
                return ["EL squad nopanel win=nil"]
            if self._takes_squad:
                self.selected = chunk.split("OnSelectClick(")[1].split(")")[0]
            return ["EL squad sel=%s" % (self.selected if self.selected else "0")]
        if "OnCheckTime" in chunk:                                    # _LAUNCH
            if not (self.panel_open and self.selected):
                return ["EL launch nopanel win=nil"]
            self.launched = True
            self.panel_open = False
            if self._raises:
                self.rallies += 1
            return ["EL launch ok=true err=nil"]
        if "GetOwnerMarches" in chunk:                                # _OWN_RALLIES
            return ["EL rallies n=%d" % self.rallies]
        if "CloseSelf" in chunk:                                      # _CLOSE_TOP
            self.popup_open = False
            self.panel_open = False
            return ["EL closed"]
        if "SQUAD uuid=" in chunk:                                    # formation_by_squad
            if not self._formation:                                   # no such squad loaded
                return ["SQUAD end"]
            return ["SQUAD uuid=%s" % self._formation, "SQUAD end"]
        return []

    def close(self):
        self.closed = True


def _elite(**over):
    e = {"pid": "7", "uuid": "77", "server": "935", "level": 3, "canAttack": 0}
    e.update(over)
    return e


def test_parse_popup_reads_the_fields():
    got = rc._parse_popup(
        "EL popup pid=505599 uuid=139711 server=935 level=5 canAttack=0 btn=RallyBoss")
    assert got == {"pid": "505599", "uuid": "139711", "server": "935",
                   "level": 5, "canAttack": 0, "btn": "RallyBoss"}, got
    # A malformed line (no pid/uuid) is rejected, not a crash.
    assert rc._parse_popup("EL popup none") is None


def test_find_target_returns_the_searched_monster():
    ev = FakeEv(_elite(uuid="33", level=5))
    got = rc.find_target(ev, level=5, wait_s=2)
    assert got is not None and got["uuid"] == "33" and got["level"] == 5, got
    assert got["btn"] == rc.RALLY_BTN


def test_find_target_none_when_search_empty():
    ev = FakeEv(None)
    assert rc.find_target(ev, level=5, wait_s=2) is None


def test_find_target_keeps_the_popup_open_for_the_rally_button():
    # The rally button lives ON the popup: closing it after the read is what used to make the
    # monster "hide" with nothing pressed.
    ev = FakeEv(_elite())
    assert rc.find_target(ev, level=3, wait_s=2, keep_open=True) is not None
    assert ev.popup_open, "the popup must still be up for the «Стягивание» press"
    # Without keep_open the map is left as found.
    ev = FakeEv(_elite())
    assert rc.find_target(ev, level=3, wait_s=2) is not None
    assert not ev.popup_open


def test_create_on_level_raises_a_rally_when_a_target_is_found():
    ev = FakeEv(_elite())
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is True and res["reason"] == "launched", res
    assert res["pid"] == "7" and res["server"] == "935"
    assert ev.launched and ev.rallies == 1, "a rally must have gone out"
    assert ev.selected == "F123", "the launch must ride the picked squad"


def test_create_on_level_reports_no_elite_when_empty():
    ev = FakeEv(None)
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is False and res["reason"] == "no_elite", res


def _with_popup_up(**over):
    """A fake whose monster popup is already open — the state raise_rally starts from."""
    ev = FakeEv(_elite(), **over)
    assert rc.find_target(ev, level=3, wait_s=2, keep_open=True) is not None
    return ev


def test_pressing_at_a_closed_popup_launches_nothing():
    # The popup is gone (closed, or never opened) — the press finds nothing to press.
    ev = FakeEv(_elite())
    ok, reason = rc.raise_rally(ev, "F123", wait_s=2)
    assert (ok, reason) == (False, "no_panel")
    assert not ev.launched and ev.rallies == 0


def test_no_squad_screen_means_nothing_is_launched():
    # The press did not bring up the squad screen (a confirm dialog in the way, say).
    ev = _with_popup_up(opens_panel=False)
    ok, reason = rc.raise_rally(ev, "F123", wait_s=2)
    assert (ok, reason) == (False, "no_panel")
    assert not ev.launched and ev.rallies == 0


def test_the_squad_must_take_before_anything_is_launched():
    # The screen is up but would not hold the squad — the launch is not pressed at all.
    ev = _with_popup_up(takes_squad=False)
    ok, reason = rc.raise_rally(ev, "F123", wait_s=2)
    assert (ok, reason) == (False, "no_squad")
    assert not ev.launched, "never launch a screen that is not holding the wanted squad"


def test_a_pressed_launch_that_raises_nothing_is_not_ok():
    # Everything was pressed and the game shows no new rally — that is a miss, not a success.
    ev = _with_popup_up(raises=False)
    ok, reason = rc.raise_rally(ev, "F123", wait_s=2)
    assert (ok, reason) == (False, "not_raised")
    assert ev.launched and ev.rallies == 0


def test_a_missing_squad_is_refused_before_the_map_is_touched():
    ev = FakeEv(_elite(), formation="")
    # The env fallback inside formation_by_squad would answer for a configured account, so the
    # resolver is stood down for this one: the point is what create_on_level does with "no squad".
    original = rc.formation_by_squad
    rc.formation_by_squad = lambda run, squad: None
    try:
        res = rc.create_on_level(ev, level=3, squad=1)
    finally:
        rc.formation_by_squad = original
    assert res["ok"] is False and res["reason"] == "no_formation", res
    assert ev.search is None, "no search should be fired for a squad that cannot be sent"


def test_level_range_is_the_same_for_both_search_kinds():
    # Both tabs take the whole 1–200 span — a season goes far past the everyday levels.
    assert rc.level_range("boss") == (1, 200)
    assert rc.level_range("monster") == (1, 200)
    assert rc.level_range() == rc.level_range(rc.RALLY_ELITE_SEARCH)   # default kind
    assert rc.level_range("nonsense") == (1, 200)                      # unknown → monster tab


def test_clamp_level_pulls_into_the_range():
    assert rc.clamp_level(200, "boss") == 200       # a level-200 elite is asked for as-is
    assert rc.clamp_level(500, "monster") == 200    # above the ceiling
    assert rc.clamp_level(0, "monster") == 1
    assert rc.clamp_level("", "boss") == 1          # unparseable reads as the minimum
    assert rc.clamp_level("7", "monster") == 7      # a numeric string is a number


def test_search_presses_the_asked_for_tab_with_a_clamped_level():
    # Monster tab (UISearchType 1) takes a level-180 seasonal monster as asked.
    ev = FakeEv(_elite(pid="1", uuid="11", level=180))
    assert rc.find_target(ev, level=180, search_type="monster", wait_s=2) is not None
    assert ev.search == (rc.UISEARCH_TYPE["monster"], 180), ev.search
    # The same level under the Boss tab (5) goes out under that tab, level untouched.
    ev = FakeEv(_elite(pid="1", uuid="11", level=180))
    rc.find_target(ev, level=180, search_type="boss", wait_s=2)
    assert ev.search == (rc.UISEARCH_TYPE["boss"], 180), ev.search
    # Past the ceiling it is clamped rather than sent.
    ev = FakeEv(None)
    rc.find_target(ev, level=999, search_type="boss", wait_s=1)
    assert ev.search == (rc.UISEARCH_TYPE["boss"], 200), ev.search


def test_create_on_level_searches_under_the_given_kind():
    ev = FakeEv(_elite(pid="5", uuid="55", level=150))
    res = rc.create_on_level(ev, level=150, squad=1, search_type="monster")
    assert res["ok"] is True and res["level"] == 150, res
    assert ev.search == (rc.UISEARCH_TYPE["monster"], 150), ev.search


def test_create_on_level_soloable_is_not_a_rally_target():
    # The search returned a monster, but its popup carries the solo attack button — there is no
    # «Стягивание» on it, so nothing is pressed.
    ev = FakeEv(_elite(pid="9", uuid="99", canAttack=1, btn="AttackMonster"))
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is False and res["reason"] == "no_elite", res
    assert not ev.launched and ev.rallies == 0


# --- the Tk widget (build + read its controls) -------------------------------
def test_rally_tab_builds_and_reads_controls():
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel import tabs_extra as tx

    class _App(tk.Tk):
        def _t(self, key, **fmt):
            return key
        def _tr(self, widget, key, option="text", **fmt):
            try:
                widget.configure(**{option: key})
            except Exception:                           # noqa: BLE001
                pass
            return widget
        def _daemon_port(self):
            return 47999

    try:
        app = _App()
        app.withdraw()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        frame = ttk.Frame(app)
        tab = tx.RallyTab(app, frame)
        # Defaults: min level, one repeat, no squad ticked.
        assert tab._level() == tx.RALLY_LEVEL_MIN
        assert tab._repeats() == 1
        assert tab._selected_squads() == []
        # Clamping and the digits-only repeat.
        tab._level_var.set(999)
        assert tab._level() == tx.RALLY_LEVEL_MAX
        tab._level_var.set(0)
        assert tab._level() == tx.RALLY_LEVEL_MIN
        tab._repeats_var.set("0")
        assert tab._repeats() == 1                      # min one
        tab._repeats_var.set("5")
        assert tab._repeats() == 5
        # Ticking squads is read back in slot order.
        tab._squad_vars[3].set(True)
        tab._squad_vars[1].set(True)
        assert tab._selected_squads() == [1, 3]
        # Launch with no squad refuses (does not start a thread).
        for v in tab._squad_vars.values():
            v.set(False)
        tab._launch()
        assert tab._stop is None, "must not start a run with no squad selected"
    finally:
        app.destroy()


def test_rally_tab_level_box_and_quick_buttons():
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel import tabs_extra as tx

    class _App(tk.Tk):
        def _t(self, key, **fmt):
            return key
        def _tr(self, widget, key, option="text", **fmt):
            try:
                widget.configure(**{option: key})
            except Exception:                           # noqa: BLE001
                pass
            return widget

    try:
        app = _App()
        app.withdraw()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab = tx.RallyTab(app, ttk.Frame(app))
        # One button per quick level, and pressing one IS setting the level — the button
        # and the box are the same variable, which is what makes a single press enough.
        assert sorted(tab._quick_buttons) == sorted(tx.RALLY_QUICK_LEVELS)
        for quick in tx.RALLY_QUICK_LEVELS:
            tab._quick_buttons[quick].invoke()
            assert tab._level() == quick, f"pressing {quick} must aim the run at it"
            assert tab._level_var.get() == str(quick)
        # …and typing a quick level lights its button back up (same variable, so the
        # radio reads pressed), while any other level leaves all four unpressed.
        tab._level_var.set("35")
        assert "selected" in tab._quick_buttons[35].state()
        tab._level_var.set("47")
        assert all("selected" not in b.state() for b in tab._quick_buttons.values())
        assert tab._level() == 47
        # Whatever the box holds is read as a level: junk, empty, out of range, and a
        # float left over from the profile the slider used to write.
        for text, expected in (("", tx.RALLY_LEVEL_MIN), ("0", tx.RALLY_LEVEL_MIN),
                               ("500", tx.RALLY_LEVEL_MAX), ("35.0", 35),
                               ("nonsense", tx.RALLY_LEVEL_MIN)):
            tab._level_var.set(text)
            assert tab._level() == expected, f"{text!r} must read as {expected}"
            # …and leaving the box puts that same level back into it, so what is on
            # screen is what the run would go out on.
            tab._normalise_level()
            assert tab._level_var.get() == str(expected)
        # Elite is the default kind; an unknown one (a hand-edited var) falls back to it.
        tab._kind_var.set(tx.RALLY_KIND_ELITE)
        assert tab._kind() == tx.RALLY_KIND_ELITE
        tab._kind_var.set(tx.RALLY_KIND_MONSTER)
        assert tab._kind() == tx.RALLY_KIND_MONSTER
        tab._kind_var.set("nonsense")
        assert tab._kind() == tx.RALLY_KIND_ELITE
    finally:
        app.destroy()


def test_rally_tab_config_round_trip_and_bad_blocks():
    """What the tab saves comes back, and a junk block cannot aim a run."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel import tabs_extra as tx

    class _App(tk.Tk):
        def _t(self, key, **fmt):
            return key
        def _tr(self, widget, key, option="text", **fmt):
            try:
                widget.configure(**{option: key})
            except Exception:                           # noqa: BLE001
                pass
            return widget

    try:
        app = _App()
        app.withdraw()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab = tx.RallyTab(app, ttk.Frame(app))
        # A fresh tab saves its defaults, so a first-run profile is a valid one.
        assert tab.config() == {"kind": tx.RALLY_KIND_ELITE, "level": tx.RALLY_LEVEL_MIN,
                                "squads": [], "repeats": 1}
        # Set all four, save, wipe, restore: the tab comes back the way it was left.
        tab._kind_var.set(tx.RALLY_KIND_MONSTER)
        tab._level_var.set("120")
        tab._squad_vars[2].set(True)
        tab._squad_vars[4].set(True)
        tab._repeats_var.set("7")
        saved = tab.config()
        assert saved == {"kind": tx.RALLY_KIND_MONSTER, "level": 120,
                         "squads": [2, 4], "repeats": 7}
        tab.apply_config({})
        assert tab.config() == {"kind": tx.RALLY_KIND_ELITE, "level": tx.RALLY_LEVEL_MIN,
                                "squads": [], "repeats": 1}
        tab.apply_config(saved)
        assert tab.config() == saved
        assert "selected" in tab._quick_buttons[120].state(), \
            "a restored quick level shows on its button"
        # A hand-edited or older config cannot smuggle in a level, a kind, a squad or a
        # repeat count the tab would refuse from the UI.
        tab.apply_config({"kind": "nonsense", "level": 9999, "squads": "1,2",
                          "repeats": 0})
        assert tab.config() == {"kind": tx.RALLY_KIND_ELITE, "level": tx.RALLY_LEVEL_MAX,
                                "squads": [], "repeats": 1}
        tab.apply_config({"level": -5, "squads": [3, 99], "repeats": True})
        assert tab.config() == {"kind": tx.RALLY_KIND_ELITE, "level": tx.RALLY_LEVEL_MIN,
                                "squads": [3], "repeats": 1}
        tab.apply_config("not a block at all")
        assert tab.config()["level"] == tx.RALLY_LEVEL_MIN
        # Every control the panel has to persist is offered for tracing — miss one and
        # that choice silently stops being remembered.
        names = {str(v) for v in tab.persist_vars()}
        for var in (tab._kind_var, tab._level_var, tab._repeats_var,
                    *tab._squad_vars.values()):
            assert str(var) in names, f"{var} is not persisted"
    finally:
        app.destroy()


def test_panel_saves_the_tab_block_without_erasing_it_at_startup():
    """The panel side of the round trip (panel/__main__.py `_rally_tab_config`).

    Settings are collected on every save, including saves that happen before the tab
    is built — those must hand back the block that is on disk, or the choices would be
    overwritten with defaults in the moment before they are restored.
    """
    try:
        import panel.__main__ as pm                      # needs tkinter
    except Exception as exc:                             # noqa: BLE001
        _skip(exc)
        return

    block = {"kind": "monster", "level": 60, "squads": [1, 3], "repeats": 4}

    class _NoTabYet:
        _settings = {"rally_tab": block}
        _tab_config = pm.Panel._tab_config

    class _Built:
        _settings = {"rally_tab": block}
        _tab_config = pm.Panel._tab_config

        class _rally_tab:                                # the tab, once it exists
            @staticmethod
            def config():
                return {"kind": "boss", "level": 35, "squads": [], "repeats": 1}

    class _Fresh:                                        # a profile with nothing saved
        _settings = {}
        _tab_config = pm.Panel._tab_config

    assert pm.Panel._rally_tab_config(_NoTabYet()) == block, \
        "a save before the tab is built must keep what is on disk"
    assert pm.Panel._rally_tab_config(_Built()) == {"kind": "boss", "level": 35,
                                                    "squads": [], "repeats": 1}
    assert pm.Panel._rally_tab_config(_Fresh()) == {}
    class _Bare:                                         # not even a settings dict yet
        _tab_config = pm.Panel._tab_config

    assert pm.Panel._rally_tab_config(_Bare()) == {}


def test_status_keys_are_named_per_kind():
    from panel import tabs_extra as tx
    assert tx._kind_key("searching", tx.RALLY_KIND_ELITE) == "rally_tab.searching"
    assert tx._kind_key("searching", tx.RALLY_KIND_MONSTER) == "rally_tab.searching_monster"
    assert tx._kind_key("no_elite", tx.RALLY_KIND_MONSTER) == "rally_tab.no_elite_monster"
    assert tx._kind_key("raised", tx.RALLY_KIND_MONSTER) == "rally_tab.raised_monster"


def test_every_status_key_exists_in_both_locales():
    import json
    # Every miss the engine can report has a line of its own — a run that comes to nothing
    # must say which of the five ways it did.
    keys = ["rally_tab.kind", "rally_tab.kind_boss", "rally_tab.kind_monster",
            "rally_tab.level", "rally_tab.level_quick",
            "rally_tab.no_formation", "rally_tab.no_panel", "rally_tab.no_squad",
            "rally_tab.not_armed"]
    for base in ("searching", "no_elite", "raised"):
        for kind in ("boss", "monster"):
            from panel import tabs_extra as tx
            keys.append(tx._kind_key(base, kind))
    for lang in ("en", "ru"):
        table = json.loads((ROOT / "panel" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in table]
        assert not missing, f"{lang}.json misses {missing}"


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
