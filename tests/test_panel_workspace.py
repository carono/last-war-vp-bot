r"""The set of profiles one window holds open (#1206, wave 2).

`panel/runtime/workspace.py` is the thing that replaces "the profile" everywhere the
shell used to mean "the process's one". What has to hold:

  * opening a profile beside another one gives it its OWN session, its own pinned
    profile manager and its own debug-log scope — except the first, which keeps none,
    so a window with one profile open logs exactly where every panel always has;
  * switching pages changes what is on screen and NOTHING else: a session whose page is
    not showing keeps its runtime, its schedule and its claim;
  * the last open profile cannot be closed, because a window with none in it is a
    window with nothing in it;
  * what was open is written down and comes back, and a profile deleted in between is
    dropped rather than re-created;
  * `each()` reaches every session and a session that throws does not take the rest
    with it;
  * and the shell's own per-profile attributes follow the page that is showing, while
    the window's own do not (`SessionScoped`, docs/research/multi-profile-panel.md §3).

The `Workspace` never touches a widget, which is what lets this run with no display:

    python3 tests/test_panel_workspace.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import profile as profilemod            # noqa: E402
from panel.runtime import session as wsmod_session  # noqa: E402
from panel.runtime import workspace as wsmod       # noqa: E402


class _Session:
    """A session double: everything the workspace asks of one, and a diary."""

    def __init__(self, name, *, root=None, defaults=None, scope=None,
                 daemon_state=None) -> None:
        self.name = name
        self.scope = scope
        self.state: dict = {}
        self.page = None
        self.started = False
        self.dead = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def shutdown(self) -> None:
        self.dead = True
        self.started = False


class _Env:
    """`profilemod` on a scratch directory, and the workspace built on it."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE,
                       wsmod.ProfileSession)
        profilemod.PROFILES_DIR = os.path.join(root, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
        wsmod.ProfileSession = _Session
        return self

    def workspace(self):
        return wsmod.Workspace(root=None, defaults={})

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


# ---------------------------------------------------------------------------

def test_the_first_session_has_no_scope_and_the_next_ones_do() -> None:
    """A window with one profile open must log exactly where it always did."""
    with _Env() as env:
        ws = env.workspace()
        first = ws.open("main")
        second = ws.open("alt")
        third = ws.open("third")
        assert first.scope is None
        assert second.scope == "alt" and third.scope == "third"
        assert len({s.scope for s in (second, third)}) == 2


def test_opening_the_same_profile_twice_is_one_session() -> None:
    with _Env() as env:
        ws = env.workspace()
        a = ws.open("main")
        b = ws.open("main")
        assert a is b and len(ws) == 1


def test_a_switch_moves_the_page_and_stops_nothing() -> None:
    with _Env() as env:
        ws = env.workspace()
        main, alt = ws.open("main"), ws.open("alt")
        ws.start_all()
        assert main.started and alt.started
        ws.switch_to("main")
        assert ws.current is main
        assert alt.started, "a page out of sight keeps farming — that is the point"
        assert not main.dead and not alt.dead


def test_the_last_profile_cannot_be_closed() -> None:
    with _Env() as env:
        ws = env.workspace()
        only = ws.open("main")
        assert ws.close("main") is None
        assert len(ws) == 1 and not only.dead


def test_closing_shuts_that_session_down_and_moves_the_page() -> None:
    with _Env() as env:
        ws = env.workspace()
        main, alt = ws.open("main"), ws.open("alt")
        ws.switch_to("alt")
        closed = ws.close("alt")
        assert closed is alt and alt.dead
        assert ws.current is main and ws.names == ["main"]
        assert not main.dead


def test_closing_something_that_is_not_open_is_nothing() -> None:
    with _Env() as env:
        ws = env.workspace()
        ws.open("main")
        ws.open("alt")
        assert ws.close("nobody") is None
        assert len(ws) == 2


def test_what_is_open_is_written_down_with_the_showing_one_first() -> None:
    with _Env() as env:
        ws = env.workspace()
        ws.open("main")
        ws.open("alt")
        ws.switch_to("alt")
        saved = env.settings()
        assert saved["open_profiles"][0] == "alt"
        assert set(saved["open_profiles"]) == {"main", "alt"}
        assert saved["active_profile"] == "alt", "the pointer follows the page on screen"


def test_restore_opens_what_was_open_last_time() -> None:
    with _Env() as env:
        first = env.workspace()
        first.open("main")
        first.open("alt")
        first.switch_to("main")

        again = env.workspace()
        again.restore()
        assert set(again.names) == {"main", "alt"}
        assert again.current.name == "main"


def test_restore_drops_a_profile_that_was_deleted_in_between() -> None:
    with _Env() as env:
        first = env.workspace()
        first.open("main")
        first.open("gone")
        first.switch_to("main")
        import shutil
        shutil.rmtree(os.path.join(profilemod.PROFILES_DIR, "gone"))

        again = env.workspace()
        again.restore()
        assert again.names == ["main"], again.names


def test_a_panel_with_no_record_opens_the_one_profile_it_always_did() -> None:
    """Every panel before this existed. It must come up unchanged."""
    with _Env() as env:
        panel = profilemod.ProfileManager()
        panel.create("main")
        panel.set_active("main")
        ws = env.workspace()
        ws.restore()
        assert ws.names == ["main"] and ws.current.name == "main"
        assert ws.current.scope is None


def test_restore_honours_an_explicit_first_profile() -> None:
    with _Env() as env:
        first = env.workspace()
        first.open("main")
        first.open("alt")

        again = env.workspace()
        again.restore(first="alt")
        assert again.current.name == "alt"
        assert set(again.names) == {"main", "alt"}


def test_each_reaches_every_session_and_survives_one_throwing() -> None:
    with _Env() as env:
        ws = env.workspace()
        good, bad, also = ws.open("main"), ws.open("bad"), ws.open("third")

        def work(session):
            if session is bad:
                raise RuntimeError("this one is broken")
            session.state["touched"] = True
            return session.name

        out = ws.each(work)
        assert good.state.get("touched") and also.state.get("touched")
        assert any(isinstance(item, RuntimeError) for item in out)
        assert len(out) == 3


def test_shutdown_takes_every_session_with_it() -> None:
    with _Env() as env:
        ws = env.workspace()
        sessions = [ws.open("main"), ws.open("alt")]
        ws.shutdown()
        assert all(s.dead for s in sessions)
        assert len(ws) == 0 and ws.current is None
        assert set(env.settings()["open_profiles"]) == {"main", "alt"}, \
            "what was open is remembered THROUGH the shutdown, not forgotten by it"


def test_each_session_has_its_own_pinned_profile_manager() -> None:
    """The real session class this time — the pinning is the whole isolation."""
    with _Env() as env:
        wsmod.ProfileSession = env._saved[2]      # the genuine one
        panel = profilemod.ProfileManager()
        panel.create("main")
        panel.create("alt")
        panel.set_active("main")

        ws = env.workspace()
        main = ws.open("main")
        alt = ws.open("alt")
        assert main.rt.profiles.pinned and alt.rt.profiles.pinned
        assert main.rt.profiles.active == "main"
        assert alt.rt.profiles.active == "alt"
        assert main.rt.profiles.debug_log() != alt.rt.profiles.debug_log()
        assert main.rt.scope is None and alt.rt.scope == "alt"
        ws.shutdown()


# ---------------------------------------------------------------------------
# the shell's per-profile attributes follow the page that is showing
# ---------------------------------------------------------------------------

class _Shell(wsmod_session.SessionScoped):
    """A stand-in for the window: two per-profile names, one of its own."""

    SESSION_ATTRS = frozenset({"_log", "_dash_values", "_ghost"})

    def __init__(self) -> None:
        self._title = "the window"            # never routed
        self._current_session = None

    @property
    def _ghost(self):                          # declared AND a descriptor
        return "a property always wins"


def test_a_routed_attribute_belongs_to_the_showing_session() -> None:
    shell, first, second = _Shell(), _Session("main"), _Session("alt")

    shell._current_session = first
    shell._log = "the main window's log"
    shell._dash_values = {"tickets": 3}

    shell._current_session = second
    shell._log = "the alt window's log"
    assert shell._log == "the alt window's log"
    assert first.state["_log"] == "the main window's log"

    shell._current_session = first
    assert shell._log == "the main window's log"
    assert shell._dash_values == {"tickets": 3}


def test_an_unrouted_attribute_is_the_windows_and_survives_every_switch() -> None:
    shell, first, second = _Shell(), _Session("main"), _Session("alt")
    shell._current_session = first
    shell._title = "one window"
    shell._current_session = second
    assert shell._title == "one window"
    assert "_title" not in first.state and "_title" not in second.state


def test_a_declared_name_that_is_a_property_is_never_routed() -> None:
    """Declaring one by mistake must be inert, not a silently broken descriptor."""
    shell = _Shell()
    shell._current_session = _Session("main")
    assert shell._ghost == "a property always wins"
    assert "_ghost" not in shell._current_session.state


def test_nothing_is_routed_before_there_is_a_session() -> None:
    """The window's own construction runs before any profile is open."""
    shell = _Shell()
    shell._log = "set during boot"
    assert shell.__dict__["_log"] == "set during boot"
    assert shell._log == "set during boot"


def test_reading_a_routed_name_the_session_has_never_set_raises() -> None:
    shell = _Shell()
    shell._current_session = _Session("main")
    try:
        shell._log
    except AttributeError as exc:
        assert "_log" in str(exc)
    else:
        raise AssertionError("a name nothing has set must raise, not answer None")


def test_a_bound_call_answers_for_the_session_it_was_MADE_in() -> None:
    """Not for the one whose page happens to be showing when it fires."""
    shell, first, second = _Shell(), _Session("main"), _Session("alt")
    shell._current_session = first
    shell._log = "the main window's log"
    shell._current_session = second
    shell._log = "the alt window's log"

    with shell.session_scope(first):
        read_first = shell.bind_session(lambda: shell._log)
    read_showing = shell.bind_session(lambda: shell._log)      # made with alt on screen

    shell._current_session = second
    assert read_first() == "the main window's log", "bound to main, so main it stays"
    assert read_showing() == "the alt window's log"
    shell._current_session = first
    assert read_first() == "the main window's log"
    assert read_showing() == "the alt window's log", "…and neither follows the page"


def test_two_threads_bound_to_two_sessions_do_not_overwrite_each_other() -> None:
    """The boot runs a thread per open profile; one shared attribute was a race."""
    import threading

    shell, first, second = _Shell(), _Session("main"), _Session("alt")
    shell._current_session = first
    shell._log = "main's"
    shell._current_session = second
    shell._log = "alt's"
    shell._current_session = None

    seen: dict = {}
    gate = threading.Barrier(2, timeout=5)

    def work(session, key):
        def body():
            gate.wait()               # both inside their scope at the same moment
            seen[key] = shell._log
        return shell.bind_session(body, session)

    threads = [threading.Thread(target=work(first, "main")),
               threading.Thread(target=work(second, "alt"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert seen == {"main": "main's", "alt": "alt's"}, seen


def test_nothing_on_SessionScoped_shadows_a_tkinter_widget_method() -> None:
    """The shell mixes this into `tk.Tk`, so a clash is the window dying at boot.

    It happened: the binder was called `bind`, and `Misc.bind` is how every widget in
    the panel attaches an event handler. The window came up and fell over on the next
    line, and nothing under `tests/` could see it — the stand-in above is not a widget.
    """
    try:
        import tkinter as tk
    except ImportError:                     # no Tk here; the shell will find out
        return
    ours = {n for n in vars(wsmod_session.SessionScoped) if not n.startswith("__")}
    clashes = sorted(n for n in ours if hasattr(tk.Misc, n))
    assert not clashes, f"these shadow tkinter.Misc: {clashes}"


def test_binding_without_a_session_hands_the_function_back_untouched() -> None:
    shell = _Shell()
    def f():
        return 1
    assert shell.bind_session(f) is f


def test_a_routed_name_can_be_deleted_from_its_own_session_only() -> None:
    shell, first, second = _Shell(), _Session("main"), _Session("alt")
    shell._current_session = first
    shell._log = "mine"
    shell._current_session = second
    shell._log = "theirs"
    del shell._log
    assert "_log" not in second.state
    shell._current_session = first
    assert shell._log == "mine"


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
