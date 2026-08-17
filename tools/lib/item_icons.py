#!/usr/bin/env python3
"""Draw one inventory cell the way the game draws it: a rarity frame with a picture on it.

The game's bag composes every cell out of TWO sprites, and the panel copies that instead
of inventing a border of its own — the item's own picture (``template.icon``, the `icon`
field ``read_inventory.md`` reports) laid over the frame its rarity picks
(``GetToolBgByColor(colour)``). See docs/research/inventory.md.

Both sprites come out of the client's own bundles into ``results/item_icons`` —
``tools/extract_item_icons.py`` puts them there, and ``results/`` is git-ignored, so the
art never leaves the machine that owns the game. Nothing here downloads anything: with no
extraction done, every lookup answers ``None`` and the caller draws a glyph instead.

The composed cell is cached as a PNG of its own (``cells/``) because a bag of several
hundred items is repainted on every keystroke in the tab's search box, and both the Tk
window and the phone ask for the same picture.
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
#: This module lives in `tools/lib`, so the repository is TWO levels up — the mistake
#: `hero_icons_map.py` shipped with for a while (#1305), not repeated here.
_ROOT = os.path.dirname(os.path.dirname(_HERE))

ICON_ROOT = os.path.join(_ROOT, "results", "item_icons")
ITEM_DIR = os.path.join(ICON_ROOT, "item")
FRAME_DIR = os.path.join(ICON_ROOT, "frame")
CELL_DIR = os.path.join(ICON_ROOT, "cells")

#: The frame sprite the game asks for, by rarity colour (1..6).
FRAME_STEM = "cfm_tongyong_daojukuang_"

#: How much of the plate the picture takes up. MEASURED, not chosen: the frames are
#: authored 162 px wide and every item picture 154 px square, so the game's own ratio is
#: 154/162. Composing at anything else would be the panel deciding how the game's bag
#: ought to look.
INSET = 154.0 / 162.0

#: What a cell is drawn at, in pixels, when nobody says. Both front-ends ask for this
#: one size, so the cache holds one file per (icon, colour) in practice.
DEFAULT_PX = 56


def available() -> bool:
    """True when the sprites have been extracted on this machine."""
    return os.path.isdir(ITEM_DIR) and os.path.isdir(FRAME_DIR)


def icon_file(icon: str) -> "str | None":
    """The item picture named on the config row, or ``None`` if it was not extracted."""
    name = str(icon or "").strip()
    if not name or name != os.path.basename(name) or name.startswith("."):
        return None
    path = os.path.join(ITEM_DIR, name + ".png")
    return path if os.path.isfile(path) else None


def frame_file(colour) -> "str | None":
    """The rarity frame for ``colour`` (1..6), or ``None``."""
    try:
        number = int(str(colour).strip())
    except (TypeError, ValueError):
        return None
    if not 1 <= number <= 6:
        return None
    path = os.path.join(FRAME_DIR, f"{FRAME_STEM}{number}.png")
    return path if os.path.isfile(path) else None


def cell_name(icon: str, colour, px: int = DEFAULT_PX) -> str:
    """The file name a composed cell is cached under — also the web route's key."""
    safe = str(icon or "").strip() or "unknown"
    try:
        number = int(str(colour).strip())
    except (TypeError, ValueError):
        number = 0
    return f"{safe}_{number}_{int(px)}.png"


def cell(icon: str, colour, px: int = DEFAULT_PX) -> "str | None":
    """Compose (once) and return the path to one inventory cell, or ``None``.

    ``None`` means «draw a glyph»: no extraction on this machine, an icon the extraction
    did not recover, or no PIL. It is never an error — the tab has a fallback and a
    missing picture must not cost anybody their inventory list.

    A cell whose rarity is unknown is still drawn: the picture alone, on nothing.

    The plate is not square — the frames are 162×170, the extra height is where the game
    prints the count — so the composed cell keeps that ratio and ``px`` is its WIDTH.
    """
    picture = icon_file(icon)
    if picture is None:
        return None
    dest = os.path.join(CELL_DIR, cell_name(icon, colour, px))
    if os.path.isfile(dest):
        return dest
    try:
        from PIL import Image
    except Exception:                       # noqa: BLE001 — no PIL is a glyph, not a crash
        return None
    try:
        width = max(8, int(px))
        art = Image.open(picture).convert("RGBA")
        back = frame_file(colour)
        if back is None:
            canvas = art.resize((width, width), Image.LANCZOS)
        else:
            plate = Image.open(back).convert("RGBA")
            fw, fh = plate.size
            canvas = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
            canvas.alpha_composite(plate)
            inner = max(1, int(round(fw * INSET)))
            canvas.alpha_composite(art.resize((inner, inner), Image.LANCZOS),
                                   ((fw - inner) // 2, (fh - inner) // 2))
            canvas = canvas.resize((width, max(1, round(width * fh / fw))), Image.LANCZOS)
        os.makedirs(CELL_DIR, exist_ok=True)
        canvas.save(dest)
    except Exception:                       # noqa: BLE001 — one picture, never the panel
        return None
    return dest


def file_named(name: str) -> "str | None":
    """A bare cell file name back into a path inside ``cells/``, or ``None``.

    The web front-end links a cell by NAME (`panel/tabs/inventory.py`), and this is the
    half that resolves one. Three checks and not one, for the reason
    `player_faces.file_named` has three: the route is reachable from a phone, so the
    name must be a plain name, carry the one suffix this folder holds, and land INSIDE
    the folder.
    """
    clean = str(name or "").strip()
    if not clean or clean != os.path.basename(clean) or clean.startswith("."):
        return None
    if os.path.splitext(clean)[1].lower() != ".png":
        return None
    root = os.path.abspath(CELL_DIR)
    full = os.path.abspath(os.path.join(root, clean))
    if os.path.dirname(full) != root or not os.path.isfile(full):
        return None
    return full
