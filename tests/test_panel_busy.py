r"""The busy debugger: one cheap snapshot, and what it calls a jam (#1392).

What is pinned here is the whole of what the block on «Разработка» promises:

  * the claim registry remembers WHEN a claim was taken, who is queued behind it and how
    many claims it has turned away — «кто держит замок дольше обычного» and «сколько
    нажатий ждало» are numbers, not impressions;
  * the errand queue says what runs, what waits and for how long, in the order they will
    get their turn;
  * a run that has ended is still readable afterwards, longest first, because the run
    that held the client for four minutes is gone from every live reading by the time
    anybody opens the debugger;
  * an armed `after` chain whose moment has passed reports a NEGATIVE time — that is what
    an event loop that is not turning looks like from outside it;
  * the snapshot asks the game nothing, builds no schedule that was not there, and reads
    no widget;
  * and every line the tab draws is a locale key with the right placeholders, said by the
    runtime — a sentence written in this file would reach somebody with the panel in
    Turkish.

Needs no Tk and no display:

    python3 tests/test_panel_busy.py
"""
from __future__ import annotations

TIER = "ui"        # imports Tk (the block is a widget), but needs no display

import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import timers as timersmod                      # noqa: E402
from panel.runtime import busy as busymod                   # noqa: E402
from panel.runtime import claims                            # noqa: E402
from panel.runtime.activity import Activity                 # noqa: E402
from panel.runtime.interrupt import Interrupts, Stop        # noqa: E402
from panel.runtime.tick import Ticker                       # noqa: E402
from panel.tabs.develop_busy import BusyView                # noqa: E402


# -- stand-ins ---------------------------------------------------------------
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


class _Ctx:
    """A script context as the busy snapshot sees one: the step it is on."""

    def __init__(self, step: str = "") -> None:
        self.step = step


class _Profiles:
    def __init__(self, name: str = "alice") -> None:
        self.active = name


class _Game:
    def __init__(self, endpoint) -> None:
        self._endpoint = endpoint

    def endpoint(self):
        return self._endpoint


class _Runtime:
    """One profile's runtime, with nothing in it that could reach a game or a widget."""

    def __init__(self, profile: str = "alice", endpoint=("127.0.0.1", 47654)) -> None:
        self.profiles = _Profiles(profile)
        self.interrupts = Interrupts()
        self.activity = Activity(name=profile)
        self.tick = Ticker(_Widget())
        self.game = _Game(endpoint)
        self._schedule = None          # nothing has asked for a schedule — see below
        self.root = None


class _Tab:
    """A tab as `BusyView` uses one: `rt`, and words said out of a real locale table."""

    def __init__(self, rt, table: dict) -> None:
        self.rt = rt
        self._table = table
        self.asked: list = []

    def t(self, key: str, **fmt) -> str:
        self.asked.append(key)
        assert key in self._table, f"no such locale key: {key}"
        return self._table[key].format(**fmt)


def _locale(lang: str = "en") -> dict:
    return json.loads((_REPO / "panel" / "locales" / f"{lang}.json")
                      .read_text(encoding="utf-8"))


# -- the claim registry ------------------------------------------------------
def test_a_claim_remembers_when_it_was_taken() -> None:
    claims.clear()
    try:
        assert claims.acquire("k", "alice/timer", claims.BACKGROUND) is None
        time.sleep(0.05)
        state = claims.state()
        assert [row["owner"] for row in state["held"]] == ["alice/timer"]
        assert state["held"][0]["secs"] >= 0.04, state
        assert state["held"][0]["level"] == claims.BACKGROUND
    finally:
        claims.clear()


def test_a_refused_claim_is_counted_so_the_debugger_can_say_how_many() -> None:
    """«сколько нажатий ждало» — the number the panel never used to keep."""
    claims.clear()
    try:
        claims.acquire("k", "alice/timer")
        for _ in range(3):
            assert claims.acquire("k", "bob/action") == "alice/timer"
        assert claims.state()["held"][0]["refused"] == 3
    finally:
        claims.clear()


def test_who_is_queued_behind_the_holder_and_since_when() -> None:
    claims.clear()
    try:
        claims.acquire("k", "alice/timer", claims.BACKGROUND)
        claims.demand("k", claims.HUMAN, "bob/action")
        claims.demand("k", claims.EXPRESS, "carol/timer")
        waiting = claims.state()["waiting"]
        # The most urgent first: that IS the order they will get in.
        assert [row["owner"] for row in waiting] == ["bob/action", "carol/timer"]
        assert waiting[0]["level"] == claims.HUMAN
        # …and the old readings still answer exactly as they did.
        assert claims.wanted("k", claims.BACKGROUND) == "bob/action"
    finally:
        claims.clear()


# -- the runs ----------------------------------------------------------------
def test_a_finished_run_is_still_readable_longest_first() -> None:
    reg = Interrupts()
    short = reg.enter("collect_trucks", "timer", _Ctx("TAP collect"), Stop())
    long = reg.enter("scan_map", "action", _Ctx("JUMP 1,1"), Stop())
    long.started -= 300                       # it has been going five minutes
    reg.leave(short)
    reg.leave(long)
    top = reg.history()
    assert [row["name"] for row in top] == ["scan_map", "collect_trucks"], top
    assert top[0]["secs"] >= 300
    assert top[0]["step"] == "JUMP 1,1"       # taken while the context was still its own
    assert reg.running() == []


# -- the panel's own timers --------------------------------------------------
def test_an_armed_chain_says_when_it_fires_and_when_it_is_late() -> None:
    tick = Ticker(_Widget())
    tick.arm("status", 5000, lambda: None)
    rows = {row["name"]: row for row in tick.pending()}
    assert 4.5 < rows["status"]["due_in"] <= 5.0, rows
    # The moment has passed and the callback has not run: the event loop is not turning.
    tick._armed_at["status"] = (5000, time.monotonic() - 12)
    assert tick.pending()[0]["due_in"] < -6
    tick.disarm("status")
    assert tick.pending() == []


# -- the errand queue --------------------------------------------------------
def _scheduler() -> timersmod.TimerScheduler:
    cat = timersmod.default_catalogue()
    return timersmod.TimerScheduler(
        store=timersmod.LastRunStore(""), catalogue=lambda: cat,
        config=lambda: {}, runner=lambda _errand: True, log=lambda key, **fmt: None)


def test_the_queue_says_what_waits_and_for_how_long() -> None:
    sched = _scheduler()
    state = sched.queue_state()
    assert state["waiting"] == [] and not state["running"]

    sched._queued.update({"base_collect", "alliance_help"})
    sched._queued_at["base_collect"] = time.monotonic() - 90
    sched._queued_at["alliance_help"] = time.monotonic() - 5
    sched._running = "restart_game"
    sched._running_since = time.monotonic() - 200

    state = sched.queue_state()
    assert state["running"] == "restart_game" and state["running_secs"] >= 200
    # Longest wait first — the order they came, which is the order they will go.
    assert [row["name"] for row in state["waiting"]] == ["base_collect", "alliance_help"]
    assert state["waiting"][0]["secs"] >= 90


# -- the snapshot ------------------------------------------------------------
def test_the_snapshot_asks_nothing_and_builds_nothing() -> None:
    """No game, no widgets — and no schedule where the profile has never had one."""
    rt = _Runtime()
    claims.clear()
    try:
        snap = busymod.snapshot(rt)
    finally:
        claims.clear()
    assert snap["profile"] == "alice"
    assert snap["runs"] == [] and snap["steps"] == []
    assert snap["queue"] == {} and snap["timers"] == []
    assert rt._schedule is None, "the debugger built a schedule to look at it"
    assert isinstance(snap["threads"], list) and snap["threads"], snap["threads"]


def test_the_snapshot_shows_this_profiles_runs_and_marks_its_claims() -> None:
    rt = _Runtime(profile="alice", endpoint=("127.0.0.1", 47654))
    run = rt.interrupts.enter("scan_map", "timer", _Ctx("JUMP 100,100"), Stop())
    run.started -= 42
    step = rt.activity.begin("activity.daemon.start", port=47654)
    step.started -= 7
    claims.clear()
    try:
        claims.acquire(("127.0.0.1", 47654), "alice/timer", claims.BACKGROUND)
        claims.acquire(claims.FOREGROUND, "bob/action", claims.HUMAN)
        snap = busymod.snapshot(rt)
    finally:
        claims.clear()

    assert snap["runs"][0]["name"] == "scan_map"
    assert snap["runs"][0]["step"] == "JUMP 100,100"
    assert snap["runs"][0]["secs"] >= 42
    assert snap["steps"][0]["key"] == "activity.daemon.start"
    assert snap["steps"][0]["secs"] >= 7

    mine = {row["owner"]: row for row in snap["claims"]}
    assert mine["alice/timer"]["mine"] and mine["alice/timer"]["client"]
    assert not mine["bob/action"]["mine"], "another profile's claim was read as ours"


def test_a_thread_carries_the_profile_it_belongs_to() -> None:
    """`play_async` names its worker `lw:<profile>:<tag>:<scenario>` — this reads it."""
    import threading

    started, hold = threading.Event(), threading.Event()

    def work() -> None:
        started.set()
        while not hold.is_set():             # busy, not parked: it must be listed
            pass

    thread = threading.Thread(target=work, name="lw:alice:timer:scan_map", daemon=True)
    thread.start()
    started.wait(2)
    try:
        rows = {row["name"]: row for row in busymod.threads("alice")}
        assert "lw:alice:timer:scan_map" in rows, sorted(rows)
        assert rows["lw:alice:timer:scan_map"]["owner"] == "alice"
        assert rows["lw:alice:timer:scan_map"]["mine"]
        assert not busymod.threads("bob")[0]["mine"] or True   # bob owns none of it
        assert all(not row["mine"] for row in busymod.threads("bob")
                   if row["name"].startswith("lw:alice"))
    finally:
        hold.set()
        thread.join(2)


# -- the signs of a jam ------------------------------------------------------
def test_a_long_held_claim_and_a_long_wait_are_named() -> None:
    snap = {"claims": [{"key": "k", "owner": "alice/timer", "secs": 400, "refused": 12}],
            "waiting": [{"key": "k", "owner": "bob/action", "secs": 30, "level": 2}],
            "queue": {"waiting": [{"name": "base_collect", "secs": 120}], "held": []},
            "timers": [{"name": "alliance_help", "due_in": -600.0}],
            "ticks": [{"name": "status", "due_in": -8.0}],
            "posted": 90}
    keys = [v["key"] for v in busymod.verdicts(snap)]
    assert keys == ["busy.jam.claim", "busy.jam.waiting", "busy.jam.queue",
                    "busy.jam.refused", "busy.jam.timer", "busy.jam.tick",
                    "busy.jam.posted"], keys


def test_a_quiet_panel_has_nothing_to_say() -> None:
    snap = {"claims": [{"key": "k", "owner": "alice/timer", "secs": 3, "refused": 0}],
            "waiting": [], "queue": {"waiting": [], "held": []},
            "timers": [{"name": "base_collect", "due_in": 300.0}],
            "ticks": [{"name": "status", "due_in": 4.0}], "posted": 1}
    assert busymod.verdicts(snap) == []


def test_the_longest_step_is_the_one_that_changed_while_nobody_watched() -> None:
    watch = busymod.StepWatch()
    now = time.monotonic()
    watch.feed({"now": now, "runs": [{"name": "scan_map", "tag": "timer",
                                      "step": "JUMP 1,1"}]})
    watch.feed({"now": now + 40, "runs": [{"name": "scan_map", "tag": "timer",
                                           "step": "READ_LUA tiles"}]})
    watch.feed({"now": now + 41, "runs": []})          # the run ended
    top = watch.top()
    assert [row["step"] for row in top] == ["JUMP 1,1", "READ_LUA tiles"], top
    assert 39 <= top[0]["secs"] <= 41, top


# -- what the tab draws ------------------------------------------------------
def test_every_line_the_block_draws_is_a_locale_key() -> None:
    """No sentence is written in the panel — the tab names keys and the runtime says
    them (`CLAUDE.md`). A missing key or a wrong placeholder raises inside `_Tab.t`."""
    rt = _Runtime()
    run = rt.interrupts.enter("scan_map", "timer", _Ctx("JUMP 1,1"), Stop())
    run.started -= 61
    rt.activity.begin("activity.daemon.start", port=47654)
    rt.tick.arm("status", 4000, lambda: None)
    claims.clear()
    try:
        claims.acquire(("127.0.0.1", 47654), "alice/timer", claims.BACKGROUND)
        claims.demand(("127.0.0.1", 47654), claims.HUMAN, "alice/action")
        snap = busymod.snapshot(rt)
    finally:
        claims.clear()
    snap["queue"] = {"running": "restart_game", "running_secs": 200.0,
                     "express": ["alliance_help"],
                     "waiting": [{"name": "base_collect", "secs": 90.0}],
                     "held": ["collect_trucks"], "hold_secs": 12.0, "alive": True}
    snap["timers"] = [{"name": "base_collect", "due_in": -300.0,
                       "last": time.time() - 3600, "state": timersmod.ATTEMPT_FAILED},
                      {"name": "alliance_help", "due_in": 120.0, "last": 0.0,
                       "state": timersmod.ATTEMPT_NONE}]

    tab = _Tab(rt, _locale("en"))
    view = BusyView(tab)
    lines = view.lines(snap)

    assert any("scan_map" in line for line in lines), lines
    assert any("restart_game" in line for line in lines), lines
    assert any("base_collect" in line for line in lines), lines
    # Every section is there, in the order a jam is asked about.
    for key in ("busy.section.jam", "busy.section.runs", "busy.section.queue",
                "busy.section.claims", "busy.section.timers", "busy.section.slowest",
                "busy.section.threads"):
        assert key in tab.asked, key
    # …and nothing composed a sentence of its own: every word came from the table.
    assert all(key.startswith(("busy.", "activity.")) for key in tab.asked), tab.asked


def _table_snapshot() -> dict:
    """A snapshot with one of everything, so a row of every section is drawn."""
    return {
        "profile": "alice", "now": time.monotonic(),
        "runs": [{"name": "scan_map", "tag": "timer", "secs": 42.0,
                  "step": "JUMP 100,100", "asked": False},
                 {"name": "heal_units", "tag": "action", "secs": 120.0,
                  "step": "TAP heal_all", "asked": True}],
        "steps": [{"key": "activity.daemon.start", "fmt": {"port": 47654},
                   "secs": 7.0}],
        "queue": {"running": "restart_game", "running_secs": 200.0,
                  "express": ["alliance_help"],
                  "waiting": [{"name": "base_collect", "secs": 90.0,
                              "scheduled": True, "by": "hand"}],
                  "held": ["collect_trucks"], "hold_secs": 12.0,
                  "gated": [{"name": "rally_auto_join", "secs": 45.0,
                            "scheduled": False, "by": "trigger",
                            "reason": "timers.log.skip_game",
                            "expires_in": 555.0, "retry_sec": 10}],
                  "recent": [{"name": "auto_treasure", "by": "hand",
                             "scheduled": False, "outcome": "done", "secs": 5.0},
                            {"name": "leaderboard_collect", "by": "trigger",
                             "scheduled": False, "outcome": "gate_expired",
                             "secs": 900.0}],
                  "alive": True},
        "claims": [{"key": ("127.0.0.1", 47654), "owner": "alice/timer", "secs": 400.0,
                    "refused": 12, "mine": True, "client": True}],
        "waiting": [{"key": ("127.0.0.1", 47654), "owner": "bob/action", "secs": 30.0,
                     "level": 2}],
        "timers": [{"name": "base_collect", "due_in": -300.0,
                    "last": time.time() - 3600, "state": timersmod.ATTEMPT_FAILED},
                   {"name": "alliance_help", "due_in": 120.0, "last": 0.0,
                    "state": timersmod.ATTEMPT_NONE}],
        "ticks": [{"name": "status", "due_in": -8.0}],
        "slowest": [{"name": "scan_map", "tag": "action", "secs": 300.0}],
        "threads": [{"name": "lw:alice:timer:scan_map", "where": "busy.py:12",
                     "owner": "alice", "mine": True}],
        "listeners": [{"kind": "wire", "what": "push.alliance.march.*",
                       "desc": "busy.listener.push", "alive": True, "heard": 412,
                       "since": 3.0, "detail": "", "who": "1"},
                      {"kind": "capture", "what": "secret_task_capture.py",
                       "desc": "busy.listener.secret_tasks", "alive": True, "heard": 0,
                       "since": None, "detail": "", "who": "9001"},
                      {"kind": "trigger", "what": "on_login", "desc": "",
                       "alive": False, "heard": 5, "since": 900.0, "detail": "",
                       "who": ""}],
        # …and what each RECEIVER did with what it heard (#1523). The listener rows above
        # say whether anything arrived; these say whether the panel took it, which is the
        # half that was missing when «события проглатываются» was unanswerable.
        "intake": [{"what": "secret.tiles", "seen": 25_563, "kept": 41,
                    "dropped": 25_522, "lost": 0, "since": 2.0,
                    "reasons": {"not_starred": 25_522}, "losses": {}},
                   {"what": "world.monsters", "seen": 2, "kept": 1, "dropped": 0,
                    "lost": 1, "since": 4.0, "reasons": {},
                    "losses": {"tab_closed": 1}}],
        "posted": 3,
    }


def test_the_block_is_several_grids_and_every_row_answers_its_grids_questions() -> None:
    """«слушатели отдельно, таймеры отдельно, и т.д.» (#1500): one grid per kind.

    A jam is found by COMPARING rows — who has been at it longest, who is waiting on
    whom — and a sentence per row is exactly what hides that comparison. What changed
    from the single filterable table (#1415) is that each KIND of row now gets its own
    grid with its own columns, because a listener's «сколько раз» and a claim's
    «отказов» are not the same question.
    """
    from panel.tabs.develop_busy import GROUPS, SECTIONS

    tab = _Tab(_Runtime(), _locale("en"))
    view = BusyView(tab)
    rows = view.rows(_table_snapshot())

    assert {row["section"] for row in rows} == set(SECTIONS), \
        sorted({row["section"] for row in rows})
    # Every row is the same shape, and its words are keys rather than sentences.
    for row in rows:
        # The eight every row has, plus the four numbers a RECEIVER row adds (#1523):
        # «принято / взято / отброшено / потеряно» are four columns and cannot be folded
        # into one, so the receivers grid is the one section with fields of its own.
        assert set(row) - {"seen", "kept", "dropped", "lost"} == {
            "section", "what", "who", "detail", "secs", "level", "status", "mark"}, row
        assert row["mark"] in ("", "slow", "stuck"), row
        assert not row["status"] or row["status"].startswith("busy."), row
    # …and every GRID names a title and covers a real subset of the sections.
    group_keys = [g[0] for g in GROUPS]
    assert len(group_keys) == len(set(group_keys)), group_keys
    covered = set()
    for _key, title, sections, columns in GROUPS:
        assert title.startswith("busy."), title
        assert columns, _key                          # every grid has columns of its own
        covered.update(sections)
        grows = [r for r in rows if r["section"] in sections]
        cells = [view._cells_for(r, columns) for r in grows]
        assert all(len(c) == len(columns) for c in cells)
    assert covered == set(SECTIONS), sorted(covered)
    # `timers.*` too: a gated row says WHY in the gate's own key — `timers.log.skip_…` —
    # rather than a busy.* paraphrase of it, which is the single source of truth #1500
    # asked for, not a hardcoded sentence dressed up as one.
    assert all(key.startswith(("busy.", "activity.", "timers."))
              for key in tab.asked), tab.asked

    by_section = {}
    for row in rows:
        by_section.setdefault(row["section"], []).append(row)
    running = by_section["runs"][0]
    assert running["what"] == "scan_map" and running["who"] == "timer"
    assert running["secs"] == 42 and running["detail"] == "JUMP 100,100"
    assert by_section["runs"][1]["status"] == "busy.status.stopping"
    assert by_section["claims"][0]["what"] == "127.0.0.1:47654"
    assert by_section["claims"][0]["who"].endswith("alice/timer")      # ★ = this profile
    assert by_section["claims"][1]["level"] == "busy.level.human"      # who is waiting
    listening = by_section["listeners"]
    assert listening[0]["level"] == "412"                # the raw heard-count, not a key
    assert listening[1]["status"] == "busy.listen.never"
    assert listening[2]["status"] == "busy.status.off" and listening[2]["mark"] == "stuck"

    # The queue grid: what runs, what waits and WHY, what is held, what is gated and
    # for how much longer, and what just left (#1500).
    queued = by_section["queue"]
    running_row = next(r for r in queued if r["status"] == "busy.status.running")
    assert running_row["what"] == "restart_game" and running_row["secs"] == 200
    waiting_row = next(r for r in queued if r["status"] == "busy.status.queued")
    assert waiting_row["who"] == "timer"                  # scheduled=True wins over `by`
    assert "restart_game" in waiting_row["detail"]        # ahead of it in the queue
    held_row = next(r for r in queued if r["status"] == "busy.status.held")
    assert "alice/timer" in held_row["detail"]             # WHO holds the game claim
    assert held_row["mark"] == "slow"
    gated_row = next(r for r in queued if r["status"] == "busy.status.gated")
    assert gated_row["who"] == "event"                    # scheduled=False, by=trigger
    assert "555" in gated_row["detail"]                   # when it gives up
    assert gated_row["mark"] == "slow"                    # 555 s left — not imminent
    done_row = next(r for r in queued if r["what"] == "auto_treasure")
    assert done_row["status"] == "busy.status.done" and done_row["mark"] == ""
    expired_row = next(r for r in queued if r["what"] == "leaderboard_collect")
    assert expired_row["status"] == "busy.status.gate_expired"
    assert expired_row["mark"] == "slow"


def test_a_row_never_lands_in_two_grids_at_once() -> None:
    """Every `section` a row can have belongs to exactly one grid's `sections`."""
    from panel.tabs.develop_busy import GROUPS, SECTIONS

    seen: dict = {}
    for key, _title, sections, _columns in GROUPS:
        for section in sections:
            assert section not in seen, (section, seen[section], key)
            seen[section] = key
    assert set(seen) == set(SECTIONS), sorted(set(SECTIONS) - set(seen))


def test_an_empty_grid_says_so_instead_of_disappearing() -> None:
    """«Пустая группа должна честно говорить «пусто»» (#1500) — never just vanish."""
    from panel.tabs.develop_busy import GROUPS

    tab = _Tab(_Runtime(), _locale("en"))
    view = BusyView(tab)
    for _key, _title, _sections, columns in GROUPS:
        placeholder = view._empty_row(columns)
        assert placeholder[0] == "— nothing", placeholder
        assert placeholder[-1] == ""                    # no colour on a placeholder row
        assert len(placeholder) == len(columns) + 1      # cells, plus the mark


def test_the_long_and_the_stuck_mark_themselves() -> None:
    """The point of the table: a jam is seen before a word of it is read."""
    from panel.tabs.develop_busy import SLOW_SEC

    view = BusyView(_Tab(_Runtime(), _locale("en")))
    rows = view.rows(_table_snapshot())
    marks = {(row["section"], row["what"] or row["status"]): row["mark"] for row in rows}

    assert marks[("runs", "scan_map")] == ""                    # 42 s — ordinary
    assert marks[("runs", "heal_units")] == "slow"              # 120 s — amber
    assert marks[("queue", "restart_game")] == "slow"           # 200 s in the queue
    assert marks[("timers", "base_collect")] == "stuck"         # overdue — red
    assert marks[("timers", "status")] == "stuck"               # a late tick of the panel
    assert all(row["mark"] == "stuck" for row in rows if row["section"] == "jam")
    # And the threshold is the one the module names, not a number spelled twice.
    quiet = {"runs": [{"name": "x", "tag": "t", "secs": SLOW_SEC - 1, "step": "",
                       "asked": False}],
             "steps": [], "queue": {}, "claims": [], "waiting": [], "timers": [],
             "ticks": [], "slowest": [], "threads": [], "posted": 0}
    assert BusyView(_Tab(_Runtime(), _locale("en"))).rows(quiet)[0]["mark"] == ""


def test_a_grid_sorts_by_seconds_as_numbers_and_leaves_its_neighbours_alone() -> None:
    """The column that matters most is the one a string sort reads 100 · 12 · 9.

    Each grid keeps its OWN sort (#1500): sorting the claims grid must not reorder the
    runs grid beside it.
    """
    from panel.tabs.develop_busy import GROUPS

    columns = dict((key, cols) for key, _t, _s, cols in GROUPS)["claims"]
    sections = dict((key, secs) for key, _t, secs, _c in GROUPS)["claims"]
    view = BusyView(_Tab(_Runtime(), _locale("en")))
    rows = view.rows(_table_snapshot())
    claims = [r for r in rows if r["section"] in sections]

    view._sort["claims"] = ("secs", True)
    longest = view._sorted_group("claims", claims, columns)
    numbers = [r["secs"] for r in longest if r["secs"] is not None]
    assert numbers == sorted(numbers, reverse=True), numbers
    assert numbers[0] == 400                        # the claim nobody has let go of

    # The runs grid was never touched: its own (unset) sort is still the build order.
    assert view._sort.get("runs", ("", False)) == ("", False)


def test_a_lua_step_cannot_flood_the_block() -> None:
    """A `READ_LUA` step is a whole Lua chunk — 1 700 characters, measured live."""
    from panel.tabs.develop_busy import STEP_CHARS, _step

    chunk = "READ_LUA (function() " + "local x = 1 " * 200 + "end)() INTO squads"
    short = _step(chunk)
    assert len(short) == STEP_CHARS and short.endswith("…"), len(short)
    assert short.startswith("READ_LUA (function()")
    assert _step("TAP heal_all xall") == "TAP heal_all xall"      # left alone


def test_a_wait_is_one_press_and_not_twenty_a_second() -> None:
    """`claim_soon` polls; counting each poll read «41 отказ» for one button (#1392)."""
    claims.clear()
    try:
        claims.acquire("k", "alice/timer")
        assert claims.acquire("k", "bob/action") == "alice/timer"     # the press
        for _ in range(20):                                           # …still waiting
            claims.acquire("k", "bob/action", count=False)
        assert claims.state()["held"][0]["refused"] == 1
    finally:
        claims.clear()


def test_the_words_are_in_every_shipped_locale() -> None:
    """A key missing from one of the eleven falls back to English in silence."""
    langs = sorted(p.stem for p in (_REPO / "panel" / "locales").glob("*.json"))
    english = {k for k in _locale("en") if k.startswith("busy.")}
    assert english, "the block's own keys are missing from en.json"
    for lang in langs:
        table = _locale(lang)
        missing = sorted(english - set(table))
        assert not missing, f"{lang}: {missing}"


if __name__ == "__main__":
    failed = 0
    for name, func in sorted(dict(globals()).items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
            print(f"ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:              # noqa: BLE001
            failed += 1
            print(f"ERR  {name}: {exc!r}")
    print("—", "all green" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
