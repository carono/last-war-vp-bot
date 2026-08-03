r"""Two profiles open in ONE process do not touch each other (#1206, wave 1).

Everything the panel does to the game used to be answered by the PROCESS: the lease
token in `os.environ`, the daemon port in `lua_client`'s module state, the debug log's
single file handler, the active-profile pointer in `panel/settings.json`, the language
in `~/.last_war_panel.json`. One profile at a time, and every one of those was right.
With two runtimes in one window they are all wrong in the same way — the second one to
be built silently redefines the first — so each is pinned here:

  * a claim by one game link leaves the other's lease alone, and neither writes the
    environment any more;
  * a child is launched with ITS OWN runtime's port and lease, and with no stale
    LW_GAME_LEASE inherited from whoever started the panel;
  * a scenario is told which client to press: `ActionRunner` hands the interpreter its
    runtime's port and token, and the interpreter builds its evaluator on them — which
    is also the one-profile bug it fixes, a profile on 47655 pressing into 47654;
  * two debug-log scopes are two files, and an unscoped call still means the shared
    one;
  * a PINNED profile manager moves itself and never the panel's saved pointer;
  * a translator built for one open profile does not rename the machine's language;
  * and, with two clients actually up, a profile that names no Windows session means
    THIS desktop's client rather than whichever one the process list happened to list
    first — which is what made both profiles' status strips point at one pid.

Tk-free on purpose — none of this is about widgets. Runs anywhere:

    python3 tests/test_panel_multi_profile.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_client                                          # noqa: E402
from lastwar_bot import script_engine                      # noqa: E402
from panel import debug_log as dbg                         # noqa: E402
from panel import i18n as i18nmod                          # noqa: E402
from panel import profile as profilemod                    # noqa: E402
from panel.runtime import game_process as gp               # noqa: E402
from panel.runtime.actions import ActionRunner             # noqa: E402
from panel.runtime.children import ChildFactory, LEASE_VAR  # noqa: E402
from panel.runtime.daemon import GameLink                  # noqa: E402


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

class _Log:
    """A LogBus that only remembers, so a refusal can be read back."""

    def __init__(self) -> None:
        self.lines: list = []

    def put(self, line) -> None:
        self.lines.append(str(line))

    def say(self, tag, key, **fmt) -> None:
        self.lines.append(f"{tag}:{key}")


class _Daemon:
    """One daemon's lease, shared by every client built against it.

    Deliberately not a mock of `DaemonClient`: the point of the test is that two links
    take turns at the SAME daemon and hold DIFFERENT tokens at the same daemon, and
    that only comes out against something that actually keeps one lease.
    """

    def __init__(self, port: int) -> None:
        self.port = port
        self.held: str = ""          # the live token, "" when free
        self.owner: str = ""
        self.issued = 0

    def client(self, token=None):
        return _Client(self, token)


class _Client:
    def __init__(self, daemon: _Daemon, token=None) -> None:
        self._d = daemon
        self.port = daemon.port
        self.token = lua_client.current_lease() if token is None else token

    def acquire(self, owner: str, ttl: float = 120.0):
        if self._d.held and self._d.held != self.token:
            return None
        if not self._d.held:
            self._d.issued += 1
            # The port is in the token so two daemons can never mint the same one —
            # which is the whole thing the child-environment test is looking at.
            self._d.held = f"tok{self._d.port}-{self._d.issued}"
            self._d.owner = owner
        self.token = self._d.held
        return self.token

    def release(self) -> bool:
        if not self.token:
            return True
        try:
            if self._d.held == self.token:
                self._d.held, self._d.owner = "", ""
            return True
        finally:
            self.token = ""

    def lease_state(self) -> dict:
        return {"owner": self._d.owner, "held_sec": 1}


def _link(daemon: _Daemon, log=None) -> GameLink:
    link = GameLink(port=lambda: daemon.port, python=lambda: "python", log=log or _Log(),
                    env=dict, cwd=str(_REPO), daemon_script="x")
    link.client = daemon.client(token="")
    return link


# ---------------------------------------------------------------------------
# the lease belongs to the link
# ---------------------------------------------------------------------------

def test_a_claim_does_not_write_the_process_environment() -> None:
    saved = os.environ.pop(LEASE_VAR, None)
    try:
        link = _link(_Daemon(47654))
        assert link.claim("panel") is True
        assert LEASE_VAR not in os.environ, "the token is the link's, not the process's"
        assert link.token, "…and the link knows it holds one"
        link.release()
        assert link.token == ""
    finally:
        if saved is not None:
            os.environ[LEASE_VAR] = saved


def test_two_links_on_two_daemons_hold_two_leases_at_once() -> None:
    a, b = _link(_Daemon(47654)), _link(_Daemon(47655))
    assert a.claim("main") and b.claim("alt"), "two clients, two leases, no contention"
    assert a.token and b.token
    a.release()
    assert a.token == "" and b.token, "one letting go must not disarm the other"
    b.release()


def test_two_links_on_ONE_daemon_still_take_turns() -> None:
    """Two profiles pointed at the same port are two views of ONE client."""
    daemon = _Daemon(47654)
    log = _Log()
    a, b = _link(daemon, log), _link(daemon, log)
    assert a.claim("main") is True
    assert b.claim("alt") is False, "the second must be refused — it is the same game"
    assert any("busy.elsewhere" in line for line in log.lines)
    a.release()
    assert b.claim("alt") is True, "…and get it once the first lets go"
    b.release()


def test_releasing_an_unreachable_daemon_still_drops_the_token() -> None:
    """Otherwise a child spawned afterwards waves a token the daemon has given away."""
    class _Gone(_Client):
        def release(self):
            try:
                raise OSError("no daemon")
            finally:
                self.token = ""

    daemon = _Daemon(47654)
    link = _link(daemon)
    link.client = _Gone(daemon, token="")
    link.claim("panel")
    link.release()
    assert link.token == ""


# ---------------------------------------------------------------------------
# a child is launched against its own runtime
# ---------------------------------------------------------------------------

def test_a_child_carries_its_own_runtimes_port_and_lease() -> None:
    a, b = _link(_Daemon(47654)), _link(_Daemon(47655))
    fa = ChildFactory(log=_Log(), cwd=".", python=lambda: "py",
                      port=a.port, schedule=None, token=lambda: a.token)
    fb = ChildFactory(log=_Log(), cwd=".", python=lambda: "py",
                      port=b.port, schedule=None, token=lambda: b.token)
    a.claim("main")
    b.claim("alt")
    ea, eb = fa.env(), fb.env()
    assert ea["LW_DAEMON_PORT"] == "47654" and eb["LW_DAEMON_PORT"] == "47655"
    assert ea[LEASE_VAR] == a.token and eb[LEASE_VAR] == b.token
    assert ea[LEASE_VAR] != eb[LEASE_VAR]
    a.release()
    b.release()


def test_an_unheld_lease_removes_the_variable_rather_than_passing_a_stale_one() -> None:
    saved = os.environ.get(LEASE_VAR)
    os.environ[LEASE_VAR] = "inherited-from-whoever-started-the-panel"
    try:
        link = _link(_Daemon(47654))
        factory = ChildFactory(log=_Log(), cwd=".", python=lambda: "py",
                               port=link.port, schedule=None, token=lambda: link.token)
        assert LEASE_VAR not in factory.env()
    finally:
        if saved is None:
            os.environ.pop(LEASE_VAR, None)
        else:
            os.environ[LEASE_VAR] = saved


# ---------------------------------------------------------------------------
# a scenario is told which client to press
# ---------------------------------------------------------------------------

def test_the_runner_hands_the_interpreter_its_own_client() -> None:
    seen: dict = {}

    def fake_run_action(name, hwnd, **kw):
        seen.update(kw)
        return True

    runner = ActionRunner(log=_Log(),
                          target=lambda: {"game_port": 47655, "game_token": "tok9"})
    saved = script_engine.run_action
    script_engine.run_action = fake_run_action
    try:
        runner.run("collect_base_resources")
    finally:
        script_engine.run_action = saved
    assert seen.get("game_port") == 47655, seen
    assert seen.get("game_token") == "tok9", seen


def test_the_runner_hands_the_interpreter_the_session_the_client_lives_in() -> None:
    """The third of the target's answers, and the only one a LAUNCH could use (#1218).

    The port reaches a client through the daemon attached to it; `START_GAME` runs when
    there is nothing to be attached to yet, so the Windows session has to travel with
    the run or the launcher lands on the panel's own desktop.
    """
    seen: dict = {}

    def fake_run_action(name, hwnd, **kw):
        seen.update(kw)
        return True

    runner = ActionRunner(log=_Log(),
                          target=lambda: {"game_port": 47655, "game_token": "tok9",
                                          "game_user": "player2"})
    saved = script_engine.run_action
    script_engine.run_action = fake_run_action
    try:
        runner.run("launch_game")
    finally:
        script_engine.run_action = saved
    assert seen.get("game_user") == "player2", seen


class _Spawned:
    """Just enough of a Popen for `ensure` to carry on past the spawn."""

    pid = 4321


def _cold_link(port: int, user=None) -> GameLink:
    """A link whose daemon is never up, so `ensure` always reaches the start."""
    link = GameLink(port=lambda: port, python=lambda: "python", log=_Log(),
                    env=dict, cwd=str(_REPO), daemon_script="x",
                    user=(lambda: user) if user else None)
    link.up = lambda: False
    return link


def _ensure_watching_popen(link) -> list:
    """Run `link.ensure()` with the spawn recorded and the retry loop cut to one turn."""
    import subprocess

    from panel.runtime import daemon as daemonmod

    spawned: list = []
    saved_popen, saved_tries, saved_wait = (subprocess.Popen, daemonmod.START_TRIES,
                                            daemonmod.START_WAIT)
    subprocess.Popen = lambda *a, **kw: (spawned.append(a), _Spawned())[1]
    daemonmod.START_TRIES, daemonmod.START_WAIT = 1, 0
    try:
        link.ensure()                     # it never comes up; the START is the point
    finally:
        subprocess.Popen = saved_popen
        daemonmod.START_TRIES, daemonmod.START_WAIT = saved_tries, saved_wait
    return spawned


def test_a_daemon_for_another_session_is_started_INSIDE_it() -> None:
    """A daemon hijacks a thread of the client it drives, and finds that client in the
    session it is itself running in. Started here for a profile whose game is in
    session 4, it would bind the right port and then drive this desktop's game — or
    none at all. So the session decides HOW it is started, not just what it finds."""
    link = _cold_link(47655, user="player2")
    seen: dict = {}
    link._start_in_session = lambda user, port: seen.update(user=user, port=port)
    spawned = _ensure_watching_popen(link)
    assert seen == {"user": "player2", "port": 47655}, seen
    assert spawned == [], "a daemon for another session must not be spawned here"


def test_a_daemon_for_this_desktop_is_still_spawned_here() -> None:
    """The single-account case, untouched: no session named means the ordinary child."""
    link = _cold_link(47654)
    link._start_in_session = lambda user, port: (_ for _ in ()).throw(
        AssertionError("nothing named a session"))
    assert len(_ensure_watching_popen(link)) == 1


def test_a_session_nobody_is_logged_on_to_is_a_refusal_not_a_crash() -> None:
    """`_start_in_session` raises; `ensure` has to answer False and say so, because the
    caller of a daemon start is a button and the alternative is a traceback nobody sees.
    """
    link = _cold_link(47655, user="ghost")
    link._start_in_session = lambda user, port: (_ for _ in ()).throw(
        LookupError(f"nobody is logged on as {user}"))
    states: list = []
    link.on_state = lambda state, ok: states.append((state, ok))
    assert link.ensure() is False
    assert ("error", False) in states, states


def test_a_profile_on_this_desktop_names_no_session_at_all() -> None:
    """`None` is left OUT rather than passed as one — "this desktop" is the default."""
    seen: dict = {}

    def fake_run_action(name, hwnd, **kw):
        seen.update(kw)
        return True

    runner = ActionRunner(log=_Log(),
                          target=lambda: {"game_port": 47654, "game_token": "",
                                          "game_user": None})
    saved = script_engine.run_action
    script_engine.run_action = fake_run_action
    try:
        runner.run("launch_game")
    finally:
        script_engine.run_action = saved
    assert "game_user" not in seen, seen


def test_a_runner_without_a_target_says_nothing_and_the_environment_answers() -> None:
    """The old behaviour, kept for every harness and every one-tab window."""
    seen: dict = {}

    def fake_run_action(name, hwnd, **kw):
        seen.update(kw)
        return True

    runner = ActionRunner(log=_Log())
    saved = script_engine.run_action
    script_engine.run_action = fake_run_action
    try:
        runner.run("collect_base_resources")
    finally:
        script_engine.run_action = saved
    assert "game_port" not in seen and "game_token" not in seen, seen


def test_the_context_carries_the_client_into_the_evaluator() -> None:
    """The one-profile bug too: a profile on 47655 used to press into 47654."""
    asked: dict = {}

    def fake_get_evaluator(*a, **kw):
        asked.update(kw)
        return object()

    ctx = script_engine.new_context(game_port=47655, game_token="tok7")
    interp = script_engine.Interpreter(ctx)
    saved = lua_client.get_evaluator
    lua_client.get_evaluator = fake_get_evaluator
    try:
        interp._evaluator()
    finally:
        lua_client.get_evaluator = saved
    assert asked == {"port": 47655, "token": "tok7"}, asked


def test_a_context_that_names_no_client_asks_for_the_process_default() -> None:
    asked: dict = {"called": False}

    def fake_get_evaluator(*a, **kw):
        asked["called"] = True
        asked.update(kw)
        return object()

    interp = script_engine.Interpreter(script_engine.new_context())
    saved = lua_client.get_evaluator
    lua_client.get_evaluator = fake_get_evaluator
    try:
        interp._evaluator()
    finally:
        lua_client.get_evaluator = saved
    assert asked["called"] and "port" not in asked and "token" not in asked, asked


def test_get_evaluator_passes_the_token_to_the_client_it_builds() -> None:
    built: dict = {}

    class _Fake:
        def __init__(self, host, port, token=None):
            built.update(host=host, port=port, token=token)

    saved_cls, saved_up = lua_client.DaemonClient, lua_client.is_running
    lua_client.DaemonClient = _Fake
    lua_client.is_running = lambda host, port, timeout=1.0: True
    try:
        lua_client.get_evaluator(port=47655, token="tok3")
    finally:
        lua_client.DaemonClient, lua_client.is_running = saved_cls, saved_up
    assert built["port"] == 47655 and built["token"] == "tok3", built


# ---------------------------------------------------------------------------
# two debug logs
# ---------------------------------------------------------------------------

def _drop(name: str) -> None:
    lg = logging.getLogger(name)
    for h in list(lg.handlers):
        lg.removeHandler(h)
        try:
            h.close()
        except Exception:                 # noqa: BLE001
            pass


def test_two_scopes_are_two_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        one, two = os.path.join(tmp, "a.log"), os.path.join(tmp, "b.log")
        dbg.configure(one, scope="s1")
        dbg.configure(two, scope="s2")
        try:
            dbg.get_logger("timers", scope="s1").info("errand of the first")
            dbg.get_logger("timers", scope="s2").info("errand of the second")
            for handler in (logging.getLogger(dbg._scope_name("s1")).handlers
                            + logging.getLogger(dbg._scope_name("s2")).handlers):
                handler.flush()
            first = Path(one).read_text(encoding="utf-8")
            second = Path(two).read_text(encoding="utf-8")
        finally:
            dbg.shutdown("s1")
            dbg.shutdown("s2")
            _drop(dbg._scope_name("s1"))
            _drop(dbg._scope_name("s2"))
    assert "errand of the first" in first and "errand of the second" not in first
    assert "errand of the second" in second and "errand of the first" not in second
    assert "[timers]" in first, "the scope is the file, not a prefix on every line"


def test_a_scoped_line_does_not_also_land_in_the_shared_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        shared, mine = os.path.join(tmp, "shared.log"), os.path.join(tmp, "mine.log")
        dbg.configure(shared)
        dbg.configure(mine, scope="s3")
        try:
            dbg.get_logger("timers", scope="s3").info("only mine")
            for handler in (logging.getLogger(dbg.ROOT_NAME).handlers
                            + logging.getLogger(dbg._scope_name("s3")).handlers):
                handler.flush()
            assert "only mine" not in Path(shared).read_text(encoding="utf-8")
            assert "only mine" in Path(mine).read_text(encoding="utf-8")
        finally:
            dbg.shutdown("s3")
            dbg.shutdown()
            _drop(dbg._scope_name("s3"))
            _drop(dbg.ROOT_NAME)


def test_an_unscoped_call_is_the_shared_tree_it_always_was() -> None:
    assert dbg.get_logger("timers").name == f"{dbg.ROOT_NAME}.timers"
    assert dbg.get_logger("timers", scope="s1").name == f"{dbg.ROOT_NAME}.s1.timers"


# ---------------------------------------------------------------------------
# a pinned profile manager
# ---------------------------------------------------------------------------

class _Profiles:
    """`profilemod` pointed at a scratch directory for the duration of a test."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE)
        profilemod.PROFILES_DIR = os.path.join(root, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
        return self

    def pointer(self) -> str:
        try:
            with open(profilemod.SETTINGS_FILE, encoding="utf-8") as fh:
                return json.load(fh).get("active_profile", "")
        except (OSError, ValueError):
            return ""

    def __exit__(self, *exc):
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._saved
        self._tmp.cleanup()
        return False


def test_a_pinned_manager_never_moves_the_panels_saved_pointer() -> None:
    with _Profiles() as env:
        panel = profilemod.ProfileManager()
        panel.create("main")
        panel.create("alt")
        panel.set_active("main")
        assert env.pointer() == "main"

        pinned = profilemod.ProfileManager(pin="alt")
        assert pinned.active == "alt" and pinned.pinned
        assert env.pointer() == "main", "opening a second profile is not switching to it"

        pinned.set_active("alt")
        assert env.pointer() == "main"


def test_two_managers_answer_for_two_profiles_at_once() -> None:
    with _Profiles() as env:
        profilemod.ProfileManager().create("alt")
        main = profilemod.ProfileManager(pin="main")
        alt = profilemod.ProfileManager(pin="alt")
        main.save({"daemon_port": 47654})
        alt.save({"daemon_port": 47655})
        assert main.load()["daemon_port"] == 47654
        assert alt.load()["daemon_port"] == 47655
        assert main.debug_log() != alt.debug_log()
        assert main.timers_json() != alt.timers_json()
        assert env.pointer() in ("", "main", "alt", "default")


def test_an_unpinned_manager_is_the_panels_own_and_still_writes() -> None:
    with _Profiles() as env:
        mgr = profilemod.ProfileManager()
        mgr.create("main")
        mgr.set_active("main")
        assert mgr.pinned is False
        assert env.pointer() == "main"


# ---------------------------------------------------------------------------
# the language of one open profile is not the machine's
# ---------------------------------------------------------------------------

def test_a_non_persisting_translator_leaves_the_machine_wide_choice_alone() -> None:
    langs = i18nmod.available_langs()
    other = next((code for code in langs if code != i18nmod.DEFAULT_LANG), None)
    assert other, "the repo ships more than one locale"

    written: list = []
    saved = i18nmod.I18n._save_pref
    i18nmod.I18n._save_pref = lambda self, lang: written.append(lang)
    try:
        quiet = i18nmod.I18n(i18nmod.DEFAULT_LANG, persist=False)
        assert quiet.set_lang(other) is True and quiet.lang == other
        assert written == [], "an open profile must not rename the machine's language"

        loud = i18nmod.I18n(i18nmod.DEFAULT_LANG)
        assert loud.set_lang(other) is True
        assert written == [other], "the panel's own window still remembers"
    finally:
        i18nmod.I18n._save_pref = saved


# ---------------------------------------------------------------------------
# with two clients up, each profile must find ITS OWN
# ---------------------------------------------------------------------------

class _TwoClients:
    """Session 1 holds this desktop's client, session 4 holds the second account's."""

    def __init__(self, here=1) -> None:
        self.here = here
        self.procs = {1: [1001], 4: [4004]}

    def __enter__(self):
        self._saved = (gp.sessions, gp._pids_in_session, gp._pids_by_name,
                       gp._endpoint, gp._client_sockets, gp.own_session)
        gp.sessions = lambda: [{"id": 1, "user": "player1", "state": gp.WTS_ACTIVE},
                               {"id": 4, "user": "player2",
                                "state": gp.WTS_DISCONNECTED}]
        gp._pids_in_session = lambda exe, session: list(self.procs.get(session, ()))
        gp._pids_by_name = lambda exe: [p for ps in self.procs.values() for p in ps]
        gp._endpoint = lambda found: None
        gp._client_sockets = lambda found: []   # not visible here, so no verdict
        gp.own_session = lambda: self.here
        return self

    def __exit__(self, *exc):
        (gp.sessions, gp._pids_in_session, gp._pids_by_name,
         gp._endpoint, gp._client_sockets, gp.own_session) = self._saved
        return False


class _Knobs:
    def __init__(self, **kw) -> None:
        self._v = {"game_exe": "LastWar.exe", "rdp_session": False, "rdp_user": ""}
        self._v.update(kw)

    def opt_str(self, key):
        return str(self._v.get(key, ""))

    def opt_bool(self, key):
        return bool(self._v.get(key))

    def opt_int(self, key, low=None, high=None):
        return int(self._v.get(key, 0))


def test_a_profile_naming_no_session_means_THIS_desktop_not_any_client() -> None:
    """The bug the second account made visible: both profiles reported one pid."""
    with _TwoClients(here=1):
        assert gp.pids("LastWar.exe") == [1001], "ours, not whichever came first"
        assert gp.pids("LastWar.exe", user="player2") == [4004]

        console = gp.profile_status(_Knobs())
        second = gp.profile_status(_Knobs(rdp_session=True, rdp_user="player2"))
        assert console[0] and second[0]
        assert "1001" in str(console[1]) and "4004" in str(second[1])
        assert str(console[1]) != str(second[1]), \
            "two clients, two answers — this is the whole point"


def test_a_machine_that_cannot_be_asked_falls_back_to_the_name() -> None:
    """One session is the only session there; the old answer is the right one."""
    with _TwoClients(here=None):
        assert gp.pids("LastWar.exe") == [1001, 4004]


def test_a_named_session_that_does_not_exist_is_still_an_error_not_an_empty_list() -> None:
    with _TwoClients():
        try:
            gp.pids("LastWar.exe", user="nobody")
        except LookupError:
            return
        raise AssertionError("an unanswerable question must not read as «not running»")


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
