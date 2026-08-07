r"""«Обновление» on «Главная»: is this checkout behind origin, and can it be pulled?

The panel now offers a one-press `git pull` (task #1194), which is the one button in it
that can destroy work the operator has not committed. So this file is mostly about the
cases where the answer must be **no**:

  * a tracked file modified — refused before git is even asked;
  * local commits origin has not got — a merge, not a fast-forward, so refused;
  * an untracked file standing where the update wants to write — git's refusal, caught
    and reported with the names;
  * no upstream, no repo at all, no route to the remote.

…and about the one case where the answer is yes: behind by N, clean tree, fast-forward.

Since #1274 there is a second half to all of it: what counts as "behind" is a RELEASE
TAG, not a commit, unless the «Обновлять до dev-версии» tick says otherwise. So the
answer must ALSO be no while `origin` has visibly moved — three commits pushed with no
tag among them are not an update — and a pull that is offered must stop exactly on the
tag rather than on whatever was pushed after it was cut.

Everything runs against REAL git in a temp directory — a bare "origin", a working clone
and a second clone that plays the other developer. No network: a file path is a perfectly
good remote, and `fetch` from one exercises the same code as a fetch from github.

Nothing here touches the panel's own checkout.

    python3 tests/test_panel_updates.py
    C:\Python312\python.exe tests\test_panel_updates.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panel.runtime import updates  # noqa: E402


# -- a two-clone world ---------------------------------------------------------
def _git(repo: str, *args: str) -> str:
    """Run git in `repo` and return its stdout — raising on anything unexpected."""
    proc = subprocess.run(("git", "-C", repo, *args), capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} in {repo}:\n{proc.stderr}")
    return proc.stdout.strip()


def _identify(repo: str) -> None:
    """A repo git will let us commit in, whatever the machine's global config says."""
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")


def _write(repo: str, name: str, text: str) -> None:
    Path(repo, name).write_text(text, encoding="utf-8")


def _commit(repo: str, name: str, text: str, message: str) -> str:
    _write(repo, name, text)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "--short", "HEAD")


class World:
    """A bare origin, our working copy, and a second clone standing in for someone else.

    `theirs` is what makes "behind" happen: it commits and pushes, exactly as another
    developer would, so `work` falls behind through the same mechanism the real thing
    uses rather than through a hand-moved ref.

    The first commit is tagged :data:`BASE_RELEASE`, because a world with no release on
    it is a world where the default channel has nothing to say (#1274) — and that case
    is worth testing deliberately (`test_a_branch_with_no_release_says_so`) rather than
    by accident in every other test.
    """

    #: Where a world starts by default: the first commit, released.
    BASE_RELEASE = "v1.0.0"

    def __init__(self, base_release: str = BASE_RELEASE) -> None:
        self.base_release = base_release
        self.root = tempfile.mkdtemp(prefix="lw-updates-")
        self.origin = os.path.join(self.root, "origin.git")
        self.work = os.path.join(self.root, "work")
        self.theirs = os.path.join(self.root, "theirs")
        subprocess.run(("git", "init", "--quiet", "--bare", "--initial-branch=main",
                        self.origin), check=True, capture_output=True)
        subprocess.run(("git", "clone", "--quiet", self.origin, self.work),
                       check=True, capture_output=True)
        _identify(self.work)
        _commit(self.work, "README.md", "one\n", "first")
        _git(self.work, "push", "--quiet", "-u", "origin", "main")
        subprocess.run(("git", "clone", "--quiet", self.origin, self.theirs),
                       check=True, capture_output=True)
        _identify(self.theirs)
        if self.base_release:
            self.they_tag(self.base_release)
            _git(self.work, "fetch", "--quiet", "--tags", "origin", "main")

    def they_push(self, name: str = "feature.txt", text: str = "new\n",
                  release: str = "") -> str:
        """One commit from the other clone, landed on origin — and released, if asked.

        `release` is what turns a push into an UPDATE: without it the default channel
        sees nothing to offer, which is the whole of #1274 and is tested on its own.
        """
        head = _commit(self.theirs, name, text, f"add {name}")
        _git(self.theirs, "push", "--quiet", "origin", "main")
        if release:
            self.they_tag(release)
        return head

    def they_tag(self, version: str) -> str:
        """Cut a release where the other clone stands right now, and push the tag.

        Annotated, like the real thing (`docs/panel-updates.md`) — a lightweight tag
        would pass every assertion here and then behave differently under
        `git describe`, which prefers annotated ones.
        """
        _git(self.theirs, "tag", "-a", version, "-m", version)
        _git(self.theirs, "push", "--quiet", "origin", version)
        return _git(self.theirs, "rev-parse", "--short", "HEAD")

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _world(base_release: str = World.BASE_RELEASE):
    """A World, or None when this machine has no usable git.

    `base_release=""` builds one that has never been released — a fork, or the days
    before the first tag, which the default channel has to say something honest about.
    """
    try:
        subprocess.run(("git", "--version"), capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return World(base_release)


# -- the readings --------------------------------------------------------------
def test_a_fresh_clone_is_current():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        state = updates.check(w.work)
        assert state.state == updates.CURRENT, state
        assert state.branch == "main", state
        assert state.behind == 0 and state.ahead == 0, state
        assert not state.dirty, state
        # Nothing to offer — the button must not appear on a checkout that is level.
        assert not state.can_pull, state
        assert state.local == state.remote, state
    finally:
        w.close()


def test_a_commit_on_origin_reads_as_behind():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        theirs = w.they_push(release="v1.1.0")
        # Without a fetch the clone cannot know: the refs are still yesterday's.
        assert updates.check(w.work, fetch=False).state == updates.CURRENT
        state = updates.check(w.work)
        assert state.state == updates.BEHIND, state
        assert state.behind == 1 and state.ahead == 0, state
        assert state.remote == theirs, state
        assert state.can_pull, state
    finally:
        w.close()


def test_local_commits_read_as_ahead_and_offer_nothing():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        _commit(w.work, "mine.txt", "mine\n", "local work")
        # Asked about the BRANCH: commits origin has not got. The same repo asked about
        # releases answers DEV_AHEAD instead, which is a different sentence for a
        # different fact — see `test_past_the_release_is_not_ahead`.
        state = updates.check(w.work, channel=updates.DEV)
        assert state.state == updates.AHEAD, state
        assert state.ahead == 1 and state.behind == 0, state
        assert not state.can_pull, state
    finally:
        w.close()


def test_both_sides_moved_reads_as_diverged():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push(release="v1.1.0")
        _commit(w.work, "mine.txt", "mine\n", "local work")
        state = updates.check(w.work)
        assert state.state == updates.DIVERGED, state
        assert state.ahead == 1 and state.behind == 1, state
        assert not state.can_pull, state
    finally:
        w.close()


def test_dirt_is_tracked_changes_only():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        # An untracked file is NOT dirt: the repo grows captures and scratch files all
        # session and none of them is in a fast-forward's way.
        _write(w.work, "scratch.log", "noise\n")
        assert not updates.is_dirty(w.work)
        assert not updates.check(w.work, fetch=False).dirty
        # A modified tracked file is. So is a staged one — it is work all the same.
        _write(w.work, "README.md", "edited\n")
        assert updates.is_dirty(w.work)
        _git(w.work, "add", "README.md")
        assert updates.is_dirty(w.work)
    finally:
        w.close()


def test_behind_but_dirty_offers_no_button():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push(release="v1.1.0")
        _write(w.work, "README.md", "edited\n")
        state = updates.check(w.work)
        assert state.state == updates.BEHIND and state.dirty, state
        # The update exists and is still not offered: the operator's own edit comes first.
        assert not state.can_pull, state
    finally:
        w.close()


def test_a_directory_that_is_not_a_repo():
    root = tempfile.mkdtemp(prefix="lw-updates-bare-")
    try:
        state = updates.check(root)
        assert state.state in (updates.NOT_A_REPO, updates.NO_GIT), state
        assert not state.can_pull, state
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_branch_with_no_upstream():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        _git(w.work, "checkout", "--quiet", "-b", "side")
        state = updates.check(w.work)
        assert state.state == updates.NO_UPSTREAM, state
        assert state.branch == "side", state
        assert not state.can_pull, state
    finally:
        w.close()


def test_a_detached_head():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        _git(w.work, "checkout", "--quiet", "--detach", "HEAD")
        state = updates.check(w.work)
        assert state.state == updates.DETACHED, state
        assert not state.can_pull, state
    finally:
        w.close()


def test_an_unreachable_remote_is_offline_not_an_error():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push(release="v1.1.0")
        updates.check(w.work)                       # a good fetch first…
        shutil.rmtree(w.origin, ignore_errors=True)  # …and now the remote is gone
        state = updates.check(w.work)
        assert state.state == updates.OFFLINE, state
        assert state.detail, "an offline reading must say why"
        # The stale tracking ref is still worth reporting — it is what we last knew.
        assert state.behind == 1, state
        assert not state.can_pull, state
    finally:
        w.close()


# -- an SSH origin on a machine with no key ------------------------------------
#
# `install.bat` attaches an installed copy to `https://github.com/…`, but a checkout
# somebody cloned themselves says `git@github.com:…` — and on a box without that key
# every check failed with «Permission denied (publickey)». The fetch now falls back to
# the HTTPS form of the same URL, which needs no key at all.
def test_an_ssh_url_is_read_over_https():
    assert updates.https_url("git@github.com:carono/last-war-vp-bot.git") == \
        "https://github.com/carono/last-war-vp-bot.git"
    assert updates.https_url("ssh://git@github.com/carono/last-war-vp-bot.git") == \
        "https://github.com/carono/last-war-vp-bot.git"
    # The port SSH needs is not one HTTPS wants.
    assert updates.https_url("ssh://git@github.com:22/carono/repo.git") == \
        "https://github.com/carono/repo.git"


def test_a_url_that_already_needs_no_key_has_no_fallback():
    # Nothing to fall back TO — and an attempt would only cost a second timeout.
    for url in ("https://github.com/carono/repo.git",
                "http://example.invalid/repo.git",
                "file:///srv/git/repo.git",
                "/srv/git/repo.git",
                r"C:\repos\repo.git",
                ""):
        assert updates.https_url(url) == "", url


def test_a_failing_ssh_remote_is_fetched_the_other_way():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    over_https = updates.https_url                     # restored in `finally`
    try:
        theirs = w.they_push(release="v1.1.0")
        # An origin no key on this machine can reach, exactly as the panel's own checkout
        # had it. The fallback URL is the only thing stubbed — where a real one resolves
        # to github, this one resolves to the bare repo next door, so everything after it
        # (the refspec, the tracking ref, the comparison) is the real code path.
        _git(w.work, "remote", "set-url", "origin", "git@nowhere.invalid:owner/x.git")
        updates.https_url = lambda url: w.origin if url.startswith("git@") else ""
        state = updates.check(w.work)
        assert state.state == updates.BEHIND, state
        assert state.behind == 1 and state.remote == theirs, state
        # …and the tracking ref really moved, so «Обновить» has something to merge.
        assert _git(w.work, "rev-parse", "--short", "origin/main") == theirs
        res = updates.pull(w.work)
        assert res.ok, (res.reason, res.detail)
    finally:
        updates.https_url = over_https
        w.close()


def test_an_ssh_remote_with_nowhere_to_fall_back_to_is_still_offline():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    over_https = updates.https_url
    try:
        _git(w.work, "remote", "set-url", "origin", "git@nowhere.invalid:owner/x.git")
        updates.https_url = lambda url: ""             # no HTTPS form of this remote
        state = updates.check(w.work)
        assert state.state == updates.OFFLINE, state
        assert state.detail, "an offline reading must say why"
    finally:
        updates.https_url = over_https
        w.close()


# -- the pull ------------------------------------------------------------------
def test_pull_fast_forwards_and_leaves_the_file_behind():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        theirs = w.they_push("feature.txt", "shipped\n", release="v1.1.0")
        res = updates.pull(w.work)
        assert res.ok, (res.reason, res.detail)
        assert res.state is not None and res.state.state == updates.CURRENT, res.state
        assert res.state.local == theirs, res.state
        assert Path(w.work, "feature.txt").read_text(encoding="utf-8") == "shipped\n"
        # …and no merge commit was made: a fast-forward moves the branch, nothing else.
        assert _git(w.work, "rev-list", "--count", "HEAD") == "2"
    finally:
        w.close()


def test_pull_on_a_level_checkout_does_nothing():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        res = updates.pull(w.work)
        assert res.reason == updates.FAIL_NOTHING, (res.reason, res.detail)
        assert not res.ok
    finally:
        w.close()


def test_pull_refuses_a_dirty_tree_without_touching_it():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push(release="v1.1.0")
        _write(w.work, "README.md", "my unsaved work\n")
        head = _git(w.work, "rev-parse", "HEAD")
        res = updates.pull(w.work)
        assert res.reason == updates.FAIL_DIRTY, (res.reason, res.detail)
        # The edit is still there and the branch has not moved.
        assert Path(w.work, "README.md").read_text(encoding="utf-8") == "my unsaved work\n"
        assert _git(w.work, "rev-parse", "HEAD") == head
    finally:
        w.close()


def test_pull_refuses_a_diverged_branch():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push(release="v1.1.0")
        mine = _commit(w.work, "mine.txt", "mine\n", "local work")
        res = updates.pull(w.work)
        assert res.reason == updates.FAIL_DIVERGED, (res.reason, res.detail)
        assert _git(w.work, "rev-parse", "--short", "HEAD") == mine
        # No merge was even attempted, so there is nothing half-done to clean up.
        assert not Path(w.work, ".git", "MERGE_HEAD").exists()
    finally:
        w.close()


def test_pull_reports_the_untracked_file_that_stands_in_the_way():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push("feature.txt", "theirs\n", release="v1.1.0")
        # Not dirt (untracked), so the panel offers the button — and git is the one that
        # refuses, because this exact path is what the update adds.
        _write(w.work, "feature.txt", "mine, uncommitted\n")
        assert updates.check(w.work).can_pull
        res = updates.pull(w.work)
        assert res.reason == updates.FAIL_OVERWRITE, (res.reason, res.detail)
        assert any("feature.txt" in f for f in res.files), res.files
        assert Path(w.work, "feature.txt").read_text(encoding="utf-8") == "mine, uncommitted\n"
    finally:
        w.close()


def test_pull_without_a_reachable_remote_is_offline():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        shutil.rmtree(w.origin, ignore_errors=True)
        res = updates.pull(w.work)
        # Nothing to merge and no way to find out whether there should be — which is a
        # different answer to "всё актуально", and must not read as one.
        assert res.reason == updates.FAIL_OFFLINE, (res.reason, res.detail)
        assert res.detail, "an offline pull must say why"
    finally:
        w.close()


# -- releases, and the tick that ignores them (#1274) --------------------------
#
# The whole point of the release channel is that MOST commits are not an update. So
# these are mostly about the answer being "нет" while `origin` has visibly moved — and
# about the one press stopping exactly on the tag rather than on whatever has been
# pushed since it was cut.
def test_the_release_channel_ignores_untagged_commits():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        # The world starts AT v1.0.0; these two commits are unreleased work.
        w.they_push("a.txt")
        w.they_push("b.txt")
        state = updates.check(w.work)               # release channel is the default
        assert state.state == updates.CURRENT, state
        assert not state.can_pull, state
        assert state.release == "v1.0.0", state
        # …and the very same checkout, asked the other question, is two behind.
        dev = updates.check(w.work, channel=updates.DEV)
        assert dev.state == updates.BEHIND and dev.behind == 2, dev
        assert dev.can_pull, dev
    finally:
        w.close()


def test_a_tag_is_what_makes_an_update():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push("a.txt")
        w.they_push("b.txt", release="v1.1.0")
        released = _git(w.theirs, "rev-parse", "--short", "HEAD")
        state = updates.check(w.work)
        assert state.state == updates.BEHIND, state
        assert state.can_pull, state
        assert state.release == "v1.1.0", state
        assert state.target == "v1.1.0", state      # the ref a pull will merge
        assert state.remote == released, (state.remote, released)
        assert state.behind == 2, state
    finally:
        w.close()


def test_a_release_pull_stops_at_the_tag():
    """The requirement in one test: with the tick off, an update goes no further.

    Two commits, a release cut on the second, and a third pushed after it — which is
    the ordinary state of the repository ten minutes after a release. The press must
    land on the tag and leave the third commit alone.
    """
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push("a.txt")
        w.they_push("b.txt", release="v1.1.0")
        released = _git(w.theirs, "rev-parse", "--short", "HEAD")
        tip = w.they_push("c.txt")                  # unreleased work, pushed after
        res = updates.pull(w.work)
        assert res.ok, (res.reason, res.detail)
        landed = _git(w.work, "rev-parse", "--short", "HEAD")
        assert landed == released, (landed, released, tip)
        assert landed != tip, "the release pull ran past the tag"
        # Still on the branch: a fast-forward onto a tag moves the branch, it does not
        # detach HEAD — and a detached panel could never be updated again.
        assert _git(w.work, "rev-parse", "--abbrev-ref", "HEAD") == "main"
        assert not Path(w.work, "c.txt").exists(), "unreleased work came along"
        after = updates.check(w.work)
        assert after.state == updates.CURRENT, after
        assert after.version == "v1.1.0", after
    finally:
        w.close()


def test_the_dev_tick_goes_all_the_way_to_the_tip():
    """…and the other half of it: with the tick on, the same repo reaches the tip."""
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push("a.txt", release="v1.1.0")
        tip = w.they_push("c.txt")
        res = updates.pull(w.work, channel=updates.DEV)
        assert res.ok, (res.reason, res.detail)
        landed = _git(w.work, "rev-parse", "--short", "HEAD")
        assert landed == tip, (landed, tip)
        assert Path(w.work, "c.txt").exists(), "the dev update left the tip behind"
    finally:
        w.close()


def test_past_the_release_is_not_ahead():
    """A checkout that took a dev update is not «локальные коммиты» — it is a dev build."""
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push("a.txt")
        w.they_push("b.txt")
        assert updates.pull(w.work, channel=updates.DEV).ok
        state = updates.check(w.work)               # …now asked about releases again
        assert state.state == updates.DEV_AHEAD, state
        assert not state.can_pull, state
        assert state.dev_build, state
        assert state.ahead == 2 and state.behind == 0, state
        assert state.version == "v1.0.0+2-dev", state
        # And the press, if something reached it anyway, does nothing rather than
        # trying to walk backwards onto the tag.
        res = updates.pull(w.work)
        assert res.reason == updates.FAIL_NOTHING, (res.reason, res.detail)
    finally:
        w.close()


def test_a_branch_with_no_release_says_so():
    w = _world(base_release="")
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push("a.txt")
        state = updates.check(w.work)
        # NOT «актуально»: the panel cannot say whether there is anything newer, and
        # reading it as "up to date" is how a fork would sit for ever on old code.
        assert state.state == updates.NO_RELEASE, state
        assert not state.can_pull, state
        assert not state.release, state
        res = updates.pull(w.work)
        assert res.reason == updates.FAIL_NO_RELEASE, (res.reason, res.detail)
        # The way out is the tick, and it works: the same repo, the other channel.
        assert updates.check(w.work, channel=updates.DEV).can_pull
    finally:
        w.close()


def test_a_tag_that_is_not_a_release_is_not_one():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        w.they_push("a.txt")
        w.they_tag("backup/before-the-rewrite")     # not a version — must not count
        state = updates.check(w.work)
        assert state.state == updates.CURRENT, state
        assert state.release == "v1.0.0", state
    finally:
        w.close()


def test_the_version_names_the_release_and_marks_a_dev_build():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        assert updates.version_text(w.work, refresh=True) == "v1.0.0"
        assert updates.describe(w.work)[:2] == ("v1.0.0", 0)
        # One commit past it, and the mark appears — this is what the version line on
        # «Главная» and the one the phone reads are both drawn from.
        _commit(w.work, "mine.txt", "x\n", "local work")
        assert updates.version_text(w.work, refresh=True) == "v1.0.0+1-dev"
        # …and the cached answer is what everything else gets, so the two front-ends
        # cannot disagree about it inside one poll.
        assert updates.version_text(w.work) == "v1.0.0+1-dev"
    finally:
        w.close()


def test_a_release_reading_still_says_what_it_is_running_offline():
    w = _world()
    if w is None:
        print("  SKIP no git")
        return
    try:
        shutil.rmtree(w.origin, ignore_errors=True)
        state = updates.check(w.work)
        assert state.state == updates.OFFLINE, state
        # The version is the half of the reading that is still true with no network,
        # and it is the half the operator is asked for when something goes wrong.
        assert state.version == "v1.0.0", state
        assert state.at_release == "v1.0.0", state
    finally:
        w.close()


def test_the_tick_is_remembered_for_the_whole_panel():
    """«Обновлять до dev-версии» is one answer per WINDOW, not per profile.

    It lives beside `active_profile` in the panel-wide file, because there is one
    checkout and every open profile runs out of it — two profiles disagreeing about
    which channel it follows would be two answers to a question with one subject.
    """
    from panel import profile as profilemod

    root = tempfile.mkdtemp(prefix="lw-updates-pref-")
    was = profilemod.SETTINGS_FILE
    profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
    try:
        # Never asked: releases. A panel that has never heard of the tick behaves as
        # every panel is meant to.
        assert profilemod.dev_updates() is False
        assert profilemod.update_channel() == updates.RELEASE
        profilemod.set_dev_updates(True)
        assert profilemod.dev_updates() is True
        assert profilemod.update_channel() == updates.DEV
        # …and it is on disk, not in a variable: the next window reads the same answer.
        assert "dev_updates" in Path(profilemod.SETTINGS_FILE).read_text(encoding="utf-8")
        profilemod.set_dev_updates(False)
        assert profilemod.update_channel() == updates.RELEASE
    finally:
        profilemod.SETTINGS_FILE = was
        shutil.rmtree(root, ignore_errors=True)


def test_every_conclusion_has_a_word_in_every_shipped_locale():
    """A state with no `update.st.<name>` key draws its own id in the status line.

    The keys are built by name in `panel/__main__.py::_paint_update`, so nothing else
    can catch a state that was added without its sentence — and English falling back
    silently is exactly what makes a missing translation invisible for months.
    """
    import json

    states = [updates.CURRENT, updates.BEHIND, updates.AHEAD, updates.DIVERGED,
              updates.OFFLINE, updates.NO_UPSTREAM, updates.DETACHED,
              updates.NOT_A_REPO, updates.NO_GIT, updates.ERROR,
              updates.DEV_AHEAD, updates.NO_RELEASE]
    wanted = [f"update.st.{s}" for s in states]
    wanted += ["update.st.behind_dirty", "update.st.behind_release",
               "update.st.behind_release_dirty", "update.confirm.body_release",
               "update.fail.no_release", "develop.updates.dev",
               "develop.updates.frame", "develop.updates.hint",
               "log.update.behind_release", "log.update.pulling_release",
               "log.update.dev_ahead", "log.update.no_release",
               "log.update.fail_no_release", "log.update.channel.dev",
               "log.update.channel.release"]
    locales = Path(__file__).resolve().parents[1] / "panel" / "locales"
    for path in sorted(locales.glob("*.json")):
        words = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in wanted if key not in words]
        assert not missing, f"{path.name} is missing {missing}"


# -- restarting onto the new code ----------------------------------------------
def test_relaunch_command_runs_the_package_not_the_file():
    cmd = updates.relaunch_command(["--profile", "alt"])
    assert cmd[0] == sys.executable, cmd
    # `-m panel`, never the __main__.py path: running that file directly imports it as
    # `__main__`, and the package's relative imports break.
    assert cmd[1:3] == ["-m", "panel"], cmd
    assert cmd[3:] == ["--profile", "alt"], cmd
    assert not any(c.endswith("__main__.py") for c in cmd), cmd


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
