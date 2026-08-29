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
    # The game's «clear devices» screen — the only place in the client with a picture of
    # a DEVICE, which is what the session kick is about (#2061).
    "device": "Assets/Main/Sprites/UI/UIDeviceManage",
    # …and the building-helper screens, which hold the game's own PICTURE of each
    # building. Its bundles are downloaded only when somebody opens that screen in the
    # game, so a machine may simply not have them.
    "helper": "Assets/Main/Sprites/UI/LWUIBuildingHelper",
    # …AND THE BUILDINGS' OWN ART (#2061, «ищи сам спрайт с таверной»). A base building
    # has no icon anywhere in the UI — but the texture beside its model is not the
    # unwrapped UV sheet one expects: the client ships a RENDERED isometric picture of
    # each building, on transparency, and that is the picture of the thing. It is what
    # the tavern draws.
    # Broad on purpose: the buildings' art is filed under several trees (a season's
    # increment, the environment models), and the name filter is what narrows it.
    "model": "Assets/_Art_LastWar",
}

MAP_PATH = os.path.join(_HERE, "data", "errand_icons.json")

#: The longest side a saved picture may have. The errands' own sprites are 40–120 px; a
#: building's rendered art is nearly a thousand, and the card that draws it is 150 px
#: tall on a phone.
MAX_SIDE = 256


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
            # A SPRITE OR A TEXTURE. Everything the UI draws is a Sprite; a building's
            # own rendered picture is a Texture2D beside its model (#2061), and both are
            # read the same way.
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
            # A CARD IS 150 px TALL, and a building's own render is a thousand across —
            # 685 KB fetched by a phone to draw a thumbnail (#2061). Anything oversized is
            # shrunk on the way out; the UI sprites are already smaller than the cap and
            # pass through untouched.
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
    for stem in sorted(want - got):
        print(f"  missing: {stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
