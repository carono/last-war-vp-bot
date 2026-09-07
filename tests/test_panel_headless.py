r"""The panel with NO WINDOW, built and answering (#1976, P3).

`panel/headless.py` is what the plan's own rule for the migration needs: the old way of
driving the panel is deleted only after the NEW one has been used to drive it
(`docs/research/panel-service-and-spa-plan.md` §3). So there is a panel with no Tk in it
before a single `build()` is deleted, and every tab that still draws goes on drawing in
the window meanwhile.

What is pinned here is what «the panel, minus the drawing» has to mean:

  * the profiles open, their schedules start, and their tabs are BUILT — state, errands
    and screens — with `build()` never called, because there is no frame to draw into;
  * a tab's saved block is still applied: a tab's settings ARE its state, and a headless
    panel keeps every one of them;
  * a screen is data off that state, so the phone sees what it always saw;
  * and nothing here needs a display, which is the whole point.

    C:\Python312\python.exe tests\test_panel_headless.py
    python3 tests/test_panel_headless.py
"""
from __future__ import annotations

TIER = "offline"   # no window and no display — if this needs Tk, P3 is not done

import json
import os
import sys
import threading
import tempfile
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing.

    Only so the test can RUN where the package is missing: what it proves is that the
    headless panel never asks it to draw. `test_panel_headless_state` is the one that
    pins the two files which import no Tk at all.
    """
    if "tkinter" in sys.modules:
        return

    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module(f"tkinter.{sub}")
        sys.modules[f"tkinter.{sub}"] = child
        setattr(tk, sub, child)


_stub_tk()

from panel import profile as profilemod              # noqa: E402
from panel.headless import HeadlessPanel             # noqa: E402
from panel.web.api import WebApi                     # noqa: E402


class _Scratch:
    """A profiles tree of its own, so nothing here touches this machine's panel."""

    def __init__(self, tabs=("checklist",)) -> None:
        # `ignore_cleanup_errors`: an opened profile leaves a `panel.db`, and on Windows
        # a SQLite file cannot be unlinked while a connection to it is open.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE)
        profilemod.PROFILES_DIR = os.path.join(self._tmp.name, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(self._tmp.name, "settings.json")
        os.makedirs(os.path.join(profilemod.PROFILES_DIR, "solo"), exist_ok=True)
        with open(os.path.join(profilemod.PROFILES_DIR, "solo", "config.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"tabs": {"enabled": list(tabs), "known": list(tabs)},
                       "watchdog": False, "power": False}, fh)

    def close(self) -> None:
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._saved
        self._tmp.cleanup()


def _panel(tabs=("checklist",)):
    scratch = _Scratch(tabs)
    panel = HeadlessPanel(["solo"], web=False)
    return scratch, panel


# ---------------------------------------------------------------------------
def test_a_panel_with_no_window_opens_its_profile_and_builds_its_tabs() -> None:
    scratch, panel = _panel()
    try:
        opened = panel.open()
        assert [s.name for s in opened] == ["solo"], opened
        rt = panel.workspace.current.rt
        assert rt.root is None, "a headless runtime grew a window"
        tab = rt.tabs.peek("checklist")
        assert tab is not None, "the tab was never built"
        assert tab.parent is None, "a headless tab was given something to draw into"
    finally:
        panel.shutdown()
        scratch.close()


def test_a_second_panel_will_not_open_a_profile_the_first_one_holds() -> None:
    """ONE panel per profile, answered by the kernel (#1994).

    The window has taken the instance lock since it had one; this took nothing — no lock,
    no beat, and a command line no guard recognised as a panel. Live on 2026-08-27 there
    were EIGHT `panel.headless` processes on one account, sharing one `panel.log`, one
    `config.json` and one client — and a restart reached whichever of the eight happened
    to answer, which is how a committed fix went undelivered for hours while every reading
    said the panel had been restarted.
    """
    from panel import headless as headlessmod

    scratch, first = _panel()
    try:
        assert [s.name for s in first.open()] == ["solo"]
        second = HeadlessPanel(["solo"], web=False)
        assert second.open() == [], "a second panel opened a profile the first one holds"
        assert second._held == ["solo"], second._held
        assert second.run() == headlessmod.HELD_EXIT, "«already running» read as a failure"

        # …and the lock follows the process: once the first lets go, one may open again.
        first.shutdown()
        third = HeadlessPanel(["solo"], web=False)
        try:
            assert [s.name for s in third.open()] == ["solo"], "the lock outlived its panel"
        finally:
            third.shutdown()
    finally:
        first.shutdown()
        scratch.close()


def test_a_windowless_panel_beats_so_the_hourly_check_can_see_it() -> None:
    """The lock says a panel is there; the beat says it is still answering (#1994)."""
    import json as _json

    from panel.runtime import autostart as autostartmod

    scratch, panel = _panel()
    try:
        panel.open()
        session = panel.workspace.current.rt
        panel._beat(panel.workspace.current)
        beat = _json.loads(Path(session.profiles.heartbeat("solo")).read_text("utf-8"))
        assert beat["pid"] == os.getpid(), beat
        assert beat.get("ts"), f"no beat, only a farewell: {beat}"

        panel.shutdown(why=autostartmod.RESTARTING)
        left = _json.loads(Path(session.profiles.heartbeat("solo")).read_text("utf-8"))
        assert left.get("left") == autostartmod.RESTARTING, left
        assert not left.get("ts"), "a farewell that still reads as a beat"
    finally:
        scratch.close()


def test_realizing_a_tab_applies_its_settings_and_draws_nothing() -> None:
    """A tab's saved block is its STATE, and state is what survives the window."""
    scratch, panel = _panel()
    try:
        panel.open()
        rt = panel.workspace.current.rt
        tab = rt.tabs.peek("checklist")
        drawn: list = []
        tab.build = lambda: drawn.append(1)      # …and it must never be called
        applied: list = []
        tab.apply_config = lambda raw: applied.append(raw)
        tab._saved_config = {"anything": 1}
        assert rt.tabs.realize(tab) is True
        assert drawn == [], "the headless panel tried to draw a tab"
        assert applied == [{"anything": 1}], applied
        assert tab.built is True
        assert rt.tabs.realize(tab) is False, "realize is not idempotent"
    finally:
        panel.shutdown()
        scratch.close()


def test_the_windowless_panel_answers_the_whole_api() -> None:
    """The phone sees what it always saw — the screens are data off the tabs' state."""
    scratch, panel = _panel()
    try:
        panel.open()
        rt = panel.workspace.current.rt
        api = WebApi(rt)
        status, payload = api.dispatch("GET", "/api/profiles", {}, {})
        assert status == 200 and "solo" in payload["profiles"], payload
        status, payload = api.dispatch("GET", "/api/state", {}, {})
        assert status == 200 and payload["profile"] == "solo", payload
        status, payload = api.dispatch("GET", "/api/screens", {}, {})
        assert status == 200, payload
        ids = [s["id"] for s in payload["screens"]]
        assert "checklist" in ids, ids
        status, screen = api.dispatch("GET", "/api/screen", {"id": "checklist"}, {})
        assert status == 200 and screen.get("cards") is not None, screen
    finally:
        panel.shutdown()
        scratch.close()


def test_the_state_says_WHICH_CODE_answered_and_not_only_which_is_checked_out() -> None:
    """`version` is not proof of a restart; `boot` is (#1994).

    The version string is computed off git each time it is asked, so it changes the moment
    somebody commits — from the same process, running the same old code. #1993 was reported
    delivered on exactly that reading. `boot` is a fact about the process that answered:
    its pid, when its code was imported, and the commit it was imported from.
    """
    scratch, panel = _panel()
    try:
        panel.open()
        api = WebApi(panel.workspace.current.rt)
        _status, payload = api.dispatch("GET", "/api/state", {}, {})
        boot = payload["panel"]["boot"]
        assert boot["pid"] == os.getpid(), boot
        assert boot["at"] > 0 and "head" in boot, boot
        _status, again = api.dispatch("GET", "/api/state", {}, {})
        assert again["panel"]["boot"] == boot, "the stamp moved under a running process"
    finally:
        panel.shutdown()
        scratch.close()


def test_its_clock_is_the_windowless_one_and_it_actually_ticks() -> None:
    """`Ticker` with no widget arms nothing — a schedule that never fires (#1976)."""
    import threading

    from panel.runtime.tick import ThreadTicker

    scratch, panel = _panel()
    try:
        panel.open()
        rt = panel.workspace.current.rt
        assert isinstance(rt.tick, ThreadTicker), type(rt.tick)
        fired = threading.Event()
        rt.tick.arm("test", 10, fired.set)
        assert fired.wait(3.0), "the headless clock never fired"
    finally:
        panel.shutdown()
        scratch.close()


def test_a_tab_that_will_not_build_is_skipped_and_said() -> None:
    """One broken tab is a line in the log, exactly as it is in a window."""
    scratch, panel = _panel(tabs=("checklist", "no_such_tab_at_all"))
    try:
        opened = panel.open()
        assert opened, "one unknown tab stopped the whole profile"
        assert panel.workspace.current.rt.tabs.peek("checklist") is not None
    finally:
        panel.shutdown()
        scratch.close()


def test_the_runtime_and_the_headless_panel_import_with_no_tkinter_at_all() -> None:
    """P3's acceptance test, as far as it reaches today (#1976).

    `panel.runtime` used to need Tk to be imported at all, because the package imported
    the log PANE — so a panel with no display, or a machine with no `tkinter` installed,
    could not so much as read its own settings. The spool is `panel/runtime/log_spool.py`
    now and the pane is imported by whoever draws one.

    WHAT IS STILL TRUE: a tab CLASS imports Tk when it is loaded, because it still draws.
    That is what the rest of P3 removes, one tab at a time; this test is what will notice
    when the last one goes.
    """
    import subprocess

    code = (
        "import sys\n"
        "sys.path[:0] = ['.', 'tools', 'tools/lib']\n"
        "sys.modules['tkinter'] = None\n"      # any import of it now raises
        "import panel.runtime, panel.headless\n"
        "print('ok')\n")
    done = subprocess.run([sys.executable, "-c", code], cwd=str(_REPO),
                          capture_output=True, text=True)
    assert done.returncode == 0 and "ok" in done.stdout, (done.stdout, done.stderr[-800:])


def test_the_two_presses_on_the_panel_ITSELF_exist_without_a_window() -> None:
    """«⟳ Перезапустить панель» and «Заглушить» were the SHELL's, and a panel with no
    window answered «unavailable» to both (#1976, measured live through the service).

    That is not a missing convenience: `CLAUDE.md` makes the restart MANDATORY after every
    fix, because a running panel plays the code it was imported with — and with no window
    there is nobody at the machine to end the process by hand either. So the windowless
    panel registers both, and a restart comes back as `panel.headless` rather than as a
    window this session may have no desktop for.
    """
    from panel.runtime import panel_control as panelctl

    source = (_REPO / "panel" / "headless.py").read_text(encoding="utf-8")
    for action in ("panelctl.RESTART", "panelctl.QUIT"):
        assert f"set_handler(self._restart_now, {action})" in source \
            or f"set_handler(self._quit_now, {action})" in source, \
            f"a windowless panel cannot be asked to {action}"
    assert 'relaunch(module="panel.headless")' in source, (
        "a windowless restart would come back with a window")
    assert panelctl.RESTART in panelctl.BY_ID and panelctl.QUIT in panelctl.BY_ID


def test_a_press_with_no_window_waits_for_its_own_answer_to_be_written() -> None:
    """The delay is not decoration: the press arrives on the socket the phone is holding,
    and pulling the interpreter out before the answer is flushed leaves it unable to tell
    «перезапускается» from «упало». With a window that wait is Tk's `after`; with none it
    is the panel's own clock — and a Tk `Ticker` without a widget arms NOTHING, which is
    why the two are told apart by name rather than trusted."""
    from panel.runtime import panel_control as panelctl
    from panel.runtime import tick as tickmod

    assert tickmod.ThreadTicker.THREADED is True
    assert tickmod.Ticker.THREADED is False

    clock = tickmod.ThreadTicker()
    clock.start()
    ran = threading.Event()

    class _Rt:
        root = None
        tick = clock

        def say(self, *a, **k):
            pass

    try:
        panelctl.set_handler(ran.set, panelctl.QUIT)
        said = panelctl.request(_Rt(), panelctl.QUIT)
        assert said.get("ok") is True, said
        assert not ran.is_set(), "the panel went down before its answer was written"
        assert ran.wait(5), "the press was armed on a clock that never fired"
    finally:
        panelctl.set_handler(None, panelctl.QUIT)
        clock.stop()


def test_a_panel_with_no_window_still_takes_the_readings() -> None:
    """THE GAP THAT COST A LIVE AFTERNOON (#1984).

    The status poll was the Tk shell's, so this panel took no readings at all: on
    2026-08-26 it played for hours while every front-end drew the boot's `unread()`
    verdict — «клиент игры не запущен» over a client that was on the world map — and the
    recovery behind it (the crash restart, the kick's wait, the maintenance knock) was
    never fed once, because all of it hangs off that poll.

    Pinned at the source, because starting a real one needs a real client: the readings
    live in `panel/runtime/status.py`, the runtime holds one, and the windowless panel
    starts it and stops it with everything else it owns.
    """
    host = (_REPO / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "StatusPoll(self)" in host, "the runtime does not hold the readings"
    source = (_REPO / "panel" / "headless.py").read_text(encoding="utf-8")
    assert "status.start()" in source, "a panel with no window takes no readings"
    assert "status.stop()" in source, "…and never lets them go"
    shell = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "self._rt.status.read_and_act()" in shell, \
        "the window took its own readings again — one rule, one place"


def _second_profile(name: str = "second", **client) -> None:
    """One more profile on disk, closed, for the presses below to reach for.

    WITH A CLIENT OF ITS OWN unless the caller says otherwise: a session and a port,
    which is what makes it a separate account rather than a second view of `solo`'s
    game. `client` overrides that, so a test can make the half-configured profile the
    gate is supposed to refuse.
    """
    values = {"tabs": {"enabled": [], "known": []}, "watchdog": False, "power": False,
              "daemon_port": 47655, "rdp_session": True, "rdp_user": name}
    values.update(client)
    os.makedirs(os.path.join(profilemod.PROFILES_DIR, name), exist_ok=True)
    with open(os.path.join(profilemod.PROFILES_DIR, name, "config.json"),
              "w", encoding="utf-8") as fh:
        json.dump(values, fh)


def test_a_windowless_panel_can_open_and_close_a_profile_from_the_phone() -> None:
    """WHICH ACCOUNTS ARE FARMED was a knob only the window could turn (#2024).

    The four profile presses are the SHELL's (`panel/runtime/profile_control.py`) and the
    window has registered them since #1976; a panel with no window registered nothing, so
    `POST /api/screen/press {id: "profiles", action: "open"}` answered
    `{"ok": false, "reason": "web.ui.refused"}` — on the front-end that actually runs the
    panel on this machine. The same class as #1984 (no `Schedule.register`, so every gear
    was empty) and #2010 (a switch on a tab the profile had off): an ability wired to the
    shell, and the shell that ships has no wire.
    """
    from panel.runtime import profile_control as profilectl

    scratch, panel = _panel()
    _second_profile()
    try:
        panel.open()
        profilectl.set_handler(panel._profile_press)                     # noqa: SLF001
        api = WebApi(panel.workspace.current.rt)

        status, out = api.dispatch("POST", "/api/screen/press", {},
                                   {"id": "profiles", "action": profilectl.OPEN,
                                    "args": {"name": "second"}})
        assert status == 200 and out.get("ok"), out
        assert "second" in panel.workspace.names, panel.workspace.names
        # …and it is a WHOLE profile, not a name in a list: its own lock, so no second
        # panel can take the account, and its tabs built off its own saved block.
        assert "second" in panel._locks, panel._locks                    # noqa: SLF001
        assert panel.workspace.get("second").rt.workspace is panel.workspace

        status, out = api.dispatch("POST", "/api/screen/press", {},
                                   {"id": "profiles", "action": profilectl.CLOSE,
                                    "args": {"name": "second"}})
        assert status == 200 and out.get("ok"), out
        assert "second" not in panel.workspace.names, panel.workspace.names
        assert "second" not in panel._locks, panel._locks                # noqa: SLF001

        # The last one open is refused, exactly as the workspace refuses it: a panel with
        # nothing open is a panel with nothing to do.
        status, out = api.dispatch("POST", "/api/screen/press", {},
                                   {"id": "profiles", "action": profilectl.CLOSE,
                                    "args": {"name": "solo"}})
        assert status == 200 and not out.get("ok"), out
        assert panel.workspace.names == ["solo"], panel.workspace.names
    finally:
        profilectl.set_handler(None)
        panel.shutdown()
        scratch.close()


def test_a_profile_another_panel_holds_is_refused_by_the_press_too() -> None:
    """The instance lock is the kernel's answer to «is somebody on this account» (#1994),
    and a press from a phone is no more entitled to overrule it than a boot is: the two
    panels would write one `config.json` and drive one client."""
    from panel.runtime import profile_control as profilectl

    scratch, panel = _panel()
    _second_profile()
    try:
        panel.open()
        other = HeadlessPanel(["second"], web=False)
        try:
            assert [s.name for s in other.open()] == ["second"]
            profilectl.set_handler(panel._profile_press)                 # noqa: SLF001
            assert profilectl.carry_out(profilectl.OPEN, "second") is False, \
                "a press took a profile a second panel is holding"
            assert "second" not in panel.workspace.names, panel.workspace.names
        finally:
            other.shutdown()
    finally:
        profilectl.set_handler(None)
        panel.shutdown()
        scratch.close()


def test_renaming_and_deleting_reach_the_disk_with_no_window() -> None:
    """Both close the profile first, because a directory holding an open `panel.log`
    cannot be renamed or removed on Windows — which is how #1253's delete reported
    success without having happened."""
    from panel.runtime import profile_control as profilectl

    scratch, panel = _panel()
    _second_profile()
    try:
        panel.open()
        profilectl.set_handler(panel._profile_press)                     # noqa: SLF001
        profiles = panel.workspace.profiles

        assert profilectl.carry_out(profilectl.RENAME, "second", "third") is True
        assert profiles.exists("third") and not profiles.exists("second"), profiles.list()

        # …and an open one is closed, moved and opened again under its new name.
        assert profilectl.carry_out(profilectl.OPEN, "third") is True
        assert profilectl.carry_out(profilectl.RENAME, "third", "fourth") is True
        assert "fourth" in panel.workspace.names, panel.workspace.names
        assert profiles.exists("fourth") and not profiles.exists("third"), profiles.list()

        assert profilectl.carry_out(profilectl.DELETE, "fourth") is True
        assert not profiles.exists("fourth"), profiles.list()
        assert panel.workspace.names == ["solo"], panel.workspace.names
        # The last profile there is cannot go: the press is offered nowhere, and refused
        # here as well.
        assert profilectl.carry_out(profilectl.DELETE, "solo") is False
        assert profiles.exists("solo")
    finally:
        profilectl.set_handler(None)
        panel.shutdown()
        scratch.close()


def test_a_profile_with_no_client_of_its_own_is_refused_and_told_why() -> None:
    """«Профиль без порта = чужой клиент», and a press must not walk into it (#2024).

    A profile with no `daemon_port` and no Windows session falls back to the console and
    the console's port, so opening it beside the profile that really owns this desktop is
    two panels farming ONE game (#1250, #1252). The lease makes them take turns rather
    than collide, so nothing looks broken — the symptom is one account's log filling with
    «игра занята — <the other one>» while its quota is spent on somebody else's tiles.

    The window could WARN, because a person is in front of it. A press from a phone has
    nobody to read a warning before the schedule starts, so with no window it is a
    refusal that names the reason and leaves the profile closed.
    """
    from panel.runtime import profile_control as profilectl

    scratch, panel = _panel()
    # No port, no session: the console, which `solo` is already on.
    _second_profile("stowaway", daemon_port=None, rdp_session=False, rdp_user="")
    # …and one whose session is switched on with nobody named: half a client, which
    # looks for the game among nobody's processes and reports «клиент не запущен» for
    # ever — a profile that was never finished, reading as a game that will not start.
    _second_profile("halfway", daemon_port=47656, rdp_session=True, rdp_user="")
    # …and one that IS a separate account, for the other half of the gate below. Made
    # here rather than where it is used: a profile is a row of the database now and the
    # manager adopts the directories it finds when it is built, so one written after the
    # panel is up is not there to be opened (#2025).
    _second_profile("roomy")                     # its own session and port
    try:
        panel.open()
        profilectl.set_handler(panel._profile_press)                     # noqa: SLF001
        for name in ("stowaway", "halfway"):
            assert profilectl.carry_out(profilectl.OPEN, name) is False, \
                f"«{name}» was opened onto another profile's client"
            assert name not in panel.workspace.names, panel.workspace.names
            assert name not in panel._locks, panel._locks                # noqa: SLF001
        # …and the refusal is WORDS, not a silent False: both reasons are said in the log
        # of the profile that is there to be read. A line waits in the spool until
        # somebody drains it — `start()` arms that pump and this test never called it —
        # so the drain is done here, exactly as `_pump_log` does it.
        rt = panel.workspace.current.rt
        rt.log.open_file(rt.profiles.panel_log("solo"))
        rt.log_spool.pump()
        said = Path(panel.workspace.profiles.panel_log("solo")).read_text("utf-8")
        assert "stowaway" in said and "halfway" in said, said[-400:]

        # THE GATE IS ABOUT WHO IS OPEN, never about every profile on disk: a client
        # nobody currently holds is free to take. `solo` closes, and the console it was
        # sitting on is the stowaway's for the asking.
        assert profilectl.carry_out(profilectl.OPEN, "roomy") is True
        assert profilectl.carry_out(profilectl.CLOSE, "solo") is True
        assert profilectl.carry_out(profilectl.OPEN, "stowaway") is True, \
            "a client nobody holds was refused anyway"
    finally:
        profilectl.set_handler(None)
        panel.shutdown()
        scratch.close()


def test_two_profiles_with_their_own_clients_open_side_by_side() -> None:
    """The gate must not be a ban on more than one profile: the three test accounts each
    have their own Windows session and their own port, which is exactly the arrangement
    it exists to protect."""
    from panel.runtime import profile_control as profilectl

    scratch, panel = _panel()
    _second_profile("one", daemon_port=47655, rdp_user="one")
    _second_profile("two", daemon_port=47656, rdp_user="two")
    try:
        panel.open()
        profilectl.set_handler(panel._profile_press)                     # noqa: SLF001
        assert profilectl.carry_out(profilectl.OPEN, "one") is True
        assert profilectl.carry_out(profilectl.OPEN, "two") is True
        assert sorted(panel.workspace.names) == ["one", "solo", "two"], \
            panel.workspace.names
    finally:
        profilectl.set_handler(None)
        panel.shutdown()
        scratch.close()


def test_the_windowless_panel_registers_the_profile_presses_at_start() -> None:
    """A handler nobody registers is the whole bug — pinned in the source, because
    `start()` also brings the port and the service link up and this test wants neither."""
    source = (_REPO / "panel" / "headless.py").read_text(encoding="utf-8")
    assert "profilectl.set_handler(self._profile_press)" in source, \
        "a panel with no window cannot open a profile"
    assert "profilectl.set_handler(None)" in source, \
        "…and goes on claiming it can once it is down"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
