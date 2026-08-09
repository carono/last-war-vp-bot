#!/usr/bin/env python3
r"""Find a player's own avatar in the client's photo cache.

The picture a player uploaded for themselves is not in the game's asset bundles — it is
theirs, so the client DOWNLOADS it the first time it meets them and keeps it. The cache
lives in the client's download tree (`game_paths.local_images()`) and is keyed the same
way the chat-photo cache is (`tools/chat_assets.py`)::

    LocalImages/<last 6 digits of uid>/<md5(f"{uid}_{picVer}")>.jpg

which means the cache holds exactly the people this client has seen — and that a uid
alone is not enough to name the file: `picVer` counts up every time the player changes
their picture, and nothing on the rally wire carries it.

So the file is found by trying: for a given uid, hash `uid_0` … `uid_<CEILING>` and keep
the highest one that is actually a file in that uid's bucket. It costs a few thousand md5
sums per player, which is nothing (253 players in ~2 s), and it cannot be fooled — a hash
either names a file on disk or it does not. The highest hit is the newest picture; the
older ones stay in the cache after a player changes theirs.

`CEILING` is a real limit and the caller is told when it bites: a `picVer` of 2 898 has
been seen in the wild, so a player who changes their photo often can outrun a small one.

    from player_photos import newest_for
    newest_for("1000000000000001")     # -> ("…/LocalImages/000001/<md5>.jpg", 92) | None
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_paths  # noqa: E402

#: How far up to look for a `picVer`. The highest seen on this machine's cache is 2 898.
CEILING = 4000

_BUCKETS: dict = {}


def _bucket(uid: str, root: str) -> set:
    """The file names in a uid's bucket, read once per run."""
    path = os.path.join(root, uid[-6:])
    names = _BUCKETS.get(path)
    if names is None:
        try:
            names = set(os.listdir(path))
        except OSError:
            names = set()
        _BUCKETS[path] = names
    return names


def newest_for(uid, root: "str | None" = None, ceiling: int = CEILING):
    """``(path, picVer)`` of the newest cached photo for `uid`, or ``None``.

    ``None`` means the client has never downloaded one — either the player uses a
    built-in avatar rather than a photo of their own, or this client has not met them.
    """
    uid = str(uid or "")
    if len(uid) < 6:
        return None
    root = root or game_paths.local_images()
    names = _bucket(uid, root)
    if not names:
        return None
    best = None
    for version in range(ceiling + 1):
        digest = hashlib.md5(f"{uid}_{version}".encode()).hexdigest()
        if f"{digest}.jpg" in names:
            best = (os.path.join(root, uid[-6:], f"{digest}.jpg"), version)
    return best


def reset_cache() -> None:
    """Forget the directory listings — for a test that writes a cache and re-reads it."""
    _BUCKETS.clear()


if __name__ == "__main__":                       # a quick look at what is on disk
    root = game_paths.local_images()
    print(f"cache: {root}")
    if not os.path.isdir(root):
        raise SystemExit("  not there — set LW_LOCAL_IMAGES, or the client has met "
                         "nobody yet")
    buckets = [name for name in sorted(os.listdir(root))
               if os.path.isdir(os.path.join(root, name))]
    files = sum(len(os.listdir(os.path.join(root, name))) for name in buckets)
    print(f"  {len(buckets)} bucket(s), {files} file(s)")
