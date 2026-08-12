#!/usr/bin/env python3
"""One face per player, resolved once and kept in the shared avatar folder.

Two things already knew how to find a player's picture and neither could be called
from a panel that has to draw one every few seconds:

* `player_photos.newest_for(uid)` finds the photo the player uploaded, in the client's
  own download cache. It is the authoritative source and it is not cheap — a uid alone
  does not name the file, so the lookup hashes `uid_0` … `uid_4000` and keeps the
  highest hit (`docs/research/player-avatars.md`).
* `head_icons_map.icon_path(head_id)` names the built-in sprite a player wears when
  they never uploaded one, out of the extracted bundle icons.

`tools/rally_report.py` joins the two for a page it generates once. This module is the
same join for a screen that is redrawn live: it answers with a path in the SHARED
folder (`game_paths.avatar_cache()`), shrinks the original into it the first time, and
remembers in-process both what it found and what it could not — so the expensive part
is paid once per player per panel run and never on a repaint.

    from player_faces import face_for
    face_for("1000000000000001", 20002)   # -> "…/cache/avatars/1000000000000001.jpg"

**The folder is the machine's, not an account's, and that is a decision written down**
(`game_paths.avatar_cache()`, #1306): the same player has the same face whichever
account met them first, so four profiles keeping four copies is four times the disk for
one answer. Hence the process-wide caches below — they hold PATHS of shared files, and
nothing in them belongs to a profile.

`None` means «no picture» rather than «not looked»: the caller draws an initial.
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_paths  # noqa: E402

#: The faces are drawn small — a row on a phone, a line in a Tk list. A photo out of
#: the client's cache averages 55 KiB, which is fifty times more picture than either
#: front-end shows, so it is thumbnailed on the way into the shared folder.
FACE_PX = 128

#: uid -> path in the shared folder, or None when neither source could place them.
_FACES: dict = {}
#: headSkinId -> path, kept apart because forty players wearing one sprite cost one file.
_HEADS: dict = {}


def _shrink(source: str, destination: str) -> bool:
    """Copy `source` into `destination`, no larger than `FACE_PX`. True when it landed.

    Without PIL — or for a cache entry the library cannot read — the file is copied
    whole: it is still what the client downloaded, and a face is better shown big than
    dropped over a resize.
    """
    try:
        from PIL import Image
        with Image.open(source) as img:
            img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
            img.thumbnail((FACE_PX, FACE_PX), Image.LANCZOS)
            img.save(destination, "JPEG", quality=82, optimize=True)
        return True
    except Exception:                            # noqa: BLE001 — see the docstring
        pass
    try:
        shutil.copyfile(source, destination)
        return True
    except OSError:
        return False


def _photo(uid: str, root: "str | None") -> "str | None":
    """The player's own photo, copied into the shared folder — or None."""
    try:
        import player_photos
    except Exception:                            # noqa: BLE001 — no cache is an answer
        return None
    destination = os.path.join(game_paths.avatar_cache(), f"{uid}.jpg")
    if os.path.isfile(destination):
        return destination
    try:
        found = player_photos.newest_for(uid, root=root)
    except Exception:                            # noqa: BLE001 — a reading, never a run
        return None
    if not found:
        return None
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
    except OSError:
        return None
    return destination if _shrink(found[0], destination) else None


def _sprite(head_id) -> "str | None":
    """The built-in avatar for a `headSkinId`, copied into the shared folder — or None.

    Most ids resolve to nothing: the `headSkinId -> sprite` table is encrypted and the
    module maps ONE family by a numbering hypothesis, deliberately leaving the rest
    unmapped rather than putting a stranger's face on a row (`head_icons_map`).
    """
    key = str(head_id or "").strip()
    if not key or key in ("0", "None"):
        return None
    if key in _HEADS:
        return _HEADS[key]
    destination = os.path.join(game_paths.avatar_cache(), f"{key}.png")
    if os.path.isfile(destination):
        _HEADS[key] = destination
        return destination
    try:
        import head_icons_map
        source = head_icons_map.icon_path(key)
    except Exception:                            # noqa: BLE001 — no map is an answer
        source = None
    if not source or not os.path.isfile(source):
        _HEADS[key] = None
        return None
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(source, destination)     # a sprite is already small
    except OSError:
        _HEADS[key] = None
        return None
    _HEADS[key] = destination
    return destination


def face_for(uid, head_id=None, root: "str | None" = None) -> "str | None":
    """The picture to draw for a player: their own photo, else their built-in avatar.

    Answers with a path inside `game_paths.avatar_cache()` — a file both front-ends can
    read, one per picture however many rows show it — or None when the client has never
    met them and their `headSkinId` is one of the unmapped families.

    NOT for the Tk thread the first time a uid is asked: the photo lookup walks a few
    thousand md5 sums (~10 ms per player) and the shrink reads a file. Once answered it
    is a dictionary hit.
    """
    uid = str(uid or "").strip()
    if uid and uid in _FACES:
        found = _FACES[uid]
        if found is not None:
            return found
    elif uid:
        found = _photo(uid, root)
        _FACES[uid] = found
        if found is not None:
            return found
    return _sprite(head_id)


def file_named(name: str) -> "str | None":
    """A bare file name back into a path inside the shared folder, or None.

    The panel's web front-end links a face by NAME rather than by path
    (`panel/tabs/rally/roster.py::face_url`), and this is the half that resolves one.
    Three checks and not one, because the route it feeds is reachable from a phone —
    and therefore from whatever else can reach that port: the name must be a plain
    name, it must carry one of the two suffixes this folder holds, and the path it
    makes must land INSIDE the folder.
    """
    clean = str(name or "").strip()
    if not clean or clean != os.path.basename(clean) or clean.startswith("."):
        return None
    if os.path.splitext(clean)[1].lower() not in (".jpg", ".png"):
        return None
    root = os.path.abspath(game_paths.avatar_cache())
    full = os.path.abspath(os.path.join(root, clean))
    if os.path.dirname(full) != root or not os.path.isfile(full):
        return None
    return full


def forget() -> None:
    """Drop what was resolved — for a test that writes a cache and re-reads it."""
    _FACES.clear()
    _HEADS.clear()
