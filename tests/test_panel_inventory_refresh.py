"""The «inventory_refresh» trigger: a push.resource.item.update wire trigger that
repaints the Inventory tab (task #1133). The trigger registration and the panel's
dispatch/refresh logic are tested without Tk or a game."""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import panel.triggers as trg          # noqa: E402
import panel.__main__ as pm           # noqa: E402


def test_trigger_is_registered_on_the_resource_push():
    t = trg.default_catalogue().by_name("inventory_refresh")
    assert t is not None, "inventory_refresh trigger missing"
    assert t.kind == trg.KIND_WIRE
    assert t.event_pattern == "push.resource.item.update"


def test_the_tab_declares_the_trigger_and_only_repaints_when_it_was_opened():
    """The bag repaint is the tab's own standing order now — and it is only offered
    while the tab is here to be repainted."""
    from panel.tabs.inventory import InventoryTab

    specs = {t.name: t for t in InventoryTab.TRIGGERS}
    assert "inventory_refresh" in specs, specs
    spec = specs["inventory_refresh"]
    assert spec.event == "push.resource.item.update"
    assert spec.handler == "refresh_live"
    assert not spec.needs_game, "a bag repaint must not wait for a daemon"

    from panel.tabs._data import DataTab

    class FakeTab(DataTab):
        def __init__(self):
            self._loaded = False
            self.calls = 0

        def refresh(self):
            self.calls += 1

    tab = FakeTab()
    tab.refresh_live()                              # unopened -> no read
    assert tab.calls == 0
    tab._loaded = True
    tab.refresh_live()                              # opened -> repaint
    assert tab.calls == 1


def test_the_schedule_calls_the_tab_and_skips_the_daemon_gate():
    """The sentinel is gone: the tab CONTRIBUTES the handler and the schedule binds it.

    It is called before the daemon gate on purpose — the tab's own read degrades
    gracefully, so a missing daemon must not fault the trigger.
    """
    import types
    from panel.runtime.schedule import Schedule

    called = []
    from panel.tabs.inventory import InventoryTab as _Cls
    spec = {t.name: t for t in _Cls.TRIGGERS}['inventory_refresh']
    tab = types.SimpleNamespace(TRIGGERS=(spec,),
                                refresh_live=lambda: called.append(1))
    sched = Schedule.__new__(Schedule)
    sched.rt = types.SimpleNamespace(
        game=types.SimpleNamespace(
            claim=lambda _o: True, release=lambda: None, on_settled=lambda: None,
            up=lambda: (_ for _ in ()).throw(
                AssertionError("must not reach the daemon gate"))),
        # `post` is how the runtime hands work to the Tk thread now (#1226);
        # here it simply runs it, which is what this double always meant.
        post=lambda fn: fn(),
        root=types.SimpleNamespace(after=lambda _ms, fn: fn()))
    sched._handlers, sched._needs_game = {}, set()
    sched._gates, sched._args = {}, {}
    sched.register(tab)
    assert sched.handles('inventory_refresh'), "the tab's trigger was not adopted"
    assert sched.run_errand(types.SimpleNamespace(name='inventory_refresh')) is True
    assert called == [1], "the tab's handler was not called"


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
