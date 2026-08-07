r"""The «Ралли» tab (panel/tabs/rally/) — the form, the monitor and what it saves.

The tab is a plugin now: it is handed a runtime and nothing else, and it can be opened
on its own (`python -m panel.tabs.rally`). So it is tested the way it is built — against
a COLD runtime, with no daemon, no client and no game (tests/fake_runtime.py).

What is worth pinning, in order of how quietly it breaks:

* **the run quotes the scenario.** The tab no longer decides why a rally came to
  nothing: `actions/create_rally.md` names six failures and `ActionRunner.play()` hands
  the sentence back, so the loop shows the scenario's own words and tells "it decided"
  (a reason) from "it broke" (no reason) apart — docs/research/panel-tabs-refactor.md §8.
* **a profile written before the move still aims the tab.** Four flat keys became one
  nested block; the tab reads either.
* **the daily cap gates the loop**: a run stops when the day's «monster» budget is spent.
* **the alert fires once per banner**, not once per push — a rally emits create AND
  refresh events.

The engine behind the command-line `tools/rally_create.py` is tests/test_rally_tool.py,
and the scenario the tab actually plays is tests/test_rally_create.py.

Needs Tk and a display; says SKIP under the WSL python3.

    C:\Python312\python.exe tests\test_panel_rally_tab.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "tools", ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else "  SKIP no tkinter")


def _tab():
    """A built «Ралли» tab on a cold runtime, plus the root to destroy afterwards."""
    import tkinter as tk
    from tkinter import ttk
    import fake_runtime
    from panel.tabs.rally.tab import RallyTab

    root = tk.Tk()
    root.withdraw()
    rt = fake_runtime.cold_runtime(root)
    tab = RallyTab(rt, ttk.Frame(root))
    rt.tabs.add(tab)
    tab.build()
    return root, rt, tab


# ---------------------------------------------------------------------------
# the form
# ---------------------------------------------------------------------------

def test_rally_tab_builds_and_reads_controls():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, _rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel.tabs.rally import tab as rl
    try:
        # Defaults: min level, one repeat, no squad ticked.
        assert tab._level() == rl.RALLY_LEVEL_MIN
        assert tab._repeats() == 1
        assert tab._selected_squads() == []
        # Clamping and the digits-only repeat.
        tab._level_var.set(999)
        assert tab._level() == rl.RALLY_LEVEL_MAX
        tab._level_var.set(0)
        assert tab._level() == rl.RALLY_LEVEL_MIN
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
        assert tab._run_stop is None, "must not start a run with no squad selected"
    finally:
        root.destroy()


def test_rally_tab_level_box_and_quick_buttons():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, _rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel.tabs.rally import tab as rl
    try:
        # One button per quick level, and pressing one IS setting the level — the button
        # and the box are the same variable, which is what makes a single press enough.
        assert sorted(tab._quick_buttons) == sorted(rl.RALLY_QUICK_LEVELS)
        for quick in rl.RALLY_QUICK_LEVELS:
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
        for text, expected in (("", rl.RALLY_LEVEL_MIN), ("0", rl.RALLY_LEVEL_MIN),
                               ("500", rl.RALLY_LEVEL_MAX), ("35.0", 35),
                               ("nonsense", rl.RALLY_LEVEL_MIN)):
            tab._level_var.set(text)
            assert tab._level() == expected, f"{text!r} must read as {expected}"
            # …and leaving the box puts that same level back into it, so what is on
            # screen is what the run would go out on.
            tab._normalise_level()
            assert tab._level_var.get() == str(expected)
        # Elite is the default kind; an unknown one (a hand-edited var) falls back to it.
        tab._kind_var.set(rl.RALLY_KIND_MONSTER)
        assert tab._kind() == rl.RALLY_KIND_MONSTER
        tab._kind_var.set("nonsense")
        assert tab._kind() == rl.RALLY_KIND_ELITE
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# what the profile keeps
# ---------------------------------------------------------------------------

def test_config_round_trip_and_bad_blocks():
    """What the tab saves comes back, and a junk block cannot aim a run."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, _rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel.tabs.rally import tab as rl
    try:
        # A fresh tab saves its defaults, so a first-run profile is a valid one — and
        # the monitor is ON by default, because an alert nobody armed is no alert.
        fresh = tab.config()
        assert fresh["form"] == {"kind": rl.RALLY_KIND_ELITE, "level": rl.RALLY_LEVEL_MIN,
                                 "squads": [], "repeats": 1}
        assert (fresh["monitor"], fresh["alert"], fresh["autojoin"]) == (True, True, False)
        assert fresh["autorally"]["squads"] == []

        tab._kind_var.set(rl.RALLY_KIND_MONSTER)
        tab._level_var.set("120")
        tab._squad_vars[2].set(True)
        tab._squad_vars[4].set(True)
        tab._repeats_var.set("7")
        tab._autojoin_var.set(True)
        tab.autorally._squad_vars[1].set(True)
        saved = tab.config()
        assert saved["form"] == {"kind": rl.RALLY_KIND_MONSTER, "level": 120,
                                 "squads": [2, 4], "repeats": 7}
        assert saved["autojoin"] is True
        assert saved["autorally"]["squads"] == [1]

        tab.apply_config({})
        assert tab.config()["form"] == fresh["form"]
        tab.apply_config(saved)
        assert tab.config() == saved
        assert "selected" in tab._quick_buttons[120].state(), \
            "a restored quick level shows on its button"

        # A hand-edited or older config cannot smuggle in a level, a kind, a squad or a
        # repeat count the tab would refuse from the UI.
        tab.apply_config({"form": {"kind": "nonsense", "level": 9999,
                                   "squads": "1,2", "repeats": 0}})
        assert tab.config()["form"] == {"kind": rl.RALLY_KIND_ELITE,
                                        "level": rl.RALLY_LEVEL_MAX,
                                        "squads": [], "repeats": 1}
        tab.apply_config({"form": {"level": -5, "squads": [3, 99], "repeats": True}})
        assert tab.config()["form"] == {"kind": rl.RALLY_KIND_ELITE,
                                        "level": rl.RALLY_LEVEL_MIN,
                                        "squads": [3], "repeats": 1}
        tab.apply_config("not a block at all")
        assert tab.config()["form"]["level"] == rl.RALLY_LEVEL_MIN

        # Every control the container has to persist is offered for tracing — miss one
        # and that choice silently stops being remembered.
        names = {str(v) for v in tab.persist_vars()}
        for var in (tab._kind_var, tab._level_var, tab._repeats_var,
                    tab._monitor_var, tab._alert_var, tab._autojoin_var,
                    *tab._squad_vars.values(), *tab.autorally.persist_vars()):
            assert str(var) in names, f"{var} is not persisted"
    finally:
        root.destroy()


def test_a_profile_written_before_the_move_still_aims_the_tab():
    """Four flat keys became one nested block; a profile that predates it must not lose
    a single choice (docs/research/panel-tabs-refactor.md §5 rule 1)."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel.tabs.rally.tab import RallyTab
    try:
        rt.settings.values = {
            "rally_tab": {"kind": "monster", "level": 60, "squads": [1, 3], "repeats": 4},
            "autorally": {"squads": [2, 4]},
            "rally_monitor": False, "rally_alert": False, "rally_autojoin": True,
        }
        tab.apply_config(rt.settings.tab_config(RallyTab.ID, RallyTab.LEGACY_KEYS))
        got = tab.config()
        assert got["form"] == {"kind": "monster", "level": 60,
                               "squads": [1, 3], "repeats": 4}, got["form"]
        assert (got["monitor"], got["alert"], got["autojoin"]) == (False, False, True)
        assert tab.join_squads() == [2, 4]
        # And the new block wins once it is there — while the flat keys are still
        # written beside it, so an older panel opening this profile finds them (§5 r2).
        rt.settings.set_tab_config(RallyTab.ID, got, RallyTab.LEGACY_KEYS)
        assert rt.settings.values["rally_tab"] == got["form"], "legacy key not mirrored"
        assert rt.settings.values["rally_monitor"] is False
        assert rt.settings.tab_config(RallyTab.ID, RallyTab.LEGACY_KEYS) == got
    finally:
        root.destroy()


def test_join_squads_answers_without_the_tab():
    """The «rally_auto_join» trigger fires on the schedule, in a profile that may not
    show the tab at all — the saved block has to answer then."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel.tabs import TabRegistry
    from panel.tabs.rally import tab as rl
    try:
        tab.autorally._squad_vars[2].set(True)
        assert rl.join_squads(rt) == [2], "the live page answers when it is there"

        rt.tabs = TabRegistry()                          # a window without a rally tab
        rt.settings.values = {"autorally": {"squads": [1, 4]}}
        assert rl.join_squads(rt) == [1, 4]
        rt.settings.values = {}
        assert rl.join_squads(rt) == []
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# the run loop — how a repeat that came to nothing is reported
# ---------------------------------------------------------------------------

def _stub_loop(tab, rl):
    """Silence the tab's talking and its pause, and collect the status keys it sets.

    The loop is what is under test — what it does with an `Outcome` — so the send is a
    canned answer and the pause between two sends is not waited out.
    """
    said = []
    tab._status = lambda key, **fmt: said.append((key, fmt))
    tab._log = lambda key, **fmt: None
    tab._after = lambda func: None
    rl.RALLY_BETWEEN_S = 0.0
    return said


def test_a_refused_repeat_shows_the_scenarios_own_words():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, _rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel.runtime import Outcome
    from panel.tabs.rally import tab as rl
    from panel.tabs.rally import limits as rallylimits

    was_pause = rl.RALLY_BETWEEN_S
    was_record, rallylimits.record = rallylimits.record, lambda rt, counts, key: counts
    try:
        reason = "the search turned up no boss of level 35"
        said = _stub_loop(tab, rl)
        tab._one_send = lambda stop, kind, level, squad: Outcome(False, reason)
        tab._run_loop(threading.Event(), "boss", 35, [1], 1)
        assert ("rally_tab.refused", {"reason": reason}) in said, said

        # A raise is counted and announced as a raise.
        said = _stub_loop(tab, rl)
        tab._one_send = lambda stop, kind, level, squad: Outcome(True)
        tab._run_loop(threading.Event(), "boss", 35, [1], 1)
        assert "rally_tab.progress" in [k for k, _f in said], said
        assert tab._done == 1, tab._done

        # No reason at all means the scenario BROKE rather than decided — and the tab
        # must not dress that up as a decision.
        said = _stub_loop(tab, rl)
        tab._one_send = lambda stop, kind, level, squad: Outcome(False, "")
        tab._run_loop(threading.Event(), "boss", 35, [1], 1)
        keys = [k for k, _f in said]
        assert "rally_tab.error_short" in keys, said
        assert "rally_tab.refused" not in keys, said
    finally:
        rl.RALLY_BETWEEN_S = was_pause
        rallylimits.record = was_record
        root.destroy()


def test_the_daily_cap_stops_the_run():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, _rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    from panel import rally_limits as rlim
    from panel.runtime import Outcome
    from panel.tabs.rally import tab as rl
    from panel.tabs.rally import limits as rallylimits

    was_pause = rl.RALLY_BETWEEN_S
    # One rally a day, and today's one is already spent.
    limits = rlim.RallyLimits({rl.RALLY_ELITE_TYPE: 1})
    counts = rlim.RallyCounts(rlim._today(), {rl.RALLY_ELITE_TYPE: 1})
    was_read, rallylimits.read = rallylimits.read, lambda _rt: (limits, counts)
    try:
        said = _stub_loop(tab, rl)
        tab._one_send = lambda stop, kind, level, squad: Outcome(True)
        tab._run_loop(threading.Event(), "boss", 35, [1], 3)
        assert "rally_tab.capped" in [k for k, _f in said], said
        assert tab._done == 0, "nothing may go out once the budget is spent"
    finally:
        rl.RALLY_BETWEEN_S = was_pause
        rallylimits.read = was_read
        root.destroy()


# ---------------------------------------------------------------------------
# the monitor
# ---------------------------------------------------------------------------

def test_the_alert_fires_once_per_banner():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._bell = lambda: None
        tab._alert_var.set(True)
        tab._autojoin_var.set(False)
        lines = rt.log.lines
        # A solo march is not a rally: no `team=`, so only the raw line comes through.
        before = len(lines)
        tab._on_line("[rally] march uuid=1 solo")
        assert len(lines) == before + 1, lines[before:]
        # A banner is announced…
        before = len(lines)
        tab._on_line("[rally] march uuid=2 team=77")
        assert len(lines) == before + 2, lines[before:]
        # …and the refresh event for the same banner must not ring again.
        before = len(lines)
        tab._on_line("[rally] march uuid=3 team=77")
        assert len(lines) == before + 1, "only the raw line, no second alert"
    finally:
        root.destroy()


def test_join_now_refuses_with_no_squad_ticked():
    """A join with no squad would be a silent no-op that looked like it had worked."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        played = []
        rt.actions.run = lambda name, args=None, **kw: played.append((name, args))
        before = len(rt.log.lines)
        tab.join_now()
        assert played == [], "no squad ticked — nothing may be sent"
        assert len(rt.log.lines) == before + 1, "…and it must say why"
    finally:
        root.destroy()


def test_the_capture_serves_three_switches_and_the_archive_is_only_the_monitors():
    """The monitor is statistics in a file; joining by itself is not, and never was.

    They were one switch because the archive-writer happened to be the thing spawning
    the capture — so «Присоединяться сам» needed a statistics file nobody asked for, and
    unticking the statistics silently unticked the joining. Three separate wants over
    one capture now: it comes up for any of them, stays up while any of them is on, and
    only «Монитор» — the box that MEANS «write it down» — passes `--out` (#1237).
    """
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        spawned = []

        class _Child:
            def __init__(self, cmd):
                self.cmd = cmd
            def start(self):
                spawned.append(self.cmd)
                return True
            def stop(self):
                spawned.append(["stop"])

        rt.children.spawn = lambda name, cmd, **kw: _Child(cmd)

        # Joining by itself, with the statistics OFF: the capture runs and writes
        # nothing. This is the case the user asked for in as many words.
        for var in (tab._monitor_var, tab._alert_var, tab._autojoin_var):
            var.set(False)
        tab._autojoin_var.set(True)
        tab._sync_capture()
        assert spawned, "auto-join alone did not bring the capture up"
        assert "--no-archive" in spawned[-1], spawned[-1]
        assert "--out" not in spawned[-1], spawned[-1]

        # Ticking the statistics on top re-points the SAME need at a writing child.
        tab._monitor_var.set(True)
        tab._sync_capture()
        assert "--out" in spawned[-1], spawned[-1]
        assert "--no-archive" not in spawned[-1], spawned[-1]

        # Statistics off again, join still on — still listening, still not writing.
        before = len(spawned)
        tab._monitor_var.set(False)
        tab._sync_capture()
        assert "--no-archive" in spawned[-1], spawned[-1]
        assert len(spawned) > before, "the child was never re-pointed"

        # Nothing wanted -> nothing running.
        tab._autojoin_var.set(False)
        tab._sync_capture()
        assert tab._proc is None, "the capture outlived every switch that wanted it"

        # …and the alert alone is reason enough on its own.
        tab._alert_var.set(True)
        tab._sync_capture()
        assert tab._proc is not None, "the alert cannot hear a rally without the capture"
    finally:
        root.destroy()


def test_the_phone_says_whether_anything_will_be_joined_and_with_what():
    """«Галки стоят, и ничего не происходит» is the question the screen must answer.

    Where the squads are the phone already showed; whether a join was ARMED, and with
    which squads, lived only in the window — so from a bus three squads standing at home
    beside a rally nobody joined looked exactly like a bot that was working (#1237).
    Three switches, because any of the three can be the quiet one, and «Автосбор» beside
    them, because it moved onto this tab and a control the window has and the phone does
    not is a control nobody away from the machine can see the state of.

    Readings, not switches: the list is edited at the machine.
    """
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab._monitor_var.set(True)
        tab._alert_var.set(False)
        tab._autojoin_var.set(False)
        pills = {i["label"]: i.get("pill") for i in tab._web_autojoin_card()["items"]}
        assert pills == {"rally.monitor": "rally.state.on",
                         "rally.alert": "rally.state.off",
                         "rally.autojoin": "rally.state.off"}, pills

        # Nothing ticked reads as a WORD, so it says the same in eleven languages.
        card = tab._web_autorally_card()
        squads = [i for i in card["items"] if i["label"] == "autorally.squads"][0]
        assert squads.get("pill") == "rally.state.none", squads

        tab._autojoin_var.set(True)
        tab.autorally._squad_vars[2].set(True)
        tab.autorally._squad_vars[3].set(True)
        card = tab._web_autorally_card()
        squads = [i for i in card["items"] if i["label"] == "autorally.squads"][0]
        # …and the squads themselves are DIGITS, which need no translating.
        assert squads.get("detail") == "2, 3", squads
        assert squads.get("pill") is None, squads
        assert [i for i in tab._web_autojoin_card()["items"]
                if i["label"] == "rally.autojoin"][0]["pill"] == "rally.state.on"
        # The daily cap is on the phone too — it is what silently stopped the joining
        # once already, and «spent/allowed» is the only reading that shows it coming.
        assert card["rows"], card
        assert all("/" in row["value"] for row in card["rows"]), card["rows"]

        # Both cards are on the screen the phone actually gets.
        titles = [c.get("title") for c in tab.web_view()["cards"]]
        assert "rally.frame" in titles and "autorally.frame" in titles, titles
    finally:
        root.destroy()


def test_the_join_recipe_tells_an_empty_list_from_squads_that_are_all_out():
    """Two empty answers, two sentences — the reading alone cannot tell them apart.

    Nobody ticked a squad and every ticked squad is marching both leave the sieve empty,
    and for weeks the auto-join blamed the second for the first (#1237). The count that
    arrived is kept in the game VM so ONE reading answers both: -1 for «none ticked».
    """
    from lastwar_bot import script_engine as se

    src = (ROOT / "src" / "lastwar_bot" / "actions" / "join_rally.md").read_text(
        encoding="utf-8")
    body, _ = se.prepare_source(src, {"squads": []})
    stmts = se.parse_text(body)
    fails = {stmt.condition: stmt.then_block[0].reason
             for stmt in stmts if isinstance(stmt, se.IfStmt)
             and stmt.then_block and isinstance(stmt.then_block[0], se.FailStmt)}
    assert "free_squads == -1" in fails, fails
    assert "free_squads == 0" in fails, fails
    assert fails["free_squads == -1"] != fails["free_squads == 0"], fails
    # …and it costs no extra round trip for THAT question: one reading answers both.
    sentinel = [s for s in stmts if isinstance(s, se.ReadLuaStmt)
                and "__lw_rally_want" in s.text]
    assert len(sentinel) == 1, [s.text[:60] for s in stmts]


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def test_status_keys_are_named_per_kind():
    from panel.tabs.rally import tab as rl
    assert rl._kind_key("searching", rl.RALLY_KIND_ELITE) == "rally_tab.searching"
    assert rl._kind_key("searching", rl.RALLY_KIND_MONSTER) == "rally_tab.searching_monster"
    assert rl._kind_key("raised", rl.RALLY_KIND_MONSTER) == "rally_tab.raised_monster"


def test_every_key_the_tab_uses_exists_in_both_locales():
    from panel.tabs.rally import tab as rl
    keys = ["tab.rally", "rally_tab.frame", "rally_tab.kind", "rally_tab.kind_boss",
            "rally_tab.kind_monster", "rally_tab.level", "rally_tab.level_quick",
            "rally_tab.squads", "rally_tab.repeats", "rally_tab.launch",
            "rally_tab.stop", "rally_tab.hint", "rally_tab.no_squads",
            "rally_tab.refused", "rally_tab.error", "rally_tab.error_short",
            "rally_tab.capped", "rally_tab.busy", "rally_tab.progress",
            "rally_tab.finished", "rally_tab.stopped",
            "rally.frame", "rally.monitor", "rally.alert", "rally.autojoin",
            "rally.state.on", "rally.state.off",
            "rally.state.none",
            "rally.join_now", "rally.hint", "rally.no_squads", "rally.joining",
            "rally.alert.fired", "log.rally.started", "log.rally.stopped",
            "log.rally.ended", "log.rally.listening", "busy",
            "autorally.frame", "autorally.squads", "autorally.drill.squads",
            "autorally.create.squads", "autorally.create.elite"]
    for base in ("searching", "raised"):
        for kind in ("boss", "monster"):
            keys.append(rl._kind_key(base, kind))
    for lang in ("en", "ru"):
        table = json.loads((ROOT / "panel" / "locales" / f"{lang}.json")
                           .read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in table]
        assert not missing, f"{lang}.json misses {missing}"


def test_the_join_counts_what_it_achieved_instead_of_reporting_ok():
    """«Пытается, а эффекта ноль» — the log said OK over a press that did nothing.

    The send is put on the game's own timer and returns before the server has replied,
    so the press cannot tell a join that worked from one that vanished. Only the squads
    standing in a rally afterwards can, and the two endings that used to look identical
    are now three: nothing was out (a quiet success), the press achieved nothing (a
    failure the auto-join will retry), or it joined and says how many (#1237).
    """
    from lastwar_bot import script_engine as se

    src = (ROOT / "src" / "lastwar_bot" / "actions" / "join_rally.md").read_text(
        encoding="utf-8")
    body, _ = se.prepare_source(src, {"squads": [1]})
    stmts = se.parse_text(body)

    reads = [s for s in stmts if isinstance(s, se.ReadLuaStmt)]
    assert any(s.var == "rallies_out" for s in reads), [s.var for s in reads]
    assert any(s.var == "joined" for s in reads), [s.var for s in reads]

    # Nothing out is a deliberate SUCCESS — a trigger firing on every march must not
    # log a failure for an ordinary quiet minute.
    quiet = [s for s in stmts if isinstance(s, se.IfStmt)
             and s.condition == "rallies_out == 0"][0]
    kinds = [type(x).__name__ for x in quiet.then_block]
    assert "StopStmt" in kinds and "FailStmt" not in kinds, kinds

    # …and a press that achieved nothing is a FAILURE, so the auto-join tries again.
    nothing = [s for s in stmts if isinstance(s, se.IfStmt)
               and s.condition == "joined < 1"][0]
    assert [type(x).__name__ for x in nothing.then_block] == ["FailStmt"], nothing

    # The count is read AFTER the press, or it would be measuring the wrong moment.
    order = [i for i, s in enumerate(stmts)]
    tap = [i for i, s in enumerate(stmts)
           if isinstance(s, se.TapStmt) and s.name == "rally_join_launch"][0]
    after = [i for i, s in enumerate(stmts)
             if isinstance(s, se.ReadLuaStmt) and s.var == "joined"][0]
    assert after > tap, f"the verdict is read before the press ({after} < {tap})"
    assert order


def test_a_busy_game_makes_the_join_wait_rather_than_drop_the_rally():
    """«занят — дождись завершения» threw the banner away instead of waiting for it.

    A rally is seconds long during an event and the game's claim is held by short
    things — a status read, a timer's errand, the auto-join TRIGGER doing the same job
    from the other side. Dropping the join the instant the claim is refused lost two
    banners in one minute on a live event, each with the claim free again a moment
    later (#1237). It waits now, on its own worker thread, and only gives up when the
    wait runs out.
    """
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        root, rt, tab = _tab()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return
    try:
        tab.JOIN_CLAIM_WAIT_SEC = 1.0
        played = []
        rt.actions.play = lambda name, args=None, **kw: played.append(name) or _Ok()

        # Busy for the first two asks, then free: the join must still happen.
        asks = {"n": 0}

        def claim(owner="panel"):
            asks["n"] += 1
            return asks["n"] > 2

        rt.game.claim = claim
        tab._join_work([1])
        assert played == ["join_rally"], (played, asks)
        assert asks["n"] == 3, asks

        # …and a game that never frees up gives the banner up rather than hanging.
        played.clear()
        rt.game.claim = lambda owner="panel": False
        before = len(rt.log.lines)
        tab._join_work([1])
        assert played == [], played
        assert len(rt.log.lines) == before + 1, "it must say it gave up, once"
    finally:
        root.destroy()


def test_the_join_tries_the_screenless_send_before_it_opens_anything():
    """The squad screen is the FALLBACK, not the route (#1238).

    It adds nothing to the message — the send builds that out of the squad — so the join
    is one press whenever the squad has soldiers in it. The screen earns its place on the
    one case the send cannot cover: a squad standing empty, which the client refuses to
    send before a byte leaves.

    Pinned because the order is the whole saving: a run that opens the screen first pays
    four presses and a couple of seconds for a rally that lasts one minute.
    """
    from lastwar_bot import script_engine as se

    src = (ROOT / "src" / "lastwar_bot" / "actions" / "join_rally.md").read_text(
        encoding="utf-8")
    body, _ = se.prepare_source(src, {"squads": [1]})
    stmts = se.parse_text(body)

    gate = [s for s in stmts if isinstance(s, se.IfStmt) and s.condition == "soldiers > 0"]
    assert gate, "the screenless send is not gated on the squad having soldiers"
    inner = [type(x).__name__ for x in gate[0].then_block]
    assert "TapStmt" in inner, inner
    assert gate[0].then_block[0].name == "rally_join_send", gate[0].then_block[0]

    # …and it happens BEFORE the screen is opened, or it is not a fast path at all.
    send = stmts.index(gate[0])
    opens = [i for i, s in enumerate(stmts)
             if isinstance(s, se.TapStmt) and s.name == "rally_join_open"]
    assert opens and send < opens[0], (send, opens)

    # A late send must not cost a second squad: the fallback asks the map first.
    guard = [s for s in gate[0].then_block
             if isinstance(s, se.ReadLuaStmt) and s.var == "already_in"]
    assert guard, "nothing checks whether the send landed late before opening the screen"


def test_the_arm_prefers_a_squad_that_can_actually_be_sent():
    """A squad can be at home, idle and EMPTY — and taking it forces the screen (#1238).

    The sieve upstream only asks «is it home and free». If squad 1 is home and empty while
    squad 3 is home with an army, arming squad 1 sends an otherwise headless join through
    the windows for nothing. So the arm picks the first ticked squad that has soldiers, and
    falls back to the first free one when none has — which is where the screen belongs,
    since filling an empty squad is what it is for.
    """
    import importlib

    la = importlib.import_module("lib.lua_actions")
    arm = la.rally_join_arm()
    assert "totalSoldierNum" in arm, "the arm does not look at soldiers at all"
    assert "soldiers_of" in arm and "if slot == nil then slot = squads[1] end" in arm, arm[-400:]
    # the marker carries the count, so a log line says WHY a run went to the screen
    assert 'soldiers="..tostring(soldiers_of' in arm, arm[-300:]


def test_a_join_is_sent_where_the_joiners_gather_not_where_the_rally_goes():
    """`targetPos` is the monster; a joining squad marches to the leader's tile (#1237)."""
    import importlib

    la = importlib.import_module("lib.lua_actions")
    assert "joinpoint" in la._RALLY_PRELUDE, "the gathering tile is not read at all"
    assert "startPos" in la._RALLY_PRELUDE, la._RALLY_PRELUDE[:200]
    # The listing keeps the target; only the join side swaps it for the gathering tile.
    assert "r.point = r.joinpoint" in la._RALLY_PRELUDE_MINE
    assert "targetPos" in la._RALLY_PRELUDE, "the listing lost where the rally is going"
    # …and the direct sends use it rather than the target.
    assert "r.joinpoint or r.point" in la.join_next_rally()


class _Ok:
    ok = True
    reason = ""


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
