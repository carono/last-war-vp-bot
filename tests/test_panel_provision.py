r"""One profile, one client — decided by the panel, not typed by the person (#1252).

`panel/runtime/provision.py` is what a profile's client comes from now. What has to
hold, and every one of these is a way the panel used to be quietly wrong:

  * **the console goes to the first profile and to nobody else.** There is one desktop,
    so there is one console profile; every profile after it is a Windows session of its
    own with a port of its own;
  * **a new profile is never handed a port somebody already has.** Five profiles created
    with an empty `config.json` all fell back to the default profile's 47654 and farmed
    ONE account while the panel showed four healthy profiles (#1250);
  * **the port is worked out, the login is asked.** A session profile with no login is
    refused — it would look for its client among nobody's processes and report the
    ordinary «клиент не запущен» for ever;
  * **what is already broken is split in two**: a port two different clients both claim
    is repaired unasked, and two profiles on ONE client are only listed, because
    separating them needs a login no amount of reading can supply;
  * **and a path is never a profile's opinion.** `runtime.settings.MACHINE_KEYS` answers
    from `tools/lib/game_paths.py`, so a value left in an old profile's file — this
    machine really had `C:\Program Files\LastWar\…`, a folder the game has never
    installed itself into — is not obeyed and is not written back.

Needs no display, no Windows and no socket: the port probe is injected.

    python3 tests/test_panel_provision.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import profile as profilemod                  # noqa: E402
from panel.runtime import provision                      # noqa: E402
from panel.runtime import settings as settingsmod        # noqa: E402

#: Nothing is listening anywhere — the machine probe, replaced.
NOTHING = lambda port: False                             # noqa: E731


class _Env:
    """`profilemod` on a scratch directory, with profiles written by hand."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE)
        profilemod.PROFILES_DIR = os.path.join(root, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
        self.profiles = profilemod.ProfileManager()
        return self

    def write(self, name: str, config: dict) -> str:
        """A profile with exactly this in its own file — `{}` for the empty ones."""
        self.profiles._ensure_dir(name)
        path = os.path.join(profilemod.PROFILES_DIR, name, profilemod.CONFIG_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        return name

    def own(self, name: str) -> dict:
        return self.profiles._load_own(name)

    def __exit__(self, *exc):
        (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE) = self._saved
        self._tmp.cleanup()
        return False


def _console(env, name: str = profilemod.DEFAULT_PROFILE) -> str:
    return env.write(name, {"daemon_port": provision.CONSOLE_PORT,
                            "rdp_session": False, "rdp_user": ""})


# ---------------------------------------------------------------------------

def test_the_first_profile_takes_the_console_and_needs_nothing_typed() -> None:
    """An ordinary machine's first profile: the desktop it is already looking at.

    `exclude` is the profile being planned FOR — a fresh install has only the seeded
    default, so with that one left out there is nobody on the console.
    """
    with _Env() as env:
        plan = provision.plan(env.profiles, exclude=profilemod.DEFAULT_PROFILE,
                              probe=NOTHING)
        assert plan.console, plan
        assert plan.port == provision.CONSOLE_PORT, plan
        assert plan.settings == {"daemon_port": provision.CONSOLE_PORT,
                                 "rdp_session": False, "rdp_user": ""}, plan.settings


def test_the_second_profile_is_refused_without_a_login() -> None:
    """The console is taken, so «somewhere else» is the only honest answer left.

    It refuses rather than quietly handing out another port on THIS desktop: a second
    daemon here finds this desktop's client, which is two leases over one game
    (docs/research/multi-profile-panel.md §4.3).
    """
    with _Env() as env:
        _console(env)
        assert provision.needs_login(env.profiles, exclude="second")
        try:
            provision.plan(env.profiles, exclude="second", probe=NOTHING)
        except ValueError as exc:
            assert "profile.error.no_login" == getattr(exc.args[0], "key", None), exc
        else:
            raise AssertionError("a second console profile was allowed")


def test_a_login_buys_a_session_and_a_port_of_its_own() -> None:
    with _Env() as env:
        _console(env)
        env.write("two", {"daemon_port": provision.CONSOLE_PORT + 1,
                          "rdp_session": True, "rdp_user": "user2"})
        plan = provision.plan(env.profiles, login="user3", exclude="three",
                              probe=NOTHING)
        assert not plan.console and plan.user == "user3", plan
        assert plan.port == provision.CONSOLE_PORT + 2, plan
        assert plan.settings["rdp_session"] is True


def test_a_port_something_is_already_listening_on_is_skipped() -> None:
    """A daemon binds exclusively, so a port that answers is not one to hand out."""
    with _Env() as env:
        _console(env)
        busy = {provision.CONSOLE_PORT + 1, provision.CONSOLE_PORT + 2}
        plan = provision.plan(env.profiles, login="user2", exclude="two",
                              probe=lambda port: port in busy)
        assert plan.port == provision.CONSOLE_PORT + 3, plan


def test_provision_writes_both_halves_and_leaves_the_rest_alone() -> None:
    with _Env() as env:
        _console(env)
        env.write("two", {"language": "de", "log_max_lines": 9})
        provision.provision(env.profiles, "two", login="user2", probe=NOTHING)
        own = env.own("two")
        assert own["daemon_port"] == provision.CONSOLE_PORT + 1, own
        assert own["rdp_session"] is True and own["rdp_user"] == "user2", own
        assert own["language"] == "de" and own["log_max_lines"] == 9, own


def test_an_empty_profile_is_seen_as_the_default_profile_s_client() -> None:
    """The bug itself (#1250), stated as a reading rather than as a symptom.

    An empty `config.json` is not «no client» — `load` layers it onto the default
    profile's, so the profile really does drive the default's port. Anything that asks
    «who else is on this client» has to see that, or the answer is «nobody».
    """
    with _Env() as env:
        _console(env)
        for name in ("two", "three", "four"):
            env.write(name, {})
        assert provision.clients(env.profiles)["three"].console
        shared = provision.shared(env.profiles)
        assert list(shared) == [provision.CONSOLE], shared
        assert sorted(shared[provision.CONSOLE]) == ["default", "four", "three", "two"]
        # The default keeps the console; the other three are what a login would separate.
        assert provision.needs_own_client(env.profiles) == ["four", "three", "two"], \
            provision.needs_own_client(env.profiles)


def test_two_sessions_on_one_port_are_repaired_without_asking() -> None:
    """The half that needs nobody: which client each drives does not change."""
    with _Env() as env:
        _console(env)
        port = provision.CONSOLE_PORT + 1
        env.write("two", {"daemon_port": port, "rdp_session": True, "rdp_user": "u2"})
        env.write("three", {"daemon_port": port, "rdp_session": True, "rdp_user": "u3"})
        # The FIRST by `ProfileManager.list`'s order keeps the port — «three» before
        # «two», since that order is the default profile then case-insensitive.
        moved = provision.repair_ports(env.profiles, probe=NOTHING)
        assert moved == [("two", port, port + 1)], moved
        after = provision.clients(env.profiles)
        assert after["three"] == provision.Client("u3", port), after
        assert after["two"] == provision.Client("u2", port + 1), after
        assert not provision.port_clashes(env.profiles)
        # …and it did NOT touch the profiles that share a CLIENT — that needs a login.
        assert not provision.needs_own_client(env.profiles)


def test_repairing_ports_leaves_one_client_shared_alone() -> None:
    """Two profiles on the console are one client whatever ports they name."""
    with _Env() as env:
        _console(env)
        env.write("two", {})
        assert provision.repair_ports(env.profiles, probe=NOTHING) == []
        assert provision.needs_own_client(env.profiles) == ["two"]


def test_a_half_typed_port_reads_as_the_console_rather_than_crashing() -> None:
    with _Env() as env:
        assert provision.client_of({"daemon_port": "  "}) == \
            provision.Client("", provision.CONSOLE_PORT)
        assert provision.client_of({"daemon_port": "47655", "rdp_session": True,
                                    "rdp_user": " u2 "}) == \
            provision.Client("u2", provision.CONSOLE_PORT + 1)
        # A login left behind by a profile put back on the console means nothing.
        assert provision.client_of({"rdp_session": False, "rdp_user": "u2"}).console


def test_running_out_of_ports_names_itself() -> None:
    with _Env() as env:
        _console(env)
        try:
            provision.free_port(env.profiles, probe=lambda port: True)
        except ValueError as exc:
            assert "profile.error.no_port" == getattr(exc.args[0], "key", None), exc
        else:
            raise AssertionError("a port was handed out with everything busy")


def test_the_boot_repairs_what_it_can_and_only_names_the_rest() -> None:
    """`Panel._sort_out_clients`, borrowed off the class — no window, no display.

    It runs before the workspace exists, which is the point: a session reads its port
    while it is being built, and a link built on the wrong one drives the wrong client
    for the rest of the run (#1224). What it may NOT do is ask anything — the hourly
    autostart opens this panel with nobody at the machine.
    """
    import types

    import panel.__main__ as pm
    from panel import runtime

    with _Env() as env:
        _console(env)
        env.write("two", {})                       # …shares the console with default
        port = provision.CONSOLE_PORT + 1
        env.write("aaa", {"daemon_port": port, "rdp_session": True, "rdp_user": "u3"})
        env.write("bbb", {"daemon_port": port, "rdp_session": True, "rdp_user": "u4"})

        shell = types.SimpleNamespace(
            _boot_profiles=env.profiles,
            _boot_i18n=runtime.Translator("en", persist=False))
        shell._t_boot = types.MethodType(pm.Panel._t_boot, shell)
        notes = pm.Panel._sort_out_clients(shell, env.profiles)

        keys = [key for key, _fmt in notes]
        assert "log.profile.port_moved" in keys, notes
        assert "log.profile.client_shared_boot" in keys, notes
        # The port half really is fixed…
        assert not provision.port_clashes(env.profiles)
        assert provision.clients(env.profiles)["aaa"].user == "u3"
        assert provision.clients(env.profiles)["bbb"].user == "u4"
        # …and the login half is only reported, because it cannot be guessed.
        assert provision.needs_own_client(env.profiles) == ["two"]
        said = dict(notes)["log.profile.client_shared_boot"]
        assert said["names"] == "two" and said["button"], said


# -- the paths nobody types ---------------------------------------------------

def test_a_path_left_in_a_profile_is_not_obeyed() -> None:
    """`MACHINE_KEYS`: the machine answers, whatever the file says.

    This is the live fault it was written for — a profile on this machine carried
    `C:\\Program Files\\LastWar\\LastWarLauncher.exe`, which is not where the game
    installs itself, and «Запустить игру» reported the ordinary «клиент не запущен».
    """
    binder = settingsmod.SettingsBinder(profiles=None, defaults=settingsmod.DEFAULTS)
    binder.values = {"launcher": r"C:\Nowhere\LastWarLauncher.exe",
                     "game_exe": "Something.exe",
                     "log_max_lines": 123}
    for key in settingsmod.MACHINE_KEYS:
        assert binder.opt(key) == settingsmod.DEFAULTS[key], key
    # …and a knob that IS the profile's opinion still is.
    assert binder.opt_int("log_max_lines") == 123


def test_the_machine_reading_says_when_a_path_is_not_there() -> None:
    """A missing launcher is a fault to report, never a box to correct by hand."""
    saved = settingsmod.DEFAULTS["launcher"]
    try:
        settingsmod.DEFAULTS["launcher"] = os.path.join(
            tempfile.gettempdir(), "no-such-launcher-1252.exe")
        value, found = settingsmod.machine_value("launcher")
        assert value.endswith("no-such-launcher-1252.exe") and not found
    finally:
        settingsmod.DEFAULTS["launcher"] = saved
    # `game_exe` is a process NAME, so there is nothing on disk to look for.
    assert settingsmod.machine_value("game_exe")[1] is True


def test_the_shell_does_not_write_a_machine_key_back() -> None:
    """`_collect_settings` skips them, so an old value drops out on the next save.

    Checked over the source rather than by running the shell: building one needs Tk and
    a whole profile, and what is being pinned is a single decision in one loop.
    """
    import ast

    source = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    collect = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_collect_settings")
    names = {getattr(n, "attr", "") for n in ast.walk(collect)}
    assert "MACHINE_KEYS" in names, \
        "_collect_settings writes every knob again — a typed path would come back"


def test_no_settings_row_takes_typing_for_a_port_or_a_path() -> None:
    """«Настройки» shows them; it does not ask for them.

    `_opt_row` is the thing that makes a knob EDITABLE — a box, a spinner or a tick
    bound to the profile. Read over the source, because what is being pinned is which
    keys reach it, and a built page can only be asked what it happens to look like.
    """
    import ast

    source = (_REPO / "panel" / "tabs" / "settings.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    typed = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", "") != "_opt_row":
            continue
        for arg in ast.walk(node):
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                typed.add(arg.value)
    forbidden = (settingsmod.MACHINE_KEYS | {"daemon_port"}) & typed
    assert not forbidden, f"still a box to type into: {sorted(forbidden)}"
    # …and the tick that DOES stay is the one thing a person answers about the client.
    assert "rdp_session" in typed and "rdp_user" in typed


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
