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

import sys
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

    Needs the panel (customtkinter); says SKIP where that is not importable.
    """
    try:
        from panel.__main__ import Panel
    except Exception:                           # noqa: BLE001
        print("  SKIP panel deps (customtkinter) not importable")
        return
    import types
    stub = types.SimpleNamespace(_autorally_squads=lambda: [2, 3],
                                 _say=lambda *a, **k: None)
    # a plain errand passes its own args through unchanged…
    plain = triggersmod.Trigger(name="x", scenario=("y",), args={"a": 1})
    assert Panel._errand_args(stub, plain) == {"a": 1}
    # …the rally auto-join one gets the live squads merged in.
    raj = triggersmod.default_catalogue().by_name("rally_auto_join")
    assert Panel._errand_args(stub, raj)["squads"] == [2, 3]


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
