r"""«Тёплый» — это не «порт отвечает»: три ответа вместо одного (#1286).

On 2026-08-07 the client went through three process ids in ten minutes — other work
restarting it — and the daemon was left holding a pid that no longer existed. Asked to
bring the daemon back, the panel answered «already warm on port 47654» and left it
lying there: `ensure()` decided by asking whether SOMETHING accepted a connection on
the port, and something did. Twelve of thirty rally auto-joins in that window came back
«связь с сервером пропала».

The port answered because the corpse was still holding it. The polite shutdown is
acknowledged BEFORE it is carried out — the daemon replies `{"ok":true}`, then closes
its evaluator, and the close takes the run lock that a call wedged against the dead
client never gives back. So `restart()` waited its five seconds, the port stayed bound,
and `ensure()` read the same corpse's socket as a warm daemon. Measured in the log:
16:34:55.954 «перезапуск…» → 16:35:00.980 «already warm», which is FREE_TRIES × FREE_WAIT
to the tenth of a second.

Four things are pinned here, and the first is the shape:

* **three answers, not two** — no daemon / a daemon on a client that is gone / a daemon
  on the client that is running. Each has a different cure and the middle one had no way
  to be said at all;
* **`ensure` never calls a corpse warm**, and restarts the DAEMON for it — never the
  client, which is #1268's six pointless relaunches;
* **the port is the verdict, never the reply**: a daemon that acknowledges a shutdown
  and keeps the port is ended by the pid its own ping named, and a port still held after
  that starts no second daemon that could not bind it anyway;
* **the daemon follows its own client**, so a restart needs nobody's help: it lets go of
  a pid that has gone and takes hold of the one that replaced it, and it LEAVES when it
  is told to even while its evaluator cannot be closed.

No game, no socket to a real daemon, no Tk: stand-in clients that answer a ping the way
the daemon answers it, and a stand-in for «which client is running».

    C:\Python312\python.exe tests\test_panel_daemon_health.py
"""
from __future__ import annotations

TIER = "ui"        # panel.runtime drags tkinter in — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import json                                                  # noqa: E402
import socket                                                # noqa: E402
import threading                                             # noqa: E402
import time                                                  # noqa: E402

import lua_daemon as daemontool                              # noqa: E402
import panel.runtime.daemon as daemonmod                     # noqa: E402
from panel.runtime.daemon import (DAEMON_LIVE, DAEMON_NONE,  # noqa: E402
                                  DAEMON_STALE, GameLink)


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

class _Log:
    def __init__(self) -> None:
        self.said: list = []

    def put(self, line) -> None:
        self.said.append(str(line))

    def say(self, tag, key, **fmt) -> None:
        self.said.append(key)


class _Client:
    """A daemon client that answers `status()` the way a real daemon answers a ping."""

    def __init__(self, port: int, reply: dict) -> None:
        self.port, self.token, self._reply = port, "", reply

    def status(self) -> dict:
        return dict(self._reply)

    def target_pid(self):
        return self._reply.get("pid")

    def shutdown(self):
        return {"ok": True}


class _Link(GameLink):
    """A link with everything the connection needs and nothing else.

    `GameLink.__init__` wants a log bus, an activity strip, a settings binder and a
    child environment; none of them is part of the question here.
    """

    def __init__(self, *, listening: bool, reply: dict = None, running=None,
                 port: int = 47654) -> None:
        self.log = _Log()
        self._log = self.log
        self._dbg = None
        self._activity = daemonmod.Activity()
        self.on_state = lambda state, ok: self.states.append(state)
        self.states: list = []
        self.listening = listening
        self._client = _Client(port, reply or {})
        self._client_port = port
        self._port_no = port
        self._running = running
        #: what the test wants to see happen, rather than a daemon being launched
        self.started = 0
        self.killed: list = []
        self.freed_after: int = 0                # kills needed before the port comes free

    # -- the machine, as this test's stand-in for it ------------------------
    def port(self) -> int:
        return self._port_no

    def up(self, fresh: bool = False) -> bool:
        return self.listening

    def user(self):
        return None

    def _running_pid(self):
        return self._running

    def _start(self) -> bool:
        self.started += 1
        return True

    def _kill(self, pid) -> bool:
        self.killed.append(pid)
        if self.freed_after and len(self.killed) >= self.freed_after:
            self.listening = False
        return True

    def _wait_free(self) -> bool:                # no sleeping through FREE_TRIES here
        return not self.listening


def _rally_link(**kw) -> _Link:
    """A link whose daemon answers, on the pid it was given."""
    kw.setdefault("listening", True)
    return _Link(**kw)


# ---------------------------------------------------------------------------
# the three answers
# ---------------------------------------------------------------------------

def test_nothing_on_the_port_is_no_daemon() -> None:
    """Nobody listening: the cure is to start one, and only that."""
    link = _Link(listening=False, running=4242)
    assert link.health() == DAEMON_NONE


def test_a_daemon_holding_a_client_that_is_gone_is_stale() -> None:
    """THE STATE THAT HAD NO NAME. The port answers; the pid it names is not running.

    This is what «already warm» was said over. `up()` cannot tell it from a healthy
    daemon, because at the socket level there is nothing to tell.
    """
    link = _rally_link(reply={"ok": True, "warm": True, "pid": 133040}, running=49788)
    assert link.health() == DAEMON_STALE


def test_a_daemon_that_answers_for_no_client_at_all_is_stale() -> None:
    """`pid: null` beside a running client is the same fault wearing another answer.

    It is what a daemon says when its attach failed, and what one says for the seconds
    after a client is replaced — which is why the recovery counts readings
    (`DAEMON_STRIKES`) instead of acting on the first.
    """
    link = _rally_link(reply={"ok": True, "warm": False, "pid": None}, running=49788)
    assert link.health() == DAEMON_STALE


def test_a_daemon_on_the_running_client_is_live() -> None:
    link = _rally_link(reply={"ok": True, "warm": True, "pid": 49788}, running=49788)
    assert link.health() == DAEMON_LIVE


def test_no_client_running_is_nobodys_fault() -> None:
    """Nothing to compare against may never come out as «stale».

    A machine with the game closed would otherwise have its daemon restarted every
    couple of polls for ever — «could not tell» is not a diagnosis, which is the rule
    `panel/runtime/recovery.py` already keeps for `unknown` link readings.
    """
    link = _rally_link(reply={"ok": True, "warm": False, "pid": None}, running=None)
    assert link.health() == DAEMON_LIVE


def test_the_callers_pid_is_used_when_it_has_one() -> None:
    """The status poll has already found the client; it must not be looked up twice."""
    link = _rally_link(reply={"ok": True, "pid": 99908}, running=None)
    assert link.health(99908) == DAEMON_LIVE
    assert link.health(49788) == DAEMON_STALE


# ---------------------------------------------------------------------------
# what `ensure` does with them
# ---------------------------------------------------------------------------

def test_ensure_calls_a_live_daemon_warm_and_starts_nothing() -> None:
    link = _rally_link(reply={"ok": True, "warm": True, "pid": 49788}, running=49788)
    assert link.ensure() is True
    assert link.started == 0
    assert link.states == ["warm"]


def test_ensure_starts_one_when_there_is_none() -> None:
    link = _Link(listening=False, running=49788)
    assert link.ensure() is True
    assert link.started == 1


def test_ensure_never_calls_a_corpse_warm() -> None:
    """The bug itself: a daemon on a dead pid was answered with «already warm».

    What must happen instead is the daemon being restarted — and the line saying so,
    because a person watching the log had no way to learn that the panel was reporting a
    daemon it had done nothing about.
    """
    restarted: list = []

    link = _rally_link(reply={"ok": True, "warm": True, "pid": 133040}, running=49788)
    link.restart = lambda: (restarted.append(True), True)[1]
    assert link.ensure() is True
    assert restarted == [True], "a daemon holding a client that is gone was left lying"
    assert "log.daemon.stale" in link.log.said
    assert link.states != ["warm"], "the corpse was reported as a warm daemon"


def test_a_stale_daemon_restarts_the_daemon_not_the_client() -> None:
    """#1268's lesson, kept: nothing here may reach for the client.

    The client is fine — it is the NEW one, and restarting it is what cost six
    relaunches in fifty minutes the first time this was diagnosed by the link state.
    """
    link = _rally_link(reply={"ok": True, "pid": 133040}, running=49788)
    link.restart = lambda: True
    link.ensure()
    assert not any("restart_game" in line for line in link.log.said)


# ---------------------------------------------------------------------------
# a daemon that acknowledges a shutdown and does not carry it out
# ---------------------------------------------------------------------------

def test_a_daemon_that_keeps_the_port_is_ended_by_its_own_pid() -> None:
    """The reply is not the act — the port is (#1286).

    The pid comes off the daemon's own ping, because nothing else on the machine can
    name it: a daemon in another Windows session is not in this session's process list.
    """
    link = _rally_link(reply={"ok": True, "warm": True, "pid": 133040, "self": 77001},
                       running=49788)
    link.freed_after = 1                          # the kill is what frees the port
    assert link.restart() is True
    assert link.killed == [77001], "the wedged daemon was left holding the port"
    assert link.started == 1


def test_a_port_still_held_after_the_kill_starts_no_second_daemon() -> None:
    """A daemon that cannot bind is the same lie one process further along.

    It happens for real: a daemon belonging to ANOTHER Windows login is not this token's
    to terminate. The honest answer is a failure with a sentence, not a green light.
    """
    link = _rally_link(reply={"ok": True, "pid": 133040, "self": 77001}, running=49788)
    link.freed_after = 0                          # nothing frees it
    assert link.restart() is False
    assert link.started == 0
    assert "log.daemon.wont_die" in link.log.said
    assert link.states[-1] == "error"


def test_a_daemon_that_goes_quietly_is_not_killed() -> None:
    """The kill is the last resort and must never become the ordinary route.

    A daemon ended mid-call leaves the game's Lua VM with whatever the call was in the
    middle of.
    """
    link = _rally_link(reply={"ok": True, "pid": 49788, "self": 77001}, running=49788)
    link.listening = False                        # the polite shutdown worked
    assert link.restart() is True
    assert link.killed == []
    assert link.started == 1


# ---------------------------------------------------------------------------
# the daemon's own half: it follows its client, and it leaves when told
# ---------------------------------------------------------------------------

class _Eval:
    def __init__(self, pid) -> None:
        self.x = type("X", (), {"pid": pid})()

    def close(self) -> None:
        pass


def _daemon_with(pid, alive: dict, session: list):
    """A `Daemon` attached to ``pid``, with the machine's answers written down."""
    import game_client

    daemon = daemontool.Daemon()
    daemon._ev = _Eval(pid) if pid else None
    was = (game_client.alive, game_client.session_pids)
    game_client.alive = lambda p: bool(alive.get(int(p or 0)))
    game_client.session_pids = lambda *a, **k: list(session)
    return daemon, was


def _restore(was) -> None:
    import game_client

    game_client.alive, game_client.session_pids = was


def test_the_daemon_lets_go_of_a_client_that_has_gone() -> None:
    """133040 → 49788 without a word from the panel.

    The pin is a process id and a restarted client is a new one, so a daemon that does
    not do this holds a dead pid until something drives it into a call that fails twice
    over — and, if the rebuild fails too, for ever after that.
    """
    daemon, was = _daemon_with(133040, alive={49788: True}, session=[49788])
    attached: list = []
    daemon._ensure = lambda: (attached.append(True),
                              setattr(daemon, "_ev", _Eval(49788)))[0]
    try:
        assert daemon.follow_client() is True
        assert daemon.target_pid() == 49788
    finally:
        _restore(was)


def test_a_daemon_on_a_live_client_is_left_exactly_alone() -> None:
    daemon, was = _daemon_with(49788, alive={49788: True}, session=[49788])
    daemon._ensure = lambda: (_ for _ in ()).throw(AssertionError("re-attached for nothing"))
    try:
        assert daemon.follow_client() is False
    finally:
        _restore(was)


def test_nothing_is_attached_while_no_client_is_running() -> None:
    """A machine with the game closed must not build an evaluator every five seconds."""
    daemon, was = _daemon_with(133040, alive={}, session=[])
    daemon._ensure = lambda: (_ for _ in ()).throw(AssertionError("attached to nothing"))
    try:
        assert daemon.follow_client() is False
    finally:
        _restore(was)


def test_a_wedged_call_is_never_waited_for() -> None:
    """The watch may not become a second thread stuck behind the first.

    A call that is wedged holds the run lock for ever; the thing that ends THAT daemon
    is the panel's kill, not a watcher queueing behind it.
    """
    daemon, was = _daemon_with(133040, alive={49788: True}, session=[49788])
    daemon._ensure = lambda: (_ for _ in ()).throw(AssertionError("took the lock"))
    daemon._lock.acquire()                        # a call in flight, and stuck
    try:
        started = time.monotonic()
        assert daemon.follow_client() is False
        assert time.monotonic() - started < 1.0
    finally:
        daemon._lock.release()
        _restore(was)


def test_a_shutdown_leaves_even_when_the_evaluator_cannot_be_closed() -> None:
    """The close takes the run lock; the process leaving may not depend on getting it.

    This is the mechanism that turned a stale daemon into a permanent one: the reply
    went out, the close blocked, `os._exit` was never reached, and the port stayed bound
    and answering for as long as the panel kept asking.
    """
    stuck, left = threading.Event(), []

    class _Stuck:
        def close(self) -> None:
            stuck.wait(10.0)                      # a lock that is never given back

    was_exit, was_grace = daemontool.os._exit, daemontool.EXIT_GRACE_SEC
    daemontool.os._exit = lambda code: left.append(code)
    daemontool.EXIT_GRACE_SEC = 0.05
    leaving = threading.Thread(target=daemontool._leave, args=(_Stuck(),), daemon=True)
    try:
        leaving.start()
        deadline = time.monotonic() + 3.0
        while not left and time.monotonic() < deadline:
            time.sleep(0.02)
        assert left == [0], "the daemon acknowledged a shutdown it never carried out"
    finally:
        # Unblocked and joined BEFORE `os._exit` is handed back: the tidy path is still
        # ahead of that thread, and the real one would end this test run rather than a
        # daemon.
        stuck.set()
        leaving.join(3.0)
        daemontool.os._exit, daemontool.EXIT_GRACE_SEC = was_exit, was_grace


def test_a_ping_names_the_daemons_own_process() -> None:
    """`self` is on the wire, because nothing outside the daemon can work it out.

    A daemon in another Windows session is not in the asker's process list, so without
    this there is no way to end one that will not end itself.
    """
    import os

    daemon = daemontool.Daemon()
    here, there = socket.socketpair()
    threading.Thread(target=daemontool._handle, args=(there, daemon), daemon=True).start()
    try:
        here.sendall(b'{"op":"ping"}\n')
        here.settimeout(5.0)
        reply = json.loads(here.recv(65536).decode("utf-8").splitlines()[0])
    finally:
        here.close()
    assert reply.get("ok") is True
    assert reply.get("self") == os.getpid()


# ---------------------------------------------------------------------------
# and the same three states drawn, in the window AND on the phone
# ---------------------------------------------------------------------------

def test_the_indicator_has_a_word_for_the_middle_state() -> None:
    """«Тёплый» over a corpse is the sentence a person actually read for half an hour.

    Amber rather than red: the daemon IS there and the panel is already restarting it —
    red would say the same thing as «no daemon at all», which is a different cure.
    """
    import panel.__main__ as pm

    said = type("P", (), {"_t": staticmethod(lambda key, **f: key)})()
    assert pm.Panel._daemon_word(said, False, False) == ("daemon.none", False)
    assert pm.Panel._daemon_word(said, True, False) == ("daemon.warm", True)
    assert pm.Panel._daemon_word(said, True, True) == ("daemon.stale", None)


def test_the_gates_in_front_of_the_game_will_not_use_a_corpse() -> None:
    """`up()` in front of an errand is the same lie one caller further along.

    The errand gate and the coordinate jump both asked «does the port answer», so a
    stale daemon was not a reason to skip or to fix anything — the errand ran, the link
    reached nothing, and the run reported «связь с сервером пропала». They ask the
    STATUS POLL's verdict rather than making one: this is in front of every errand,
    including the rally auto-join that is racing other alliances.
    """
    for rel in ("panel/runtime/schedule.py", "panel/runtime/daemon.py"):
        text = (_REPO / rel).read_text(encoding="utf-8")
        assert "last_health() == daemonmod.DAEMON_STALE" in text \
            or "last_health() == DAEMON_STALE" in text, \
            f"{rel} still gates the game on the port alone"


def test_the_phone_is_told_the_same_three_states() -> None:
    """A change on one front-end that never reaches the other is half a change.

    The phone is the front-end that needs this MOST: whoever is holding it cannot see
    the log scrolling past and has only the dot to go on.
    """
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    page = (_REPO / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert '"stale": rt.game.last_health()' in api, "the payload never carries the state"
    assert "web.ui.stale" in page, "the page has no word for a daemon holding a corpse"
    for lang in sorted((_REPO / "panel" / "locales").glob("*.json")):
        words = json.loads(lang.read_text(encoding="utf-8"))
        for key in ("daemon.stale", "web.ui.stale", "log.daemon.stale",
                    "log.daemon.wont_die", "log.daemon.killing",
                    "log.daemon.kill_failed", "log.daemon.no_client"):
            assert key in words, f"{lang.name} is missing {key}"


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
