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
import re
import sys
from pathlib import Path

try:
    import UnityPy
except ImportError:  # pragma: no cover
    sys.exit("UnityPy is required: python -m pip install --user UnityPy")

# The bundle headers ship a stripped Unity version ("0.0.0"); the game is built
# with Unity 2019.4.40f1 (see LastWar_Data/resources.assets), so tell UnityPy.
UnityPy.config.FALLBACK_UNITY_VERSION = "2019.4.40f1"

# dir-path prefix -> output category. LW_HeroBody is opt-in via --body.
ICON_PREFIXES = {
    "big": "Assets/Main/Sprites/HeroIconsBig",
    "small": "Assets/Main/Sprites/HeroIconsSmall",
}
BODY_PREFIXES = {"body": "Assets/Main/Sprites/LW_HeroBody"}


def read_sections(gameres: Path):
    """Return {sectionName: [lines...]} for the gameres text index."""
    data = gameres.read_bytes()
    tags = ["Version", "Directories", "Paths", "Bundles", "Groups"]
    positions = {t: data.find(f"[{t}]".encode()) for t in tags}
    positions = {t: p for t, p in positions.items() if p >= 0}
    order = sorted(positions, key=lambda t: positions[t])
    out = {}
    for i, t in enumerate(order):
        start = positions[t]
        end = positions[order[i + 1]] if i + 1 < len(order) else len(data)
        out[t] = data[start:end].decode("latin-1").splitlines()[1:]
    return out


def sanitize(name: str) -> str:
    name = name.strip() or "unnamed"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


def build_targets(sections, categories):
    """Map sprite-name -> category and bundle-sha256 -> {sprite names expected}."""
    # dirIndex -> category
    dir_cat = {}
    for line in sections.get("Directories", []):
        if not line.strip():
            continue
        idx, path = line.split(",", 1)
        for cat, prefix in categories.items():
            if path == prefix or path.startswith(prefix + "/"):
                dir_cat[int(idx)] = cat
                break

    # fileIndex -> (category, spriteName)  (sprite name = filename without extension)
    file_target = {}
    for line in sections.get("Paths", []):
        if not line.strip():
            continue
        parts = line.split(",", 2)
        if len(parts) < 3:
            continue
        fidx, didx, fname = int(parts[0]), int(parts[1]), parts[2]
        cat = dir_cat.get(didx)
        if cat is None:
            continue
        stem = fname.rsplit(".", 1)[0]
        file_target[fidx] = (cat, stem)

    # bundle sha256 -> {spriteName: category}
    bundle_sprites = {}
    for line in sections.get("Bundles", []):
        line = line.strip()
        if not line:
            continue
        fields = line.split(",")
        if len(fields) < 8:
            continue
        real = fields[-1]
        idxs = fields[4].split("|") if fields[4] else []
        for s in idxs:
            if not s.isdigit():
                continue
            tgt = file_target.get(int(s))
            if tgt:
                cat, stem = tgt
                bundle_sprites.setdefault(real, {})[stem] = cat
    return file_target, bundle_sprites


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
                    default=Path(__file__).resolve().parent.parent / "results" / "hero_icons")
    ap.add_argument("--body", action="store_true",
                    help="also extract full-body hero art (LW_HeroBody)")
    args = ap.parse_args()

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
