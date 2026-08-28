"""The game's own picture for a kind of banner, as a name the phone can ask for (#2055).

The fifth door of the shape `panel/runtime/errand_art.py` opened (#2019), and it exists
for the same reason: the panel must not reach into `tools/lib` from five callers, and the
answer must never be an exception. A machine that has not run the extractor has no
pictures, every lookup answers `""`, and the cards draw with no picture — which is what
they look like now, not a fault.

WHICH COLUMN OF THE CONFIG NAMES THE SPRITE WAS SETTLED BY READING IT (#2051,
`docs/research/rally-monster-groups.md`): `worldmap_icon` is the shared MAP PIN — one
value on most of the seasonal line — and `pic_name` is the species' own picture, a
portrait for the seasonal monsters and a world prefab for the older ones, which is what
`docs/research/golden-zombies.md` saw. The map is `tools/data/monster_icons.json`, kind ->
sprite stem, generated from that read: a portrait where a kind has one, and among
portraits the newest season's, because a kind that has run six seasons should draw the
face the player is looking at now.
"""
from __future__ import annotations

import urllib.parse as _url


def name_for(kind: str) -> str:
    """The LINK the phone draws for one kind, or `""` when this machine has no picture.

    A link and not a blob, for the reason every other picture on these screens is one: a
    sprite is tens of kilobytes and the page is polled, so the browser fetches it once and
    keeps it (`panel/runtime/errand_art.py`).
    """
    try:
        import monster_icons

        name = monster_icons.name_for(kind)
    except Exception:                    # noqa: BLE001 — a picture, never the page
        return ""
    if not name:
        return ""
    return "/api/monstericon?icon=" + _url.quote(name)
