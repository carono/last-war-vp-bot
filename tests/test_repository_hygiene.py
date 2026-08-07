r"""What may be IN this repository, by shape — task #1234.

This is what is left of `tests/test_no_hardcoded_values.py` after it was deleted for
carrying a list of real nicknames, logins and account ids in order to ban them. These
six checks never needed that list: **not one concrete value appears in this file**, only
extensions, paths, variable names and shapes. That is the property to keep — if a change
here needs somebody's nickname, uid, login or server number to work, it belongs somewhere
else, or nowhere.

The rule itself lives in `CLAUDE.md`, «Not one identifier of a real account is written
down». This file only stops the accidents that a person cannot see in a diff.

Chief among them: **a screenshot.** A `.png` shows up in `git diff` as `Bin 41k` and in a
review as nothing at all, while carrying a nickname, an alliance tag, a map coordinate,
or a Windows taskbar with a login on it. Take as many as you like — behind `.gitignore`,
where they belong. None of them ever reaches a commit.

Run:
    C:\Python312\python.exe tests\test_repository_hygiene.py
    python3 tests/test_repository_hygiene.py
"""
from __future__ import annotations

import os
import pathlib
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "lib"))

import repo_git             # noqa: E402 — a bare name, reachable only once the path is set


def _git(*args: str) -> str:
    """Ask git, from either side of the WSL boundary — see `tools/lib/repo_git.py`.

    Three of the six checks in this file shell out to `git`, and all three USED to fail
    inside a worktree created from WSL: its `.git` file names a `/mnt/…` path that the
    Windows interpreter running the tests cannot resolve, so «a worktree per agent»
    looked broken when it was not (#1282). The helper resolves the git directory itself
    and spells it for whichever platform is asking.
    """
    return repo_git.out(_REPO, *args)


def _tracked() -> list[str]:
    return [f for f in _git("ls-files").split("\n") if f]


def _read(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------------
# 1. Nothing but text is committed.

#: What this repository is made of: text somebody wrote. An ALLOW-list, and that is the
#: whole design — a list of BANNED extensions only ever holds the five or six people
#: remember (`.png`, `.jpg`, …), while the next thing to arrive is a `.webp`, a `.psd`,
#: a `.pcapng`, a browser trace `.zip` or a screen recording, and it walks in because
#: nobody thought of it. Here, anything unlisted fails: an unfamiliar suffix is a
#: question for a person, not a default yes.
SOURCE_SUFFIXES = {".py", ".md", ".json", ".bat", ".cmd", ".ps1", ".sh", ".txt", ".lua",
                   ".toml", ".js", ".html", ".css", ".yml", ".yaml", ".cfg", ".ini",
                   ".example"}

#: …and the few files a repository carries that have no suffix at all.
SOURCE_NAMES = {"LICENSE", ".gitignore", ".gitattributes"}


def test_nothing_but_text_is_tracked() -> None:
    """No image, capture, recording or database is committed — ever, for any reason.

    A screenshot is the leak nobody reviews. It is not read, it is not searchable, it
    does not appear in a diff as anything but a size in kilobytes — and it carries
    whatever was on the screen when it was taken, which in this project is a running
    game client with real people in it.

    There is no legitimate exception. Development material, template crops, «just for
    the README» — all of it lives behind `.gitignore` and stays on the disk of whoever
    made it.
    """
    offenders = [
        rel for rel in _tracked()
        if pathlib.Path(rel).suffix.lower() not in SOURCE_SUFFIXES
        and pathlib.Path(rel).name not in SOURCE_NAMES
    ]
    assert not offenders, (
        f"tracked, and not text: {offenders[:5]}. Put it behind .gitignore — a "
        f"screenshot, a capture or any binary belongs on the disk that made it, never "
        f"in a public repository. If this really is source, add its suffix to "
        f"SOURCE_SUFFIXES so that the decision is written down rather than assumed."
    )


# --------------------------------------------------------------------------------
# 2 & 3. What is NOT committed stays that way — from both directions.

#: Directories that hold live data from a real account on the machine that plays: chat
#: logs with real senders in them, captures, per-profile settings, throwaway probes.
#: Each is git-ignored, and that ignore is the ONLY thing between them and the public
#: repository — the files are genuinely there in the working tree while the bot runs.
#: An ignore rule is one hand-edited line, so it gets a test under it.
PRIVATE_TREES = [
    ("profiles", "chat logs, per-account settings, session state — ALL of it (#1276)"),
    # Where the same data was until #1276. A checkout that has not been started since
    # the move still has it sitting there, so the ignore has to cover both.
    ("panel/profiles", "the pre-#1276 location of the same per-account data"),
    ("results", "captures, traces and scans recorded off a live account"),
    ("screenshots", "pictures of a running client, i.e. of somebody's screen"),
    ("tools/scratch", "throwaway probes from RE sessions"),
    ("tools/archive", "superseded probes, each written against one machine"),
]


def test_the_trees_that_hold_live_data_stay_ignored() -> None:
    """The private directories are ignored — checked, not assumed.

    A near miss is why this exists: a chat log with two real people's names, uids and
    alliance in it was sitting in the working tree, ignored and never at risk — but
    nothing verified the ignore, and every other check reads only TRACKED files, so all
    of them would have gone on reporting «clean» right up to the moment the rule was
    edited away.
    """
    for path, what in PRIVATE_TREES:
        if not (_REPO / path).exists():
            continue        # not every machine has run every part of the bot
        ignored = repo_git.run(_REPO, "check-ignore", "-q", path, check=False).returncode
        # 0 «ignored», 1 «not ignored», anything else «git could not answer» — and the
        # third must not be read as the second. That is what this check did inside a
        # worktree: git returned 128 and the assertion reported a leak that was not
        # there (#1282).
        assert ignored in (0, 1), (
            f"git could not say whether {path}/ is ignored (exit {ignored}) — the "
            f"check did not run, which is not the same as passing."
        )
        assert ignored == 0, (
            f"{path}/ is NOT git-ignored, and it holds {what}. One `git add -A` "
            f"publishes it."
        )


def test_nothing_untracked_is_waiting_to_be_committed_by_accident() -> None:
    """The complement of the check above: a recording can also land OUTSIDE a private
    tree, where no ignore rule covers it — and then `git add -A` sweeps it up.

    Same allow-list as :func:`test_nothing_but_text_is_tracked`, deliberately: a list of
    known-bad suffixes would go quiet the moment `.gitignore` grew rules for all of them
    — which is exactly what happened to the first draft of this check, and a vacuous
    test reports «clean» in the same words as a working one. Asking «is this text?»
    instead keeps it alive for the suffix nobody has met yet.
    """
    stray = [l[3:] for l in _git("status", "--porcelain", "--untracked-files=all").split("\n")
             if l.startswith("??")]
    data = [f for f in stray
            if pathlib.Path(f).suffix.lower() not in SOURCE_SUFFIXES
            and pathlib.Path(f).name not in SOURCE_NAMES]
    assert not data, (
        f"untracked, unignored and not text: {data[:5]}. Either it belongs in a private "
        f"tree, or .gitignore is missing a rule for wherever it is being written — one "
        f"`git add -A` is all it takes."
    )


# --------------------------------------------------------------------------------
# 4-6. Three values that must be ASKED rather than known. Each check names the knob,
#      never an answer — a real port, login or install path would be the very thing the
#      deleted guard was deleted for.


def test_the_capture_tools_ask_rather_than_pin_the_port() -> None:
    """A capture filtered on a port that has moved does not fail — it goes quiet.

    That is what makes this worth a test: the tools report an empty capture, which reads
    exactly like «nothing is happening in the game», and the person goes looking for the
    wrong bug. So the port comes from the environment, falls back to a default, and
    survives nonsense instead of crashing a capture that would otherwise have worked.

    The value used below is invented — the check is that the knob MOVES, not what any
    particular server answers on.
    """
    import game_paths as gp  # noqa: PLC0415

    moved = str(gp.DEFAULT_GAME_PORT + 1)
    old = os.environ.get("LW_GAME_PORT")
    try:
        os.environ["LW_GAME_PORT"] = moved
        assert gp.game_port() == int(moved), "LW_GAME_PORT does not move the port"
        os.environ["LW_GAME_PORT"] = "not-a-port"
        assert gp.game_port() == gp.DEFAULT_GAME_PORT, \
            "nonsense in the variable must fall back, not crash a capture"
        del os.environ["LW_GAME_PORT"]
        assert gp.game_port() == gp.DEFAULT_GAME_PORT
    finally:
        os.environ.pop("LW_GAME_PORT", None)
        if old is not None:
            os.environ["LW_GAME_PORT"] = old


def test_the_installer_puts_python_where_it_is_told() -> None:
    """The interpreter location is the installer's DEFAULT, never its decision.

    Checked by knob name rather than by path: `install.bat` offers `--pydir` and honours
    `LW_PY_DIR`, and every launcher finds the interpreter through the same two variables
    instead of assuming where the installer usually puts it.
    """
    bat = _read("install.bat")
    assert "--pydir" in bat, "the installer offers no way to choose the location"
    assert "if not defined LW_PY_DIR" in bat, \
        "the installer's default is not an overridable one"
    for rel in ("panel.bat", "daemon.bat", "update.bat", "tools/start_instance.cmd"):
        text = _read(rel)
        assert "LW_WIN_PYTHON" in text and "LW_PY_DIR" in text, \
            f"{rel} cannot find a Python installed anywhere but the default"


def test_the_second_client_asks_which_account_rather_than_guessing() -> None:
    """A Windows account has no sensible default, so the tool asks for one.

    It used to name a login, and on anybody else's machine that is worse than an error:
    the tool goes looking for a session that cannot exist and reports the ordinary «not
    running», so the person has no way to tell «misconfigured» from «not started».

    The registry that ships is empty for the same reason — an account is registered by
    whoever has it, not shipped by whoever wrote the tool.
    """
    text = _read("tools/rdp_instance.py")
    assert "LW_SECOND_USER" in text, "the account has to come from somewhere"
    assert "DEFAULT_USER = (os.environ" in text, "DEFAULT_USER is a literal again"

    import instance_manager  # noqa: PLC0415

    users = [i.get("user") for i in instance_manager.DEFAULT_INSTANCES]
    assert users == [""], "the built-in registry names an account — register it instead"


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
