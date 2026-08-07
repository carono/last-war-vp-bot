r"""The autostart: the beat the panel writes, and what the hourly look makes of it.

Three things are worth pinning here, and all three are quiet when broken.

* **A stale beat whose process is still there is «hung», not «gone».** That is the whole
  reason the beat is written from the Tk queue rather than by a thread — a white,
  unresponsive window is exactly what a process-list check cannot tell from a working
  panel, and the wrong verdict means the account sits dead until somebody notices.
* **A recycled pid is not a panel.** Windows hands the number out again within minutes,
  so the executable name travels with it; without that check «pid 8124 exists» is a
  claim made by whatever got the number next.
* **The task names THIS install.** The interpreter and the working directory come from
  the panel doing the registering. A hard-coded path would work on the machine it was
  written on and open the wrong panel — or none — everywhere else.
* **ONE task for ONE panel, whatever it has open (#1207).** A panel holds a page per open
  profile since #1206, so a task per profile meant two windows on one game client. The
  task names no profile; the set is read when it fires, and a panel is «there» if ANY of
  those profiles is still beating.

Touches no scheduler: `register` is never called, only the XML it would hand over. The
profiles live in a temporary directory, so a real profile is neither read nor written.

Needs no display, but it does need tkinter: the module lives in `panel/runtime/`, and
importing that package brings the whole runtime — the settings binder included — with
it. So it says SKIP under the WSL python3, like the rest of the panel's tests.

    C:\Python312\python.exe tests\test_panel_autostart.py
    python3 tests/test_panel_autostart.py        # SKIP without tkinter
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import os
import sys
import tempfile
import time
import types
import xml.etree.ElementTree as ET
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:                                        # the WSL python3 has no tkinter
    from panel.runtime import autostart as autostartmod
except ModuleNotFoundError as exc:          # noqa: BLE001
    if exc.name != "tkinter":
        raise
    autostartmod = None
from panel import profile as profilemod            # noqa: E402

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class _profiles_in_tmp:
    """Point the profile store at a temporary directory for one test."""

    def __enter__(self) -> "profilemod.ProfileManager":
        self._tmp = tempfile.TemporaryDirectory()
        self._dir, self._settings = profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE
        profilemod.PROFILES_DIR = os.path.join(self._tmp.name, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(self._tmp.name, "settings.json")
        return profilemod.ProfileManager()

    def __exit__(self, *exc):
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._dir, self._settings
        self._tmp.cleanup()
        return False


def _age(profiles, seconds: float) -> None:
    """Backdate the heartbeat, as an unattended panel does simply by existing."""
    path = profiles.heartbeat()
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    saved["ts"] = time.time() - seconds
    Path(path).write_text(json.dumps(saved), encoding="utf-8")


def test_a_fresh_beat_from_this_process_reads_as_running():
    with _profiles_in_tmp() as profiles:
        autostartmod.beat(profiles)
        live = autostartmod.probe(profiles)
        assert live.state == "running", live
        assert live.pid == os.getpid()
        assert live.age is not None and live.age < 5


def test_no_beat_at_all_is_a_panel_that_is_not_running():
    with _profiles_in_tmp() as profiles:
        assert autostartmod.probe(profiles).state == "stopped"
        # …and so is one that closed on purpose: the file goes with the window.
        autostartmod.beat(profiles)
        autostartmod.clear(profiles)
        assert autostartmod.probe(profiles).state == "stopped"
        autostartmod.clear(profiles)          # twice is not an error


def test_a_stale_beat_whose_process_is_alive_is_hung_not_gone():
    """The case the whole file exists for — and the one a process check gets wrong.

    This very process is the stand-in for the wedged panel: its pid is real and its
    executable name matches, so the only thing saying anything is wrong is the age of
    the beat. `psutil` is what answers «is that pid alive»; without it the machine
    cannot tell, and then a stale beat is only ever «stopped» — never a kill.
    """
    with _profiles_in_tmp() as profiles:
        autostartmod.beat(profiles)
        _age(profiles, autostartmod.STALE_SEC + 60)
        live = autostartmod.probe(profiles)
        try:
            import psutil                     # noqa: F401
        except Exception:                     # noqa: BLE001 — not installed here
            assert live.state == "stopped", live
            return
        assert live.state == "hung", live
        assert live.pid == os.getpid()


def test_a_recycled_pid_is_not_a_panel():
    """A beat naming a live pid that is NOT a python is a number Windows handed on."""
    try:
        import psutil                         # noqa: F401
    except Exception:                         # noqa: BLE001
        return
    with _profiles_in_tmp() as profiles:
        autostartmod.beat(profiles)
        path = profiles.heartbeat()
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        saved["exe"] = "notepad.exe"          # same pid, somebody else's process
        Path(path).write_text(json.dumps(saved), encoding="utf-8")
        assert autostartmod.probe(profiles).state == "stopped"


def test_a_beat_from_the_future_is_not_stale():
    """A clock that moved must not restart a working panel."""
    with _profiles_in_tmp() as profiles:
        autostartmod.beat(profiles)
        _age(profiles, -3600)
        assert autostartmod.probe(profiles).age == 0
        assert autostartmod.probe(profiles).state in ("running", "stopped")


def test_the_beat_is_per_profile():
    with _profiles_in_tmp() as profiles:
        profiles.create("second")
        autostartmod.beat(profiles)                   # the active one only
        assert autostartmod.probe(profiles).state == "running"
        assert autostartmod.probe(profiles, "second").state == "stopped"


def test_the_check_reports_without_launching_anything():
    """`launch=False` is the dry run the tests (and `--status`) need: nothing is opened."""
    with _profiles_in_tmp() as profiles:
        record = autostartmod.check(profiles.active, launch=False)
        assert record["state"] == "stopped"
        assert record["seen"] == "stopped"
        saved = json.loads(Path(profiles.autostart_state()).read_text(encoding="utf-8"))
        assert saved["state"] == "stopped"
        autostartmod.beat(profiles)
        assert autostartmod.check(profiles.active, launch=False)["state"] == "running"


def test_the_instance_lock_is_exclusive_and_dies_with_its_holder():
    """«A panel is on this profile», answered by the kernel.

    This is the half a heartbeat cannot do: a file's CONTENTS can be stale, a lock cannot
    — the OS drops it when the process ends, however it ends. It is per profile, so two
    accounts open at once do not see each other.
    """
    with _profiles_in_tmp() as profiles:
        profiles.create("second")
        assert autostartmod.locked(profiles) is False
        held = autostartmod.take_lock(profiles)
        assert held is not None
        try:
            assert autostartmod.locked(profiles) is True
            assert autostartmod.take_lock(profiles) is None, "two holders at once"
            assert autostartmod.locked(profiles, "second") is False, "not per profile"
        finally:
            autostartmod.drop_lock(held)
        assert autostartmod.locked(profiles) is False
        # The pid is in it for a person reading the folder; the lock is what counts.
        assert Path(profiles.lock_file()).read_text(encoding="utf-8").strip() \
            == str(os.getpid())


def test_one_panel_per_profile_not_one_per_machine():
    """The rule, both halves — and the second half is a FEATURE, not a leftover.

    A second window on a second profile is how people work: another account, or an
    instance of one's own inside an RDP session. Only the SAME profile twice is the
    thing that breaks, because both write that profile's settings file over each other
    and both drive its daemon. So the guard is per profile directory and must never
    grow into «one panel on this machine».
    """
    with _profiles_in_tmp() as profiles:
        profiles.create("second")
        held = autostartmod.take_lock(profiles, "main" if profiles.active == "main"
                                      else profiles.active)
        try:
            here = profiles.active
            assert autostartmod.locked(profiles, here) is True
            assert autostartmod.holder(profiles, here) is None or isinstance(
                autostartmod.holder(profiles, here), int)
            # …and the other profile is completely unaffected: a panel opens there.
            assert autostartmod.locked(profiles, "second") is False
            other = autostartmod.take_lock(profiles, "second")
            assert other is not None, "a second profile must be free to open"
            autostartmod.drop_lock(other)
        finally:
            autostartmod.drop_lock(held)


def test_the_holder_is_named_so_the_refusal_can_be_worded():
    """`holder` answers «who has it» — `None` when nobody does, a pid when the panel
    that took it has also beaten. The lock decides; the pid is for the message."""
    with _profiles_in_tmp() as profiles:
        assert autostartmod.holder(profiles) is None
        held = autostartmod.take_lock(profiles)
        try:
            autostartmod.beat(profiles)
            assert autostartmod.holder(profiles) == os.getpid()
        finally:
            autostartmod.drop_lock(held)
        assert autostartmod.holder(profiles) is None


def test_a_profile_that_could_not_be_reopened_says_so_on_the_page():
    """A remembered profile that is NOT restored has to say why, where it can be read.

    It did not (#1215). `Workspace.restore` runs before any session has been adopted, so
    the refusal was said into a log that did not exist yet and fell through to a stderr a
    windowed panel does not have: the profile was simply missing, with nothing anywhere
    saying it had been asked for — and since a profile without a page is rebuilt from
    scratch on every switch, the cost showed up as a freeze rather than as a message.

    So the note waits for a page, and it says WHOSE lock it is: a second panel that is
    genuinely running reads differently from one that has stopped answering, and only
    the second is something the person has to go and close. The lock itself is never
    broken on the strength of a heartbeat — it is the kernel's answer, and overruling it
    is how two panels end up writing one `config.json`.
    """
    try:
        from panel import __main__ as pm                  # needs tkinter and a display
    except Exception as exc:                              # noqa: BLE001
        print(f"  skip (panel.__main__ will not import here: {exc})")
        return

    class _Panel:
        _profile_held_elsewhere = pm.Panel._profile_held_elsewhere
        _holder_note = pm.Panel._holder_note

        def __init__(self, profiles) -> None:
            self._workspace = types.SimpleNamespace(profiles=profiles)
            self._current_session = None       # …as it is while the workspace restores
            self._held_notes: list = []
            self.said: list = []

        def _say(self, tag, key, **fmt) -> None:
            self.said.append((key, fmt))

    with _profiles_in_tmp() as profiles:
        name = profiles.active
        # A panel that is genuinely up: it holds the lock and it is beating. The lock is
        # real — this process stands in for the one holding it — so «did the note leave
        # it alone» is a question with an answer at the end.
        held = autostartmod.take_lock(profiles, name)
        assert held is not None, "could not take the lock to stand in with"
        autostartmod.beat(profiles)
        panel = _Panel(profiles)
        panel._profile_held_elsewhere(name)
        assert panel.said == [], "said into a log that does not exist yet"
        assert [k for k, _f in panel._held_notes] == ["log.profile.held_elsewhere"], \
            panel._held_notes
        # …and once there is a page, it is said there.
        panel._current_session = object()
        panel._profile_held_elsewhere(name)
        assert [k for k, _f in panel.said] == ["log.profile.held_elsewhere"], panel.said

        # The other case: the lock is held and nothing has beaten for it in an hour.
        _age(profiles, autostartmod.STALE_SEC + 3600)
        panel = _Panel(profiles)
        panel._current_session = object()
        panel._profile_held_elsewhere(name)
        key, fmt = panel.said[0]
        assert key == "log.profile.held_stale", panel.said
        assert fmt["name"] == name and fmt["mins"] >= 60, fmt
        # Whatever it says, it did not take the profile over: a heartbeat is a nicety
        # and the lock is the answer, so the lock is still exactly where it was.
        try:
            assert autostartmod.locked(profiles, name) is True, \
                "the note broke the lock it was only supposed to describe"
        finally:
            autostartmod.drop_lock(held)
        assert autostartmod.locked(profiles, name) is False


def test_a_held_profile_is_never_opened_a_second_time():
    """The lock has the last word when the beat says nothing — no file, no psutil."""
    with _profiles_in_tmp() as profiles:
        name, launched = profiles.active, []
        real_open, real_pids = autostartmod.open_panel, autostartmod.panel_pids
        autostartmod.open_panel = lambda p, n: launched.append(n)
        autostartmod.panel_pids = lambda p, n=None: []     # nothing to see there either
        held = autostartmod.take_lock(profiles)
        try:
            record = autostartmod.check(name)
        finally:
            autostartmod.drop_lock(held)
            autostartmod.open_panel, autostartmod.panel_pids = real_open, real_pids
        assert launched == [], "it opened a second panel on a held profile"
        assert record["state"] == "running" and record["seen"] == "lock"
        assert record["locked"] is True


def test_the_daemon_port_is_read_per_profile_and_is_not_the_liveness_test():
    """The daemon answers «can I drive the game», never «is the panel running».

    It is started detached and outlives the panel that started it, it has no idle
    timeout, and `daemon.bat` runs one with no panel at all — so it says «up» with
    nothing open. Kept as a diagnostic, and per profile, because a second account in its
    own Windows session drives its own client on its own port.
    """
    import lua_client

    with _profiles_in_tmp() as profiles:
        assert autostartmod._daemon_port(profiles) == lua_client.DEFAULT_PORT
        profiles.save({"daemon_port": 47655})
        assert autostartmod._daemon_port(profiles) == 47655
        for junk in ("", "abc", None, 0, 99999):
            profiles.save({"daemon_port": junk})
            assert autostartmod._daemon_port(profiles) == lua_client.DEFAULT_PORT, junk
        # And it is nowhere near the verdict: a profile with a daemon up and no beat is
        # «stopped», which is the whole point of not testing liveness with a port.
        profiles.save({})
        assert autostartmod.probe(profiles).state == "stopped"


def test_a_panel_process_is_told_from_a_tab_and_from_the_check_itself():
    """What counts as «a panel is already on this profile».

    The module argument has to be exactly `panel`: `-m panel.runtime.autostart` is this
    very check (it runs hourly and would find itself), and `-m panel.tabs.rally` is one
    tab in a window of its own, which writes no `config.json` and is not a panel.
    """
    at = autostartmod._panel_profile
    assert at(["pythonw.exe", "-m", "panel", "--profile", "main"]) == "main"
    assert at(["python.exe", "-m", "panel"]) == ""            # whatever is active
    assert at(["pythonw.exe", "-m", "panel.runtime.autostart", "--profile", "main"]) is None
    assert at(["python.exe", "-m", "panel.tabs.rally"]) is None
    assert at(["python.exe", "somescript.py"]) is None
    assert at([]) is None


def test_no_second_panel_on_a_profile_that_already_has_one():
    """The guard that does not depend on a file: two panels write one config.json.

    A beat can be missing for reasons that are not «the panel is gone» — the file
    deleted by hand, a profile directory restored from a backup, a panel built before
    the beat existed. In every one of those a launch would be the damaging answer, so
    the process scan has the last word and the check leaves the panel alone.
    """
    with _profiles_in_tmp() as profiles:
        name = profiles.active
        launched = []
        real_pids, real_open = autostartmod.panel_pids, autostartmod.open_panel
        autostartmod.panel_pids = lambda p, n=None: [4242]
        autostartmod.open_panel = lambda p, n: launched.append(n)
        try:
            record = autostartmod.check(name)          # no beat at all, panel running
        finally:
            autostartmod.panel_pids, autostartmod.open_panel = real_pids, real_open
        assert launched == [], "it opened a second panel on a live profile"
        assert record["state"] == "running" and record["seen"] == "process"
        assert record["pid"] == 4242


def test_a_wedged_panel_is_closed_before_a_new_one_is_opened():
    """The one case that DOES act on top of something — and only after closing it."""
    with _profiles_in_tmp() as profiles:
        name = profiles.active
        autostartmod.beat(profiles)
        _age(profiles, autostartmod.STALE_SEC + 60)
        if autostartmod.probe(profiles).state != "hung":
            return                                     # no psutil: never a kill
        stopped, launched = [], []
        real_stop, real_open, real_pids = (autostartmod.stop, autostartmod.open_panel,
                                           autostartmod.panel_pids)
        autostartmod.stop = lambda pid: stopped.append(pid)
        autostartmod.open_panel = lambda p, n: launched.append(n)
        autostartmod.panel_pids = lambda p, n=None: [4242]   # a second one, somehow
        try:
            record = autostartmod.check(name)
        finally:
            (autostartmod.stop, autostartmod.open_panel,
             autostartmod.panel_pids) = real_stop, real_open, real_pids
        assert stopped == [os.getpid(), 4242], stopped
        assert launched == [name]
        assert record["state"] == "failed"             # the stand-in never beats
        assert record["seen"] == "hung"


# -- one panel, several profiles (#1207) ---------------------------------------
def test_the_set_it_opens_is_the_one_the_panel_saved():
    """Read when the task fires, never frozen into it — the person opens and closes pages."""
    with _profiles_in_tmp() as profiles:
        assert autostartmod.open_set(profiles) == [profiles.active], "no set = the active one"
        profiles.create("player2")
        profiles.set_open_profiles([profiles.active, "player2"])
        assert autostartmod.open_set(profiles) == [profiles.active, "player2"]
        # `--profile` only says which page is on top; the rest still come up.
        assert autostartmod.open_set(profiles, "player2") == ["player2", profiles.active]


def test_a_legacy_task_pointing_at_a_deleted_profile_opens_the_saved_set_instead():
    """#1203 left tasks named after profiles. One whose profile is gone must NOT re-create
    it, empty, and open a panel on it every hour for ever."""
    with _profiles_in_tmp() as profiles:
        profiles.create("player2")
        profiles.set_open_profiles([profiles.active, "player2"])
        assert autostartmod.open_set(profiles, "deleted-long-ago") == \
            [profiles.active, "player2"]


def test_one_beating_page_means_the_panel_is_up_and_nothing_is_opened():
    """The window is one. A profile of the set still beating IS the panel — opening a
    second one for the page that is quiet would fight the first for its config.json."""
    with _profiles_in_tmp() as profiles:
        profiles.create("player2")
        profiles.set_open_profiles([profiles.active, "player2"])
        launched = []
        real_open, real_pids = autostartmod.open_panel, autostartmod.panel_pids
        autostartmod.open_panel = lambda p, n: launched.append(n)
        autostartmod.panel_pids = lambda p, n=None: []
        try:
            autostartmod.beat(profiles, "player2")      # only the second page beats
            record = autostartmod.check()
        finally:
            autostartmod.open_panel, autostartmod.panel_pids = real_open, real_pids
        assert launched == [], "it opened a second panel over a running one"
        assert record["state"] == "running", record
        assert record["profiles"] == [profiles.active, "player2"], record
        # …and every page's Settings reads the same verdict, whichever one is showing.
        for name in (profiles.active, "player2"):
            saved = json.loads(Path(profiles.autostart_state(name))
                               .read_text(encoding="utf-8"))
            assert saved["state"] == "running", name


def test_nothing_beating_opens_ONE_panel_on_the_first_page():
    """The whole set is dead — one window comes up, and it restores the rest itself."""
    with _profiles_in_tmp() as profiles:
        profiles.create("player2")
        profiles.set_open_profiles([profiles.active, "player2"])
        launched = []
        real_open, real_pids = autostartmod.open_panel, autostartmod.panel_pids
        autostartmod.open_panel = lambda p, n: launched.append(n)
        autostartmod.panel_pids = lambda p, n=None: []
        try:
            record = autostartmod.check()
        finally:
            autostartmod.open_panel, autostartmod.panel_pids = real_open, real_pids
        assert launched == [profiles.active], "one panel, on the page that was on top"
        assert record["state"] == "failed"        # the stand-in never beats
        assert record["profiles"] == [profiles.active, "player2"]


def test_the_task_names_this_install_and_looks_once_an_hour():
    xml = autostartmod.task_xml(python=r"C:\Python312\pythonw.exe",
                                repo=r"C:\LastWar", account="PC\\player",
                                run_level="HighestAvailable",
                                start="2026-01-01T12:00:00")
    root = ET.fromstring(xml)
    exec_node = root.find(".//t:Actions/t:Exec", NS)
    assert exec_node.find("t:Command", NS).text == r"C:\Python312\pythonw.exe"
    assert exec_node.find("t:WorkingDirectory", NS).text == r"C:\LastWar"
    # NO `--profile` (#1207): what one panel opens is read from the panel's own saved set
    # when the task fires, so the task cannot go on opening yesterday's profiles.
    assert exec_node.find("t:Arguments", NS).text == "-m panel.runtime.autostart"

    every = root.find(".//t:TimeTrigger/t:Repetition/t:Interval", NS)
    assert every.text == "PT1H", "the check is hourly — that is the whole feature"
    # No <Duration>: the repetition must not quietly expire after a day.
    assert root.find(".//t:TimeTrigger/t:Repetition/t:Duration", NS) is None
    assert root.find(".//t:LogonTrigger", NS) is not None, "nothing runs it after a reboot"

    principal = root.find(".//t:Principals/t:Principal", NS)
    assert principal.find("t:LogonType", NS).text == "InteractiveToken", \
        "a task with no desktop can open no window"
    assert principal.find("t:RunLevel", NS).text == "HighestAvailable"
    assert principal.find("t:UserId", NS).text == "PC\\player"
    assert root.find(".//t:Settings/t:MultipleInstancesPolicy", NS).text == "IgnoreNew"


def test_the_task_mirrors_the_rights_the_panel_has_now():
    """A panel running plain registers a plain task — asking for more is what needs an
    administrator, and refusing to register at all would be worse than a task that
    opens the panel exactly as the person runs it themselves."""
    plain = ET.fromstring(autostartmod.task_xml(run_level="LeastPrivilege"))
    assert plain.find(".//t:Principals/t:Principal/t:RunLevel", NS).text == "LeastPrivilege"


def test_an_account_name_needing_escaping_still_makes_valid_xml():
    xml = autostartmod.task_xml(python="py.exe", repo="C:\\x & <y>",
                                account="PC\\a & b", run_level="LeastPrivilege")
    root = ET.fromstring(xml)                 # it parses, which is the assertion
    assert root.find(".//t:Actions/t:Exec/t:WorkingDirectory", NS).text == "C:\\x & <y>"
    assert root.find(".//t:Principals/t:Principal/t:UserId", NS).text == "PC\\a & b"
    assert autostartmod.task_xml(account="", run_level="LeastPrivilege").count(
        "<UserId>") == 0


def test_one_task_for_one_panel_and_the_old_per_profile_names_are_known():
    """#1207: the task is `Last War Bot\\panel`, and #1203's names are only swept away."""
    assert autostartmod.task_name() == r"Last War Bot\panel"
    assert autostartmod.legacy_task_name("main") == r"Last War Bot\panel-main"
    assert autostartmod.legacy_task_name("second") == r"Last War Bot\panel-second"
    # A name that sanitises to nothing must not make a task called `panel-`.
    assert autostartmod.legacy_task_name("///") == r"Last War Bot\panel-default"
    assert autostartmod.task_name().startswith(autostartmod.TASK_FOLDER)


def test_a_path_with_spaces_and_cyrillic_survives_the_xml():
    """Ordinary here: the install is wherever it was unpacked (#1196), and the account is
    the person's own. The definition is written UTF-16 for exactly this."""
    xml = autostartmod.task_xml(python=r"C:\Python312\pythonw.exe",
                                repo=r"D:\Games\мои проекты\last-war-vp-bot",
                                account="PC\\Игрок", run_level="LeastPrivilege")
    root = ET.fromstring(xml)
    assert (root.find(".//t:Actions/t:Exec/t:WorkingDirectory", NS).text
            == r"D:\Games\мои проекты\last-war-vp-bot")
    assert root.find(".//t:Principals/t:Principal/t:UserId", NS).text == "PC\\Игрок"
    # And it is handed to schtasks as UTF-16, which is the only encoding it reads.
    assert xml.startswith('<?xml version="1.0" encoding="UTF-16"?>')
    assert xml.encode("utf-16").startswith(b"\xff\xfe")


def test_the_status_is_asked_of_windows_not_of_the_profile():
    """Off this OS there is no scheduler, so nothing is registered and nothing pretends."""
    with _profiles_in_tmp() as profiles:
        info = autostartmod.status(profiles)
        assert info.task == autostartmod.TASK
        assert info.profiles == (profiles.active,)
        assert info.supported is (os.name == "nt")
        if not info.supported:
            assert info.registered is False and info.elevated is False


def test_the_panel_is_opened_with_the_windowed_interpreter_when_there_is_one():
    """Nobody is there to look at a console window at three in the morning.

    …and nobody is there to close one either: `python.exe` would leave a console behind
    every launch. The swap is to the twin BESIDE it, never to a guessed path — an
    install without `pythonw.exe` keeps the interpreter it was given.
    """
    with tempfile.TemporaryDirectory() as tmp:
        console = os.path.join(tmp, "python.exe")
        Path(console).write_text("", encoding="utf-8")
        assert autostartmod.panel_python(console) == console
        windowed = os.path.join(tmp, "pythonw.exe")
        Path(windowed).write_text("", encoding="utf-8")
        assert autostartmod.panel_python(console) == windowed
        assert autostartmod.panel_python(windowed) == windowed
    assert autostartmod.panel_python("/usr/bin/python3") == "/usr/bin/python3"


def _main() -> int:
    if autostartmod is None:
        print("  SKIP no tkinter — panel.runtime cannot be imported here")
        return 0
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
