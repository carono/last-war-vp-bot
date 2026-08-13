"""THE ONE ENTRANCE to this profile's register of players (#1371).

## Why it is on the runtime and not on the tab

The register was born on the «Игроки» tab (#1335) and fed by one thing: the checkpoint
a lap of the map leaves behind. But a lap is not the only place the panel meets a
player. It meets them in the live block of banners, in the chat, in the alliance roster,
on a secret-task tile — every one of those readings already happens, is already paid
for, and was already being thrown away the moment the widget that drew it was redrawn.

So the store moves to where every one of them can reach it, and there is exactly ONE
call that writes:

    rt.players.sighted(records, source=SRC_CHAT)

Five copies of «open the file, merge, save» in five tabs is how two of them end up
disagreeing about what a lap may overwrite. There is one, it is here, and the rules
below are enforced in it rather than remembered by each caller.

## Nothing here asks the game anything. Ever.

**Every source is something the panel is ALREADY told**, and that is the whole bargain
(#1335): a sweep sees thousands of players and a per-player top-up would be thousands of
requests the game never asked for. A feeder passes on what it happened to hear while
doing its own job. A feeder that would have to SEND something to fill a field does not
fill that field; the field stays empty and the page says so.

## What each source is allowed to write

A source may only write the fields it can actually know — :data:`SOURCE_FIELDS`. That is
not bookkeeping, it is the guard the register needs most: the banner block reads a
`power` off every squad standing in a rally, and that is **the marching squad's** power,
not the player's. Merged onto `power` it would quietly overwrite a real profile reading
with a tenth of it. So the banner source may write `march_power` and cannot write
`power` however its records are spelled.

## An unknown never overwrites a known

A record carries what its source happened to see. Everything it does not mention is
dropped on the way in (`incoming`), so a chat line that knows a name and no coordinates
leaves the coordinates alone, and a tile that knows no power leaves an hour-old profile
reading standing. The same sentence as «an empty read removes nothing», one field down.

## Every field remembers where it came from and when

`row["src"]` is `{field: [source, unix seconds]}`. It is stamped when the VALUE CHANGES
(or arrives for the first time) and NOT on every re-confirmation, and that is a
measured decision rather than a shortcut: a lap re-lists four thousand unchanged players
every twenty seconds, and stamping those would rewrite a multi-megabyte file on every
tick for ever. So a field's stamp answers «since when has it been this, and who said
so», and «when was this row last confirmed at all» is `last_seen`, which is what the
table's «Виден» column has always shown.

## A row leaves for one reason and it is a person asking

Inherited from the store underneath (`panel/kept.py`): the list accepts
:data:`~panel.kept.PERSON_ASKED` and nothing else, so a read that came back empty cannot
take a row away — not by construction of this module, but by construction of the type.
"""
from __future__ import annotations

import os
import threading
import time

from ..kept import PERSON_ASKED, Kept

# ---------------------------------------------------------------------------
# who tells us about a player
# ---------------------------------------------------------------------------
#: A lap of the map — the base tiles a sweep drives over (`tools/lib/world_index.py`).
SRC_MAP = "map"
#: A `get.user.info.multi` reply: the person opened a base in the game, or the client
#: fetched the alliance roster at login. The only place a combat number comes from.
SRC_PROFILE = "profile"
#: The note THIS ACCOUNT has written on that player, as the game holds it.
SRC_REMARK = "remark"
#: The live block of banners — who is standing in a rally right now (#1324).
SRC_RALLY = "rally"
#: A chat message: whoever said it.
SRC_CHAT = "chat"
#: The alliance roster the «Альянс» tab reads.
SRC_ALLIANCE = "alliance"
#: The owner of a tile — a secret task, a ghost-recon point, a mine.
SRC_TILE = "tile"
#: The person at the panel. The only source that may write `note`.
SRC_PERSON = "person"

#: Every source, so a UI can list them and a test can walk them.
SOURCES = (SRC_MAP, SRC_PROFILE, SRC_REMARK, SRC_RALLY, SRC_CHAT, SRC_ALLIANCE,
           SRC_TILE, SRC_PERSON)

# ---------------------------------------------------------------------------
# what a row can hold
# ---------------------------------------------------------------------------
#: The fields a register row can hold. Anything else a feeder carries is dropped on the
#: way in — a store that quietly grew a column would be a store nobody could review.
FIELDS = (
    "uid", "name", "level", "server_id", "x", "y", "uuid", "country",
    "alliance_id", "alliance_abbr", "alliance_name",
    "power", "army_power", "army_kill", "svip_level",
    "head", "march_power", "online",
    "remark", "note", "first_seen", "last_seen", "profile_seen_at", "src",
)

#: The two the register keeps for itself, and the provenance map. No source writes them.
OWN_FIELDS = frozenset({"first_seen", "last_seen", "src"})

#: What a base tile carries. Measured over one recorded whole-server lap of 6 723 of
#: them: the first eight on every single tile, the alliance's uuid and tag on the
#: quarter of players who are in one.
MAP_FIELDS = frozenset({"uid", "name", "level", "server_id", "x", "y", "uuid",
                        "country", "alliance_id", "alliance_abbr", "alliance_name"})

#: …and what ONLY a profile reply carries.
PROFILE_FIELDS = frozenset({"power", "army_power", "army_kill", "svip_level",
                            "profile_seen_at"})

#: Which fields each source may write. A source that hands over anything else has that
#: field dropped — see the module docstring: the banner block's `power` is a SQUAD's.
SOURCE_FIELDS = {
    # The map sweep's checkpoint is not only tiles: the capture folds a profile reply
    # and the account's own notes onto the rows it keeps (`tools/lib/world_index.py`),
    # so the source that reads that file may carry all three. Which is which is said by
    # `field_source` (:data:`CHECKPOINT_SOURCES`) rather than by dropping the fields.
    SRC_MAP: MAP_FIELDS | PROFILE_FIELDS | {"remark"},
    SRC_PROFILE: MAP_FIELDS | PROFILE_FIELDS,
    SRC_REMARK: frozenset({"uid", "remark"}),
    SRC_RALLY: frozenset({"uid", "name", "head", "march_power", "server_id"}),
    SRC_CHAT: frozenset({"uid", "name", "alliance_abbr", "server_id", "head"}),
    SRC_ALLIANCE: frozenset({"uid", "name", "level", "power", "online",
                             "alliance_abbr", "alliance_name"}),
    # NO COORDINATE. A tile with an owner — a secret task, a ghost-recon point, a truck
    # on the road — is somewhere out on the map, nowhere near that player's base, so
    # its position says where their TASK is and nothing about where they live. Writing
    # it would move everybody in the alliance onto their own dispatch points.
    SRC_TILE: frozenset({"uid", "name", "server_id", "alliance_abbr", "alliance_id",
                         "country"}),
    SRC_PERSON: frozenset({"uid", "note"}),
}

#: The map checkpoint is three sources in one file — the tile, the profile reply folded
#: onto it and the account's own note — so its fields are attributed one by one instead
#: of all being called «карта». Handed to `sighted` as `field_source`.
CHECKPOINT_SOURCES = dict(
    {field: SRC_PROFILE for field in PROFILE_FIELDS},
    remark=SRC_REMARK,
)


def incoming(record: dict, source: str, now: float) -> dict:
    """One record as the register takes it — empties dropped, stamped, sieved.

    `seen_at` on a feeder's side means «this source confirmed the player just now»,
    which is exactly what `last_seen` means here, so it is renamed rather than kept
    twice under two names that would drift.
    """
    allowed = SOURCE_FIELDS.get(source) or frozenset()
    out = {}
    for field, value in record.items():
        if field not in FIELDS or field in OWN_FIELDS or field not in allowed:
            continue
        # Zero is a real level and a real coordinate; only None is «did not say».
        if value is None or value == "":
            continue
        out[field] = value
    if out.get("uid") is None:
        return {}
    out["uid"] = str(out["uid"])
    out["last_seen"] = int(record.get("seen_at") or now)
    return out


class PlayerBook:
    """Everyone this profile has met, however it met them, kept for good.

    A thin layer over :class:`~panel.kept.Kept`: the file, the key, the one removal
    reason and the provenance are decided here so that no caller has to remember them.
    Every write goes through :meth:`sighted` or one of the two a PERSON makes.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._kept = Kept(path, key="uid", accepts=(PERSON_ASKED,))
        # Feeders run on their own threads — a capture's reader, the banner block's
        # read, the chat poll — and they all end up in one dict and one file.
        self._lock = threading.RLock()

    # -- reading ---------------------------------------------------------------------
    def rows(self) -> list:
        with self._lock:
            return self._kept.rows()

    def get(self, uid) -> dict | None:
        with self._lock:
            return self._kept.get(uid)

    def __len__(self) -> int:
        with self._lock:
            return len(self._kept)

    # -- THE ONE WRITE ---------------------------------------------------------------
    def sighted(self, records, source: str, now: float | None = None,
                field_source: dict | None = None) -> int:
        """Merge what one source has just seen. **Adds and updates; never removes.**

        `field_source` names a different source for particular fields — the map
        checkpoint uses it because the file it writes is three sources in one
        (:data:`CHECKPOINT_SOURCES`).

        Returns how many rows were added or changed, so a caller can say «the lap
        brought 412 new faces» rather than «something happened».
        """
        if source not in SOURCE_FIELDS:
            raise ValueError(
                f"{source!r} is not a source. The register's sources are {SOURCES} — "
                f"add yours there, with the fields it is allowed to write, rather "
                f"than here.")
        now = time.time() if now is None else now
        fresh = []
        with self._lock:
            for record in records or ():
                if not isinstance(record, dict):
                    continue
                row = incoming(record, source, now)
                if not row:
                    continue
                held = self._kept.get(row["uid"])
                if held is None:
                    # `first_seen` is written once and never again — the merge updates
                    # a row field by field, so writing it every time would move it on.
                    row["first_seen"] = row["last_seen"]
                elif all(held.get(f) == v for f, v in row.items()):
                    # NOTHING NEW ABOUT THIS PLAYER, so nothing is merged and the file
                    # is not rewritten. A checkpoint re-lists the same sighting every
                    # tick for as long as it is fresh (#1335): without this the panel
                    # said «карта добавила или обновила 103» every twenty seconds, for
                    # ever, over a map on which nothing had moved.
                    continue
                row["src"] = self._provenance(held, row, source, field_source, now)
                fresh.append(row)
            return self._kept.merge(fresh)

    @staticmethod
    def _provenance(held, row: dict, source: str, field_source, now: float) -> dict:
        """The row's `src` map after this sighting.

        Stamped for a field whose VALUE CHANGED or which is new, and left alone for one
        merely re-confirmed — see the module docstring: stamping every confirmation
        would rewrite the whole file on every tick of every lap.
        """
        src = dict((held or {}).get("src") or {})
        stamp = int(now)
        for field, value in row.items():
            if field in OWN_FIELDS or field == "uid":
                continue
            if held is not None and held.get(field) == value:
                continue
            who = (field_source or {}).get(field) or source
            src[field] = [who, stamp]
        return src

    # -- what a person writes --------------------------------------------------------
    def set_note(self, uid, text: str | None) -> bool:
        """Write (or clear) THIS PROFILE's own mark on a player.

        A mark on a player the register has never heard of is refused rather than
        filed: a row with a note and no name is not a player, and the press that could
        make one is a bug somewhere else.
        """
        with self._lock:
            held = self._kept.get(uid)
            if held is None:
                return False
            text = (text or "").strip() or None
            src = dict(held.get("src") or {})
            src["note"] = [SRC_PERSON, int(time.time())]
            self._kept.merge([{"uid": str(uid), "note": text, "src": src}])
            return True

    def forget(self, uid) -> bool:
        """THE ONE WAY A ROW LEAVES — a person asked (:data:`~panel.kept.PERSON_ASKED`).

        The store accepts no other reason, so this is not a convention but the only
        call that compiles.
        """
        with self._lock:
            return self._kept.drop(uid, PERSON_ASKED)

    # -- what the page tells about itself --------------------------------------------
    def alliances(self) -> list:
        """Every alliance tag in the register, once each, in alphabetical order."""
        tags = {(row.get("alliance_abbr") or "").strip() for row in self.rows()}
        return sorted(t for t in tags if t)

    def servers(self) -> list:
        """Every server number in the register, ascending."""
        found = {row.get("server_id") for row in self.rows()}
        return sorted(s for s in found if isinstance(s, int))

    def file_size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


def provenance_of(row: dict) -> list:
    """One row as `(field, value, source, when)`, freshest first — for both front-ends.

    The window's «Подробно» dialog and the phone's detail card are the same list said
    twice, so it is built once and here. A field with no stamp — everything written
    before this existed — is reported with an empty source rather than a guessed one.
    """
    src = row.get("src") or {}
    out = []
    for field in FIELDS:
        if field in OWN_FIELDS or field == "uid":
            continue
        value = row.get(field)
        if value is None or value == "":
            continue
        who, when = (src.get(field) or ["", 0])[:2]
        out.append((field, value, who or "", float(when or 0)))
    out.sort(key=lambda item: (-item[3], item[0]))
    return out
