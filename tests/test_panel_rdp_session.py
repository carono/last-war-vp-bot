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

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools" / "lib"))

import game_link                            # noqa: E402 — the reading itself (#1260)

try:                                        # the WSL python3 has no tkinter, and the
    from panel.runtime import game_process as gp   # runtime package imports it
except Exception as _exc:                   # noqa: BLE001
    gp, _WHY = None, _exc


class _Settings:
    """A stand-in for the profile's settings binder — just the readers used here."""

    def __init__(self, **values) -> None:
        self.values = {"game_exe": "LastWar.exe", "rdp_session": False,
                       "rdp_user": "", "daemon_port": 47655, **values}

    def opt_bool(self, key):
        return bool(self.values.get(key))

    def opt_str(self, key):
        return str(self.values.get(key) or "")

    def opt_int(self, key, low=None, high=None):
        return int(self.values.get(key) or 0)


class _Machine:
    """The Windows half, stubbed: who is logged on where, and what runs there.

    ``sessions`` is ``{login: id}`` or ``{login: (id, state)}``; ``None`` is the machine
    that cannot be asked at all (no pywin32), which is a different answer from "no such
    session" and has to stay that way. Only the two calls that reach Windows are
    replaced — the resolution on top of them is the real code.
    """

    def __init__(self, sessions, processes: dict, exe: str = "LastWar.exe") -> None:
        self.rows = None if sessions is None else [
            {"id": (v[0] if isinstance(v, tuple) else v), "user": k,
             "state": (v[1] if isinstance(v, tuple) else gp.WTS_ACTIVE)}
            for k, v in sessions.items()]
        self.processes = processes                                    # session -> pids
        self.exe = exe            # what those pids are called; anything else is absent

    def _named(self, exe):
        return exe.lower() == self.exe.lower()

    def __enter__(self):
        # Stubbed where the reading lives (`tools/lib/game_link.py`, #1260) and read
        # back through the panel: the resolution on top of these two calls is the real
        # code, and there is exactly one copy of it to stub.
        self._saved = (game_link.sessions, game_link._pids_in_session,
                       game_link._pids_by_name, game_link.endpoint_of,
                       game_link.client_sockets)
        game_link.sessions = lambda: self.rows
        game_link._pids_in_session = lambda exe, session: (
            list(self.processes.get(session, ())) if self._named(exe) else [])
        game_link._pids_by_name = lambda exe: ([pid for pids in self.processes.values()
                                                for pid in pids] if self._named(exe) else [])
        game_link.endpoint_of = lambda found: None   # foreign sockets come back with no pid
        game_link.client_sockets = lambda found: []  # …so there is no verdict on the link
        return self

    def __exit__(self, *exc):
        (game_link.sessions, game_link._pids_in_session, game_link._pids_by_name,
         game_link.endpoint_of, game_link.client_sockets) = self._saved
        return False


# -- the two knobs are one answer -------------------------------------------

def test_the_login_means_nothing_while_the_tick_is_off():
    assert gp.profile_user(_Settings(rdp_user="player2")) is None
    assert gp.profile_user(_Settings(rdp_session=True, rdp_user="player2")) == "player2"
    # Trimmed, because a login typed with a trailing space is the same login.
    assert gp.profile_user(_Settings(rdp_session=True, rdp_user=" player2 ")) == "player2"
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
    with _Machine(sessions={"player1": 1}, processes={1: [111]}):
        running, label = gp.status("LastWar.exe", user="player2")
    assert running is False, label
    # NOT "game not found": the answer is "there is nowhere to look", and the watchdog
    # relaunching on the strength of it would start a client on the wrong desktop.
    assert label.key == "game.st.no_session", label.key
    assert label.fmt == {"user": "player2"}, label.fmt


def test_the_client_on_this_desktop_is_not_the_other_profiles():
    with _Machine(sessions={"player1": 1, "player2": 4}, processes={1: [111]}):
        running, label = gp.status("LastWar.exe", user="player2")
    assert running is False, label
    assert label.key == "game.st.session_not_found", label.key


def test_a_client_in_the_named_session_is_found_there():
    with _Machine(sessions={"player1": 1, "player2": 4}, processes={1: [111], 4: [222]}):
        running, label = gp.status("LastWar.exe", user="player2")
    assert running is True, label
    assert label.key == "game.st.session_running", label.key
    assert label.fmt == {"user": "player2", "pid": 222}, label.fmt


def test_without_a_session_nothing_changes():
    with _Machine(sessions={"player1": 1}, processes={1: [111]}):
        running, label = gp.status("LastWar.exe")
    assert running is True and label.fmt == {"pid": 111}, label
    assert label.key == "game.st.running", label.key

    with _Machine(sessions={}, processes={}):
        running, label = gp.status("LastWar.exe")
    assert running is False and label.key == "game.st.not_found", label.key


# -- every answer is one the panel can say in the person's language ----------

def test_the_strip_never_shows_a_sentence_the_locales_do_not_have():
    import json
    from pathlib import Path

    seen = []
    with _Machine(sessions={"player1": 1, "player2": (4, gp.WTS_DISCONNECTED)},
                  processes={1: [111], 4: [222]}):
        seen.append(gp.status("LastWar.exe")[1])
        seen.append(gp.status("LastWar.exe", user="player2")[1])
        seen.append(gp.status("Nothing.exe")[1])
        seen.append(gp.status("Nothing.exe", user="player2")[1])
        seen.append(gp.status("LastWar.exe", user="nobody")[1])
    keys = [m.key for m in seen]
    assert len(set(keys)) == 5, keys
    root = Path(__file__).resolve().parents[1] / "panel" / "locales"
    for path in sorted(root.glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in locale]
        assert not missing, f"{path.name}: {missing}"
        for msg in seen:                      # …and it takes the values it is given
            locale[msg.key].format(**msg.fmt)


# -- «Проверить»: what is wrong, not merely that something is ----------------

def test_the_check_tells_the_four_ways_it_can_be_wrong_apart():
    live = {"player1": 1, "player2": (4, gp.WTS_DISCONNECTED)}

    def kind(settings, sessions=live, processes=None):
        with _Machine(sessions=sessions, processes=processes or {1: [111], 4: [222]}):
            return gp.check(settings)

    # Not ticked at all — this desktop, and nothing to complain about.
    assert kind(_Settings())["kind"] == "off"
    # Ticked with an empty box: a setting half made, NOT the same as not ticked.
    assert kind(_Settings(rdp_session=True))["kind"] == "no_login"
    # Nobody by that name is logged on: the session is not up yet.
    assert kind(_Settings(rdp_session=True, rdp_user="ghost"))["kind"] == "no_session"
    # The session is up and empty: the client itself has to be started in it.
    empty = kind(_Settings(rdp_session=True, rdp_user="player2"), processes={1: [111]})
    assert empty["kind"] == "no_client" and empty["session"] == 4, empty
    # …and the whole of it in place.
    ok = kind(_Settings(rdp_session=True, rdp_user="player2"))
    assert ok["kind"] == "ok" and ok["pid"] == 222, ok
    assert ok["state"] == gp.WTS_DISCONNECTED, ok      # normal, and shown as such
    # A machine that cannot be asked is its own answer, not "no such session".
    assert kind(_Settings(rdp_session=True, rdp_user="player2"),
                sessions=None)["kind"] == "unsupported"


def test_the_port_and_the_session_are_read_as_one_answer():
    import lua_client

    other = _Settings(rdp_session=True, rdp_user="player2", daemon_port=47655)
    same = _Settings(rdp_session=True, rdp_user="player2",
                     daemon_port=lua_client.DEFAULT_PORT)
    here = _Settings(daemon_port=lua_client.DEFAULT_PORT)

    assert gp.port_clash(other) is False
    # Looking into another session while talking to THIS desktop's daemon: reads one
    # client, presses the buttons of another. Nothing else in the panel would say so.
    assert gp.port_clash(same) is True
    # …and a profile that never left this desktop is not in that state at all.
    assert gp.port_clash(here) is False

    with _Machine(sessions={"player2": 4}, processes={4: [222]}):
        assert gp.check(same)["clash"] is True
        assert gp.check(other)["clash"] is False


def test_the_check_verdicts_all_have_something_to_say_in_every_locale():
    import json
    from pathlib import Path

    kinds = ("off", "no_login", "no_session", "no_client", "ok", "unsupported",
             "probe_error")
    root = Path(__file__).resolve().parents[1] / "panel" / "locales"
    for path in sorted(root.glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        for extra in ("session.check", "session.clash", "session.state.active",
                      "session.state.disconnected", "session.state.other"):
            assert extra in locale, f"{path.name}: {extra}"
        for kind in kinds:
            assert f"session.check.{kind}" in locale, f"{path.name}: {kind}"


# -- and the page says it in words, not in verdict codes ---------------------

def test_the_page_answers_in_sentences_and_greys_the_login_box():
    """Press «Проверить» on the real page and read what a person would read.

    The verdict is a `kind`; what must reach the person is the sentence for it. This is
    the seam where a kind nobody wrote a key for would show up as `session.check.ok`
    typed out literally on the page — the one failure the locale test above cannot see.

    Needs Tk and a display; says SKIP without one.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no tkinter: {exc}")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import fake_runtime
        from panel.tabs.settings import SettingsTab
        root = tk.Tk()
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no display: {exc}")
        return
    try:
        root.withdraw()
        rt = fake_runtime.cold_runtime(root)
        rt.settings.save = lambda raw=None: None
        page = SettingsTab(rt, ttk.Frame(root))
        page._build_session_settings(page.parent)

        saved = gp.check
        try:
            for kind in ("off", "no_login", "no_session", "no_client", "ok",
                         "unsupported", "probe_error"):
                gp.check = lambda s, k=kind: {
                    "kind": k, "user": "player2", "session": 4,
                    "state": gp.WTS_DISCONNECTED, "exe": "LastWar.exe", "pid": 222,
                    "port": 47655, "clash": False, "error": "boom"}
                page._check_session()
                said = page._session_verdict.cget("text")
                assert said and not said.startswith("session."), (kind, said)
                assert "{" not in said, (kind, said)      # every slot was filled
        finally:
            gp.check = saved

        # The login control follows the tick, both ways. WHICH control it is depends on
        # the machine — a picker of this machine's accounts where Windows will list
        # them, a box to type in where it will not (#1263) — so the live state is
        # «usable», not one particular word for it.
        rt.settings.vars["rdp_session"].set(False)
        assert str(page._session_user_entry.cget("state")) == "disabled"
        rt.settings.vars["rdp_session"].set(True)
        assert str(page._session_user_entry.cget("state")) in ("normal", "readonly"), \
            page._session_user_entry.cget("state")
    finally:
        try:
            root.destroy()
        except Exception:                   # noqa: BLE001
            pass


def test_the_page_names_a_shared_client_and_what_the_two_knobs_amount_to():
    """The two sentences #1263 put under the knobs, on the real page.

    They exist because «Развести клиенты…» was a modal that answered neither question:
    a person could not see that this profile was farming somebody else's account, and
    could not see whether what they had just done had applied. Both are readings now,
    on the page where the login is typed — and the first one moves with the tick rather
    than with the file, so ticking the box clears the warning at once.

    Needs Tk and a display; says SKIP without one.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no tkinter: {exc}")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import fake_runtime
        from panel.tabs.settings import SettingsTab
        root = tk.Tk()
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no display: {exc}")
        return
    try:
        root.withdraw()
        rt = fake_runtime.cold_runtime(root)
        rt.settings.save = lambda raw=None: None
        # A second profile with a config of its own that says nothing — which is the
        # whole bug (#1250): an empty file falls back to the default profile's port, so
        # the two really do drive one client.
        second = rt.profiles.create("shared-1263")
        rt.profiles.save({}, second)

        page = SettingsTab(rt, ttk.Frame(root))
        page._build_session_settings(page.parent)

        said = page._session_shared.cget("text")
        assert second in said and not said.startswith("session."), said
        assert "{" not in said, said
        means = page._session_means.cget("text")
        assert means and not means.startswith("session.") and "{" not in means, means

        # Give this profile a session of its own: the warning goes, and the sentence
        # under it changes to the one that names what is still left to do.
        rt.settings.vars["rdp_user"].set("player2")
        rt.settings.vars["rdp_session"].set(True)
        assert page._session_shared.cget("text") == "", page._session_shared.cget("text")
        means = page._session_means.cget("text")
        assert "player2" in means and "{" not in means, means

        # …and a login left empty is its own sentence rather than a silent nothing.
        rt.settings.vars["rdp_user"].set("")
        means = page._session_means.cget("text")
        assert means and "{" not in means, means
    finally:
        try:
            root.destroy()
        except Exception:                   # noqa: BLE001
            pass


# -- the one call a caller wants --------------------------------------------

def test_profile_status_honours_the_executable_and_the_session_together():
    seen = {}
    saved = gp.status
    gp.status = lambda exe, user=None: seen.update(exe=exe, user=user) or (True, "ok")
    try:
        gp.profile_status(_Settings(game_exe="Other.exe", rdp_session=True,
                                    rdp_user="player2"))
        assert seen == {"exe": "Other.exe", "user": "player2"}, seen
        gp.profile_status(_Settings(game_exe="Other.exe"))
        assert seen == {"exe": "Other.exe", "user": None}, seen
    finally:
        gp.status = saved


def test_the_knobs_are_in_the_profile_defaults():
    from panel.runtime import settings as settingsmod
    assert settingsmod.DEFAULTS["rdp_session"] is False
    assert settingsmod.DEFAULTS["rdp_user"] == ""


def test_the_session_travels_to_a_scenario_beside_the_port():
    """What the runtime hands a run: the port, the lease, and WHERE the client is.

    The third one is the launch's (#1218). Without it `START_GAME` had nothing to go on
    and the launcher landed on the panel's own desktop — a third client in front of
    whoever is at the keyboard, while the account that was asked for stayed down.
    """
    from panel.runtime import host as hostmod

    class _FakeGame:
        token = "tok3"

    class _Runtime:
        settings = _Settings(rdp_session=True, rdp_user="player2", daemon_port=47655)
        game = _FakeGame()
        daemon_port = staticmethod(lambda: 47655)
        game_target = hostmod.PanelRuntime.game_target

    rt = _Runtime()
    assert _Runtime.game_target(rt) == {"game_port": 47655, "game_token": "tok3",
                                        "game_user": "player2"}
    # …and a profile on this desktop names no session at all, rather than "".
    _Runtime.settings = _Settings()
    assert _Runtime.game_target(rt)["game_user"] is None


# -- «Поднять сессию»: the panel does it itself now (#1231) ------------------

def test_a_profile_on_this_desktop_has_no_session_to_bring_up():
    """The button is a no-op there, and says so by refusing rather than by guessing.

    Bringing "the session" up for a profile that names none would create one for
    whatever `--user` defaulted to — which on somebody else's machine is nobody.
    """
    try:
        gp.bring_up(_Settings())
    except LookupError:
        return
    raise AssertionError("a profile with no session named must refuse to bring one up")


def test_the_bring_up_hands_the_session_and_the_port_to_the_tool():
    """Both halves travel: a bring-up that forgot the port starts a daemon on 47654,
    which is THIS desktop's — the exact crossing `session.clash` exists to warn about.
    """
    seen = {}

    class _Tool:
        @staticmethod
        def bring_up(user, port, say=None, **kw):
            seen.update(user=user, port=port, say=say, **kw)
            return 0

    saved = sys.modules.get("rdp_instance")
    sys.modules["rdp_instance"] = _Tool
    try:
        note = []
        code = gp.bring_up(_Settings(rdp_session=True, rdp_user="player2",
                                     daemon_port=47655), say=note.append)
    finally:
        if saved is None:
            del sys.modules["rdp_instance"]
        else:
            sys.modules["rdp_instance"] = saved
    assert code == 0, code
    assert seen["user"] == "player2" and seen["port"] == 47655, seen
    assert seen["say"] is not None, "the panel's log must be handed in, not dropped"
    # …and it asks for nothing else. `seal` rewrites a stored credential into a form
    # this logon was measured refusing to spend (#1231): a button that turned it on by
    # itself would leave the person's second instance failing over on every bring-up,
    # for a hardening they never asked for and cannot see.
    assert not seen.get("seal"), seen


def test_a_tool_that_gives_up_reaches_the_panel_as_an_error():
    """`SystemExit` is how a command-line tool says "this cannot go on" — and it is not
    an `Exception`, so a worker thread that lets one past dies with nothing said."""

    class _Tool:
        @staticmethod
        def bring_up(user, port, say=None):
            raise SystemExit("no session for player2 after 180s")

    saved = sys.modules.get("rdp_instance")
    sys.modules["rdp_instance"] = _Tool
    try:
        gp.bring_up(_Settings(rdp_session=True, rdp_user="player2"))
    except RuntimeError as exc:
        assert "player2" in str(exc), exc
        return
    except SystemExit:
        raise AssertionError("SystemExit reached the panel unconverted")
    finally:
        if saved is None:
            sys.modules.pop("rdp_instance", None)
        else:
            sys.modules["rdp_instance"] = saved
    raise AssertionError("a tool that gave up must be reported, not swallowed")


def test_the_verdict_that_names_the_button_spells_it_from_the_button_s_own_key():
    """«…поднимите сессию» must name what is written ON the button, in every locale —
    a verdict pointing at a control worded differently is a person hunting for it."""
    import json
    root = Path(__file__).resolve().parents[1] / "panel" / "locales"
    for path in sorted(root.glob("*.json")):
        loc = json.loads(path.read_text(encoding="utf-8"))
        assert "session.bring_up" in loc, path.name
        assert "{up}" in loc["session.check.no_session"], path.name


# -- one address is one credential slot (#1263) ------------------------------
#
# The live fault: bringing ANY profile's session up signed in as one and the same
# account. Nothing was hard-coded — the panel passed each profile's own login and the
# log said so. Windows keys a saved RDP password by `TERMSRV/<address>` and by nothing
# else, one address was shared by every profile, and `credential_state` asked «is there
# a password here» where it meant «is it mine». So mstsc was started with a password
# that belonged to somebody else, spent it, and signed in as its owner.

def _rdp():
    """`tools/rdp_instance.py` without pywin32 — the two halves under test need none."""
    sys.path.insert(0, str(_ROOT / "tools"))
    try:
        import rdp_instance
        return rdp_instance
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no rdp_instance: {exc}")
        return None


def test_each_profile_gets_a_credential_slot_of_its_own():
    """The address follows the daemon port the panel already made unique.

    Nothing new to store and nothing to type: the port is one per profile by
    construction (`panel/runtime/provision.py`), so the addresses are too, and two
    accounts can each keep a saved password without overwriting the other's.
    """
    R = _rdp()
    if R is None:
        return
    base = R.DEFAULT_SERVER
    first, second, third = (R.host_for(p) for p in (47655, 47656, 47657))
    assert first == base, (first, base)
    assert len({first, second, third}) == 3, (first, second, third)
    # The console profile has no session to bring up, so its port answers with the base
    # rather than with an address below it.
    assert R.host_for(47654) == base
    # Anything unusable falls back to the base instead of inventing an address that
    # would not connect at all.
    for odd in (None, 0, -5, 999999, "nonsense"):
        assert R.host_for(odd) == base, odd


def test_a_password_belonging_to_somebody_else_is_never_spent():
    """`credential_state` asks WHOSE, not whether — for the readable slot too.

    The readable half is the one that was `is not None`, and that single line is why
    every «Поднять сессию» came up as one account (#1263). Both halves are stubbed at
    the credential read, so this needs no Windows and no saved passwords.
    """
    R = _rdp()
    if R is None:
        return
    try:
        import win32cred                    # noqa: F401 — only the constants are used
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no pywin32: {exc}")
        return
    saved_read, saved_account = R._cred_read, R._account
    R._account = lambda user: (None, "MACHINE", user)
    try:
        # A generic password saved for a DIFFERENT account on this address.
        R._cred_read = lambda target, kind: (
            {"UserName": r"MACHINE\other"} if kind == win32cred.CRED_TYPE_GENERIC
            and target.startswith("TERMSRV/") else None)
        state = R.credential_state("player2", "127.0.0.9")
        assert state["readable_rdp"] is False, state
        assert state["stored"] is False, state
        assert state["foreign"] is True, state
        assert state["owner"] == r"MACHINE\other", state

        # …and the same slot, this time holding this account's own password.
        R._cred_read = lambda target, kind: (
            {"UserName": r"MACHINE\player2"} if kind == win32cred.CRED_TYPE_GENERIC
            and target.startswith("TERMSRV/") else None)
        state = R.credential_state("player2", "127.0.0.9")
        assert state["readable_rdp"] is True and state["stored"] is True, state
        assert state["foreign"] is False, state

        # An empty slot is neither mine nor anybody's — Windows asks, nothing is stored.
        R._cred_read = lambda target, kind: None
        state = R.credential_state("player2", "127.0.0.9")
        assert state["stored"] is False and state["foreign"] is False, state
        assert state["owner"] == "", state
    finally:
        R._cred_read, R._account = saved_read, saved_account


def test_the_words_for_a_slot_somebody_else_owns_exist_everywhere():
    """The reading a person needs to understand «упорно один и тот же пользователь».

    It names three things and all three are data — the address, the owner, and who was
    asked for — so a locale that drops one leaves a sentence that cannot be acted on.
    """
    import json
    root = Path(__file__).resolve().parents[1] / "panel" / "locales"
    for path in sorted(root.glob("*.json")):
        loc = json.loads(path.read_text(encoding="utf-8"))
        for key in ("session.cred.foreign", "log.session.cred_foreign"):
            assert key in loc, (path.name, key)
            for slot in ("{server}", "{owner}", "{user}"):
                assert slot in loc[key], (path.name, key, slot)
        # …and the command that fixes it carries the port, because the port is what
        # decides which address the password lands on.
        assert "{port}" in loc["log.session.save_hint"], path.name


# -- the login is picked, not typed (#1263) -----------------------------------

def test_the_account_list_comes_from_windows_and_drops_the_disabled_ones():
    """`local_users` enumerates live and keeps nothing — there is no list to go stale.

    Disabled accounts are dropped because offering a login that cannot sign in is the
    mistake a picker exists to remove: `Guest` and the built-in service accounts are
    disabled on an ordinary install and would otherwise sit in the list looking usable.
    """
    R = _rdp()
    if R is None:
        return
    try:
        import win32net
        import win32netcon
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no pywin32: {exc}")
        return
    page = [
        [{"name": "beta", "flags": 0},
         {"name": "alpha", "flags": win32netcon.UF_ACCOUNTDISABLE},
         {"name": "Gamma", "flags": 0},
         {"name": "  ", "flags": 0}],
        [{"name": "delta", "flags": 0}, {"name": "beta", "flags": 0}],
    ]
    calls = {"n": 0}

    def fake_enum(server, level, flt, resume=0):
        # Two pages, so the resume handle is exercised: a machine with more accounts
        # than one call returns must not lose the tail.
        calls["n"] += 1
        return (page[resume], len(page[0]) + len(page[1]), 0 if resume else 1)

    saved = win32net.NetUserEnum
    win32net.NetUserEnum = fake_enum
    try:
        assert R.local_users() == ["beta", "delta", "Gamma"], R.local_users()
    finally:
        win32net.NetUserEnum = saved
    assert calls["n"] == 2, calls          # both pages were read


def test_a_machine_that_cannot_be_asked_is_not_a_machine_with_no_accounts():
    """`game_process.local_users` answers `(names, error)`, and the two are different.

    Folding them together is the failure this signature prevents: an empty list with no
    reason reads as a fresh install, and the page would offer a picker with nothing in
    it instead of a box to type in and a sentence saying why.
    """
    try:
        from panel.runtime import game_process as gpmod
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no runtime: {exc}")
        return
    R = _rdp()
    if R is None:
        return
    saved = R.local_users
    try:
        R.local_users = lambda: (_ for _ in ()).throw(OSError("pywin32 is not here"))
        names, error = gpmod.local_users()
        assert names == [] and "pywin32" in error, (names, error)
        R.local_users = lambda: ["one", "two"]
        names, error = gpmod.local_users()
        assert names == ["one", "two"] and error == "", (names, error)
    finally:
        R.local_users = saved


def test_the_page_offers_a_list_and_falls_back_to_typing():
    """The real page, both ways round — and the saved login survives either.

    A profile pointed at an account the enumeration does not return (a domain one, or
    one since renamed) must keep what it has: a picker that silently dropped it would
    turn a configured profile into a blank one on the next save.

    Needs Tk and a display; says SKIP without one.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no tkinter: {exc}")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import fake_runtime
        from panel.runtime import game_process as gpmod
        from panel.tabs.settings import SettingsTab
        root = tk.Tk()
    except Exception as exc:                # noqa: BLE001
        print(f"  SKIP no display: {exc}")
        return
    saved = gpmod.local_users
    try:
        root.withdraw()
        rt = fake_runtime.cold_runtime(root)
        rt.settings.save = lambda raw=None: None

        # A list, and a saved login that is NOT in it.
        gpmod.local_users = lambda: (["one", "two"], "")
        rt.settings.vars["rdp_user"].set("elsewhere")
        page = SettingsTab(rt, ttk.Frame(root))
        page._build_session_settings(page.parent)
        picker = page._session_user_entry
        assert isinstance(picker, ttk.Combobox), type(picker)
        values = list(picker.cget("values"))
        assert set(values) == {"one", "two", "elsewhere"}, values
        assert page._session_users.cget("text") == "", "a working list needs no excuse"
        # Picked, never typed — and the tick governs it.
        rt.settings.vars["rdp_session"].set(True)
        assert str(picker.cget("state")) == "readonly", picker.cget("state")
        rt.settings.vars["rdp_session"].set(False)
        assert str(picker.cget("state")) == "disabled", picker.cget("state")
        # Choosing writes the profile's own variable, which is what persists it (#1263).
        picker.set("two")
        assert rt.settings.opt_str("rdp_user") == "two"

        # …and a machine that will not answer gets a box and a reason, not an empty list.
        gpmod.local_users = lambda: ([], "pywin32 is not here")
        page2 = SettingsTab(rt, ttk.Frame(root))
        page2._build_session_settings(page2.parent)
        assert isinstance(page2._session_user_entry, ttk.Entry), \
            type(page2._session_user_entry)
        said = page2._session_users.cget("text")
        assert said and "pywin32" in said and "{" not in said, said
    finally:
        gpmod.local_users = saved
        try:
            root.destroy()
        except Exception:                   # noqa: BLE001
            pass


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
