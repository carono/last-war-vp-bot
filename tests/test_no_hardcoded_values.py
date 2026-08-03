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

#: A quoted value, in Python or JSON alike.
def _quoted(value: str) -> re.Pattern:
    return re.compile(r"""["']""" + re.escape(value) + r"""["']""")


def _tracked(*globs: str) -> list[str]:
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
        for rel in _tracked("*.py", "*.bat", "*.json"):
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


def test_no_personal_login_is_shipped():
    """No Windows account name from any one developer's machine, anywhere.

    A login is the most personal of these values and the least visible: it reads as a
    perfectly ordinary identifier right up until somebody else runs the code. So the
    check is on the whole line, quoted or not — including comments, which is where the
    last ones were hiding.
    """
    personal = re.compile(r"\b(casper|spame)\b", re.IGNORECASE)
    for rel in _tracked("*.py", "*.bat", "*.json", "*.cmd", "*.ps1"):
        for i, line in enumerate(_read(rel).splitlines(), 1):
            hit = personal.search(line)
            assert not hit, (
                f"{rel}:{i} names {hit.group(0)!r} — a Windows account that exists on "
                f"exactly one machine. Use a placeholder, or ask for it."
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
