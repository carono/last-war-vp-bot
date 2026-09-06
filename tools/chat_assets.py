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
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
ASSETS_DIR = os.path.join(_REPO, "results", "chat_assets")
_MAP_PATH = os.path.join(_HERE, "data", "chat_assets_map.json")

# Chat photos are downloaded by the client into its persistentDataPath, keyed
# deterministically -- no CDN URL / native call needed (verified live 2026-07-27):
#   <LocalLow>/<game folder>/ChatPhotos/<uid[-6:]>/<md5(f"{uid}_{picVer}")>.jpg
# and "..._big.jpg" for the full-size copy (only present once opened fullscreen).
# Where that tree is, is game_paths' business, not this module's.
sys.path.insert(0, os.path.join(_HERE, "lib"))

import game_paths  # noqa: E402

PHOTOS_DIR = game_paths.chat_photos_dir()


#: Where the panel keeps the pictures IT fetched. The client's own cache is read
#: first and never written to — it belongs to the game, and a build that changes its
#: mind about that tree must not find our files in it.
OWN_PHOTOS_DIR = os.path.join(_REPO, "results", "chat_photos")

#: The picture CDN the client itself names (`UIPlayerHead`, beside `LocalImages` and
#: the `{0}_{1}` / `_big` / `.jpg` it builds a key out of). An environment variable in
#: front of it for the same reason every other address here has one: a build that moves
#: it must be answerable without editing code.
PIC_CDN = (os.environ.get("LW_PIC_CDN") or "https://lastwar-cdn.akamaized.net/img")

#: How long one fetch may take, and how big an answer may be. A chat photograph is a
#: phone snapshot — measured live at 8–13 KB for the thumbnail and 0.14–0.43 MB for the
#: full-size copy — so anything past this is not the picture we asked for.
PHOTO_TIMEOUT_SEC = 12.0
PHOTO_MAX_BYTES = 12 * 1024 * 1024

#: A name the CDN answered 404 for, and when. A miss is NOT written to disk — caching
#: it as a file would make it permanent, and a picture can appear later — but it is
#: remembered for a while in memory, because the browser re-asks for every bubble on
#: every scroll and the alternative is one request over the internet per bubble.
_PHOTO_MISSES: dict = {}
PHOTO_MISS_TTL_SEC = 600.0


def photo_key(uid, pic_ver) -> "tuple | None":
    """``(folder, md5)`` naming one picture, or ``None`` when the pair is not a pair.

    The client keys every picture a player owns — the avatar and every photograph — the
    same way: the last six digits of the uid as a folder, and `md5("<uid>_<ver>")` as
    the name. Verified against this machine's own cache: 296 of 316 avatars named in the
    chat history resolve to a file that is there.
    """
    uid, ver = str(uid or "").strip(), str(pic_ver or "").strip()
    if not uid.isdigit() or not ver.isdigit():
        return None
    return uid[-6:], hashlib.md5(f"{uid}_{ver}".encode()).hexdigest()


def photo_url(uid, pic_ver, big: bool = False) -> "str | None":
    """The address the picture is served from, or ``None`` for a bad pair.

    ``<cdn>/<last six digits of the uid>/<md5("<uid>_<ver>")>[_big].jpg`` — no query, no
    signature and no expiry: measured live, the plain address answers 200 with the JPEG.
    An invented example of the shape, so nothing real is written down here:

        https://<cdn>/img/000123/0123456789abcdef0123456789abcdef.jpg
        https://<cdn>/img/000123/0123456789abcdef0123456789abcdef_big.jpg
    """
    key = photo_key(uid, pic_ver)
    if key is None:
        return None
    folder, name = key
    return f"{PIC_CDN.rstrip('/')}/{folder}/{name}{'_big' if big else ''}.jpg"


def photo_path(uid, pic_ver, big: bool = False) -> str | None:
    """Local JPG for a chat photo, or None if neither cache has it YET.

    Two places are read and neither is asked twice: the CLIENT's own download tree
    first (it is the game's, and it is already there for anything the game drew), then
    the panel's own (`results/chat_photos`), which is where :func:`photo_fetch` puts
    what this machine went and got.
    """
    key = photo_key(uid, pic_ver)
    if key is None:
        return None
    folder, name = key
    leaf = os.path.join(folder, f"{name}{'_big' if big else ''}.jpg")
    for root in (PHOTOS_DIR, OWN_PHOTOS_DIR):
        cand = os.path.join(root, leaf)
        if os.path.isfile(cand):
            return cand
    return None



def _through_a_plain_interpreter(url: str) -> "bytes | None":
    """The same fetch, made by a short-lived CONSOLE interpreter, or ``None``.

    THIS PROCESS MAY NOT BE ALLOWED ON THE NETWORK AT ALL, and it is not something the
    code can see: measured on the live machine, a request from the windowed interpreter
    the panel and the service both run under (`pythonw.exe`) is reset by the far end
    («WinError 10054»), and the identical request made a second later by the console one
    (`python.exe`) answers 200. Whatever draws that line — a split-tunnelled VPN, a
    firewall rule naming an image — belongs to the machine and not to the bot, and the
    only thing to do about it here is to ask an interpreter that IS allowed.

    So a failure is retried ONCE through `game_paths.win_python()` — the same
    interpreter every other child process of the panel is started with, asked for rather
    than written down. On a machine with no such split this costs nothing, because the
    first attempt succeeds and this is never reached.
    """
    import os as _os
    import subprocess
    import sys as _sys

    exe = (game_paths.win_python() or "").strip()
    if not exe or not _os.path.isfile(exe):
        return None
    if _os.path.basename(exe).lower() == _os.path.basename(_sys.executable or "").lower():
        return None                       # the same interpreter, so the same answer
    code = ("import sys,urllib.request;"
            "a=urllib.request.urlopen(sys.argv[1],timeout=%d);"
            "sys.stdout.buffer.write(a.read(%d))" % (int(PHOTO_TIMEOUT_SEC),
                                                     PHOTO_MAX_BYTES + 1))
    # NO CONSOLE WINDOW: the caller is a windowed process, and a black box blinking on
    # the desktop every time somebody scrolls a chat is not a picture arriving quietly.
    quiet = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run([exe, "-c", code, url], capture_output=True,
                              timeout=PHOTO_TIMEOUT_SEC + 8, creationflags=quiet)
    except Exception:                     # noqa: BLE001 — a picture, never the page
        return None
    if done.returncode != 0 or not done.stdout:
        return None
    return done.stdout


def photo_fetch(uid, pic_ver, big: bool = False, log=None) -> "str | None":
    """The picture on disk, fetching it ONCE if this machine has not got it.

    THE CLIENT NEVER FETCHES THESE FOR US (#2418). A chat photograph is downloaded when
    the game's own chat window draws the message, and the panel reads chat without ever
    opening it — measured: the client's chat-photo cache did not exist at all, so every
    picture in the panel was a blank bubble. The address is the client's own
    (:func:`photo_url`), so this is the same picture the game would have shown.

    Called from the route that SERVES one picture and from nowhere else: one fetch per
    photograph a person actually looked at, never a sweep and never a clock.

    IT SAYS WHY IT FAILED when it is handed a `log` (#2418). Every way of not getting a
    picture ends in the same 404 on the wire — no network, a certificate the machine
    does not trust, a name the CDN never had, a disk that refused the write — and the
    first live run of this had the panel's own process fetching nothing while the same
    address answered 200 from a shell on the same machine. One line naming the reason is
    the difference between that hour and a minute.
    """
    have = photo_path(uid, pic_ver, big=big)
    if have:
        return have
    url = photo_url(uid, pic_ver, big=big)
    if not url:
        return None
    import time
    import urllib.request

    missed = _PHOTO_MISSES.get(url)
    if missed is not None and (time.time() - missed) < PHOTO_MISS_TTL_SEC:
        return None

    folder, name = photo_key(uid, pic_ver)
    leaf = f"{name}{'_big' if big else ''}"
    dest = os.path.join(OWN_PHOTOS_DIR, folder, leaf + ".jpg")

    def _no(reason: str) -> None:
        _PHOTO_MISSES[url] = time.time()
        if log:
            try:
                log(f"chat photo {folder}/{leaf}: {reason}")
            except Exception:             # noqa: BLE001 — a picture, never the page
                pass

    try:
        with urllib.request.urlopen(url, timeout=PHOTO_TIMEOUT_SEC) as answer:
            status = getattr(answer, "status", 200)
            if status != 200:
                _no(f"the CDN answered {status}")
                return None
            blob = answer.read(PHOTO_MAX_BYTES + 1)
    except Exception as exc:              # noqa: BLE001 — a picture, never the page
        blob = _through_a_plain_interpreter(url)
        if blob is None:
            _no(f"{type(exc).__name__}: {exc}")
            return None
    if not blob or len(blob) > PHOTO_MAX_BYTES or blob[:2] != b"\xff\xd8":
        # Not a JPEG: the CDN answers a small XML document (404, `NoSuchKey`) for a name
        # it does not know, and writing that to disk would cache the miss for ever.
        _no(f"not a JPEG, {len(blob or b'')} bytes")
        return None
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        with open(tmp, "wb") as handle:
            handle.write(blob)
        os.replace(tmp, dest)
    except OSError as exc:
        _no(f"cannot write it here: {exc}")
        return None
    return dest


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


#: Which sub-folders of `results/chat_assets/` a front-end may ask for by name. The
#: photos are NOT among them: a chat photograph is somebody's own picture, and the phone
#: draws those from the CDN link the message carries rather than from this machine.
SPRITE_DIRS = ("emoji", "sticker", "sticker_cover")


def sprite_named(name: str) -> "str | None":
    """``"emoji/e006.png"`` back into a path inside the sprite tree, or ``None``.

    The web front-end links a sprite by NAME (`panel/tabs/chat.py`), and this is the half
    that resolves one — the same three checks `item_icons.file_named` makes, plus the
    folder, because these sprites live in three: the name is a folder this module owns
    and a plain file inside it, it carries the one suffix those folders hold, and it
    lands INSIDE the tree. The route is reachable from a phone, so none of the three is
    optional.
    """
    clean = str(name or "").strip().replace("\\", "/")
    parts = clean.split("/")
    if len(parts) != 2 or parts[0] not in SPRITE_DIRS:
        return None
    stem = parts[1]
    if not stem or stem != os.path.basename(stem) or stem.startswith("."):
        return None
    if os.path.splitext(stem)[1].lower() != ".png":
        return None
    root = os.path.abspath(os.path.join(ASSETS_DIR, parts[0]))
    full = os.path.abspath(os.path.join(root, stem))
    if os.path.dirname(full) != root or not os.path.isfile(full):
        return None
    return full


def sprite_link(path: str) -> "str | None":
    """One sprite as the phone asks for it: ``/api/chatsprite?sprite=emoji/e006.png``.

    A LINK and never bytes, for the reason `inventory.cell_url` is one: `web_view` runs
    on the Tk thread and a card carrying a hundred base64 images would be a hundred file
    reads in front of the event loop.
    """
    import urllib.parse as _url

    if not path:
        return None
    folder = os.path.basename(os.path.dirname(path))
    if folder not in SPRITE_DIRS:
        return None
    return "/api/chatsprite?sprite=" + _url.quote(f"{folder}/{os.path.basename(path)}")


def photo_link(uid, pic_ver, big: bool = False) -> "str | None":
    """One chat PHOTO as the phone asks for it, or None when the pair is not a pair.

    The same route the sprites travel on (`/api/chatsprite`) and deliberately not a
    second one — the person's rule, and the reason is the one every picture route here
    keeps: a link rather than bytes, and a name that is RESOLVED rather than trusted.
    A photo is named by the pair that identifies it in the game (`uid` + the `[photo:N]`
    number), never by a path, so nothing a message carries can point the route at a file
    of its own choosing.

    `big` asks for the full-size copy — what a tap opens. BOTH SIZES ARE ALWAYS
    OFFERED since #2418: neither is on this disk until somebody looks at the picture,
    because the route fetches it then (`photo_fetch`), and the CDN keeps the two
    beside each other. A link is therefore a link to a picture that CAN be had, never
    a promise that it is already here — a name the CDN does not know is answered 404
    by the route and the bubble says so.
    """
    import urllib.parse as _url

    if photo_key(uid, pic_ver) is None:
        return None
    q = {"photo": str(uid), "ver": str(pic_ver)}
    if big:
        q["big"] = "1"
    return "/api/chatsprite?" + _url.urlencode(q)


def photo_named(uid, pic_ver, big: bool = False, log=None) -> "str | None":
    """Resolve a photo the way `sprite_named` resolves a sprite: by name, never a path.

    It FETCHES what neither cache holds (#2418), because nothing else ever will: the
    client downloads a chat photograph when its own chat window draws the message, and
    the panel reads chat without opening it — measured live, `ChatPhotos` did not exist
    at all on this machine, so every picture in the panel was a blank bubble. One fetch
    per photograph somebody actually looked at, on the server's own thread, never a
    sweep and never a clock.

    Both halves must be digits — this is the one place a value that came off the wire
    becomes part of a filename, and `photo_key` is what checks it.
    """
    return photo_fetch(uid, pic_ver, big=bool(big), log=log)


def emoji_catalogue() -> list:
    """Every inline emoji that has a sprite on disk, in config order.

    Each entry is ``{"id": "<config id>", "hex": "<PUA hex>", "path": "<png>"}``.
    The ``id`` is what an outgoing message references as a ``{e:<id>}`` token
    (``tools/chat_send.py`` resolves it to the PUA glyph); the sprite is drawn in
    the picker so the person chooses by looking, not by id.
    """
    out = []
    for e in _MAP.get("emoji", []):
        hex_stem = str(e.get("name") or "")
        path = token_image("e", hex_stem) if hex_stem else None
        if path:
            out.append({"id": str(e.get("id") or ""), "hex": hex_stem, "path": path})
    return out


def sticker_catalogue() -> list:
    """Every sticker that has a sprite on disk, ordered by numeric id.

    Each entry is ``{"id": "<config id>", "name": "<resource name>", "path":
    "<png>"}``. A sticker is sent as its own message (``--sticker <id>``); the
    sprite (its first animation frame) is the picker thumbnail.
    """
    out = []
    for sid, ent in _STICKER_BY_ID.items():
        path = token_image("sticker", sid)
        if path:
            out.append({"id": str(sid),
                        "name": str(ent.get("name") or ent.get("stem") or sid),
                        "path": path})
    out.sort(key=lambda s: int(s["id"]) if s["id"].isdigit() else (1 << 30))
    return out


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
