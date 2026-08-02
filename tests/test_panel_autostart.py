r"""The autostart: the beat the panel writes, and what the hourly look makes of it.

Three things are worth pinning here, and all three are quiet when broken.

* **A stale beat whose process is still there is «hung», not «gone».** That is the whole
  reason the beat is written from the Tk queue rather than by a thread — a white,
  unresponsive window is exactly what a process-list check cannot tell from a working
  panel, and the wrong verdict means the account sits dead until somebody notices.
* **A recycled pid is not a panel.** Windows hands the number out again within minutes,
  so the executable name travels with it; without that check «pid 8124 exists» is a
  claim made by whatever got the number next.
* **The task names THIS install.** The interpreter, the working directory and the
  profile all come from the panel doing the registering. A hard-coded path would work on
  the machine it was written on and open the wrong panel — or none — everywhere else.

Touches no scheduler: `register` is never called, only the XML it would hand over. The
profiles live in a temporary directory, so a real profile is neither read nor written.

    C:\Python312\python.exe tests\test_panel_autostart.py
    python3 tests/test_panel_autostart.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import autostart as autostartmod        # noqa: E402
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


def test_the_task_names_this_install_and_looks_once_an_hour():
    xml = autostartmod.task_xml("main", python=r"C:\Python312\pythonw.exe",
                                repo=r"C:\LastWar", account="PC\\player",
                                run_level="HighestAvailable",
                                start="2026-01-01T12:00:00")
    root = ET.fromstring(xml)
    exec_node = root.find(".//t:Actions/t:Exec", NS)
    assert exec_node.find("t:Command", NS).text == r"C:\Python312\pythonw.exe"
    assert exec_node.find("t:WorkingDirectory", NS).text == r"C:\LastWar"
    # `-m panel.autostart` with the profile quoted: a name with a space in it must not
    # arrive as two arguments and check a profile nobody has.
    assert exec_node.find("t:Arguments", NS).text == '-m panel.autostart --profile "main"'

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
    plain = ET.fromstring(autostartmod.task_xml("main", run_level="LeastPrivilege"))
    assert plain.find(".//t:Principals/t:Principal/t:RunLevel", NS).text == "LeastPrivilege"


def test_a_profile_name_needing_escaping_still_makes_valid_xml():
    xml = autostartmod.task_xml('a & b <c>', python="py.exe", repo="C:\\x",
                                account="", run_level="LeastPrivilege")
    root = ET.fromstring(xml)                 # it parses, which is the assertion
    assert 'a & b <c>' in root.find(".//t:Actions/t:Exec/t:Arguments", NS).text
    assert root.find(".//t:Principals/t:Principal/t:UserId", NS) is None


def test_one_task_per_profile_all_in_one_folder():
    assert autostartmod.task_name("main") == r"Last War Bot\panel-main"
    assert autostartmod.task_name("second") == r"Last War Bot\panel-second"
    # A name that sanitises to nothing must not make a task called `panel-`.
    assert autostartmod.task_name("///") == r"Last War Bot\panel-default"


def test_the_status_is_asked_of_windows_not_of_the_profile():
    """Off this OS there is no scheduler, so nothing is registered and nothing pretends."""
    with _profiles_in_tmp() as profiles:
        info = autostartmod.status(profiles)
        assert info.task == autostartmod.task_name(profiles.active)
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
