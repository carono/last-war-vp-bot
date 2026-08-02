r"""Which client is this profile's? (task #1204)

A second account does not run on this desktop. It runs in a Windows session of its own,
owned by that session's own user (tools/rdp_instance.py), and the panel drives it over
its own daemon port. The port answers "what do I talk to"; it says nothing about *which
process is the game*, and by executable name alone the two clients are the same string.
A panel that asks by name gets the console session's client and calls it this profile's:
"running (pid …)" over a client of its own that died hours ago, and a watchdog that puts
a third one on this desktop.

So a profile names the session — the tick «игра запущена в RDP-сессии» and the login of
the user logged on to it — and this file pins what that naming is worth:

  * the two knobs are read as a pair: the login means nothing while the tick is off,
    and a blank login is the same as no tick;
  * a session that cannot be resolved is NOT "the game is not running". Folding the two
    together is what would have the watchdog relaunch a client that is alive and well;
  * with a session named, only the clients inside it count — the one on this desktop is
    not this profile's, however loudly it is running.

No Tk, no game, no pywin32: the two Windows calls are the seam
(`panel/runtime/game_process.session_of` and `_pids_in_session`), stubbed here.

    C:\Python312\python.exe tests\test_panel_rdp_session.py
    python3 tests/test_panel_rdp_session.py     # SKIP: the runtime package needs tkinter
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:                                        # the WSL python3 has no tkinter, and the
    from panel.runtime import game_process as gp   # runtime package imports it
except Exception as _exc:                   # noqa: BLE001
    gp, _WHY = None, _exc


class _Settings:
    """A stand-in for the profile's settings binder — just the readers used here."""

    def __init__(self, **values) -> None:
        self.values = {"game_exe": "LastWar.exe", "rdp_session": False,
                       "rdp_user": "", **values}

    def opt_bool(self, key):
        return bool(self.values.get(key))

    def opt_str(self, key):
        return str(self.values.get(key) or "")


class _Machine:
    """The Windows half, stubbed: who is logged on where, and what runs there."""

    def __init__(self, sessions: dict, processes: dict) -> None:
        self.sessions = {k.lower(): v for k, v in sessions.items()}   # login -> session
        self.processes = processes                                    # session -> pids

    def __enter__(self):
        self._saved = (gp.session_of, gp._pids_in_session, gp._pids_by_name, gp._endpoint)
        gp.session_of = lambda user: self.sessions.get(user.strip().lower())
        gp._pids_in_session = lambda exe, session: list(self.processes.get(session, ()))
        gp._pids_by_name = lambda exe: [pid for pids in self.processes.values()
                                        for pid in pids]
        gp._endpoint = lambda found: None      # foreign sockets come back without a pid
        return self

    def __exit__(self, *exc):
        (gp.session_of, gp._pids_in_session, gp._pids_by_name, gp._endpoint) = self._saved
        return False


# -- the two knobs are one answer -------------------------------------------

def test_the_login_means_nothing_while_the_tick_is_off():
    assert gp.profile_user(_Settings(rdp_user="casper")) is None
    assert gp.profile_user(_Settings(rdp_session=True, rdp_user="casper")) == "casper"
    # Trimmed, because a login typed with a trailing space is the same login.
    assert gp.profile_user(_Settings(rdp_session=True, rdp_user=" casper ")) == "casper"
    # Ticked with nothing typed is not a session — it is this desktop, as before.
    assert gp.profile_user(_Settings(rdp_session=True, rdp_user="  ")) is None


def test_a_half_typed_profile_is_this_desktop_rather_than_a_crash():
    class Broken:
        def opt_bool(self, key):
            raise ValueError("half-typed")

        def opt_str(self, key):
            return ""

    assert gp.profile_user(Broken()) is None


# -- a session that cannot be resolved is not "no game" ----------------------

def test_nobody_logged_on_there_is_said_in_so_many_words():
    with _Machine(sessions={"spame": 1}, processes={1: [111]}):
        running, label = gp.status("LastWar.exe", user="casper")
    assert running is False, label
    # NOT "game not found": the answer is "there is nowhere to look", and the watchdog
    # relaunching on the strength of it would start a client on the wrong desktop.
    assert "no session for casper" == label, label
    assert "not found" not in label, label


def test_the_client_on_this_desktop_is_not_the_other_profiles():
    with _Machine(sessions={"spame": 1, "casper": 4}, processes={1: [111]}):
        running, label = gp.status("LastWar.exe", user="casper")
    assert running is False, label
    assert "game not found" in label and "casper" in label, label


def test_a_client_in_the_named_session_is_found_there():
    with _Machine(sessions={"spame": 1, "casper": 4}, processes={1: [111], 4: [222]}):
        running, label = gp.status("LastWar.exe", user="casper")
    assert running is True, label
    assert "222" in label and "casper" in label, label


def test_without_a_session_nothing_changes():
    with _Machine(sessions={"spame": 1}, processes={1: [111]}):
        running, label = gp.status("LastWar.exe")
    assert running is True and "111" in label, label
    assert "session" not in label, label

    with _Machine(sessions={}, processes={}):
        running, label = gp.status("LastWar.exe")
    assert running is False and label == "game not found", label


# -- the one call a caller wants --------------------------------------------

def test_profile_status_honours_the_executable_and_the_session_together():
    seen = {}
    saved = gp.status
    gp.status = lambda exe, user=None: seen.update(exe=exe, user=user) or (True, "ok")
    try:
        gp.profile_status(_Settings(game_exe="Other.exe", rdp_session=True,
                                    rdp_user="casper"))
        assert seen == {"exe": "Other.exe", "user": "casper"}, seen
        gp.profile_status(_Settings(game_exe="Other.exe"))
        assert seen == {"exe": "Other.exe", "user": None}, seen
    finally:
        gp.status = saved


def test_the_knobs_are_in_the_profile_defaults():
    from panel.runtime import settings as settingsmod
    assert settingsmod.DEFAULTS["rdp_session"] is False
    assert settingsmod.DEFAULTS["rdp_user"] == ""


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
