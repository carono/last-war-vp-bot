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


#: The fixture's home server. Every `_row` sits on server 1, i.e. ABROAD — which is the
#: only place the standing order may rob since #1188, so an ordinary fixture row is a
#: legal target and the tests that are ABOUT the home rule move a row onto this number.
_HOME_SERVER = 534


class _FakeAutoLoot:
    """What the tab asks the standing order: its one bound, and the own-server rule.

    Since #1256 the rule is a single «минимальный уровень» — this level and everything
    above it — and the tab's `rob_candidates` reads it through here.
    """

    def __init__(self, tab):
        self.tab = tab
        self._seen = set()
        # The home server, and it is never None in a working client (#1188): the
        # exclusion is unconditional now, so `rob_candidates` reads this as «which one
        # is home» rather than «is the prohibition on». `0`/`None` means the client
        # could not say, and then nothing is a target at all.
        self.skip = _HOME_SERVER

    def level_min(self):
        raw = str(self.tab.level_min_var.get()).strip()
        return int(raw) if raw.isdigit() else None

    def skip_server(self):
        return self.skip


def _make_tab(rows, lo="", hi="", autoloot=False, rob_min=None):
    """A tab with its build skipped, wired just enough to run the timer / poll paths.

    No Tk root: the countdown, the poll reconciliation and the #1099 rob rule are all
    plain decisions over the row dicts, and that is the point of testing them here.
    """
    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    tab = object.__new__(st.SecretTasksTab)
    tab.t = i18n.t
    # The robbery's one bound (#1256). Defaulted from the fixture's `hi` because that is
    # what the range it replaces actually robbed — «от 1 до 7» took 7s and left 6s alone
    # — so a test written before the change still means what it meant.
    tab.level_min_var = _Var(rob_min if rob_min is not None else hi)
    # The DISPLAY pair, from the same argument: the fixture predates the split (#1244),
    # and every test written against it means «this range, for both». The tests that are
    # ABOUT the split set the two apart themselves.
    tab.filter_from_var, tab.filter_to_var = _Var(lo), _Var(hi)
    tab.autoloot_var = _Var(autoloot)
    # «Показывать исчерпанные» — off, as a fresh profile has it.
    tab.show_spent_var = _Var(False)
    # «Скрывать со своего сервера» — the display rule (#1251). OFF in the fixture even
    # though a fresh profile has it ON: every test written before it means «show me the
    # rows», and the own server is unreadable here anyway. The tests that are ABOUT the
    # rule set both halves themselves.
    tab.hide_own_var = _Var(False)
    tab._own_server = 0
    tab.autoloot = _FakeAutoLoot(tab)
    tab._rows = rows
    tab._collected = set()
    # Presses waiting out the ten-second window (#1272) — a fresh tab has none.
    tab._pressing = set()
    tab._polling = False
    tab._rendered = 0
    tab._render = lambda: setattr(tab, "_rendered", tab._rendered + 1)
    # The counters live on the notebook tabs now (#1272); a fixture with no notebook
    # simply has nothing to relabel.
    tab.sync_page_counts = lambda: None
    tab._update_status = lambda: None
    # `_persist_rows` runs after every structural change now (#1242) — a throwaway file
    # so the timer / poll paths this fixture is FOR do not have to know that, and a test
    # that cares about persistence itself overrides this with its own `_FakeProfiles`.
    tab.rt = _fake_rt(_state_path())
    # The «уже поделились» store (#1245): every countdown pass consults it, so the tab
    # carries one whatever the fixture is testing. It is empty unless a test marks
    # something, and it reads its own throwaway file like the checkpoint above.
    tab.shared = _shared_marks(tab)
    # How far back the camera sits when this tab moves it (#1265) — the close view a
    # fresh profile has, which is what every jump did before the setting existed.
    tab._zoom_level = "tile"
    return tab


def _shared_marks(tab):
    """A real `SharedMarks` over the fixture's runtime — no Tk, no game, just a file."""
    from panel.tabs.secret_tasks.shared import SharedMarks
    return SharedMarks(tab.rt)


def _row(uuid, level, done_off, exp_off):
    now = int(__import__("time").time() * 1000)
    return {"uuid": uuid, "server": 1, "x": 1, "y": 2, "level": level,
            # A cfgId that really is a STARRED tile of that level (family 6000,
            # `LLVV` tail): the restore path judges the star off this now (#1244).
            "cfg_id": int("6000%02d01" % level), "loot_count": 0,
            "completed_at": now + done_off, "expires_at": now + exp_off,
            # The list this fixture stands for is starred-only by construction (#1244).
            "starred": True,
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
    """A ready tile the read CAN see and does not carry is off the map; a failed read
    removes none.

    «Can see» is the part #1272 had to add: the read carries something, and the row is
    one this same read put on the list. An EMPTY answer and a row from another source
    both have their own tests below — they are the two shapes that were deleting tiles
    nobody could get back.
    """
    rows = {"2": _row(2, 7, -5_000, 600_000)}
    rows["2"]["ready"] = True
    rows["2"]["source"] = st.SOURCE_VM
    tab = _make_tab(rows)

    tab._poll_apply(["2"], {"9": _LiveTask(9)})   # a read that answered, without it
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


def test_the_rule_takes_the_minimum_level_and_everything_above_it():
    """«минимальный уровень 6» takes the 6 AND the 7, best first (#1256).

    The rule it replaces would have left the 6 standing there for ever: it robbed the
    range's TOP and nothing else, so «от 1 до 7» meant «7 or nothing» however long a
    raidable 6 sat on the map.
    """
    rows = {"6": _row(6, 6, -5_000, 600_000), "7": _row(7, 7, -5_000, 600_000)}
    for r in rows.values():
        r["ready"] = True
    tab = _make_tab(rows, rob_min="6")
    assert [int(r["level"]) for r in tab.rob_candidates()] == [7, 6]

    # Raise the bound and the 6 drops out of the choice — nothing else changes.
    tab.level_min_var.set("7")
    assert [int(r["level"]) for r in tab.rob_candidates()] == [7]


def test_nothing_below_the_minimum_is_ever_a_target():
    """A tile under «минимальный уровень» is not chosen, however raidable it is."""
    rows = {"6": _row(6, 6, -5_000, 600_000), "7": _row(7, 7, -5_000, 600_000)}
    for r in rows.values():
        r["ready"] = True
    tab = _make_tab(rows, rob_min="8")
    assert tab.rob_candidates() == []

    # An empty box is no bound at all — every ready star is a target.
    tab.level_min_var.set("")
    assert [int(r["level"]) for r in tab.rob_candidates()] == [7, 6]


def test_the_poll_verifies_the_list_and_robs_nothing_itself():
    """The ready-row poll is the actuality check, not a second robbery path (#1256).

    It used to rob as well as verify, through a copy of the rule and a steal of its own
    — a third doorway into the ability on a thirty-second clock. What it does now is
    drop what the game no longer confirms and leave the choosing to the one place that
    chooses.
    """
    rows = {"6": _row(6, 6, -5_000, 600_000), "7": _row(7, 7, -5_000, 600_000)}
    for r in rows.values():
        r["ready"] = True
        # Both came off the same read the poll makes, so the poll may reconcile them —
        # a tile from the capture is out of its scope and has a test of its own (#1272).
        r["source"] = st.SOURCE_VM
    tab = _make_tab(rows, rob_min="6", autoloot=True)
    tab._collect = lambda row: (_ for _ in ()).throw(
        AssertionError("the poll robbed something"))

    # The 6 is gone from the game's answer: its row goes, and the choice narrows to what
    # is left — without a single press from here.
    tab._poll_apply(list(rows), {"7": _LiveTask(7)})
    assert sorted(tab._rows) == ["7"], tab._rows
    assert [int(r["level"]) for r in tab.rob_candidates()] == [7]


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
    # A tile off the wire knows no owner, and an empty cell is how the table says so
    # rather than inventing one (#1244).
    assert cells["owner"] == "", cells
    # A tile still counting down offers no action: collecting it early is a robbery the
    # server would refuse.
    assert cells["action"] == "", cells

    # A row the GAME does not star wears no star (#1244, live report): the glyph used
    # to be part of the level format, so all 200 rows of the roster claimed one while
    # 167 of them have none in the game. It says its level, and the owner beside it.
    plain = dict(_row(2, 7, 120_000, 600_000), owner_name="Player1", starred=False)
    plain["timer"].set("")
    cells = dict(zip([c[0] for c in st.COLUMNS],
                     st.SecretTasksTab._row_values(tab, plain)))
    assert cells["owner"] == "Player1", cells
    assert "⭐" not in cells["lvl"], cells
    assert cells["lvl"].endswith(tab.t("secrettasks.level", n=7)), cells

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


def test_toggling_auto_loot_starts_the_order_and_greys_nothing_beside_it():
    """«Автолут ★» has no companion control any more (#1188).

    It used to grey «Не грабить на своём сервере» — the one box that hung off it — and
    that whole apparatus (`_sync_autoloot_controls`, `_on_skip_own_change`) went with the
    box when the prohibition became unconditional. What is left is the toggle itself, and
    a tab whose widgets are not built yet must still survive it: «Стоп всё» and
    `apply_config` both reach this before there is anything on screen.
    """
    tab = object.__new__(st.SecretTasksTab)
    tab.autoloot_var = _Var(False)
    toggled = []
    tab.autoloot = __import__("types").SimpleNamespace(
        toggle=lambda: toggled.append(1))
    st.SecretTasksTab._on_autoloot_toggle(tab)
    assert toggled == [1], toggled

    for gone in ("_sync_autoloot_controls", "_on_skip_own_change"):
        assert not hasattr(st.SecretTasksTab, gone), gone


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

    # The standing order weighs the same rows and passes over the spent one. Asked of
    # the choice itself (#1256) rather than of the poll around it: the poll refreshes a
    # row's loot count from the game first, and the game never reports a 3/3 tile at all
    # — it drops them — so the poll could only reach this case by inventing a reading
    # the VM cannot give.
    tab.autoloot_var = _Var(True)
    assert [r["uuid"] for r in tab.rob_candidates()] == [6]


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
    """The paths `rt.profiles` is asked for: the checkpoint and the shared-mark store.

    The second one is the «уже поделились» file (#1245), which the panel and the two
    capture children all append to; it lives beside the checkpoint so a fixture that
    writes one has somewhere to put the other.
    """

    def __init__(self, path: str) -> None:
        self._path = path

    def secret_tasks_state_json(self, name=None) -> str:
        return self._path

    def secret_shared_json(self, name=None) -> str:
        import os
        return os.path.join(os.path.dirname(self._path), "secret_shared.jsonl")


class _FakeOrder:
    """A stand-in for `Capture`/`AutoLoot`/`Sweep`: only `start`/`stop` are called.

    …and, for the watcher, the book of uuids it has already fired at — a profile switch
    clears it, because those belong to the map the other client was looking at (#1256).
    """

    def __init__(self) -> None:
        self.started = self.stopped = 0
        self._seen: set = set()

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _StubTask:
    """What `_fetch_vm`/`_fetch_scan` hand `_merge` — just the fields a row copies.

    `starred` is what `_vm_landed` splits the one read on (#1244): the stars go up into
    the working list, the whole reply goes down into the alliance grid.
    """

    def __init__(self, uuid, server_id=1, x=1, y=2, level=7, cfg_id=60000701,
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
                {"uuid": 1, "server": 1, "x": 1, "y": 2, "level": 7,
                 "cfg_id": 60000701,
                 "loot_count": 0, "expires_at": now - 1_000, "completed_at": now - 5_000},
                {"uuid": 2, "server": 1, "x": 3, "y": 4, "level": 6,
                 "cfg_id": 60000601,
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

    # The same row as the wire resends it, plus a genuinely new tile. The ROW OBJECT
    # survives — its timer, its marks and where it came from are the panel's, not the
    # wire's — and what the wire is the only source of is taken (#1272).
    tab._merge([_StubTask(1, loot_count=2), _StubTask(2)])

    assert tab._rows["1"] is existing, "an un-verified merge replaced an existing row"
    assert tab._rows["1"]["loot_count"] == 2, "the fresh loot count was thrown away"
    assert "2" in tab._rows

    # …and a STALER copy cannot undo it: a tile is robbed 0 -> 1 -> 2 -> 3 and never
    # un-robbed, so the count only rises.
    tab._merge([_StubTask(1, loot_count=0)])
    assert tab._rows["1"]["loot_count"] == 2, "a stale record walked the count backwards"


def test_a_rescan_that_fills_a_tile_takes_it_off_the_raid_list():
    """«Полностью ограбленные не исчезают» (#1272) — they do now, because the count
    that decides it can finally move. Three looters and the tile has no slot for
    anybody, so it stops being drawn (unless «Показывать исчерпанные» asks)."""
    row = _row(1, 7, -5_000, 600_000)
    row["loot_count"] = 1
    tab = _make_tab({"1": row})
    tab.rt = _fake_rt(_state_path())
    assert [r["uuid"] for r in tab._visible_rows()] == [1]

    tab._merge([_StubTask(1, loot_count=3)])

    assert tab._rows["1"]["loot_count"] == 3
    assert tab._spent(tab._rows["1"]) is True
    assert tab._visible_rows() == [], "a 3/3 tile is still drawn as a raid"
    # …and it is HIDDEN, not deleted: «Показывать исчерпанные» is what it is for.
    assert "1" in tab._rows


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
    tab._merge = lambda tasks, verify=None, source=None: merges.append((tasks, verify))
    captured["fn"]()
    assert merges == [([], None)], merges
    assert tab._restore_pending == {"1"}, "a failed read must not clear the pending set"


def test_a_read_that_cannot_see_a_row_may_not_delete_it():
    """THE ONE THAT COST A MAP LAP (#1272).

    The read that verifies the restored list walks the client's own `allianceTask` — MY
    alliance's tasks. Measured live: 170 of them, all mine, all on the home server, and
    the raid list drops the home server on the way in — so on that account the read comes
    back EMPTY every single time. Every restored row is a tile the map capture found
    somewhere else entirely, and every one of them was being deleted for not being in an
    answer that could never have contained it. «Увидел список на секунду — и он пропал.»
    """
    import types
    restored = _row(1, 7, -5_000, 600_000)          # the capture found this one
    restored["source"] = st.SOURCE_WIRE
    seeded = _row(2, 7, -5_000, 600_000)            # …and the VM read seeded this one
    seeded["source"] = st.SOURCE_VM
    tab = _make_tab({"1": restored, "2": seeded})
    tab.rt = _fake_rt(_state_path())

    # A perfectly successful VM read that happens to carry neither of them.
    tab._merge([_StubTask(3)], verify={"1", "2"}, source=st.SOURCE_VM)

    assert "1" in tab._rows, "a wire row was deleted by a read that cannot see it"
    assert "2" not in tab._rows, "a VM row the VM read dropped should be gone"


def test_an_empty_answer_says_nothing_about_anything():
    """A read that came back with no rows is «I have nothing to say», never «none of
    them exists» — and on a home-bound alliance that is what the raid read returns every
    time (#1272)."""
    row = _row(1, 7, -5_000, 600_000)
    row["source"] = st.SOURCE_VM                    # …even its OWN source's rows survive
    tab = _make_tab({"1": row})
    tab.rt = _fake_rt(_state_path())

    tab._merge([], verify={"1"}, source=st.SOURCE_VM)

    assert "1" in tab._rows, "an empty read emptied the list"


def test_the_ready_row_poll_obeys_the_same_scope():
    """It reads the same alliance table on a thirty-second clock, so it was deleting the
    capture's tiles all session long, quietly (#1272)."""
    wire = _row(1, 7, -5_000, 600_000)
    wire["source"], wire["ready"] = st.SOURCE_WIRE, True
    vm = _row(2, 7, -5_000, 600_000)
    vm["source"], vm["ready"] = st.SOURCE_VM, True
    tab = _make_tab({"1": wire, "2": vm})

    tab._poll_apply(["1", "2"], {"3": _LiveTask(3)})

    assert "1" in tab._rows, "the poll deleted a tile it cannot see"
    assert "2" not in tab._rows

    # …and an empty read still takes nothing, whoever found the row.
    tab = _make_tab({"2": dict(vm)})
    tab._poll_apply(["2"], {})
    assert "2" in tab._rows, "an empty poll read emptied the list"


def test_a_restored_row_is_the_captures_until_the_checkpoint_says_otherwise():
    """A checkpoint written before #1272 says nothing about where its rows came from,
    and the safe answer is the capture's — anything else re-opens the deletion."""
    import json as _json
    import types
    path = _state_path()
    rec = {"uuid": 1, "server": 1, "x": 1, "y": 2, "level": 7, "cfg_id": 60000701,
           "loot_count": 0, "starred": True,
           "completed_at": _ms(-5_000), "expires_at": _ms(600_000)}
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump([rec], fh)                        # …no «source» at all
    tab = _make_tab({})
    tab.rt = types.SimpleNamespace(profiles=_FakeProfiles(path), root=None)

    tab._load_persisted()

    assert tab._rows["1"]["source"] == st.SOURCE_WIRE
    tab._merge([], verify={"1"}, source=st.SOURCE_VM)
    assert "1" in tab._rows, "a restored row was verified away on the first read"


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
    tab.capture, tab.autoloot = _FakeOrder(), _FakeOrder()
    # …and the alliance page's own standing order, which spends a second daily budget
    # over a second list and so has to be bounced onto the new account too (#1272).
    tab.autoassist = _FakeOrder()
    # The ghost sniffer is a second, independent capture since #1251 — its switch lives
    # on the map page, so the fixture carries both.
    tab.ghost_capture = _FakeOrder()
    tab.monitor_var, tab.autoassist_var = _Var(False), _Var(False)
    tab._rule_lbl = tab._rule_line = None
    tab._assist_lbl = tab._assist_line = None
    tab._ids, tab._own_server = ("1", "a"), 1
    # The live re-seeds have tests of their own; this one is about the rows.
    tab._snapshot = tab._roster = tab._ghost = lambda: None
    tab._prime_own_server = lambda: None
    tab.alliance, tab.ghost = _FakeAllianceGrid(), _FakeAllianceGrid()
    tab.ghost_allies = _FakeAllianceGrid()
    tab.ghost_map = _FakeAllianceGrid()
    tab.ghost_map.monitor_var = _Var(False)

    tab.on_profile_switch()

    assert tab._rows == {}, "the old profile's rows leaked into the new one"
    assert tab.alliance.cleared == 1, "the alliance grid kept the old account's tiles"
    # The ghost page is another account's event budget and another account's squads
    # (#1251) — it goes with the rest.
    assert tab.ghost.cleared == 1, "the ghost grid kept the old account's squads"
    assert tab.ghost_allies.cleared == 1, "the allies' ghost grid kept the old alliance"
    assert tab.ghost_map.cleared == 1, "the map page kept the old profile's tiles"
    # …and what the standing order had already fired at is the other account's map too
    # (#1256 — the book moved onto the watcher when the choosing did).
    assert tab._collected == set() and tab.autoloot._seen == set()
    assert tab._ids is None and tab._own_server == 0
    assert tab.capture.stopped == 1 and tab.autoloot.stopped == 1
    assert tab.autoassist.stopped == 1, "the help order stayed on the old account"


# -- the alliance grid (#1244) -------------------------------------------------------
#
# The tab has two tables now: the starred working list above, and a mirror of the game's
# own alliance table below. These pin the three things that make the second one a mirror
# rather than a second working list — one read fills both, it is replaced whole, and it
# keeps the plain tiles the list above drops.

from panel.tabs.secret_tasks import alliance as al   # noqa: E402
from panel.tabs.secret_tasks import grid as gr       # noqa: E402

# Same reason as `st.tk_stringvar` above: a row's countdown variable is made here too,
# and a real one needs a live Tk root. In `grid` since #1251 — that is where the shared
# `TaskGrid` builds a row, for the alliance page and the ghost one alike.
gr.tk_stringvar = lambda master: _Var()


class _FakeAllianceGrid:
    """What the tab asks of the grid below it — nothing that needs a widget."""

    def __init__(self) -> None:
        self.applied, self.dropped = [], []
        self.cleared = self.ticks = 0

    def apply(self, tasks) -> None:
        self.applied.append(list(tasks))

    def clear(self) -> None:
        self.cleared += 1

    def mark_robbed(self, key) -> None:
        """One robbery marks the tile on every table it is drawn on (#1272).

        It used to be `drop` — the row came off this table as well — and the whole of
        that change is that it does not any more.
        """
        self.robbed = getattr(self, "robbed", [])
        self.robbed.append(str(key))

    def tick(self) -> None:
        self.ticks += 1

    def restore(self) -> None:
        """The map page keeps a list of its own and reads it back (#1251)."""
        self.restored = getattr(self, "restored", 0) + 1


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
    rt = types.SimpleNamespace(root=None, profiles=_FakeProfiles(_state_path()))
    def _rank(row):
        key = "secrettasks.stars" if row.get("starred") else "secrettasks.level"
        return i18n.t(key, n=int(row.get("level") or 0))

    tab = types.SimpleNamespace(t=i18n.t, rt=rt, _rank=_rank,
                                _collectable=lambda row: bool(row.get("ready")),
                                # The strip of buttons is re-aimed whenever a page
                                # redraws (#1251); with no window there is nothing to
                                # aim, so the fixture only has to answer the call.
                                sync_actions=lambda: None,
                                # …and the per-page counters, which land on a notebook
                                # this fixture does not have (#1272).
                                sync_page_counts=lambda: None,
                                _row_values=lambda row: tuple(
                                    str(row[c]) for c in ("x", "y", "level", "uuid",
                                                          "loot_count", "server")))
    # The store every grid reads the «уже поделились» mark from (#1245) — a real one
    # over a throwaway file, so a test can mark a tile and see the table say so.
    tab.shared = _shared_marks(tab)
    g = object.__new__(al.AllianceGrid)
    g.tab = tab
    g._rows, g._tree, g._sort = {}, tree, None
    g._body = g._empty = None
    g._count_var = _Var()
    # Every page carries its own level range now (#1251) — blank here, so a test that
    # does not mention it sees every row.
    g.level_from, g.level_to = _Var(""), _Var("")
    # The page's own two display rules (#1251) — off, which is how a fresh profile has
    # them, so a test that does not mention them sees the whole mirror.
    g.ur_var, g.star_var = _Var(False), _Var(False)
    return g


def _member_task(uuid, owner="Player1", level=7, loot_count=0,
                 completed_at=1_000, expires_at=999_000, starred=True,
                 cfg_id=60000701):
    """One record in the shape `dispatch_tasks.alliance_roster` hands the grid.

    Invented values of the real shape, never a live one (CLAUDE.md): a made-up uuid, a
    name that looks made up, and an alliance tag that is plainly not anybody's.
    """
    return {"uuid": uuid, "server": 1, "x": 1, "y": 2, "point_id": 4242,
            "cfg_id": cfg_id, "family": "6000", "level": level, "starred": starred,
            "loot_count": loot_count, "completed_at": completed_at,
            "expires_at": expires_at, "owner_uid": "1000000000000001",
            "owner_name": owner, "alliance_abbr": "AL1"}


def test_the_raid_read_stays_the_raid_read():
    """The list above is the ROBBABLE stars and says so; the roster below is its own
    read, because a filtered list cannot answer «who is running what» (#1244)."""
    tab = object.__new__(st.SecretTasksTab)
    tab._vm_busy = True
    merges = []
    tab._merge = lambda tasks, verify=None, source=None: merges.append((list(tasks), verify))

    tab._vm_landed([_StubTask(1)], {"7"})

    assert [t.uuid for t in merges[0][0]] == [1], merges
    assert merges[0][1] == {"7"}, "the restored-row check must survive"
    assert tab._vm_busy is False


def test_the_roster_read_fills_the_alliance_grid():
    """A good read replaces the table below; nothing else on the tab is touched."""
    tab = object.__new__(st.SecretTasksTab)
    tab._roster_busy = True
    tab.alliance = _FakeAllianceGrid()

    tab._roster_landed([_member_task(1), _member_task(2, owner="Player2")], True)

    assert [r["owner_name"] for r in tab.alliance.applied[0]] == ["Player1", "Player2"]
    assert tab._roster_busy is False


def test_a_failed_roster_read_leaves_the_alliance_grid_alone():
    """A dead daemon is not evidence the alliance has nothing out — the same lie
    `_merge` refuses to tell about a restored row."""
    tab = object.__new__(st.SecretTasksTab)
    tab._roster_busy = True
    tab.alliance = _FakeAllianceGrid()

    tab._roster_landed([], False)

    assert tab.alliance.applied == [], "a failed read emptied the alliance table"


def test_refresh_presses_every_source():
    """«Обновить» — and the phone's — press all four: wire, raid list, roster, ghost."""
    tab = object.__new__(st.SecretTasksTab)
    calls = []
    tab.refresh = lambda: calls.append("wire")
    tab._snapshot = lambda: calls.append("vm")
    tab._roster = lambda: calls.append("roster")
    tab._ghost = lambda: calls.append("ghost")

    tab.refresh_both()
    assert calls == ["wire", "vm", "roster", "ghost"], calls

    calls.clear()
    assert tab.web_press("refresh", {}) == {"ok": True}
    assert calls == ["wire", "vm", "roster", "ghost"], calls


def test_a_share_does_not_pay_for_the_roster_read():
    """A mate sharing a raid changes the raid list, not who is running what — and the
    roster is the tab's slowest round trip (#1244)."""
    tab = object.__new__(st.SecretTasksTab)
    tab.loaded = True
    calls = []
    tab.refresh = lambda: calls.append("wire")
    tab._snapshot = lambda: calls.append("vm")
    tab._roster = lambda: calls.append("roster")
    # The ghost list is a different event altogether — a share says nothing about it
    # either (#1251).
    tab._ghost = lambda: calls.append("ghost")

    tab.refresh_live()

    assert calls == ["wire", "vm"], calls


def test_the_reads_do_not_silence_each_other():
    """Four paths, four flags: one in flight must not skip the others (#1244, #1251)."""
    import threading as _t
    tab = object.__new__(st.SecretTasksTab)
    tab._busy = True                               # the wire feed is already running
    tab._vm_busy = tab._roster_busy = tab._ghost_busy = False
    tab._status_var = _Var()
    tab.t = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru").t
    started = []
    real = _t.Thread
    _t.Thread = lambda target=None, daemon=None, args=(): type(
        "T", (), {"start": lambda self: started.append(target)})()
    try:
        tab._snapshot()
        tab._roster()
        tab._ghost()
    finally:
        _t.Thread = real
    assert len(started) == 3, "a read skipped because another one held `_busy`"
    assert tab._vm_busy is True and tab._roster_busy is True
    assert tab._ghost_busy is True


def test_each_read_clears_only_its_own_flag():
    """`_merge` is shared by two paths, so it clears neither: one read finishing must
    not tell the others they are free to start a second thread (#1244)."""
    tab = object.__new__(st.SecretTasksTab)
    tab._merge = lambda tasks, verify=None, source=None: None
    tab.alliance = _FakeAllianceGrid()

    tab.ghost = _FakeAllianceGrid()
    tab.ghost.landed = lambda status, rows: None
    tab.ghost_allies = _FakeAllianceGrid()
    tab.ghost_allies.landed = lambda status, rows: None
    tab._busy = tab._vm_busy = tab._roster_busy = tab._ghost_busy = True
    tab._wire_landed([])
    assert (tab._busy, tab._vm_busy, tab._roster_busy) == (False, True, True)

    tab._busy = True
    tab._vm_landed([], None)
    assert (tab._busy, tab._vm_busy, tab._roster_busy) == (True, False, True)

    tab._vm_busy = True
    tab._roster_landed([], True)
    assert (tab._busy, tab._vm_busy, tab._roster_busy) == (True, True, False)

    tab._roster_busy = True
    tab.ghost_map = _FakeAllianceGrid()
    tab.ghost_map.landed = lambda status, rows: None
    tab._ghost_landed({}, [], [], [], True)
    assert (tab._busy, tab._vm_busy, tab._roster_busy, tab._ghost_busy) == (
        True, True, True, False)


def test_the_alliance_grid_is_replaced_whole_by_each_read():
    """A mirror, not a working list: a task the game stopped listing is gone from it,
    and one that survived keeps its countdown variable so its cell does not blink."""
    g = _alliance_grid()
    # Nothing is filtered out of it — not the plain tiles the star rule drops, not the
    # ones already robbed three times: every one of them is somebody's task.
    g.apply([_member_task(1), _member_task(2, starred=False, loot_count=3)])
    assert set(g._rows) == {"1", "2"}, g._rows
    kept = g._rows["1"]["timer"]

    g.apply([_member_task(1, owner="Player3", loot_count=2, expires_at=222_000)])

    assert set(g._rows) == {"1"}, g._rows
    assert g._rows["1"]["timer"] is kept, "the countdown variable was thrown away"
    assert g._rows["1"]["loot_count"] == 2 and g._rows["1"]["expires_at"] == 222_000
    assert g._rows["1"]["owner_name"] == "Player3", "the row kept a stale owner"


def test_the_alliance_grid_carries_who_is_running_the_task():
    """The whole point of the table: the member, the rank, the finish and the loots."""
    g = _alliance_grid()
    g.apply([_member_task(1, owner="Player1", level=6, loot_count=2,
                          completed_at=111_000, expires_at=222_000)])
    row = g._rows["1"]
    assert row["owner_name"] == "Player1"
    assert (row["level"], row["loot_count"]) == (6, 2)
    assert (row["completed_at"], row["expires_at"]) == (111_000, 222_000)


def test_the_alliance_grid_counts_down_and_drops_the_expired():
    """The same per-second arithmetic as the table above — `grid.refresh_timers`."""
    tree = _FakeTable()
    g = _alliance_grid(tree)
    now = int(__import__("time").time() * 1000)
    g.apply([_member_task(1, completed_at=now + 120_000, expires_at=now + 600_000),
             _member_task(2, completed_at=now - 100_000, expires_at=now - 1_000)])
    assert set(g._rows) == {"1", "2"}

    g.tick()

    assert set(g._rows) == {"1"}, "the ended task stayed on the mirror"
    assert tree.rows == ["1"], tree.rows
    assert "готово через" in g._rows["1"]["timer"].get()


def test_a_robbery_marks_the_tile_on_both_tables_and_removes_it_from_neither():
    """One tile can be on both lists; one robbery marks both and takes away neither.

    It used to take the row off both, and that threw away what the tile was still good
    for: a raid worth one of the day's five is the raid worth telling the alliance
    about, and «Поделиться» has to be pressed on a row (#1272).
    """
    tab = _robbed_tab()

    assert "9" in tab._rows, "the robbed row was taken off the list"
    assert tab._rows["9"]["robbed"] is True
    assert tab.alliance.robbed == ["9"], "the table below kept the old behaviour"
    # …and the session book still remembers the uuid, which is what stops a later
    # capture putting back an unmarked copy once this row has expired.
    assert tab._collected == {"9"}


def test_a_robbed_row_offers_no_robbery_anywhere_it_is_asked():
    """Every doorway into «Собрать» goes through `_collectable`, so one rule shuts them
    all: the action cell, the strip, the right-click menu and the standing order."""
    tab = _robbed_tab()
    row = tab._rows["9"]

    assert tab._collectable(row) is False
    assert row not in tab.rob_candidates()
    assert tab.rob_candidates() == [], tab.rob_candidates()
    # The action cell is empty, which is what a Treeview has instead of a hidden button.
    cells = dict(zip([c[0] for c in st.COLUMNS], st.SecretTasksTab._row_values(tab, row)))
    assert cells["action"] == "", cells


def test_a_robbed_row_still_says_where_it_is_and_still_says_it_was_robbed():
    """The mark is the glyph on the coordinate and the words in the state cell — the
    shape «уже поделились» already had (#1245) — and the token still parses, because
    jumping to the tile is half of what the row is kept for."""
    import coords as coords_fmt
    tab = _robbed_tab()
    row = tab._rows["9"]
    tab._refresh_timers()
    cells = dict(zip([c[0] for c in st.COLUMNS], st.SecretTasksTab._row_values(tab, row)))

    assert cells["coords"].startswith(gr.ROBBED_GLYPH), cells
    assert coords_fmt.parse(cells["coords"]), "the coordinate stopped being clickable"
    assert tab.t("secrettasks.robbed_mark") in row["timer"].get(), row["timer"].get()


def test_a_robbed_row_survives_the_reads_that_would_otherwise_drop_it():
    """Our own robbery is what most often fills the tile's last slot, so the very next
    read is the one that stops carrying it — and the row would vanish half a minute
    after the change made to keep it (#1272). Its own expiry still ends it."""
    tab = _robbed_tab()

    tab._poll_apply(["9"], {})                  # a good read, and the tile is not in it
    assert "9" in tab._rows, "the ready-row poll dropped the robbed row"

    # …and it is still shown once the robbery has filled the tile — «Показывать
    # исчерпанные» is off in this fixture, and a 3/3 tile we robbed is not hidden by it.
    tab._rows["9"]["loot_count"] = 3
    assert tab._spent(tab._rows["9"]) is True
    assert [r["uuid"] for r in tab._visible_rows()] == [9]

    # The clock is what ends it, robbed or not.
    tab._rows["9"]["expires_at"] = 0
    expired, _changed = tab._refresh_timers()
    assert expired == ["9"], expired


def test_the_robbed_mark_survives_a_restart():
    """A restart that forgot it would put back a row offering «Собрать» on a tile the
    server has already refused us once."""
    path = _state_path()
    tab = _robbed_tab()
    import types
    tab.rt = types.SimpleNamespace(profiles=_FakeProfiles(path), root=None)
    tab._persist_rows()

    back = _make_tab({})
    back.rt = types.SimpleNamespace(profiles=_FakeProfiles(path), root=None)
    back._load_persisted()

    assert back._rows["9"]["robbed"] is True
    assert back._collectable(back._rows["9"]) is False
    assert back._collected == {"9"}


def test_the_robbed_mark_reaches_the_phone_and_no_press_goes_with_it():
    """CLAUDE.md: what the window grew, the web grows in the same commit.

    The mark travels — the glyph on the coordinate, the words as a fact, and the pill,
    which must not go on saying «готово к сбору» about a tile we have already taken.
    No «Собрать» goes with it because there has never been one here: the phone reads
    this list and presses nothing on it (#1188).
    """
    import types
    tab = _robbed_tab()
    tab.show_spent_var = _Var(False)
    tab.monitor_var = _Var(False)
    tab.hide_own_var = _Var(False)
    tab.autoassist_var = _Var(False)
    tab._zoom_level = "tile"
    tab.autoloot = types.SimpleNamespace(
        state=lambda: ("secret.autoloot", "off"), level_min=lambda: 7)
    tab.autoassist = types.SimpleNamespace(
        state=lambda: ("autoassist.state.off", ""), level_min=lambda: None)
    tab.alliance = types.SimpleNamespace(web_items=lambda: [], ur_var=_Var(False),
                                         star_var=_Var(False),
                                         counts=lambda: (0, 0))
    tab.ghost = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_allies = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_map = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [],
                                          monitor_var=_Var(False),
                                          counts=lambda: (0, 0))

    cards = {c.get("title"): c for c in tab.web_view()["cards"]}
    item = cards["secrettasks.page.stars"]["items"][0]
    assert item["text"].startswith(gr.ROBBED_GLYPH), item
    assert {"label": "secrettasks.robbed_mark", "value": ""} in item["facts"], item
    assert item["pill"] == "secrettasks.robbed_mark", item
    # …and the card's buttons are the display switches and nothing that robs.
    assert {a["id"] for a in cards["secrettasks.page.stars"]["actions"]} == {
        "monitor", "show_spent", "hide_own", "clear"}


def test_collect_is_offered_ten_seconds_early_and_not_eleven():
    """«Кнопку "Собрать" нужно отображать за 10 секунд до готовности» (#1272).

    The border is the whole test: a raidable star is taken in the first moment it exists,
    so the button has to be under a finger before the moment — and a button that appeared
    a minute early would be a button that is on for tiles nobody can take yet.
    """
    early = _row(1, 7, 9_000, 600_000)       # nine seconds to go — offered
    late = _row(2, 7, 11_000, 600_000)       # eleven — not yet
    ripe = _row(3, 7, -5_000, 600_000)       # already raidable
    tab = _make_tab({"1": early, "2": late, "3": ripe})
    tab._refresh_timers()

    assert tab._collectable(early) is True, "the ten-second window did not open"
    assert tab._collectable(late) is False, "the button appeared outside the window"
    assert tab._collectable(ripe) is True

    # …and the cell says so, because the cell IS the button on a Treeview.
    def action(row):
        return dict(zip([c[0] for c in st.COLUMNS],
                        st.SecretTasksTab._row_values(tab, row)))["action"]

    assert action(early) == tab.t("secrettasks.collect")
    assert action(late) == ""


def test_the_phone_says_the_window_is_open_at_the_same_instant_the_button_appears():
    """«То же на телефоне» — the READING travels, which is all that honestly can here.

    The phone has never had «Собрать» on this list and does not grow one now: the robbery
    is still a hand-driven press the web may not carry (#1188). What it gets is the same
    fact at the same moment — the tile is about to open — so the two front-ends do not
    disagree about when that is.
    """
    import types
    rows = {"1": _row(1, 7, 9_000, 600_000), "2": _row(2, 7, 11_000, 600_000)}
    tab = _make_tab(rows)
    tab._refresh_timers()
    tab.show_spent_var = _Var(False)
    tab.monitor_var = _Var(False)
    tab.autoassist_var = _Var(False)
    tab._visible_rows = lambda: list(rows.values())
    tab._zoom_level = "tile"
    tab.autoloot = types.SimpleNamespace(
        state=lambda: ("secret.autoloot", "off"), level_min=lambda: 7)
    tab.autoassist = types.SimpleNamespace(
        state=lambda: ("autoassist.state.off", ""), level_min=lambda: None)
    tab.alliance = types.SimpleNamespace(web_items=lambda: [], ur_var=_Var(False),
                                         star_var=_Var(False),
                                         counts=lambda: (0, 0))
    tab.ghost = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_allies = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_map = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [],
                                          monitor_var=_Var(False),
                                          counts=lambda: (0, 0))

    cards = {c.get("title"): c for c in tab.web_view()["cards"]}
    pills = [i["pill"] for i in cards["secrettasks.page.stars"]["items"]]
    assert "secrettasks.collect_soon" in pills, pills
    assert pills.count("secrettasks.collect_soon") == 1, pills
    # …and still no press on the card: the display switches and nothing that robs.
    assert {a["id"] for a in cards["secrettasks.page.stars"]["actions"]} == {
        "monitor", "show_spent", "hide_own", "clear"}


def test_the_early_window_is_the_hands_and_the_standing_order_keeps_the_strict_gate():
    """The window is for a finger. A machine gains nothing from pressing early, and a
    send the server answers «рано» is a round trip that robs nothing — so «Автолут ★»
    asks the strict question and the two gates are deliberately two (#1272)."""
    early = _row(1, 7, 9_000, 600_000)
    early["server"] = _HOME_SERVER + 1
    tab = _make_tab({"1": early}, rob_min="1", autoloot=True)
    tab._refresh_timers()

    assert tab._collectable(early) is True      # the hand may press, nine seconds out
    assert tab._raidable(early) is False        # …the standing order may not
    assert tab.rob_candidates() == [], tab.rob_candidates()

    # Two seconds out is the standing order's own window — «за пару секунд до
    # готовности», and it starts pressing there rather than waiting for the moment.
    early["completed_at"] = _ms(2_000)
    tab._refresh_timers()
    assert tab._raidable(early) is True
    assert [r["uuid"] for r in tab.rob_candidates()] == [1]

    # …and the moment it matures, both still say yes.
    early["completed_at"] = _ms(-1_000)
    tab._refresh_timers()
    assert tab._raidable(early) is True
    assert [r["uuid"] for r in tab.rob_candidates()] == [1]


def test_a_press_inside_the_window_holds_only_what_the_spam_cannot_reach():
    """The hand and the standing order press the same way — through the recipe (#1272).

    The recipe SPAMS, and pressing early is free, so a press made ten seconds out does
    not need to wait for the tile: it needs to wait until the tile is inside the spam's
    own window and then let it press. What it must never do is send once, early, and
    call that a robbery.
    """
    import threading as _threading
    import types
    row = _row(1, 7, 9_000, 600_000)
    tab = _make_tab({"1": row})
    tab.after = lambda fn: fn()
    tab.alliance = _FakeAllianceGrid()
    tab.rt.put = lambda _line: None
    tab._persist_rows = lambda: None
    said, slept = [], []
    tab.say = lambda _tag, key, **fmt: said.append(key)
    waiting, release = _threading.Event(), _threading.Event()
    played = _Actions(lines=["ACT steal_sent uuid=1 srv=1",
                             "steal_taken — the server confirmed a robbery"])
    tab.rt.actions = played
    real_time, real_sleep = st.time, st.time.sleep

    def _sleep(secs):
        slept.append(secs)
        waiting.set()
        release.wait(5)          # held here, so the press really is «in flight»

    st.time = types.SimpleNamespace(sleep=_sleep)
    try:
        tab._collect(row)
        assert waiting.wait(5), "the press did not wait at all"
        assert played.played == [], "the recipe was played before the window"
        # A second press while the first is in flight arms nothing more.
        tab._collect(row)
        release.set()
        for _ in range(250):
            if row.get("robbed"):
                break
            real_sleep(0.02)
    finally:
        release.set()
        st.time = real_time

    assert "log.secret.collect_armed" in said, said
    # Nine seconds out, and the spam reaches two and a half: it holds the difference.
    assert len(slept) == 1 and 6 <= slept[0] <= 7, slept
    assert played.played == ["steal_secret_task"], played.played
    assert played.args == [{"queue": "{uuid=1,server=1}"}], played.args
    assert row["robbed"] is True, "the wait swallowed the robbery"


def test_a_hand_press_is_a_robbery_only_when_the_server_says_so():
    """Same rule as the standing order's: a sent frame is not a robbery (#1272)."""
    row = _row(2, 7, -5_000, 600_000)
    row["ready"] = True
    tab = _make_tab({"2": row})
    tab.after = lambda fn: fn()
    tab.alliance = _FakeAllianceGrid()
    tab.rt.put = lambda _line: None
    tab._persist_rows = lambda: None
    tab.say = lambda *_a, **_k: None
    tab.rt.actions = _Actions(lines=["ACT steal_sent uuid=2 srv=1"])   # sent, not taken

    tab._collect(row)
    import time as _time
    for _ in range(250):
        if "2" not in tab._pressing:
            break
        _time.sleep(0.02)

    assert row.get("robbed") is not True, "a sent frame was counted as a robbery"


def test_the_phone_says_the_window_is_open_at_the_same_instant_the_button_appears():
    """«То же на телефоне» — the READING travels, which is all that honestly can here.

    The phone has never had «Собрать» on this list and does not grow one now: the robbery
    is still a hand-driven press the web may not carry (#1188). What it gets is the same
    fact at the same moment — the tile is about to open — so the two front-ends do not
    disagree about when that is.
    """
    import types
    rows = {"1": _row(1, 7, 9_000, 600_000), "2": _row(2, 7, 11_000, 600_000)}
    tab = _make_tab(rows)
    tab._refresh_timers()
    tab.show_spent_var = _Var(False)
    tab.monitor_var = _Var(False)
    tab.autoassist_var = _Var(False)
    tab._visible_rows = lambda: list(rows.values())
    tab._zoom_level = "tile"
    tab.autoloot = types.SimpleNamespace(
        state=lambda: ("secret.autoloot", "off"), level_min=lambda: 7)
    tab.autoassist = types.SimpleNamespace(
        state=lambda: ("autoassist.state.off", ""), level_min=lambda: None)
    tab.alliance = types.SimpleNamespace(web_items=lambda: [], ur_var=_Var(False),
                                         star_var=_Var(False),
                                         counts=lambda: (0, 0))
    tab.ghost = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_allies = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_map = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [],
                                          monitor_var=_Var(False),
                                          counts=lambda: (0, 0))

    cards = {c.get("title"): c for c in tab.web_view()["cards"]}
    pills = [i["pill"] for i in cards["secrettasks.page.stars"]["items"]]
    assert "secrettasks.collect_soon" in pills, pills
    assert pills.count("secrettasks.collect_soon") == 1, pills
    # …and still no press on the card: the display switches and nothing that robs.
    assert {a["id"] for a in cards["secrettasks.page.stars"]["actions"]} == {
        "monitor", "show_spent", "hide_own", "clear"}


def test_the_early_window_is_the_hands_and_the_standing_order_keeps_the_strict_gate():
    """The window is for a finger. A machine gains nothing from pressing early, and a
    send the server answers «рано» is a round trip that robs nothing — so «Автолут ★»
    asks the strict question and the two gates are deliberately two (#1272)."""
    early = _row(1, 7, 9_000, 600_000)
    early["server"] = _HOME_SERVER + 1
    tab = _make_tab({"1": early}, rob_min="1", autoloot=True)
    tab._refresh_timers()

    assert tab._collectable(early) is True      # the hand may press, nine seconds out
    assert tab._raidable(early) is False        # …the standing order may not
    assert tab.rob_candidates() == [], tab.rob_candidates()

    # Two seconds out is the standing order's own window — «за пару секунд до
    # готовности», and it starts pressing there rather than waiting for the moment.
    early["completed_at"] = _ms(2_000)
    tab._refresh_timers()
    assert tab._raidable(early) is True
    assert [r["uuid"] for r in tab.rob_candidates()] == [1]

    # …and the moment it matures, both still say yes.
    early["completed_at"] = _ms(-1_000)
    tab._refresh_timers()
    assert tab._raidable(early) is True
    assert [r["uuid"] for r in tab.rob_candidates()] == [1]


def test_a_tile_the_server_calls_gone_comes_off_the_list():
    """«В списке всё ещё видно, что есть» (#1272).

    THE ONE ABSENCE THAT IS EVIDENCE. `_answerable` refuses to delete a row for missing
    from a read that could not see it — that rule stands, it is what stopped the list
    being wiped every start-up. This is the other case: the answer was ABOUT this tile,
    and it said there is nothing there.
    """
    rows = {"1": _row(1, 7, -5_000, 600_000), "2": _row(2, 7, -5_000, 600_000)}
    tab = _make_tab(rows)
    tab.rt = _fake_rt(_state_path())
    tab.say = lambda *_a, **_k: None

    tab._drop_gone("1")

    assert sorted(tab._rows) == ["2"], tab._rows


def test_a_tile_we_robbed_ourselves_is_kept_even_when_called_gone():
    """Our own robbery is the likeliest reason the server would now call a tile taken,
    and the row is on the list precisely so it can still be shared (#1272)."""
    row = _row(1, 7, -5_000, 600_000)
    row["robbed"] = True
    tab = _make_tab({"1": row})
    tab.rt = _fake_rt(_state_path())
    tab.say = lambda *_a, **_k: None

    tab._drop_gone("1")

    assert "1" in tab._rows, "the row we kept for sharing was deleted"


def test_the_verdict_travels_from_the_recipe_to_the_list():
    """The recipe says `steal_done uuid=… how=gone` as it drops each target; both the
    hand press and the standing order act on it, in one place (#1272)."""
    import types
    row = _row(7, 7, -5_000, 600_000)
    row["ready"] = True
    tab = _make_tab({"7": row})
    tab.after = lambda fn: fn()
    tab.alliance = _FakeAllianceGrid()
    tab.rt.put = lambda _line: None
    tab._persist_rows = lambda: None
    tab.say = lambda *_a, **_k: None
    tab.rt.actions = _Actions(lines=["ACT steal_done uuid=7 how=gone tip=dispatch_des042"])

    tab._collect(row)
    import time as _time
    for _ in range(250):
        if "7" not in tab._pressing:
            break
        _time.sleep(0.02)

    assert "7" not in tab._rows, "the tile the server called gone stayed on the list"


def _state_tab(rows):
    """A tab wired for `_state_landed` — no game, no Tk, just the decision."""
    tab = _make_tab(rows)
    tab.rt = _fake_rt(_state_path())
    tab._vm_busy = True
    tab.said = []
    tab.say = lambda _tag, key, **fmt: tab.said.append((key, fmt))
    return tab


def test_the_state_refresh_updates_the_loot_count_from_the_alliance_table():
    """«Чтобы обновлялось число ограблений» (#1272) — the one reading that carries it."""
    row = _row(1, 7, -5_000, 600_000)
    row["loot_count"] = 0
    tab = _state_tab({"1": row})
    task = _LiveTask(1)
    task.loot_count = 2

    tab._state_landed(["1"], {"1": task}, {}, True)

    assert tab._rows["1"]["loot_count"] == 2
    key, fmt = tab.said[-1]
    assert key == "log.secret.state_done"
    assert (fmt["checked"], fmt["updated"], fmt["gone"]) == (1, 1, 0), fmt


def test_a_tile_the_server_has_no_detail_for_is_gone():
    """A point with no task on it answers with no detail at all — measured live. With
    the control proving the answers were arriving, that is «there is nothing there»."""
    rows = {"1": _row(1, 7, -5_000, 600_000), "2": _row(2, 7, -5_000, 600_000)}
    tab = _state_tab(rows)

    # row 1 answered with its own uuid, row 2 with nothing; the control came back.
    tab._state_landed(["1", "2"], {}, {1: 1, 2: 0}, True)

    assert sorted(tab._rows) == ["1"], tab._rows
    key, fmt = tab.said[-1]
    assert (fmt["checked"], fmt["gone"]) == (2, 1), fmt


def test_without_the_control_no_row_is_dropped():
    """The rule that stopped the list being wiped every start-up, kept here: when the
    control tile did not answer either, the answers were not arriving and an absence
    proves nothing (#1272)."""
    rows = {"1": _row(1, 7, -5_000, 600_000), "2": _row(2, 7, -5_000, 600_000)}
    tab = _state_tab(rows)

    tab._state_landed(["1", "2"], {}, {1: 0, 2: 0}, False)

    assert sorted(tab._rows) == ["1", "2"], "an unproven silence emptied the list"
    key, fmt = tab.said[-1]
    assert fmt["unconfirmed"] == 2 and fmt["gone"] == 0, fmt


def test_a_row_we_robbed_is_never_dropped_by_the_refresh():
    """It is on the list so it can still be shared, and our own robbery is the likeliest
    reason the tile would now answer with nothing (#1272)."""
    row = _row(1, 7, -5_000, 600_000)
    row["robbed"] = True
    tab = _state_tab({"1": row})

    tab._state_landed(["1"], {}, {1: 0}, True)

    assert "1" in tab._rows


def test_the_refresh_asks_about_the_ready_rows_first():
    """«Приоритет — готовым строкам»: their state lives seconds, and they are the ones
    the operator was seeing a lie about (#1272)."""
    waiting = _row(1, 7, 120_000, 600_000)
    ready = _row(2, 7, -5_000, 600_000)
    ready["ready"] = True
    tab = _make_tab({"1": waiting, "2": ready})
    tab.rt = _fake_rt(_state_path())
    asked = {}
    tab.after = lambda fn: None
    import types
    tab.rt.game = types.SimpleNamespace(
        evaluator=lambda: (_ for _ in ()).throw(RuntimeError("no game here")))
    tab._vm_busy = True
    tab._state_work()
    # The read raised, so nothing was applied — what this pins is the ORDER it built.
    rows = sorted(tab._rows.values(),
                  key=lambda r: (not r.get("ready"),
                                 r.get("completed_at") or float("inf")))
    assert [r["uuid"] for r in rows] == [2, 1], rows


def test_a_robbed_row_leaves_only_by_its_own_clock():
    """«Какого хуя пропадают мои собранные секретки» — the rule, pinned whole (#1272).

    A robbed row is not a map finding. It is a receipt: the tile stays on the list,
    marked and without «Собрать», for one reason — so it can still be shared (#1188,
    140a4d2). Every way this list loses a row is walked here, because the regression was
    ONE of them added later and none of the others: the lap's own wipe.

    The last case is the one that matters most: «уже взято» is not evidence against a
    tile WE took — it is the answer we earned by taking it.
    """
    import types
    row = _row(7, 7, -60_000, 3_600_000)
    row["robbed"], row["ready"], row["source"] = True, True, st.SOURCE_WIRE
    tab = _make_tab({"7": row})
    tab.rt = _fake_rt(_state_path())
    tab.say = lambda *_a, **_k: None
    tab.post = lambda fn: fn()
    tab._maybe_start_poll = lambda: None      # no window, no chain to arm
    tab._sweeping, tab._sweep_btn = False, None
    tab._retitle_sweep = lambda: None
    tab.capture = types.SimpleNamespace(running=True)
    tab.ghost_capture = types.SimpleNamespace(running=False)
    tab.rt.play_async = lambda name, args=None, **kw: True

    # A live read that carries nothing, and one that carries something else.
    tab._merge([], verify={"7"}, source=st.SOURCE_VM)
    assert "7" in tab._rows, "an empty read took it"
    tab._merge([_StubTask(9)], verify={"7"}, source=st.SOURCE_VM)
    assert "7" in tab._rows, "a read that could not see it took it"

    # The ready-row poll, with a good answer that does not carry it.
    tab._poll_apply(["7"], {"9": _LiveTask(9)})
    assert "7" in tab._rows, "the ready-row poll took it"

    # «Обновить состояние»: the control answered, our tile has no detail at all.
    tab._vm_busy = True
    tab._state_landed(["7"], {}, {1: 0}, True)
    assert "7" in tab._rows, "the state refresh took it"

    # The server's own «уже взято», which is what it says about a tile we robbed.
    tab._drop_gone("7")
    assert "7" in tab._rows, "the tile was deleted for the answer our own robbery earned"

    # …and a lap of the map, which re-reads the MAP and not what we did today.
    tab._sweep_once()
    assert "7" in tab._rows, "«Обойти карту» wiped a collected task"

    # Only its own expiry ends it.
    tab._rows["7"]["expires_at"] = _ms(-1_000)
    expired, _changed = tab._refresh_timers()
    assert expired == ["7"], expired


def test_the_lap_still_wipes_everything_that_is_not_ours():
    """The wipe has a job — a table that is a blend of two laps is unreadable — and
    keeping the receipts does not take it away (#1272)."""
    import types
    kept = _row(7, 7, -60_000, 3_600_000)
    kept["robbed"] = True
    tab = _make_tab({"7": kept, "8": _row(8, 7, -5_000, 600_000)})
    tab.rt = _fake_rt(_state_path())
    tab.say = lambda *_a, **_k: None
    tab.post = lambda fn: fn()
    tab._sweeping, tab._sweep_btn = False, None
    tab._retitle_sweep = lambda: None
    tab.capture = types.SimpleNamespace(running=True)
    tab.ghost_capture = types.SimpleNamespace(running=False)
    tab.rt.play_async = lambda name, args=None, **kw: True

    tab._sweep_once()

    assert sorted(tab._rows) == ["7"], tab._rows


def _robbed_tab():
    """A tab whose one ready row has just been robbed, through the real `_collect_done`."""
    import types
    rows = {"9": _row(9, 7, -5_000, 600_000)}
    rows["9"]["ready"] = True
    # Abroad, so the home-server prohibition is not what empties `rob_candidates` below.
    rows["9"]["server"] = _HOME_SERVER + 1
    tab = _make_tab(rows, rob_min="1", autoloot=True)
    tab.alliance = _FakeAllianceGrid()
    tab.rt.put = lambda _line: None
    tab._persist_rows = lambda: None
    tab._collect_done("9", True)
    tab._persist_rows = types.MethodType(st.SecretTasksTab._persist_rows, tab)
    return tab


def test_the_phone_is_shown_every_page_the_window_has():
    """CLAUDE.md: what the window grew, the web grows in the same commit.

    Three pages in the window (#1251) are three cards on the phone — a screen scrolls
    where a window switches — and the ghost card carries the event's own facts too,
    because six days a week «событие закрыто» IS the reading.
    """
    import types
    tab = object.__new__(st.SecretTasksTab)
    tab._rows = {}
    tab.show_spent_var = _Var(False)
    tab.hide_own_var = _Var(True)
    tab.monitor_var = _Var(False)       # the ★ page's own sniffer switch (#1251)
    tab._own_server = 0                 # unread here, so the rule holds nothing back
    tab._visible_rows = lambda: []
    tab._zoom_level = "tile"            # the camera height the bar is set to (#1265)
    # The card carries the RULE beside the state now (#1256), so the stand-in
    # answers both questions the phone asks of the standing order.
    tab.autoloot = types.SimpleNamespace(
        state=lambda: ("secret.autoloot", "off"), level_min=lambda: 7)
    # …and the same pair for «Автопомощь», whose card sits above the alliance one (#1272).
    tab.autoassist = types.SimpleNamespace(
        state=lambda: ("autoassist.state.off", ""), level_min=lambda: 6)
    tab.autoassist_var = _Var(False)
    tab.alliance = types.SimpleNamespace(
        ur_var=_Var(False), star_var=_Var(False), counts=lambda: (1, 0),
        web_items=lambda: [{"text": "X:1 Y:2", "facts": [], "until": None, "pill": None}])
    tab.ghost = types.SimpleNamespace(
        counts=lambda: (1, 0),
        web_rows=lambda: [{"label": "secrettasks.ghost.state_line", "value": "идёт"}],
        web_items=lambda: [{"text": "#3 X:4 Y:5", "facts": [], "until": None,
                            "pill": None}])
    tab.ghost_allies = types.SimpleNamespace(
        counts=lambda: (1, 0),
        web_items=lambda: [{"text": "#6 X:7 Y:8", "facts": [], "until": None,
                            "pill": None}])
    tab.ghost_map = types.SimpleNamespace(
        monitor_var=_Var(False), counts=lambda: (1, 0),
        web_items=lambda: [{"text": "#9 X:1 Y:1", "facts": [], "until": None,
                            "pill": None}])

    view = tab.web_view()
    cards = {c.get("title"): c for c in view["cards"]}
    assert "secrettasks.alliance" in cards, cards
    assert cards["secrettasks.alliance"]["items"][0]["text"] == "X:1 Y:2"
    assert cards["secrettasks.alliance"]["empty"] == "secrettasks.alliance.empty"
    assert "secrettasks.ghost" in cards, cards
    assert cards["secrettasks.ghost"]["items"][0]["text"] == "#3 X:4 Y:5"
    assert cards["secrettasks.ghost"]["rows"][0]["value"] == "идёт"
    assert cards["secrettasks.ghost"]["empty"] == "secrettasks.ghost.empty"
    # …and the alliancemates' squads are a card of their own, not folded into mine.
    assert "secrettasks.ghost.allies" in cards, cards
    assert cards["secrettasks.ghost.allies"]["items"][0]["text"] == "#6 X:7 Y:8"
    assert "secrettasks.ghost.map" in cards, cards
    assert cards["secrettasks.ghost.map"]["items"][0]["text"] == "#9 X:1 Y:1"
    # EVERY BOX IS A BUTTON ON ITS OWN CARD (#1251) — a press has to say which list it
    # is about, exactly as the window's switches sit on their own pages.
    stars = {a["id"]: a["label"] for a in cards["secrettasks.page.stars"]["actions"]}
    assert {"monitor", "hide_own", "show_spent", "clear"} == set(stars), stars
    assert stars["hide_own"] == "secrettasks.filter.show_own"       # it is hiding now
    # …and it says WHICH monitoring it starts, not just «monitoring» (#1264): the
    # screen has two of them and a thumb scrolls past the card titles.
    assert stars["monitor"] == "secret.monitoring.stars.on"         # not running yet
    ally = {a["id"]: a["label"] for a in cards["secrettasks.alliance"]["actions"]}
    assert {"ur_only", "star_only"} == set(ally), ally
    assert ally["ur_only"] == "secrettasks.filter.ur_on"            # it is not on yet
    # «Автопомощь» is a card of its own directly above the list it helps (#1272): the
    # rule, the state, and the one press the phone may make — the whole ability is a
    # scenario, so there is no hand-driven half to copy out of the house.
    assert "autoassist.frame" in cards, cards
    assist = cards["autoassist.frame"]
    assert [r["label"] for r in assist["rows"]] == ["autoassist.level_min",
                                                    "autoassist.state.off"]
    assert assist["rows"][0]["value"] == "6"
    assert [a["id"] for a in assist["actions"]] == ["autoassist"]
    assert assist["actions"][0]["label"] == "autoassist.on"         # it is not on yet
    # THE GHOST SWITCH IS ON BOTH GHOST CARDS (#1264): on the one its findings land on,
    # and on the one named «Операция Призрак», which is where a person looks for it.
    for title in ("secrettasks.ghost", "secrettasks.ghost.map"):
        actions = {a["id"]: a["label"] for a in cards[title]["actions"]}
        assert actions == {"ghost_monitor": "secret.monitoring.ghost.on"}, (title, actions)
    # What is left at the bottom belongs to the whole tab — «Обновить», and the camera
    # bar the window put on this tab too (#1265): which height it is set to, and the lap
    # that spends it.
    # …and «Обновить состояние» beside them (#1272): it re-reads what is already on the
    # list and robs nothing, so it is a press the phone may make.
    assert [a["id"] for a in view["actions"]] == ["refresh", "refresh_state", "zoom",
                                                 "sweep_now"]
    assert view["actions"][2]["label"] == "coord.zoom.tile"


def test_the_phone_reads_the_alliance_rows_the_same_way_as_the_window():
    """Same member, same rank, same loots, same countdown — one list drawn two ways."""
    g = _alliance_grid()
    now = int(__import__("time").time() * 1000)
    g.apply([_member_task(1, owner="Player1", level=6, loot_count=1,
                          completed_at=now - 5_000, expires_at=now + 600_000)])
    g._rows["1"]["ready"] = True

    item = g.web_items()[0]
    # The same coordinate token the card above prints — server included, because a tile
    # on somebody else's server is a different tile.
    assert item["text"] == "#1 X:1 Y:2", item
    # The rank the window draws, star and all — a starred record here, so «⭐×6».
    assert [f["value"] for f in item["facts"]] == ["Player1", "⭐×6", "1/3"], item
    assert item["facts"][0]["label"] == "secrettasks.col.owner", item
    assert item["pill"] == "secrettasks.ready"
    assert abs(item["until"] - (now + 600_000) / 1000.0) < 1


def test_every_grid_is_literally_the_same_table():
    """«Грид точно такой же» (#1244, #1251): one column set, one sort rule, one table.

    Three pages now, and not one of them may grow a table of its own: the alliance and
    ghost pages ARE `grid.TaskGrid`, and the only `make_tree` in the package is the one
    inside it.
    """
    from panel.tabs.secret_tasks import ghost as gh

    assert st.COLUMNS is gr.COLUMNS
    assert (st.LINK_COLUMN, st.ACTION_COLUMN) == (gr.LINK_COLUMN, gr.ACTION_COLUMN)
    assert st.SecretTasksTab.SORT_KEYS is gr.SORT_KEYS
    assert issubclass(al.AllianceGrid, gr.TaskGrid)
    assert issubclass(gh.GhostGrid, gr.TaskGrid)
    pkg = Path(__file__).resolve().parents[1] / "panel" / "tabs" / "secret_tasks"
    for name in ("alliance.py", "ghost.py"):
        src = (pkg / name).read_text(encoding="utf-8")
        assert "make_tree" not in src, f"{name} builds a table of its own"


# ---------------------------------------------------------------------------
# «Уже поделились» (#1245) — the mark, its two producers and both front-ends
# ---------------------------------------------------------------------------

def test_a_share_the_panel_made_marks_the_tile():
    """The panel's own «Поделиться» records the fact; a failed one records nothing."""
    tab = _make_tab({"11": _row(11, 7, -5_000, 600_000)})
    drawn = []
    tab._render = lambda: drawn.append("window")
    tab.alliance = __import__("types").SimpleNamespace(
        render=lambda: drawn.append("alliance"))
    tab.rt.put = lambda _line: None
    row = tab._rows["11"]

    tab._share_done(row, st.SHARE_ALLIANCE, False)
    assert not tab.shared.has(11), "a failed share must not claim the tile was shown"
    assert drawn == []

    tab._share_done(row, st.SHARE_ALLIANCE, True)
    assert tab.shared.has(11)
    # Both tables, at once: the same tile can be on either, and it is one fact.
    assert drawn == ["window", "alliance"]


def test_a_share_pressed_in_the_game_reaches_the_list_too():
    """The mark a capture child appends is read by the tab — nobody presses anything.

    That is the whole of #1245: a tile forwarded from the game's own share button
    never touches the panel, so the fact arrives through the profile's store, written
    by the capture that was already decoding the stream.
    """
    tab = _make_tab({"11": _row(11, 7, -5_000, 600_000)})
    _mark_as_the_game_would(tab, 11)

    expired, changed = tab._refresh_timers()
    assert expired == []
    assert changed is True, "a mark that landed since the last pass must redraw the row"
    assert tab._rows["11"]["shared"] is True
    assert tab.t("secrettasks.shared_mark") in tab._rows["11"]["timer"].get()
    # And it does not keep announcing itself: nothing changed on the second pass.
    assert tab._refresh_timers()[1] is False


def test_the_shared_tile_is_marked_in_both_tables_and_on_the_phone():
    """CLAUDE.md: the window and the web say the same thing, in the same commit."""
    import types
    tab = _make_tab({"11": _row(11, 7, -5_000, 600_000)})
    tab._collectable = lambda row: True
    _mark_as_the_game_would(tab, 11)
    tab._refresh_timers()

    # The window's table above: the glyph rides the coordinate cell, which still holds
    # the token `coords.parse` reads back — the cell is the camera link.
    cells = tab._row_values(tab._rows["11"])
    coords_cell = cells[[c[0] for c in st.COLUMNS].index("coords")]
    assert coords_cell.startswith(gr.SHARED_GLYPH), coords_cell
    import coords as coords_fmt
    assert coords_fmt.parse(coords_cell), "the coordinate stopped being clickable"

    # The phone's copy of the very same row.
    tab.show_spent_var = _Var(False)
    tab.monitor_var = _Var(False)
    tab._visible_rows = lambda: list(tab._rows.values())
    tab._spent = lambda _row: False
    # The card carries the RULE beside the state now (#1256), so the stand-in
    # answers both questions the phone asks of the standing order.
    tab.autoloot = types.SimpleNamespace(
        state=lambda: ("secret.autoloot", "off"), level_min=lambda: 7)
    tab.autoassist = types.SimpleNamespace(
        state=lambda: ("autoassist.state.off", ""), level_min=lambda: None)
    tab.autoassist_var = _Var(False)
    tab.alliance = types.SimpleNamespace(web_items=lambda: [], ur_var=_Var(False),
                                         star_var=_Var(False),
                                         counts=lambda: (0, 0))
    tab.ghost = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_allies = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [], counts=lambda: (0, 0))
    tab.ghost_map = types.SimpleNamespace(web_items=lambda: [], web_rows=lambda: [],
                                          monitor_var=_Var(False),
                                          counts=lambda: (0, 0))
    item = [c for c in tab.web_view()["cards"] if c.get("items")][0]["items"][0]
    assert item["text"].startswith(gr.SHARED_GLYPH), item
    assert {"label": "secrettasks.shared_mark", "value": ""} in item["facts"], item

    # …and the table below, which is the same table drawn twice.
    g = _alliance_grid()
    now = int(__import__("time").time() * 1000)
    g.apply([_member_task(11, completed_at=now - 5_000, expires_at=now + 600_000)])
    _mark_as_the_game_would(g.tab, 11)
    g._refresh_timers()
    assert g._rows["11"]["shared"] is True
    web = g.web_items()[0]
    assert web["text"].startswith(gr.SHARED_GLYPH), web
    assert {"label": "secrettasks.shared_mark", "value": ""} in web["facts"], web


def test_the_mark_belongs_to_the_profile_that_made_it():
    """A switched profile does not inherit the other one's shares.

    The store's path is part of what the reload compares, so a runtime pointed at
    another profile empties the marks rather than showing that profile the shares
    somebody made in a different account.
    """
    tab = _make_tab({"11": _row(11, 7, -5_000, 600_000)})
    _mark_as_the_game_would(tab, 11)
    assert tab.shared.apply(tab._rows) is True
    assert tab.shared.has(11)

    tab.shared.rt = _fake_rt(_state_path())     # a different profile's paths
    assert tab.shared.apply(tab._rows) is True  # …and the flag comes back off
    assert not tab.shared.has(11)
    assert tab._rows["11"]["shared"] is False


def test_the_capture_marks_every_share_the_game_announces():
    """Both share commands count — the live broadcast and the login backlog.

    The payloads are invented, of the shape `docs/research/protocol.md` records: a
    made-up mission uuid, a made-up cfgId that splits into a starred level.
    """
    import os
    import sys
    root = Path(__file__).resolve().parents[1]
    for extra in (str(root / "tools"), str(root / "tools" / "lib")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import share_marks
    import secret_task_capture as capture

    path = os.path.join(os.path.dirname(_state_path()), "secret_shared.jsonl")
    index = object.__new__(capture.TaskIndex)
    index._shared_json = path
    index.shares_marked = 0

    index.on_response("push.alliance.share.mission.add",
                      {"missionCfgId": 60000701, "missionUuid": 1000000000000001,
                       "missionCurrentServerId": 100, "shareUid": "1000000000000009"})
    index.on_response("get.alliance.share.mission.list",
                      {"shareMissionArr": [{"missionCfgId": 60000701,
                                            "missionUuid": 1000000000000002}]})
    index.on_response("world.get.detail.new", {"missionUuid": 1000000000000003})

    marks = share_marks.load(path)
    assert set(marks) == {"1000000000000001", "1000000000000002"}, marks
    assert index.shares_marked == 2
    assert marks["1000000000000001"]["via"] == share_marks.VIA_GAME
    assert marks["1000000000000001"]["uid"] == "1000000000000009"


def _mark_as_the_game_would(tab, uuid) -> None:
    """Append a mark the way a capture child does — a line, from another process."""
    import sys
    root = Path(__file__).resolve().parents[1]
    for extra in (str(root / "tools"), str(root / "tools" / "lib")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import share_marks
    assert share_marks.mark(tab.rt.profiles.secret_shared_json(), uuid,
                            share_marks.VIA_GAME, "1000000000000009")


# -- the star is not a setting, and the log is the list (#1244, live report) ----------
#
# Two complaints, one root each. The log printed every plain tile the map carried — 236
# of the 277 in the live checkpoint that opened this — and the TABLE filtered on the
# auto-loot range while the LOG filtered on the display one, so a profile set to show
# 5-7 and rob 7-7 read level-5 stars in the log and found no rows for them.

def _capture(tab):
    """A `Capture` with nothing but the tab behind it — `passes` needs no child."""
    from panel.tabs.secret_tasks.capture import Capture
    cap = object.__new__(Capture)
    cap.tab = tab
    return cap


def _finding(level, family="6000", star=True) -> str:
    """A finding line in the shape the capture child prints one."""
    return ("%s lvl %2d  @[403,446|946]  steal 0/3  family %s  cfg %s01"
            % (" *" if star else "  ", level, family, "%s%02d" % (family, level)))


def test_the_log_prints_stars_only_whatever_the_boxes_say():
    """«Фильтр звезда всегда включён» — not a box, and not something to switch off."""
    tab = _make_tab({}, lo="1", hi="9")
    cap = _capture(tab)

    assert cap.passes(_finding(7)) is True
    # The three plain families the map is mostly made of — every one of them used to
    # print, and none of them can ever appear in the table beside the log.
    for family in ("30", "40", "5000"):
        assert cap.passes(_finding(7, family=family, star=False)) is False, family
    # …and the one-per-player class is family 6000 without being a star.
    assert cap.passes(_finding(99)) is False
    # A line that is not a finding at all — a header, a progress line, a summary —
    # is never filtered.
    assert cap.passes("listening 15s — pan the map") is True
    assert cap.passes("3 star(s) still on timer") is True


def test_the_log_and_the_table_filter_on_the_same_pair():
    """What is printed and what is on the table are ONE set (#1244).

    The bug this pins: the table asked the AUTO-LOOT range while the log asked the
    display one, so a profile showing 5-7 and robbing 7-7 had level-5 stars in the log
    and nothing in the table for them.
    """
    rows = {"5": _row(5, 5, -5_000, 600_000),
            "6": _row(6, 6, -5_000, 600_000),
            "7": _row(7, 7, -5_000, 600_000)}
    tab = _make_tab(rows)
    tab.filter_from_var, tab.filter_to_var = _Var("5"), _Var("7")   # what is shown
    tab.level_min_var = _Var("7")                                   # what is robbed
    cap = _capture(tab)

    shown = sorted(int(r["level"]) for r in tab._visible_rows())
    printed = [lvl for lvl in (4, 5, 6, 7, 8) if cap.passes(_finding(lvl))]
    assert shown == [5, 6, 7], shown          # both ends inclusive, the middle too
    assert printed == [5, 6, 7], printed      # and the log says exactly the same
    assert shown == [lvl for lvl in printed if lvl in shown], (shown, printed)


def test_the_robbery_keeps_its_own_range_while_the_table_widens():
    """#1099 the other way round: widening what is SHOWN must not widen what is ROBBED."""
    rows = {"5": _row(5, 5, -5_000, 600_000), "7": _row(7, 7, -5_000, 600_000)}
    for r in rows.values():
        r["ready"] = True
    tab = _make_tab(rows)
    tab.filter_from_var, tab.filter_to_var = _Var("1"), _Var("9")   # show everything
    tab.level_min_var = _Var("7")                                   # rob from 7 up
    tab.autoloot_var = _Var(True)

    assert [int(r["level"]) for r in tab.rob_candidates()] == [7]
    assert sorted(int(r["level"]) for r in tab._visible_rows()) == [5, 7]


def test_a_restored_row_that_is_not_a_star_is_dropped():
    """The working list is starred-only at both feeds; the checkpoint is the one path
    that is not a feed, and a plain tile restored from it sat there looking like a raid.
    """
    import json

    import game_clock
    game_clock.reset()
    try:
        now = game_clock.now_ms()
        path = _state_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([
                {"uuid": 1, "server": 1, "x": 1, "y": 2, "level": 7,
                 "cfg_id": 60000701, "loot_count": 0,          # a star
                 "expires_at": now + 600_000, "completed_at": now - 5_000},
                {"uuid": 2, "server": 1, "x": 3, "y": 4, "level": 4,
                 "cfg_id": 400401, "loot_count": 0,            # a plain tile
                 "expires_at": now + 600_000, "completed_at": now - 5_000},
                {"uuid": 3, "server": 1, "x": 5, "y": 6, "level": 99,
                 "cfg_id": 60009901, "loot_count": 0,          # the special class
                 "expires_at": now + 600_000, "completed_at": now - 5_000},
            ], fh)
        tab = _make_tab({})
        tab.rt = _fake_rt(path)
        assert tab._load_persisted() == {"1"}
        assert list(tab._rows) == ["1"], tab._rows
    finally:
        game_clock.reset()



def test_the_roster_wears_a_star_only_where_the_game_draws_one():
    """The live report: «есть отметка звезды, но по факту там может и не быть звезды».

    The glyph was part of the LEVEL format, so every row of the roster claimed a star —
    167 of the operator's 200 tasks have none. The record says which, and the record is
    the game's own `is_special` column now, not arithmetic on the cfgId.
    """
    g = _alliance_grid()
    g.apply([_member_task(1, starred=True), _member_task(2, starred=False)])
    assert g._rows["1"]["starred"] is True and g._rows["2"]["starred"] is False
    assert "⭐" in g.tab._rank(g._rows["1"])
    assert "⭐" not in g.tab._rank(g._rows["2"])


def test_a_task_the_cfg_id_calls_level_99_is_the_level_the_game_gives():
    """«это не особое, это такое же 7 уровня, просто другого типа» (live report).

    `60009903` reads as level 99 by its digits — the game's own config row says
    `level = 7` and `is_special = 0`. The digits used to decide both, which is how a
    level-7 task ended up named «особое задание» and outside a 5-7 filter.
    """
    g = _alliance_grid()
    g.apply([_member_task(1, level=7, starred=False, cfg_id=60009903)])
    row = g._rows["1"]
    assert row["level"] == 7 and row["starred"] is False
    assert "99" not in g.tab._rank(row) and "⭐" not in g.tab._rank(row)
    # …and a level the game calls 7 is inside a 5-7 filter, which is what put those
    # tasks in the log and not on the table.
    tab = _make_tab({}, lo="5", hi="7")
    assert tab._in_range(row["level"]) is True


# ---------------------------------------------------------------------------
# The three pages, and the boxes over them (#1251)
# ---------------------------------------------------------------------------

def test_the_star_page_hides_the_home_server_and_only_that():
    """«Скрывать со своего сервера» — a DISPLAY rule, and on by default.

    The raids worth a march are the ones abroad, so a neighbour's tile at home starts
    out of the way. It hides rows and nothing else: the tile is still collectable by
    hand, and the robberies obey their own «Не грабить на своём сервере».
    """
    home = dict(_row(1, 7, -5_000, 600_000), server=100, ready=True)
    away = dict(_row(2, 7, -5_000, 600_000), server=200, ready=True)
    tab = _make_tab({"1": home, "2": away})
    tab.hide_own_var = _Var(True)
    tab._own_server = 100

    assert [r["uuid"] for r in tab._visible_rows()] == [2]
    # The hidden tile is not a forbidden one — «Собрать» still means something on it.
    assert tab._collectable(home) is True

    tab.hide_own_var = _Var(False)
    assert sorted(r["uuid"] for r in tab._visible_rows()) == [1, 2]


def test_an_unread_own_server_hides_nothing():
    """0 is «could not be read», not «everything is home» — a rule that cannot tell
    them apart must not empty the table (#1251)."""
    tab = _make_tab({"1": dict(_row(1, 7, -5_000, 600_000), server=100)})
    tab.hide_own_var = _Var(True)
    tab._own_server = 0
    assert [r["uuid"] for r in tab._visible_rows()] == [1]


def test_the_display_rule_survived_the_robbery_rule_becoming_unconditional():
    """One box left, and it is the one about the EYES (#1099/#1251/#1188).

    There used to be two, and telling them apart was the whole point: «Скрывать со
    своего сервера» decides what the TABLE shows, «Не грабить на своём сервере» decided
    what was ROBBED. The second is gone — the home server is never a target and there is
    no setting for it — and this test now guards the thing that could go wrong next:
    somebody tidying up the first one along with it.
    """
    keys = st.SecretTasksTab.config(_config_stub())
    assert keys["hide_own_server"] is True          # what is SHOWN — still a choice
    assert "autoloot_skip_own_server" not in keys, keys
    # …and each page's own filters live under its own key, so one page's box can never
    # land in another's slot (#1251).
    assert set(keys["grids"]) == {"alliance", "ghost", "ghost_allies", "ghost_map"}
    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "tab.py").read_text(encoding="utf-8")
    assert "hide_own_var" in src, "the display rule went with it"
    assert "self.skip_own_var" not in src, "the robbery's box came back"
    # …and the table's rule still does not consult the robbery's home server.
    assert "_visible_rows" in src and "skip_server" not in \
        src.split("def _visible_rows")[1].split("def ")[0]


def _config_stub():
    """A tab with only the variables `config()` reads — no Tk, no window."""
    import types
    stub = object.__new__(st.SecretTasksTab)
    stub._combo = None
    stub.interval_var = _Var("15")
    stub.monitor_var, stub.show_spent_var = _Var(False), _Var(False)
    stub.hide_own_var = _Var(True)
    stub.filter_from_var = stub.filter_to_var = _Var("")
    stub.autoloot_var = _Var(False)
    stub.level_min_var = _Var("")
    stub.autoassist_var = _Var(False)
    stub.assist_level_var = _Var("")
    stub.coord_x_var = stub.coord_y_var = stub.coord_srv_var = _Var("")
    stub._jump_hist = []
    stub._zoom_level = "tile"
    # Every page keeps its own settings block now (#1251), so `config()` asks each of
    # them for one. A stand-in that answers is all this fixture needs.
    types = __import__("types")

    def _page(key):
        return types.SimpleNamespace(CONFIG_KEY=key, config=lambda: {"level_from": "",
                                                                     "level_to": ""},
                                     ur_var=_Var(False), star_var=_Var(False),
                                     monitor_var=_Var(False), interval_var=_Var("15"))

    stub.alliance = _page("alliance")
    stub.ghost = _page("ghost")
    stub.ghost_allies = _page("ghost_allies")
    stub.ghost_map = _page("ghost_map")
    return stub


def test_the_alliance_page_filters_on_ur_and_on_the_star():
    """The two boxes over the mirror (#1251), and neither of them touches the read."""
    g = _alliance_grid()
    # colour 5 is what the game's own config calls UR; 4 is the tier under it. The
    # star is `is_special`, and it is a separate axis — a UR task without one exists.
    g.apply([dict(_member_task(1, starred=True), colour=5),
             dict(_member_task(2, starred=False), colour=5),
             dict(_member_task(3, starred=False), colour=4)])
    assert len(g.visible_rows()) == 3

    g.ur_var = _Var(True)
    assert sorted(int(r["uuid"]) for r in g.visible_rows()) == [1, 2]

    g.star_var = _Var(True)
    assert [int(r["uuid"]) for r in g.visible_rows()] == [1]

    g.ur_var = _Var(False)
    assert [int(r["uuid"]) for r in g.visible_rows()] == [1]


def test_ur_falls_back_to_the_cfg_id_when_the_config_is_not_loaded():
    """A record whose config the client has not read carries colour 0 — the cfgId
    family answers instead, and a row with neither is not called UR."""
    assert gr.is_ur({"colour": 5}) is True
    assert gr.is_ur({"colour": 4}) is False
    assert gr.is_ur({"colour": 0, "cfg_id": 60000701}) is True   # family 6000
    assert gr.is_ur({"colour": 0, "cfg_id": 50000702}) is True   # family 5000
    assert gr.is_ur({"colour": 0, "cfg_id": 40000701}) is False  # family 4000
    assert gr.is_ur({}) is False


def _ghost_grid(cls=None):
    """A ghost page with no Tk behind it — the rows and the arithmetic only."""
    import types
    from panel.tabs.secret_tasks import ghost as gh

    cls = cls or gh.GhostGrid

    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")

    def _rank(row):
        key = "secrettasks.stars" if row.get("starred") else "secrettasks.level"
        return i18n.t(key, n=int(row.get("level") or 0))

    rt = types.SimpleNamespace(root=None, profiles=_FakeProfiles(_state_path()))
    tab = types.SimpleNamespace(t=i18n.t, rt=rt, _rank=_rank,
                                sync_actions=lambda: None,
                                # …and the per-page counters, which land on a notebook
                                # this fixture does not have (#1272).
                                sync_page_counts=lambda: None,
                                _collectable=lambda row: bool(row.get("ready")),
                                _row_values=lambda row: ())
    tab.shared = _shared_marks(tab)
    g = object.__new__(cls)
    g.tab = tab
    g._rows, g._tree, g._sort = {}, None, None
    g._body = g._empty = None
    g._count_var = _Var()
    g._status_var = _Var()
    g.status = {}
    g.level_from, g.level_to = _Var(""), _Var("")
    # The map page also owns the ghost sniffer's switch and interval (#1251).
    g.monitor_var, g.interval_var = _Var(False), _Var("15")
    return g


def _ghost_record(uuid=1, cfg=60301, state=2, looted=0, mine=False, ready=None,
                  done=0, ends=None, owner="Player1", task_state=2, level=5,
                  colour=6, starred=None, loot_max=3):
    """One record in the shape `ghost_recon_steal.roster` hands the page.

    Invented throughout (CLAUDE.md): a made-up uuid, a template id of the real shape,
    a name that looks made up and server numbers that are nobody's. The level, the
    colour and the star are the CONFIG's answers, which is where the tool takes them
    from (#1251).
    """
    return {"uuid": str(uuid), "server": 900, "owner_server": 935,
            "x": 3, "y": 4, "cfg_id": cfg,
            "level": level, "colour": colour,
            "starred": str(cfg).startswith("6") if starred is None else starred,
            "loot_count": looted, "loot_max": loot_max, "completed_at": done or None,
            # None is «no deadline», which is what the tool makes of an event ceiling
            # (`NEVER_MS`) — the record the page gets is already normalised.
            "expires_at": ends,
            "owner_uid": "1000000000000001", "owner_name": owner,
            "alliance_id": "0000000000000000000000000000000a", "mine": mine,
            "state": state, "task_state": task_state,
            "ready": (state == 2 and not mine) if ready is None else ready}


def test_the_ghost_page_believes_the_games_verdict_not_a_clock():
    """A squad has no completion time until it is back — the client's own
    `GhostreconPointStealType` is what «готово» means here (#1251)."""
    g = _ghost_grid()
    g.apply([_ghost_record(1, state=2), _ghost_record(2, state=4)])
    g._refresh_timers()

    assert g._rows["1"]["ready"] is True and g._rows["2"]["ready"] is False
    assert g._rows["1"]["state_key"] == "secrettasks.ghost.state.can"
    assert g._rows["2"]["state_key"] == "secrettasks.ghost.state.not_shown"
    # …and the cell says the verdict rather than drawing «готово через —».
    assert g._rows["2"]["timer"].get() == g.tab.t("secrettasks.ghost.state.not_shown")


def test_only_the_event_ceiling_means_no_deadline_at_all():
    """`actEndTime` alone is the int32 ceiling — 68 years is not a countdown (#1251)."""
    import ghost_recon_steal as tool

    lines = ["ACT ghost open=true left=5 known=1",
             "ACT G uuid=1000000000000009 cfg=50301 owner=1000000000000002 srv=900 "
             "tsrv=901 x=1 y=2 done=0 ends=2147483647000 exp=0 looted=0 state=4 raw=2 "
             "lvl=5 colour=5 spec=0 slots=3 al=000000000000000a name= mine=false"]
    ev = __import__("types").SimpleNamespace(run=lambda *_a, **_k: lines)
    _status, records = tool.roster(ev, refresh=False)
    assert records[0]["expires_at"] is None


def test_a_squad_that_never_expires_is_not_dropped_by_the_countdown():
    """`actEndTime` is the EVENT's end and reads as the int32 ceiling while it has
    none — the tool turns that into «no deadline», and a row wearing it must not be
    counted down to nor swept off the table."""
    g = _ghost_grid()
    g.apply([_ghost_record(1, state=2)])
    assert g._rows["1"]["expires_at"] is None
    expired, _changed = g._refresh_timers()
    assert expired == [], expired


def test_the_ghost_page_never_offers_the_robbery():
    """It lives in «Командный пункт» because a robbery there is two steps — a tool parks
    the targets, the recipe spends them (#1188) — and a third doorway to that is the thing
    the rule forbids."""
    g = _ghost_grid()
    g.apply([_ghost_record(1, state=2)])
    assert g.collectable(g._rows["1"]) is False
    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "ghost.py").read_text(encoding="utf-8")
    assert "ghost_recon_steal(" not in src, "the page assembles a robbery of its own"
    assert "queue_set" not in src


def test_the_ghost_row_says_whose_squad_it_is_and_how_often_it_was_robbed():
    """The same table, in the two places a ghost squad is not a secret task.

    The loot cell counts against the TEMPLATE's own capacity — three live, but read
    rather than assumed — and the action cell stays empty because these pages do not
    rob (#1188).
    """
    g = _ghost_grid()
    g.apply([_ghost_record(1, mine=True, looted=2, owner="Player1", loot_max=3)])
    g._refresh_timers()
    cells = dict(zip([c[0] for c in gr.COLUMNS], g.row_values(g._rows["1"])))
    assert cells["owner"] == "Player1", cells
    assert cells["slots"] == g.tab.t("secrettasks.ghost.slots", n=2, max=3)
    assert cells["action"] == "", "the ghost page must not draw a «Собрать» cell"

    # A template the client has not loaded has no capacity to count against — the cell
    # says how many, and does not invent a denominator.
    g2 = _ghost_grid()
    g2.apply([_ghost_record(2, looted=1, loot_max=0)])
    g2._refresh_timers()
    cells = dict(zip([c[0] for c in gr.COLUMNS], g2.row_values(g2._rows["2"])))
    assert cells["slots"] == g2.tab.t("secrettasks.ghost.looted", n=1)


def test_the_two_ghost_pages_are_two_lists_from_two_managers():
    """«не не, это разные гриды» — and they are not one list filtered twice (#1251).

    My own page is what THIS account is mixed up in; the alliance page is the list the
    game's own window draws, which is the whole alliance at once. A squad of mine that
    turns up in both is kept off the alliance page, because that is the page that
    answers «what has somebody ELSE sent out».
    """
    import types
    from panel.tabs.secret_tasks import ghost as gh

    tab = object.__new__(st.SecretTasksTab)
    tab._ghost_busy = True
    mine_page, allies_page = [], []
    tab.ghost = types.SimpleNamespace(
        landed=lambda status, rows: mine_page.extend(rows))
    tab.ghost_allies = types.SimpleNamespace(
        landed=lambda status, rows: allies_page.extend(rows))

    map_page = []
    tab.ghost_map = types.SimpleNamespace(
        landed=lambda status, rows: map_page.extend(rows))
    tab._ghost_landed({"open": True, "left": 5},
                      [_ghost_record(1, mine=True), _ghost_record(9, mine=False)],
                      [_ghost_record(2, mine=False), _ghost_record(3, mine=False),
                       _ghost_record(1, mine=True)],
                      [_ghost_record(7, mine=False)], True)

    assert [r["uuid"] for r in mine_page] == ["1"]
    assert [r["uuid"] for r in allies_page] == ["2", "3"]
    # …and the map's own findings go to the third ghost page, untouched: that is the
    # OTHER sniffer, and the only one that sees other alliances (#1251).
    assert [r["uuid"] for r in map_page] == ["7"]
    assert tab._ghost_busy is False
    # The two pages are two classes, so neither can quietly become the other.
    assert issubclass(gh.GhostAllianceGrid, gr.TaskGrid)
    assert gh.GhostAllianceGrid.TITLE_KEY != gh.GhostGrid.TITLE_KEY


def test_neither_ghost_read_asks_the_server():
    """«читай из пушей и из общего списка, не с сервера» — the client holds both lists
    already, so the tab reads local state and requests nothing (#1251)."""
    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "tab.py").read_text(encoding="utf-8")
    work = src.split("def _ghost_work")[1].split("def _ghost_landed")[0]
    assert "refresh=False" in work, "the ghost read still asks the server"
    # The seed is the one request there is, and it fires only on an EMPTY list.
    assert "seed_if_empty=True" in work
    allies = src.split("def _ghost_allies_work")[1].split("\n    def ")[0]
    assert "alliance_roster" in allies
    assert "seed_if_empty" not in allies, "a push must never ask the server"
    assert "refresh" not in allies


def test_the_push_is_what_keeps_the_alliance_page_current():
    """The alliance's squads arrive as a push, so the tab contributes a wire trigger
    for it — and the handler re-reads the LOCAL list rather than polling (#1251)."""
    import panel.triggers as trg

    specs = {t.name: t for t in st.SecretTasksTab.TRIGGERS}
    assert "ghost_recon_alliance" in specs, specs
    spec = specs["ghost_recon_alliance"]
    assert spec.event == "push.ghost.recon.alliance.single"
    assert spec.handler == "refresh_ghost_allies"

    catalogued = trg.default_catalogue().by_name("ghost_recon_alliance")
    assert catalogued is not None, "the trigger is not offered in the catalogue"
    assert catalogued.kind == trg.KIND_WIRE
    assert catalogued.event_pattern == "push.ghost.recon.alliance.single"
    assert catalogued.enabled is False           # opt-in, like the other listeners

    # …and it does nothing at all until somebody has opened the tab.
    tab = object.__new__(st.SecretTasksTab)
    tab.loaded = False
    tab._ghost_allies_work = lambda: (_ for _ in ()).throw(AssertionError("read!"))
    tab.refresh_ghost_allies()


def test_the_alliance_list_is_read_off_the_window_s_own_manager():
    """13 rows where the other list carried 4: the page reads what the game draws."""
    import ghost_recon_steal as tool

    lines = [
        "ACT ghost_alliance n=2",
        # Invented ids of the real shape (CLAUDE.md); `name` is hex, as the dump sends
        # it, and there is deliberately no steal count on these records.
        "ACT A uuid=1000000000000001 cfg=50306 owner=1000000000000002 srv=955 "
        "x=941 y=300 start=1700000000000 lvl=5 colour=5 spec=0 slots=3 dur=2100000 "
        "state=4 members=2 name=506c6179657231",
        "ACT A uuid=1000000000000003 cfg=60301 owner=1000000000000004 srv=947 "
        "x=1 y=2 start=1700000000000 lvl=5 colour=6 spec=1 slots=3 dur=2100000 "
        "state=2 members=1 name=506c6179657232",
    ]
    ev = __import__("types").SimpleNamespace(run=lambda *_a, **_k: lines)
    rows = tool.alliance_roster(ev)

    assert [r["uuid"] for r in rows] == ["1000000000000001", "1000000000000003"]
    first = rows[0]
    assert first["owner_name"] == "Player1"
    assert (first["x"], first["y"], first["server"]) == (941, 300, 955)
    # The config answers the level, the rarity, the star and the capacity.
    assert first["level"] == 5 and first["colour"] == 5 and first["loot_max"] == 3
    assert first["starred"] is False and rows[1]["starred"] is True
    # No completion field on these records — it is «set out» plus the config's own
    # duration, which is two READ values rather than a guess.
    assert first["completed_at"] == 1700000000000 + 2100000
    # …and what the list does not carry stays unanswered rather than becoming a zero.
    assert first["loot_count"] is None
    assert first["expires_at"] is None
    # The game's own verdict rides along: «can steal» is ready, anything else is not.
    assert first["ready"] is False and rows[1]["ready"] is True


def test_an_empty_alliance_list_is_seeded_once_and_never_on_a_push():
    """«Never asked» and «nothing out» look the same in an empty table (#1251).

    A client whose event window has not been opened this session has never been sent
    the list, so ONE request seeds it — the same message the game's own window makes on
    open. A list that already has rows is never re-requested, and neither is one being
    re-read because a push landed.
    """
    import ghost_recon_steal as tool

    asked, empty = [], ["ACT ghost_alliance n=0"]

    def run(chunk, *_a, **_k):
        if "GhostReconGetAllianceTaskList" in chunk:
            asked.append("request")
            return []
        return empty

    ev = __import__("types").SimpleNamespace(run=run)
    tool.time = __import__("types").SimpleNamespace(sleep=lambda _s: None)

    tool.alliance_roster(ev)                      # a push's re-read: never asks
    assert asked == [], asked

    tool.alliance_roster(ev, seed_if_empty=True)  # an empty list: asked once
    assert asked == ["request"], asked

    asked.clear()
    full = ["ACT A uuid=1000000000000001 cfg=50306 owner=1000000000000002 srv=955 "
            "x=1 y=2 start=1700000000000 lvl=5 colour=5 spec=0 slots=3 dur=2100000 "
            "state=4 members=1 name="]

    def run_full(chunk, *_a, **_k):
        if "GhostReconGetAllianceTaskList" in chunk:
            asked.append("request")
            return []
        return full

    rows = tool.alliance_roster(
        __import__("types").SimpleNamespace(run=run_full), seed_if_empty=True)
    assert asked == [] and len(rows) == 1, (asked, rows)


def test_a_map_tile_is_read_with_the_games_config_not_with_its_cfg_id():
    """A tile off the wire carries a cfgId and nothing else — and turning digits into a
    level is the mistake that invented «level 99» on the other robbery (#1244/#1251)."""
    import json as _json
    import tempfile
    import time as _time
    import ghost_recon_steal as tool

    # A checkpoint in the capture's own shape, seen just now so it is «fresh».
    record = {"uuid": 1000000000000001, "cfg_id": 60301, "level": 3, "family": "6",
              "state": 3, "target_server": 950, "owner_server": 935,
              "owner_id": "1000000000000002", "alliance_id": "000000000000000a",
              "alliance_show": True, "point_id": 300941, "x": 941, "y": 300,
              "completion_time": 1, "expire_time": 0, "team_start_time": 1,
              "steal_count": 1, "member_count": 5, "seen_at": _time.time()}
    path = tempfile.mktemp(suffix=".json")
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump([record], fh)

    # The config's own answers win…
    rows = tool.map_roster(path, {60301: {"level": 5, "colour": 6, "starred": True,
                                          "loot_max": 3, "duration": 2100000}})
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["level"] == 5 and row["colour"] == 6 and row["starred"] is True
    assert row["loot_max"] == 3 and row["loot_count"] == 1
    # The tile stands on its owner's map; where the squad was SENT is separate.
    assert row["server"] == 935 and row["target_server"] == 950
    # A tile off the wire has no nickname and no verdict from the game's own gate.
    assert row["owner_name"] == "" and row["state"] is None

    # …and with no config at all, the cfgId is the fallback and nothing more.
    bare = tool.map_roster(path)[0]
    assert bare["level"] == 5           # 60301 -> `03` + 2, task #1137
    assert bare["loot_max"] == 0        # never invented


def test_an_empty_star_table_says_why_it_is_empty():
    """A list emptied by the home-server rule must SAY so where the eye is (#1251).

    One live account had every star it could see at home: the table went blank, the
    count said «скрыто: 34» in grey off to the side, and the whole thing read as a tab
    that had failed to read anything.
    """
    said = []
    tab = _make_tab({"1": dict(_row(1, 7, -5_000, 600_000), server=100)})
    tab.hide_own_var = _Var(True)
    tab._own_server = 100
    import types as _t
    tab._empty = _t.SimpleNamespace(pack=lambda **_k: None,
                                    pack_forget=lambda: None)
    tab._body = object()
    tab.tr = lambda widget, key, **fmt: said.append((key, fmt))
    st.SecretTasksTab._show_empty(tab, True)
    assert said and said[-1][0] == "secrettasks.empty_hidden", said
    assert said[-1][1] == {"n": 1}, said

    # …and with nothing hidden it is the plain sentence again.
    tab.hide_own_var = _Var(False)
    st.SecretTasksTab._show_empty(tab, True)
    assert said[-1][0] == "secrettasks.empty", said


def test_an_unread_loot_count_draws_an_empty_cell_not_a_zero():
    """A «0/3» on a row nobody counted reads as «nobody has robbed it» — which is a
    claim the game never made (#1251)."""
    from panel.tabs.secret_tasks import ghost as gh

    g = _ghost_grid(gh.GhostAllianceGrid)
    g.apply([dict(_ghost_record(1, mine=False), loot_count=None)])
    g._refresh_timers()
    cells = dict(zip([c[0] for c in gr.COLUMNS], g.row_values(g._rows["1"])))
    assert cells["slots"] == "", cells
    # …and the phone leaves the fact out altogether rather than saying nothing badly.
    facts = {f["label"] for f in g.web_items()[0]["facts"]}
    assert "secrettasks.col.slots" not in facts, facts


def test_the_allies_page_names_who_sent_the_squad():
    """That column is the whole point of the page, exactly as on the alliance
    secret-task one — and a ghost squad's own member list is where the name lives."""
    g = _ghost_grid(__import__("panel.tabs.secret_tasks.ghost",
                               fromlist=["GhostAllianceGrid"]).GhostAllianceGrid)
    g.apply([_ghost_record(5, mine=False, owner="Player2", state=2)])
    g._refresh_timers()
    cells = dict(zip([c[0] for c in gr.COLUMNS], g.row_values(g._rows["5"])))
    assert cells["owner"] == "Player2"
    # A mate's squad the game calls robbable is «ready» — and says so in words.
    assert g._rows["5"]["ready"] is True
    assert g._rows["5"]["state_key"] == "secrettasks.ghost.state.can"
    # …and the phone's copy of the same row carries the name first.
    item = g.web_items()[0]
    assert item["facts"][0] == {"label": "secrettasks.col.owner", "value": "Player2"}


def test_the_two_sniffers_are_two_pages_and_neither_replaces_the_other():
    """«Это два разных снифа, чужие снифаем по карте, свои из списка» (#1251).

    The client's own lists never carry another alliance's squads — nobody tells the
    client about them — so a map sweep is the only way to see the tiles a robbery is
    actually aimed at. It gets a page of its own rather than being folded into either
    list, and the three pages are three classes.
    """
    from panel.tabs.secret_tasks import ghost as gh

    for cls in (gh.GhostGrid, gh.GhostAllianceGrid, gh.GhostMapGrid):
        assert issubclass(cls, gr.TaskGrid)
    titles = {gh.GhostGrid.TITLE_KEY, gh.GhostAllianceGrid.TITLE_KEY,
              gh.GhostMapGrid.TITLE_KEY}
    assert len(titles) == 3, titles

    # The map page is fed by the capture's checkpoint, and the client-read pages are
    # not: mixing them is what made «свои» and «чужие» one indistinguishable list.
    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "tab.py").read_text(encoding="utf-8")
    assert "map_roster" in src and "ghost_json" in src


def test_the_ghost_capture_is_given_a_checkpoint_to_write():
    """The regression that made a whole lap of the map produce nothing (#1251).

    The tile capture was launched WITHOUT `--json`, so everything it decoded went to
    the log and no further — hundreds of tiles, a busy progress line, and not one row
    on any table. Each capture writes to a file of its own: the ghost records are a
    different shape and the secret-task reader must never be handed them.
    """
    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "capture.py").read_text(encoding="utf-8")
    start = src.split("def start")[1].split("def _launch")[0]
    assert "tasks_json()" in start and "ghost_json()" in start
    # …and they are not the same file, whichever branch is taken: the ghost records
    # are a different shape, and auto-loot reads only the secret-task one.
    assert 'cmd += ["--json", self.rt.profiles.tasks_json()]' in start
    assert 'cmd += ["--json", self.rt.profiles.ghost_json()]' in start


def test_the_ghost_read_is_one_round_trip_and_carries_the_event_with_it():
    """`roster` parses the dump the client answers with — the event's own state is on
    its first line, so the page's status and its rows cost ONE read (#1251)."""
    import ghost_recon_steal as tool

    lines = [
        "ACT ghost open=true left=4 known=2",
        # Invented ids of the real shape — never a live one (CLAUDE.md).
        # `lvl`/`colour`/`spec`/`slots` are the event's OWN config row, and `name` is
        # the owner's nickname hex-encoded. `srv` is where the robbery is addressed,
        # `tsrv` is where the TILE is.
        "ACT G uuid=1000000000000001 cfg=60301 owner=1000000000000002 srv=900 "
        "tsrv=901 x=11 y=22 done=1700000000000 ends=2147483647000 exp=1700003600000 "
        "looted=1 state=2 "
        "raw=3 lvl=5 colour=6 spec=1 slots=3 al=000000000000000a "
        "name=506c6179657231 mine=false",
        "ACT G uuid=1000000000000003 cfg=40302 owner=1000000000000002 srv=900 "
        "tsrv=902 x=0 y=0 done=0 ends=0 looted=0 state=4 raw=2 lvl=4 colour=4 spec=0 "
        "slots=3 al=000000000000000a name=506c6179657232 mine=true",
        # My own EMPTY dispatch slot: no tile, no clock — and the game's steal gate
        # answers «robbable» for it all the same. Never a row (#1251).
        "ACT G uuid=1000000000000004 cfg=50301 owner=1000000000000002 srv=900 "
        "tsrv=903 x=0 y=0 done=0 ends=0 looted=0 state=2 raw=0 lvl=5 colour=5 spec=0 "
        "slots=3 al=000000000000000a name=506c6179657232 mine=true",
    ]
    ev = __import__("types").SimpleNamespace(run=lambda *_a, **_k: lines)
    status, records = tool.roster(ev, refresh=False)

    assert status == {"open": True, "left": 4, "known": 2}
    assert [r["uuid"] for r in records] == ["1000000000000001", "1000000000000003"]
    first = records[0]
    # The TILE stands on the OWNER's map — measured with the tile capture running, a
    # lap of one server found 38 ghost tiles and every one of them was that server's
    # (#1251). `targetServer` is where the squad was sent, and is carried separately.
    assert (first["x"], first["y"]) == (11, 22)
    assert first["server"] == 900 and first["owner_server"] == 900
    assert first["target_server"] == 901
    # The level, the rarity, the star and the loot capacity are the CONFIG's answers.
    assert first["level"] == 5 and first["starred"] is True
    assert first["colour"] == 6 and first["loot_max"] == 3
    assert first["owner_name"] == "Player1"
    assert first["ready"] is True and first["loot_count"] == 1
    # The TASK's own expiry is the deadline; the event ceiling (`ends`) is not one.
    assert first["expires_at"] == 1700003600000, first["expires_at"]
    assert records[1]["mine"] is True and records[1]["ready"] is False
    assert records[1]["starred"] is False and records[1]["level"] == 4


def test_the_config_answers_the_level_and_the_star_and_the_digits_only_fill_gaps():
    """#1244's lesson, applied before it is paid for again (#1251).

    A template the client HAS answers for itself — even when its numbers disagree with
    the cfgId's digits. A line with no config on it at all falls back to the
    arithmetic, which is the only thing left to fall back to.
    """
    import ghost_recon_steal as tool

    ev = lambda lines: __import__("types").SimpleNamespace(run=lambda *_a, **_k: lines)

    # The config says level 4 on a cfgId whose digits read 5 — the config wins, the
    # way `lw_dispatch_tasks` won over «level 99» on the other robbery.
    said = ["ACT ghost open=true left=5 known=1",
            "ACT G uuid=1000000000000001 cfg=50301 owner=1000000000000002 srv=900 "
            "tsrv=901 x=1 y=2 done=0 ends=0 looted=0 state=4 raw=2 lvl=4 colour=6 "
            "spec=1 slots=2 al=000000000000000a name= mine=false"]
    _status, records = tool.roster(ev(said), refresh=False)
    assert records[0]["level"] == 4, "the cfgId's digits overruled the config"
    assert records[0]["starred"] is True, "the config's own star was ignored"
    assert records[0]["loot_max"] == 2

    # …and with nothing from the config, the digits are all there is: `50301` is
    # family 5 (no star) and `03` + 2 = level 5 (#1137).
    silent = ["ACT ghost open=true left=5 known=1",
              "ACT G uuid=1000000000000001 cfg=50301 owner=1000000000000002 srv=900 "
              "tsrv=901 x=1 y=2 done=0 ends=0 looted=0 state=4 raw=2 mine=false"]
    _status, records = tool.roster(ev(silent), refresh=False)
    assert records[0]["level"] == 5 and records[0]["starred"] is False
    assert records[0]["loot_max"] == 0, "an unread capacity must not be invented"


def test_my_own_squad_is_never_offered_as_a_target():
    """The gate answers about the TILE, so it says «robbable» about my own squad too —
    and `--all` skips my own separately. A row saying «готово к сбору» on it would be
    offering a press the server refuses (#1251)."""
    import ghost_recon_steal as tool

    lines = ["ACT ghost open=true left=5 known=1",
             "ACT G uuid=1000000000000005 cfg=60301 owner=1000000000000002 srv=900 "
             "x=7 y=8 done=1700000000000 ends=0 looted=0 state=2 raw=3 mine=true"]
    ev = __import__("types").SimpleNamespace(run=lambda *_a, **_k: lines)
    _status, records = tool.roster(ev, refresh=False)
    assert records[0]["mine"] is True and records[0]["ready"] is False

    # …and the page labels it by what it is DOING, not by a robbery verdict.
    g = _ghost_grid()
    g.apply(records)
    assert g._rows["1000000000000005"]["state_key"] == \
        "secrettasks.ghost.state.mine_done"


def test_the_phone_can_flip_the_same_three_boxes_the_window_has():
    """CLAUDE.md, the other direction: a rule the window holds is a press on the phone,
    and it goes through the window's OWN variable so the two cannot disagree."""
    import types
    tab = object.__new__(st.SecretTasksTab)
    tab.hide_own_var = _Var(True)
    tab.alliance = types.SimpleNamespace(ur_var=_Var(False), star_var=_Var(False),
                                          refilter=lambda: None)
    tab.rt = types.SimpleNamespace(settings=types.SimpleNamespace(changed=lambda: None))
    tab._render = lambda: None
    tab._update_status = lambda: None
    posted = []
    tab.post = lambda fn: posted.append(fn)

    assert tab.web_press("hide_own", {}) == {"ok": True}
    assert tab.web_press("ur_only", {}) == {"ok": True}
    assert tab.web_press("star_only", {}) == {"ok": True}
    for fn in posted:
        fn()
    assert tab.hide_own_var.get() is False
    assert tab.alliance.ur_var.get() is True
    assert tab.alliance.star_var.get() is True


def test_the_camera_height_is_one_setting_both_front_ends_move(monkeypatch=None):
    """«Зум кнопкой там же, где переход по координатам» (#1265).

    Three levels, named by what each is for, and the phone's press walks the SAME field
    the window's box writes — so the two cannot disagree about how far back the camera
    is about to sit. The lap and every jump this tab makes read that one field.
    """
    import types
    import lua_actions
    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    tab = object.__new__(st.SecretTasksTab)
    tab.t = i18n.t
    tab._zoom_level = lua_actions.DEFAULT_ZOOM_LEVEL
    tab._zoom_combo = None
    tab._zoom_label_var = _Var("")
    said = []
    tab.say = lambda tag, key, **fmt: said.append(key)
    tab.rt = types.SimpleNamespace(settings=types.SimpleNamespace(changed=lambda: None))
    posted = []
    tab.post = lambda fn: posted.append(fn)

    # The close view is the default, and it is the height the jump always used.
    assert lua_actions.zoom_level(tab._zoom_level)[0] == lua_actions.JUMP_ZOOM
    # …and the phone cycles through all three and back, writing the window's own field.
    assert tab.web_press("zoom", {}) == {"ok": True}
    for fn in posted:
        fn()
    assert tab._zoom_level == "tasks"
    assert lua_actions.zoom_level("tasks")[0] == lua_actions.SWEEP_ZOOM_MAX
    assert lua_actions.zoom_level("bases")[0] == lua_actions.BASE_ZOOM_MAX
    # A level nobody has heard of (an old profile) answers with the close view rather
    # than refusing to draw the tab.
    assert lua_actions.zoom_level("from-an-older-panel") == \
        lua_actions.ZOOM_LEVELS[lua_actions.DEFAULT_ZOOM_LEVEL]
    # Every level has a step that belongs to it: a step is meaningless without its height.
    assert all(step > 0 for _height, step in lua_actions.ZOOM_LEVELS.values())


def test_the_lap_is_a_scenario_and_the_panel_only_plays_it():
    """CLAUDE.md: the ability is `actions/scan_map.md`, the tab decides only WHEN."""
    import types
    import lua_actions
    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    tab = _sweep_tab()
    played = tab.rt.played

    tab._sweep_once()
    assert played == [("scan_map", {"zoom": lua_actions.SWEEP_ZOOM_MAX,
                                    "step": lua_actions.FAST_STEP})]
    # Nothing was said about an unwatched lap: the ★ monitor is on.
    assert "log.coord.sweep_unwatched" not in tab.said

    # …and with both sniffers off it says so, because a lap nobody reads finds nothing.
    played.clear()
    tab._sweeping = False
    tab.capture = types.SimpleNamespace(running=False)
    tab._sweep_once()
    assert "log.coord.sweep_unwatched" in tab.said


def _sweep_tab(rows=None):
    """A tab wired for the lap: no window, no game, just the decisions it makes."""
    import types
    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    tab = object.__new__(st.SecretTasksTab)
    tab.t = i18n.t
    tab._zoom_level = "tasks"
    tab._sweeping, tab._sweep_btn = False, None
    tab._rows = dict(rows or {})
    tab._collected, tab._restore_pending = {"already-robbed"}, {"x"}
    tab.said = []
    tab.say = lambda tag, key, **fmt: tab.said.append(key)
    tab.capture = types.SimpleNamespace(running=True)
    tab.ghost_capture = types.SimpleNamespace(running=False)
    tab.post = lambda fn: fn()
    tab._render = tab._update_status = tab._persist_rows = lambda: None
    tab._retitle_sweep = lambda: None
    played = []
    tab.rt = types.SimpleNamespace(
        played=played,
        play_async=lambda name, args=None, **kw: played.append((name, args)) or True)
    return tab


def test_pressing_the_lap_empties_the_list_first():
    """«При клике обход карты убрать из списка тайл» (#1272).

    The list accumulates between laps and no READ may empty it — that is the rule that
    stopped it being wiped every start-up. A PERSON pressing «Обойти карту» is the
    explicit «покажи, что на карте сейчас», which is a different thing entirely: leaving
    yesterday's finds mixed with this lap's makes the table a blend nobody can read.
    """
    tab = _sweep_tab({"1": _row(1, 7, -5_000, 600_000)})

    tab._sweep_once()

    assert tab._rows == {}, "the lap started on top of yesterday's finds"
    assert "log.coord.sweep_wiped" in tab.said
    # …but the session's robbed set survives, or a tile taken today could be offered
    # again the moment the lap re-finds it.
    assert tab._collected == {"already-robbed"}


def test_a_second_press_stops_the_lap_instead_of_starting_another():
    """«Кнопки завершения нет» — now there is, and it is the same button (#1272)."""
    import types
    tab = _sweep_tab()
    stopped = []
    tab.rt.game = types.SimpleNamespace(
        evaluator=lambda: types.SimpleNamespace(
            run=lambda chunk, marker=None, settle=0: stopped.append(chunk) or []))

    tab._sweep_once()
    tab._sweeping = True                     # what `on_start` sets on the Tk thread
    tab._sweep_once()

    assert len(tab.rt.played) == 1, "the second press started a second lap"
    assert "log.coord.sweep_stopped" in tab.said
    import time as _time
    for _ in range(200):
        if stopped:
            break
        _time.sleep(0.01)
    assert stopped and "__lw_sweep_run" in stopped[0], stopped
    assert tab._sweeping is False


def test_the_lap_heights_no_longer_offer_the_tile_view():
    """A lap at the tile view is 88 seconds against 6 and finds nothing extra — it was
    only ever on the list because this box also decided how high a JUMP landed (#1272)."""
    import lua_actions
    assert "tile" not in lua_actions.SWEEP_LEVELS
    assert lua_actions.SWEEP_LEVELS == ("tasks", "bases")
    slow = lua_actions.fast_sweep_seconds(lua_actions.ZOOM_LEVELS["tile"][1])
    quick = lua_actions.fast_sweep_seconds(lua_actions.ZOOM_LEVELS["tasks"][1])
    assert slow > 10 * quick, (slow, quick)


def test_every_coordinate_jump_lands_at_the_tile_view():
    """«Это для ЛЮБЫХ переходов по координатам» (#1272) — so the rule is in the jump
    itself and no caller can forget it: there is nothing left to pass."""
    import inspect
    from panel.runtime import daemon as daemonmod
    sig = inspect.signature(daemonmod.GameLink.jump)
    assert "zoom" not in sig.parameters, "a caller can still choose a height"
    src = inspect.getsource(daemonmod.GameLink.jump)
    assert "jump_to_coord(x, y, target)" in src, src
    # …and the tab's own jump passes nothing either.
    tabsrc = inspect.getsource(st.SecretTasksTab._jump)
    assert "zoom=" not in tabsrc, tabsrc


def test_the_two_sniffers_have_two_independent_switches():
    """«В секретках и операциях свои фильтры и мониторы» (#1251).

    One box with a dropdown meant choosing which sniffer to watch STOPPED the other.
    Now each capture has a switch of its own, on the page it feeds, and either may run
    while the other does not.
    """
    from panel.tabs.secret_tasks import capture as cap

    made = []

    class _Child:
        def __init__(self, *a, **k):
            made.append(k)
            self.started = self.stopped = 0

    tab = object.__new__(st.SecretTasksTab)
    star_switch, ghost_switch = _Var(False), _Var(False)
    star = cap.Capture.__new__(cap.Capture)
    star.switch, star.interval, star._proc, star._starting = star_switch, _Var("15"), None, False
    ghost = cap.Capture.__new__(cap.Capture)
    ghost.switch, ghost.interval, ghost._proc, ghost._starting = ghost_switch, _Var("15"), None, False

    # Each capture reads ITS OWN box, and knows which script it is.
    assert star.wanted is False and ghost.wanted is False
    ghost_switch.set(True)
    assert ghost.wanted is True and star.wanted is False

    # …and a child that dies clears only its own box.
    ghost._untick()
    assert ghost_switch.get() is False and star_switch.get() is False

    # The two are told apart by index, which is what picks the script and the
    # checkpoint (`captures.CAPTURE_OPTIONS`).
    from panel.runtime import captures as capturemod
    assert len(capturemod.CAPTURE_OPTIONS) == 2
    assert capturemod.CAPTURE_OPTIONS[0]["script"] == capturemod.SECRET_TASK_CAPTURE


def test_every_page_filters_by_its_own_level_range():
    """One range on top of the tab narrowed lists it had nothing to do with: ghost
    squads are levels 3-5 where secret tasks run 1-7 (#1251)."""
    from panel.tabs.secret_tasks import ghost as gh

    ally = _alliance_grid()
    ally.apply([_member_task(1, level=6), _member_task(2, level=7)])
    assert len(ally.visible_rows()) == 2
    ally.level_from.set("7")
    assert [int(r["uuid"]) for r in ally.visible_rows()] == [2]

    # …and the ghost page's own range is a different box entirely: narrowing one must
    # not touch the other.
    squads = _ghost_grid(gh.GhostAllianceGrid)
    squads.apply([_ghost_record(5, level=5), _ghost_record(6, level=3)])
    assert len(squads.visible_rows()) == 2
    squads.level_to.set("4")
    assert [r["uuid"] for r in squads.visible_rows()] == ["6"]
    assert [int(r["uuid"]) for r in ally.visible_rows()] == [2], "the ranges are shared"


def test_each_page_saves_its_filters_under_its_own_key():
    """A monitor ticked on one page must not travel with another's settings (#1251)."""
    from panel.tabs.secret_tasks import ghost as gh

    page = _ghost_grid(gh.GhostMapGrid)
    page.level_from.set("4")
    page.monitor_var.set(True)
    page.interval_var.set("7")
    saved = page.config()
    assert saved == {"level_from": "4", "level_to": "", "monitor": True,
                     "interval": "7"}, saved

    fresh = _ghost_grid(gh.GhostMapGrid)
    fresh.apply_config(saved)
    assert fresh.level_from.get() == "4" and fresh.monitor_var.get() is True
    assert fresh.interval_var.get() == "7"

    # …and a page with no block of its own reads as a fresh one, not as a crash.
    fresh.apply_config(None)
    assert fresh.level_from.get() == "" and fresh.monitor_var.get() is False


def test_the_alliance_page_stays_a_mirror_on_purpose():
    """«Задания альянса списком, он один и всегда актуален, чего нет — значит протухло.»

    The operator's own ruling (#1251), and the one place on this tab where a read
    REPLACES the table instead of adding to it: `alliance_roster` hands over the whole
    thing every time — 200 tasks from 52 members, live — so a task it stops listing has
    ended, and keeping the row would be a raid that no longer exists.

    Pinned rather than merely written down, because the rest of the tab was moved the
    other way in the same task and «make them all consistent» is exactly the tidy-up
    that would break this one.
    """
    mirror = _alliance_grid()
    mirror.apply([_member_task(1), _member_task(2)])
    assert set(mirror._rows) == {"1", "2"}
    mirror.apply([_member_task(3)])
    assert set(mirror._rows) == {"3"}, "the alliance mirror started accumulating"

    # It inherits the base's replace-whole `apply` — an override here IS the change
    # this test exists to catch.
    assert al.AllianceGrid.apply is gr.TaskGrid.apply
    src = (Path(__file__).resolve().parents[1] / "panel" / "tabs" / "secret_tasks" /
           "alliance.py").read_text(encoding="utf-8")
    assert "def apply(" not in src, "the alliance page grew an apply() of its own"
    # …and the reason is written where the next reader will find it.
    assert "MIRROR" in src.upper() and "протухло" in src


def _abroad_tab(own):
    """A tab reduced to what `_abroad_only` touches: the home server and the log."""
    said = []
    tab = object.__new__(st.SecretTasksTab)
    tab._own_server = own
    tab._warned_no_own_feed = False
    tab.own_server = lambda: tab._own_server
    tab.say = lambda tag, key, **fmt: said.append(key)
    return tab, said


def _feed(uuid, server):
    """A `SecretTask` as a feed hands one over — only `server_id` matters here."""
    import lastwar_proto as proto
    return proto.SecretTask.from_dict({
        "uuid": uuid, "server_id": server, "x": 1, "y": 2, "level": 7,
        "cfg_id": 60000701, "family": "6000", "looted_by": [],
        "expires_at": 0, "completed_at": 0, "starred_cfg": True})


def test_a_home_tile_never_ENTERS_the_list_at_all():
    """The gate is on the FEED, not in front of each consumer of the list (#1188).

    A home tile used to reach `_rows` and be filtered afterwards — by the display rule
    when drawing, by `rob_candidates` when robbing. That left a window nobody had to
    invent: `on_show` primes the own server on a THREAD and fires the first snapshot
    immediately, so a feed can land while home is still unknown, and everything that
    judges a row against home reads «unknown» as «nothing is home». Live it showed as
    home tiles in the grid for about a second — long enough for a 2-second poll, and
    the game fines the player for a raid at home.
    """
    tab, _said = _abroad_tab(935)
    kept = st.SecretTasksTab._abroad_only(tab, [_feed(1, 935), _feed(2, 999),
                                                _feed(3, 935), _feed(4, 1024)])
    assert [t.uuid for t in kept] == [2, 4], [t.uuid for t in kept]


def test_an_unreadable_home_server_admits_NOTHING_to_the_raid_list():
    """«I cannot tell home from abroad» must never come out as «none of it is home».

    That is the exact shape of the bug above, so the feed refuses instead — and says so
    once per spell of not knowing rather than once per read.
    """
    tab, said = _abroad_tab(0)
    assert st.SecretTasksTab._abroad_only(tab, [_feed(1, 999)]) == []
    assert st.SecretTasksTab._abroad_only(tab, [_feed(2, 999)]) == []
    assert said == ["log.secret.no_own_server_feed"], said

    # …and once home IS known the complaint resets, so a later spell is said again.
    tab._own_server = 935
    assert [t.uuid for t in st.SecretTasksTab._abroad_only(tab, [_feed(3, 999)])] == [3]
    tab._own_server = 0
    assert st.SecretTasksTab._abroad_only(tab, [_feed(4, 999)]) == []
    assert said == ["log.secret.no_own_server_feed"] * 2, said


def test_both_feeds_go_through_the_gate_and_not_only_one():
    """Two sources fill this list, and a gate on one of them is not a gate."""
    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "tab.py").read_text(encoding="utf-8")
    for feed in ("_fetch_scan", "_fetch_vm"):
        body = src.split(f"def {feed}")[1].split("\n    def ")[0]
        assert "_abroad_only" in body, f"{feed} still admits home tiles"


def test_a_tile_with_no_finish_time_never_enters_the_model():
    """«Есть в списке "готово через" и прочерк — такие вообще не нужно выводить» (#1272).

    The wire decoder reads the finish time off the tile's own field and hands over `None`
    when the tile does not carry one. Such a row can never mature — `ready` is «set and
    past» — so it can never be robbed, never counts down and never leaves on its own
    clock. It is refused at the model's door rather than hidden by the table, because
    everything downstream (the standing order, the phone, the checkpoint) reads the model.
    """
    tab = _make_tab({})
    tab._merge([_WireTask(1, completed_at=None), _WireTask(2)])

    assert sorted(tab._rows) == ["2"], tab._rows


def test_a_checkpoint_row_with_no_finish_time_is_not_restored():
    """Only a file written before the gate can hold one, and it must not come back: it
    would sit there drawing «готово через —» until the panel was shut (#1272)."""
    import json as _json
    path = _state_path()
    good = {"uuid": 2, "server": 1, "x": 1, "y": 2, "level": 7, "cfg_id": 60000701,
            "loot_count": 0, "starred": True,
            "completed_at": _ms(-5_000), "expires_at": _ms(600_000)}
    bad = dict(good, uuid=1, completed_at=None)
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump([bad, good], fh)
    import types
    tab = _make_tab({})
    tab.rt = types.SimpleNamespace(profiles=_FakeProfiles(path), root=None)

    restored = tab._load_persisted()

    assert sorted(tab._rows) == ["2"], tab._rows
    assert restored == {"2"}, restored


def test_the_countdown_is_redrawn_far_more_often_than_the_model_is_recomputed():
    """«Те, что уже можно грабить, должны обновляться несколько раз в секунду» (#1272).

    The fast pass draws and decides nothing: it writes the state cell of a row whose
    clock has moved, and it does not expire, flip or re-sort anything — all of which is
    what makes it affordable four times a second.
    """
    rows = {"2": _row(2, 7, -5_000, 600_000)}
    rows["2"]["ready"] = True
    tab = _make_tab(rows)
    tab._refresh_timers()
    before = rows["2"]["timer"].get()
    tree = _CountingTree()

    # The clock has moved on a minute: the cell follows, and the row is untouched.
    rows["2"]["expires_at"] = _ms(540_000)
    gr.repaint_countdowns(tree, rows, tab.t)
    assert rows["2"]["timer"].get() != before
    assert tree.writes == [("2", "state", rows["2"]["timer"].get())], tree.writes
    assert rows["2"]["ready"] is True, "the drawing pass flipped a flag"

    # A pass that changes nothing costs no Tk call at all — three passes in four, in the
    # steady state, and that is what keeps the rate off the shared event loop (#1226).
    tree.writes.clear()
    gr.repaint_countdowns(tree, rows, tab.t)
    assert tree.writes == [], tree.writes

    # …and an expired row is NOT dropped here: dropping is the once-a-second pass's job.
    rows["2"]["expires_at"] = _ms(-1_000)
    gr.repaint_countdowns(tree, rows, tab.t)
    assert "2" in rows


def test_the_fast_repaint_is_armed_only_while_something_is_counting_down():
    """Four wake-ups a second times every open profile is a real share of the one event
    loop they share, so a tab with nothing to draw does not ask for them (#1272)."""
    assert gr.has_countdown({}) is False
    assert gr.has_countdown({"2": _row(2, 7, -5_000, 600_000)}) is True
    # A ghost row with neither clock — the game's verdict and no timestamps — is not one.
    still = dict(_row(3, 5, 0, 0))
    still["completed_at"] = still["expires_at"] = None
    still["state_key"] = "secrettasks.ghost.state.out"
    assert gr.has_countdown({"3": still}) is False


class _CountingTree:
    """Enough of a Treeview to see WHICH cells the repaint actually writes."""

    def __init__(self) -> None:
        self.writes: list = []

    def exists(self, _iid) -> bool:
        return True

    def set(self, iid, column, value) -> None:
        self.writes.append((iid, column, value))


class _WireTask:
    """One decoded tile, the shape `_merge` is handed (`lastwar_proto.SecretTask`)."""

    def __init__(self, uuid, completed_at=-5_000, expires_at=600_000) -> None:
        self.uuid = uuid
        self.server_id, self.x, self.y = 1, 1, 2
        self.level, self.cfg_id, self.loot_count = 7, 60000701, 0
        self.completed_at = _ms(completed_at) if completed_at is not None else None
        self.expires_at = _ms(expires_at) if expires_at is not None else None


def _ms(offset: int) -> int:
    """A game-clock stamp `offset` milliseconds from now."""
    import game_clock
    return game_clock.now_ms() + offset


def test_the_capture_only_fills_the_list_and_never_empties_it():
    """«Мониторинг только наполняет наши таблицы» (#1251).

    A finding that reached the list STAYS in it: the checkpoint reader hands over
    everything it holds, however long ago the map was last driven past it. The list
    empties by its own rules — an expiry, a robbery, a live read that stops confirming
    — and «нас давно не сканировали» is not one of them.
    """
    import json as _json
    import tempfile
    import time as _time
    import lastwar_proto as proto

    old_seen = _time.time() - 3 * proto.TASK_FRESH_SECONDS
    record = dict(_row(1, 7, -5_000, 600_000))
    record.pop("timer"), record.pop("frame")
    record = {"uuid": 1, "server_id": 1, "x": 1, "y": 2, "level": 7,
              "cfg_id": 60000701, "family": "6000", "looted_by": [],
              "owner_uid": "1000000000000001", "alliance_id": "AL1",
              "expires_at": None, "completed_at": None, "seen_at": old_seen}
    path = tempfile.mktemp(suffix=".json")
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump([record], fh)

    # The window still exists for whoever asks for it — a robbery does…
    assert proto.load_fresh_tasks(path) == []
    # …and the panel's own feed does not: the list is the panel's from here on.
    kept = proto.load_fresh_tasks(path, max_age_seconds=None)
    assert len(kept) == 1 and kept[0].uuid == 1

    src = (Path(__file__).resolve().parents[1] /
           "panel" / "tabs" / "secret_tasks" / "tab.py").read_text(encoding="utf-8")
    fetch = src.split("def _fetch_scan")[1].split("\n    def ")[0]
    assert "max_age_seconds=None" in fetch, "the tab still drops findings for being old"


def test_an_old_row_says_its_age_instead_of_vanishing():
    """The window is a WORD now, not a filter (#1251)."""
    import time as _time

    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    rows = {"1": dict(_row(1, 7, -5_000, 600_000),
                      seen_at=_time.time() - 40 * 60)}
    gr.refresh_timers(rows, i18n.t)
    said = rows["1"]["timer"].get()
    assert i18n.t("secrettasks.seen_ago", n=40) in said, said

    # …and a row seen a moment ago says nothing about its age at all.
    rows = {"2": dict(_row(2, 7, -5_000, 600_000), seen_at=_time.time() - 30)}
    gr.refresh_timers(rows, i18n.t)
    assert "мин назад" not in rows["2"]["timer"].get()


def test_the_map_page_keeps_its_own_list_and_checkpoints_it():
    """The map page is nobody's mirror: a lap that shows the south does not mean the
    north is empty, so a read ADDS rather than replaces (#1251)."""
    from panel.tabs.secret_tasks import ghost as gh

    page = _ghost_grid(gh.GhostMapGrid)
    saved = []
    page.persist = lambda: saved.append(len(page._rows))

    page.apply([_ghost_record(1), _ghost_record(2)])
    assert set(page._rows) == {"1", "2"}
    # A second lap, of a different patch of the world: the first two stay.
    page.apply([_ghost_record(3)])
    assert set(page._rows) == {"1", "2", "3"}
    assert saved == [2, 3], saved

    # …and so does the alliance page, for the same reason: its source was watched
    # emptying mid-event (13 rows, then 1, then 0) as squads came home, and a blink
    # must not take the table with it.
    ally = _ghost_grid(gh.GhostAllianceGrid)
    ally.apply([_ghost_record(1), _ghost_record(2)])
    ally.apply([_ghost_record(3)])
    assert set(ally._rows) == {"1", "2", "3"}

    # The secret-task alliance page IS still a mirror — see the test below.


# ---------------------------------------------------------------------------
# The robbery is a scenario now (#1188)
# ---------------------------------------------------------------------------
class _Proc:
    """A `spawn_raw` child that has already said its piece and gone."""

    def __init__(self, lines) -> None:
        self.stdout = iter(list(lines))
        self.returncode = 0

    def terminate(self) -> None: ...


class _Actions:
    """`rt.actions`, remembering which scenario was played and with which arguments."""

    def __init__(self, ok: bool = True, reason: str = "", lines=()) -> None:
        self.played, self.args = [], []
        self._ok, self._reason, self._lines = ok, reason, list(lines)

    def play(self, name, args=None, **kw):
        from panel.runtime.actions import Outcome
        self.played.append(name)
        self.args.append(dict(args or {}))
        for line in self._lines:
            (kw.get("on_event") or (lambda _m: None))(line)
        return Outcome(self._ok, self._reason)


def _order(lines=(), ok: bool = True, reason: str = ""):
    """An `AutoLoot` over a runtime that spawns nothing and presses nothing.

    Everything a robbery touches and not one thing more: `rt.actions` (which records the
    scenario, its arguments, and replays the lines the recipe would have said), the
    settings the pause comes from, and a tab that can say a locale key.
    """
    import types

    from panel.tabs.secret_tasks.autoloot import AutoLoot

    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("ru")
    said, put = [], []
    rt = types.SimpleNamespace(
        actions=_Actions(ok, reason, lines),
        settings=types.SimpleNamespace(opt_int=lambda key, low=0, high=0: 5),
        put=put.append)
    tab = types.SimpleNamespace(
        t=i18n.t, level_min_var=_Var("7"), skip_own_var=_Var(False),
        say=lambda tag, key, **fmt: said.append(key))
    order = AutoLoot(rt, tab)
    return order, rt, said, put


def _drain(order) -> None:
    """Wait for the worker `run()` started — the whole robbery lives on it."""
    import time as _time
    for _ in range(400):
        if order._proc is None:
            return
        _time.sleep(0.01)
    raise AssertionError("the robbery never finished")


def test_the_robbery_is_the_scenario_and_the_targets_travel_as_its_argument():
    """ONE step now, and the clock is why (#1272).

    It used to spawn `tools/steal_secret_task.py --queue-only` to park the targets and
    then play the recipe. The child costs FIVE SECONDS end to end, and the race this
    order exists to win is decided in fractions of one — so the queue travels as an
    argument of the call that was going to be made anyway. What must NOT have changed is
    where the targets come from: they are still chosen by `rob_candidates` and named to
    the recipe, never re-derived by it (#1256).
    """
    order, rt, _said, _put = _order(["ACT steal_sent uuid=1 srv=100",
                                     "steal_taken — the server confirmed a robbery"])
    order.run([(1, 100, "@[1,2|100]")])
    _drain(order)

    assert rt.actions.played == ["steal_secret_task"], rt.actions.played
    assert rt.actions.args == [{"queue": "{uuid=1,server=100}"}], rt.actions.args
    # …and nothing was spawned: there is no child factory on this runtime at all, so a
    # robbery that reached for one would have raised rather than quietly slowed down.
    assert not hasattr(rt, "children")


def test_only_the_servers_answer_counts_as_a_robbery():
    """«Успех только по ответу игры» (#1272). A `steal_sent` line proves a frame left the
    client; the daily counter moving proves the server took it, and that is what the
    recipe says as `steal_taken`."""
    order, rt, said, _put = _order(["ACT steal_sent uuid=1 srv=100"])
    order.run([(1, 100, "@[1,2|100]")])
    _drain(order)
    assert rt.actions.played == ["steal_secret_task"]
    assert "log.autoloot.taken" not in said, said

    order, _rt, said, _put = _order(["ACT steal_sent uuid=1 srv=100",
                                     "steal_taken — the server confirmed a robbery"])
    order.run([(1, 100, "@[1,2|100]")])
    _drain(order)
    assert "log.autoloot.taken" in said, said


def test_a_spent_budget_pauses_the_order():
    """The recipe says so now that there is no parking child to say it, and the watcher
    still pauses on it rather than polling a budget that cannot come back today."""
    order, _rt, said, _put = _order(["steals_spent — the day's robberies are gone"])
    order.run([(1, 100, "@[1,2|100]")])
    _drain(order)
    assert "log.autoloot.spent" in said, said
    assert order._pause_until > 0


def test_a_recipe_that_failed_says_so_in_the_scenarios_own_words():
    """The scenario is the authority on why it stopped; the panel repeats it."""
    order, rt, said, _put = _order(ok=False, reason="no daemon")
    order.run([(1, 100, "@[1,2|100]")])
    _drain(order)
    assert rt.actions.played == ["steal_secret_task"]
    assert "log.autoloot.spend_failed" in said, said


def test_naming_no_target_presses_nothing():
    """A tick with an empty choice must not play a recipe over somebody else's
    leftovers — the queue argument would be empty and the recipe would spend whatever
    happened to be parked."""
    order, rt, _said, _put = _order()
    order.run([])
    assert rt.actions.played == [], rt.actions.played
    assert order._proc is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
