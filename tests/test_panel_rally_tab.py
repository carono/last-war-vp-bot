"""The «Ралли» tab (panel/tabs_extra.py RallyTab) and its engine (tools/rally_create.py).

Two halves. The engine's decision logic — parse a monster popup, pick the first rally
elite of the wanted level, branch create_on_level on what was found — is pure once the
game is replaced by a scripted fake evaluator, so it is tested directly and always runs.
The tab widget needs Tk, so it is built on a CustomTkinter root and only checked to
construct and read its controls without raising; skips without a Tk display.
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
    """Stands in for the live Lua evaluator. Serves one elite popup per scan step.

    ``elites`` is a list of dicts (pid/uuid/server/level/canAttack); the finder walks
    them one clone at a time and then reports the map exhausted, exactly as the real
    clone-hunt would. Formation reads answer with a warm squad so no UI is opened.
    """

    def __init__(self, elites, formation="F123"):
        self._elites = list(elites)
        self._i = 0
        self._formation = formation
        self.closed = False
        self.armed = False

    def run(self, chunk, marker=None, settle=None):
        if "reset" in chunk and "__lw_elite_seen" in chunk:
            self._i = 0
            return ["EL reset"]
        if "FindObjectsOfType" in chunk and "clicked" in chunk:       # _CLICK_NEXT
            if self._i < len(self._elites):
                return ["EL clicked WorldMonster0%d(Clone)" % (self._i + 1)]
            return ["EL none"]
        if "GetStackTopWindow" in chunk and "GetMonsterData" in chunk:  # _READ_POPUP
            if self._i < len(self._elites):
                e = self._elites[self._i]
                self._i += 1
                return ["EL popup pid=%s uuid=%s server=%s level=%s canAttack=%s"
                        % (e["pid"], e["uuid"], e["server"], e["level"], e["canAttack"])]
            return ["EL popup none"]
        if "CloseSelf" in chunk:                                      # _CLOSE_POPUP
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


def test_find_elite_matches_level_and_skips_soloable():
    # A soloable lvl-5 (canAttack=1) and a rally lvl-9 come first; the rally lvl-5 is third.
    ev = FakeEv([
        {"pid": "1", "uuid": "11", "server": "935", "level": 5, "canAttack": 1},   # soloable
        {"pid": "2", "uuid": "22", "server": "935", "level": 9, "canAttack": 0},   # wrong level
        {"pid": "3", "uuid": "33", "server": "935", "level": 5, "canAttack": 0},   # the match
    ])
    got = rc.find_elite(ev, level=5)
    assert got is not None and got["uuid"] == "33" and got["level"] == 5, got


def test_find_elite_none_when_no_rally_elite():
    ev = FakeEv([{"pid": "1", "uuid": "11", "server": "935", "level": 5, "canAttack": 1}])
    assert rc.find_elite(ev, level=5) is None


def test_create_on_level_arms_when_elite_found():
    ev = FakeEv([{"pid": "7", "uuid": "77", "server": "935", "level": 3, "canAttack": 0}])
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is True and res["reason"] == "armed", res
    assert res["pid"] == "7" and res["server"] == "935"
    assert ev.armed, "the create send must have been armed"


def test_create_on_level_reports_no_elite():
    ev = FakeEv([])
    res = rc.create_on_level(ev, level=3, squad=1)
    assert res["ok"] is False and res["reason"] == "no_elite", res


# --- the Tk widget (build + read its controls) -------------------------------
def test_rally_tab_builds_and_reads_controls():
    try:
        import customtkinter as ctk
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel import tabs_extra as tx

    class _App(ctk.CTk):
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
        frame = ctk.CTkFrame(app)
        tab = tx.RallyTab(app, frame)
        # Defaults: min level, one repeat, no squad ticked.
        assert tab._level() == tx.RALLY_ELITE_MIN
        assert tab._repeats() == 1
        assert tab._selected_squads() == []
        # Clamping and the digits-only repeat.
        tab._level_var.set("999")
        assert tab._level() == tx.RALLY_ELITE_MAX
        tab._level_var.set("")
        assert tab._level() == tx.RALLY_ELITE_MIN
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
