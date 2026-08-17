"""Extract the bag's item pictures — and the rarity frames behind them — as PNGs.

The game draws an inventory cell as TWO sprites, and the panel copies that rather than
inventing a border of its own (docs/research/inventory.md):

* the **frame**, picked by the item's rarity — ``ItemTemplateManager:GetToolBgByColor(c)``
  answers ``…/LWCommon/Sprite/cfm_tongyong_daojukuang_<c>.png`` for ``c`` in 1..6;
* the **picture**, named on the item's own config row (``template.icon``), which lives
  in the ``Assets/Main/Sprites/ItemIcons`` tree. Every icon a live bag asked for was
  found there — including hero shards, whose picture is a hero portrait copied into the
  item tree under the same name.

Note the picture is NOT derivable from the item id: a shard filed under one id routinely
wears another id's portrait. Always read ``icon`` off the row (``read_inventory.md``).

Run with a Python that can see the install AND the bundle cache — they are often on
different drives (``LastWarLauncher.json`` names both)::

    C:\\Python312\\python.exe tools\\extract_item_icons.py

Output lands in ``results/item_icons/{item,frame}/<spriteName>.png``, which is where
``tools/lib/item_icons.py`` looks for it. ``results/`` is git-ignored: these are the
game's own art and they stay on the machine that extracted them.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import game_paths        # noqa: E402  (where the game is — LW_GAMERES & co)
import gameres_index     # noqa: E402  (the shared index reader)

try:
    import UnityPy
except ImportError:  # pragma: no cover
    sys.exit("UnityPy is required: python -m pip install --user UnityPy")

# The bundle headers ship a stripped Unity version ("0.0.0"); the game is built with
# Unity 2019.4.40f1 (see LastWar_Data/resources.assets), so tell UnityPy.
UnityPy.config.FALLBACK_UNITY_VERSION = "2019.4.40f1"

#: dir-path prefix -> output category.
SET_PREFIXES = {
    "item": "Assets/Main/Sprites/ItemIcons",
    "frame": "Assets/Main/Sprites/UI/LWCommon/Sprite",
}

#: The frame directory holds several thousand common-UI sprites and we want six of
#: them, so the `frame` category is filtered by name. The stem the game asks for is
#: `cfm_tongyong_daojukuang_<colour>`; the other spelling (`tongyong_cfm_…`) is an
#: older duplicate the client no longer names, kept out on purpose.
FRAME_STEM = "cfm_tongyong_daojukuang_"


def _wanted(category: str, stem: str) -> bool:
    if category == "frame":
        return stem.startswith(FRAME_STEM)
    return True


def main() -> int:
    default_gameres = Path(game_paths.gameres())
    default_cache = Path(game_paths.asset_cache())

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gameres", type=Path, default=default_gameres)
    ap.add_argument("--cache", type=Path, default=default_cache)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "results" / "item_icons")
    ap.add_argument("--sets", default=None,
                    help="comma-separated sets instead of both: "
                         + ", ".join(sorted(SET_PREFIXES)))
    args = ap.parse_args()

    if args.sets:
        chosen = [name.strip() for name in args.sets.split(",") if name.strip()]
        unknown = [name for name in chosen if name not in SET_PREFIXES]
        if unknown:
            sys.exit(f"unknown set(s): {', '.join(unknown)} — "
                     f"pick from {', '.join(sorted(SET_PREFIXES))}")
        categories = {name: SET_PREFIXES[name] for name in chosen}
    else:
        categories = dict(SET_PREFIXES)

    if not args.gameres.exists():
        sys.exit(f"gameres index not found: {args.gameres}")
    if not args.cache.exists():
        sys.exit(f"bundle cache not found: {args.cache}")

    sections = gameres_index.read_sections(args.gameres)
    file_target, bundle_sprites = gameres_index.build_targets(
        sections, categories, name_filter=_wanted)
    print(f"Sprites in index: {len(file_target)} across {len(bundle_sprites)} bundles")

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
            dest = args.out / cat / f"{gameres_index.sanitize(name)}.png"
            # The same sprite name can appear in more than one bundle (a dynamic atlas
            # rebuild leaves the old one behind). The first one wins and the rest are
            # skipped — unlike the hero extractor, which numbers them, because here the
            # file name IS the lookup key the panel uses.
            if dest.exists():
                got_names.add(name)
                continue
            try:
                img = data.image
            except Exception as exc:  # noqa: BLE001
                print(f"  ! image failed for {name}: {exc}")
                continue
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
        print(f"  ({len(not_found)} indexed sprite names not recovered — "
              f"likely in uncached bundles)")
    print(f"\nOutput: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
