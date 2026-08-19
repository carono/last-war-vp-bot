r"""THE RULE FOR EVERY RECEIVER IN THE PANEL: an accepted event is processed or queued,
never discarded (#1523).

WHAT THIS FILE IS FOR. The operator's report was one sentence and it named a class rather
than a page: «обход карты работает, но не все монстры добавляются в грид, события
проглатываются и не обрабатываются. Это вообще повсеместная проблема.» Every receiver
that had the fault had it in the same SHAPE — an early `return` at the top, guarded by
whether anybody happened to be looking at the tab:

    def refresh_world(self):
        if not self.loaded:          # <- the whole bug, four times over
            return

A lap of the map decoded 25 563 tiles and 7 994 mines into the checkpoint, and with the
tab shut not one of them was merged; the monster read, whose source leaves NOTHING on
disk behind it, threw away the only copy there was. #1476 took this shape out of the ★
tiles and left it standing on the other four doors, which is exactly why a class needs a
test and not four fixes.

So what is pinned here is the class, not a page:

  * the ledger itself — four numbers per receiver, `lost` separate from `dropped`,
    because a deliberate refusal with a reason and a silent throw-away are different
    facts and the whole diagnosis turns on telling them apart;
  * a tab that NOBODY HAS OPENED still merges everything its receivers are handed:
    the world checkpoint, the ghost map, the monsters, the ★ tiles;
  * a receiver that is BUSY declines rather than loses — the event is accounted for;
  * a receiver whose source is DEAD (a torn checkpoint, a client that is not in the
    world) says so and is counted, instead of looking exactly like an empty map;
  * and «Занятость» draws the lot, with a verdict at ANY loss — every other verdict in
    that block is a threshold, and this one is not, because there is no ordinary number
    of thrown-away events.

Needs no display; the tab half imports Tk:

    python3 tests/test_panel_intake.py
"""
from __future__ import annotations

TIER = "ui"        # imports Tk (the tab is a widget), but needs no display

import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import busy as busymod                    # noqa: E402
from panel.runtime import intake as intakemod                # noqa: E402


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------
def test_a_receiver_keeps_four_numbers_and_they_do_not_run_together():
    led = intakemod.Intake()
    take = led.at("world.monsters")
    take.seen(10)
    take.kept(7)
    take.dropped(2, reason="home_server")
    take.lost(1, reason="tab_closed")
    row = led.report()[0]
    assert row["what"] == "world.monsters"
    assert (row["seen"], row["kept"], row["dropped"], row["lost"]) == (10, 7, 2, 1)
    # The two reason books are separate on purpose: one says what the receiver FILTERS,
    # the other says what is BROKEN, and merging them is how a filter starts reading as
    # a fault.
    assert row["reasons"] == {"home_server": 2}
    assert row["losses"] == {"tab_closed": 1}


def test_a_drop_with_no_reason_is_still_recorded():
    """A lazy caller must not be able to make a loss invisible — that is the whole point."""
    led = intakemod.Intake()
    led.lost("secret.tiles")
    row = led.report()[0]
    assert row["lost"] == 1
    assert row["losses"] == {intakemod.UNKNOWN: 1}


def test_the_losing_receiver_is_reported_first():
    led = intakemod.Intake()
    led.at("a.quiet").seen(1000)
    led.at("a.quiet").kept(1000)
    led.at("z.losing").seen(2)
    led.at("z.losing").lost(2, reason="torn")
    assert [row["what"] for row in led.report()] == ["z.losing", "a.quiet"]
    assert led.lost_total() == 2


def test_zero_and_negative_counts_never_create_a_row():
    """A receiver that was handed nothing is not a receiver with a zero — it is silent."""
    led = intakemod.Intake()
    led.seen("nothing", 0)
    led.lost("nothing", -5)
    assert led.report() == []


def test_a_profile_switch_empties_the_ledger():
    """Another account's receivers are not this one's (`CLAUDE.md`, #1306)."""
    led = intakemod.Intake()
    led.at("secret.tiles").seen(25_563)
    led.clear()
    assert led.report() == []
    assert led.lost_total() == 0


def test_a_runtime_without_a_ledger_is_handed_one_that_counts_nothing():
    """So no receiver ever writes `if self.rt.intake is not None` — which is the shape
    that lets an instrumented path quietly stop being instrumented."""
    bare = types.SimpleNamespace()
    take = intakemod.of(bare).at("world.monsters")
    take.seen(5)
    take.lost(5, reason="whatever")          # must not raise, must not count
    assert intakemod.of(bare).report() == []
    real = types.SimpleNamespace(intake=intakemod.Intake())
    intakemod.of(real).at("x").seen(1)
    assert intakemod.of(real).report()[0]["seen"] == 1


# ---------------------------------------------------------------------------
# «Занятость» — a loss must be visible at once, not a day later
# ---------------------------------------------------------------------------
def test_the_snapshot_carries_the_ledger():
    rt = _Runtime()
    rt.intake.at("world.checkpoint").seen(7_994)
    rt.intake.at("world.checkpoint").kept(7_994)
    snap = busymod.snapshot(rt)
    assert "intake" in snap, "the busy snapshot lost the receivers section"
    assert snap["intake"][0]["what"] == "world.checkpoint"


def test_one_lost_event_is_already_a_verdict():
    """Every other verdict in that block is a THRESHOLD — a claim held a while, a queue
    a bit deep, all of them things a busy panel does legitimately. This one is not."""
    rt = _Runtime()
    rt.intake.at("world.monsters").seen(1)
    rt.intake.at("world.monsters").lost(1, reason="tab_closed")
    keys = [v["key"] for v in busymod.verdicts(busymod.snapshot(rt))]
    assert "busy.jam.lost" in keys, keys


def test_a_deliberate_drop_is_not_a_verdict():
    """Three tiles in four on a real map are plain ones nobody will ever raid — a
    receiver saying so is working, not failing."""
    rt = _Runtime()
    rt.intake.at("secret.tiles").seen(277)
    rt.intake.at("secret.tiles").dropped(236, reason="not_starred")
    rt.intake.at("secret.tiles").kept(41)
    keys = [v["key"] for v in busymod.verdicts(busymod.snapshot(rt))]
    assert "busy.jam.lost" not in keys, keys


def test_the_busy_block_has_a_grid_for_the_receivers():
    from panel.tabs.develop_busy import GROUPS, SECTIONS

    assert "intake" in SECTIONS, SECTIONS
    groups = {key: columns for key, _title, _sections, columns in GROUPS}
    assert "intake" in groups, sorted(groups)
    fields = {field for field, *_rest in groups["intake"]}
    # The four numbers the report is read from have to be ON the grid, or the ledger is
    # a thing only a test can see.
    assert {"seen", "kept", "dropped", "lost"} <= fields, fields


def test_every_word_the_receivers_grid_says_is_a_locale_key():
    """`CLAUDE.md`: not one word of the panel is written in the panel."""
    import json

    words = json.loads((_REPO / "panel" / "locales" / "en.json").read_text("utf-8"))
    from panel.tabs.develop_busy import GROUPS

    for key, title, _sections, columns in GROUPS:
        if key != "intake":
            continue
        assert title in words, title
        for _field, head, *_rest in columns:
            assert head in words, head
    for key in ("busy.section.intake", "busy.intake.line", "busy.intake.losing",
                "busy.intake.never", "busy.intake.quiet", "busy.intake.taking",
                "busy.jam.lost"):
        assert key in words, key


# ---------------------------------------------------------------------------
# THE CLASS: a receiver does not need anybody to be looking
# ---------------------------------------------------------------------------
def test_no_receiver_is_gated_on_somebody_looking_at_the_tab():
    """The SHAPE of the bug, read straight off the source (#1476, #1523).

    Four receivers opened with `if not self.loaded: return` and each one threw away what
    it was handed while the tab was shut. A merge is a file read and a dict write; only
    the DRAWING needs a window, and every grid's `render` already skips without a tree.
    Pinned as a source check because that is the only way to catch the fifth one somebody
    adds next year.
    """
    import ast

    source = (_REPO / "panel" / "tabs" / "secret_tasks" / "tab.py").read_text("utf-8")
    tree = ast.parse(source)
    receivers = {"refresh_world", "refresh_ghost_map", "_read_monsters",
                 "_tiles_land", "_areas_land", "tile_seen", "area_seen"}
    guarded = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in receivers:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.If):
                continue
            for name in ast.walk(inner.test):
                if isinstance(name, ast.Attribute) and name.attr == "loaded":
                    guarded.append(node.name)
    assert not guarded, f"receivers still wait for somebody to look: {sorted(set(guarded))}"


def test_the_world_checkpoint_merges_with_the_tab_shut():
    tab, rt = _tab()
    tab.loaded = False                       # nobody has ever opened it
    merged: list = []
    for page in (tab.mines, tab.trains, tab.trucks):
        page.apply = lambda records, _p=page: merged.append((_p, len(records)))
    _run_sync(lambda: tab.refresh_world())
    assert sum(n for _p, n in merged) == 3, merged
    row = _row_for(rt, "world.checkpoint")
    assert (row["seen"], row["kept"], row["lost"]) == (3, 3, 0), row


def test_a_torn_checkpoint_is_a_loss_and_says_so():
    """«Пусто» and «не смог прочитать» are different facts (#1296) — and the second one
    is now a NUMBER as well as a line, because a line said once is a line missed once."""
    tab, rt = _tab(checkpoint=ValueError("mid-write"))
    _run_sync(lambda: tab.refresh_world())
    row = _row_for(rt, "world.checkpoint")
    assert row["lost"] == 1 and row["losses"] == {"torn": 1}, row
    assert tab.said and tab.said[0][0] == "log.world.unreadable", tab.said


def test_a_checkpoint_that_was_never_written_is_not_a_loss():
    """Nothing was ever handed over, so nothing was thrown away. A capture that has not
    run yet is a switch to flip, not a bug — and mislabelling it would bury the real one."""
    tab, rt = _tab(checkpoint=OSError("no such file"))
    _run_sync(lambda: tab.refresh_world())
    assert _row_for(rt, "world.checkpoint") is None
    assert tab.said and tab.said[0][0] == "log.world.no_file", tab.said


def test_the_ghost_map_merges_with_the_tab_shut():
    tab, rt = _tab()
    tab.loaded = False
    landed: list = []
    tab.ghost_map.landed = lambda status, rows: landed.append(len(rows))
    _run_sync(lambda: tab.refresh_ghost_map())
    assert landed == [2], landed
    row = _row_for(rt, "ghost.map")
    assert (row["seen"], row["kept"], row["lost"]) == (2, 2, 0), row


def test_the_monsters_are_read_with_the_tab_shut():
    """THE ONE PAGE WITH NO FILE BEHIND IT. The other three come back out of the
    capture's own checkpoint whenever anybody next looks; a monster read leaves nothing
    on disk, so what a shut tab dropped was the only copy there was."""
    tab, rt = _tab()
    tab.loaded = False
    _run_sync(lambda: tab._read_monsters())
    assert tab.monsters.applied and len(tab.monsters.applied[0]) == 2, tab.monsters.applied
    row = _row_for(rt, "world.monsters")
    assert (row["seen"], row["kept"], row["lost"]) == (2, 2, 0), row
    assert tab.said and tab.said[0][0] == "log.monsters.read", tab.said


def test_a_client_that_is_not_in_the_game_says_so_instead_of_showing_an_empty_map():
    """Measured live (#1523): with the client in the BASE there is no `WorldScene` at
    all, so nothing is drawn and nothing can be read — and the panel used to answer that
    with the same blank page a genuinely empty patch of map gets. Four different facts,
    one silence; now each is a reason and a line."""
    tab, rt = _tab(game_ready=False)
    _run_sync(lambda: tab._read_monsters())
    assert tab.said and tab.said[0][0] == "log.monsters.unread", tab.said
    assert tab.said[0][1]["why"] == "no_game", tab.said
    # NOT a loss: nothing was ever handed over. What was lost is what the read never got
    # the chance to see, and that is counted where it happens — at the reader.
    assert _row_for(rt, "world.monsters") is None


def test_a_second_monster_read_declines_and_is_accounted_for():
    """Busy is an ANSWER, not a silence: the event is on the ledger with its reason."""
    tab, rt = _tab()
    tab._monster_busy = True
    tab._read_monsters()
    row = _row_for(rt, "world.monsters")
    assert (row["dropped"], row["lost"]) == (1, 0), row
    assert row["reasons"] == {"already_reading": 1}


def test_a_tile_off_the_sniffer_is_counted_at_the_door():
    tab, rt = _tab()
    tab.tile_seen({"uuid": "1000000000000001", "cfg": 60001, "server": 1, "x": 1, "y": 2})
    tab.tile_seen({"uuid": "", "cfg": 60001})            # a torn record — declined
    row = _row_for(rt, "secret.tiles")
    assert (row["seen"], row["dropped"], row["lost"]) == (2, 1, 0), row
    assert row["reasons"] == {"no_uuid": 1}


def test_a_region_the_server_answered_about_is_counted_too():
    tab, rt = _tab()
    tab.area_seen({"server": 1, "x0": 0, "y0": 0, "x1": 9, "y1": 9, "at": 1.0,
                   "uuids": ["1000000000000001"]})
    tab.area_seen({"server": 0, "x0": 0, "y0": 0, "x1": 9, "y1": 9})   # no warzone
    tab.area_seen({"server": 1})                                       # malformed
    row = _row_for(rt, "secret.areas")
    assert (row["seen"], row["kept"], row["dropped"], row["lost"]) == (3, 1, 2, 0), row
    assert row["reasons"] == {"no_server": 1, "malformed": 1}


# ---------------------------------------------------------------------------
# THE LAP THAT FILLS THE MONSTER PAGE — the pace, the heights, and the harvest
# ---------------------------------------------------------------------------
def test_the_lap_can_pick_the_monsters_up_and_says_so_only_when_asked():
    """`HARVEST` is a flag on the lap, and OFF unless a recipe asks (#1523).

    The ★ lap is timed in fractions of a second and must stay exactly what it was: a
    sampler scheduled beside its waypoints would be a cost on the one lap that cannot
    afford one. So the monster lap asks and the others do not.
    """
    import lua_actions

    picked = lua_actions.fast_map_sweep(zoom=600, step=90, interval=1.2, server=1,
                                        harvest=True)
    plain = lua_actions.fast_map_sweep(zoom=600, step=90, interval=0.05, server=1)
    assert "__lw_sample" in picked
    assert "dynamicObj" in picked, "the sampler stopped walking the node it was measured on"
    assert "__lw_sample" not in plain, "the ★ lap grew a sampler"


def test_the_sampler_looks_the_node_up_again_every_time():
    """The bug that made the first measurement of this nonsense (#1523).

    Caching the `dynamicObj` transform in a global and reusing it is what turned a lap
    that was really collecting thirty monsters into one that reported two: the handle
    goes stale when the scene churns and every later sample walked a destroyed object.
    """
    import lua_actions

    body = lua_actions.MONSTER_SAMPLER
    assert body.count("FindObjectsOfType") == 1, body
    assert "_G.__lw_dyn" not in body, "the sampler is caching the node again"


def test_the_monster_lap_is_a_scenario_with_the_pace_as_an_argument():
    import pathlib

    from lastwar_bot import script_engine as se

    text = (_REPO / "src" / "lastwar_bot" / "actions"
            / "scan_map_monsters.md").read_text("utf-8")
    defaults, rest = se.extract_defaults(text)
    # The four the panel passes, and `every` among them: the pace is the whole quantity
    # and it may not be a constant in the recipe either.
    assert {"server", "zoom", "step", "every"} <= set(defaults), defaults
    program = se.parse_text(se.substitute(rest, defaults))
    sweeps = [st for st in program if type(st).__name__ == "SweepMapStmt"]
    assert len(sweeps) == 1 and sweeps[0].harvest, sweeps
    # …and the default is the measured one, not a number somebody liked: below ~1 s the
    # client's region loader does not keep up and the same lap collects tens.
    assert float(defaults["every"]) >= 1.0, defaults["every"]


def test_the_page_owns_the_pace_and_the_heights_and_saves_them():
    from panel.tabs.secret_tasks.world import MonsterGrid

    page = object.__new__(MonsterGrid)
    page.pace_var, page.stages_var = _Var("2.5"), _Var("300, 600")
    assert page.pace() == 2.5
    assert page.stages() == [(300, 45), (600, 90)]
    # A blank or nonsense box is a person who has not chosen, never a lap that collects
    # nothing while looking like it worked.
    page.pace_var, page.stages_var = _Var(""), _Var("")
    assert page.pace() == float(MonsterGrid.DEFAULT_PACE)
    assert page.stages() == [(600, 90)]
    # …and a height nobody has a step for is walked with the nearest one that has: a step
    # from another height is a lap with holes in it.
    page.stages_var = _Var("1000")
    assert page.stages() == [(1000, MonsterGrid.STAGE_STEPS[900])]


def test_the_lap_reaches_the_phone_as_well_as_the_window():
    """`CLAUDE.md`: an edit travels between the window and the web, in BOTH directions."""
    import ast

    source = (_REPO / "panel" / "tabs" / "secret_tasks" / "tab.py").read_text("utf-8")
    assert '"id": "sweep_monsters"' in source, "the phone cannot start the lap"
    assert '"world.monsters.pace"' in source, "the phone cannot see the pace it walks at"
    assert '"world.monsters.stages"' in source, "…nor the heights"
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "sweep_monsters" in names, "the window has no button behind it"
    world = (_REPO / "panel" / "tabs" / "secret_tasks" / "world.py").read_text("utf-8")
    assert '"world.monsters.sweep"' in world, "the window's own button is missing"


class _Var:
    """A stand-in for a Tk variable — just `.get()` / `.set()`."""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


# ---------------------------------------------------------------------------
# stand-ins
# ---------------------------------------------------------------------------
class _Widget:
    """Enough of a Tk widget for `Ticker`: after / after_cancel, and no event loop."""

    def __init__(self) -> None:
        self.jobs: dict = {}
        self._next = 0

    def after(self, _delay, func):
        self._next += 1
        self.jobs[self._next] = func
        return self._next

    def after_cancel(self, job) -> None:
        self.jobs.pop(job, None)


class _Profiles:
    def __init__(self, name: str = "alice") -> None:
        self.active = name

    def world_json(self) -> str:
        return "/nowhere/world_map.json"

    def ghost_json(self) -> str:
        return "/nowhere/ghost_recon_tiles.json"


class _Runtime:
    """A profile's runtime as the busy snapshot and a receiver see one."""

    def __init__(self, game_ready: bool = True) -> None:
        self.intake = intakemod.Intake()
        self.profiles = _Profiles()
        self.root = _Widget()
        self.game = types.SimpleNamespace(ready=lambda: game_ready,
                                          endpoint=lambda: "")
        self.actions = types.SimpleNamespace(play=lambda *a, **k: None)
        self.interrupts = None
        self.activity = None
        self.tick = None

    def dbg(self, _tag):
        return types.SimpleNamespace(warning=lambda *a, **k: None,
                                     error=lambda *a, **k: None)


class _Page:
    """One world page: it only has to accept a merge and remember it."""

    def __init__(self) -> None:
        self.applied: list = []

    def apply(self, records) -> None:
        self.applied.append(list(records or ()))


def _tab(checkpoint=None, game_ready: bool = True):
    """A `SecretTasksTab` with nothing of Tk about it — the file's own idiom (#1135)."""
    from panel.tabs.secret_tasks import tab as st
    from panel.tabs.secret_tasks import world as worldmod

    tab = object.__new__(st.SecretTasksTab)
    rt = _Runtime(game_ready=game_ready)
    tab.rt = rt
    tab.loaded = True
    tab._busy = False
    tab._monster_busy = False
    tab._monsters_said = None
    tab._world_said = None
    tab._own_server = 935
    tab._ghost_config = {}
    tab.said: list = []
    tab.say = lambda _tag, key, **fmt: tab.said.append((key, fmt))
    tab.after = lambda call: call()
    tab.post = lambda call: call()
    tab.mines, tab.trains, tab.trucks = _Page(), _Page(), _Page()
    tab.monsters = _Page()
    tab.ghost_map = types.SimpleNamespace(status={}, landed=lambda status, rows: None)
    tab._tiles, tab._areas = {}, []

    import threading as _threading
    tab._tiles_lock = _threading.Lock()
    tab._tiles_soon = lambda: None
    tab._areas_soon = lambda: None

    # The two sources this tab reads, replaced with answers of the right SHAPE and made-up
    # values (`CLAUDE.md`: a fixture is written by hand, never pasted off a live reply).
    import lastwar_proto as proto

    if isinstance(checkpoint, Exception):
        def _load(_path):
            raise checkpoint
    else:
        def _load(_path):
            return {"mines": [{"uuid": "1", "x": 1, "y": 1}],
                    "trains": [{"uuid": "2", "x": 2, "y": 2}],
                    "trucks": [{"uuid": "3", "x": 3, "y": 3}]}
    proto.load_checkpoint = _load
    worldmod.mine_records = lambda raw: list(raw or ())
    worldmod.train_records = lambda raw: list(raw or ())
    worldmod.truck_records = lambda raw: list(raw or ())
    worldmod.parse_monsters = lambda text, server=None: (
        [{"uuid": "%s:1" % server, "point_id": 1},
         {"uuid": "%s:2" % server, "point_id": 2}] if text else [])

    ghost = types.ModuleType("ghost_recon_steal")
    ghost.map_roster = lambda path, cfg: [{"uuid": "g1"}, {"uuid": "g2"}]
    ghost.alliance_roster = lambda ev: []
    sys.modules["ghost_recon_steal"] = ghost

    rt.actions = types.SimpleNamespace(
        play=lambda *a, **k: types.SimpleNamespace(
            ok=True, ctx=types.SimpleNamespace(vars={"monsters": "src=scene pid=1"})))
    return tab, rt


def _run_sync(call) -> None:
    """Run a receiver whose work is on a worker thread, HERE, and wait for nothing.

    The receivers spawn a thread and the test wants the answer; swapping the module's
    `threading` for a stand-in that runs the target inline is the smallest thing that
    keeps the production code exactly as it ships.
    """
    from panel.tabs.secret_tasks import tab as st

    class _Now:
        def __init__(self, target=None, daemon=False, **_kw) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    import threading as _threading

    was = st.threading
    # The MODULE NAME in the tab is rebound, never `threading.Thread` itself: mutating
    # the real module would reach every other thread in the interpreter, including the
    # ones a test running beside this one is using.
    st.threading = types.SimpleNamespace(Thread=_Now, Lock=_threading.Lock,
                                         Event=_threading.Event)
    try:
        call()
    finally:
        st.threading = was


def _row_for(rt, what: str):
    for row in rt.intake.report():
        if row["what"] == what:
            return row
    return None


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    bad = 0
    for t in tests:
        try:
            t()
            print("  ok  ", t.__name__)
        except Exception as exc:                  # noqa: BLE001 — a test runner
            bad += 1
            print("  FAIL", t.__name__, "->", exc)
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
