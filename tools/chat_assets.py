r"""Resolve chat-render tokens to local sprite PNGs, and split a message for
inline image rendering in the panel.

``chat_reader.py`` normalises rich inline objects to bracket tokens:

* ``[e:E006]``    -- local chat emoji; sprite stem is the PUA codepoint (``e006``).
* ``[sticker:35]``-- sticker; id -> resource stem via the live config map.
* ``[photo:429]`` -- user photo (picVer); the client caches it on disk keyed by
  ``md5(f"{uid}_{picVer}")`` (see ``photo_path``), so it resolves to a real JPG.

Sprites are extracted once by ``tools/extract_chat_assets.py`` into
``results/chat_assets/{emoji,sticker,sticker_cover}/``; the id->stem map lives in
``tools/data/chat_assets_map.json`` (dumped live from ``ChatEmojiTemplateManager``).

This module is import-safe on any OS: it only touches the filesystem, no game/Lua.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
ASSETS_DIR = os.path.join(_REPO, "results", "chat_assets")
_MAP_PATH = os.path.join(_HERE, "data", "chat_assets_map.json")

# Chat photos are downloaded by the client into its persistentDataPath, keyed
# deterministically -- no CDN URL / native call needed (verified live 2026-07-27):
#   <LocalLow>/FunFly/Last War-Survival Game/ChatPhotos/<uid[-6:]>/<md5(f"{uid}_{picVer}")>.jpg
# and "..._big.jpg" for the full-size copy (only present once opened fullscreen).
PHOTOS_DIR = os.environ.get("LASTWAR_CHATPHOTOS") or os.path.join(
    os.path.expanduser("~"), "AppData", "LocalLow",
    "FunFly", "Last War-Survival Game", "ChatPhotos")


def photo_path(uid, pic_ver, big: bool = False) -> str | None:
    """Local cached JPG for a chat photo, or None if not downloaded yet.

    ``uid`` is the sender uid, ``pic_ver`` the ``[photo:N]`` number (picVer).
    """
    if not uid or pic_ver in (None, ""):
        return None
    uid, pic_ver = str(uid), str(pic_ver)
    h = hashlib.md5(f"{uid}_{pic_ver}".encode()).hexdigest()
    cand = os.path.join(PHOTOS_DIR, uid[-6:], f"{h}{'_big' if big else ''}.jpg")
    return cand if os.path.isfile(cand) else None


def avatar_path(uid, head_pic_ver) -> str | None:
    """Local cached JPG for a sender's avatar, or None if not on disk.

    The client caches a player's avatar under the same ChatPhotos scheme as a
    message photo -- ``md5(f"{uid}_{headPicVer}").jpg`` -- so the same resolver
    applies. A built-in head frame (no uploaded avatar) has no cached file and
    returns None; the caller then shows the message without an avatar.
    """
    return photo_path(uid, head_pic_ver)

# One token = one rich object. Matches what chat_reader._render_text emits.
_TOKEN_RE = re.compile(r"\[(e|sticker|photo|emoji):([0-9A-Fa-f]+)\]")


def _load_map() -> dict:
    try:
        with open(_MAP_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


_MAP = _load_map()
_STICKER_BY_ID = _MAP.get("sticker_by_id", {})


def sticker_stem(sticker_id: str) -> str | None:
    """Resource stem (filename without dir/ext) for a sticker id, or None."""
    ent = _STICKER_BY_ID.get(str(sticker_id))
    if not ent:
        return None
    return ent.get("stem") or (ent.get("name") or "").rsplit("/", 1)[-1] or None


def token_image(kind: str, ident: str) -> str | None:
    """Absolute path to the PNG for a render token, or None if not a local asset.

    ``kind`` is one of e / emoji / sticker / photo; ``ident`` is the hex codepoint
    (emoji) or numeric id (sticker/photo). Returns None when the sprite is not on
    disk (photos, or assets not yet extracted).
    """
    if kind in ("e", "emoji"):
        # ident is the 4-hex PUA codepoint ("E006"); the sprite stem is that same
        # hex, lowercased (e006.png) -- the leading e/f is part of the hex, not a
        # prefix.
        cand = os.path.join(ASSETS_DIR, "emoji", f"{ident.lower()}.png")
        return cand if os.path.isfile(cand) else None
    if kind == "sticker":
        stem = sticker_stem(ident)
        if not stem:
            return None
        for sub in ("sticker", "sticker_cover"):
            cand = os.path.join(ASSETS_DIR, sub, f"{stem}.png")
            if os.path.isfile(cand):
                return cand
        return None
    # photo: CDN image, no local sprite (placeholder handled by the caller)
    return None


def segments(msg: str):
    """Split a rendered message into ordered segments for inline display.

    Yields ``("text", str)`` and ``("image", path)`` / ``("token", raw_token)``:
    an image segment when the token resolves to a local PNG, otherwise a token
    segment so the caller can show the bracket text as a readable fallback.
    """
    pos = 0
    for m in _TOKEN_RE.finditer(msg):
        if m.start() > pos:
            yield ("text", msg[pos:m.start()])
        path = token_image(m.group(1), m.group(2))
        yield ("image", path) if path else ("token", m.group(0))
        pos = m.end()
    if pos < len(msg):
        yield ("text", msg[pos:])


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        print(f"{arg!r}:")
        for kind, val in segments(arg):
            print(f"   {kind:6s} {val!r}")
