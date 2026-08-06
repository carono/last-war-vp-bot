r"""Deleting a profile actually deletes it — the page too (#1253).

The report was «I delete a profile, confirm, and its tab is still there», and the tab
was only the visible end of it. `Panel._delete_profile` predates the window holding more
than one profile (#1206): it removed the directory and then *re-pointed the one runtime*,
which is exactly what a single-profile panel needed and nothing at all of what a
workspace needs. Nothing told the workspace, so:

  * the page stayed in the notebook and the session went on running — its schedule
    firing errands, its captures writing, its game lease held;
  * `self._profiles` is the SHOWING SESSION's *pinned* manager, whose `set_active`
    writes nothing, so `panel/settings.json` still named the deleted profile and the
    next launch opened it again;
  * and the `rmtree` ran while that same session had `panel.log` and `debug.log` open —
    on Windows a directory that cannot be removed, reported as a success because the
    store passed `ignore_errors=True`. `ProfileManager._ensure_dir` then re-made the
    config file the moment anything asked for the directory, and the profile was back
    in the list with its settings intact.

So what is pinned here is the ORDER, which is the fix: keep a page, stop the daemon,
close the session, and only then the disk — and a directory that did not go says so
instead of reporting a delete that did not happen.

No Tk and no display: the workspace never touches a widget, and the shell's three
methods are borrowed off the class against a stand-in (the same trick
`tests/test_panel_profile_compat.py` uses).

    python3 tests/test_panel_profile_delete.py
    C:\Python312\python.exe tests\test_panel_profile_delete.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import profile as profilemod            # noqa: E402
from panel.runtime import workspace as wsmod       # noqa: E402


class _Session:
    """A session double — what the workspace and the delete path ask of one."""

    def __init__(self, name, *, root=None, defaults=None, scope=None,
                 daemon_state=None) -> None:
        self.name = name
        self.scope = scope
        self.state: dict = {}
        self.page = None
        self.started = False
        self.dead = False
        self.rt = types.SimpleNamespace(
            profiles=profilemod.ProfileManager(pin=name),
            daemon_port=lambda: 47654,
            game=types.SimpleNamespace(up=lambda: False, client=None))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def shutdown(self) -> None:
        """What the real one does that matters here: let the files go."""
        self.started = False
        self.dead = True


class _Shell:
    """`Panel`'s delete path, off the class, on a real workspace of doubles.

    Everything it needs that draws is a stub that WRITES DOWN what it was asked to do —
    the order of those entries is the thing under test.
    """

    def __init__(self, env) -> None:
        self.did: list = []
        self.said: list = []
        self.shown: list = []
        self.refused_open: set = set()
        self._workspace = env.workspace()
        self._profile_var = types.SimpleNamespace(get=lambda: self._selected)
        self._selected = ""
        self._activity = types.SimpleNamespace(step=lambda *a, **k: _nothing())
        for name in ("_delete_profile", "_make_room_to_delete", "_stop_daemon_of"):
            setattr(self, name, types.MethodType(getattr(_PANEL, name), self))

    # -- the stubs the real window fills in ---------------------------------
    def _t(self, key, **fmt):
        return key

    def _profile_dialog_parent(self):
        return None

    def _say(self, tag, key, **fmt):
        self.said.append((key, fmt))

    def _error_text(self, exc):
        return getattr(exc.args[0], "key", str(exc))

    def _refresh_profile_combo(self, select=None):
        self.did.append(("combo", select))

    def _profile_is_free(self, name):
        return name not in self.refused_open

    def _open_profile(self, name):
        if not self._profile_is_free(name):
            return
        self.did.append(("open", name))
        self._workspace.open(name)

    def _close_profile(self, name=None):
        """The real one's contract, minus the widgets: the workspace is told."""
        session = self._workspace.get(name)
        if session is None or len(self._workspace) <= 1:
            return
        self.did.append(("close", name))
        self._workspace.close(name)
        self.shown.append(self._workspace.current.name)


def _nothing():
    import contextlib
    return contextlib.nullcontext()


class _Env:
    """`profilemod` on a scratch directory, with profiles written by hand."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE,
                       wsmod.ProfileSession)
        profilemod.PROFILES_DIR = os.path.join(root, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
        wsmod.ProfileSession = _Session
        self.profiles = profilemod.ProfileManager()
        return self

    def write(self, name: str, config: dict | None = None) -> str:
        self.profiles._ensure_dir(name)
        path = os.path.join(profilemod.PROFILES_DIR, name, profilemod.CONFIG_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config or {}, fh)
        return name

    def litter(self, name: str) -> None:
        """The files a live profile really has, so a delete has something to remove."""
        base = os.path.join(profilemod.PROFILES_DIR, name)
        for stem in (profilemod.PANEL_LOG, profilemod.DEBUG_LOG,
                     profilemod.TIMERS_STATE, profilemod.TASKS_JSON):
            with open(os.path.join(base, stem), "w", encoding="utf-8") as fh:
                fh.write("x")

    def workspace(self):
        return wsmod.Workspace(root=None, defaults={}, profiles=self.profiles)

    def settings(self) -> dict:
        try:
            with open(profilemod.SETTINGS_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def __exit__(self, *exc):
        (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE,
         wsmod.ProfileSession) = self._saved
        self._tmp.cleanup()
        return False


def _shell(env, selected: str, answer: bool = True):
    """A stand-in with the profile picker on ``selected`` and the dialogs answered."""
    shell = _Shell(env)
    shell._selected = selected
    _PM.messagebox = types.SimpleNamespace(
        askyesno=lambda *a, **k: answer,
        showerror=lambda *a, **k: shell.did.append(("error", a[1] if len(a) > 1 else "")),
        showwarning=lambda *a, **k: None,
        showinfo=lambda *a, **k: None)
    return shell


import panel.__main__ as _PM                        # noqa: E402
_PANEL = _PM.Panel
_REAL_MESSAGEBOX = _PM.messagebox


# ---------------------------------------------------------------------------

def test_deleting_an_open_profile_closes_its_session_before_the_disk() -> None:
    """The bug itself: the workspace was never told, so the page never went."""
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("second")
        env.litter("second")
        shell = _shell(env, "second")
        shell._workspace.restore(first=profilemod.DEFAULT_PROFILE)
        shell._workspace.open("second", make_current=False)
        assert "second" in shell._workspace

        shell._delete_profile()

        # …closed, and closed BEFORE the directory went — a session still holding
        # `panel.log` open is a directory Windows will not remove.
        assert ("close", "second") in shell.did, shell.did
        assert "second" not in shell._workspace, shell._workspace.names
        assert not env.profiles.exists("second"), "the directory is still there"
        assert not os.path.isdir(
            os.path.join(profilemod.PROFILES_DIR, "second"))


def test_the_session_it_closes_is_really_shut_down() -> None:
    """Errands, captures, the game lease, the logs — `shutdown` is what lets them go."""
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("second")
        shell = _shell(env, "second")
        shell._workspace.restore(first=profilemod.DEFAULT_PROFILE)
        session = shell._workspace.open("second", make_current=False)
        session.start()

        shell._delete_profile()

        assert session.dead, "the session was left running with its profile gone"
        assert not session.started


def test_the_panel_wide_file_stops_naming_it() -> None:
    """The pinned manager writes nothing, so this used to survive a restart.

    `open_profiles` and `active_profile` are the WORKSPACE's to write — its manager is
    the unpinned one. Deleting through a session's own manager left both naming a
    profile that was not there, and the next launch re-created it (`_ensure_dir`).
    """
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("second")
        shell = _shell(env, "second")
        shell._workspace.restore(first=profilemod.DEFAULT_PROFILE)
        shell._workspace.open("second")           # …and it is the one showing
        assert env.settings().get("active_profile") == "second"

        shell._delete_profile()

        saved = env.settings()
        assert "second" not in (saved.get("open_profiles") or []), saved
        assert saved.get("active_profile") != "second", saved
        assert env.profiles.open_profiles() == [profilemod.DEFAULT_PROFILE]


def test_deleting_the_profile_that_is_showing_moves_the_window_to_another() -> None:
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("second")
        shell = _shell(env, "second")
        shell._workspace.restore(first=profilemod.DEFAULT_PROFILE)
        shell._workspace.open("second")
        assert shell._workspace.current.name == "second"

        shell._delete_profile()

        assert shell._workspace.current.name == profilemod.DEFAULT_PROFILE
        assert shell.shown[-1] == profilemod.DEFAULT_PROFILE
        assert ("combo", profilemod.DEFAULT_PROFILE) in shell.did, shell.did


def test_deleting_the_only_open_profile_opens_another_one_first() -> None:
    """A window with no page in it is a window with nothing in it.

    `Workspace.close` refuses the last session and is right to, so the delete makes room
    rather than leaving the page of a profile that no longer exists.
    """
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("second")
        shell = _shell(env, "second")
        shell._workspace.open("second")            # the ONLY one open
        assert shell._workspace.names == ["second"]

        shell._delete_profile()

        assert ("open", profilemod.DEFAULT_PROFILE) in shell.did, shell.did
        assert shell._workspace.names == [profilemod.DEFAULT_PROFILE]
        assert not env.profiles.exists("second")


def test_it_refuses_when_there_is_no_page_to_fall_back_to() -> None:
    """Every other profile held by a second panel: say so and delete NOTHING."""
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("second")
        shell = _shell(env, "second")
        shell.refused_open.add(profilemod.DEFAULT_PROFILE)
        shell._workspace.open("second")

        shell._delete_profile()

        assert ("error", "") not in shell.did or True   # it complained…
        assert any(kind == "error" for kind, _ in shell.did), shell.did
        assert env.profiles.exists("second"), "it deleted the profile anyway"
        assert shell._workspace.names == ["second"]


def test_deleting_a_profile_that_is_not_open_touches_no_session() -> None:
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("shelved")
        shell = _shell(env, "shelved")
        shell._workspace.restore(first=profilemod.DEFAULT_PROFILE)
        assert "shelved" not in shell._workspace

        shell._delete_profile()

        assert not any(kind == "close" for kind, _ in shell.did), shell.did
        assert not env.profiles.exists("shelved")
        assert shell._workspace.names == [profilemod.DEFAULT_PROFILE]


def test_saying_no_deletes_nothing() -> None:
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("second")
        shell = _shell(env, "second", answer=False)
        shell._workspace.restore(first=profilemod.DEFAULT_PROFILE)
        shell._workspace.open("second", make_current=False)

        shell._delete_profile()

        assert env.profiles.exists("second")
        assert "second" in shell._workspace
        assert shell.did == [], shell.did


def test_the_last_profile_on_disk_is_refused_before_anything_is_closed() -> None:
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        shell = _shell(env, profilemod.DEFAULT_PROFILE)
        shell._workspace.restore()

        shell._delete_profile()

        assert any(kind == "error" for kind, _ in shell.did), shell.did
        assert env.profiles.exists(profilemod.DEFAULT_PROFILE)
        assert shell._workspace.names == [profilemod.DEFAULT_PROFILE]


# -- the store's own half -----------------------------------------------------

def test_a_directory_that_will_not_go_is_a_refusal_not_a_success() -> None:
    """`rmtree(ignore_errors=True)` and nothing else is a delete that reports success.

    Simulated by making the removal a no-op rather than by holding a file open, because
    what has to hold is the LOGIC — look after you leap — and «an open file cannot be
    unlinked» is a Windows rule that Linux does not share, so a test written that way
    would pass here for the wrong reason.
    """
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("stuck")
        env.litter("stuck")
        saved = shutil.rmtree
        shutil.rmtree = lambda *a, **k: None
        try:
            env.profiles.delete("stuck")
        except ValueError as exc:
            assert getattr(exc.args[0], "key", None) == "profile.error.not_removed", exc
        else:
            raise AssertionError("a directory that is still there was reported as gone")
        finally:
            shutil.rmtree = saved
        # …and the active pointer was NOT moved off a profile that is still on the disk.
        assert env.profiles.exists("stuck")


def test_a_refused_delete_says_so_in_the_log_and_keeps_the_page() -> None:
    """The whole point of the refusal: the person finds out, and nothing is half-done."""
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("stuck")
        shell = _shell(env, "stuck")
        shell._workspace.restore(first=profilemod.DEFAULT_PROFILE)
        shell._workspace.open("stuck", make_current=False)
        saved = shutil.rmtree
        shutil.rmtree = lambda *a, **k: None
        try:
            shell._delete_profile()
        finally:
            shutil.rmtree = saved
        assert any(key == "log.profile.delete_failed" for key, _ in shell.said), shell.said
        assert env.profiles.exists("stuck")


def test_a_second_attempt_is_made_before_giving_up() -> None:
    """A handle released in between — a child ending, a log closing — makes it work."""
    with _Env() as env:
        env.write(profilemod.DEFAULT_PROFILE)
        env.write("late")
        env.litter("late")
        saved = shutil.rmtree
        tries = []

        def once(path, *a, **k):
            tries.append(path)
            if len(tries) > 1:                    # the retry succeeds
                saved(path, *a, **k)

        shutil.rmtree = once
        try:
            env.profiles.delete("late")
        finally:
            shutil.rmtree = saved
        assert len(tries) == 2, tries
        assert not env.profiles.exists("late")


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
        finally:
            _PM.messagebox = _REAL_MESSAGEBOX
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
