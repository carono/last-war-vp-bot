r"""The triggers module — the catalogue it reads, and the watcher that fires.

A *trigger* (task #1128) runs its scenario when a wire event lands, not when a
period passes: the alliance-help order answers «Помочь всем» the instant a
request's push crosses the wire. Two halves are tested here:

  * :class:`panel.triggers.TriggerCatalogue` — the configured list: a trigger round-
    trips through the file, a junk entry costs that entry not the whole set, and the
    switches re-derive against the current list;
  * :class:`panel.triggers.TriggerWatcher` — the bookkeeping: :meth:`sync` brings a
    listener up for an enabled trigger and takes it down when unticked; a fired push
    submits the scenario to the shared queue; arming sweeps once; a dead listener is
    forgotten so the next sync respawns it; :meth:`stop` takes every listener down.

``panel.triggers`` imports no Tk and spawns nothing itself — the panel passes the
spawn and the submit in — so this runs anywhere::

    python3 tests/test_panel_triggers.py
    C:\Python312\python.exe tests\test_panel_triggers.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from panel import triggers as triggersmod  # noqa: E402


# -- the catalogue ----------------------------------------------------------
def test_a_trigger_round_trips_through_the_file():
    entries = [{"name": "ah", "event_pattern": "al.help.new",
                "scenario": "help_ally", "enabled": True}]
    cat = triggersmod.parse_catalogue(entries)
    ah = cat.by_name("ah")
    assert ah.event_pattern == "al.help.new"
    assert ah.scenario == ("help_ally",)
    assert ah.enabled is True
    assert ah.as_dict()["event_pattern"] == "al.help.new"


def test_a_junk_entry_costs_that_entry_not_the_set():
    entries = [
        {"name": "good", "event_pattern": "al.help.new", "scenario": "help_ally"},
        {"event_pattern": "x", "scenario": "y"},          # no name
        {"name": "no_pattern", "scenario": "y"},          # no event_pattern
    ]
    cat = triggersmod.parse_catalogue(entries)
    assert cat.names() == ["good"]
    assert len(cat.errors) == 2


def test_the_builtin_alliance_help_trigger_ships():
    ah = triggersmod.default_catalogue().by_name("alliance_help")
    assert ah is not None
    assert ah.event_pattern == "al.help.new"
    assert ah.scenario == ("help_ally",)
    assert not ah.enabled                      # opt-in, exactly as the old box was


def test_the_builtin_rally_monitor_trigger_ships():
    rm = triggersmod.default_catalogue().by_name("rally_monitor")
    assert rm is not None
    assert not rm.is_poll and rm.kind == triggersmod.KIND_WIRE
    assert rm.event_pattern == "push.alliance.march"
    assert rm.scenario == ("rally_monitor",)
    assert not rm.enabled                      # opt-in — it records, it does not act


def test_the_builtin_rally_auto_join_trigger_ships():
    raj = triggersmod.default_catalogue().by_name("rally_auto_join")
    assert raj is not None
    assert not raj.is_poll and raj.kind == triggersmod.KIND_WIRE
    assert raj.event_pattern == "push.alliance.march"
    assert raj.scenario == ("join_rally",)     # joins with the profile's JOIN squads
    assert not raj.enabled                      # opt-in


def test_errand_args_injects_live_join_squads():
    """rally_auto_join takes its squads from the profile at fire time, not the trigger.

    The rule belongs to the rally code (it answers in a profile that does not show the
    tab), and the schedule only knows that SOMETHING was registered under that name.
    """
    import types
    from panel.runtime.schedule import Schedule

    sched = Schedule.__new__(Schedule)
    sched._args = {}
    sched.register_args("rally_auto_join", lambda: {"squads": [2, 3]})

    # a plain errand passes its own args through unchanged…
    plain = triggersmod.Trigger(name="x", scenario=("y",), args={"a": 1})
    assert sched.args(plain) == {"a": 1}
    # …the rally auto-join one gets the live squads merged in.
    raj = triggersmod.default_catalogue().by_name("rally_auto_join")
    assert sched.args(raj)["squads"] == [2, 3]


def test_a_trigger_whose_tab_is_missing_is_not_offered():
    """The point of replacing the sentinels: a listener must not be spawned for work
    that has nowhere to land (docs/research/panel-tabs-refactor.md §3.2)."""
    import types
    from panel.runtime.schedule import Schedule

    sched = Schedule.__new__(Schedule)
    sched._handlers, sched._needs_game = {}, set()
    sched.trigger_catalogue = triggersmod.default_catalogue()
    sched.trigger_config_source = lambda: {"inventory_refresh": True,
                                           "alliance_help": True}
    # No tab registered its handler, so the hook-shaped trigger is not offered…
    assert sched.trigger_config()["inventory_refresh"] is False
    # …while one naming a real scenario always is: a scenario belongs to the bot.
    assert sched.trigger_config()["alliance_help"] is True
    # Once the tab is there, it is offered again.
    sched.register(types.SimpleNamespace(
        TRIGGERS=({t.name: t for t in
                   __import__("panel.tabs.inventory", fromlist=["InventoryTab"])
                   .InventoryTab.TRIGGERS}["inventory_refresh"],),
        refresh_live=lambda: None))
    assert sched.trigger_config()["inventory_refresh"] is True


def test_the_builtin_resource_tracker_trigger_ships():
    rt = triggersmod.default_catalogue().by_name("resource_tracker")
    assert rt is not None
    assert not rt.is_poll and rt.kind == triggersmod.KIND_WIRE
    assert rt.event_pattern == "push.resource.item.update"
    assert not rt.enabled                       # opt-in — it records, it does not act


def test_the_builtin_leaderboard_collect_trigger_ships():
    lc = triggersmod.default_catalogue().by_name("leaderboard_collect")
    assert lc is not None
    assert not lc.is_poll and lc.kind == triggersmod.KIND_WIRE
    assert lc.event_pattern == "rank"           # covers al.rank / champion.duel…rank
    assert not lc.enabled                       # opt-in — a standing collector


def test_the_builtin_session_kick_trigger_is_a_poll():
    sk = triggersmod.default_catalogue().by_name("session_kick")
    assert sk is not None
    assert sk.is_poll and sk.kind == triggersmod.KIND_POLL
    assert sk.check                            # a Lua check, not a wire pattern
    assert sk.scenario == ("recover_from_kick",)
    assert sk.interval_sec >= triggersmod.MIN_POLL_INTERVAL_SEC
    assert not sk.enabled                      # opt-in


def test_a_poll_trigger_round_trips_and_keeps_its_kind():
    entries = [{"name": "k", "kind": "poll", "check": "foo()",
                "scenario": "bar", "interval_sec": 20, "cooldown_sec": 40}]
    cat = triggersmod.parse_catalogue(entries)
    k = cat.by_name("k")
    assert k.is_poll and k.check == "foo()"
    assert k.interval_sec == 20 and k.cooldown_sec == 40
    d = k.as_dict()
    assert d["kind"] == "poll" and d["check"] == "foo()"
    assert "event_pattern" not in d            # a poll writes no wire pattern


def test_a_poll_without_a_check_is_dropped():
    # A valid entry alongside, so the junk one is dropped rather than the whole file
    # falling back to the built-in defaults ("no usable triggers → use defaults").
    cat = triggersmod.parse_catalogue([
        {"name": "ok", "event_pattern": "al.help.new", "scenario": "help_ally"},
        {"name": "k", "kind": "poll", "scenario": "x"},
    ])
    assert cat.names() == ["ok"]
    assert any("no check" in e for e in cat.errors)


# -- an old file grows the new built-ins (task #1136) ------------------------
def test_merge_new_appends_the_missing_builtins_switched_off():
    old = triggersmod.parse_catalogue([
        {"name": "alliance_help", "event_pattern": "al.help.new",
         "scenario": "help_ally", "enabled": True},
    ])
    grown, added = triggersmod.merge_new(old)
    assert "session_kick" in added and "resource_tracker" in added
    assert grown.names()[0] == "alliance_help"          # the old entry stays first
    # everything the built-in list ships is now on the list…
    assert set(grown.names()) >= {t.name for t in triggersmod.DEFAULT_TRIGGERS}
    # …and every newcomer arrives opt-in, so a start cannot begin acting on its own
    assert all(grown.by_name(name).enabled is False for name in added)


def test_merge_new_leaves_a_complete_file_alone():
    cat = triggersmod.default_catalogue()
    same, added = triggersmod.merge_new(cat)
    assert added == () and same is cat


def test_merge_new_keeps_the_operators_own_settings():
    old = triggersmod.parse_catalogue([
        {"name": "alliance_help", "event_pattern": "custom.event",
         "scenario": ["help_ally", "collect_base"], "enabled": True,
         "args": {"squad": 2}},
    ])
    grown, _ = triggersmod.merge_new(old)
    ah = grown.by_name("alliance_help")
    assert ah.enabled is True                  # the switch is the operator's
    assert ah.event_pattern == "custom.event"  # so is the event…
    assert ah.scenario == ("help_ally", "collect_base")   # …the scenario…
    assert ah.args == {"squad": 2}                        # …and the args


def test_loading_an_old_file_grows_it_on_disk():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "triggers.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([{"name": "alliance_help", "event_pattern": "al.help.new",
                        "scenario": "help_ally", "enabled": True}], fh)
        cat = triggersmod.load_catalogue(path)
        assert "session_kick" in cat.names()
        assert cat.by_name("alliance_help").enabled is True
        # the growth was written back, so the next start reads the same list
        with open(path, encoding="utf-8") as fh:
            on_disk = json.load(fh)
        assert [e["name"] for e in on_disk] == cat.names()
        assert on_disk[0]["enabled"] is True


def test_an_unreadable_file_is_not_grown_or_overwritten():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "triggers.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        cat = triggersmod.load_catalogue(path)
        assert cat.errors                       # the panel says so…
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == "{ not json"    # …and the file is left as it was


def test_with_enabled_moves_only_the_switch():
    cat = triggersmod.default_catalogue()
    flipped = cat.with_enabled({"alliance_help": True})
    ah = flipped.by_name("alliance_help")
    assert ah.enabled is True
    # the pattern and scenario are untouched
    assert ah.event_pattern == "al.help.new"
    assert ah.scenario == ("help_ally",)


# -- the watcher ------------------------------------------------------------
class _Handle:
    """A stand-in for the spawned child: it only remembers it was stopped."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _Harness:
    """A watcher wired to fakes, so a test can toggle config and fire a push."""

    def __init__(self, catalogue) -> None:
        self.catalogue = catalogue
        self.config: dict = {}
        self.spawned: list[_Handle] = []
        self.submitted: list[str] = []
        self.fires: dict = {}                  # name -> the on_fire callback
        self.log: list = []
        self.watcher = triggersmod.TriggerWatcher(
            catalogue=lambda: self.catalogue,
            config=lambda: self.config,
            spawn=self._spawn,
            submit=lambda t: self.submitted.append(t.name),
            log=lambda key, **fmt: self.log.append((key, fmt)),
        )

    def _spawn(self, trigger, on_fire):
        handle = _Handle(trigger.name)
        self.spawned.append(handle)
        self.fires[trigger.name] = on_fire
        return handle


def _catalogue():
    return triggersmod.TriggerCatalogue([
        triggersmod.Trigger(name="ah", event_pattern="al.help.new",
                            scenario=("help_ally",)),
    ])


def test_sync_brings_a_listener_up_only_for_an_enabled_trigger():
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    assert h.watcher.watching() == {"ah"}
    h.watcher.sync()                            # nothing changed → no second listener
    assert len(h.spawned) == 1


def test_an_off_trigger_is_never_watched():
    h = _Harness(_catalogue())
    h.config = {"ah": False}
    h.watcher.start()
    assert h.watcher.watching() == set()
    assert h.spawned == []


def test_arming_a_trigger_sweeps_once():
    """Arming runs the errand once, to clear a request already waiting at start."""
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    assert h.submitted == ["ah"]                # one sweep on arm, no push needed


def test_a_fired_push_submits_the_scenario():
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    h.submitted.clear()                         # drop the arm-time sweep
    h.fires["ah"]()                             # the listener saw the push
    assert h.submitted == ["ah"]


def test_a_push_that_keeps_arriving_is_said_once_and_then_rolled_up():
    """One trigger's log line per push buried a live log: 6 675 of them in a day
    for a single trigger (#1293). The first is said, the rest are counted."""
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    h.log.clear()
    for _ in range(200):
        h.fires["ah"]()
    assert len(h.log) == 1, [k for k, _f in h.log]
    assert h.log[0][0] == "triggers.log.fire", h.log[0]

    # The window is up: one line, carrying everything that piled up inside it.
    h.watcher._fires["ah"][2] -= triggersmod.FIRE_NOTE_SEC + 1
    h.fires["ah"]()
    assert len(h.log) == 2, [k for k, _f in h.log]
    key, fmt = h.log[1]
    assert key == "triggers.log.fire_more", key
    assert fmt["count"] == 200, fmt         # the 199 counted, plus this one


def test_a_different_outcome_is_said_at_once_however_recent_the_last_line():
    """«уже в очереди» after «запускаю» is news, not a repeat — the roll-up must
    not swallow it, or a change of behaviour would go unrecorded for a minute."""
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    trigger = next(iter(h.catalogue))
    h.log.clear()
    assert h.watcher._note_fire(trigger, "triggers.log.fire") is True
    assert h.watcher._note_fire(trigger, "triggers.log.fire") is False
    assert h.watcher._note_fire(trigger, "triggers.log.fire_waiting") is True
    assert [k for k, _f in h.log] == ["triggers.log.fire",
                                      "triggers.log.fire_waiting"], h.log


def test_unticking_takes_the_listener_down():
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    handle = h.spawned[0]
    h.config = {"ah": False}
    h.watcher.sync()
    assert h.watcher.watching() == set()
    assert handle.stopped is True


def test_a_dead_listener_is_forgotten_and_respawned():
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    assert h.watcher.watching() == {"ah"}
    h.watcher.on_listener_exit("ah")            # the child died on its own
    assert h.watcher.watching() == set()
    h.watcher.sync()                            # still on → a fresh listener comes up
    assert h.watcher.watching() == {"ah"}
    assert len(h.spawned) == 2


def test_stop_takes_every_listener_down():
    h = _Harness(_catalogue())
    h.config = {"ah": True}
    h.watcher.start()
    h.watcher.stop()
    assert h.watcher.watching() == set()
    assert h.spawned[0].stopped is True
    h.watcher.sync()                            # stopped → sync does nothing
    assert h.watcher.watching() == set()


# -- poll triggers ----------------------------------------------------------
def _poll_catalogue():
    return triggersmod.TriggerCatalogue([
        triggersmod.Trigger(name="kick", kind=triggersmod.KIND_POLL,
                            check="x", scenario=("recover",),
                            interval_sec=5, cooldown_sec=5),
    ])


def test_a_poll_trigger_fires_when_the_check_is_true():
    """The poll thread submits the scenario the moment the check comes back true."""
    import threading
    fired = threading.Event()
    submitted = []
    watcher = triggersmod.TriggerWatcher(
        catalogue=_poll_catalogue,
        config=lambda: {"kick": True},
        spawn=lambda t, f: None,                # no wire triggers here
        submit=lambda t: (submitted.append(t.name), fired.set()),
        log=lambda *a, **k: None,
        poll=lambda t: True,                    # the kick is on screen
    )
    watcher.start()
    try:
        assert watcher.watching() == {"kick"}   # a poll handle, not a wire child
        assert fired.wait(2.0), "the poll never fired"
        assert submitted == ["kick"]
    finally:
        watcher.stop()
    assert watcher.watching() == set()


def test_a_poll_trigger_that_reads_false_never_fires():
    import threading
    fired = threading.Event()
    watcher = triggersmod.TriggerWatcher(
        catalogue=_poll_catalogue,
        config=lambda: {"kick": True},
        spawn=lambda t, f: None,
        submit=lambda t: fired.set(),
        log=lambda *a, **k: None,
        poll=lambda t: False,                   # no kick
    )
    watcher.start()
    try:
        assert not fired.wait(0.5)              # nothing fired
    finally:
        watcher.stop()


# -- adaptive backoff -------------------------------------------------------
def test_backoff_escalates_caps_and_resets():
    """The whole session-kick story on the state alone, driving time by hand.

    A quick refire (sooner than refire_window after the last run) grows the delay by
    a step, capped at max; a fire after the session held past stability resets it.
    """
    p = triggersmod.BackoffPolicy(initial_sec=900, step_sec=900, max_sec=2700,
                                  stability_sec=600, refire_window_sec=600)
    st = triggersmod.BackoffState(p)

    # First kick ever: no prior run → the initial delay (15 min). Run lands at +delay.
    assert st.plan(0) == 900
    st.mark_run(900)
    # Kicked 100 s after that run (100 < 600) → +step → 30 min.
    assert st.plan(1000) == 1800
    st.mark_run(2800)
    # Kicked quickly again → +step → 45 min.
    assert st.plan(2900) == 2700
    st.mark_run(5600)
    # Quick again → capped at max, does not pass 45 min.
    assert st.plan(5700) == 2700
    st.mark_run(8400)
    # The session finally holds: kicked 700 s after the run (700 >= 600) → reset.
    assert st.plan(9100) == 900


def test_backoff_holds_between_the_windows():
    """With the two windows apart, an elapsed that falls between them changes nothing:
    not a quick refire (no escalation), not yet settled (no reset)."""
    p = triggersmod.BackoffPolicy(initial_sec=900, step_sec=900, max_sec=2700,
                                  stability_sec=1200, refire_window_sec=600)
    st = triggersmod.BackoffState(p)
    assert st.plan(0) == 900
    st.mark_run(900)
    st.plan(1000)                       # 100 s → escalate to 1800
    st.mark_run(2800)
    # 800 s after the run: 600 <= 800 < 1200 → held where it is.
    assert st.plan(3600) == 1800


def test_backoff_policy_reads_partial_and_junk():
    base = triggersmod.BackoffPolicy(initial_sec=900, step_sec=900, max_sec=2700,
                                     stability_sec=600, refire_window_sec=600)
    # Only max_sec set — the rest fall back to the base.
    pol = triggersmod.BackoffPolicy.from_raw({"max_sec": 3600}, base)
    assert pol.max_sec == 3600 and pol.initial_sec == 900 and pol.step_sec == 900
    # A junk value falls back rather than crashing the whole policy.
    pol2 = triggersmod.BackoffPolicy.from_raw({"initial_sec": "oops"}, base)
    assert pol2.initial_sec == 900
    # Not an object → no policy at all.
    assert triggersmod.BackoffPolicy.from_raw(None) is None


def test_the_session_kick_trigger_watches_and_does_not_act():
    """WHAT IT BECAME, and why (#1296). Two mechanisms were aimed at one event — this poll
    and `panel/runtime/recovery.py` — with different criteria and, for a while, an
    escalating wait each. Only `recovery.py` had ever recovered a kick (fourteen times
    live against zero fires here, because no poll trigger could fire at all), so the act
    stays there and this side keeps the eyes.

    Its own backoff is GONE with the same stroke: 15 → 30 → 45 min lives beside the act
    now (`recovery.KICK_HOLD_STEP_SEC` …). Two identical escalations in two modules is two
    executors deferred, not one policy.
    """
    sk = triggersmod.default_catalogue().by_name("session_kick")
    assert sk.observe is True, "the kick poll must not be able to act"
    assert sk.backoff is None, "the wait belongs to the module that acts"
    #: the scenario stays: it is what it would play the day `recover_from_kick` is proven
    #: live and becomes the act (docs/research/session-kick.md)
    assert sk.scenario == ("recover_from_kick",)


def test_an_observer_never_submits_its_scenario():
    """The whole point of the flag, driven through the watcher: the fire is noted and the
    scenario is not handed to the queue."""
    submitted = []
    said = []
    trigger = triggersmod.Trigger(name="watcher_only", kind=triggersmod.KIND_POLL,
                                  check="1 == 1", scenario=("recover_from_kick",),
                                  observe=True, enabled=True)
    w = triggersmod.TriggerWatcher(
        catalogue=lambda: triggersmod.TriggerCatalogue([trigger], []),
        config=lambda: {"watcher_only": {"enabled": True}},
        spawn=lambda *a, **k: None,
        submit=lambda errand: submitted.append(errand.name) or "queued",
        poll=lambda t: True,
        log=lambda key, **fmt: said.append(key))
    w._fire(trigger)
    assert submitted == [], "an observer submitted its scenario"
    assert "triggers.log.observed" in said, said


def test_an_observer_gets_no_backoff_state_however_the_file_is_edited():
    """A hand-edited `triggers.json` must not be able to give the observer a wait of its
    own back — that is the second escalation returning through the side door."""
    trigger = triggersmod.Trigger(
        name="watcher_only", kind=triggersmod.KIND_POLL, check="1 == 1",
        scenario=("x",), observe=True, enabled=True,
        backoff=triggersmod.BackoffPolicy(initial_sec=60))
    w = triggersmod.TriggerWatcher(
        catalogue=lambda: triggersmod.TriggerCatalogue([trigger], []),
        config=lambda: {}, spawn=lambda *a, **k: None,
        submit=lambda errand: "queued", poll=lambda t: True, log=lambda key, **fmt: None)
    assert w._backoff_state(trigger) is None


def test_the_file_cannot_grant_a_second_executor():
    """`observe` is the code's answer, not a setting: it comes from the built-in entry of
    that name and is never read out of the catalogue file, so no edit can hand an event a
    second executor — nor is it written back when the file is saved."""
    entries = [{"name": "session_kick", "kind": "poll", "check": "x",
                "scenario": "recover_from_kick", "enabled": True, "observe": False}]
    sk = triggersmod.parse_catalogue(entries).by_name("session_kick")
    assert sk.observe is True, "the file overrode who is allowed to act"
    assert "observe" not in sk.as_dict()
    #: …and a name the code has never heard of is an ordinary trigger
    mine = triggersmod.parse_catalogue(
        [{"name": "mine", "kind": "wire", "event_pattern": "p", "scenario": "s"}]
    ).by_name("mine")
    assert mine.observe is False


def test_a_backoff_policy_round_trips_through_the_file():
    entries = [{"name": "k", "kind": "poll", "check": "x", "scenario": "recover",
                "backoff": {"initial_sec": 60, "step_sec": 30, "max_sec": 120,
                            "stability_sec": 90, "refire_window_sec": 90}}]
    k = triggersmod.parse_catalogue(entries).by_name("k")
    assert k.backoff is not None and k.backoff.initial_sec == 60 and k.backoff.max_sec == 120
    d = k.as_dict()
    assert d["backoff"]["step_sec"] == 30
    # …and back in again unchanged.
    k2 = triggersmod.parse_catalogue([d]).by_name("k")
    assert k2.backoff == k.backoff


def test_a_backoff_poll_asks_again_before_firing():
    """THE BLIND SHOT (#1296), and it is not about the kick.

    Any poll trigger carrying a backoff used to act on a reading taken a quarter of an
    hour earlier: `wait(delay)` and then fire, with nothing asked in between. For the kick
    that means a modal which merely FLICKERED — one truthy reading — buys a relaunch of a
    perfectly healthy client fifteen minutes later. The condition is re-asked now, and a
    condition that has gone means no fire.

    And the non-fire is SAID, because a wait that ended in nothing must not look like a
    wait that never happened — the whole failure mode this task has been chasing.
    """
    import threading

    submitted = []
    said = []
    seen = threading.Event()
    answers = [True, False]          # true when armed, gone by the time it would fire

    def poll(_t):
        if answers:
            return answers.pop(0)
        return False

    cat = triggersmod.TriggerCatalogue([
        triggersmod.Trigger(
            name="kick", kind=triggersmod.KIND_POLL, check="x",
            scenario=("recover",), interval_sec=5, cooldown_sec=5,
            backoff=triggersmod.BackoffPolicy(
                initial_sec=0, step_sec=900, max_sec=2700,
                stability_sec=600, refire_window_sec=600)),
    ])

    def log(key, **fmt):
        said.append(key)
        if key == "triggers.log.stale":
            seen.set()

    watcher = triggersmod.TriggerWatcher(
        catalogue=lambda: cat, config=lambda: {"kick": True},
        spawn=lambda t, f: None,
        submit=lambda t: submitted.append(t.name),
        log=log, poll=poll)
    watcher.start()
    try:
        assert seen.wait(3.0), f"the stale wait was never reported: {said}"
        assert submitted == [], "it fired on a condition that had gone"
    finally:
        watcher.stop()


def test_a_condition_that_is_still_true_after_the_wait_does_fire():
    """The other half: the re-read must not make the backoff useless. A fault that is
    still there when the wait ends is acted on, exactly as before."""
    import threading

    fired = threading.Event()
    submitted = []
    cat = triggersmod.TriggerCatalogue([
        triggersmod.Trigger(
            name="kick", kind=triggersmod.KIND_POLL, check="x",
            scenario=("recover",), interval_sec=5, cooldown_sec=5,
            backoff=triggersmod.BackoffPolicy(
                initial_sec=0, step_sec=900, max_sec=2700,
                stability_sec=600, refire_window_sec=600)),
    ])
    watcher = triggersmod.TriggerWatcher(
        catalogue=lambda: cat, config=lambda: {"kick": True},
        spawn=lambda t, f: None,
        submit=lambda t: (submitted.append(t.name), fired.set()),
        log=lambda *a, **k: None,
        poll=lambda t: True)                 # still true when the wait ends
    watcher.start()
    try:
        assert fired.wait(3.0), "a condition that held was not acted on"
        assert submitted[:1] == ["kick"]
    finally:
        watcher.stop()


def test_a_re_read_that_cannot_be_taken_does_not_fire():
    """A daemon that went away answers by raising. «Cannot tell» must read as «do not
    act»: not acting costs a later fire, acting on nothing costs a live client."""
    import threading

    submitted = []
    said = []
    seen = threading.Event()
    calls = []

    def poll(_t):
        calls.append(1)
        if len(calls) == 1:
            return True
        raise RuntimeError("daemon went away")

    def log(key, **fmt):
        said.append(key)
        if key in ("triggers.log.stale", "triggers.log.poll_error"):
            seen.set()

    cat = triggersmod.TriggerCatalogue([
        triggersmod.Trigger(
            name="kick", kind=triggersmod.KIND_POLL, check="x",
            scenario=("recover",), interval_sec=5, cooldown_sec=5,
            backoff=triggersmod.BackoffPolicy(initial_sec=0)),
    ])
    watcher = triggersmod.TriggerWatcher(
        catalogue=lambda: cat, config=lambda: {"kick": True},
        spawn=lambda t, f: None,
        submit=lambda t: submitted.append(t.name),
        log=log, poll=poll)
    watcher.start()
    try:
        assert seen.wait(3.0), f"nothing was said about the failed re-read: {said}"
        assert submitted == [], "it fired although the re-read had failed"
    finally:
        watcher.stop()



def test_a_backoff_poll_waits_then_fires_and_remembers_the_run():
    """The watcher end to end: an enabled backoff poll fires (initial delay 0 here, so
    no real wait) and the run is stamped on the state it keeps by name."""
    import threading
    fired = threading.Event()
    submitted = []
    cat = triggersmod.TriggerCatalogue([
        triggersmod.Trigger(
            name="kick", kind=triggersmod.KIND_POLL, check="x",
            scenario=("recover",), interval_sec=5, cooldown_sec=5,
            backoff=triggersmod.BackoffPolicy(
                initial_sec=0, step_sec=900, max_sec=2700,
                stability_sec=600, refire_window_sec=600)),
    ])
    watcher = triggersmod.TriggerWatcher(
        catalogue=lambda: cat,
        config=lambda: {"kick": True},
        spawn=lambda t, f: None,
        submit=lambda t: (submitted.append(t.name), fired.set()),
        log=lambda *a, **k: None,
        poll=lambda t: True,
    )
    watcher.start()
    try:
        assert fired.wait(2.0), "the backoff poll never fired"
        assert submitted[:1] == ["kick"]
        state = watcher._backoff.get("kick")
        assert state is not None and state.last_run_ts is not None
    finally:
        watcher.stop()


# ---------------------------------------------------------------------------
# the poll's answer, and the trace it leaves — #1296
# ---------------------------------------------------------------------------
class _Say:
    """A debug logger that remembers what it was told."""

    def __init__(self) -> None:
        self.lines = []

    def _put(self, fmt, args):
        self.lines.append(fmt % args if args else fmt)

    def info(self, fmt, *args):
        self._put(fmt, args)

    def debug(self, fmt, *args):
        self._put(fmt, args)


class _Evaluator:
    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []

    def run(self, chunk, marker=None, settle=None, early=None):
        self.asked.append(chunk)
        nxt = self.answers.pop(0) if self.answers else []
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class _Link:
    def __init__(self, evaluator, ready=True):
        self._ev = evaluator
        self._ready = ready

    def ready(self):
        return self._ready

    def evaluator(self):
        return self._ev


class _Gate:
    """`DaemonGate` as the poll sees it: one question, and whether it was asked."""

    def __init__(self, open_: bool = True):
        self.open = open_
        self.asked = 0

    def alive(self) -> bool:
        self.asked += 1
        return self.open


class _Rt:
    def __init__(self, link, gate=None):
        self.game = link
        # Nothing automatic runs while this profile's daemon is down (#1393) — a poll
        # least of all, since its check is a round trip into the game every ten seconds.
        self.gate = gate if gate is not None else _Gate()


class _PollHost:
    """The real `Schedule.poll` / `_poll_note`, bound to the least state they touch.

    The method is used as it ships rather than re-implemented, the way
    `test_panel_recovery` drives the watchdog: a re-implementation would have agreed
    with the bug it is here to catch.
    """

    def __init__(self, answers, ready=True, gate=None):
        from panel.runtime.schedule import Schedule    # noqa: PLC0415 — Tk at import

        self.ev = _Evaluator(answers)
        self.rt = _Rt(_Link(self.ev, ready=ready), gate=gate)
        self._poll_seen = {}
        self._dbg = _Say()
        self._poll = Schedule.poll.__get__(self)
        # …and the note it calls: the real one, bound here too, so the roll-up and the
        # pulse are the shipped behaviour rather than a stand-in that agrees with itself.
        self._poll_note = Schedule._poll_note.__get__(self)

    def poll(self, trigger):
        return self._poll(trigger)


def _poll_trigger(name="probe"):
    return triggersmod.Trigger(name=name, kind=triggersmod.KIND_POLL,
                               check="1 == 1", scenario=("noop",))


def test_a_poll_asks_the_gate_before_it_asks_the_game():
    """A stopped panel polls nothing at all (#1393).

    The check is a chunk sent into the game every `interval_sec`, and against a daemon
    that is not there every one of them is a connect timeout for an answer that was known
    before it was asked. Asked through the gate rather than probed here, so «is anything
    allowed to run» has ONE answer for the whole profile.
    """
    gate = _Gate(open_=False)
    host = _PollHost([["TRIGCHK=true"]], gate=gate)
    assert host.poll(_poll_trigger()) is False, "a poll fired with the daemon down"
    assert gate.asked == 1, "the gate was not asked"
    assert host.ev.asked == [], "the game was asked anyway"


def test_a_poll_reads_the_games_own_yes():
    """The whole point, and the thing that was broken: the game answers `TRIGCHK=true`
    in the marker's own capitals, and the verdict has to be True. It was False for every
    reading there can be — the needle was capitalised against a lowered haystack — so no
    poll trigger had ever fired, `session_kick` included (#1296)."""
    host = _PollHost([["TRIGCHK=true"]])
    assert host.poll(_poll_trigger()) is True


def test_a_poll_reads_a_no_as_a_no():
    host = _PollHost([["TRIGCHK=false"]])
    assert host.poll(_poll_trigger()) is False


def test_every_poll_leaves_a_trace_of_what_it_saw():
    """THE ACTUAL FIX. A poll answering «no», a poll skipped because the game is down and
    a poll that never ran used to write byte-identical logs — nothing — so a dead poll
    could only be caught by forcing its condition true by hand. Each ending now names
    itself, and quotes the game's own line rather than only the verdict: those two
    disagreeing is precisely the fault."""
    host = _PollHost([["TRIGCHK=false"]])
    host.poll(_poll_trigger("kick"))
    said = " | ".join(host._dbg.lines)
    assert "poll kick" in said and "no" in said, said
    assert "TRIGCHK=false" in said, "the game's own answer must be in the trace"


def test_the_two_silent_endings_name_themselves():
    """A game that is not ready and a read that threw both used to `return False` without
    a word — two more ways for a poll to look exactly like a quiet minute."""
    down = _PollHost([], ready=False)
    assert down.poll(_poll_trigger("kick")) is False
    assert any("not ready" in ln for ln in down._dbg.lines), down._dbg.lines

    broke = _PollHost([RuntimeError("daemon went away")])
    assert broke.poll(_poll_trigger("kick")) is False
    assert any("unreadable" in ln and "daemon went away" in ln
               for ln in broke._dbg.lines), broke._dbg.lines


def test_a_repeated_answer_is_rolled_up_and_a_changed_one_is_said_at_once():
    """A check runs every ten seconds; a line each would bury the log it exists to make
    readable. So the same answer is rolled up and a DIFFERENT one is news."""
    host = _PollHost([["TRIGCHK=false"]] * 4 + [["TRIGCHK=true"]])
    trigger = _poll_trigger("kick")
    for _ in range(4):
        host.poll(trigger)
    assert len(host._dbg.lines) == 1, host._dbg.lines      # first look only
    assert host.poll(trigger) is True
    assert len(host._dbg.lines) == 2, host._dbg.lines
    assert "was no" in host._dbg.lines[-1], host._dbg.lines[-1]


def test_the_pulse_says_a_quiet_poll_is_still_alive():
    """The line whose ABSENCE now means something: while the answer does not change, the
    poll still says «still looking, N more looks» every few minutes. Without it «alive
    and seeing no» and «dead» are the same log again."""
    import panel.runtime.schedule as schedmod                # noqa: PLC0415

    host = _PollHost([["TRIGCHK=false"]] * 3)
    trigger = _poll_trigger("kick")
    host.poll(trigger)
    host.poll(trigger)
    assert len(host._dbg.lines) == 1
    # …the pulse is due: age the last note past the interval
    verdict, _said_at, since = host._poll_seen["kick"]
    host._poll_seen["kick"] = (verdict, -schedmod.POLL_PULSE_SEC, since)
    host.poll(trigger)
    assert len(host._dbg.lines) == 2, host._dbg.lines
    assert "still no" in host._dbg.lines[-1], host._dbg.lines[-1]



def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
