"""The game's own picture for an errand, as a name the phone can ask for (#2019).

A three-line door onto `tools/lib/errand_icons.py`, and it exists for the reason every
other such door in `panel/runtime/` does: the panel must not import a tool by reaching
into `tools/lib` from five callers, and the answer must never be an exception. A machine
that has not run `tools/extract_errand_icons.py` has no pictures, every lookup answers
`""`, and the page draws blocks with no icon — which is what it looked like before.
"""
from __future__ import annotations

import urllib.parse as _url


def name_for(errand: str) -> str:
    """The LINK the phone draws, or `""` when this machine has no such picture.

    A link and not a blob: a sprite is tens of kilobytes and the timers page is polled,
    so the picture is fetched once by the browser and cached, exactly as a player's face
    and an inventory cell already are (`panel/tabs/rally/roster.py`,
    `panel/tabs/inventory.py`).
    """
    try:
        import errand_icons

        name = errand_icons.name_for(errand)
    except Exception:                    # noqa: BLE001 — a picture, never the page
        return ""
    if not name:
        return ""
    return "/api/errandicon?icon=" + _url.quote(name)


def cover_for(errand: str) -> str:
    """The CARD-SIZED picture for an errand, or `""` when this machine has none (#2340).

    A cover is not the game's sprite: it is a picture drawn FROM that sprite by
    `tools/generate_errand_art.py`, sized for the card rather than for a corner of it. A
    card that has one draws it at full brightness and in full colour, with no wash over
    the picture — which is only honest for a picture composed for the card, and is why the
    two are told apart here rather than in the stylesheet.
    """
    try:
        import errand_icons

        name = errand_icons.cover_name_for(errand)
    except Exception:                    # noqa: BLE001 — a picture, never the page
        return ""
    if not name:
        return ""
    return "/api/errandicon?art=" + _url.quote(name)


def cover_focus(errand: str) -> str:
    """Where the card crops that cover — a CSS vertical position, or `""` (#2340).

    A cover is square and a card is a wide band, so a stripe of the picture is what is
    seen; which stripe is a fact about the picture and travels with it.
    """
    try:
        import errand_icons

        return errand_icons.cover_focus(errand)
    except Exception:                    # noqa: BLE001 — a picture, never the page
        return ""
