"""Extract hero icon sprites from Last War's cached Unity asset bundles.

Last War ships a text index file ``gameres`` (StreamingAssets/AssetBundles)
describing every logical asset. Its sections are::

    [Directories]  dirIndex, logical/folder/path
    [Paths]        fileIndex, dirIndex, filename
    [Bundles]      bundleIndex, unityName, crc, size, fileIndices, ?, flags, <sha256>.bundle

Downloaded UnityFS bundles are cached flat as ``Cache/AssetBundles/<sha256>.bundle``
(the cache root is recorded in ``bundle_cache_path.txt`` in persistentDataPath).

Hero icons live in the ``Assets/Main/Sprites/HeroIconsBig`` and ``HeroIconsSmall``
directory trees (full-body art in ``LW_HeroBody``). The runtime packs sprites into
size-based dynamic atlases, so a single atlas bundle mixes hero and non-hero
sprites; selecting by bundle name alone is imprecise. Instead this tool walks the
index to find the exact sprite names that belong to the hero directories, opens
only the bundles that carry them, and writes just those Sprites as PNGs.

Run with the Windows Python that can see both the C: install and the D: cache::

    /mnt/c/Python312/python.exe tools/extract_hero_icons.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import game_paths     # noqa: E402  (where the game is — LW_GAMERES & co)
import gameres_index  # noqa: E402  (the shared index reader)

try:
    import UnityPy
except ImportError:  # pragma: no cover
    sys.exit("UnityPy is required: python -m pip install --user UnityPy")

# The bundle headers ship a stripped Unity version ("0.0.0"); the game is built
# with Unity 2019.4.40f1 (see LastWar_Data/resources.assets), so tell UnityPy.
UnityPy.config.FALLBACK_UNITY_VERSION = "2019.4.40f1"

# dir-path prefix -> output category. `big` and `small` are the default; the rest are
# asked for by name with `--sets`, because each one costs a pass over the bundles that
# carry it. `head` is the player's own avatar — the picture beside a name in a rally,
# a chat line or a ranking (`tools/rally_report.py` uses it).
SET_PREFIXES = {
    "big": "Assets/Main/Sprites/HeroIconsBig",
    "small": "Assets/Main/Sprites/HeroIconsSmall",
    "body": "Assets/Main/Sprites/LW_HeroBody",
    "head": "Assets/Main/Sprites/UI/UIHeadIcon",
    "head_s6": "Assets/Main/SeasonRes/S6/Sprites/UIHeadIcon",
}
ICON_PREFIXES = {name: SET_PREFIXES[name] for name in ("big", "small")}
BODY_PREFIXES = {"body": SET_PREFIXES["body"]}


# The three index steps — read the sections, pick the sprite names, work out which
# bundles carry them — are shared with tools/extract_item_icons.py and live in
# tools/lib/gameres_index.py. They are re-exported here under their old names so the
# rest of this file (and anything importing it) reads exactly as it did.
read_sections = gameres_index.read_sections
sanitize = gameres_index.sanitize
build_targets = gameres_index.build_targets


def main() -> int:
    # Where the game keeps its assets is game_paths' business — nothing about the
    # install (drive, publisher folder, username) is spelled out here. Both honour
    # an override: LW_GAMERES and LW_ASSET_CACHE, or --gameres / --cache.
    default_gameres = Path(game_paths.gameres())
    default_cache = Path(game_paths.asset_cache())

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gameres", type=Path, default=default_gameres)
    ap.add_argument("--cache", type=Path, default=default_cache)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "results" / "hero_icons")
    ap.add_argument("--body", action="store_true",
                    help="also extract full-body hero art (LW_HeroBody)")
    ap.add_argument("--sets", default=None,
                    help="comma-separated sets to extract instead of the default "
                         "hero icons: " + ", ".join(sorted(SET_PREFIXES)))
    args = ap.parse_args()

    if args.sets:
        chosen = [name.strip() for name in args.sets.split(",") if name.strip()]
        unknown = [name for name in chosen if name not in SET_PREFIXES]
        if unknown:
            sys.exit(f"unknown set(s): {', '.join(unknown)} — "
                     f"pick from {', '.join(sorted(SET_PREFIXES))}")
        categories = {name: SET_PREFIXES[name] for name in chosen}
    else:
        categories = dict(ICON_PREFIXES)
    if args.body:
        categories.update(BODY_PREFIXES)

    if not args.gameres.exists():
        sys.exit(f"gameres index not found: {args.gameres}")
    if not args.cache.exists():
        sys.exit(f"bundle cache not found: {args.cache}")

    sections = read_sections(args.gameres)
    file_target, bundle_sprites = build_targets(sections, categories)
    wanted_total = len(file_target)
    print(f"Hero sprites in index: {wanted_total} across {len(bundle_sprites)} bundles")

    for cat in categories:
        (args.out / cat).mkdir(parents=True, exist_ok=True)

    saved = {c: 0 for c in categories}
    missing_bundles = 0
    got_names = set()
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
            if obj.type.name != "Sprite":
                continue
            try:
                data = obj.read()
                name = getattr(data, "m_Name", "") or getattr(data, "name", "")
            except Exception:  # noqa: BLE001
                continue
            cat = sprite_cats.get(name)
            if cat is None:
                continue
            try:
                img = data.image
            except Exception as exc:  # noqa: BLE001
                print(f"  ! image failed for {name}: {exc}")
                continue
            dest = args.out / cat / f"{sanitize(name)}.png"
            i = 1
            while dest.exists():
                dest = args.out / cat / f"{sanitize(name)}_{i}.png"
                i += 1
            img.save(dest)
            saved[cat] += 1
            got_names.add(name)

    print("\nExtracted:")
    for cat in categories:
        print(f"  {cat:6s}: {saved[cat]} PNGs -> {args.out / cat}")
    if missing_bundles:
        print(f"  ({missing_bundles} bundles referenced by the index are not in the cache)")
    wanted_names = {stem for (_c, stem) in file_target.values()}
    not_found = wanted_names - got_names
    if not_found:
        print(f"  ({len(not_found)} indexed sprite names not recovered — likely in uncached bundles)")
    print(f"\nOutput: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
