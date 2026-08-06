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

# The persistence tests build rows the same way `_merge`/`_load_persisted` do, and
# those call `tk_stringvar` for every row they touch — a real `tk.StringVar` needs a
# live root, which is exactly what `_make_tab`'s docstring says this file goes out of
# its way not to need. A plain `.get()`/`.set()` stand-in is all any of them read.
st.tk_stringvar = lambda master: _Var()


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
    tab.refresh = lambda: calls.append("wire")
    tab._snapshot = lambda: calls.append("vm")
    tab.refresh_live()                              # unopened -> no read
    assert calls == []
    tab.loaded = True
    tab.refresh_live()                              # opened -> both lists
    # The push that fires this is the event that changes the game's own alliance table,
    # so the share re-reads it as well as re-merging the checkpoint (#1244).
    assert calls == ["wire", "vm"]


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
        # `post` is how the runtime hands work to the Tk thread now (#1226);
        # here it simply runs it, which is what this double always meant.
        post=lambda fn: fn(),
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


def test_the_uuid_is_carried_but_not_shown():
    """The table names a tile by coordinate and server; the uuid is what is SENT.

    It had a column of its own for one commit and went with the redraw (#1209) — an
    18-digit id nobody can read out loud was taking the width the countdown needed.
    """
    assert not hasattr(st.SecretTasksTab, "_short_uuid"), "the uuid column is back"
    assert "uuid" not in {c[0] for c in st.COLUMNS}, st.COLUMNS
    assert "uuid" in _row(1, 7, 0, 0), "the row stopped carrying the uuid"


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
    # «Показывать исчерпанные» — off, as a fresh profile has it.
    tab.show_spent_var = _Var(False)
    tab.autoloot = _FakeAutoLoot(tab)
    tab._rows = rows
    tab._collected = set()
    tab._auto_attempted = set()
    tab._polling = False
    tab._rendered = 0
    tab._render = lambda: setattr(tab, "_rendered", tab._rendered + 1)
    tab._update_status = lambda: None
    # `_persist_rows` runs after every structural change now (#1242) — a throwaway file
    # so the timer / poll paths this fixture is FOR do not have to know that, and a test
    # that cares about persistence itself overrides this with its own `_FakeProfiles`.
    tab.rt = _fake_rt(_state_path())
    return tab


def _row(uuid, level, done_off, exp_off):
    now = int(__import__("time").time() * 1000)
    return {"uuid": uuid, "server": 1, "x": 1, "y": 2, "level": level,
            "cfg_id": 16003, "loot_count": 0,
            "completed_at": now + done_off, "expires_at": now + exp_off,
            "timer": _Var(), "frame": None, "ready": False, "soon": False}


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


def test_the_table_has_one_cell_per_column_and_the_two_live_ones():
    """The list is a grid now (#1209): a row is exactly as wide as the headings."""
    tab = _make_tab({})
    row = _row(1000000000014972, 7, 120_000, 600_000)
    row["timer"].set("готово через 02:00")
    row["server"], row["x"], row["y"], row["loot_count"] = 534, 568, 371, 1
    cells = dict(zip([c[0] for c in st.COLUMNS],
                     st.SecretTasksTab._row_values(tab, row)))
    assert len(cells) == len(st.COLUMNS), cells
    assert cells["coords"] == "X:568 Y:371", cells      # the clickable cell, no server
    assert cells["server"] == "#534", cells             # …which has a column of its own
    assert "⭐×7" in cells["lvl"] and st.TYPE_GLYPH in cells["lvl"], cells
    assert cells["state"] == "готово через 02:00", cells
    assert cells["slots"] == "1/3", cells
    # A tile still counting down offers no action: collecting it early is a robbery the
    # server would refuse.
    assert cells["action"] == "", cells

    # A ready tile swaps the glyph and grows its button.
    row["ready"] = True
    ready = dict(zip([c[0] for c in st.COLUMNS],
                     st.SecretTasksTab._row_values(tab, row)))
    assert st.READY_GLYPH in ready["lvl"], ready
    assert ready["action"] == tab.t("secrettasks.collect"), ready

    # …and both columns a click acts in are columns that exist.
    assert {st.LINK_COLUMN, st.ACTION_COLUMN} <= {c[0] for c in st.COLUMNS}


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
    # Every column but the action one sorts; the action column is a button, not an order.
    assert set(st.SecretTasksTab.SORT_KEYS) == {c[0] for c in st.COLUMNS} - {st.ACTION_COLUMN}


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


def _column_at(name: str) -> str:
    """The Treeview's «#N» for a column id, as `identify_column` would answer."""
    return "#%d" % (1 + [c[0] for c in st.COLUMNS].index(name))


def test_the_coordinate_cell_jumps_and_the_action_cell_collects():
    """The two live cells of the table, and the many that only select the row."""
    tab = object.__new__(st.SecretTasksTab)
    tab._rows = {"11": _row(11, 7, -5_000, 600_000)}
    walked, robbed = [], []
    tab._jump_to_row = lambda row: walked.append(row["uuid"])
    tab._collect = lambda row: robbed.append(row["uuid"])
    event = __import__("types").SimpleNamespace(x=10, y=10)

    tab._tree = _FakeTree(column=_column_at(st.LINK_COLUMN))
    assert st.SecretTasksTab._column_at(tab, event) == st.LINK_COLUMN
    st.SecretTasksTab._on_click(tab, event)
    assert walked == [11] and robbed == [], (walked, robbed)

    # The action cell is the row's «Собрать» — but only once the tile is raidable.
    tab._tree = _FakeTree(column=_column_at(st.ACTION_COLUMN))
    st.SecretTasksTab._on_click(tab, event)
    assert robbed == [], "collected a tile that was still counting down"
    tab._rows["11"]["ready"] = True
    st.SecretTasksTab._on_click(tab, event)
    assert robbed == [11], robbed

    # …a plain column is not a link, and neither is the empty space under the rows.
    tab._tree = _FakeTree(column=_column_at("lvl"))
    st.SecretTasksTab._on_click(tab, event)
    assert walked == [11], "a click outside the coordinate column jumped"
    tab._tree = _FakeTree(region="nothing", column=_column_at(st.LINK_COLUMN))
    assert st.SecretTasksTab._column_at(tab, event) == ""
    st.SecretTasksTab._on_click(tab, event)
    assert walked == [11], "a click below the last row jumped"

    # The pointer says so before the click: a hand over a cell that acts, nothing over
    # one that does not — including the action cell of a row with no action on it.
    for column, ready, want in ((st.LINK_COLUMN, True, "hand2"),
                                (st.ACTION_COLUMN, True, "hand2"),
                                (st.ACTION_COLUMN, False, ""),
                                ("lvl", True, "")):
        tab._rows["11"]["ready"] = ready
        tab._tree = _FakeTree(column=_column_at(column))
        st.SecretTasksTab._on_motion(tab, event)
        assert tab._tree.cursor == want, (column, ready, tab._tree.cursor)


class _FakeBox:
    """A ttk.Checkbutton reduced to what greying it out touches."""

    def __init__(self):
        self.states = []

    def state(self, spec):
        self.states.append(tuple(spec))


def test_the_prohibition_is_lit_only_while_auto_loot_can_rob():
    """«Не грабить на своём сервере» greys out with «Автолут ★», and keeps its value.

    With nothing robbing by itself the prohibition has nothing to forbid, and a live
    box that changes nothing is how a person concludes the panel ignored them.
    """
    tab = object.__new__(st.SecretTasksTab)
    tab.autoloot_var = _Var(False)
    tab.skip_own_var = _Var(True)
    tab._skip_own_box = _FakeBox()

    st.SecretTasksTab._sync_autoloot_controls(tab)
    assert tab._skip_own_box.states[-1] == ("disabled",), tab._skip_own_box.states
    tab.autoloot_var.set(True)
    st.SecretTasksTab._sync_autoloot_controls(tab)
    assert tab._skip_own_box.states[-1] == ("!disabled",), tab._skip_own_box.states
    # Greying it never changes what it says — ticking auto-loot back on brings the
    # prohibition back exactly as it was left.
    assert tab.skip_own_var.get() is True

    # Toggling auto-loot itself does both things: the standing order, then the box.
    toggled = []
    tab.autoloot = __import__("types").SimpleNamespace(
        toggle=lambda: toggled.append(1))
    tab.autoloot_var.set(False)
    st.SecretTasksTab._on_autoloot_toggle(tab)
    assert toggled == [1], toggled
    assert tab._skip_own_box.states[-1] == ("disabled",), tab._skip_own_box.states

    # A tab whose widgets are not built yet must survive the same call — «Стоп всё» and
    # `apply_config` both reach it before there is a checkbox to grey.
    bare = object.__new__(st.SecretTasksTab)
    bare.autoloot_var = _Var(False)
    st.SecretTasksTab._sync_autoloot_controls(bare)


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


def test_a_looted_out_tile_is_off_the_list_unless_it_is_asked_for():
    """3/3 is spent — it cannot pay anybody, so it is not on the list (#1227).

    Hidden by a display rule rather than thrown away, because «Показывать исчерпанные»
    has to be able to bring it back: a row that vanishes is otherwise impossible to
    account for. And however it is reached, it is never collectable — pressing it would
    spend one of the day's five on a robbery the server refuses.
    """
    spent = dict(_row(5, 7, -5_000, 600_000), loot_count=3, ready=True)
    free = dict(_row(6, 7, -5_000, 600_000), loot_count=2, ready=True)
    tab = _make_tab({"5": spent, "6": free})

    assert [r["uuid"] for r in tab._visible_rows()] == [6]
    tab.show_spent_var = _Var(True)
    assert sorted(r["uuid"] for r in tab._visible_rows()) == [5, 6]

    # Shown, but not offered: no action cell, no strip button, no menu entry, and the
    # auto-loot rule does not aim at it either.
    assert tab._collectable(spent) is False
    assert tab._collectable(free) is True
    cells = dict(zip([c[0] for c in st.COLUMNS],
                     st.SecretTasksTab._row_values(tab, spent)))
    assert cells["action"] == "", cells
    assert cells["slots"] == "3/3", cells

    # The standing order weighs the same rows and passes over the spent one. Aimed at
    # `_auto_loot` rather than the poll around it: the poll refreshes a row's loot count
    # from the game first, and the game never reports a 3/3 tile at all — it drops them
    # — so the poll could only reach this case by inventing a reading the VM cannot give.
    robbed = []
    tab.autoloot_var = _Var(True)
    tab._collect = lambda row: robbed.append(row["uuid"])
    tab._auto_loot({"5": _LiveTask(5), "6": _LiveTask(6)})
    assert robbed == [6], robbed


def test_the_countdown_runs_on_the_games_clock_not_this_machines():
    """A tile matures when the GAME says so, not when this PC does (#1227).

    The two were twelve seconds apart live. With the game's clock a minute ahead, a tile
    whose completion is forty seconds away by the PC's reckoning is already raidable.
    """
    import game_clock

    rows = {"1": _row(1, 7, 40_000, 600_000)}
    # Forty seconds off is inside the ten-minute «soon» window on its own (#1241) — set
    # to match what the first pass will compute, so this call's `changed` is about the
    # ready flag the test is actually pinning, not a soon-flag settling on a cold row.
    rows["1"]["soon"] = True
    tab = _make_tab(rows)
    game_clock.reset()
    _expired, changed = tab._refresh_timers()
    assert rows["1"]["ready"] is False and changed is False
    try:
        game_clock.note(int((__import__("time").time() + 60) * 1000),
                        __import__("time").time(), __import__("time").time())
        _expired, changed = tab._refresh_timers()
        assert rows["1"]["ready"] is True, "the game's clock was not what decided"
        assert changed is True
    finally:
        game_clock.reset()


def test_room_ids_from_cached_self_ids():
    tab = object.__new__(st.SecretTasksTab)         # no Tk build
    tab._ids = ("100", "3d4b9dee")
    assert tab._room_id(None, st.SHARE_WORLD) == "country_100"
    assert tab._room_id(None, st.SHARE_ALLIANCE) == "alliance_100_3d4b9dee"
    tab._ids = ("", "")                             # nothing read -> no room, no send
    assert tab._room_id(None, st.SHARE_WORLD) == ""
    assert tab._room_id(None, st.SHARE_ALLIANCE) == ""


# -- surviving a restart (#1242) ---------------------------------------------------

class _FakeProfiles:
    """The one thing `_persist_rows`/`_load_persisted` ask of `rt.profiles`: a path."""

    def __init__(self, path: str) -> None:
        self._path = path

    def secret_tasks_state_json(self, name=None) -> str:
        return self._path


class _FakeOrder:
    """A stand-in for `Capture`/`AutoLoot`/`Sweep`: only `start`/`stop` are called."""

    def __init__(self) -> None:
        self.started = self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _StubTask:
    """What `_fetch_vm`/`_fetch_scan` hand `_merge` — just the fields a row copies.

    `starred` is what `_vm_landed` splits the one read on (#1244): the stars go up into
    the working list, the whole reply goes down into the alliance grid.
    """

    def __init__(self, uuid, server_id=1, x=1, y=2, level=7, cfg_id=16003,
                loot_count=1, expires_at=999_000, completed_at=1_000, starred=True):
        self.uuid = uuid
        self.server_id = server_id
        self.x, self.y, self.level, self.cfg_id = x, y, level, cfg_id
        self.loot_count = loot_count
        self.expires_at, self.completed_at = expires_at, completed_at
        self.starred = starred


def _state_path() -> str:
    import os
    import tempfile
    return os.path.join(tempfile.mkdtemp(), "secret_tasks_state.json")


def _fake_rt(path: str):
    """`rt.profiles.secret_tasks_state_json()` and `rt.root` — the only two things
    `_persist_rows`/`_load_persisted`/`_merge` ask of the runtime; `root` is never
    inspected once `tk_stringvar` is patched to `_Var` above, only passed through."""
    import types
    return types.SimpleNamespace(profiles=_FakeProfiles(path), root=None)


def test_persist_writes_a_checkpoint_load_persisted_reads_it_back():
    """A row's own fields survive a round trip through the profile's checkpoint file."""
    path = _state_path()
    tab = _make_tab({"11": _row(11, 6, 120_000, 600_000)})
    import types
    tab.rt = _fake_rt(path)
    tab._persist_rows()

    fresh = _make_tab({})
    fresh.rt = _fake_rt(path)
    restored = fresh._load_persisted()
    assert restored == {"11"}, restored
    row = fresh._rows["11"]
    assert (row["level"], row["x"], row["y"]) == (6, 1, 2)
    # Never trusted stored — `on_show`'s live check decides these, same as a freshly
    # merged row does; a restored one starts exactly as uncertain.
    assert row["ready"] is False and row["soon"] is False


def test_load_persisted_drops_a_row_already_expired_while_the_panel_was_shut():
    """Nothing a live check could confirm about a tile the map itself says is gone —
    dropped on load rather than shown and pulled a moment later (#1242)."""
    import json

    import game_clock
    game_clock.reset()
    try:
        now = game_clock.now_ms()
        path = _state_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([
                {"uuid": 1, "server": 1, "x": 1, "y": 2, "level": 7, "cfg_id": 1,
                 "loot_count": 0, "expires_at": now - 1_000, "completed_at": now - 5_000},
                {"uuid": 2, "server": 1, "x": 3, "y": 4, "level": 6, "cfg_id": 1,
                 "loot_count": 0, "expires_at": now + 600_000, "completed_at": now - 5_000},
            ], fh)
        tab = _make_tab({})
        import types
        tab.rt = _fake_rt(path)
        restored = tab._load_persisted()
        assert restored == {"2"}, restored
        assert list(tab._rows) == ["2"]
    finally:
        game_clock.reset()


def test_load_persisted_tolerates_a_missing_or_malformed_file():
    """No prior session, or one before #1242 — "nothing to restore", not a crash."""
    import types
    tab = _make_tab({})
    tab.rt = _fake_rt(_state_path())  # never written
    assert tab._load_persisted() == set()
    assert tab._rows == {}

    path = _state_path()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("not json")
    tab.rt = _fake_rt(path)
    assert tab._load_persisted() == set()


def test_merge_with_verify_drops_unconfirmed_rows_and_refreshes_confirmed_ones():
    """The live check `on_show` runs on whatever was restored (#1242): a row the game
    still backs is refreshed in place, one it does not confirm comes off the list
    rather than sit there unverified."""
    import types
    rows = {"1": _row(1, 7, -5_000, 600_000), "2": _row(2, 6, -5_000, 600_000)}
    tab = _make_tab(rows)
    tab.rt = _fake_rt(_state_path())

    confirmed = _StubTask(1, loot_count=2, expires_at=222_000, completed_at=111_000)
    tab._merge([confirmed], verify={"1", "2"})

    assert set(tab._rows) == {"1"}, tab._rows
    assert tab._rows["1"]["loot_count"] == 2
    assert tab._rows["1"]["expires_at"] == 222_000


def test_merge_without_verify_still_only_adds_new_ones():
    """The wire nudge / «Обновить» path (no `verify`) keeps its old ADD-only behaviour —
    #1242 must not turn every rescan into an unwanted reconciliation."""
    import types
    existing = _row(1, 7, -5_000, 600_000)
    tab = _make_tab({"1": existing})
    tab.rt = _fake_rt(_state_path())

    # A stale copy of the SAME row, as the wire might resend — must not clobber it —
    # plus a genuinely new tile.
    tab._merge([_StubTask(1, loot_count=99), _StubTask(2)])

    assert tab._rows["1"] is existing, "an un-verified merge overwrote an existing row"
    assert tab._rows["1"]["loot_count"] != 99
    assert "2" in tab._rows


def test_a_failed_verifying_read_leaves_restored_rows_alone():
    """A dead daemon right after the panel starts is not evidence a restored tile is
    gone — `_snapshot_work` must not hand `_merge` a `verify` set for a read that
    raised, or every restart with a slow-to-load game would empty the list on its own."""
    import types
    tab = object.__new__(st.SecretTasksTab)
    tab._restore_pending = {"1"}
    tab._fetch_vm = lambda: (_ for _ in ()).throw(RuntimeError("no daemon yet"))
    captured = {}
    tab.after = lambda fn: captured.setdefault("fn", fn)
    tab._snapshot_work()
    # `after` hands back the merge closure rather than running it (real `after` marshals
    # onto the Tk thread) — call it now, with a spy in place of the real `_merge`, to see
    # what `_snapshot_work` decided to pass it.
    merges = []
    tab._merge = lambda tasks, verify=None: merges.append((tasks, verify))
    captured["fn"]()
    assert merges == [([], None)], merges
    assert tab._restore_pending == {"1"}, "a failed read must not clear the pending set"


def test_clear_wipes_every_row_including_ones_not_expired():
    """#1243: «Очистить список» empties the table outright, not just the stale rows.

    The button used to only sweep out already-expired tiles — which the countdown
    drops on its own each second anyway, so it had nothing left to do. Now it wipes
    the whole list, on screen and on the checkpoint `_persist_rows` writes.
    """
    path = _state_path()
    rows = {"1": _row(1, 7, 120_000, 600_000),      # far from expiring
            "2": _row(2, 6, -100_000, -1_000)}      # already expired
    tab = _make_tab(rows)
    tab.rt = _fake_rt(path)
    tab._collected = {"9"}
    tab._restore_pending = {"1"}

    tab._clear()

    assert tab._rows == {}, tab._rows
    assert tab._collected == set()
    assert tab._restore_pending == set()
    assert tab._rendered == 1

    fresh = _make_tab({})
    fresh.rt = _fake_rt(path)
    assert fresh._load_persisted() == set(), "the wipe must reach the checkpoint too"


def test_web_press_clear_runs_the_wipe_on_the_tk_thread():
    """The phone gets the same «Очистить список» the window has (CLAUDE.md)."""
    tab = object.__new__(st.SecretTasksTab)
    posted = []
    tab.post = lambda fn: posted.append(fn)
    result = tab.web_press("clear", {})
    assert result == {"ok": True}
    assert posted == [tab._clear]


def test_on_profile_switch_drops_the_old_profiles_rows():
    """Every row's coordinate and server belongs to the OLD account — left in place it
    would be checkpointed straight back out under the NEW profile's own file (#1242)."""
    import types
    tab = _make_tab({"9": _row(9, 5, -5_000, 600_000)})
    tab.rt = _fake_rt(_state_path())
    tab.loaded = True
    tab.capture, tab.autoloot, tab.sweep = _FakeOrder(), _FakeOrder(), _FakeOrder()
    tab.monitor_var, tab.sweep_var = _Var(False), _Var(False)
    tab._sweep_hint = tab._rule_lbl = tab._rule_line = None
    tab._ids, tab._own_server = ("1", "a"), 1
    tab._snapshot = lambda: None          # the live re-seed is its own test, not this one
    tab.alliance = _FakeAllianceGrid()

    tab.on_profile_switch()

    assert tab._rows == {}, "the old profile's rows leaked into the new one"
    assert tab.alliance.cleared == 1, "the alliance grid kept the old account's tiles"
    assert tab._collected == set() and tab._auto_attempted == set()
    assert tab._ids is None and tab._own_server == 0
    assert tab.capture.stopped == 1 and tab.autoloot.stopped == 1 and tab.sweep.stopped == 1


# -- the alliance grid (#1244) -------------------------------------------------------
#
# The tab has two tables now: the starred working list above, and a mirror of the game's
# own alliance table below. These pin the three things that make the second one a mirror
# rather than a second working list — one read fills both, it is replaced whole, and it
# keeps the plain tiles the list above drops.

from panel.tabs.secret_tasks import alliance as al   # noqa: E402
from panel.tabs.secret_tasks import grid as gr       # noqa: E402

# Same reason as `st.tk_stringvar` above: a row's countdown variable is made here too,
# and a real one needs a live Tk root.
al.tk_stringvar = lambda master: _Var()


class _FakeAllianceGrid:
    """What the tab asks of the grid below it — nothing that needs a widget."""

    def __init__(self) -> None:
        self.applied, self.dropped = [], []
        self.cleared = self.ticks = 0

    def apply(self, tasks) -> None:
        self.applied.append(list(tasks))

    def clear(self) -> None:
        self.cleared += 1

    def drop(self, key) -> None:
        self.dropped.append(str(key))

    def tick(self) -> None:
        self.ticks += 1


class _FakeTable:
    """Enough of a Treeview for a grid to draw itself into without a display."""

    def __init__(self) -> None:
        self.rows: list = []

    def selection(self):
        return ()

    def selection_set(self, _iids):
        pass

    def get_children(self, _parent=""):
        return list(self.rows)

    def delete(self, iid):
        self.rows.remove(iid)

    def insert(self, _parent, _where, iid=None, values=(), tags=()):
        self.rows.append(iid)

    def exists(self, iid):
        return iid in self.rows

    def set(self, _iid, _column, _value):
        pass


def _alliance_grid(tree=None):
    """An `AllianceGrid` with no Tk behind it — the rows and the arithmetic only."""
    import types
    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    tab = types.SimpleNamespace(t=i18n.t, rt=types.SimpleNamespace(root=None),
                                _collectable=lambda row: bool(row.get("ready")),
                                _row_values=lambda row: tuple(
                                    str(row[c]) for c in ("x", "y", "level", "uuid",
                                                          "loot_count", "server")))
    g = object.__new__(al.AllianceGrid)
    g.tab = tab
    g._rows, g._tree, g._sort = {}, tree, None
    g._body = g._empty = None
    g._count_var = _Var()
    return g


def test_one_vm_read_fills_both_grids():
    """The stars go up into the working list, the WHOLE reply goes down into the mirror.

    The star filter used to live in `_fetch_vm`, which is why the lower table could not
    exist without a second round trip (#1244).
    """
    tab = object.__new__(st.SecretTasksTab)
    tab._vm_busy = True
    merges = []
    tab._merge = lambda tasks, verify=None: merges.append((list(tasks), verify))
    tab.alliance = _FakeAllianceGrid()

    star, plain = _StubTask(1, starred=True), _StubTask(2, starred=False)
    tab._vm_landed([star, plain], {"7"}, True)

    assert [t.uuid for t in merges[0][0]] == [1], merges
    assert merges[0][1] == {"7"}, "the restored-row check must survive the split"
    assert [t.uuid for t in tab.alliance.applied[0]] == [1, 2], tab.alliance.applied
    assert tab._vm_busy is False


def test_a_failed_vm_read_leaves_the_alliance_grid_alone():
    """A dead daemon is not evidence the alliance has nothing out — the same lie
    `_merge` refuses to tell about a restored row."""
    tab = object.__new__(st.SecretTasksTab)
    tab._vm_busy = True
    tab._merge = lambda tasks, verify=None: None
    tab.alliance = _FakeAllianceGrid()

    tab._vm_landed([], None, False)

    assert tab.alliance.applied == [], "a failed read emptied the alliance table"


def test_refresh_presses_both_sources():
    """«Обновить» — and the phone's — refresh the wire feed AND the game's own table."""
    tab = object.__new__(st.SecretTasksTab)
    calls = []
    tab.refresh = lambda: calls.append("wire")
    tab._snapshot = lambda: calls.append("vm")

    tab.refresh_both()
    assert calls == ["wire", "vm"], calls

    calls.clear()
    assert tab.web_press("refresh", {}) == {"ok": True}
    assert calls == ["wire", "vm"], calls


def test_the_two_reads_do_not_silence_each_other():
    """Two paths, two flags: the checkpoint merge in flight must not skip the VM read."""
    tab = object.__new__(st.SecretTasksTab)
    tab._busy, tab._vm_busy = True, False          # the wire feed is already running
    tab._status_var = _Var()
    tab.t = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru").t
    started = []
    import threading as _t
    real = _t.Thread
    _t.Thread = lambda target=None, daemon=None, args=(): type(
        "T", (), {"start": lambda self: started.append(target)})()
    try:
        tab._snapshot()
    finally:
        _t.Thread = real
    assert started and tab._vm_busy is True, "the VM read skipped because of `_busy`"


def test_each_read_clears_only_its_own_flag():
    """`_merge` is shared by both paths, so it clears neither: one read finishing must
    not tell the other it is free to start a second thread (#1244)."""
    tab = object.__new__(st.SecretTasksTab)
    tab._merge = lambda tasks, verify=None: None
    tab.alliance = _FakeAllianceGrid()

    tab._busy = tab._vm_busy = True
    tab._wire_landed([])
    assert (tab._busy, tab._vm_busy) == (False, True)

    tab._busy = True
    tab._vm_landed([], None, True)
    assert (tab._busy, tab._vm_busy) == (True, False)


def test_the_alliance_grid_is_replaced_whole_by_each_read():
    """A mirror, not a working list: a tile the game stopped listing is gone from it,
    and one that survived keeps its countdown variable so its cell does not blink."""
    g = _alliance_grid()
    g.apply([_StubTask(1), _StubTask(2, starred=False)])
    assert set(g._rows) == {"1", "2"}, g._rows
    # …and the plain tile the list above filters out is exactly what this one is for.
    kept = g._rows["1"]["timer"]

    g.apply([_StubTask(1, loot_count=2, expires_at=222_000)])

    assert set(g._rows) == {"1"}, g._rows
    assert g._rows["1"]["timer"] is kept, "the countdown variable was thrown away"
    assert g._rows["1"]["loot_count"] == 2 and g._rows["1"]["expires_at"] == 222_000


def test_the_alliance_grid_counts_down_and_drops_the_expired():
    """The same per-second arithmetic as the table above — `grid.refresh_timers`."""
    tree = _FakeTable()
    g = _alliance_grid(tree)
    now = int(__import__("time").time() * 1000)
    g.apply([_StubTask(1, completed_at=now + 120_000, expires_at=now + 600_000),
             _StubTask(2, completed_at=now - 100_000, expires_at=now - 1_000)])
    assert set(g._rows) == {"1", "2"}

    g.tick()

    assert set(g._rows) == {"1"}, "the expired tile stayed on the mirror"
    assert tree.rows == ["1"], tree.rows
    assert "готово через" in g._rows["1"]["timer"].get()


def test_a_robbery_takes_the_tile_off_both_tables():
    """One tile can be on both lists; one robbery, so it leaves both."""
    tab = object.__new__(st.SecretTasksTab)
    tab._rows = {"11": _row(11, 7, -5_000, 600_000)}
    tab._collected = set()
    tab.alliance = _FakeAllianceGrid()
    tab._render = lambda: None
    tab._update_status = lambda: None
    tab._persist_rows = lambda: None
    import types
    tab.rt = types.SimpleNamespace(put=lambda _line: None)
    tab.t = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru").t

    tab._collect_done("11", True)

    assert tab._rows == {} and tab.alliance.dropped == ["11"]


def test_the_phone_is_shown_the_alliance_list_too():
    """CLAUDE.md: what the window grew, the web grows in the same commit."""
    import types
    tab = object.__new__(st.SecretTasksTab)
    tab._rows = {}
    tab.show_spent_var = _Var(False)
    tab._visible_rows = lambda: []
    tab.autoloot = types.SimpleNamespace(state=lambda: ("secret.autoloot", "off"))
    tab.alliance = types.SimpleNamespace(
        web_items=lambda: [{"text": "X:1 Y:2", "facts": [], "until": None, "pill": None}])

    view = tab.web_view()
    cards = {c.get("title"): c for c in view["cards"]}
    assert "secrettasks.alliance" in cards, cards
    assert cards["secrettasks.alliance"]["items"][0]["text"] == "X:1 Y:2"
    assert cards["secrettasks.alliance"]["empty"] == "secrettasks.alliance.empty"


def test_the_phone_reads_the_alliance_rows_the_same_way_as_the_window():
    """Same facts, same countdown, same ready pill — one list drawn two ways."""
    g = _alliance_grid()
    now = int(__import__("time").time() * 1000)
    g.apply([_StubTask(1, level=6, loot_count=1,
                       completed_at=now - 5_000, expires_at=now + 600_000)])
    g._rows["1"]["ready"] = True

    item = g.web_items()[0]
    # The same coordinate token the card above prints — server included, because a tile
    # on somebody else's server is a different tile.
    assert item["text"] == "#1 X:1 Y:2", item
    assert {f["value"] for f in item["facts"]} == {"6", "1/3"}, item
    assert item["pill"] == "secrettasks.ready"
    assert abs(item["until"] - (now + 600_000) / 1000.0) < 1


def test_both_grids_are_literally_the_same_table():
    """«Грид точно такой же» (#1244): one column set, one sort rule, one set of colours."""
    assert st.COLUMNS is gr.COLUMNS
    assert (st.LINK_COLUMN, st.ACTION_COLUMN) == (gr.LINK_COLUMN, gr.ACTION_COLUMN)
    assert st.SecretTasksTab.SORT_KEYS is gr.SORT_KEYS
    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "alliance.py").read_text(encoding="utf-8")
    assert "grid.make_tree" in src, "the second grid builds a table of its own"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
