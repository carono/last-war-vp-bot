r"""Four profiles open at once, and none of them in the others' way (#1226).

The complaint this pins: *«действия одного профиля блокируют интерфейс панели; с двумя
профилями терпимо, на 3-4 панель будет парализована»*. Measured on the live panel with
`LW_PANEL_STALL_MS`, the biggest real contributor to the samples was not the work — it
was the REPORTING of it. Two things scale with the number of open profiles and both go
through the one Tk event loop:

  * **reading a setting.** `SettingsBinder.opt()` answers off a Tk variable, and it is
    read almost entirely from background threads — the scheduler, the status poll, the
    dashboard, an action, a tab's fetch. From a thread that is not Tk's, tkinter does
    not read anything: it queues the call for the Tk thread and BLOCKS until the event
    loop runs it. So a profile merely asking «which port am I on» waits on the thread
    that draws every other profile.
  * **handing a repaint back.** `root.after(0, …)` from a worker is two such calls
    (`Misc._register`, then `after`), and while the main thread is not inside the event
    loop — most of a panel's boot — it raises «main thread is not in main loop» and
    killed the worker outright.

What has to hold, and what each group below pins:

  * a hand-over from a worker touches NO Tk (`TkPost`), keeps its order, and one that
    raises does not swallow the batch;
  * a background `opt()` never touches a Tk variable and still answers what the widget
    holds;
  * the three MACHINE-wide walks (sockets, processes, sessions) are taken once for every
    open profile rather than once each;
  * two profiles pointed at ONE client take turns even with no daemon to arbitrate, two
    profiles on two clients never wait for each other, and a refusal names the profile
    that is holding it;
  * a profile WAITING for the client says so once per episode rather than once per
    poll, and the panel says outright that two profiles are on one client instead of
    leaving it to be deduced from the stream of refusals (#1250);
  * the desktop's one foreground is taken only by a scenario that clicks or looks, and
    an RDP profile — which has a desktop of its own — neither takes it nor waits;
  * and nothing a profile does BLOCKS the Tk thread: not the check that its daemon is
    there, not the claim, not binding the web server, not writing the panel's file.

The second group came out of running the thing rather than reading it. A real panel with
four profiles, driven by `tools/dev/panel_load_bench.py`, booted in **81.5 s** with the
pre-#1226 paths and **8.6 s** with them — and reverting the two halves separately says
which is which: the queueing half alone is 79.8 s of that, and the blocking half is what
the stall reports pointed at during a page build. Both are pinned below.

Tk-free except for the two groups that are about Tk, which use a widget DOUBLE rather
than a real window: what is being asserted is «was Tk called from this thread», and a
real Tk would answer that by hanging or by raising, neither of which is a test.

    python3 tests/test_panel_parallel_profiles.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import claims                       # noqa: E402
from panel.runtime import tick as tickmod              # noqa: E402


# ---------------------------------------------------------------------------
# a widget that says who called it
# ---------------------------------------------------------------------------
class FakeWidget:
    """A stand-in for the window: records `after`, and refuses calls off the Tk thread.

    Which is exactly what a real one does — `_tkinter` blocks the caller and, with no
    loop running, raises RuntimeError. Here it raises straight away so a test can say
    «nothing called Tk from a worker» as an assertion rather than as a stopwatch.
    """

    def __init__(self) -> None:
        self.tk_thread = threading.current_thread()
        self.jobs: list = []            # (delay, func) still pending
        self.calls = 0                  # how many times `after` was called at all
        self.foreign = 0                # …of those, from a thread that is not Tk's

    def after(self, delay, func):
        self.calls += 1
        if threading.current_thread() is not self.tk_thread:
            self.foreign += 1
            raise RuntimeError("main thread is not in main loop")
        self.jobs.append((delay, func))
        return f"job{self.calls}"

    def after_cancel(self, job) -> None:
        pass

    def report_callback_exception(self, *_exc) -> None:
        self.reported = getattr(self, "reported", 0) + 1

    # -- driving it ---------------------------------------------------------
    def pump(self, rounds: int = 4) -> None:
        """Run what is pending, the way an event loop would. Tk thread only."""
        for _ in range(rounds):
            due, self.jobs = self.jobs, []
            for _delay, func in due:
                func()


def _worker(func):
    """Run ``func()`` on a thread that is not the main one and wait for it."""
    box = {}

    def run() -> None:
        try:
            box["value"] = func()
        except Exception as exc:                       # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(10)
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ---------------------------------------------------------------------------
# 1. the hand-over
# ---------------------------------------------------------------------------
def test_a_worker_hands_work_over_without_calling_tk() -> None:
    w = FakeWidget()
    ticker = tickmod.Ticker(w)          # built on the Tk thread, as a runtime is
    before = w.calls
    done: list = []

    _worker(lambda: ticker.post(lambda: done.append("painted")))

    assert w.foreign == 0, "a worker called Tk to hand work over"
    assert w.calls == before, "posting armed something instead of queueing it"
    assert done == [], "the work ran on the worker instead of the Tk thread"
    w.pump()
    assert done == ["painted"], done


def test_the_order_work_was_posted_in_is_the_order_it_runs_in() -> None:
    w = FakeWidget()
    ticker = tickmod.Ticker(w)
    seen: list = []
    _worker(lambda: [ticker.post(lambda i=i: seen.append(i)) for i in range(5)])
    w.pump()
    assert seen == [0, 1, 2, 3, 4], seen


def test_one_hand_over_that_raises_does_not_swallow_the_rest() -> None:
    """The rest of the batch is another profile's repaint. It must still happen."""
    w = FakeWidget()
    ticker = tickmod.Ticker(w)
    seen: list = []

    def boom() -> None:
        raise ValueError("a repaint went wrong")

    _worker(lambda: (ticker.post(boom), ticker.post(lambda: seen.append("after"))))
    w.pump()
    assert seen == ["after"], seen
    assert getattr(w, "reported", 0) == 1, "the failure was not reported at all"


def test_one_pump_per_window_however_many_profiles_are_open() -> None:
    """Four sessions is four Tickers and ONE drain — not four wake-ups a tick."""
    w = FakeWidget()
    tickers = [tickmod.Ticker(w) for _ in range(4)]
    assert w.calls == 1, f"{w.calls} chains for one window"
    seen: list = []
    for i, ticker in enumerate(tickers):
        _worker(lambda t=ticker, i=i: t.post(lambda: seen.append(i)))
    w.pump()
    assert seen == [0, 1, 2, 3], seen


def test_on_tk_from_a_worker_waits_for_the_work_not_for_tk() -> None:
    w = FakeWidget()
    ticker = tickmod.Ticker(w)
    ran: list = []
    started = threading.Event()

    def call_it() -> None:
        started.set()
        ticker.on_tk(lambda: ran.append("done"), timeout=5)

    thread = threading.Thread(target=call_it)
    thread.start()
    started.wait(2)
    time.sleep(0.05)
    assert ran == [], "it ran somewhere other than the Tk thread"
    assert w.foreign == 0, "on_tk called Tk from the worker"
    w.pump()
    thread.join(5)
    assert not thread.is_alive(), "the worker never came back"
    assert ran == ["done"], ran


def test_on_tk_from_the_tk_thread_runs_straight_away() -> None:
    """Posting it would deadlock: the pump cannot run until the caller returns."""
    w = FakeWidget()
    ticker = tickmod.Ticker(w)
    ran: list = []
    ticker.on_tk(lambda: ran.append("done"))
    assert ran == ["done"], ran


def test_stop_ends_the_shared_pump_for_the_whole_window() -> None:
    """`tick.stop(widget)` — called once, when the WHOLE window is closing — ends the
    drain for good: the already-scheduled callback firing one last time must not
    re-arm another `after` behind it (#1236 — nothing called this, ever, so a process
    that opens and closes several windows kept every one of their pumps ticking)."""
    w = FakeWidget()
    tickmod.Ticker(w)                      # arms the shared pump, as a runtime would
    calls_before = w.calls
    tickmod.stop(w)
    w.pump()                               # the job already queued fires one more time
    assert w.calls == calls_before, "the pump re-armed itself after being stopped"


def test_stop_with_no_widget_or_no_pump_is_a_no_op() -> None:
    tickmod.stop(None)                     # nothing to stop — must not raise
    tickmod.stop(FakeWidget())             # a widget that never got a Ticker


# ---------------------------------------------------------------------------
# 2. reading a setting off a background thread
# ---------------------------------------------------------------------------
class TkOnlyVar:
    """A Tk variable double: `get()` from anywhere but the Tk thread is a failure.

    A real one does not fail — it blocks and then answers — which is the whole problem
    and is unassertable. Failing makes it visible.
    """

    def __init__(self, value) -> None:
        self.tk_thread = threading.current_thread()
        self._value = value
        self._traces: list = []
        self.reads = 0

    def get(self):
        self.reads += 1
        if threading.current_thread() is not self.tk_thread:
            raise AssertionError("a background thread read a Tk variable")
        return self._value

    def set(self, value) -> None:
        self._value = value
        for func in list(self._traces):
            func()

    def trace_add(self, _mode, func):
        self._traces.append(func)
        return "trace0"


def _binder(saved=None, defaults=None):
    from panel.runtime.settings import SettingsBinder

    class _Profiles:
        def load(self) -> dict:
            return dict(saved or {})

        def save(self, _raw) -> None: ...

    binder = SettingsBinder(_Profiles(), defaults or {"daemon_port": 47654,
                                                      "rdp_user": ""})
    binder.load()
    binder.create_vars(object(), factory=lambda _m, d: TkOnlyVar(d))
    return binder


def test_a_background_read_answers_what_the_widget_holds_without_touching_it() -> None:
    binder = _binder()
    binder.vars["daemon_port"].set("47655")            # as the Settings box would
    reads = binder.vars["daemon_port"].reads

    got = _worker(lambda: binder.opt_int("daemon_port", low=1, high=65535))

    assert got == 47655, got
    assert binder.vars["daemon_port"].reads == reads, "the worker read the variable"


def test_the_tk_thread_still_reads_the_variable_itself() -> None:
    """A value written and read inside one callback must not wait for a trace."""
    binder = _binder()
    binder.vars["daemon_port"].set("47656")
    assert binder.opt_int("daemon_port", low=1, high=65535) == 47656


def test_a_background_read_falls_back_to_the_saved_value_with_no_widgets() -> None:
    from panel.runtime.settings import SettingsBinder

    class _Profiles:
        def load(self) -> dict:
            return {"daemon_port": 47657}

        def save(self, _raw) -> None: ...

    binder = SettingsBinder(_Profiles(), {"daemon_port": 47654})
    binder.load()
    assert _worker(lambda: binder.opt_int("daemon_port")) == 47657


def test_four_profiles_read_their_own_ports_at_once() -> None:
    """The failure this replaces: every one of them queued behind the Tk thread."""
    binders = [_binder(defaults={"daemon_port": 47654 + i}) for i in range(4)]
    for i, binder in enumerate(binders):
        binder.vars["daemon_port"].set(str(47654 + i))
    seen: list = []
    threads = [threading.Thread(
        target=lambda b=b: seen.append(b.opt_int("daemon_port", low=1, high=65535)))
        for b in binders]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sorted(seen) == [47654, 47655, 47656, 47657], seen


# ---------------------------------------------------------------------------
# 3. the machine's own facts, read once for everybody
# ---------------------------------------------------------------------------
def test_one_walk_of_the_socket_table_serves_every_open_profile() -> None:
    # The shared walk moved to `tools/lib/game_link.py` with the rest of the reading
    # (#1260), so it is asked there — and no tkinter is needed to ask it, which is why
    # this no longer goes through the panel at all.
    import game_link

    walks = []

    class _Fake:
        @staticmethod
        def net_connections(kind="tcp"):
            walks.append(kind)
            return []

    held = sys.modules.get("psutil")
    sys.modules["psutil"] = _Fake
    try:
        game_link.forget_machine_state()
        for _ in range(4):                             # four profiles' status polls
            game_link.client_sockets([111])
        assert len(walks) == 1, f"{len(walks)} walks for four profiles"
        game_link.forget_machine_state()
        game_link.client_sockets([111])
        assert len(walks) == 2, "forgetting did not make it walk again"
    finally:
        if held is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = held
        game_link.forget_machine_state()


def test_the_shared_reading_is_taken_once_even_by_four_threads_at_once() -> None:
    from game_link import _Shared

    walks: list = []

    def slow():
        walks.append(1)
        time.sleep(0.05)                               # a walk long enough to race
        return "table"

    shared = _Shared(slow)
    threads = [threading.Thread(target=shared.get) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(walks) == 1, f"{len(walks)} concurrent walks"


# ---------------------------------------------------------------------------
# 4. two profiles, one client
# ---------------------------------------------------------------------------
class _Link:
    """The claim half of `GameLink`, with no daemon behind it — which is the case."""

    def __init__(self, profile: str, port: int) -> None:
        from panel.runtime.daemon import GameLink

        self.link = GameLink.__new__(GameLink)
        self.link._busy = False
        self.link._busy_lock = threading.Lock()
        self.link._port = lambda: port
        self.link._name = lambda: profile
        self.link._log = _SilentLog()
        self.link._client = None
        self.link._client_port = port
        self.link._up_seen = (0.0, None, False)
        self.link._said_busy = None

    def __getattr__(self, name):
        return getattr(self.link, name)


class _SilentLog:
    def __init__(self) -> None:
        self.lines: list = []

    def say(self, tag, key, **fmt) -> None:
        self.lines.append((key, fmt))

    def put(self, line) -> None:
        self.lines.append(line)


def test_two_profiles_on_ONE_client_take_turns_with_no_daemon_to_ask() -> None:
    """The hole: with no daemon, `_claim_lease` says yes to everybody."""
    claims.clear()
    first, second = _Link("main", 47654), _Link("alt", 47654)
    try:
        assert first.claim("timer") is True
        assert second.claim("timer") is False, "both profiles drove one client"
        first.release()
        assert second.claim("timer") is True, "the client was never let go"
        second.release()
    finally:
        claims.clear()


def test_two_profiles_on_TWO_clients_never_wait_for_each_other() -> None:
    claims.clear()
    first, second = _Link("main", 47654), _Link("alt", 47655)
    try:
        assert first.claim("timer") is True
        assert second.claim("timer") is True
    finally:
        first.release(), second.release()
        claims.clear()


def test_a_refusal_names_the_profile_that_is_holding_the_client() -> None:
    claims.clear()
    first, second = _Link("main", 47654), _Link("alt", 47654)
    try:
        first.claim("timer")
        second.claim("rally")
        said = [fmt for key, fmt in second.link._log.lines if key == "busy.elsewhere"]
        assert said and said[0]["owner"] == "main/timer", said
    finally:
        first.release()
        claims.clear()


def test_a_profile_cannot_release_the_client_another_one_is_driving() -> None:
    """`release()` is called by callers that never claimed — a runtime always lets go.

    With the key re-derived at release time rather than remembered, the second profile
    shutting down would hand the FIRST one's client to anybody, in the middle of its
    errand. That is the one failure this registry exists to prevent.
    """
    claims.clear()
    first, second = _Link("main", 47654), _Link("alt", 47654)
    try:
        assert first.claim("timer") is True
        second.release()                               # never claimed anything
        import lua_client

        assert claims.holder((lua_client.HOST, 47654)) == "main/timer", claims.held()
        assert second.claim("timer") is False, "it took the client anyway"
    finally:
        claims.clear()


def test_nothing_is_left_held_when_a_claim_is_refused() -> None:
    claims.clear()
    first, second = _Link("main", 47654), _Link("alt", 47654)
    try:
        first.claim("timer")
        second.claim("timer")
        assert second.link.busy is False, "a refused claim left the local flag up"
        first.release()
        assert claims.held() == {}, claims.held()
    finally:
        claims.clear()


def _busy_lines(link) -> list:
    return [fmt for key, fmt in link.link._log.lines if key == "busy.elsewhere"]


def test_a_profile_waiting_for_the_client_says_so_ONCE() -> None:
    """The flood (#1250): every polled refusal used to be a line naming the OTHER one.

    `panel/tabs/rally/tab.py::_join` asks for the claim every 0.15 s until it gets it,
    so one profile waiting a minute on another wrote four hundred identical records
    into its own log — which is how a shared client came to read as two profiles' logs
    being crossed.
    """
    claims.clear()
    first, second = _Link("main", 47654), _Link("alt", 47654)
    try:
        first.claim("timer")
        for _ in range(50):                            # the waiter, polling
            assert second.claim("rally") is False
        said = _busy_lines(second)
        assert len(said) == 1, f"{len(said)} lines for one wait"
        assert said[0]["owner"] == "main/timer", said
    finally:
        first.release()
        claims.clear()


def test_the_client_changing_hands_is_said_again() -> None:
    """Deduped on the HOLDER, not silenced: a new holder is a new fact."""
    claims.clear()
    first, third = _Link("main", 47654), _Link("third", 47654)
    second = _Link("alt", 47654)
    try:
        first.claim("timer")
        second.claim("rally")
        second.claim("rally")
        first.release()
        third.claim("timer")                           # the client moves to `third`
        second.claim("rally")
        owners = [fmt["owner"] for fmt in _busy_lines(second)]
        assert owners == ["main/timer", "third/timer"], owners
    finally:
        third.release()
        claims.clear()


def test_getting_the_client_re_arms_the_line() -> None:
    """Once this profile has HAD the game, losing it again is news once more."""
    claims.clear()
    first, second = _Link("main", 47654), _Link("alt", 47654)
    try:
        first.claim("timer")
        second.claim("rally")
        first.release()
        assert second.claim("rally") is True
        second.release()
        first.claim("timer")
        second.claim("rally")
        assert len(_busy_lines(second)) == 2, _busy_lines(second)
    finally:
        first.release()
        claims.clear()


# ---------------------------------------------------------------------------
# 4b. …and the panel says WHY, instead of leaving it to be deduced (#1250)
# ---------------------------------------------------------------------------
class _WarnSession:
    """A session double with just enough of one to answer «which client is this»."""

    def __init__(self, name: str, port: "int | None") -> None:
        self.name = name
        self.said: list = []
        self.rt = type("_Rt", (), {})()
        self.rt.say = lambda tag, key, **fmt: self.said.append((key, fmt))
        self.rt.game = None if port is None else _Link(name, port)

    start = staticmethod(lambda: None)


def _workspace_of(*sessions):
    from panel.runtime import workspace as wsmod

    space = wsmod.Workspace.__new__(wsmod.Workspace)
    space._sessions = list(sessions)
    return space


def test_two_profiles_on_one_client_are_named_to_each_other() -> None:
    space = _workspace_of(_WarnSession("main", 47654), _WarnSession("alt", 47654))
    first, second = space.sessions
    assert [s.name for s in space.sharing(first)] == ["alt"]
    assert [s.name for s in space.sharing(second)] == ["main"]


def test_two_profiles_on_two_clients_share_nothing() -> None:
    space = _workspace_of(_WarnSession("main", 47654), _WarnSession("alt", 47655))
    assert space.sharing(space._sessions[0]) == []


def test_a_session_that_cannot_say_which_client_it_is_shares_nothing() -> None:
    """A test's session is a name and nothing else — and «no opinion» is never a match."""
    space = _workspace_of(_WarnSession("main", None), _WarnSession("alt", None))
    assert space.sharing(space._sessions[0]) == []


def test_the_warning_lands_in_BOTH_profiles_logs_when_the_second_one_opens() -> None:
    """Both, because there is no telling which of the two the person is reading."""
    space = _workspace_of()
    sessions = [_WarnSession("main", 47654), _WarnSession("alt", 47654)]
    for session in sessions:                           # …as `Workspace.open` does
        space._sessions.append(session)
        space._warn_client_shared(session)
    said = [(s.name, key, fmt) for s in sessions for key, fmt in s.said]
    assert [(n, k) for n, k, _ in said] == [
        ("main", "profile.client_shared"), ("alt", "profile.client_shared")], said
    # Each is told the name of the OTHER, and both are told which port they collided on.
    assert [f["others"] for _n, _k, f in said] == ["alt", "main"], said
    assert all(f["port"] == 47654 for _n, _k, f in said), said


def test_the_first_profile_opened_is_told_nothing() -> None:
    """One profile on its own has nobody to collide with, and says nothing about it."""
    space = _workspace_of()
    alone = _WarnSession("main", 47654)
    space._sessions.append(alone)
    space._warn_client_shared(alone)
    assert alone.said == [], alone.said


# ---------------------------------------------------------------------------
# 5. the desktop's one foreground
# ---------------------------------------------------------------------------
def test_the_foreground_is_one_and_says_who_has_it() -> None:
    claims.clear()
    try:
        with claims.Foreground("main/street_run") as first:
            assert first.taken is None
            with claims.Foreground("alt/street_run") as second:
                assert second.taken == "main/street_run", second.taken
        assert claims.holder(claims.FOREGROUND) is None, "it was never let go"
    finally:
        claims.clear()


def test_a_profile_with_a_desktop_of_its_own_neither_takes_it_nor_waits() -> None:
    claims.clear()
    try:
        with claims.Foreground("main/x") as first:
            assert first.taken is None
            with claims.Foreground("rdp/x", exempt=True) as rdp:
                assert rdp.taken is None, "an RDP profile waited for this desktop"
        # …and the exempt one did not quietly take it either.
        assert claims.holder(claims.FOREGROUND) is None
    finally:
        claims.clear()


def test_a_headless_scenario_never_asks_for_the_foreground() -> None:
    """Every blessed scenario is headless Lua, so the guard must cost them nothing."""
    try:
        from panel.runtime.actions import ActionRunner
    except Exception as exc:                           # noqa: BLE001 — no tkinter here
        print(f"  SKIP headless: {exc}")
        return
    from panel.runtime.actions import ACTIONS_DIR

    blessed = sorted(Path(ACTIONS_DIR).glob("*.md"))
    assert blessed, "no blessed scenarios found at all"
    vision = [p.stem for p in blessed if ActionRunner.needs_foreground(p.stem)]
    assert vision == [], f"a blessed scenario now clicks the screen: {vision}"


def test_a_scenario_that_clicks_is_recognised() -> None:
    try:
        from panel.runtime.actions import ActionRunner
    except Exception as exc:                           # noqa: BLE001
        print(f"  SKIP recognised: {exc}")
        return
    import tempfile

    from lastwar_bot import script_engine

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "clicky.md"
        path.write_text("# Clicks about\nFIND button.png\nCLICK\n", encoding="utf-8")
        was = script_engine.resolve_action
        script_engine.resolve_action = lambda name: path if name == "clicky" else None
        try:
            assert ActionRunner.needs_foreground("clicky") is True
            assert ActionRunner.needs_foreground("nothing_by_that_name") is False
        finally:
            script_engine.resolve_action = was


# ---------------------------------------------------------------------------
# 6. what a profile may NOT do on the Tk thread
#
# Every one of these was found by running `tools/dev/panel_load_bench.py` with four
# profiles and reading the stall reports. They are the second half of the fault: the
# first is a profile's work QUEUEING on the Tk thread (above), this is a profile's work
# SITTING on it. Both scale with the number of profiles and neither is visible with one.
# ---------------------------------------------------------------------------
def test_a_daemon_that_is_not_there_is_not_a_second_of_frozen_window() -> None:
    """A connect to a port nothing is listening on is DROPPED here, not refused.

    So the check cost its whole timeout, every time, and the old timeout was a second —
    on the Tk thread, once per profile, whenever an account was not up yet. And the
    answer was never remembered, so asking twice cost two.
    """
    from panel.runtime import daemon as daemonmod

    assert daemonmod.UP_TIMEOUT_SEC <= 0.5, daemonmod.UP_TIMEOUT_SEC
    link = _Link("main", 47654)
    asked: list = []

    import lua_client

    was = lua_client.is_running
    lua_client.is_running = lambda **kw: (asked.append(kw), False)[1]
    try:
        assert link.link.up() is False
        assert link.link.up() is False and link.link.up() is False
        assert len(asked) == 1, f"the answer was not remembered: {len(asked)} asks"
        assert asked[0]["timeout"] <= 0.5, asked[0]
        # …and the caller watching for one it has just started is never fobbed off.
        link.link.up(fresh=True)
        assert len(asked) == 2, "fresh=True read a remembered answer"
    finally:
        lua_client.is_running = was


def test_a_claim_does_not_dial_a_daemon_it_knows_is_not_there() -> None:
    """`claim` runs on the TK THREAD from every button, and dialling costs a connect."""
    link = _Link("main", 47654)
    dialled: list = []

    class _Client:
        def acquire(self, owner, ttl=0):
            dialled.append(owner)
            return "token"

    link.link._client = _Client()
    link.link.up = lambda fresh=False: False
    claims.clear()
    try:
        assert link.claim("panel") is True, "a down daemon must not refuse the claim"
        assert dialled == [], "it dialled a daemon it had just been told is not there"
    finally:
        link.release()
        claims.clear()


def test_connecting_to_the_daemon_and_waiting_for_it_are_two_different_waits() -> None:
    """A Lua chunk may take a minute; a LOCAL connect either works at once or never."""
    import lua_client

    client = lua_client.DaemonClient(port=47654)
    assert client.timeout >= 30, client.timeout          # the answer may take a while
    assert client.connect_timeout <= 1.0, client.connect_timeout
    assert lua_client.CONNECT_TIMEOUT <= 1.0, lua_client.CONNECT_TIMEOUT


def test_the_web_server_does_not_look_itself_up_in_dns_to_bind() -> None:
    """`HTTPServer.server_bind` ends in `getfqdn(host)` — on the wildcard, ~0.9 s.

    On the Tk thread, because the tab binds from `ensure_loaded`. Nothing reads
    `server_name`, so the lookup bought a second of frozen window and nothing else.
    """
    from http.server import BaseHTTPRequestHandler

    from panel.web import server as websrv

    started = time.perf_counter()
    httpd = websrv._Server(("0.0.0.0", 0), BaseHTTPRequestHandler)
    held = time.perf_counter() - started
    try:
        assert held < 0.2, f"the bind took {held * 1000:.0f} ms — it is still resolving"
        assert httpd.server_name, "a server with no name at all"
    finally:
        httpd.server_close()


def test_opening_four_profiles_writes_the_panel_file_once() -> None:
    """`_remember` reads and rewrites the panel-wide settings on every `open`.

    On the Tk thread, with a virus scanner between it and the disk. The list is only
    interesting once it is complete.
    """
    from panel.runtime.workspace import Workspace

    writes: list = []

    class _Profiles:
        active = "one"

        def open_profiles(self) -> list:
            return ["one", "two", "three", "four"]

        def set_active(self, name, write=True) -> None: ...

        def set_open_profiles(self, names, active=None) -> None:
            writes.append(list(names))

        def _ensure_dir(self, name) -> str:
            return name

    space = Workspace(None, profiles=_Profiles())
    space.open = lambda name, make_current=True: space._sessions.append(
        type("S", (), {"name": name, "rt": None})())
    space.switch_to = lambda name: None
    space.restore()
    assert len(writes) == 1, f"{len(writes)} writes for four profiles: {writes}"


# ---------------------------------------------------------------------------
# 7. and it stays that way
# ---------------------------------------------------------------------------
def test_nothing_in_the_panel_hands_work_over_with_a_bare_after() -> None:
    """A grep, deliberately — the same shape as the one guarding `_arm`.

    The rule is only worth what the next hand-over written obeys, and `root.after(0, …)`
    is the obvious thing to write. `rt.post` / `self.post` / `tick.post` is the door;
    a REAL delay (`after(400, …)`) is not this and is left alone.
    """
    import ast

    root = _REPO / "panel"
    allowed = {
        # The harness that opens ONE tab on its own: this line runs on the Tk thread,
        # before the mainloop, and is the thing that starts it.
        "tabs/base.py",
        # Where the queue itself lives.
        "runtime/tick.py",
    }
    offenders = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in allowed:
            continue
        # Parsed, not grepped: half this file's prose SAYS `root.after(0, …)` while
        # explaining why not to write it, and a grep cannot tell the two apart.
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "after" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value == 0:
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], (
        "a hand-over onto the Tk thread that is not `post`: " + ", ".join(offenders))


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
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
