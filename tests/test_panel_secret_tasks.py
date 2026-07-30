"""The «Secret Tasks» tab (task #1135): the `secret_task_share` wire trigger, the
panel's refresh dispatch, and the tab's pure helpers (countdown, room ids, uuid tail).
All tested without Tk or a game."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import panel.triggers as trg              # noqa: E402
import panel.__main__ as pm               # noqa: E402
import panel.secret_tasks as st           # noqa: E402


def test_trigger_is_registered_on_the_share_push():
    t = trg.default_catalogue().by_name("secret_task_share")
    assert t is not None, "secret_task_share trigger missing"
    assert t.kind == trg.KIND_WIRE
    assert t.event_pattern == "alliance.share.mission.add"
    assert t.enabled is False               # opt-in, like the other listeners


def test_refresh_only_when_the_tab_was_opened():
    class FakeTab:
        def __init__(self):
            self._loaded = False
            self.calls = 0

        def refresh(self):
            self.calls += 1

    class Stub:
        _refresh_secret_tasks_tab = pm.Panel._refresh_secret_tasks_tab

    s = Stub()
    s._secret_tasks_tab = FakeTab()
    s._refresh_secret_tasks_tab()                  # unopened -> no read
    assert s._secret_tasks_tab.calls == 0
    s._secret_tasks_tab._loaded = True
    s._refresh_secret_tasks_tab()                  # opened -> repaint
    assert s._secret_tasks_tab.calls == 1
    del s._secret_tasks_tab                        # missing tab -> no crash
    s._refresh_secret_tasks_tab()


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

        def _refresh_secret_tasks_tab(self):
            pass

        def after(self, ms, fn=None):
            scheduled.append(fn)

        def _daemon_up(self):
            raise AssertionError("the secret-task refresh must not reach the daemon gate")

    class Timer:
        name = "secret_task_share"
        scenario = ("__secret_task_share__",)

    s = Stub()
    assert s._run_timer_action(Timer()) is True
    assert s._refresh_secret_tasks_tab in scheduled, "refresh was not scheduled on the Tk thread"


def test_fmt_left_clock():
    assert st._fmt_left(90_000) == "01:30"          # under an hour -> MM:SS
    assert st._fmt_left(3_661_000) == "1:01:01"     # over an hour -> H:MM:SS
    assert st._fmt_left(0) == "00:00"
    assert st._fmt_left(-5_000) == "00:00"          # already gone floors at zero


def test_short_uuid_keeps_the_distinguishing_tail():
    assert st.SecretTasksTab._short_uuid(1697234600000972) == "…00000972"
    assert st.SecretTasksTab._short_uuid(123) == "123"


def test_room_ids_from_cached_self_ids():
    tab = object.__new__(st.SecretTasksTab)         # no Tk build
    tab._ids = ("935", "3d4b9dee")
    assert tab._room_id(None, st.SHARE_WORLD) == "country_935"
    assert tab._room_id(None, st.SHARE_ALLIANCE) == "alliance_935_3d4b9dee"
    tab._ids = ("", "")                             # nothing read -> no room, no send
    assert tab._room_id(None, st.SHARE_WORLD) == ""
    assert tab._room_id(None, st.SHARE_ALLIANCE) == ""


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
