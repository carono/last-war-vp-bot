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
