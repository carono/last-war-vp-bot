"""Is this working copy behind the current RELEASE, and moving it forward.

The panel is run from a git checkout — there is no installer, so "обновить бота" means
moving that checkout forward. Until #1194 that was a terminal the operator had to
remember to open, which is why a box could sit weeks behind with nobody noticing.

**WHAT «NEWER» MEANS: a tag, not a commit (#1274).** Every commit on `master` used to be
an update, which put half-finished work in front of somebody who only wanted to farm —
a push made ten minutes ago was offered as «доступно обновление» with no way to tell it
from a week of tested work. So the unit of an update is a RELEASE: an annotated tag
`vMAJOR.MINOR.PATCH` (:data:`TAG_GLOB`), cut deliberately, and the panel compares itself
against the newest one that is on its upstream branch. `docs/panel-updates.md` says who
cuts them and when.

Two channels, and they differ in exactly one thing — what a pull aims at:

* :data:`RELEASE` (the default) → the newest release tag on the upstream branch. A
  checkout sitting between two releases has nothing to pull and says so.
* :data:`DEV` → `origin/<branch>`, whatever is on it, which is what this module did for
  every checkout before #1274. It is a tick on «Разработка», off unless somebody asks.

The channel is not decided here: it is a panel-wide preference (`panel/profile.py`,
`dev_updates`) that both `check` and `pull` are handed. Nothing about a channel is
remembered between calls, so a tick can change the answer with no state to invalidate.

Pure subprocess, no Tk: «Главная» draws the answer, this decides what the answer is
(the shell is a shell — CLAUDE.md). It is also deliberately dumb about the UI's timing:
every call here is blocking and belongs on a worker thread.

**Nothing here ever prompts.** A `git fetch` over SSH against a host whose key is not
known, or over HTTPS without a credential helper, will happily sit waiting on a terminal
that a windowed panel does not have — so the environment silences every prompt git owns
(:data:`_ENV`) and every call carries a timeout. A checkout that cannot reach `origin`
reports :data:`OFFLINE` and the panel stays usable.

**An SSH `origin` is read over HTTPS instead.** `install.bat` attaches every installed
copy to `https://github.com/…`, which needs no key and no account; a checkout somebody
cloned themselves usually says `git@github.com:…`, and on a machine without that key
every check would fail with «Permission denied (publickey)» for ever. So when a fetch
against an SSH remote fails, the same branch is fetched once more from the HTTPS form of
that URL (:func:`https_url`) into the same tracking ref. Reading is all this needs — the
push URL is never touched, and a remote that is already HTTPS is never fetched twice.

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
import time
from dataclasses import dataclass, field, replace

from .. import __version__ as FALLBACK_VERSION
from .paths import REPO

#: How long any local git call may take. Generous: a `status` on a cold cache over a
#: 9p-mounted Windows drive is slow the first time and instant afterwards.
LOCAL_TIMEOUT = 20.0

#: How long a `fetch` may take before the network counts as absent. A checkout with no
#: route to github hangs on the TCP connect, not on git.
FETCH_TIMEOUT = 45.0

# -- the two channels ---------------------------------------------------------
#: Only tagged releases. What every panel does unless somebody says otherwise.
RELEASE = "release"
#: The tip of the upstream branch, releases or not. A tick on «Разработка» (#1274).
DEV = "dev"
CHANNELS = (RELEASE, DEV)

#: What a release tag looks like: `v` and then a digit — `v1.4.0`, `v2.0.10`. A glob and
#: not a regex because it is handed straight to `git tag --list`, which is also what
#: keeps a branch-shaped tag (`backup/…`, `wip-…`) out of the answer without this module
#: having to know the names anybody has ever used.
TAG_GLOB = "v[0-9]*"

#: The suffix a version wears when the checkout is PAST its newest release — the mark
#: the task asked for. Not a locale key: it is part of an identifier, like the `+7`
#: beside it, and it must read the same in a log, on a phone and in a bug report.
DEV_SUFFIX = "-dev"

#: How long a computed version string is reused. The number can only change under a
#: pull (which asks for a restart) or a commit made on this machine, and it is read by
#: the web state route every couple of seconds by every phone that has the page open —
#: so it is cached, and short enough that an operator who has just committed sees it.
VERSION_TTL = 60.0

# -- what `check` can conclude ------------------------------------------------
CURRENT = "current"          #: level with the target — the release, or the branch tip
BEHIND = "behind"            #: the target has commits this copy has not — the update case
AHEAD = "ahead"              #: local commits origin has not; nothing to pull
DIVERGED = "diverged"        #: both, from a common ancestor — a merge, not a pull
OFFLINE = "offline"          #: `fetch` failed or timed out; the reading is local-only
NO_UPSTREAM = "no_upstream"  #: the branch tracks nothing
DETACHED = "detached"        #: not on a branch at all
NOT_A_REPO = "not_a_repo"    #: no .git — someone unpacked a zip
NO_GIT = "no_git"            #: git is not on PATH
ERROR = "error"              #: git ran and said something unexpected; see `detail`
#: PAST the newest release, on the release channel — the ordinary state of a checkout
#: that has taken a dev update, or of the machine the releases are cut on. Not `AHEAD`:
#: nothing is wrong and nothing is local, the next release simply has not been cut yet.
DEV_AHEAD = "dev_ahead"
#: The upstream branch carries no release tag at all — a fork, a shallow clone, or a
#: checkout made before the first release. Nothing to compare against, so nothing is
#: offered; the dev channel still works and the status line says so.
NO_RELEASE = "no_release"

# -- what `pull` can conclude -------------------------------------------------
OK = "ok"                          #: fast-forwarded; the panel must be restarted
FAIL_NOTHING = "nothing"           #: already level — nothing was done
FAIL_DIRTY = "dirty"               #: tracked files modified; refused before touching git
FAIL_DIVERGED = "diverged"         #: not a fast-forward; a human has to merge
FAIL_OVERWRITE = "overwrite"       #: local files stand where the update wants to write
FAIL_OFFLINE = "offline"           #: could not fetch, and nothing was fetched earlier
FAIL_NO_RELEASE = "no_release"     #: release channel, and there is no release to go to
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
    remote: str = ""             # short hash of the TARGET (the release, or the tip)
    upstream: str = ""           # e.g. "origin/master"
    behind: int = 0              # commits the target has and this copy has not
    ahead: int = 0               # the other way round
    dirty: bool = False          # tracked files modified — independent of `state`
    detail: str = ""             # git's own words, for the log
    # -- which question was asked, and what the answer was measured against (#1274)
    channel: str = RELEASE       # RELEASE or DEV — what "newer" meant for this reading
    target: str = ""             # the ref a pull would move to: "v1.4.0" / "origin/main"
    release: str = ""            # newest release tag on the upstream branch, "" if none
    # -- and where THIS checkout stands, whichever channel it is on
    version: str = ""            # the version text of HEAD: "v1.4.0", "v1.4.0+7-dev"
    at_release: str = ""         # the newest release HEAD contains, "" before the first
    dev_commits: int = 0         # commits HEAD is past `at_release` — 0 on the tag

    @property
    def can_pull(self) -> bool:
        """Is «Обновить» worth offering? Behind, and nothing of the operator's at risk."""
        return self.state == BEHIND and not self.dirty

    @property
    def dev_build(self) -> bool:
        """Is this checkout BETWEEN releases — code no release has shipped yet?

        What the version line marks. True on the machine the releases are cut on, on a
        checkout that has taken a dev update, and on one made before the first tag.
        """
        return self.dev_commits > 0 or not self.at_release


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


def https_url(url: str) -> str:
    """The anonymous-HTTPS form of an SSH remote URL, or ``""`` when there is none.

    Both spellings git accepts are the same repository::

        git@github.com:carono/last-war-vp-bot.git   -> https://github.com/carono/…
        ssh://git@github.com:22/carono/…            -> https://github.com/carono/…

    Anything already fetchable without a key — `https://`, `http://`, `file://`, a plain
    path — returns ``""``: there is nothing to fall back to and trying would only cost a
    second timeout.
    """
    url = (url or "").strip()
    if not url:
        return ""
    rest = ""
    if url.startswith("ssh://"):
        rest = url[len("ssh://"):]
    elif "://" not in url and ":" in url:
        # The scp-like form, `[user@]host:path`. A Windows drive letter (`C:\…`) and a
        # path with no colon at all are not remotes of this shape.
        host, _sep, path = url.partition(":")
        if len(host) < 2 or "/" in host or "\\" in path[:1]:
            return ""
        rest = f"{host}/{path}"
    else:
        return ""
    rest = rest.split("@", 1)[-1]           # drop the `git@` login
    host, _slash, path = rest.partition("/")
    host = host.split(":", 1)[0]            # …and the `:22`, which HTTPS does not want
    if not host or not path:
        return ""
    return f"https://{host}/{path.lstrip('/')}"


def _remote_url(repo: str, remote: str) -> str:
    """Where ``remote`` fetches from, or ``""`` if git cannot say."""
    rc, out, _err = _git("remote", "get-url", remote, repo=repo)
    return out if rc == 0 else ""


def _fetch(repo: str, remote: str, branch: str, timeout: float,
           tags: bool = False) -> str:
    """Bring ``remote``'s ``branch`` up to date. Returns ``""`` on success, else why not.

    One branch, not every ref the remote has: a full fetch on this repo pulls every
    other branch for a question about one. ``tags`` adds the tags to that — the release
    channel compares against one, and a tag nobody fetched is a release nobody is
    offered. A failure against an SSH remote is retried over HTTPS (see the module
    docstring) — with an explicit refspec, because a fetch by URL updates no tracking
    ref of its own and the comparison that follows reads exactly those refs.
    """
    args = ["fetch", "--quiet"]
    if tags:
        args.append("--tags")
    rc, _out, err = _git(*args, remote, branch, repo=repo, timeout=timeout)
    if rc == 0:
        return ""
    said = _first_line(err) or "fetch failed"

    over_https = https_url(_remote_url(repo, remote))
    if not over_https:
        return said
    refspecs = [f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}"]
    if tags:
        refspecs.append("+refs/tags/*:refs/tags/*")
    rc, _out, err2 = _git("fetch", "--quiet", over_https, *refspecs,
                          repo=repo, timeout=timeout)
    return "" if rc == 0 else (_first_line(err2) or said)


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


# -- which release is this, and which is the newest ----------------------------
def latest_release(repo: str = REPO, ref: str = "HEAD") -> str:
    """The newest release tag that ``ref`` CONTAINS, or ``""`` when there is none.

    `--merged` is what makes this "on this branch" rather than "in this repository": a
    tag cut on a branch nobody has merged is not a release this checkout can be offered,
    and fast-forwarding onto it would take the branch somewhere it does not go.
    `-v:refname` is git's own version sort, so `v1.10.0` comes after `v1.9.0` — which is
    the whole reason the ordering is not done here.
    """
    rc, out, _err = _git("tag", "--list", TAG_GLOB, "--merged", ref,
                         "--sort=-v:refname", repo=repo)
    if rc != 0:
        return ""
    for line in out.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def describe(repo: str = REPO) -> tuple:
    """``(release, commits_past_it, short_hash)`` for HEAD. Any of them may be empty.

    One `git describe --long` rather than a tag lookup plus a count: it answers both
    halves off the same walk, and `--long` is what stops it collapsing "exactly on the
    tag" into a bare tag name that cannot be told from "seven commits past it".
    """
    rc, out, _err = _git("describe", "--tags", "--long", "--abbrev=7",
                         "--match", TAG_GLOB, repo=repo)
    if rc != 0 or not out:
        # No tag reachable from HEAD — a fork, a shallow clone, or the days before the
        # first release. The hash is still worth having: it is what an operator reads
        # out when asked "какая у тебя версия".
        return "", 0, head(repo)
    stem, _sep, short = out.rpartition("-g")
    tag, _sep, count = stem.rpartition("-")
    try:
        past = int(count)
    except ValueError:                       # a tag with an unexpected shape in it
        return "", 0, head(repo)
    return tag, past, short


def version_text(repo: str = REPO, refresh: bool = False) -> str:
    """What this checkout calls itself — `v1.4.0`, or `v1.4.0+7-dev` between releases.

    Cached for :data:`VERSION_TTL`, because both front-ends ask for it on a timer and
    the answer only moves when somebody pulls or commits. `refresh=True` is what a check
    passes: it has just run git anyway, so the reading it takes is free and current.

    A checkout with no release tag falls back to `panel.__version__` — which the release
    commit bumps to the number it is about to tag (`docs/panel-updates.md`), so an
    unpacked zip with no `.git` still names its own release rather than a hash.
    """
    now = time.monotonic()
    if not refresh:
        stamped = _VERSION_CACHE.get(repo)
        if stamped is not None and now - stamped[0] < VERSION_TTL:
            return stamped[1]
    tag, past, _short = describe(repo)
    if not tag:
        text = FALLBACK_VERSION if not is_repo(repo) else f"{FALLBACK_VERSION}{DEV_SUFFIX}"
    elif past:
        text = f"{tag}+{past}{DEV_SUFFIX}"
    else:
        text = tag
    _VERSION_CACHE[repo] = (now, text)
    return text


#: repo path -> (when it was read, what it said). See :func:`version_text`.
_VERSION_CACHE: dict = {}


def _forget_version(repo: str) -> None:
    """Drop the cached version — after a pull, which is the one thing that moves it."""
    _VERSION_CACHE.pop(repo, None)


def _stamp(state: UpdateState, repo: str, channel: str) -> UpdateState:
    """Fill in the "where does this checkout stand" half of a reading.

    Every path out of :func:`check` goes through here, including the ones that failed
    before git could say anything useful — the version line is drawn from the last
    reading, and a panel that cannot reach `origin` must still be able to say what it
    is running.
    """
    tag, past, _short = describe(repo)
    return replace(state, channel=channel, at_release=tag, dev_commits=past,
                   version=version_text(repo, refresh=True))


def _compare(repo: str, branch: str, upstream: str, dirty: bool, *,
             target: str = "", channel: str = DEV, release: str = "") -> UpdateState:
    """Count the divergence against ``target`` — a tracking ref or a release tag.

    The one place the two channels part company: on :data:`RELEASE`, being ahead of the
    target is :data:`DEV_AHEAD` rather than :data:`AHEAD`, because "past the newest
    release" is where an ordinary checkout sits for most of a release cycle and calling
    it «локальные коммиты» would send somebody looking for commits they never made.
    """
    target = target or upstream
    local = head(repo)
    # `^{commit}` PEELS, and it has to: a release is an ANNOTATED tag, so plain
    # `rev-parse v1.4.0` hands back the tag OBJECT's hash — a number that appears
    # nowhere in the history and matches nothing the operator can look up. Everything
    # else here (`rev-list`, `merge`) peels on its own; this one does not.
    rc, out, err = _git("rev-parse", "--short", f"{target}^{{commit}}", repo=repo)
    remote = out if rc == 0 else ""
    common = {"branch": branch, "local": local, "remote": remote, "upstream": upstream,
              "dirty": dirty, "target": target, "release": release}
    rc, out, err = _git("rev-list", "--left-right", "--count",
                        f"HEAD...{target}", repo=repo)
    if rc != 0:
        return UpdateState(ERROR, detail=_first_line(err), **common)
    try:
        ahead, behind = (int(n) for n in out.split()[:2])
    except (ValueError, IndexError):
        return UpdateState(ERROR, detail=f"unreadable rev-list output: {out!r}", **common)
    if ahead and behind:
        state = DIVERGED
    elif behind:
        state = BEHIND
    elif ahead:
        state = DEV_AHEAD if channel == RELEASE else AHEAD
    else:
        state = CURRENT
    return UpdateState(state, behind=behind, ahead=ahead, **common)


def check(repo: str = REPO, fetch: bool = True, timeout: float = FETCH_TIMEOUT,
          channel: str = RELEASE) -> UpdateState:
    """Compare this checkout with the newest release — or, on :data:`DEV`, the branch tip.

    Blocking — call it off the UI thread.

    With `fetch=False` the comparison is against whatever the last fetch left behind,
    which is what :func:`pull` re-reads after doing its own fetch (and what a test uses
    to stay off the network).

    A failed fetch is :data:`OFFLINE` rather than an error: the local half of the reading
    is still true and worth showing, and "нет связи" is a different thing to tell the
    operator than "git сломался".
    """
    channel = channel if channel in CHANNELS else RELEASE
    rc, out, err = _git("rev-parse", "--is-inside-work-tree", repo=repo)
    if rc == -1:
        return _stamp(UpdateState(NO_GIT, detail=_first_line(err)), repo, channel)
    if rc != 0 or out != "true":
        return _stamp(UpdateState(NOT_A_REPO, detail=_first_line(err)), repo, channel)

    dirty = is_dirty(repo)
    local = head(repo)

    rc, branch, _err = _git("rev-parse", "--abbrev-ref", "HEAD", repo=repo)
    branch = branch if rc == 0 else ""
    if branch in ("", "HEAD"):
        # Detached: mid-bisect, on a tag, or a checkout of one commit. There is no
        # "next" to pull towards and guessing one would be a fine way to lose a state
        # the operator put themselves in deliberately.
        return _stamp(UpdateState(DETACHED, local=local, dirty=dirty), repo, channel)

    rc, upstream, err = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name",
                             "@{u}", repo=repo)
    if rc != 0 or not upstream:
        return _stamp(UpdateState(NO_UPSTREAM, branch=branch, local=local, dirty=dirty,
                                  detail=_first_line(err)), repo, channel)

    if fetch:
        remote = upstream.split("/", 1)[0]
        # Tags only on the release channel: they are what it compares against, and a
        # dev checkout that never looks at one should not pay for them either.
        failed = _fetch(repo, remote, branch, timeout, tags=(channel == RELEASE))
        if failed:
            state = _resolve(repo, branch, upstream, dirty, channel)
            # Keep whatever the stale refs know — they may already be behind from an
            # earlier fetch — but say plainly that this reading is not fresh.
            return _stamp(replace(state, state=OFFLINE, detail=failed), repo, channel)

    return _stamp(_resolve(repo, branch, upstream, dirty, channel), repo, channel)


def _resolve(repo: str, branch: str, upstream: str, dirty: bool,
             channel: str) -> UpdateState:
    """Pick what this channel measures against, and measure. Refs only, never a fetch."""
    if channel == DEV:
        return _compare(repo, branch, upstream, dirty, target=upstream, channel=DEV,
                        release=latest_release(repo, upstream))
    release = latest_release(repo, upstream)
    if not release:
        # Nothing tagged on this branch. NOT an error and NOT «актуально»: the panel
        # genuinely cannot say whether there is anything newer, and the way out is the
        # dev tick rather than anything it could do by itself.
        return UpdateState(NO_RELEASE, branch=branch, local=head(repo),
                           upstream=upstream, dirty=dirty, target="", release="")
    return _compare(repo, branch, upstream, dirty, target=release, channel=RELEASE,
                    release=release)


# -- moving forward ------------------------------------------------------------
def pull(repo: str = REPO, timeout: float = FETCH_TIMEOUT,
         channel: str = RELEASE) -> PullResult:
    """Fast-forward the checkout to the newest release — or, on :data:`DEV`, to the tip.

    Blocking — call it off the UI thread.

    Refuses before touching anything when the tree is dirty or the branch has diverged,
    so the failure modes that matter never get as far as git. The merge itself is
    `--ff-only` onto `state.target`: on the release channel that is a TAG, which keeps
    the branch attached (a fast-forward moves it, it does not detach HEAD) and lands the
    checkout exactly on the release rather than on whatever has been pushed since. On
    success the panel is running code that no longer matches the files on disk — hence
    :data:`OK` meaning "restart me", not "done".
    """
    channel = channel if channel in CHANNELS else RELEASE
    before = check(repo, fetch=False, channel=channel)
    if before.state in (NO_GIT, NOT_A_REPO, DETACHED, NO_UPSTREAM, ERROR):
        return PullResult(FAIL_ERROR, state=before, detail=before.detail or before.state)
    if before.dirty:
        # Deliberately before the fetch: a dirty tree is the operator's own work and
        # nothing about the network changes the answer.
        return PullResult(FAIL_DIRTY, state=before)

    remote = before.upstream.split("/", 1)[0]
    fetch_err = _fetch(repo, remote, before.branch, timeout, tags=(channel == RELEASE))

    now = check(repo, fetch=False, channel=channel)
    if now.state in (CURRENT, DEV_AHEAD):
        # Nothing to do. DEV_AHEAD belongs here and not in the refusals below: a
        # checkout sitting past the newest release is not broken, it is simply already
        # carrying everything the release channel has to offer. If the fetch failed we
        # cannot honestly claim either — the refs we just read may be days old.
        return (PullResult(FAIL_OFFLINE, state=now, detail=fetch_err) if fetch_err
                else PullResult(FAIL_NOTHING, state=now))
    if now.state == NO_RELEASE:
        return PullResult(FAIL_NO_RELEASE, state=now, detail=fetch_err)
    if now.state in (AHEAD, DIVERGED):
        return PullResult(FAIL_DIVERGED, state=now, detail=fetch_err)
    if now.state != BEHIND:
        return PullResult(FAIL_OFFLINE if fetch_err else FAIL_ERROR, state=now,
                          detail=fetch_err or now.detail or now.state)

    rc, out, err = _git("merge", "--ff-only", now.target, repo=repo)
    _forget_version(repo)
    after = check(repo, fetch=False, channel=channel)
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
