"""The «Secret Tasks» tab (tasks #1135 / #1154): the `secret_task_share` wire trigger,
the panel's refresh dispatch, the tab's pure helpers (countdown, room ids, uuid tail),
and the ready-row lifecycle — the countdown to raidability, the poll that drops gone
tiles, and the auto-loot rule. All tested without Tk or a game."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import panel.triggers as trg                        # noqa: E402
import panel.__main__ as pm                         # noqa: E402
from panel.tabs.secret_tasks import tab as st       # noqa: E402


def test_trigger_is_registered_on_the_share_push():
    t = trg.default_catalogue().by_name("secret_task_share")
    assert t is not None, "secret_task_share trigger missing"
    assert t.kind == trg.KIND_WIRE
    assert t.event_pattern == "alliance.share.mission.add"
    assert t.enabled is False               # opt-in, like the other listeners


def test_the_tab_declares_the_share_trigger():
    specs = {t.name: t for t in st.SecretTasksTab.TRIGGERS}
    assert "secret_task_share" in specs, specs
    spec = specs["secret_task_share"]
    assert spec.event == "alliance.share.mission.add"
    assert spec.handler == "refresh_live"


def test_refresh_only_when_the_tab_was_opened():
    tab = object.__new__(st.SecretTasksTab)
    tab.loaded = False
    calls = []
    tab.refresh = lambda: calls.append(1)
    tab.refresh_live()                              # unopened -> no read
    assert calls == []
    tab.loaded = True
    tab.refresh_live()                              # opened -> re-merge
    assert calls == [1]


def test_the_schedule_calls_the_tab_and_skips_the_daemon_gate():
    """The sentinel is gone: the tab CONTRIBUTES the handler and the schedule binds it.

    It is called before the daemon gate on purpose — the tab's own read degrades
    gracefully, so a missing daemon must not fault the trigger.
    """
    import types
    from panel.runtime.schedule import Schedule

    called = []
    _Cls = st.SecretTasksTab
    spec = {t.name: t for t in _Cls.TRIGGERS}['secret_task_share']
    tab = types.SimpleNamespace(TRIGGERS=(spec,),
                                refresh_live=lambda: called.append(1))
    sched = Schedule.__new__(Schedule)
    sched.rt = types.SimpleNamespace(
        game=types.SimpleNamespace(
            claim=lambda _o: True, release=lambda: None, on_settled=lambda: None,
            up=lambda: (_ for _ in ()).throw(
                AssertionError("must not reach the daemon gate"))),
        root=types.SimpleNamespace(after=lambda _ms, fn: fn()))
    sched._handlers, sched._needs_game = {}, set()
    sched._gates, sched._args = {}, {}
    sched.register(tab)
    assert sched.handles('secret_task_share'), "the tab's trigger was not adopted"
    assert sched.run_errand(types.SimpleNamespace(name='secret_task_share')) is True
    assert called == [1], "the tab's handler was not called"


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


class _FakeAutoLoot:
    """The one thing the timer / poll paths ask the standing order: its range."""

    def __init__(self, tab):
        self.tab = tab

    def levels(self):
        def bound(var):
            raw = var.get().strip()
            return int(raw) if raw.isdigit() else None
        return bound(self.tab.level_from_var), bound(self.tab.level_to_var)


def _make_tab(rows, lo="", hi="", autoloot=False):
    """A tab with its build skipped, wired just enough to run the timer / poll paths.

    No Tk root: the countdown, the poll reconciliation and the #1099 rob rule are all
    plain decisions over the row dicts, and that is the point of testing them here.
    """
    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    tab = object.__new__(st.SecretTasksTab)
    tab.t = i18n.t
    tab.level_from_var, tab.level_to_var = _Var(lo), _Var(hi)
    tab.autoloot_var = _Var(autoloot)
    tab.autoloot = _FakeAutoLoot(tab)
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
    tab = _make_tab(rows)
    expired, changed = tab._refresh_timers()
    assert expired == ["3"]                    # the past-expiry tile is removed
    assert changed is True                     # row 2 crossed into ready this pass
    assert rows["1"]["ready"] is False and "готово через" in rows["1"]["timer"].get()
    assert rows["2"]["ready"] is True and "готово к сбору" in rows["2"]["timer"].get()


def test_poll_drops_the_gone_and_keeps_the_present():
    """A ready tile missing from a good read is off the map; a failed read removes none."""
    rows = {"2": _row(2, 7, -5_000, 600_000)}
    rows["2"]["ready"] = True
    tab = _make_tab(rows)

    tab._poll_apply(["2"], {})                 # good read, tile absent -> gone
    assert "2" not in tab._rows

    rows = {"2": _row(2, 7, -5_000, 600_000)}
    rows["2"]["ready"] = True
    tab = _make_tab(rows)
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
    tab = _make_tab(rows, lo="1", hi="7", autoloot=True)
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

    off = _make_tab(rows, lo="1", hi="7", autoloot=False)
    off._collect = lambda row: (_ for _ in ()).throw(AssertionError("robbed with box off"))
    off._poll_apply(list(rows), live)           # box off -> no steal

    out = _make_tab({k: dict(v, ready=True) for k, v in rows.items()},
                    lo="1", hi="5", autoloot=True)
    robbed = []
    out._collect = lambda row: robbed.append(int(row["level"]))
    out._poll_apply(list(rows), live)           # both above the range
    assert robbed == []


def test_the_table_has_one_cell_per_column_and_a_link_column():
    """The list is a grid now (#1209): a row is exactly as wide as the headings."""
    tab = _make_tab({})
    row = _row(1697234600000972, 7, 120_000, 600_000)
    row["timer"].set("готово через 02:00")
    row["server"], row["x"], row["y"], row["loot_count"] = 534, 568, 371, 1
    values = st.SecretTasksTab._row_values(tab, row)
    assert len(values) == len(st.COLUMNS), (values, st.COLUMNS)
    assert "⭐×7" in values[0] and st.TYPE_GLYPH in values[0]
    assert values[1] == "#534 X:568 Y:371", values          # the clickable cell
    assert values[2] == "готово через 02:00", values
    assert values[3] == "1/3", values
    assert values[4] == "…00000972", values

    # A ready tile swaps the glyph — the colour is the tag, the glyph is the text.
    row["ready"] = True
    assert st.READY_GLYPH in st.SecretTasksTab._row_values(tab, row)[0]

    # …and the column a click walks to the tile is a column that exists.
    assert st.LINK_COLUMN in [c[0] for c in st.COLUMNS]


def test_the_table_sorts_by_the_heading_and_falls_back_to_the_best_raid():
    """No heading clicked: the best raid on top. Clicked: by that column, both ways."""
    tab = _make_tab({})
    tab._sort = None
    rows = [
        dict(_row(1, 6, -5_000, 900_000), server=1, x=1, y=1, loot_count=2, ready=True),
        dict(_row(2, 7, -5_000, 600_000), server=1, x=2, y=2, loot_count=0, ready=True),
        dict(_row(3, 7, 120_000, 300_000), server=1, x=3, y=3, loot_count=1),
    ]
    order = st.SecretTasksTab._sorted_rows(tab, rows)
    # highest star first, and within a level the tile that expires soonest
    assert [r["uuid"] for r in order] == [3, 2, 1], [r["uuid"] for r in order]

    tab._sort = ("slots", False)
    assert [r["uuid"] for r in st.SecretTasksTab._sorted_rows(tab, rows)] == [2, 3, 1]
    tab._sort = ("slots", True)
    assert [r["uuid"] for r in st.SecretTasksTab._sorted_rows(tab, rows)] == [1, 3, 2]
    # «Состояние» sorts by attention needed: the ready rows first, soonest to expire.
    tab._sort = ("state", False)
    assert [r["uuid"] for r in st.SecretTasksTab._sorted_rows(tab, rows)] == [2, 1, 3]
    # Every column the table draws knows how to sort itself.
    assert set(st.SecretTasksTab.SORT_KEYS) == {c[0] for c in st.COLUMNS}


class _FakeTree:
    """Enough of a Treeview to aim a click at a cell: a region, a column, a row."""

    def __init__(self, region="cell", column="#2", row="11"):
        self._region, self._column, self._row = region, column, row
        self.cursor = None

    def identify(self, _what, _x, _y):
        return self._region

    def identify_column(self, _x):
        return self._column

    def identify_row(self, _y):
        return self._row

    def configure(self, cursor=None):
        self.cursor = cursor


def test_only_the_coordinate_cell_is_a_link():
    """A click walks the camera from the coordinate column and from nowhere else."""
    tab = object.__new__(st.SecretTasksTab)
    tab._rows = {"11": _row(11, 7, -5_000, 600_000)}
    walked = []
    tab._jump_to_row = lambda row: walked.append(row["uuid"])

    link_at = "#%d" % (1 + [c[0] for c in st.COLUMNS].index(st.LINK_COLUMN))
    tab._tree = _FakeTree(column=link_at)
    event = __import__("types").SimpleNamespace(x=10, y=10)
    assert st.SecretTasksTab._column_at(tab, event) == st.LINK_COLUMN
    st.SecretTasksTab._on_click(tab, event)
    assert walked == [11], walked

    # …the level column is not a link, and neither is the empty space under the rows.
    tab._tree = _FakeTree(column="#1")
    st.SecretTasksTab._on_click(tab, event)
    assert walked == [11], "a click outside the coordinate column jumped"
    tab._tree = _FakeTree(region="nothing", column=link_at)
    assert st.SecretTasksTab._column_at(tab, event) == ""
    st.SecretTasksTab._on_click(tab, event)
    assert walked == [11], "a click below the last row jumped"

    # The pointer says so before the click: a hand over the link, nothing elsewhere.
    tab._tree = _FakeTree(column=link_at)
    st.SecretTasksTab._on_motion(tab, event)
    assert tab._tree.cursor == "hand2", tab._tree.cursor
    tab._tree = _FakeTree(column="#1")
    st.SecretTasksTab._on_motion(tab, event)
    assert tab._tree.cursor == "", tab._tree.cursor


def test_the_own_server_is_read_once_and_an_unreadable_one_is_zero():
    """What «не грабить на своём сервере» judges a tile against.

    Zero rather than an exception on a dead game: the standing order reads that as
    «do not rob», and a raise on the watcher thread would take the loop down.
    """
    tab = object.__new__(st.SecretTasksTab)
    tab._own_server = 0
    tab._ids = None
    reads = []
    tab.rt = __import__("types").SimpleNamespace(
        game=__import__("types").SimpleNamespace(client=object()))
    tab._self_ids = lambda ev: (reads.append(1), ("534", "a1"))[1]
    assert tab.own_server() == 534
    assert tab.own_server() == 534
    assert reads == [1], "the own server was re-read: %r" % (reads,)

    blind = object.__new__(st.SecretTasksTab)
    blind._own_server = 0
    blind.rt = __import__("types").SimpleNamespace(
        game=__import__("types").SimpleNamespace(client=object()))
    blind._self_ids = lambda ev: ("", "")
    assert blind.own_server() == 0

    def _boom(_ev):
        raise RuntimeError("no daemon")

    blind._self_ids = _boom
    assert blind.own_server() == 0


def test_the_jump_history_remembers_the_newest_first_and_is_capped():
    """«Куда ходил» on the tab's coordinate block: newest first, no duplicates, capped."""
    tab = object.__new__(st.SecretTasksTab)
    tab._jump_hist = []
    tab._jump_hist_combo = None
    saved = []
    tab.rt = __import__("types").SimpleNamespace(
        settings=__import__("types").SimpleNamespace(changed=lambda: saved.append(1)))
    tab._remember_jump(568, 371, 534)
    tab._remember_jump(100, 200, None)
    tab._remember_jump(568, 371, 534)          # the same tile again -> moves to the top
    assert tab._jump_hist == ["#534 X:568 Y:371", "X:100 Y:200"], tab._jump_hist
    assert saved, "a walked-to tile was not persisted"

    for i in range(st.JUMP_HISTORY_MAX + 5):
        tab._remember_jump(i, i, 1)
    assert len(tab._jump_hist) == st.JUMP_HISTORY_MAX, len(tab._jump_hist)


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
