r"""One profile leaves no trace in another (#1306).

A profile is meant to be a whole panel of its own — its own threads, its own log, its
own captures, its own daemon. It very nearly is, and the ways it was not were all the
same shape: a value that belongs to ONE account held by the PROCESS, which is right
while a panel means one profile and silently wrong the moment a window holds four.

Each case below was measured on a live four-profile panel before it was fixed, and each
would come back unnoticed, because none of them fails loudly:

  * **A capture heard every client on the machine.** Narrowing was a pid list read ONCE,
    at spawn — and a profile whose client lives in its own Windows session has no client
    yet while the panel is booting. Empty meant «hear everything» and meant it for the
    rest of the run: three of four profiles were logging each other's rallies and firing
    triggers off each other's pushes. The anchor is the SESSION now, and the capture
    looks the pids up again on its own clock.
  * **`tools/rdp_instance.py` had one commentary sink for the whole process.** A panel
    brings its profiles' clients and daemons up at the same time, each on its own
    thread, so two overlapping bring-ups wrote into each other's logs — and the
    restoring `finally` could leave the sink pointed at a profile that had closed.
  * **The remote-control server logged into whichever profile switched it on.** One
    server answers for every open profile, so `GET /api/state?profile=default` was
    landing verbatim in another account's `debug.log`, where nothing marks it as
    somebody else's.
  * **The three module-level fallback loggers were the unscoped tree** — which is the
    FIRST open profile's file, so a line nobody handed a logger to was filed under an
    account it had nothing to do with.

What is deliberately SHARED is pinned here too, so that a later reading of this file
cannot mistake it for something that was missed: the claim registry
(`panel/runtime/claims.py`) is one client and one desktop being taken turns over, and
«Прервать» / «перезапустить панель» are presses about the PROCESS.

Game-free — no client, no daemon, no npcap — but NOT Tk-free: `from panel.runtime import
game_process` runs `panel/runtime/__init__.py`, which reaches the settings binder and
`import tkinter`. So the file is `ui` and says so (#1284 is the same lesson):

    C:\Python312\python.exe tests\test_profile_isolation.py
"""
from __future__ import annotations

TIER = "ui"        # Tk (not a display) — see tools/run_tests.py

import logging
import os
import sys
import threading
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import map_capture                                        # noqa: E402
from panel import debug_log                               # noqa: E402
from panel.runtime import claims, game_process            # noqa: E402


class _Settings:
    """The two knobs `game_process` reads, and nothing else."""

    def __init__(self, rdp: bool = False, user: str = "") -> None:
        self._rdp, self._user = rdp, user

    def opt_bool(self, key: str) -> bool:
        return self._rdp if key == "rdp_session" else False

    def opt_str(self, key: str) -> str:
        return self._user if key == "rdp_user" else ""


# -- the captures -------------------------------------------------------------

def test_a_capture_is_narrowed_even_before_its_client_exists():
    """The regression itself: no client yet must not mean «hear the whole machine».

    `profile_pids` answers for the moment it is asked, and at the panel's boot that
    answer is empty for every profile whose client is in another Windows session. The
    argv must still carry an anchor.
    """
    def none_running(_settings):
        return []

    real, game_process.profile_pids = game_process.profile_pids, none_running
    try:
        rdp = game_process.capture_narrowing(_Settings(True, "Player1"))
        assert rdp == ["--client-user", "Player1"], rdp
        here = game_process.capture_narrowing(_Settings(False, ""))
        assert here == ["--client-own-session"], here
    finally:
        game_process.profile_pids = real


def test_the_pids_ride_along_as_a_seed_when_there_are_some():
    def two(_settings):
        return [11, 22]

    real, game_process.profile_pids = game_process.profile_pids, two
    try:
        args = game_process.capture_narrowing(_Settings(True, "Player1"))
        assert args == ["--client-user", "Player1",
                        "--client-pid", "11", "--client-pid", "22"], args
    finally:
        game_process.profile_pids = real


def test_every_narrowing_the_panel_can_produce_is_an_anchor():
    """Whatever `capture_narrowing` says, the capture must call itself anchored."""
    import argparse

    for settings in (_Settings(True, "Player1"), _Settings(False, "")):
        real, game_process.profile_pids = game_process.profile_pids, lambda _s: []
        try:
            argv = game_process.capture_narrowing(settings)
        finally:
            game_process.profile_pids = real
        ap = argparse.ArgumentParser()
        map_capture.add_capture_arguments(ap, include_dump=False)
        args = ap.parse_args(argv)
        watcher = map_capture.OwnPorts(args.client_pid,
                                       logins=args.client_user,
                                       own_session=args.client_own_session)
        assert watcher.anchored, argv


def test_a_capture_told_nothing_is_still_machine_wide():
    """The command line stays what it was: no flags, no narrowing, hear everything.

    Pinned because it is what every capture run BY HAND relies on, and because the
    panel's own promise («never deaf on doubt») is built on this being the meaning.
    """
    assert not map_capture.OwnPorts(()).anchored


def test_the_session_anchor_finds_a_client_that_was_not_there_at_spawn():
    """A late client is picked up by the next refresh instead of never."""
    found: list = []
    real = map_capture.game_link.pids
    map_capture.game_link.pids = lambda user=None, **_kw: list(found)
    stub = types.ModuleType("psutil")
    stub.pid_exists = lambda pid: False
    stub.process_iter = lambda attrs=None: []
    stub.net_connections = lambda kind="tcp": []
    sys.modules["psutil"] = stub
    try:
        watcher = map_capture.OwnPorts((), ttl=0.0, logins=("Player1",))
        assert watcher._live_pids() == set(), "there is no client yet"
        found.append(4001)
        assert watcher._live_pids() == {4001}, "the late client was never picked up"
    finally:
        map_capture.game_link.pids = real
        sys.modules.pop("psutil", None)


def test_a_session_not_logged_on_is_an_answer_and_a_failed_question_is_not():
    """The two ways of finding no client, which are not the same finding.

    A session that is not logged on has been ASKED and has answered: that account has
    no client, so nothing on the wire is its. A question that could not be PUT — no
    session table, no pywin32 — is doubt, and doubt keeps the traffic.
    """
    real = map_capture.game_link.pids
    stub = types.ModuleType("psutil")
    stub.pid_exists = lambda pid: False
    stub.process_iter = lambda attrs=None: []
    stub.net_connections = lambda kind="tcp": []
    sys.modules["psutil"] = stub
    try:
        def not_logged_on(user=None, **_kw):
            raise LookupError(f"no session for {user}")

        map_capture.game_link.pids = not_logged_on
        assert map_capture.OwnPorts((), ttl=0.0, logins=("Player1",))() == set(), (
            "an account with no client must hear nothing, not everything")

        def cannot_ask(user=None, **_kw):
            raise OSError("no session table on this machine")

        map_capture.game_link.pids = cannot_ask
        assert map_capture.OwnPorts((), ttl=0.0, logins=("Player1",))() is None, (
            "doubt must lose the separation, never the traffic")
    finally:
        map_capture.game_link.pids = real
        sys.modules.pop("psutil", None)


# -- the commentary sink ------------------------------------------------------

def test_two_bring_ups_at_once_do_not_write_into_each_others_logs():
    """`rdp_instance.spoken_to` is per thread, because bring-ups overlap."""
    import rdp_instance

    said: dict = {"a": [], "b": []}
    ready, go = threading.Event(), threading.Event()

    def profile_a():
        with rdp_instance.spoken_to(said["a"].append):
            ready.set()
            go.wait(5.0)
            rdp_instance.log("A speaks")

    def profile_b():
        ready.wait(5.0)
        with rdp_instance.spoken_to(said["b"].append):
            rdp_instance.log("B speaks")
        go.set()

    threads = [threading.Thread(target=profile_a), threading.Thread(target=profile_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10.0)

    assert [line for line in said["a"] if "A speaks" in line], said
    assert [line for line in said["b"] if "B speaks" in line], said
    assert not [line for line in said["a"] if "B speaks" in line], "B's line reached A"
    assert not [line for line in said["b"] if "A speaks" in line], "A's line reached B"


def test_a_sink_that_has_gone_does_not_outlive_its_block():
    """And the restore puts back THIS thread's previous sink, never another's.

    Read off the sink rather than off stdout: `log` falls back to `print`, and a test
    that captured stdout would be pinning where the fallback WRITES instead of that
    there is one.
    """
    import rdp_instance

    outer: list = []
    with rdp_instance.spoken_to(outer.append):
        with rdp_instance.spoken_to(lambda _line: None):
            rdp_instance.log("swallowed")
        rdp_instance.log("back to the outer sink")
    assert [line for line in outer if "back to the outer sink" in line], outer
    assert not [line for line in outer if "swallowed" in line], outer
    assert rdp_instance._say_now() is None, "a closed block left its sink behind"


# -- the logs -----------------------------------------------------------------

def test_the_windows_own_scope_is_not_any_profiles():
    """Anything that belongs to the WINDOW logs where no account can claim it."""
    assert debug_log.PANEL_SCOPE.startswith("_"), (
        "the window's scope must be a name `panel/profile.py::sanitize` refuses, "
        "or a profile could be created that collides with it")
    logger = debug_log.panel_logger("web")
    assert logger.name == f"{debug_log.ROOT_NAME}.{debug_log.PANEL_SCOPE}.web", logger.name
    # Sealed off the shared tree, which is the FIRST open profile's file.
    window = logging.getLogger(f"{debug_log.ROOT_NAME}.{debug_log.PANEL_SCOPE}")
    assert not window.propagate, "the window's lines would travel into a profile's file"


def test_the_module_fallback_loggers_are_the_windows_and_not_the_first_profiles():
    """The three components that can be built without being handed a logger."""
    from panel import dashboard, timers, triggers

    for module in (timers, triggers, dashboard):
        name = module._dbg_window().name
        assert debug_log.PANEL_SCOPE in name, (module.__name__, name)


def test_the_web_server_logs_to_the_window():
    """One server, every profile — so its access log belongs to none of them."""
    source = (_REPO / "panel" / "web" / "server.py").read_text(encoding="utf-8")
    assert "debug_log.panel_logger(\"web\")" in source
    assert "server.rt.dbg(\"web\")" not in source, (
        "the access log is back in whichever profile happened to start the server")


# -- what makes a profile a profile -------------------------------------------

def _scratch_profiles(tmp: str):
    """Point `panel.profile` at an empty tree and hand back a bare manager."""
    from panel import profile as profilemod

    profilemod.PROFILES_DIR = tmp
    manager = profilemod.ProfileManager.__new__(profilemod.ProfileManager)
    return profilemod, manager


def test_a_profile_is_a_directory_with_a_config_not_any_directory():
    """The definition, and the folder that forced it (#1306).

    `profiles/` also collects things that are not accounts — the squads report writes
    its faces into `profiles/<report>_avatars/` — and «every directory in profiles/»
    made one of those an account with a share in another profile's daemon. Reserving
    that one name would have fixed that one folder.
    """
    import tempfile
    from panel import profile as profilemod

    keep = profilemod.PROFILES_DIR
    with tempfile.TemporaryDirectory() as tmp:
        try:
            mod, manager = _scratch_profiles(tmp)
            for name in ("alpha", "avatars_of_a_report", "beta"):
                os.makedirs(os.path.join(tmp, name))
            for name in ("alpha", "beta"):
                with open(os.path.join(tmp, name, mod.CONFIG_FILE), "w",
                          encoding="utf-8") as fh:
                    fh.write("{}")

            assert manager.list() == ["alpha", "beta"], manager.list()
            assert manager.exists("alpha")
            assert not manager.exists("avatars_of_a_report"), (
                "a folder with no config is an account again")
        finally:
            profilemod.PROFILES_DIR = keep


def test_an_empty_config_is_still_a_profile():
    """`{}` means «nothing overridden», not «not a profile».

    Pinned because the rule above is about the FILE existing, and a profile that has
    never had a setting changed is exactly the one whose file is empty.
    """
    import tempfile
    from panel import profile as profilemod

    keep = profilemod.PROFILES_DIR
    with tempfile.TemporaryDirectory() as tmp:
        try:
            mod, manager = _scratch_profiles(tmp)
            os.makedirs(os.path.join(tmp, "untouched"))
            with open(os.path.join(tmp, "untouched", mod.CONFIG_FILE), "w",
                      encoding="utf-8") as fh:
                fh.write("{}")
            assert manager.list() == ["untouched"]
            assert manager.exists("untouched")
        finally:
            profilemod.PROFILES_DIR = keep


def test_a_folder_that_is_not_a_profile_is_SAID_not_skipped():
    """«Passed over quietly» and «there was nothing there» must not look the same.

    Two different things land in `strays()` — a report's pictures, and a real profile
    whose config was lost and which has just become invisible — and only the person
    can tell which they are looking at. So the panel says the line either way.
    """
    import tempfile
    from panel import profile as profilemod

    keep = profilemod.PROFILES_DIR
    with tempfile.TemporaryDirectory() as tmp:
        try:
            mod, manager = _scratch_profiles(tmp)
            os.makedirs(os.path.join(tmp, "alpha"))
            with open(os.path.join(tmp, "alpha", mod.CONFIG_FILE), "w",
                      encoding="utf-8") as fh:
                fh.write("{}")
            os.makedirs(os.path.join(tmp, "avatars_of_a_report"))
            os.makedirs(os.path.join(tmp, "_bot"))          # machinery: never said
            os.makedirs(os.path.join(tmp, ".hidden"))       # nor is a dot-directory

            assert manager.strays() == ["avatars_of_a_report"], manager.strays()
        finally:
            profilemod.PROFILES_DIR = keep


def test_the_shell_says_the_line_and_it_exists_in_every_locale():
    """The saying half: a key, in all eleven, said off `strays()` at boot."""
    import json

    source = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "log.profile.not_a_profile" in source, "nothing says it"
    assert "profiles.strays()" in source, "the line is said off something else"

    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, [p.name for p in locales]
    for path in locales:
        text = json.loads(path.read_text(encoding="utf-8"))
        assert "log.profile.not_a_profile" in text, path.name
        assert "{name}" in text["log.profile.not_a_profile"], path.name


def test_the_backfill_that_would_undo_all_this_is_gone():
    """The old rule wrote a config into every listed directory — including the strays.

    It is how `profiles/rally_report_avatars/` came to hold a `config.json` on the live
    machine: the panel PROMOTED the folder. Run over directories rather than over
    profiles, that loop turns every stray into an account, so its absence is part of
    the definition rather than tidying.
    """
    source = (_REPO / "panel" / "profile.py").read_text(encoding="utf-8")
    body = source[source.index("def __init__(self, pin"):
                  source.index("    # -- profile enumeration")]
    assert "for existing in self.list()" not in body, (
        "the backfill loop is back; it re-promotes strays into accounts")


# -- what is NOT an account's -------------------------------------------------

def test_the_cache_is_shared_asked_for_in_one_place_and_not_in_profiles():
    """Isolation is about what belongs to an ACCOUNT; a downloaded face is not one.

    The same player has the same picture whichever profile met them first, so the faces
    and the pages built from every profile's archive live in one shared directory. It
    must not be inside `profiles/` either — that tree is accounts, and a folder sitting
    in it is what started #1306's last chapter.
    """
    import game_paths
    from panel import paths as panel_paths

    cache = os.path.abspath(game_paths.cache_dir())
    profiles = os.path.abspath(panel_paths.PROFILES_DIR)
    assert os.path.commonpath([cache, profiles]) != profiles, (
        f"the shared cache is inside the accounts' tree: {cache}")
    for path in (game_paths.avatar_cache(), game_paths.report_dir()):
        assert os.path.abspath(path).startswith(cache + os.sep), path


def test_the_cache_moves_with_one_variable_and_nothing_re_spells_it():
    """One place answers it, as everything machine-dependent here does."""
    import game_paths

    keep = os.environ.get("LW_CACHE_DIR")
    os.environ["LW_CACHE_DIR"] = os.path.join("elsewhere", "lw")
    try:
        assert game_paths.cache_dir() == os.path.join("elsewhere", "lw")
        assert game_paths.avatar_cache().startswith(os.path.join("elsewhere", "lw"))
    finally:
        if keep is None:
            os.environ.pop("LW_CACHE_DIR", None)
        else:
            os.environ["LW_CACHE_DIR"] = keep

    # …and the report tool asks it rather than spelling a path of its own. The literal
    # is what the old per-report folder was BUILT from, so its absence is the check;
    # `copy_avatars` and the prose explaining the move keep the word legitimately.
    source = (_REPO / "tools" / "rally_report.py").read_text(encoding="utf-8")
    assert "game_paths.avatar_cache()" in source
    assert '"_avatars"' not in source, "the per-report avatar folder is back in the code"
    assert "profiles/rally_report.html" not in source, "the old default is back"


def test_the_shared_cache_is_git_ignored():
    """It is other people's photographs and two hundred nicknames, like `profiles/`."""
    ignore = (_REPO / ".gitignore").read_text(encoding="utf-8").split("\n")
    assert "cache/" in [line.strip() for line in ignore], "cache/ is not ignored"


# -- what is shared ON PURPOSE ------------------------------------------------

def test_the_claim_registry_is_process_wide_and_is_meant_to_be():
    """One client and one desktop: profiles take turns, they do not each get one."""
    claims.clear()
    try:
        assert claims.acquire(("127.0.0.1", 47654), "alpha") is None
        # A SECOND profile pointed at the SAME client is refused, and told by whom.
        assert claims.acquire(("127.0.0.1", 47654), "beta") == "alpha"
        # …and a profile with its own client is not made to wait for anything.
        assert claims.acquire(("127.0.0.1", 47655), "beta") is None
    finally:
        claims.clear()


def test_a_profile_with_its_own_desktop_does_not_queue_for_the_foreground():
    """The one exemption, because a Windows session of one's own is a desktop of one's own."""
    claims.clear()
    try:
        with claims.Foreground("alpha") as first:
            assert first.taken is None
            with claims.Foreground("beta") as second:
                assert second.taken == "alpha", "two scenarios would click into one screen"
            with claims.Foreground("gamma", exempt=True) as own_desktop:
                assert own_desktop.taken is None, "an RDP profile was made to wait"
    finally:
        claims.clear()


# -- the status strip along the bottom (#1391) --------------------------------
#
# The one line in the window that says what is happening NOW was showing the newest
# step of EVERY open profile, with the owner's name glued in front. So a person reading
# one account's page was told what a different account was doing — and because the strip
# keeps the newest step, a busy background profile painted over the foreground one's,
# which made the line least trustworthy exactly when the profile being watched was
# working hardest.

def _strip(front, behind, window):
    """A stand-in for the window: the three activities the strip can reach."""
    import panel.__main__ as pm

    fake = types.SimpleNamespace(
        _activity=window,
        _current_session=types.SimpleNamespace(
            name="front", rt=types.SimpleNamespace(activity=front)),
        _workspace=[object(), object()],           # two profiles open, `len()` is all
        _t=lambda key, **fmt: key)
    fake._activities = lambda: pm.Panel._activities(fake)
    fake._activity_text = lambda: pm.Panel._activity_text(fake)
    fake._behind = behind
    return fake


def test_the_status_strip_never_draws_another_profiles_step():
    """Two profiles open, the other one busier: the strip stays on this one."""
    from panel.runtime.activity import Activity

    window, front, behind = Activity(), Activity("front"), Activity("behind")
    strip = _strip(front, behind, window)

    front.begin("activity.tab.build", name="rally")
    behind.begin("activity.daemon.start", port=47655)      # newer, and NOT ours
    assert behind not in strip._activities(), "another account's activity is reachable"
    assert strip._activity_text() == "activity.tab.build", (
        "the strip drew the profile that is not on screen")

    # …and with nothing of our own running, a busy neighbour still says nothing.
    front.clear()
    assert strip._activity_text() == "activity.idle", (
        "an idle page reported another account's work as its own")


def test_the_windows_own_steps_are_still_drawn():
    """Opening a profile, pulling an update, restarting: the PROCESS's, and shown.

    The narrowing must not take these with it — they are what the strip is for while a
    page is being built, and they belong to whoever is looking at the window.
    """
    from panel.runtime.activity import Activity

    window, front, behind = Activity(), Activity("front"), Activity("behind")
    strip = _strip(front, behind, window)
    window.begin("activity.profile.open", name="other")
    assert strip._activity_text() == "activity.profile.open"


def test_the_strip_asks_the_page_on_screen_not_the_thread_it_is_on():
    """`_current_session`, never `_session()` (the thread's) or the whole workspace.

    A repaint is handed over from the worker thread of whichever profile reported a
    step, so «the session this thread is acting for» is the BACKGROUND one precisely
    when it matters — that is the same back door, one level down.
    """
    import inspect

    import panel.__main__ as pm

    body = inspect.getsource(pm.Panel._activities)
    assert "_current_session" in body, "the strip stopped asking what is on screen"
    assert "self._workspace.sessions" not in body, (
        "the strip walks every open profile again")
    assert "self._session()" not in body, (
        "the strip follows the thread instead of the glass")


def test_interrupt_is_still_every_profile_and_is_meant_to_be():
    """The press beside the strip did NOT narrow with the reading, and that is the rule.

    «Прервать» is one of the two presses about the PROCESS (with «перезапустить
    панель»): a window holds several accounts and the run that has to be stopped is not
    reliably the one being looked at. The READING is an account's, the PRESS is the
    machine's — so this is pinned from both sides rather than left to look like an
    oversight in whichever direction the next reader is going.
    """
    import inspect

    import panel.__main__ as pm

    for method in (pm.Panel._interrupt_all, pm.Panel._runs_live):
        body = inspect.getsource(method)
        assert "self._workspace.sessions" in body, (
            f"{method.__name__} stopped reaching every open profile")


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
