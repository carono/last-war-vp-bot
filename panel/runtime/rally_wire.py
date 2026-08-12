"""What the wire has said about the banners standing on the map, per profile (#1323).

WHY THIS EXISTS. A rally's KIND — which monster the banner is going for — is
`targetContentId`, and that field lives on `push.alliance.march.*` and in nothing the
client keeps: 25 of the push's 33 fields survive into `GetAllMarches()` and this is not
one of them, and `GetMonsterData(targetUuid)` answers nil while the map around the target
is not streamed in (docs/research/rally-join.md). So the wire is the ONLY place a
banner's kind can be known before a squad is spent, and the panel has to remember what it
heard.

Until now it remembered it in ONE place: `RallyTab._targets`, filled by the «Ралли» tab's
own capture child. A profile whose window does not show that tab has no such child and no
such dict — and the auto-join trigger, which is a standing order of the SCHEDULE and runs
whether or not any tab is drawn, then joined banner after banner with `targets = ""`.
Every one of them classified as the fallback `monster`, every join counted under that one
key, and every per-kind cap the person had set left at zero for ever. Live on 2026-08-12:
one profile counted `general_trial_elite`, `doom_elite`, `doom_walker` and `sky_predator`
apart and capped them; the other counted `monster: 15` and nothing else, joined all day,
and its log said `unclassified=1` in a sentence that blamed the event lists.

So the book moves to the runtime, beside the ear that hears the pushes:

* `panel/runtime/wire.py` runs the one capture this profile has with `--fields
  push.alliance.march`, and hands every fields line here;
* the join's argument providers ask for the three maps in the shapes
  `actions/join_rally.md` parks them in.

**THE TAB IS STILL THE RICHER SOURCE and still wins.** Its own capture is not cooled down
at all and it hears the same pushes; where both have an entry for a banner, the tab's is
used (:func:`merge`). This is the floor under it, not a replacement for it.

**NOT the same thing as `panel/tabs/rally/roster.py` (#1324),** which draws the banners
standing right now — states, seats, faces, compositions read back out of the client. That
is a screen belonging to a tab, and it disappears with the tab exactly as `_targets` does.
This is three maps and no screen, kept for the one caller that must work without one.

NOTHING HERE IS A PERSON. The fields line carries `team`, `content`, `slots` and `join` —
uuids of things and counts — because the child builds it from an allow-list and never
from the payload (#1293, `tools/wire_event_monitor.py`). Nothing in this file may start
keeping a name, a uid or an alliance id: the maps it hands over are pasted into a Lua
chunk and echoed into the profile's log.

A PROFILE'S OWN, like everything else on the runtime (CLAUDE.md, «A profile is a whole
panel of its own»): one book per runtime, fed only by that profile's ear, which is
narrowed to that profile's client (#1306).
"""
from __future__ import annotations

import threading
import time

#: How long a heard ADDRESS is offered to a join for. A banner gathers for a minute at
#: most — `waitTime` is 60 s after `createTime` on every push measured — so an older
#: entry stands for a banner that has left or come down, and by then the client's own
#: march table is the authority anyway. The same number the «Ралли» tab keeps for the
#: same reason (`panel/tabs/rally/tab.py::POINT_TTL_SEC`); it is written twice because
#: the runtime may not import a tab, and it means the same thing in both.
POINT_TTL_SEC = 60.0

#: How long a banner is remembered AT ALL. A target and a seat count age far better than
#: an address — the client's march table catches up with the banner and keeps it alive
#: for the whole gathering, and a rally that has been joined and fought is simply gone
#: from every list the join reads — but a book nothing ever forgets is a leak in a
#: process that runs for weeks.
BANNER_TTL_SEC = 900.0


def _pairs(raw: str) -> dict:
    """`"a:1,b:2"` -> `{"a": "1", "b": "2"}`; anything unreadable is dropped."""
    out: dict = {}
    for part in str(raw or "").split(","):
        key, sep, value = part.strip().partition(":")
        if sep and key.strip() and value.strip():
            out[key.strip()] = value.strip()
    return out


def merge(primary: str, fallback: str) -> str:
    """Two `key:value,…` maps as one, with ``primary`` winning per banner.

    The tab's own capture and the profile's wire ear hear the same pushes, and either
    may be the only one running: the tab has no child in a window that does not show it,
    and the ear has none while every wire trigger is switched off. A banner known to
    both must appear once, and the tab's answer is the one kept — it is not cooled down
    at all, so its entry is the fresher of the two whenever they differ.
    """
    merged = _pairs(fallback)
    merged.update(_pairs(primary))
    return ",".join(f"{key}:{value}" for key, value in merged.items())


class BannerBook:
    """The banners this profile's ear has heard about, and what they are going for.

    Fed off the capture's reader thread and read from the join's own thread, so every
    touch is under one lock. Nothing here asks the game anything: it is a memory of what
    arrived, and an empty book is a perfectly good answer that costs the join nothing.
    """

    def __init__(self, rt=None) -> None:
        self._rt = rt
        self._lock = threading.Lock()
        # teamUuid -> {"content", "slots", "point", "server", "heard"}
        self._seen: dict = {}

    # -- writing -------------------------------------------------------------
    def note(self, fields: dict, now=None) -> bool:
        """Remember one banner off a fields line. ``True`` when anything was kept.

        A field that is absent LEAVES WHAT WAS THERE. The `create` push carries the
        target and the address; a later `refresh` of the same banner may carry only the
        seat count, and taking the target away because the second push did not repeat it
        is how a banner that was named once becomes unnamed again.
        """
        team = str((fields or {}).get("team") or "").strip()
        if not team.isdigit():
            return False
        stamp = time.monotonic() if now is None else now
        with self._lock:
            entry = dict(self._seen.get(team) or {})
            for key in ("content", "slots"):
                value = str((fields or {}).get(key) or "").strip()
                if value:
                    entry[key] = value
            aim = str((fields or {}).get("join") or "").strip()
            point, _, server = aim.partition("/")
            if point.isdigit() and server.isdigit():
                entry["point"], entry["server"] = point, server
                entry["aimed"] = stamp
            entry["heard"] = stamp
            self._seen[team] = entry
            self._forget(stamp)
        return True

    def _forget(self, now: float) -> None:
        """Drop banners nothing has said anything about for a quarter of an hour."""
        for team, entry in list(self._seen.items()):
            if now - float(entry.get("heard") or 0.0) > BANNER_TTL_SEC:
                self._seen.pop(team, None)

    # -- reading, in the shapes the recipe parks ------------------------------
    def targets(self) -> str:
        """`team:contentId,…` — what each banner we have heard of is going for."""
        with self._lock:
            return ",".join(f"{team}:{entry['content']}"
                            for team, entry in self._seen.items()
                            if entry.get("content"))

    def slots(self) -> str:
        """`team:taken/max,…` — how full each banner was when we last heard it."""
        with self._lock:
            return ",".join(f"{team}:{entry['slots']}"
                            for team, entry in self._seen.items()
                            if entry.get("slots"))

    def points(self, now=None) -> str:
        """`team:tile/server,…` for the banners heard in the last minute.

        Aged on the ADDRESS's own stamp rather than on the banner's: a refresh that
        carries no address must not keep an old tile alive, because that tile is the one
        thing a join acts on directly (#1301).
        """
        stamp = time.monotonic() if now is None else now
        with self._lock:
            return ",".join(
                f"{team}:{entry['point']}/{entry['server']}"
                for team, entry in self._seen.items()
                if entry.get("point") and entry.get("server")
                and stamp - float(entry.get("aimed") or 0.0) <= POINT_TTL_SEC)

    def known(self) -> int:
        """How many banners the book is holding — what a test and a log line read."""
        with self._lock:
            return len(self._seen)


def parse_fields(tail: str) -> dict:
    """`"team=1 content=2 slots=1/5 join=3/4"` -> a dict. Never raises.

    The child's own format (`tools/wire_event_monitor.py`), parsed here because this is
    the only thing that reads it. A token without an `=` is dropped rather than guessed
    at.
    """
    out: dict = {}
    for token in str(tail or "").split():
        key, sep, value = token.partition("=")
        if sep and key:
            out[key] = value
    return out
