"""Which of the game's own sprites stands for which errand, and where it is on disk.

The reading half of `tools/extract_errand_icons.py` (#2019). The map is
``tools/data/errand_icons.json`` — errand name -> sprite stem — and the sprites are the
client's own art extracted into ``results/errand_icons``, which is git-ignored: the game's
pictures never leave the machine that owns the game.

WITH NOTHING EXTRACTED EVERY LOOKUP ANSWERS ``None`` and the panel draws a block with no
picture, exactly as it did before. That is deliberate and it is the same contract
`item_icons.py` and `chat_assets.py` keep: an installation that has not run the extractor
is not a broken panel, it is a panel without pictures.

Nothing here imports the panel, touches the game or downloads anything — it is a JSON
file and an ``os.path.isfile``.
"""

from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
#: This module lives in `tools/lib`, so the repository is TWO levels up — the mistake
#: `hero_icons_map.py` shipped with once (#1305).
_ROOT = os.path.dirname(os.path.dirname(_HERE))

ICON_ROOT = os.path.join(_ROOT, "results", "errand_icons")
MAP_PATH = os.path.join(_ROOT, "tools", "data", "errand_icons.json")

_map: "dict | None" = None


def _icons() -> dict:
    """The map, read once. A missing or mangled file is «no pictures», never a crash."""
    global _map
    if _map is None:
        try:
            with open(MAP_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            icons = data.get("icons")
            _map = {str(k): str(v) for k, v in icons.items()} if isinstance(icons, dict) else {}
        except (OSError, ValueError, AttributeError):
            _map = {}
    return _map


def forget() -> None:
    """Drop the cached map — for a test that writes its own."""
    global _map
    _map = None


def stem_for(errand: str) -> str:
    """The sprite stem an errand draws, or ``""`` when it has none."""
    return _icons().get(str(errand or ""), "")


def name_for(errand: str) -> str:
    """The file name the phone asks for, or ``""`` when there is nothing on disk.

    Checked against the FOLDER and not merely the map: an errand named in the map whose
    sprite this machine never extracted must answer «no picture» rather than a link that
    404s on every block of the page.
    """
    stem = stem_for(errand)
    if not stem:
        return ""
    name = stem + ".png"
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
