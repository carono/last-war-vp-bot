"""The «Secret Tasks» tab (tasks #1135 / #1154): the `secret_task_share` wire trigger,
the panel's refresh dispatch, the tab's pure helpers (countdown, room ids, uuid tail),
and the ready-row lifecycle — the countdown to raidability, the poll that drops gone
tiles, and the auto-loot rule. All tested without Tk or a game."""
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


class _Var:
    """A stand-in for a tk StringVar/BooleanVar — just `.get()` / `.set()`."""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _FakeApp:
    """The slice of the panel the tab's timer / poll logic touches — no Tk root."""

    def __init__(self, lo="", hi="", autoloot=False):
        self._i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
        self._lvl_from_var = _Var(lo)
        self._lvl_to_var = _Var(hi)
        self._autoloot_var = _Var(autoloot)

    def _t(self, key, **kw):
        return self._i18n.t(key, **kw)

    def _autoloot_levels(self):
        def bound(var):
            raw = var.get().strip()
            return int(raw) if raw.isdigit() else None
        return bound(self._lvl_from_var), bound(self._lvl_to_var)


def _make_tab(app, rows):
    """A tab with its build skipped, wired just enough to run the timer / poll paths."""
    tab = object.__new__(st.SecretTasksTab)
    tab.app = app
    tab._rows = rows
    tab._collected = set()
    tab._auto_attempted = set()
    tab._polling = False
    tab._rendered = 0
    tab._render = lambda: setattr(tab, "_rendered", tab._rendered + 1)
    tab._update_status = lambda: None
    return tab


def _row(uuid, level, done_off, exp_off):
    now = int(__import__("time").time() * 1000)
    return {"uuid": uuid, "server": 1, "x": 1, "y": 2, "level": level,
            "cfg_id": 16003, "loot_count": 0,
            "completed_at": now + done_off, "expires_at": now + exp_off,
            "timer": _Var(), "frame": None, "ready": False}


def test_countdown_targets_completion_and_flips_ready():
    """The timer counts to completion, flips a matured row to ready, and expiry drops."""
    rows = {
        "1": _row(1, 7, 120_000, 600_000),    # ready in 2 min
        "2": _row(2, 7, -5_000, 600_000),     # already raidable
        "3": _row(3, 7, -100_000, -1_000),    # expired
    }
    tab = _make_tab(_FakeApp(), rows)
    expired, changed = tab._refresh_timers()
    assert expired == ["3"]                    # the past-expiry tile is removed
    assert changed is True                     # row 2 crossed into ready this pass
    assert rows["1"]["ready"] is False and "готово через" in rows["1"]["timer"].get()
    assert rows["2"]["ready"] is True and "готово к сбору" in rows["2"]["timer"].get()


def test_poll_drops_the_gone_and_keeps_the_present():
    """A ready tile missing from a good read is off the map; a failed read removes none."""
    rows = {"2": _row(2, 7, -5_000, 600_000)}
    rows["2"]["ready"] = True
    tab = _make_tab(_FakeApp(), rows)

    tab._poll_apply(["2"], {})                 # good read, tile absent -> gone
    assert "2" not in tab._rows

    rows = {"2": _row(2, 7, -5_000, 600_000)}
    rows["2"]["ready"] = True
    tab = _make_tab(_FakeApp(), rows)
    tab._poll_apply(["2"], None)               # failed read proves nothing
    assert "2" in tab._rows


class _LiveTask:
    def __init__(self, uuid, can_loot=True):
        self.uuid = uuid
        self.expires_at = int(__import__("time").time() * 1000) + 600_000
        self.completed_at = int(__import__("time").time() * 1000) - 5_000
        self.loot_count = 0
        self.can_loot = can_loot


def test_auto_loot_robs_only_the_top_level_in_range():
    """«от 1 до 7» robs 7-star tiles and leaves a raidable 6 alone (the #1099 rule)."""
    rows = {"6": _row(6, 6, -5_000, 600_000), "7": _row(7, 7, -5_000, 600_000)}
    for r in rows.values():
        r["ready"] = True
    app = _FakeApp(lo="1", hi="7", autoloot=True)
    tab = _make_tab(app, rows)
    robbed = []
    tab._collect = lambda row: robbed.append(int(row["level"]))
    tab._poll_apply(list(rows), {"6": _LiveTask(6), "7": _LiveTask(7)})
    assert robbed == [7]                        # only the top of the range
    assert tab._auto_attempted == {"7"}         # and only attempted once


def test_auto_loot_skips_out_of_range_and_when_unticked():
    """Nothing is robbed when the tiles fall outside the range, or the box is off."""
    rows = {"6": _row(6, 6, -5_000, 600_000), "7": _row(7, 7, -5_000, 600_000)}
    for r in rows.values():
        r["ready"] = True
    live = {"6": _LiveTask(6), "7": _LiveTask(7)}

    off = _make_tab(_FakeApp(lo="1", hi="7", autoloot=False), rows)
    off._collect = lambda row: (_ for _ in ()).throw(AssertionError("robbed with box off"))
    off._poll_apply(list(rows), live)           # box off -> no steal

    out = _make_tab(_FakeApp(lo="1", hi="5", autoloot=True),
                    {k: dict(v, ready=True) for k, v in rows.items()})
    robbed = []
    out._collect = lambda row: robbed.append(int(row["level"]))
    out._poll_apply(list(rows), live)           # both above the range
    assert robbed == []


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
