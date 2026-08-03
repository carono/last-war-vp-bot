r"""Where the game is, and who gets to say so (task #1218 follow-up).

Every path the launch touches used to be a literal, and the same literal appeared in
several files that had already drifted apart — the panel's «launcher» default said
`C:\Program Files\LastWar` while the shell three hundred lines away said
`%LOCALAPPDATA%\FunFly\Last War-Survival Game`. Someone whose game is on another drive
had no way to say so except a source change.

What this pins:

  * an environment variable moves the answer, and an unset (or empty) one changes
    nothing — a machine that sets none behaves exactly as the literals used to;
  * an ABSOLUTE launcher travels to another account's session and a per-user one does
    not, which is the whole distinction the RDP launch turns on;
  * every module in the launch path asks THIS resolver, so they cannot disagree again.

    C:\Python312\python.exe tests\test_game_paths.py
    python3 tests/test_game_paths.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "tools" / "lib", _REPO / "src", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_paths as gp  # noqa: E402


class _env:
    """Set (or clear) environment variables for the length of a block."""

    def __init__(self, **values) -> None:
        self._want = values
        self._saved: dict = {}

    def __enter__(self):
        for key, value in self._want.items():
            self._saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, old in self._saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        return False


_CLEAR = dict(LW_LAUNCHER=None, LW_GAME_DIR=None, LW_GAME_FOLDER=None,
              LW_LAUNCHER_EXE=None, LW_GAME_EXE=None, LW_WIN_PYTHON=None)


def test_the_defaults_are_the_literals_that_used_to_be_scattered():
    with _env(**_CLEAR):
        assert gp.game_folder() == os.path.join("FunFly", "Last War-Survival Game")
        assert gp.launcher_exe() == "LastWarLauncher.exe"
        assert gp.game_exe() == "LastWar.exe"
        assert gp.win_python() == r"C:\Python312\python.exe"
        assert gp.game_dir() == os.path.join(gp.local_appdata(), gp.game_folder())
        assert gp.launcher() == os.path.join(gp.game_dir(), "LastWarLauncher.exe")


def test_an_empty_variable_is_not_an_answer():
    """A variable set to "" (or spaces) is a knob somebody cleared, not a path.

    Obeyed literally it would resolve the launcher to a bare filename and the client's
    process name to nothing — which matches every process or none.
    """
    with _env(**{**_CLEAR, "LW_LAUNCHER": "", "LW_GAME_EXE": "   "}):
        assert gp.game_exe() == "LastWar.exe"
        assert gp.launcher().endswith("LastWarLauncher.exe")
        # Absolute only where the fallback can be: `~\AppData\Local` is a Windows
        # path and expanduser leaves it alone elsewhere, which is fine — nothing but
        # Windows ever launches the game.
        if os.name == "nt":
            assert os.path.isabs(gp.launcher())


def test_each_knob_moves_exactly_what_it_names():
    with _env(**{**_CLEAR, "LW_GAME_EXE": "Other.exe"}):
        assert gp.game_exe() == "Other.exe"
    with _env(**{**_CLEAR, "LW_LAUNCHER_EXE": "Start.exe"}):
        assert gp.launcher().endswith("Start.exe")
    with _env(**{**_CLEAR, "LW_GAME_DIR": os.path.join("D:", os.sep, "Games", "LW")}):
        assert gp.game_dir() == os.path.join("D:", os.sep, "Games", "LW")
        assert gp.launcher() == os.path.join("D:", os.sep, "Games", "LW",
                                             "LastWarLauncher.exe")
    with _env(**{**_CLEAR, "LW_WIN_PYTHON": r"D:\py\python.exe"}):
        assert gp.win_python() == r"D:\py\python.exe"


def test_the_launcher_variable_wins_outright():
    forced = os.path.join("D:", os.sep, "Games", "LW", "Boot.exe")
    with _env(**{**_CLEAR, "LW_GAME_DIR": "C:\\ignored", "LW_LAUNCHER": forced}):
        assert gp.launcher() == forced


def test_another_accounts_copy_is_named_relative_to_ITS_profile():
    """`%LOCALAPPDATA%` is per user, so the other session's install is built from the
    profile directory SYSTEM looked up — never from ours."""
    profile = os.path.join("C:", os.sep, "Users", "casper")
    with _env(**_CLEAR):
        assert gp.launcher_in_profile(profile) == os.path.join(
            profile, "AppData", "Local", "FunFly", "Last War-Survival Game",
            "LastWarLauncher.exe")
    # …and a renamed vendor folder follows into that account too.
    with _env(**{**_CLEAR, "LW_GAME_FOLDER": os.path.join("Acme", "LW")}):
        assert gp.launcher_in_profile(profile) == os.path.join(
            profile, "AppData", "Local", "Acme", "LW", "LastWarLauncher.exe")


def test_another_accounts_launcher_is_never_read_out_of_OUR_environment():
    """`launcher_in_profile` answers for an account that is not this process's.

    So it must ignore `LW_LAUNCHER` entirely, whatever it says. The variable is read
    where a usable environment exists — in the panel, which passes the string down
    verbatim — and never here: this function's callers run as SYSTEM, whose copy of
    that variable is nobody's game. An earlier version let it win and made the
    resolver's answer depend on who happened to be running it.
    """
    profile = os.path.join("C:", os.sep, "Users", "casper")
    plain = gp.launcher_in_profile(profile)
    for value in (os.path.join("D:", os.sep, "Games", "LW", "LastWarLauncher.exe"),
                  r"%LOCALAPPDATA%\LW\LastWarLauncher.exe"):
        with _env(**{**_CLEAR, "LW_LAUNCHER": value}):
            assert gp.launcher_in_profile(profile) == plain
    assert plain.startswith(profile), plain


def test_a_variable_is_expanded_against_the_TARGET_sessions_environment():
    """The whole point of the correction, and it cannot be done anywhere else.

    `session_launch.expand_for` is handed the environment block `CreateEnvironmentBlock`
    built from the target account's token — the one place on the machine where that
    account's `%LOCALAPPDATA%` is correct. Expanding in the caller (a panel running as
    somebody else, or the SYSTEM task that carries the request) names the wrong profile
    and starts nothing.

    Imported by source rather than as a module: `tools/session_launch.py` needs pywin32
    and exits at import off Windows, while this function is pure text handling.
    """
    import types

    src = (_REPO / "tools" / "session_launch.py").read_text(encoding="utf-8")
    body = src[src.index("def expand_for("):src.index("def game_launcher(")]
    mod = types.ModuleType("_expand_probe")
    exec(compile("import re\n" + body, "session_launch", "exec"), mod.__dict__)
    expand_for = mod.expand_for

    casper = {"LOCALAPPDATA": r"C:\Users\casper\AppData\Local",
              "USERPROFILE": r"C:\Users\casper"}
    assert expand_for(r"%LOCALAPPDATA%\Acme\Custom.exe", casper) == \
        r"C:\Users\casper\AppData\Local\Acme\Custom.exe"
    # Case-insensitive, as Windows is.
    assert expand_for(r"%localappdata%\x.exe", casper) == \
        r"C:\Users\casper\AppData\Local\x.exe"
    # An absolute path is untouched, so the ordinary case pays nothing.
    assert expand_for(r"D:\Games\LW\Boot.exe", casper) == r"D:\Games\LW\Boot.exe"
    # An unknown name is LEFT STANDING: a path with %TYPO% in it is a mistake somebody
    # can read, one silently missing a segment is not.
    assert expand_for(r"%NOPE%\x.exe", casper) == r"%NOPE%\x.exe"
    assert expand_for("", casper) == ""


def test_the_launch_path_asks_this_one_and_not_a_copy():
    """The drift that started it: four modules, four opinions, one of them wrong."""
    with _env(**_CLEAR):
        import game_client
        assert game_client.GAME_EXE == gp.game_exe()
        assert game_client.default_launcher() == gp.launcher()

        try:                              # the WSL python3 has no tkinter
            from panel.runtime import game_process
            from panel.runtime import settings as settingsmod
        except Exception:                 # noqa: BLE001
            return
        assert settingsmod.DEFAULTS["game_exe"] == gp.game_exe()
        assert settingsmod.DEFAULTS["launcher"] == gp.launcher()
        assert settingsmod.GAME_DIR == gp.game_dir()
        assert game_process.GAME_EXE == gp.game_exe()


def test_no_module_spells_the_install_out_for_itself():
    """A literal anywhere is a fifth opinion waiting to disagree with the other four.

    Read as text rather than imported, because `tools/session_launch.py` is Windows-only
    (it exits at import elsewhere) and is exactly one of the files that used to carry
    the folder — it builds the OTHER account's path, which no environment can express.
    """
    watched = ["tools/session_launch.py", "tools/lib/game_client.py",
               "panel/runtime/settings.py", "panel/runtime/game_process.py",
               "panel/__main__.py", "src/lastwar_bot/actions/launch_game.md"]
    # QUOTED occurrences only — a literal in quotes is a value being used to build a
    # path, which is the thing that must not come back. The same words in a comment
    # are prose explaining why the launcher is not the client, and are worth keeping.
    import re
    spelled = re.compile(r"""["'](FunFly|LastWarLauncher\.exe)["']""")
    for rel in watched:
        found = spelled.search((_REPO / rel).read_text(encoding="utf-8"))
        assert not found, f"{rel} spells out {found.group(1)!r} again"

    # The interpreter is the same story with one wrinkle: several of these files name
    # it in a "run it like this" line, which is documentation and must stay readable.
    # What may not come back is a second place that DECIDES it, so the check is on
    # assignment rather than on the string.
    assigns = re.compile(r"=\s*r?[\"']C:\\+Python312")
    for rel in [*watched, "tools/rdp_instance.py"]:
        text = (_REPO / rel).read_text(encoding="utf-8")
        assert not assigns.search(text), f"{rel} decides the interpreter for itself"
    assert gp.DEFAULT_WIN_PYTHON == r"C:\Python312\python.exe", \
        "…and this is the one place that does"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
