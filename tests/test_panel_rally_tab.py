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
import re
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


def test_the_capture_driven_join_asks_the_same_question_before_it_starts():
    """The tab is the SECOND driver, and it must not start a pointless run either (#1281).

    The schedule's «rally_auto_join» trigger is not the only thing that plays the join:
    the capture's reader raises one for every banner it hears, on a thread of its own,
    and that path never passes the schedule's gate. Measured live on the Marshal event —
    41 pushes, 34 runs, four of the six that joined something came through here.
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
        from panel.tabs.rally import limits as rallylimits

        tab._bell = lambda: None
        tab._alert_var.set(False)
        tab._autojoin_var.set(True)
        started = []
        tab.join_now = lambda: started.append(1)
        tab._after = lambda fn: fn()

        answers = {"reason": "rally.skip.squads_out"}
        rallylimits.join_precondition = lambda _rt, _squads=None: answers["reason"]
        tab._on_line("[rally] push.alliance.march.create  team=4242  participants=1 [x]")
        assert started == [], "a run was raised with every squad out"

        # …and when somebody is home the banner is joined exactly as before.
        answers["reason"] = None
        tab._on_line("[rally] push.alliance.march.create  team=4343  participants=1 [x]")
        assert started == [1], started
    finally:
        root.destroy()


def test_the_tab_remembers_how_big_each_banner_is_and_hands_it_to_the_join():
    """`slots=2/5` off the capture line becomes the join's `slots` argument (#1281).

    A rally that has not left yet can still be shut, and the client's own march record
    has no field that says so — `assemblyMarchMax` is on the wire only, exactly like the
    target's config id. The player watched the Marshal event and named the symptom: the
    active-rally list was full of banners nobody could enter and every squad we had was
    being thrown at one. Nine banners measured on the wire during that event read 5 of 5.
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
        tab._bell = lambda: None
        tab._alert_var.set(False)
        tab._autojoin_var.set(False)
        tab._on_line("[rally] push.alliance.march.create  team=77  participants=2 [a] "
                     "content=1031023  slots=2/5")
        tab._on_line("[rally] push.alliance.march.refresh  team=88  participants=5 [b] "
                     "slots=5/5")
        # A line with no seats at all leaves nothing behind — an unheard size is not a
        # full banner, and inventing one would shut a rally that was open.
        tab._on_line("[rally] push.alliance.march.create  team=99  participants=1 [c]")
        assert tab._slots == {"77": "5", "88": "5"}, tab._slots

        from panel.tabs.rally import tab as rallytab
        rt.tabs = {rallytab.RallyTab.ID: tab}
        rendered = dict(pair.split(":") for pair in rallytab.slot_map(rt).split(","))
        assert rendered == {"77": "5", "88": "5"}, rendered
    finally:
        root.destroy()


def test_a_refused_banner_is_written_off_and_the_squads_go_to_the_next_one():
    """«Мест уже нет» is terminal: the same banner is not asked twice (#1281).

    The game's own words for it are key `390857` — «Rally participant full. Unable to
    join.» Nothing about that banner will change while it stands, so a second squad spent
    on it is a squad not spent on the rally beside it. The recipe writes the banners this
    pass sent to into `__lw_rally_shut` and presses again, and the chunk passes over them.
    """
    from lastwar_bot import script_engine as se

    src = (ROOT / "src" / "lastwar_bot" / "actions" / "join_rally.md").read_text(
        encoding="utf-8")
    stmts = se.parse_text(se.prepare_source(src, {})[0])

    # The run starts with an EMPTY write-off list: a refusal is terminal for the banner,
    # not for ever — the next run asks the map again.
    assert "__lw_rally_shut = {}" in stmts[0].chunk, stmts[0].chunk

    presses = [i for i, s in enumerate(stmts) if isinstance(s, se.TapStmt)]
    marks = [i for i, s in enumerate(stmts)
             if isinstance(s, se.LuaStmt) and "__lw_rally_sent_teams" in s.chunk]
    assert marks, [type(s).__name__ for s in stmts]
    # The write-off happens AFTER a press and is followed by another one: that is what
    # «go to the next banner in the same run» is.
    assert any(p < marks[0] for p in presses), (presses, marks)
    assert any(p > marks[0] for p in presses), (presses, marks)


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


def test_the_join_names_every_squad_and_rally_it_passed_over():
    """No squad is left behind without a word for why (#1281).

    «Тихо не поехали» is the fault this pins. Nobody ticked a squad, every ticked squad
    is marching, and a ticked squad standing at home with no soldiers all used to leave
    the same empty sieve, and the auto-join blamed whichever it happened to check first
    (#1237). Each has its own word now, written by the chunk that does the sieving, and
    the recipe reads the whole sentence back and logs it — so a run that joined nothing
    always says which of them it was.

    Read off the Lua rather than the recipe because the sieve moved INTO the one press
    the recipe makes: eight readings before the send cost 100 s on a live client, which
    is longer than the banner they were about.
    """
    import importlib

    from lastwar_bot import script_engine as se

    la = importlib.import_module("lib.lua_actions")
    chunk = la.rally_join_all()
    for word in ("':out'", "':empty'", "':no-formation'"):
        assert word in chunk, f"no word for a squad passed over: {word}"
    assert "no rally of this alliance is out" in chunk, chunk[-600:]
    assert "not one of the chosen squads can be sent" in chunk, chunk[-600:]
    assert "more rallies than squads" in chunk, chunk[-600:]
    assert "__lw_rally_report" in chunk

    # …and the recipe reads that sentence back and puts it in the log, every run.
    src = (ROOT / "src" / "lastwar_bot" / "actions" / "join_rally.md").read_text(
        encoding="utf-8")
    body, _ = se.prepare_source(src, {"squads": []})
    stmts = se.parse_text(body)
    reads = [s for s in stmts if isinstance(s, se.ReadLuaStmt)]
    assert any(s.var == "report" and "__lw_rally_report" in s.text for s in reads), \
        [s.var for s in reads]
    # …and NOT through a placeholder. `{x}` is substituted once, before the run
    # (docs/dsl.md), so a value a later `READ_LUA` writes never reaches a `LOG` or a
    # `FAIL` — it prints as the literal `{x}`, which is what the live log showed for a
    # day (`the game says: {refusal}`). The reading logs its own value; the sentence
    # beside it must not pretend to carry one.
    assert not [s for s in stmts
                if isinstance(s, (se.LogStmt, se.FailStmt))
                and re.search(r"\{(report|joined|refusal|todo)\}",
                              getattr(s, "text", "") or getattr(s, "reason", "") or "")], \
        "a LOG or FAIL carries a runtime placeholder that will print as a literal"


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
    assert any(s.var == "joined" for s in reads), [s.var for s in reads]
    assert any(s.var == "todo" for s in reads), [s.var for s in reads]

    # Nothing SENT is a deliberate success — a trigger firing on every alliance march
    # must not log a failure for an ordinary quiet minute, and the chunk has already
    # said in words which quiet minute it was.
    quiet = [s for s in stmts if isinstance(s, se.IfStmt)
             and s.condition == "todo == 0"][0]
    kinds = [type(x).__name__ for x in quiet.then_block]
    assert "StopStmt" in kinds and "FailStmt" not in kinds, kinds

    # …while a send that achieved nothing IS a failure: that is the client's link, not
    # a quiet map, and it is the one ending worth waking somebody for.
    fails = [s for s in stmts if isinstance(s, se.FailStmt)]
    assert len(fails) == 1, [f.reason for f in fails]

    # The count is read AFTER the press, or it would be measuring the wrong moment.
    tap = [i for i, s in enumerate(stmts)
           if isinstance(s, se.TapStmt) and s.name == "rally_join_all"][0]
    after = [i for i, s in enumerate(stmts)
             if isinstance(s, se.ReadLuaStmt) and s.var == "joined"][0]
    assert after > tap, f"the verdict is read before the press ({after} < {tap})"


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

        def claim(owner="panel", priority=0):
            asks["n"] += 1
            return asks["n"] > 2

        rt.game.claim = claim
        tab._join_work([1])
        assert played == ["join_rally"], (played, asks)
        assert asks["n"] == 3, asks

        # …and a game that never frees up gives the banner up rather than hanging.
        played.clear()
        rt.game.claim = lambda owner="panel", priority=0: False
        before = len(rt.log.lines)
        tab._join_work([1])
        assert played == [], played
        assert len(rt.log.lines) == before + 1, "it must say it gave up, once"
    finally:
        root.destroy()


def test_the_join_opens_nothing_and_reaches_the_send_in_two_calls():
    """No window at any point, and as little as possible in front of the send (#1281).

    The screen was the fallback for a squad standing EMPTY, and it cost four more
    presses. The person asked for a march with no windows, and the measurement agrees:
    a call into the game VM was 1.3 s at best and 10–19 s under the panel's ordinary
    load, so four presses spent filling one squad are four presses the next banner pays
    for. An empty squad is now reported as `empty` and left at home.

    THE TWO CALLS ARE THE ACCEPTANCE CRITERION, so they are pinned rather than described:
    park the argument, then press. The version this replaced took EIGHT readings before
    it sent anything — measured at 100 s to the send on a live client, twice over.
    """
    from lastwar_bot import script_engine as se

    src = (ROOT / "src" / "lastwar_bot" / "actions" / "join_rally.md").read_text(
        encoding="utf-8")
    body, _ = se.prepare_source(src, {"squads": [1]})
    stmts = se.parse_text(body)

    press = [i for i, s in enumerate(stmts)
             if isinstance(s, se.TapStmt) and s.name == "rally_join_all"]
    # WHAT IS PINNED IS THE FIRST press, not the only one. Later passes exist and are
    # supposed to: a banner that answers «мест уже нет» is written off and the squads go
    # to the next one in the same run (#1281). They all sit AFTER the first send and
    # after the wait that proves it, so none of them is in front of a banner.
    assert press and press[0] == 1, [type(s).__name__ for s in stmts]

    # Nothing that reaches the game stands in front of it but the one park.
    before = [s for s in stmts[:press[0]]
              if isinstance(s, (se.TapStmt, se.LuaStmt, se.ReadLuaStmt))]
    assert len(before) == 1, [type(s).__name__ for s in before]
    assert isinstance(before[0], se.LuaStmt) and "__lw_rally_squads" in before[0].chunk

    # …and no screen is opened by this recipe at all. The empty squad — the one thing the
    # send cannot cover — is a FETCH now and not a window (#1285): the client had simply
    # never asked the server for that squad's army. It is still reached only down the
    # branch where NOTHING could be sent, after every squad that had an army has gone.
    windows = [s.name for s in stmts if isinstance(s, se.TapStmt)
               and s.name in ("rally_join_open", "rally_join_squad",
                              "rally_join_launch", "close")]
    assert windows == [], windows

    branch = [s for s in stmts if isinstance(s, se.IfStmt) and s.condition == "todo < 0"]
    assert branch, [getattr(s, "condition", None) for s in stmts]
    # The second chance is the FETCH — one request for the army of every squad reading
    # zero — and it is written out here rather than CALLed. A sub-recipe's failure fails
    # the CALLER (`script_engine._do_call`), which is how «nothing could be sent» became
    # «the join run failed» 59 times in an hour on a live measurement (#1285). It is a
    # `LUA` chunk in `pcall`s of its own, so nothing on a banner's path can throw.
    fetch = [x for x in branch[0].then_block
             if isinstance(x, se.LuaStmt) and "GetFormationSoldier" in x.chunk]
    assert len(fetch) == 1, [type(x).__name__ for x in branch[0].then_block]
    assert fetch[0].chunk.startswith("pcall("), fetch[0].chunk[:60]
    # …and the branch presses again afterwards, or the fetch achieved nothing.
    assert [x.name for x in branch[0].then_block
            if isinstance(x, se.TapStmt)] == ["rally_join_all"]
    assert not [s for s in stmts if type(s).__name__ == "CallStmt"], \
        "a sub-recipe on the banner's path can fail the run — this one must not have any"


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
