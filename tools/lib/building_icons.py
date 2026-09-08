"""The pictures the game draws for the base's own buildings (#2632).

The reading half of `tools/extract_building_icons.py`, and the seventh route of the
shape `item_icons.py` / `monster_icons.py` / `arms_icons.py` already keep. The sprites
are the client's own art extracted into ``results/building_icons``, which is git-ignored:
the game's pictures never leave the machine that owns the game.

THERE IS NO MAP HERE, and that is the whole difference from `arms_icons.py`. A building's
sprite is not something anybody has to decide: the client answers it itself —
`BuildManager:GetBuildIconPath(buildId, level)` gives a full asset path, and the last part
of it is the stem this folder is filled with (`UI_building_10310000`). So the recipe that
reads a finished building carries its own picture's name, and nothing in the repository
holds an opinion about which picture belongs to which building.

WITH NOTHING EXTRACTED EVERY LOOKUP ANSWERS ``None`` and the row draws with no picture,
exactly as it did before — the same contract every other picture route here keeps. A
building the game named a sprite for that this machine never extracted draws NOTHING
rather than the nearest picture: «нет иконки — заглушка, чужую картинку не подставлять».

Nothing here imports the panel, touches the game or downloads anything — it is an
``os.path.isfile``.
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
#: This module lives in `tools/lib`, so the repository is TWO levels up.
_ROOT = os.path.dirname(os.path.dirname(_HERE))

ICON_ROOT = os.path.join(_ROOT, "results", "building_icons")


def name_for(stem: str) -> str:
    """The file name the phone asks for, or ``""`` when there is nothing on disk.

    Checked against the FOLDER and not merely spelled out: a stem the game named whose
    sprite this machine never extracted must answer «no picture» rather than a link that
    404s on every row of the list.
    """
    clean = str(stem or "").strip()
    if not clean:
        return ""
    name = clean if clean.lower().endswith(".png") else clean + ".png"
    return name if file_named(name) else ""


def file_named(name: str) -> "str | None":
    """A bare file name back into a path inside the icon folder, or ``None``.

    The same three checks `item_icons.file_named` makes and for the same reason: the
    route is reachable from a phone, so the name must be a plain name, carry the one
    suffix this folder holds, and land INSIDE the folder.
    """
    clean = str(name or "").strip()
    if not clean or clean != os.path.basename(clean) or clean.startswith("."):
        return None
    if os.path.splitext(clean)[1].lower() != ".png":
        return None
    root = os.path.abspath(ICON_ROOT)
    full = os.path.abspath(os.path.join(root, clean))
    if os.path.dirname(full) != root or not os.path.isfile(full):
        return None
    return full
