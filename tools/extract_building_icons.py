"""Extract the game's own picture of every base building (#2632).

The seventh extractor of the same shape as ``extract_arms_icons.py`` and
``extract_monster_icons.py``, and for the same reason: the pictures are the GAME's own
art, they are pulled out of the client's cached bundles on the machine that owns the
game, and they land in ``results/`` — which is git-ignored, so nobody's install ships
anywhere.

WHAT IT TAKES. Everything under the client's ``BuildIconOutCity`` tree — the sprite a
building draws in the game's own lists, one per building id and per art revision
(``UI_building_10310000``). There is no map to keep and nothing to choose: the client
answers which sprite a building wears itself, through
``BuildManager:GetBuildIconPath(buildId, level)``, and the recipe that reads a finished
building carries the stem along with it (`actions/read_ready_buildings.md`).

Run with the Windows Python that can see both the install and the bundle cache::

    /mnt/c/Python312/python.exe tools/extract_building_icons.py
    /mnt/c/Python312/python.exe tools/extract_building_icons.py --only UI_building_10310000

Nothing here knows where the game is: ``tools/lib/game_paths.py`` answers that, so a
machine that keeps its bundles on another drive needs no edit here (`CLAUDE.md`).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import UnityPy
except ImportError:  # pragma: no cover — the extractor is a tool, not a panel import
    sys.exit("UnityPy is required: python -m pip install --user UnityPy")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "lib"))

import game_paths        # noqa: E402  (where the game is — LW_GAMERES & co)
import gameres_index     # noqa: E402

UnityPy.config.FALLBACK_UNITY_VERSION = "2019.4.40f1"

#: Where the buildings' own list sprites live. One tree, named rather than searched: the
#: index holds a hundred thousand paths and opening every bundle that might carry a name
#: would be minutes rather than seconds.
PREFIXES = {"build": "Assets/Main/Sprites/BuildIconOutCity"}

#: The longest side a saved picture may have. These sprites are already small; the cap is
#: here for the same reason the other extractors carry one — a row on a phone is 40 px.
MAX_SIDE = 256


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gameres", type=Path, default=Path(game_paths.gameres()))
    ap.add_argument("--cache", type=Path, default=Path(game_paths.asset_cache()))
    ap.add_argument("--out", type=Path,
                    default=Path(_HERE).parent / "results" / "building_icons")
    ap.add_argument("--only", default="",
                    help="comma-separated sprite stems to pull instead of the whole tree")
    args = ap.parse_args(argv)

    if not args.gameres.exists():
        sys.exit(f"gameres index not found: {args.gameres}")
    if not args.cache.exists():
        sys.exit(f"bundle cache not found: {args.cache}")

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    sections = gameres_index.read_sections(args.gameres)
    _files, bundle_sprites = gameres_index.build_targets(
        sections, PREFIXES,
        name_filter=(lambda _cat, stem: stem in only) if only else None)
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"{len(bundle_sprites)} bundle(s) hold the buildings' sprites")

    saved, missing = 0, 0
    got = set()
    for real, sprites in sorted(bundle_sprites.items()):
        path = args.cache / real
        if not path.exists():
            missing += 1
            continue
        try:
            env = UnityPy.load(str(path))
        except Exception as exc:              # noqa: BLE001 — one bundle, not the run
            print(f"  ! load failed {real[:12]}: {exc}")
            continue
        for obj in env.objects:
            if obj.type.name not in ("Sprite", "Texture2D"):
                continue
            try:
                data = obj.read()
            except Exception:                 # noqa: BLE001
                continue
            name = getattr(data, "m_Name", "")
            if name not in sprites or name in got:
                continue
            try:
                image = data.image
            except Exception as exc:          # noqa: BLE001
                print(f"  ! image failed for {name}: {exc}")
                continue
            if max(image.size) > MAX_SIDE:
                scale = MAX_SIDE / max(image.size)
                image = image.resize((max(1, round(image.width * scale)),
                                      max(1, round(image.height * scale))))
            image.save(args.out / f"{gameres_index.sanitize(name)}.png")
            got.add(name)
            saved += 1

    print(f"saved {saved} sprite(s) into {args.out}")
    if missing:
        print(f"{missing} bundle(s) are not in this machine's cache — "
              "open the screens that use them in the game and run this again")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
