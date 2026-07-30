"""The «inventory_refresh» trigger: a push.resource.item.update wire trigger that
repaints the Inventory tab (task #1133). The trigger registration and the panel's
dispatch/refresh logic are tested without Tk or a game."""
from __future__ import annotations

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


def test_refresh_only_when_the_tab_was_opened():
    class FakeTab:
        def __init__(self):
            self._loaded = False
            self.calls = 0
        def refresh(self):
            self.calls += 1

    class Stub:
        _refresh_inventory_tab = pm.Panel._refresh_inventory_tab

    s = Stub()
    s._inventory_tab = FakeTab()
    s._refresh_inventory_tab()                      # unopened -> no read
    assert s._inventory_tab.calls == 0
    s._inventory_tab._loaded = True
    s._refresh_inventory_tab()                      # opened -> repaint
    assert s._inventory_tab.calls == 1
    del s._inventory_tab
    s._refresh_inventory_tab()                      # no tab -> no crash


def test_dispatch_schedules_refresh_and_skips_the_daemon_gate():
    scheduled = []

    class Stub:
        _run_timer_action = pm.Panel._run_timer_action
        def _claim_busy(self):
            return True
        def _release_busy(self):
            pass
        def _refresh_status(self):
            pass
        def _refresh_inventory_tab(self):
            pass
        def after(self, ms, fn=None):
            scheduled.append(fn)
        def _daemon_up(self):
            raise AssertionError("the inventory refresh must not reach the daemon gate")

    class Timer:
        name = "inventory_refresh"
        scenario = ("__inventory_refresh__",)

    s = Stub()
    assert s._run_timer_action(Timer()) is True
    assert s._refresh_inventory_tab in scheduled, "refresh was not scheduled on the Tk thread"


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
