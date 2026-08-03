r"""Nothing about THIS machine is written into the code — task #1220.

The repository is public and gets installed on other people's computers. Everything
that is true of one machine and not another — where the game is installed, what its
window and its process are called, which Windows account a second client runs as,
where the Python that drives it lives — is a question with one answer per machine, so
it belongs to `tools/lib/game_paths.py` (and, for the account-shaped ones, to an
environment variable or a registry file) and to nowhere else.

The rule this file enforces is in `CLAUDE.md`. Two things make it enforceable rather
than merely written down:

* **Quoted occurrences only.** A literal in quotes is a value being *used* — building
  a path, filtering a process list, matching a window. The same words in a comment or
  a docstring are prose explaining why the launcher is not the client, and prose is
  worth keeping. So the check is on `"FunFly"`, never on the word FunFly.
* **One place is allowed to spell each value out**, and the test names it. That is the
  point of a resolver: the literal still exists, exactly once, with an environment
  variable in front of it.

Run:
    C:\Python312\python.exe tests\test_no_hardcoded_values.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "lib"))

import game_paths as gp  # noqa: E402


# `tools/archive/` and `tools/scratch/` are kept experiments, not shipped code — they
# name a client that was running on the day they were written and are not run again.
# `docs/` is prose by definition. `tests/` writes literals on purpose: it is what a
# test asserts against.
SKIP_PREFIXES = ("tools/archive/", "tools/scratch/", "docs/", "tests/")

#: Where each value is allowed to be spelled out — the resolver, plus the files that
#: legitimately show it to a person rather than use it.
ALLOWED = {
    "FunFly": {"tools/lib/game_paths.py"},
    "LastWarLauncher.exe": {
        "tools/lib/game_paths.py",
        # The panel's settings field shows it greyed out as «what goes here» — a
        # translated hint in every locale, not a path this code builds.
        *(f"panel/locales/{loc}.json" for loc in
          ("en", "ru", "de", "fr", "es", "it", "pt", "pl", "tr", "id", "vi")),
    },
    "LastWar.exe": {"tools/lib/game_paths.py"},
    "Last War-Survival Game": {"tools/lib/game_paths.py"},
}

#: Every kind of file that can hold a decision. **The list matters more than it looks:**
#: the first cut of this test read `.py`, `.bat` and `.json`, and `tools/start_instance.cmd`
#: sat outside it with the interpreter, the install path and the port all written out.
#: A guard that covers most of the tree reads exactly like one that covers all of it.
SOURCE_GLOBS = ("*.py", "*.bat", "*.cmd", "*.ps1", "*.json", "*.sh")


def _quoted(value: str) -> re.Pattern:
    """A quoted value, in Python or JSON alike — and in EITHER case.

    Case-insensitively on purpose: `GAME_PROCESS = "lastwar.exe"` in the capture tools
    is the same decision as `"LastWar.exe"` anywhere else, and a case-sensitive first
    cut of this test walked straight past two of them.
    """
    return re.compile(r"""["']""" + re.escape(value) + r"""["']""", re.IGNORECASE)


def _tracked(*globs: str) -> list[str]:
    globs = globs or SOURCE_GLOBS
    out = subprocess.run(["git", "ls-files", *globs], cwd=_REPO,
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f and not f.startswith(SKIP_PREFIXES)]


def _read(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------------


def test_where_the_game_is_installed_is_spelled_out_once():
    """The publisher folder, the launcher and the client, each in one file only."""
    for value, allowed in ALLOWED.items():
        pat = _quoted(value)
        for rel in _tracked():
            if rel in allowed:
                continue
            hit = pat.search(_read(rel))
            assert not hit, (
                f"{rel} spells out {value!r}. Ask tools/lib/game_paths.py instead — "
                f"that is the one place a machine can answer differently."
            )


def test_the_resolver_still_answers_all_of_them():
    """…and «spelled out once» means the answers are still there to be had."""
    assert gp.game_folder().startswith("FunFly")
    assert gp.launcher_exe() == "LastWarLauncher.exe"
    assert gp.game_exe() == "LastWar.exe"
    assert gp.window_title() == "Last War-Survival Game"


def test_every_knob_moves_exactly_what_it_names():
    """A machine that is not ordinary changes one variable and nothing else."""
    cases = [
        ("LW_WINDOW_TITLE", "Another Window", gp.window_title),
        ("LW_LOCALLOW", os.path.join("Z:", os.sep, "low"), gp.local_low),
        ("LW_GAME_DATA_DIR", os.path.join("Z:", os.sep, "data"), gp.data_dir),
        ("LW_CHAT_PHOTOS", os.path.join("Z:", os.sep, "pics"), gp.chat_photos_dir),
        ("LW_GAMERES", os.path.join("Z:", os.sep, "gameres"), gp.gameres),
        ("LW_ASSET_CACHE", os.path.join("Z:", os.sep, "cache"), gp.asset_cache),
        ("LW_WIRESHARK_DIR", os.path.join("Z:", os.sep, "ws"),
         lambda: gp.wireshark_dirs()[0]),
    ]
    for name, value, read in cases:
        old = os.environ.get(name)
        os.environ[name] = value
        try:
            assert read() == value, f"{name} did not move {read.__name__}()"
        finally:
            os.environ.pop(name, None)
            if old is not None:
                os.environ[name] = old


def test_an_empty_variable_is_not_an_answer():
    """Set-but-empty is how a shell passes «unset»; it must not blank a path."""
    for name in ("LW_WINDOW_TITLE", "LW_GAMERES", "LW_CHAT_PHOTOS"):
        old = os.environ.get(name)
        os.environ[name] = ""
        try:
            assert gp.window_title() and gp.gameres() and gp.chat_photos_dir()
        finally:
            os.environ.pop(name, None)
            if old is not None:
                os.environ[name] = old


def test_the_download_tree_is_not_the_install_tree():
    """LocalLow (what the client downloads) is never Local (what it shipped with).

    Confusing the two is the bug this pair of helpers exists to prevent: chat photos
    live under `persistentDataPath`, the asset bundles under the install.
    """
    for name in ("LW_LOCALLOW", "LW_GAME_DATA_DIR", "LW_GAME_DIR", "LW_CHAT_PHOTOS"):
        os.environ.pop(name, None)
    assert gp.data_dir() != gp.game_dir()
    assert gp.chat_photos_dir().startswith(gp.data_dir())
    assert gp.gameres().startswith(gp.game_dir())


#: Real people, in the two shapes this repository kept collecting them in: Windows
#: logins, and the game identities that got copied out of a live session into a test
#: fixture. Both are personal data in a public repository, and the second kind is not
#: even the author's own — `DeadMorozzz` was another player who happened to be on
#: screen when a capture was recorded.
PERSONAL = re.compile(
    r"\b(casper|spame"                        # Windows logins
    r"|Carono|DeadMorozzz"                    # game nicknames
    r"|TLou"                                  # an alliance tag
    r"|1522777203000972|1371213785000935)\b", # live game uids
    re.IGNORECASE)

#: The repository's own address is not personal data — it is where the project lives,
#: and it has to be the real one for anybody to download it. Any line carrying it is
#: exempt, and nothing else is.
REPO_URL = re.compile(r"github\.com(:\d+)?[/:]carono|carono/last-war-vp-bot")

#: This file names them all in order to ban them, so it is the one that may.
PERSONAL_ALLOWED = {"tests/test_no_hardcoded_values.py"}


def test_no_personal_identity_is_shipped():
    """No real person — a Windows login, a game nickname, an alliance, an account id.

    **Tests are checked too**, and that is the point rather than an afterthought: the
    other assertions here skip `tests/`, because a test writes literals on purpose. But
    a fixture recorded from a live session is not a literal written on purpose — it is
    a real account, and the first cut of this guard skipped the whole directory and so
    walked past a live player's nickname and uid sitting in a committed fixture.

    Whole lines, quoted or not: comments and docstrings are exactly where the last
    Windows logins were hiding.
    """
    everything = subprocess.run(["git", "ls-files", *SOURCE_GLOBS, "*.md"], cwd=_REPO,
                                capture_output=True, text=True,
                                check=True).stdout.split("\n")
    for rel in everything:
        # `docs/` is prose, and prose the author signs: a name under a README is
        # authorship, not a value the code acts on. Everything executable, and every
        # fixture, is in scope.
        if not rel or rel in PERSONAL_ALLOWED or rel.startswith(
                ("tools/archive/", "tools/scratch/", "docs/")):
            continue
        for i, line in enumerate(_read(rel).splitlines(), 1):
            if REPO_URL.search(line):
                continue
            hit = PERSONAL.search(line)
            assert not hit, (
                f"{rel}:{i} names {hit.group(0)!r} — a real person or account. Use a "
                f"placeholder; a fixture recorded live has to be anonymised before it "
                f"is committed."
            )


def test_the_second_client_asks_which_account_rather_than_guessing():
    """`tools/rdp_instance.py` ships no default user, and no default second instance.

    Both used to name one developer's login, so on anybody else's machine the tool
    went looking for a session that could not exist and reported it as «not running».
    """
    text = _read("tools/rdp_instance.py")
    assert "LW_SECOND_USER" in text, "the account has to come from somewhere"
    assert re.search(r"DEFAULT_USER\s*=\s*\(os\.environ", text), \
        "DEFAULT_USER is a literal again"

    sys.path.insert(0, str(_REPO / "tools" / "lib"))
    import instance_manager  # noqa: PLC0415

    users = [i.get("user") for i in instance_manager.DEFAULT_INSTANCES]
    assert users == [""], \
        f"the built-in registry names an account: {users!r} — register it instead"


def test_the_capture_tools_ask_rather_than_pin_the_port():
    """A capture filtered on a port that has moved does not fail — it goes quiet.

    That is why this one is worth a test of its own: `17935` was pinned in two files
    while a live client had connected out on `10012`, and the tools reported an empty
    capture, which reads exactly like «nothing is happening in the game».
    """
    old = os.environ.get("LW_GAME_PORT")
    os.environ["LW_GAME_PORT"] = "10012"
    try:
        assert gp.game_port() == 10012
    finally:
        os.environ.pop("LW_GAME_PORT", None)
        if old is not None:
            os.environ["LW_GAME_PORT"] = old
    assert gp.game_port() == gp.DEFAULT_GAME_PORT
    # Nonsense must not crash a capture that would otherwise have worked.
    os.environ["LW_GAME_PORT"] = "not-a-port"
    try:
        assert gp.game_port() == gp.DEFAULT_GAME_PORT
    finally:
        os.environ.pop("LW_GAME_PORT", None)


def test_the_installer_puts_python_where_it_is_told():
    """`C:\\Python312` is the installer's *default*, not its decision.

    It stays a literal in exactly two places — `install.bat`'s default and the
    resolver's — and both are reachable: `--pydir` on the command line, `LW_PY_DIR`
    in the environment.
    """
    bat = _read("install.bat")
    assert "--pydir" in bat, "the installer offers no way to choose the location"
    assert 'if not defined LW_PY_DIR' in bat, \
        "the installer's default is not an overridable one"
    # …and the launchers find it there rather than assuming the default.
    for rel in ("panel.bat", "daemon.bat", "update.bat", "tools/start_instance.cmd"):
        text = _read(rel)
        assert "LW_WIN_PYTHON" in text and "LW_PY_DIR" in text, \
            f"{rel} cannot find a Python installed anywhere but the default"


def test_the_interpreter_is_decided_in_one_place():
    """Several files SHOW the interpreter in a «run it like this» line, which is
    documentation and stays. What may not come back is a second file that DECIDES it."""
    assigns = re.compile(r"=\s*r?[\"']C:\\+Python312")
    for rel in _tracked("*.py"):
        if rel == "tools/lib/game_paths.py":
            continue
        hit = assigns.search(_read(rel))
        assert not hit, f"{rel} decides the interpreter for itself"
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
