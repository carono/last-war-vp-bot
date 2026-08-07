r"""Asking `git` about this checkout — from either side of the WSL boundary (#1282).

A worktree per agent is the cure for a shared index, and one small thing blocked it:
`git worktree add` run from WSL writes an absolute POSIX path into the worktree's `.git`
file —

    gitdir: /mnt/p/<the repository>/.git/worktrees/<name>

— and the Windows interpreter that runs the tests cannot resolve it:

    fatal: not a git repository: /mnt/p/…/.git/worktrees/<name>

So every check that shells out to `git` FAILS inside a worktree while passing in the main
tree, which makes «give each agent its own worktree» look broken when it is not. Worse,
one of them failed silently: `git check-ignore` returning 128 is not 0, and a check that
reads «is this ignored?» as «no» reports a leak that is not there — or, when the private
trees do not exist in a fresh worktree, reports nothing at all.

This module is the one place that knows the translation. `run()` finds the real git
directory, converts the path to whichever platform is asking, and passes it explicitly,
so a caller gets the same answer from `/mnt/p/…` and from `P:\…` alike.

It knows no path of its own: every value it uses comes from the checkout it is sitting
in, so there is nothing here that is true of one machine.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

#: `/mnt/p/…` — how WSL spells a Windows drive.
_WSL_MOUNT = re.compile(r"^/mnt/([a-zA-Z])(/.*)?$")
#: `P:\…` / `P:/…` — how Windows spells the same drive.
_WIN_DRIVE = re.compile(r"^([a-zA-Z]):[\\/](.*)$")


def to_this_platform(path: str) -> str:
    """A path written by the OTHER side of the WSL boundary, spelled for this one.

    Only the drive-mount form travels: `/mnt/p/x` ⇄ `P:\\x`. Anything else — a POSIX
    path under `/home`, a UNC path, a relative one — is handed back untouched, because
    it either already works or has no equivalent to translate to.
    """
    if os.name == "nt":
        m = _WSL_MOUNT.match(path)
        if m:
            drive, rest = m.group(1).upper(), (m.group(2) or "/")
            return f"{drive}:{rest}".replace("/", "\\")
        return path
    m = _WIN_DRIVE.match(path)
    if m:
        return "/mnt/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")
    return path


def git_dir(repo: Path | str) -> str | None:
    """The `--git-dir` this checkout needs, or `None` when plain `git` will do.

    A `.git` DIRECTORY is an ordinary clone and needs nothing. A `.git` FILE is a
    worktree (or a submodule), and its one line names a directory that may have been
    written from the other side of the boundary.
    """
    dot = Path(repo) / ".git"
    if dot.is_dir():
        return None
    try:
        line = dot.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    return to_this_platform(line.split(":", 1)[1].strip())


def args_for(repo: Path | str) -> list[str]:
    """`["git", …]` with whatever this checkout needs in front of the sub-command."""
    gd = git_dir(repo)
    if gd is None:
        return ["git"]
    return ["git", f"--git-dir={gd}", f"--work-tree={repo}"]


def run(repo: Path | str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run one `git` sub-command against `repo`, worktree or not.

    `check=False` is for the commands whose EXIT CODE is the answer — `check-ignore`
    says «yes» with 0 and «no» with 1. Those callers must still tell a 1 from a 128:
    a git that could not open the repository at all answers 128, and reading that as
    «not ignored» is how a check goes quietly wrong inside a worktree.
    """
    return subprocess.run([*args_for(repo), *args], cwd=str(repo),
                          capture_output=True, text=True, check=check)


def out(repo: Path | str, *args: str) -> str:
    """The stdout of a `git` sub-command, raising when it failed."""
    return run(repo, *args).stdout
