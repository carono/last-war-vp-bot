"""Extract chat emoji and sticker sprites from Last War's cached asset bundles.

Companion to ``extract_hero_icons.py`` -- same mechanism (walk the ``gameres``
text index, open only the bundles that carry the wanted sprites, write PNGs) but
targeting the chat asset directories discovered live from the Lua config
(``ChatEmojiTemplateManager``):

* local chat emoji  -> ``Assets/Main/Sprites/UI/LWChatEmoji/Default`` (``eXXXX.png``,
  the file stem is the PUA codepoint, e.g. ``e006`` == U+E006 == the ``[e:E006]``
  token emitted by ``chat_reader.py``).
* sticker covers    -> ``Assets/Main/Sprites/UI/LWChatEmoji/StickerCover`` (static
  thumbnail per sticker) and the dynamic sticker textures under
  ``Assets/Main/TextureEx/UIStickerDynamic``.

Run with the Windows Python that can see both the C: install and the D: cache::

    /mnt/c/Python312/python.exe tools/extract_chat_assets.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import UnityPy
except ImportError:  # pragma: no cover
    sys.exit("UnityPy is required: python -m pip install --user UnityPy")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from extract_hero_icons import read_sections, build_targets, sanitize  # noqa: E402

UnityPy.config.FALLBACK_UNITY_VERSION = "2019.4.40f1"

# dir-path prefix -> output category.
CHAT_PREFIXES = {
    "emoji": "Assets/Main/Sprites/UI/LWChatEmoji/Default",
    "sticker_cover": "Assets/Main/Sprites/UI/LWChatEmoji/StickerCover",
    "sticker": "Assets/Main/TextureEx/UIStickerDynamic",
}

# The individual emoji PNGs (LWChatEmoji/Default) live in a bundle that only
# downloads when the in-game emoji picker is opened. The emoji the client renders
# inline in chat come from the TMP sprite atlas ``lwEmoji`` instead, which is
# always cached (chat shows emoji). We crop the atlas by the TMP glyph table --
# same 81 emoji, no download needed. Search both dirs where the atlas can sit.
_EMOJI_ATLAS_PREFIXES = ("Assets/Main/TMPAsset/EmojiAssets",
                         "Assets/_Art_LastWar/Emoji")
_EMOJI_ATLAS_NAME = "lwEmoji"

# Dynamic sticker sheets are grids of this cell size (observed 128x128).
_FRAME = 128
_MAP_STICKER_PREFIX = "Assets/Main/Sprites/MapSticker"
_STICKER_MAP_PATH = os.path.join(_HERE, "data", "chat_assets_map.json")


def extract_map_stickers(sections, cache: Path, out_dir: Path, have: set) -> int:
    """Crop map-emote stickers (map_like, …) from their shared MapSticker atlas.

    These stickers have no standalone sprite; the live config
    (``tools/data/chat_assets_map.json``: ``sticker_by_id``) gives ``para1`` (the
    atlas stem, e.g. ``MapSticker_default``) and ``para2`` (the frame index into a
    128x128 grid, row-major). Crop that cell -> ``<stem>.png``. Skips any stem
    already extracted from UIStickerDynamic. Returns the count written.
    """
    try:
        with open(_STICKER_MAP_PATH, encoding="utf-8") as fh:
            by_id = json.load(fh).get("sticker_by_id", {})
    except (OSError, ValueError):
        return 0
    # atlas stem -> [(stem, frame_index)]
    want: dict[str, list] = {}
    for ent in by_id.values():
        para1, para2, stem = ent.get("para1", ""), ent.get("para2", ""), ent.get("stem", "")
        if not (para1 and str(para2).isdigit() and stem) or stem in have:
            continue
        atlas = para1.rsplit("/", 1)[-1]
        want.setdefault(atlas, []).append((stem, int(para2)))
    if not want:
        return 0
    _ft, bundles = build_targets(sections, {"x": _MAP_STICKER_PREFIX})
    n = 0
    for real in bundles:
        p = cache / real
        if not p.exists():
            continue
        try:
            env = UnityPy.load(str(p))
        except Exception:  # noqa: BLE001
            continue
        by_name = {}
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            try:
                data = obj.read()
                by_name[getattr(data, "m_Name", "")] = data
            except Exception:  # noqa: BLE001
                continue
        for atlas, items in want.items():
            data = by_name.get(atlas)
            if data is None:
                continue
            try:
                img = data.image
            except Exception:  # noqa: BLE001
                continue
            cols = max(1, img.size[0] // _FRAME)
            for stem, idx in items:
                col, row = idx % cols, idx // cols
                cell = img.crop((col * _FRAME, row * _FRAME,
                                 col * _FRAME + _FRAME, row * _FRAME + _FRAME))
                cell.save(out_dir / f"{sanitize(stem)}.png")
                have.add(stem)
                n += 1
    return n


def extract_emoji_from_tmp(sections, cache: Path, out_dir: Path) -> int:
    """Crop each chat emoji from the ``lwEmoji`` TMP atlas -> ``eXXXX.png``.

    The TMP sprite asset (a MonoBehaviour) carries m_SpriteCharacterTable
    (unicode -> glyph index + name) and m_SpriteGlyphTable (glyph -> atlas rect);
    the Texture2D of the same name is the atlas. Returns the count written.
    """
    cands = set()
    for pref in _EMOJI_ATLAS_PREFIXES:
        _ft, bs = build_targets(sections, {"x": pref})
        cands |= set(bs)
    mono = tex = None
    for real in cands:
        p = cache / real
        if not p.exists():
            continue
        try:
            env = UnityPy.load(str(p))
        except Exception:  # noqa: BLE001
            continue
        for obj in env.objects:
            try:
                data = obj.read()
                name = getattr(data, "m_Name", "") or getattr(data, "name", "")
            except Exception:  # noqa: BLE001
                continue
            if name != _EMOJI_ATLAS_NAME:
                continue
            if obj.type.name == "MonoBehaviour":
                mono = obj
            elif obj.type.name == "Texture2D":
                tex = data
    if mono is None or tex is None:
        print(f"  ! emoji atlas '{_EMOJI_ATLAS_NAME}' not found in cache "
              f"(mono={mono is not None}, tex={tex is not None})")
        return 0
    tt = mono.read_typetree()
    glyph_rect = {g["m_Index"]: g["m_GlyphRect"] for g in tt.get("m_SpriteGlyphTable", [])}
    atlas = tex.image
    _w, H = atlas.size
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for ch in tt.get("m_SpriteCharacterTable", []):
        rect = glyph_rect.get(ch["m_GlyphIndex"])
        if not rect:
            continue
        x, y, w, h = rect["m_X"], rect["m_Y"], rect["m_Width"], rect["m_Height"]
        # Unity texture space is bottom-left origin; PIL is top-left -> flip Y.
        crop = atlas.crop((x, H - y - h, x + w, H - y))
        stem = ch.get("m_Name") or f"e{ch['m_Unicode']:04x}"
        crop.save(out_dir / f"{stem}.png")
        n += 1
    return n


def main() -> int:
    # No hardcoded username: derive %LOCALAPPDATA% (or the running user's home).
    home = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    default_gameres = os.environ.get("LW_GAMERES") or Path(home) / "FunFly" / \
        "Last War-Survival Game" / "Game" / "LastWar_Data" / "StreamingAssets" / \
        "AssetBundles" / "gameres"
    # Cache dir is machine-specific (any drive) — override with --cache or LW_ASSET_CACHE.
    default_cache = os.environ.get("LW_ASSET_CACHE") or \
        Path(home) / "FunFly" / "Last War-Survival Game" / "Cache" / "AssetBundles"

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gameres", type=Path, default=default_gameres)
    ap.add_argument("--cache", type=Path, default=default_cache)
    ap.add_argument("--out", type=Path,
                    default=Path(_HERE).parent / "results" / "chat_assets")
    args = ap.parse_args()

    if not args.gameres.exists():
        sys.exit(f"gameres index not found: {args.gameres}")
    if not args.cache.exists():
        sys.exit(f"bundle cache not found: {args.cache}")

    sections = read_sections(args.gameres)
    file_target, bundle_sprites = build_targets(sections, CHAT_PREFIXES)
    print(f"Chat sprites in index: {len(file_target)} across {len(bundle_sprites)} bundles")

    for cat in CHAT_PREFIXES:
        (args.out / cat).mkdir(parents=True, exist_ok=True)

    saved = {c: 0 for c in CHAT_PREFIXES}
    missing_bundles = 0
    got_names = set()
    # Emoji/sticker art can be a Sprite or a bare Texture2D depending on the atlas.
    wanted_types = {"Sprite", "Texture2D"}
    for real, sprite_cats in sorted(bundle_sprites.items()):
        bundle_path = args.cache / real
        if not bundle_path.exists():
            missing_bundles += 1
            continue
        try:
            env = UnityPy.load(str(bundle_path))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! load failed {real[:12]}: {exc}")
            continue
        for obj in env.objects:
            if obj.type.name not in wanted_types:
                continue
            try:
                data = obj.read()
                name = getattr(data, "m_Name", "") or getattr(data, "name", "")
            except Exception:  # noqa: BLE001
                continue
            cat = sprite_cats.get(name)
            if cat is None:
                continue
            # Prefer the Sprite render; a Sprite and its backing Texture2D share the
            # name, so skip the raw texture once the sprite is saved.
            if name in got_names:
                continue
            try:
                img = data.image
            except Exception as exc:  # noqa: BLE001
                print(f"  ! image failed for {name}: {exc}")
                continue
            if cat == "sticker":
                # UIStickerDynamic textures are animation SPRITESHEETS -- a grid of
                # 128x128 frames (dice 512x512 = 4x4, S3_1 512x1024 = 4x8). Shrinking
                # the whole sheet gives an unreadable mush, so crop the first frame
                # (top-left cell) as a static thumbnail.
                w, h = img.size
                if w >= _FRAME and h >= _FRAME and w % _FRAME == 0 and h % _FRAME == 0:
                    img = img.crop((0, 0, _FRAME, _FRAME))
            dest = args.out / cat / f"{sanitize(name)}.png"
            img.save(dest)
            saved[cat] += 1
            got_names.add(name)

    # Map-emote stickers (map_like, …) live only as frames in a shared MapSticker
    # atlas; crop them by the config's para1/para2.
    map_n = extract_map_stickers(sections, args.cache, args.out / "sticker", got_names)
    if map_n:
        saved["sticker"] += map_n
        print(f"  sticker: cropped {map_n} map-emote frames from MapSticker atlases")

    # Emoji: the individual-PNG bundle is rarely cached, so always (re)build the
    # emoji set from the always-cached TMP atlas. This overwrites the same names.
    emoji_n = extract_emoji_from_tmp(sections, args.cache, args.out / "emoji")
    if emoji_n:
        saved["emoji"] = emoji_n
        print(f"  emoji: cropped {emoji_n} from the '{_EMOJI_ATLAS_NAME}' TMP atlas")

    print("\nExtracted:")
    for cat in CHAT_PREFIXES:
        print(f"  {cat:14s}: {saved[cat]} PNGs -> {args.out / cat}")
    if missing_bundles:
        print(f"  ({missing_bundles} bundles referenced by the index are not in the cache)")
    wanted_names = {stem for (_c, stem) in file_target.values()}
    not_found = wanted_names - got_names
    if not_found:
        print(f"  ({len(not_found)} indexed sprite names not recovered — likely uncached)")
    print(f"\nOutput: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
