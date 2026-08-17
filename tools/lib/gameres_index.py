#!/usr/bin/env python3
"""Read Last War's ``gameres`` asset index and say which bundle holds which sprite.

The game ships one text index (``StreamingAssets/AssetBundles/gameres``) describing
every logical asset, and caches the downloaded UnityFS bundles flat as
``<sha256>.bundle``. The index's sections are::

    [Directories]  dirIndex, logical/folder/path
    [Paths]        fileIndex, dirIndex, filename
    [Bundles]      bundleIndex, unityName, crc, size, fileIndices, ?, flags, <sha256>.bundle

Two extractors need exactly the same three steps — read the sections, decide which
sprite names are wanted, work out which bundles carry them — so the steps live here
rather than in either of them (``tools/extract_hero_icons.py`` for the heroes,
``tools/extract_item_icons.py`` for the bag).

Nothing in this module knows where the game is installed: the caller asks
``tools/lib/game_paths.py`` and hands over a path.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The index's section tags, in the order the file happens to use them. Unknown tags
#: are ignored rather than fatal — a later build may add one.
SECTIONS = ("Version", "Directories", "Paths", "Bundles", "Groups")


def read_sections(gameres: "Path | str") -> dict:
    """Return ``{sectionName: [lines…]}`` for the gameres text index."""
    data = Path(gameres).read_bytes()
    positions = {t: data.find(f"[{t}]".encode()) for t in SECTIONS}
    positions = {t: p for t, p in positions.items() if p >= 0}
    order = sorted(positions, key=lambda t: positions[t])
    out = {}
    for i, tag in enumerate(order):
        start = positions[tag]
        end = positions[order[i + 1]] if i + 1 < len(order) else len(data)
        out[tag] = data[start:end].decode("latin-1").splitlines()[1:]
    return out


def sanitize(name: str) -> str:
    """A sprite name made safe to use as a file name on any of the three platforms."""
    name = name.strip() or "unnamed"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


def build_targets(sections: dict, categories: dict, name_filter=None):
    """Map the index onto the sprites a caller wants.

    ``categories`` is ``{categoryName: logicalDirPrefix}``. ``name_filter``, when given,
    is called as ``name_filter(category, spriteName)`` and only the names it accepts are
    kept — which is how the rarity frames are picked out of a directory holding several
    thousand other common-UI sprites without extracting all of them.

    Returns ``(file_target, bundle_sprites)``:

    * ``file_target``   — ``{fileIndex: (category, spriteName)}``
    * ``bundle_sprites`` — ``{bundleSha256: {spriteName: category}}``
    """
    dir_cat = {}
    for line in sections.get("Directories", []):
        if not line.strip():
            continue
        idx, path = line.split(",", 1)
        for cat, prefix in categories.items():
            if path == prefix or path.startswith(prefix + "/"):
                dir_cat[int(idx)] = cat
                break

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
        if name_filter is not None and not name_filter(cat, stem):
            continue
        file_target[fidx] = (cat, stem)

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
            target = file_target.get(int(s))
            if target:
                cat, stem = target
                bundle_sprites.setdefault(real, {})[stem] = cat
    return file_target, bundle_sprites
