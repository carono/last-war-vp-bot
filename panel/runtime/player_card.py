"""Who is playing this profile — the card the header draws, and the one it REMEMBERS.

WHY IT IS REMEMBERED (#2061). The header reads the character's name and HQ level out of
the client's own object (`actions/read_player_profile.md`), which means a profile whose
client is closed — or which is not open in this window at all — has nothing to show. The
person asked the account picker to be a list of «всех доступных аккаунтов с их аватарами,
уровнями и никами», and a list that draws only the accounts that happen to be running is
not that list.

So every reading is written down, once, in the ONE database (#2025) under that profile's
own scope: the name, the HQ level, the character's id and which upload of their picture
is current, plus WHEN it was read. It is a few dozen bytes per account, written on a
reading the panel was taking anyway, and it is what lets a closed profile draw as itself
rather than as a bare directory name.

WHAT IT IS NOT. It is not a second copy of the truth: an OPEN profile always draws from
the live header (`panel/runtime/header.py`), and this is consulted only where there is no
live reading to consult. A remembered card is therefore never fresher than the game, and
a card that turns out to be stale is corrected by the first reading the profile takes
after it opens.

THE AVATAR IS NOT KEPT HERE. The picture lives in the shared face folder the whole panel
uses (`tools/lib/player_faces.py`, `game_paths.avatar_cache()`), and what travels to the
front-end is a LINK into `/api/avatar` — never the bytes, and never the uid, which stays
on this side of the wire.
"""
from __future__ import annotations

import os
import time

#: The row a profile's card lives in, inside that profile's own scope.
BLOB = "player_card"


def remember(store, nick: str, level: int, uid: str = "", pic_ver: int = 0,
             now: float | None = None) -> None:
    """Write down what the header just read. A reading with no name is not written.

    Deliberately forgiving about everything else: a client that answered with a name and
    nothing else is still worth remembering, because the name is what a person picks an
    account by.
    """
    if store is None or not str(nick or "").strip():
        return
    try:
        store.blob_set(BLOB, {"nick": str(nick).strip(), "level": int(level or 0),
                              "uid": str(uid or ""), "pic_ver": int(pic_ver or 0),
                              "at": float(now if now is not None else time.time())})
    except Exception:                        # noqa: BLE001 — a note, never the reading
        pass


def recall(store) -> dict:
    """The last card written for this profile, or `{}` — never an exception."""
    try:
        said = store.blob_get(BLOB) if store is not None else None
    except Exception:                        # noqa: BLE001 — a reading, never the page
        return {}
    return dict(said) if isinstance(said, dict) else {}


def recall_for(profiles_dir: str, profile: str) -> dict:
    """The same, for a profile this window does not have OPEN (#2061).

    There is one database for every account since #2025, so a closed profile's card is a
    row in it and needs no profile to be opened, no client to be running and no lock to be
    taken. A tree with no database yet answers `{}`, which draws as a name and no face.
    """
    from . import store as storemod

    path = os.path.join(profiles_dir, storemod.DB_FILE)
    if not os.path.exists(path):
        return {}
    store = None
    try:
        store = storemod.Store(path, profile)
        return recall(store)
    except Exception:                        # noqa: BLE001 — a reading, never the page
        return {}
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:                # noqa: BLE001 — closing, never the panel
                pass


def face_link(uid: str, pic_ver: int = 0) -> str:
    """The picture this character draws, as a link the phone can ask for — or `""`.

    The same route, the same folder and the same rules every other face on this panel
    already uses (`panel/tabs/rally/roster.py::face_url`): the browser fetches it once and
    keeps it, and only the file's NAME travels — the character's id stays here.

    A character who never uploaded a photo has no picture at all. There is no head-icon id
    on the client's own character object (probed, #2061), so the honest answer is «no
    face» and the front-end draws the account's initial — never somebody else's art.
    """
    uid = str(uid or "").strip()
    if not uid:
        return ""
    try:
        import player_faces

        path = player_faces.face_for(uid)
    except Exception:                        # noqa: BLE001 — a picture, never the page
        return ""
    if not path:
        return ""
    import urllib.parse as _url

    return "/api/avatar?face=" + _url.quote(os.path.basename(path))
