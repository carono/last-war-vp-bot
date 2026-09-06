"""The game's own picture for one phase of «Гонка вооружений» (#2579).

The sixth door of the shape `panel/runtime/errand_art.py` opened (#2019) and
`monster_art.py` copied (#2055), and it exists for the same two reasons: the panel must
not reach into `tools/lib` from several callers, and the answer must never be an
exception. A machine that has not run `tools/extract_arms_icons.py` has no pictures,
every lookup answers `""`, and the sheet behind the «i» draws its rows with no picture —
which is not a fault, it is a panel without art.

THE MAP IS FOUR PHASES AND NOT FIVE, on purpose. `tools/data/arms_icons.json` names the
hero, the building, the soldier and the research globe, which are the four pictures in
the client's own art folder that unmistakably belong to a phase. The drone's is not among
them and is left out rather than given the nearest-looking one — the same rule the errand
covers keep: a wrong icon is worse than none.
"""
from __future__ import annotations

import urllib.parse as _url


def name_for(kind) -> str:
    """The LINK the phone draws for one phase, or `""` when there is no picture.

    A link and not a blob, for the reason every other picture on these screens is one: the
    page is polled and a sprite is tens of kilobytes, so the browser fetches it once and
    keeps it.
    """
    try:
        import arms_icons

        name = arms_icons.name_for(str(kind or ""))
    except Exception:                    # noqa: BLE001 — a picture, never the page
        return ""
    if not name:
        return ""
    return "/api/armsicon?icon=" + _url.quote(name)
