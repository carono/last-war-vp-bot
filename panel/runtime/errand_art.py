"""The picture drawn for an errand's card, as a name the phone can ask for (#2019).

THERE IS ONE KIND OF PICTURE HERE, AND THERE USED TO BE TWO (#2407). A card fell back on
the game's own SPRITE when this machine had no cover for the errand, and drew that under
a darkening wash — so which of two drawings a card got was decided by which files a disk
happened to hold. `name_for()` is gone with that fallback: a card with no cover draws the
one placeholder, and no page of this front-end has a second format to add to.

A three-line door onto `tools/lib/errand_icons.py`, and it exists for the reason every
other such door in `panel/runtime/` does: the panel must not import a tool by reaching
into `tools/lib` from five callers, and the answer must never be an exception. A machine
that has not run `tools/extract_errand_icons.py` has no pictures, every lookup answers
`""`, and the page draws blocks with no icon — which is what it looked like before.
"""
from __future__ import annotations

import urllib.parse as _url


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
