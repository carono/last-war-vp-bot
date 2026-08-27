"""Extract the sprites the timers page draws beside each errand (#2019).

The third extractor of the same shape as ``extract_hero_icons.py`` and
``extract_chat_assets.py``, and for the same reason: the pictures are the GAME's own
art, they are pulled out of the client's cached bundles on the machine that owns the
game, and they land in ``results/`` — which is git-ignored, so nobody's install ships
anywhere.

WHAT IT TAKES. Exactly the stems named in ``tools/data/errand_icons.json`` (the map the
panel reads: errand -> sprite stem), plus anything given with ``--extra`` — which is how
the map was chosen in the first place: pull a shortlist, look at it, keep what depicts
the thing.

Run with the Windows Python that can see both the install and the bundle cache::

    /mnt/c/Python312/python.exe tools/extract_errand_icons.py
    /mnt/c/Python312/python.exe tools/extract_errand_icons.py --extra cfm_zhujiemian_qizi

Nothing here knows where the game is: ``tools/lib/game_paths.py`` answers that, so a
machine that keeps its bundles on another drive needs no edit here (`CLAUDE.md`).
"""

from __future__ import annotations

import argparse
import json
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

#: Where the sprites live. Named as CATEGORIES rather than searched blindly, because the
#: index holds 105 000 paths and opening every bundle that might carry a name would be
#: minutes rather than seconds.
PREFIXES = {
    "item": "Assets/Main/Sprites/ItemIcons",
    "main": "Assets/Main/Sprites/UI/UIMain/LWMainUI",
    "build": "Assets/Main/Sprites/UI/UIBuildBtns",
    "lod": "Assets/Main/Sprites/LodIcon",
    "common": "Assets/Main/Sprites/UI/LWCommon/Sprite",
    "alliance": "Assets/Main/Sprites/UI/UILWAlliance",
    "radar": "Assets/Main/Sprites/UI/UIRadarCenter",
}

MAP_PATH = os.path.join(_HERE, "data", "errand_icons.json")


def wanted_stems(extra=()) -> set:
    """Every sprite stem the panel would draw, plus whatever exploration asked for."""
    want = set(str(s) for s in extra if s)
    try:
        with open(MAP_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return want
    for value in (data.get("icons") or {}).values():
        if value:
            want.add(str(value))
    return want


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gameres", type=Path, default=Path(game_paths.gameres()))
    ap.add_argument("--cache", type=Path, default=Path(game_paths.asset_cache()))
    ap.add_argument("--out", type=Path,
                    default=Path(_HERE).parent / "results" / "errand_icons")
    ap.add_argument("--extra", default="",
                    help="comma-separated sprite stems to pull as well (exploration)")
    args = ap.parse_args(argv)

    if not args.gameres.exists():
        sys.exit(f"gameres index not found: {args.gameres}")
    if not args.cache.exists():
        sys.exit(f"bundle cache not found: {args.cache}")

    want = wanted_stems([s.strip() for s in args.extra.split(",") if s.strip()])
    if not want:
        sys.exit("nothing to extract: the map is empty and no --extra was given")

    sections = gameres_index.read_sections(args.gameres)
    _files, bundle_sprites = gameres_index.build_targets(
        sections, PREFIXES, name_filter=lambda _cat, stem: stem in want)
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"wanted {len(want)} stems across {len(bundle_sprites)} bundles")

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
            if obj.type.name != "Sprite":
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
            image.save(args.out / f"{gameres_index.sanitize(name)}.png")
            got.add(name)
            saved += 1

    print(f"saved {saved} sprite(s) into {args.out}")
    if missing:
        print(f"{missing} bundle(s) are not in this machine's cache — "
              "open the screens that use them in the game and run this again")
    for stem in sorted(want - got):
        print(f"  missing: {stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
