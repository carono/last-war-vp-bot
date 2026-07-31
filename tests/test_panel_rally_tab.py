"""The «Ралли» tab (panel/tabs_extra.py RallyTab) and its engine (tools/rally_create.py).

Two halves. The engine's decision logic — press the «лупа» search for a level, read back
the monster popup the game opens, branch create_on_level on whether it is a rally elite —
is pure once the game is replaced by a scripted fake evaluator, so it is tested directly
and always runs. The tab widget needs Tk, so it is built on a tkinter root and only
checked to construct and read its controls without raising; skips without a Tk display.
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
    """Stands in for the live Lua evaluator. Answers the «лупа» search with one popup.

    ``result`` is the monster the search returns — a dict (pid/uuid/server/level/canAttack),
    or ``None`` to model a search that came back empty (no monster of that level). The read
    chunk serves that popup once the search has been "fired"; formation reads answer with a
    warm squad so no UI is opened.
    """

    def __init__(self, result, formation="F123"):
        self._result = result
        self._fired = False
        self._formation = formation
        self.closed = False
        self.armed = False
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
        if "GetStackTopWindow" in chunk and "GetMonsterData" in chunk:  # _READ_POPUP
            if self._fired and self._result is not None:
                e = self._result
                return ["EL popup pid=%s uuid=%s server=%s level=%s canAttack=%s"
                        % (e["pid"], e["uuid"], e["server"], e["level"], e["canAttack"])]
            return ["EL popup waiting win=UISearch"]
        if "CloseSelf" in chunk:                                      # _CLOSE_TOP
            return ["EL closed"]
        if "FM PICK" in chunk:                                        # pick_formation (warm)
            return ["FM PICK uuid=%s soldiers=3123" % self._formation]
        if "SQUAD uuid=" in chunk:                                    # formation_by_squad
            return ["SQUAD uuid=%s" % self._formation, "SQUAD end"]
        if "RC armed" in chunk:                                       # create_rally
            self.armed = True
            return ["RC sent ok=true err=nil", "RC armed"]
        return []

    def close(self):
        self.closed = True


def test_parse_popup_reads_the_fields():
    got = rc._parse_popup("EL popup pid=505599 uuid=139711 server=935 level=5 canAttack=0")
    assert got == {"pid": "505599", "uuid": "139711", "server": "935",
                   "level": 5, "canAttack": 0}, got
    # A malformed line (no pid/uuid) is rejected, not a crash.
    assert rc._parse_popup("EL popup none") is None


def test_spawn_elite_returns_the_searched_monster():
    ev = FakeEv({"pid": "3", "uuid": "33", "server": "935", "level": 5, "canAttack": 0})
    got = rc.spawn_elite(ev, level=5, wait_s=2)
    assert got is not None and got["uuid"] == "33" and got["level"] == 5, got


def test_spawn_elite_none_when_search_empty():
    ev = FakeEv(None)
    assert rc.spawn_elite(ev, level=5, wait_s=2) is None


def test_create_on_level_arms_when_elite_found():
    ev = FakeEv({"pid": "7", "uuid": "77", "server": "935", "level": 3, "canAttack": 0})
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is True and res["reason"] == "armed", res
    assert res["pid"] == "7" and res["server"] == "935"
    assert ev.armed, "the create send must have been armed"


def test_create_on_level_reports_no_elite_when_empty():
    ev = FakeEv(None)
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is False and res["reason"] == "no_elite", res


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
    ev = FakeEv({"pid": "1", "uuid": "11", "server": "935", "level": 180, "canAttack": 0})
    assert rc.spawn_elite(ev, level=180, search_type="monster", wait_s=2) is not None
    assert ev.search == (rc.UISEARCH_TYPE["monster"], 180), ev.search
    # The same level under the Boss tab (5) goes out under that tab, level untouched.
    ev = FakeEv({"pid": "1", "uuid": "11", "server": "935", "level": 180, "canAttack": 0})
    rc.spawn_elite(ev, level=180, search_type="boss", wait_s=2)
    assert ev.search == (rc.UISEARCH_TYPE["boss"], 180), ev.search
    # Past the ceiling it is clamped rather than sent.
    ev = FakeEv(None)
    rc.spawn_elite(ev, level=999, search_type="boss", wait_s=1)
    assert ev.search == (rc.UISEARCH_TYPE["boss"], 200), ev.search


def test_create_on_level_searches_under_the_given_kind():
    ev = FakeEv({"pid": "5", "uuid": "55", "server": "935", "level": 150, "canAttack": 0})
    res = rc.create_on_level(ev, level=150, squad=1, search_type="monster")
    assert res["ok"] is True and res["level"] == 150, res
    assert ev.search == (rc.UISEARCH_TYPE["monster"], 150), ev.search


def test_create_on_level_soloable_is_not_a_rally_elite():
    # The search returned a monster, but it is soloable (canAttack=1) — not a rally elite.
    ev = FakeEv({"pid": "9", "uuid": "99", "server": "935", "level": 3, "canAttack": 1})
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is False and res["reason"] == "no_elite", res


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


def test_rally_tab_level_slider_reads_whole_levels():
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
        # The slider spans the whole range, the same one for both kinds.
        assert (int(float(tab._level_scale.cget("from"))),
                int(float(tab._level_scale.cget("to")))) \
            == (tx.RALLY_LEVEL_MIN, tx.RALLY_LEVEL_MAX)
        # It writes floats; the level is read as a whole number and the label follows.
        tab._level_scale.set(180.4)
        tab._on_level()
        assert tab._level() == 180
        assert tab._level_text.get() == "180"
        tab._level_scale.set(34.6)
        tab._on_level()
        assert tab._level() == 35 and tab._level_text.get() == "35"
        # The ceiling holds even if the variable is written past it directly.
        tab._level_var.set(500)
        assert tab._level() == tx.RALLY_LEVEL_MAX
        # Elite is the default kind; an unknown one (a hand-edited var) falls back to it.
        assert tab._kind() == tx.RALLY_KIND_ELITE
        tab._kind_var.set(tx.RALLY_KIND_MONSTER)
        assert tab._kind() == tx.RALLY_KIND_MONSTER
        tab._kind_var.set("nonsense")
        assert tab._kind() == tx.RALLY_KIND_ELITE
    finally:
        app.destroy()


def test_status_keys_are_named_per_kind():
    from panel import tabs_extra as tx
    assert tx._kind_key("searching", tx.RALLY_KIND_ELITE) == "rally_tab.searching"
    assert tx._kind_key("searching", tx.RALLY_KIND_MONSTER) == "rally_tab.searching_monster"
    assert tx._kind_key("no_elite", tx.RALLY_KIND_MONSTER) == "rally_tab.no_elite_monster"
    assert tx._kind_key("raised", tx.RALLY_KIND_MONSTER) == "rally_tab.raised_monster"


def test_every_status_key_exists_in_both_locales():
    import json
    keys = ["rally_tab.kind", "rally_tab.kind_boss", "rally_tab.kind_monster"]
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
