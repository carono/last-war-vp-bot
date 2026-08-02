"""Is this working copy behind origin, and moving it forward.

The panel is run from a git checkout — there is no installer and no release channel, so
"обновить бота" means `git pull` in the repo the panel is imported from. Until now that
was a terminal the operator had to remember to open, which is why a box could sit weeks
behind `origin` with nobody noticing.

Pure subprocess, no Tk: «Главная» draws the answer, this decides what the answer is
(the shell is a shell — CLAUDE.md). It is also deliberately dumb about the UI's timing:
every call here is blocking and belongs on a worker thread.

**Nothing here ever prompts.** A `git fetch` over SSH against a host whose key is not
known, or over HTTPS without a credential helper, will happily sit waiting on a terminal
that a windowed panel does not have — so the environment silences every prompt git owns
(:data:`_ENV`) and every call carries a timeout. A checkout that cannot reach `origin`
reports :data:`OFFLINE` and the panel stays usable.

**Nothing here ever loses work.** The only way forward is a fast-forward:

* uncommitted changes to *tracked* files → :data:`DIRTY`, no pull offered;
* local commits `origin` has not got → :data:`AHEAD` / :data:`DIVERGED`, no pull offered;
* a pull is `fetch` + `merge --ff-only`, which cannot make a merge commit, cannot open
  an editor and cannot leave a conflicted index behind. It either moves the branch or
  refuses.

Untracked files are NOT dirt: the repo grows `results/`, captures and scratch files
during any normal session, none of which a fast-forward touches. The one case where an
untracked file does block a merge — it is in the way of a file the update adds — is
git's to refuse, and it comes back as :data:`FAIL_OVERWRITE` with the names in `detail`.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

from .paths import REPO

#: How long any local git call may take. Generous: a `status` on a cold cache over a
#: 9p-mounted Windows drive is slow the first time and instant afterwards.
LOCAL_TIMEOUT = 20.0

#: How long a `fetch` may take before the network counts as absent. A checkout with no
#: route to github hangs on the TCP connect, not on git.
FETCH_TIMEOUT = 45.0

# -- what `check` can conclude ------------------------------------------------
CURRENT = "current"          #: level with the upstream branch
BEHIND = "behind"            #: upstream has commits this copy has not — the update case
AHEAD = "ahead"              #: local commits origin has not; nothing to pull
DIVERGED = "diverged"        #: both, from a common ancestor — a merge, not a pull
OFFLINE = "offline"          #: `fetch` failed or timed out; the reading is local-only
NO_UPSTREAM = "no_upstream"  #: the branch tracks nothing
DETACHED = "detached"        #: not on a branch at all
NOT_A_REPO = "not_a_repo"    #: no .git — someone unpacked a zip
NO_GIT = "no_git"            #: git is not on PATH
ERROR = "error"              #: git ran and said something unexpected; see `detail`

# -- what `pull` can conclude -------------------------------------------------
OK = "ok"                          #: fast-forwarded; the panel must be restarted
FAIL_NOTHING = "nothing"           #: already level — nothing was done
FAIL_DIRTY = "dirty"               #: tracked files modified; refused before touching git
FAIL_DIVERGED = "diverged"         #: not a fast-forward; a human has to merge
FAIL_OVERWRITE = "overwrite"       #: local files stand where the update wants to write
FAIL_OFFLINE = "offline"           #: could not fetch, and nothing was fetched earlier
FAIL_ERROR = "error"               #: git refused for some other reason; see `detail`

#: Everything git might ask a human, answered before it asks. `GIT_TERMINAL_PROMPT=0`
#: turns a credential prompt into a failure; the two ASKPASS entries stop git from
#: spawning a helper GUI instead; `BatchMode=yes` does the same for ssh's
#: host-key/passphrase questions, and its own connect timeout keeps a black-holed route
#: from eating the whole budget.
_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
                       "-o ConnectTimeout=10",
    # A pull must never open $EDITOR — `--ff-only` already cannot, but a repo-level
    # `pull.rebase`/`merge.tool` config could still try. `true` exits 0 having done
    # nothing, which git reads as "the message is fine as it is".
    "GIT_EDITOR": "true",
    # Locale-independent output: the failure classifier below reads git's own words.
    "LC_ALL": "C",
    "LANGUAGE": "C",
}


@dataclass(frozen=True)
class UpdateState:
    """What one check found. `state` is one of the constants above."""

    state: str
    branch: str = ""
    local: str = ""              # short hash of HEAD
    remote: str = ""             # short hash of the upstream tip
    upstream: str = ""           # e.g. "origin/v2"
    behind: int = 0              # commits upstream has and this copy has not
    ahead: int = 0               # the other way round
    dirty: bool = False          # tracked files modified — independent of `state`
    detail: str = ""             # git's own words, for the log

    @property
    def can_pull(self) -> bool:
        """Is «Обновить» worth offering? Behind, and nothing of the operator's at risk."""
        return self.state == BEHIND and not self.dirty


@dataclass(frozen=True)
class PullResult:
    """What one pull did. `reason` is :data:`OK` or one of the ``FAIL_*`` constants."""

    reason: str
    state: UpdateState | None = None   # the reading taken after the attempt
    detail: str = ""
    files: tuple = field(default_factory=tuple)   # names git named, when it named any

    @property
    def ok(self) -> bool:
        return self.reason == OK


# -- running git --------------------------------------------------------------
def _git(*args: str, repo: str = REPO, timeout: float = LOCAL_TIMEOUT
         ) -> tuple[int, str, str]:
    """Run one git command in `repo`. Returns ``(rc, stdout, stderr)``, both stripped.

    Never raises: a missing git is ``rc=-1`` and a timeout is ``rc=-2``, because every
    caller here has to say something in the UI either way and none of them can usefully
    tell a `FileNotFoundError` from a non-zero exit.
    """
    env = dict(os.environ)
    env.update(_ENV)
    try:
        proc = subprocess.run(
            ("git", "-C", repo, *args),
            capture_output=True, text=True, timeout=timeout, env=env,
            # Windows: no console window for a panel started with pythonw.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return -1, "", "git not found"
    except subprocess.TimeoutExpired:
        return -2, "", f"timed out after {timeout:.0f}s"
    except OSError as exc:                      # a repo path that has gone away
        return -1, "", str(exc)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _first_line(text: str) -> str:
    """git's complaint in one line — the log gets the gist, not the whole essay."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _named_files(text: str) -> tuple:
    """The file names git listed in a refusal.

    Both messages this matters for ("Your local changes to the following files would be
    overwritten", "The following untracked working tree files would be overwritten")
    print one tab-indented path per line, so the indent is the marker.
    """
    return tuple(line.strip() for line in text.splitlines()
                 if line[:1] in ("\t", " ") and line.strip()
                 and not line.strip().startswith("Please "))


# -- the readings --------------------------------------------------------------
def is_repo(repo: str = REPO) -> bool:
    """Is `repo` a git working tree at all?"""
    rc, out, _err = _git("rev-parse", "--is-inside-work-tree", repo=repo)
    return rc == 0 and out == "true"


def head(repo: str = REPO) -> str:
    """The short hash of HEAD, or ``""`` when there is nothing to read.

    The one thing worth showing even when everything else failed: it is what an operator
    reads out when asked "какая у тебя версия".
    """
    rc, out, _err = _git("rev-parse", "--short", "HEAD", repo=repo)
    return out if rc == 0 else ""


def is_dirty(repo: str = REPO) -> bool:
    """Are there uncommitted changes to TRACKED files?

    Untracked files are excluded on purpose — see the module docstring. Staged changes
    count: they are work a fast-forward could strand just as easily as unstaged ones.
    """
    rc, out, _err = _git("status", "--porcelain", "--untracked-files=no", repo=repo)
    return rc == 0 and bool(out)


def _compare(repo: str, branch: str, upstream: str, dirty: bool) -> UpdateState:
    """Count the divergence against an upstream ref that is known to exist."""
    local = head(repo)
    rc, out, err = _git("rev-parse", "--short", upstream, repo=repo)
    remote = out if rc == 0 else ""
    rc, out, err = _git("rev-list", "--left-right", "--count",
                        f"HEAD...{upstream}", repo=repo)
    if rc != 0:
        return UpdateState(ERROR, branch=branch, local=local, remote=remote,
                           upstream=upstream, dirty=dirty, detail=_first_line(err))
    try:
        ahead, behind = (int(n) for n in out.split()[:2])
    except (ValueError, IndexError):
        return UpdateState(ERROR, branch=branch, local=local, remote=remote,
                           upstream=upstream, dirty=dirty,
                           detail=f"unreadable rev-list output: {out!r}")
    if ahead and behind:
        state = DIVERGED
    elif behind:
        state = BEHIND
    elif ahead:
        state = AHEAD
    else:
        state = CURRENT
    return UpdateState(state, branch=branch, local=local, remote=remote,
                       upstream=upstream, behind=behind, ahead=ahead, dirty=dirty)


def check(repo: str = REPO, fetch: bool = True,
          timeout: float = FETCH_TIMEOUT) -> UpdateState:
    """Compare this checkout with its upstream branch. Blocking — call it off the UI thread.

    With `fetch=False` the comparison is against whatever the last fetch left behind,
    which is what :func:`pull` re-reads after doing its own fetch (and what a test uses
    to stay off the network).

    A failed fetch is :data:`OFFLINE` rather than an error: the local half of the reading
    is still true and worth showing, and "нет связи" is a different thing to tell the
    operator than "git сломался".
    """
    rc, out, err = _git("rev-parse", "--is-inside-work-tree", repo=repo)
    if rc == -1:
        return UpdateState(NO_GIT, detail=_first_line(err))
    if rc != 0 or out != "true":
        return UpdateState(NOT_A_REPO, detail=_first_line(err))

    dirty = is_dirty(repo)
    local = head(repo)

    rc, branch, _err = _git("rev-parse", "--abbrev-ref", "HEAD", repo=repo)
    branch = branch if rc == 0 else ""
    if branch in ("", "HEAD"):
        # Detached: mid-bisect, on a tag, or a checkout of one commit. There is no
        # "next" to pull towards and guessing one would be a fine way to lose a state
        # the operator put themselves in deliberately.
        return UpdateState(DETACHED, local=local, dirty=dirty)

    rc, upstream, err = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name",
                             "@{u}", repo=repo)
    if rc != 0 or not upstream:
        return UpdateState(NO_UPSTREAM, branch=branch, local=local, dirty=dirty,
                           detail=_first_line(err))

    if fetch:
        # Fetch the one branch that matters, not every ref the remote has: a full fetch
        # on this repo pulls tags and every other branch for a question about one.
        remote = upstream.split("/", 1)[0]
        rc, _out, err = _git("fetch", "--quiet", remote, branch,
                             repo=repo, timeout=timeout)
        if rc != 0:
            state = _compare(repo, branch, upstream, dirty)
            # Keep whatever the stale tracking ref knows — it may already be behind from
            # an earlier fetch — but say plainly that this reading is not fresh.
            return UpdateState(OFFLINE, branch=branch, local=local, remote=state.remote,
                               upstream=upstream, behind=state.behind, ahead=state.ahead,
                               dirty=dirty, detail=_first_line(err) or "fetch failed")

    return _compare(repo, branch, upstream, dirty)


# -- moving forward ------------------------------------------------------------
def pull(repo: str = REPO, timeout: float = FETCH_TIMEOUT) -> PullResult:
    """Fast-forward the checkout to its upstream. Blocking — call it off the UI thread.

    Refuses before touching anything when the tree is dirty or the branch has diverged,
    so the failure modes that matter never get as far as git. The merge itself is
    `--ff-only`: on success the working tree is exactly the upstream commit and the
    panel is running code that no longer matches the files on disk — hence
    :data:`OK` meaning "restart me", not "done".
    """
    before = check(repo, fetch=False)
    if before.state in (NO_GIT, NOT_A_REPO, DETACHED, NO_UPSTREAM, ERROR):
        return PullResult(FAIL_ERROR, state=before, detail=before.detail or before.state)
    if before.dirty:
        # Deliberately before the fetch: a dirty tree is the operator's own work and
        # nothing about the network changes the answer.
        return PullResult(FAIL_DIRTY, state=before)

    remote = before.upstream.split("/", 1)[0]
    rc, _out, err = _git("fetch", "--quiet", remote, before.branch,
                         repo=repo, timeout=timeout)
    fetch_err = _first_line(err) if rc != 0 else ""

    now = check(repo, fetch=False)
    if now.state == CURRENT:
        # Nothing to do. If the fetch failed we cannot honestly claim that — the tracking
        # ref we just read may be days old.
        return (PullResult(FAIL_OFFLINE, state=now, detail=fetch_err) if fetch_err
                else PullResult(FAIL_NOTHING, state=now))
    if now.state in (AHEAD, DIVERGED):
        return PullResult(FAIL_DIVERGED, state=now, detail=fetch_err)
    if now.state != BEHIND:
        return PullResult(FAIL_OFFLINE if fetch_err else FAIL_ERROR, state=now,
                          detail=fetch_err or now.detail or now.state)

    rc, out, err = _git("merge", "--ff-only", now.upstream, repo=repo)
    after = check(repo, fetch=False)
    if rc == 0:
        return PullResult(OK, state=after, detail=_first_line(out))

    said = f"{err}\n{out}"
    low = said.lower()
    if "would be overwritten" in low:
        return PullResult(FAIL_OVERWRITE, state=after, detail=_first_line(err),
                          files=_named_files(said))
    if "not possible to fast-forward" in low or "diverging" in low:
        return PullResult(FAIL_DIVERGED, state=after, detail=_first_line(err))
    return PullResult(FAIL_ERROR, state=after, detail=_first_line(err) or _first_line(out))


# -- starting the new code -----------------------------------------------------
#
# A successful pull replaces the .py files under a running interpreter: every module
# already imported keeps the old code, and the next one imported comes from the new
# checkout. That mix is worse than either half — so the panel does not try to reload
# anything, it starts itself again from scratch.
def relaunch_command(argv: list | None = None) -> list:
    """The command line that starts this panel again, with the same arguments.

    `python -m panel` rather than the `sys.argv[0]` path: with `-m`, argv[0] is
    `…/panel/__main__.py`, and running THAT file directly is not the same thing (it
    imports as `__main__`, so the package's relative imports break).
    """
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    return [sys.executable, "-m", "panel", *args]


def relaunch(argv: list | None = None, repo: str = REPO):
    """Start a fresh panel and return the new process.

    The caller closes the old window FIRST — the new panel reads the profile on the way
    up, and a shutdown that has not yet written it is a lost session's worth of
    settings. Detached, so the replacement outlives the process that spawned it.
    """
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return subprocess.Popen(relaunch_command(argv), cwd=repo, close_fds=True,
                            creationflags=flags)
