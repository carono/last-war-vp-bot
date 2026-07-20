#!/usr/bin/env python3
"""Survey and decode a passive Last War capture.

Two jobs in one tool:

1. **Survey** every TCP and UDP flow in the capture, classify it
   (game / TLS / HTTP / unknown) and show a payload sample — so a second game
   endpoint (chat, login, region server) cannot hide behind a port assumption.
2. **Decode** the flows that speak the game protocol: TCP reassembly, the
   client XOR mask, the typed TLV tree, zstd frames and embedded protobuf,
   with a wall-clock timestamp on every message.

Nothing here touches the game process — this is pure offline pcap analysis.
See ``docs/research/protocol.md`` for the format specification.

Usage::

    python tools/lastwar_proto.py capture.pcapng                 # survey + summary
    python tools/lastwar_proto.py capture.pcapng --timeline      # every message, in order
    python tools/lastwar_proto.py capture.pcapng --grep chat     # filter by command
    python tools/lastwar_proto.py capture.pcapng --json out.json # full transcript
    python tools/lastwar_proto.py capture.pcapng --survey-only
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import struct
import sys
import time
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Frame constants
# --------------------------------------------------------------------------

# Flag byte: the low three flag bits describe the body, the rest identifies the
# direction.
#   0x20  body is compressed
#   0x10  compression is zstd (with a 4-byte raw-size prefix), else raw zlib
#   0x08  the length field is uint32 instead of uint16 (large frames)
# Direction lives in the bits outside FLAG_MASK: 0x80 server, 0xc4 client.
FLAG_COMPRESSED = 0x20
FLAG_ZSTD = 0x10
FLAG_LEN32 = 0x08
FLAG_MASK = FLAG_COMPRESSED | FLAG_ZSTD | FLAG_LEN32
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SERVER_MAGIC = 0x80
CLIENT_MAGIC = 0xC4


def is_magic(byte: int, direction: str) -> bool:
    """True if this byte is a frame flag byte for the given direction."""
    base = SERVER_MAGIC if direction == "down" else CLIENT_MAGIC
    return byte & ~FLAG_MASK & 0xFF == base


SERVER_MAGICS = tuple(SERVER_MAGIC | f for f in range(FLAG_MASK + 1) if not f & ~FLAG_MASK)
CLIENT_MAGICS = tuple(CLIENT_MAGIC | f for f in range(FLAG_MASK + 1) if not f & ~FLAG_MASK)

# TLV type tags. Names mirror on-wire semantics, not any official SDK.
T_BOOL = 0x01
T_INT8 = 0x02
T_INT16 = 0x03
T_INT32 = 0x04
T_INT64 = 0x05
T_FLOAT = 0x06
T_DOUBLE = 0x07
T_STRING = 0x08
T_BLOB = 0x0A
T_INT32_ARRAY = 0x0C
T_INT64_ARRAY = 0x0D
T_STRING_ARRAY = 0x10
T_LIST = 0x11
T_MAP = 0x12

K_COMMAND = "c"
K_PARAMS = "p"

unknown_tags: Counter[int] = Counter()


class Truncated(Exception):
    """Buffer ends mid-value."""


class BadTag(Exception):
    """Unknown type tag — stream is not ours, or mis-framed."""


# --------------------------------------------------------------------------
# TLV parser
# --------------------------------------------------------------------------


class Reader:
    def __init__(self, buf: bytes, pos: int = 0):
        self.buf = buf
        self.pos = pos

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            raise Truncated
        out = self.buf[self.pos : self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.take(2), "big")

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "big")

    def i32(self) -> int:
        return int.from_bytes(self.take(4), "big", signed=True)

    def i64(self) -> int:
        return int.from_bytes(self.take(8), "big", signed=True)


def read_value(r: Reader):
    tag = r.u8()
    if tag == T_BOOL:
        return bool(r.u8())
    if tag == T_INT8:
        return r.u8()
    if tag == T_INT16:
        return int.from_bytes(r.take(2), "big", signed=True)
    if tag == T_INT32:
        return r.i32()
    if tag == T_INT64:
        return r.i64()
    if tag == T_FLOAT:
        return struct.unpack(">f", r.take(4))[0]
    if tag == T_DOUBLE:
        return struct.unpack(">d", r.take(8))[0]
    if tag == T_STRING:
        return r.take(r.u16()).decode("utf-8", "replace")
    if tag == T_BLOB:
        raw = r.take(r.u32())
        return {"_blob": raw.hex(), "_protobuf": parse_protobuf(raw)}
    if tag == T_INT32_ARRAY:
        return [r.i32() for _ in range(r.u16())]
    if tag == T_INT64_ARRAY:
        return [r.i64() for _ in range(r.u16())]
    if tag == T_STRING_ARRAY:
        return [r.take(r.u16()).decode("utf-8", "replace") for _ in range(r.u16())]
    if tag == T_LIST:
        return [read_value(r) for _ in range(r.u16())]
    if tag == T_MAP:
        out = {}
        for _ in range(r.u16()):
            key = r.take(r.u16()).decode("utf-8", "replace")
            out[key] = read_value(r)
        return out
    unknown_tags[tag] += 1
    raise BadTag(f"unknown TLV tag 0x{tag:02x} at offset {r.pos - 1}")


# --------------------------------------------------------------------------
# Protobuf (0x0a blobs carry protobuf with no shipped .proto)
# --------------------------------------------------------------------------


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = shift = 0
    while pos < len(buf):
        byte = buf[pos]
        pos += 1
        val |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return val, pos
        shift += 7
    raise Truncated


def _as_text(raw: bytes) -> str | None:
    """Return raw as text if it is unambiguously a string, else None.

    Player names, alliance names and hex ids are the fields we actually care
    about, and they are all printable. Anything with control bytes is treated
    as a nested message instead.
    """
    if not raw:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text if all(ch == "\n" or ch >= " " for ch in text) else None


def parse_protobuf(buf: bytes, depth: int = 0) -> dict:
    """Best-effort decode; nested LEN fields are parsed recursively."""
    out: dict[str, object] = {}
    pos = 0
    try:
        while pos < len(buf):
            key, pos = _varint(buf, pos)
            field, wire = key >> 3, key & 7
            name = f"f{field}"
            if wire == 0:
                val, pos = _varint(buf, pos)
            elif wire == 1:
                val = int.from_bytes(buf[pos : pos + 8], "little")
                pos += 8
            elif wire == 2:
                length, pos = _varint(buf, pos)
                raw = buf[pos : pos + length]
                pos += length
                # A LEN field is either a nested message or a string, and the
                # two are ambiguous on the wire. Prefer a clean text decode —
                # otherwise player and alliance names come out as garbage
                # varints.
                text = _as_text(raw)
                if text is not None:
                    val = text
                else:
                    nested = parse_protobuf(raw, depth + 1) if depth < 4 else None
                    val = nested if nested else raw.decode("utf-8", "replace")
            elif wire == 5:
                val = int.from_bytes(buf[pos : pos + 4], "little")
                pos += 4
            else:
                return out
            if name in out:
                if not isinstance(out[name], list):
                    out[name] = [out[name]]
                out[name].append(val)  # type: ignore[union-attr]
            else:
                out[name] = val
    except (Truncated, IndexError):
        pass
    return out


# --------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------


def unmask(body: bytes, k1: int, k2: int) -> bytes:
    """Strip the client->server XOR mask. Indices count from the body start."""
    out = bytearray(body)
    for i in range(0, len(out), 4):
        out[i] ^= k1
    for i in range(1, len(out), 4):
        out[i] ^= k2
    return bytes(out)


def decompress_zstd(blob: bytes, expected: int) -> bytes:
    import zstandard  # type: ignore

    return zstandard.ZstdDecompressor().decompress(blob, max_output_size=expected or 1 << 26)


def decompress_zlib(blob: bytes) -> tuple[bytes, int]:
    """Inflate and report how many input bytes the stream consumed.

    Client frames have no length field, so the zlib stream's own end is what
    delimits the frame.
    """
    obj = zlib.decompressobj()
    out = obj.decompress(blob)
    return out, len(blob) - len(obj.unused_data)


def iter_frames(stream: bytes, direction: str):
    """Yield (envelope, start, end) per frame; stop at the first partial frame.

    Server frames are length-prefixed. Client frames carry no length field, so
    the self-delimiting TLV tree defines the frame boundary.
    """
    magics = SERVER_MAGICS if direction == "down" else CLIENT_MAGICS
    # Smallest header that can be read without indexing past the end: a server
    # header is flags + uint16, a client one adds serverId, K2 and K1.
    min_header = 3 if direction == "down" else 5
    pos = 0
    while pos + min_header <= len(stream):
        flags = stream[pos]
        if flags not in magics:
            nxt = _resync(stream, pos, magics)
            if nxt < 0:
                return
            pos = nxt
            continue
        # Large frames carry a uint32 length; ordinary ones a uint16.
        len_size = 4 if flags & FLAG_LEN32 else 2
        length = int.from_bytes(stream[pos + 1 : pos + 1 + len_size], "big")
        compressed = bool(flags & FLAG_COMPRESSED)
        use_zstd = bool(flags & FLAG_ZSTD)
        # Server headers are flags+length; client headers add serverId, K2, K1.
        cursor = pos + 1 + len_size if direction == "down" else pos + 5
        raw_size = 0
        # zstd bodies carry a 4-byte uncompressed-size prefix; zlib ones don't.
        if compressed and use_zstd:
            if cursor + 4 > len(stream):
                return
            raw_size = int.from_bytes(stream[cursor : cursor + 4], "big")
            cursor += 4

        if direction == "down":
            body = stream[cursor : cursor + length]
            if len(body) < length:
                return
            end = cursor + length
        else:
            # Client bodies are masked first, compressed second — so unmask,
            # then inflate. Bytes 1-2 of the header are the serverId, not a
            # length, so the body's own end delimits the frame.
            k2, k1 = stream[pos + 3], stream[pos + 4]
            body = unmask(stream[cursor:], k1, k2)
            end = None

        if compressed:
            try:
                if use_zstd:
                    body = decompress_zstd(body, raw_size)
                else:
                    body, consumed = decompress_zlib(body)
                    if end is None:
                        end = cursor + consumed
            except Exception:
                pos = end if end else pos + 3
                continue

        reader = Reader(body)
        try:
            value = read_value(reader)
        except Truncated:
            if end is None:
                return
            value = None
        except BadTag:
            value = None

        if end is None and value is not None:
            end = cursor + reader.pos
        if value is not None:
            yield value, pos, end
        if end is not None:
            pos = end
        else:
            nxt = _resync(stream, pos + 1, magics)
            if nxt < 0:
                return
            pos = nxt


def _resync(stream: bytes, pos: int, magics) -> int:
    """Next candidate flag byte at or after pos+1.

    bytes.find runs in C; scanning byte-by-byte in Python is orders of
    magnitude slower and this is the hot path when probing unrelated traffic.
    """
    best = -1
    for magic in magics:
        found = stream.find(bytes([magic]), pos + 1)
        if found != -1 and (best == -1 or found < best):
            best = found
    return best


# --------------------------------------------------------------------------
# Map semantics: secret tasks (hero dispatch), the f2 = 17 tiles
# --------------------------------------------------------------------------
#
# Everything above this line is transport — framing, masking, TLV. This
# section is the first piece of *meaning*: it turns `world.get.block` tiles
# into records the bot can act on. See docs/research/protocol.md §7.
#
#     f1       coordinate, y * maxAreaSize + x, server-local
#     f100     task uuid
#     f10.f1   owner uid          f10.f2   cfgId (encodes the level)
#     f10.f3   completion time    f10.f4   uids that already looted it
#     f10.f8   expiry             f10.f9   allianceId
#     f102     serverId

# A task can be looted by at most three players. Established over 636 tiles
# and 144 dispatch records: no `f10.f4` and no `stealInfoList` ever ran
# longer than three, and the two agreed 48/48 where the same uuid appeared
# in both.
MAX_LOOTERS = 3

# Once a dispatch is within this long of finishing, the game draws a countdown
# with a loot button — the tile is not raidable yet but is about to be. A scan
# surfaces those as `pending` so a raid can be lined up before the timer ends.
PENDING_WINDOW_MS = 10 * 60 * 1000

# A tile is only trustworthy while the map keeps re-sending it. Once it stops
# (you panned away), its cached loot/dispatch state can no longer be verified
# and reads exactly like a live one — the (159,90) false positive, still
# can_loot=True a day after its dispatch "completed". So both the live index
# and any reader of a checkpoint keep only tiles re-observed within this window.
# The unit is wall-clock seconds on the capture host, not the game's ms clock.
TASK_FRESH_SECONDS = 15 * 60

# `cfgId` splits into a family prefix and a trailing `LLVV` (level, variant).
# The prefix is not a fixed width, so it must be read from the right:
#     400602   -> family "40",   level 6, variant 2
#     50000704 -> family "5000", level 7, variant 4
# Four families exist, and each pins `f10.f10` exactly (766/766 tiles), so
# that flag carries nothing the cfgId does not.
TASK_FAMILY_FLAG = {"30": 1, "40": 1, "5000": 3, "6000": 3}

# Level 99 is not a level. 128 tiles came back as `6000 99 xx`, one per
# player, with a template range of their own — a different task class that
# happens to share the encoding. Parsed, but kept out of level filters.
SPECIAL_TASK_LEVEL = 99

# ---------------------------------------------------------------------------
# The star
# ---------------------------------------------------------------------------
# Some task markers are drawn with a star and are the ones worth raiding.
# The star is **not a field**: all 766 captured tiles carry the identical
# field set, so the client must derive it from `cfgId` — the same place the
# level hides.
#
# Family "6000" is the maintainer's ruling, taken on this evidence:
#
#   * a task shared into chat from server 999 at (470, 652) was starred, and
#     its attachment named `cfgId 60000701` — family "6000". The maintainer
#     confirmed the star personally at the moment of sharing;
#   * an unstarred task at (469, 659) matched a tile with `cfgId 50000704`
#     — family "5000". From a dataset outside this repo, not reproduced here;
#   * across 271 live tiles nothing contradicted the reading.
#   * a 2026-07-19 live run (`--tasks --families`, server 935, 32 tasks) re-
#     captured `cfgId 60000701` — the exact family-"6000" cfgId the maintainer
#     had confirmed starred by hand — and never split a family across the star.
#
# One caveat a future reader should not have to rediscover:
#
#   * "nothing contradicted it" is weaker than it sounds. No tile's star was
#     ever checked by eye except the one shared into chat, so a contradiction
#     between an on-screen star and the family had no way to surface. The live
#     tiles are consistent with the rule, not an independent by-eye test of it;
#     the only ground truth for the star is visual, so that check stays manual.
#
# A prior caveat is now resolved. The maintainer had once reported a *starred
# level-4* task and noted family "6000" held no level-4 tile in any capture,
# which read as unexplained. The 2026-07-19 run captured `cfgId 60000401` —
# family "6000", level 4 — so the family does span level 4 after all; the old
# note stood only because no such tile had been seen, not because none exist.
#
# The `99` class is excluded from the star, and that exclusion is now a
# sighting rather than an inference. This note used to argue that level 99
# "the UI does not draw, so they cannot be the starred markers a player sees".
# The first half is wrong: on 2026-07-19 the maintainer watched a family-"6000"
# tile with `cfgId 60009902` — level 99 by the cfgId — render on screen as a
# seasonal oil-barrel task, shown at level 6 in the UI and carrying **no star**.
# So the UI does draw them; it just draws them unstarred, under a level of its
# own that the cfgId does not agree with.
#
# The conclusion therefore survives its broken premise, and the family test
# alone over-reports: in the captures of that day 113 of 189 starred lines —
# 60% — were level 99, none of them ever confirmed by eye. Both by-eye
# confirmations on record (`60000701` level 7, `60000401` level 4) are outside
# the class, so excluding it costs no confirmed star.
#
# Two things this does NOT settle, for whoever picks it up next:
#   * whether every `99` tile is unstarred, or only this seasonal type. One
#     sighting cannot tell those apart;
#   * what the UI level means when it disagrees with the cfgId (6 vs 99).
#     Until that is understood, `level` on a `99` task is the wire's number,
#     not the player's.
#
# This constant plus `SecretTask.starred` are the only places the rule lives.
# To re-test, run `live_tshark.py --tasks --families` and compare the tally
# with the stars actually drawn on that patch of map.
STAR_TASK_FAMILIES = frozenset({"6000"})


@dataclass(slots=True)
class SecretTask:
    uuid: int
    server_id: int
    x: int
    y: int
    level: int
    cfg_id: int
    family: str
    looted_by: tuple[str, ...]
    owner_uid: str | None
    alliance_id: str | None
    expires_at: int | None
    completed_at: int | None

    @property
    def loot_count(self) -> int:
        return len(self.looted_by)

    @property
    def free_slots(self) -> int:
        return max(0, MAX_LOOTERS - self.loot_count)

    @property
    def can_loot(self) -> bool:
        """Raidable right now — which a free loot slot alone does not prove.

        Confirmed against three tiles the maintainer checked by eye on server
        1003: (442,413) could be raided, while (440,409) and (386,381) could
        not despite reading 0/3 looted. What separates them is the owner's
        dispatch state, not the loot count:

          * `completed_at` (f3) is when the owner's dispatch finishes. While it
            is still running the tile shows "ещё выполняется" and cannot be
            raided even at 0/3 — so the dispatch must have completed, i.e.
            `completed_at` is set and no longer in the future.
          * `expires_at` (f8) is when the tile leaves the map; a past value
            means it is already gone.
          * a loot slot must still be free (a 3/3 tile is spent).

        Both timestamps are epoch milliseconds on the game's clock, so they are
        compared against wall-clock now.
        """
        now = int(time.time() * 1000)
        if self.completed_at is None or self.completed_at > now:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return self.free_slots > 0

    @property
    def pending(self) -> bool:
        """Not raidable yet, but its dispatch finishes within ~10 minutes.

        At that point the game shows a countdown with a loot button, so a scan
        flags the tile as imminent rather than hiding it. Mutually exclusive
        with `can_loot`: that one needs `completed_at` already in the past,
        this one needs it in the near future. `expires_at` (the tile's daily
        map-expiry) still has to be ahead or the tile is already gone.
        """
        now = int(time.time() * 1000)
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return (self.completed_at is not None
                and now < self.completed_at <= now + PENDING_WINDOW_MS)

    @property
    def awaiting(self) -> bool:
        """On the map, but its dispatch has more than the pending window left.

        The third and last state of a live tile: `can_loot` is raidable now,
        `pending` is raidable within ~10 minutes, and this is everything else
        still ahead of its timer. All three are mutually exclusive, so counting
        the starred ones here says how many stars the map is holding in
        reserve — a number that only moves as tiles mature into `pending`.

        An already-expired tile is gone from the map and is none of the three.
        """
        now = int(time.time() * 1000)
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return (self.completed_at is not None
                and self.completed_at > now + PENDING_WINDOW_MS)

    @property
    def starred(self) -> bool:
        """Drawn with a star on the map — see STAR_TASK_FAMILIES.

        The `99` class is excluded: family alone over-reports. See the note by
        STAR_TASK_FAMILIES for the sighting that settled it.
        """
        return self.family in STAR_TASK_FAMILIES and not self.is_special

    @property
    def is_special(self) -> bool:
        """The one-per-player `99` class, not a levelled task."""
        return self.level == SPECIAL_TASK_LEVEL

    def as_dict(self) -> dict:
        return {
            "uuid": self.uuid, "server_id": self.server_id,
            "x": self.x, "y": self.y, "level": self.level,
            "cfg_id": self.cfg_id, "family": self.family,
            "looted_by": list(self.looted_by), "owner_uid": self.owner_uid,
            "alliance_id": self.alliance_id, "expires_at": self.expires_at,
            "completed_at": self.completed_at, "loot_count": self.loot_count,
            "free_slots": self.free_slots, "can_loot": self.can_loot,
            "pending": self.pending, "starred": self.starred,
        }

    @classmethod
    def from_dict(cls, record: dict) -> "SecretTask":
        """Rebuild a task from an as_dict() record — e.g. a checkpoint file.

        Only the stored fields are restored; the time-relative properties
        (can_loot, pending) are recomputed against the current clock when read,
        never taken from the record, so a checkpoint written minutes ago is
        re-evaluated rather than trusted frozen.
        """
        return cls(
            uuid=record.get("uuid"), server_id=record.get("server_id"),
            x=record.get("x"), y=record.get("y"), level=record.get("level"),
            cfg_id=record.get("cfg_id"), family=record.get("family"),
            looted_by=tuple(record.get("looted_by") or ()),
            owner_uid=record.get("owner_uid"),
            alliance_id=record.get("alliance_id"),
            expires_at=record.get("expires_at"),
            completed_at=record.get("completed_at"),
        )


def split_cfg_id(cfg_id) -> tuple[str, int, int]:
    """Return `(family, level, variant)` for a task cfgId.

    The trailing four digits are always `LLVV`; everything before them is the
    family. Anything shorter than five digits is not a task cfgId.
    """
    text = str(cfg_id)
    if len(text) < 5 or not text.isdigit():
        raise ValueError(f"not a task cfgId: {cfg_id!r}")
    return text[:-4], int(text[-4:-2]), int(text[-2:])


def _looters(raw) -> tuple[str, ...]:
    """`f10.f4` is absent for none, a bare value for one, a list for many."""
    if raw is None:
        return ()
    if isinstance(raw, list):
        return tuple(str(v) for v in raw)
    return (str(raw),)


def secret_tasks(payload: dict):
    """Yield every secret task in one decoded `world.get.block` response.

    Coordinates come out **server-local**, 0..maxAreaSize-1 — the same numbers
    the game shows on screen, paired with `server_id`. A tile's `f1` packs them
    as `y * maxAreaSize + x`, so unpacking is all that is needed.

    No world-space lift happens here, and that is deliberate. Request and
    response use different packings (protocol.md §7): the *request* packs
    `leftBottom` as `y * 3000 + x` in world space, the *response* block packs
    its own `leftBottom` as `y * maxAreaSize + x` in server-local space. Adding
    a world origin derived from the response block conflates the two — it
    silently produced x values above 1000 on a 1000x1000 server, which is how
    this was caught.
    """
    for block in payload.get("serverPointArr") or ():
        area = block.get("maxAreaSize") or 1000

        for point in block.get("points") or ():
            tile = point.get("_protobuf") or {}
            if tile.get("f2") != 17:
                continue
            detail = tile.get("f10") or {}
            try:
                family, level, _variant = split_cfg_id(detail["f2"])
            except (KeyError, ValueError):
                continue  # shaped like a task, but no usable cfgId
            packed = tile.get("f1") or 0
            yield SecretTask(
                uuid=tile.get("f100"),
                server_id=tile.get("f102") or tile.get("f103"),
                x=packed % area,
                y=packed // area,
                level=level,
                cfg_id=int(detail["f2"]),
                family=family,
                looted_by=_looters(detail.get("f4")),
                owner_uid=detail.get("f1"),
                alliance_id=detail.get("f9"),
                expires_at=detail.get("f8"),
                completed_at=detail.get("f3"),
            )


def filter_tasks(tasks, level=None, star_only=False, can_loot=False,
                 min_free_slots=None, exclude_alliance=None,
                 pending=False) -> list:
    """Narrow a task list. None/False means "any".

    `level` takes either one level or any iterable of them, and a task passes
    if it matches any — levels are one dimension, so listing several reads as
    "or", the same way `can_loot`/`pending` do below.

    Criteria from *different* dimensions are ANDed, but `can_loot` and
    `pending` are two values of one dimension — raid readiness — so asking for
    both means "either". They are disjoint by construction (`can_loot` needs
    `completed_at` already past, `pending` needs it just ahead), so ANDing them
    matched nothing at all and the caller simply went quiet. Everything else
    still narrows: `--star --level 7 --can-loot --pending` reads as starred AND
    level 7 AND (raidable now OR about to be).

    `can_loot` keeps only tasks that are raidable right now — dispatch
    completed, not expired, and a slot free (see `SecretTask.can_loot`).
    `pending` keeps only tasks about to become raidable — dispatch finishing
    within ~10 minutes (see `SecretTask.pending`).
    `min_free_slots` is a stricter *slot* count (3 = untouched) and does not by
    itself imply raidable. `exclude_alliance` drops your own alliance's tasks,
    which you cannot loot from.
    """
    # A bare int stays a one-element set, so every existing caller passing a
    # single level is unaffected.
    levels = None
    if level is not None:
        levels = {level} if isinstance(level, int) else set(level)

    out = []
    for t in tasks:
        if levels is not None and t.level not in levels:
            continue
        if star_only and not t.starred:
            continue
        if can_loot or pending:
            # Only the requested states count towards the match, so asking for
            # one behaves exactly as before.
            if not ((can_loot and t.can_loot) or (pending and t.pending)):
                continue
        if min_free_slots is not None and t.free_slots < min_free_slots:
            continue
        if exclude_alliance is not None and t.alliance_id == exclude_alliance:
            continue
        out.append(t)
    # Least-looted first, then highest level — the order you would raid in.
    out.sort(key=lambda t: (t.loot_count, -t.level))
    return out


def load_fresh_tasks(path, max_age_seconds: float = TASK_FRESH_SECONDS,
                     now: float | None = None) -> list:
    """Load a capture checkpoint, keeping only tiles re-seen this scan window.

    A raid decision must ignore any tile last observed outside the current
    window: its cached state is unverifiable and looks identical to a live one
    (the (159,90) false positive — still raidable a day after its dispatch
    "completed"). Each record carries `seen_at` (epoch seconds on the capture
    host); records without it, or older than `max_age_seconds`, are dropped.
    What survives comes back as `SecretTask` objects, so can_loot/pending are
    recomputed against the current clock rather than trusted as written.

    Accepts both the bare-list checkpoint and a ``{"tasks": [...]}`` wrapper.
    """
    now = time.time() if now is None else now
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    records = data.get("tasks") if isinstance(data, dict) else data
    fresh = []
    for record in records or ():
        seen = record.get("seen_at")
        if seen is None or now - seen > max_age_seconds:
            continue
        fresh.append(SecretTask.from_dict(record))
    return fresh


# --------------------------------------------------------------------------
# Map semantics: player bases, the f2 = 6 tiles
# --------------------------------------------------------------------------
#
# The second kind of tile worth keeping. A base carries its owner's public
# profile inline, so a map sweep reads name/level/alliance off the wire with
# no OCR and no profile screen. See docs/research/protocol.md §7.
#
#     f1       coordinate, y * maxAreaSize + x, server-local
#     f100     tile uuid (repeated as f3.f2)
#     f3.f1    owner uid          f3.f14   player name
#     f3.f4    HQ level (4-35)    f3.f27   country code
#     f3.f7    allianceId         f3.f15   alliance abbreviation
#     f102     serverId
#
# Field presence over the 3223 base tiles of the saved captures: f1, f4, f14
# and f27 are on every one of them, while f7 (1573) and f15 (1551) are only on
# the bases of players who are in an alliance. So a missing alliance is the
# normal case, not a decode failure, and both come back as None.


@dataclass(slots=True)
class PlayerBase:
    uid: str
    server_id: int
    x: int
    y: int
    name: str | None
    level: int | None
    alliance_id: str | None
    alliance_abbr: str | None
    country: str | None
    uuid: int | None
    # Only a profile response carries these — the map tile does not. None means
    # "never looked this player up", which is not the same as zero.
    power: int | None = None
    army_power: int | None = None
    army_kill: int | None = None
    svip_level: int | None = None
    # The note *you* wrote on this player in the client — see player_remarks().
    # Not a property of the player, and nothing on their tile carries it.
    remark: str | None = None

    @property
    def has_profile(self) -> bool:
        """Whether a `get.user.info.multi` reply has filled the combat stats."""
        return self.power is not None

    def merged_with(self, profile: "PlayerProfile") -> "PlayerBase":
        """This base with `profile`'s fields laid over it.

        The profile is the fresher and richer source — it is a direct answer
        about this player, where the tile is a snapshot of the ground. So it
        wins on everything it carries, and the tile keeps only what it alone
        knows: the coordinates and the tile uuid.
        """
        return PlayerBase(
            uid=self.uid,
            server_id=profile.server_id or self.server_id,
            x=self.x, y=self.y,
            name=profile.name if profile.name is not None else self.name,
            level=profile.level if profile.level is not None else self.level,
            alliance_id=(profile.alliance_id if profile.alliance_id is not None
                         else self.alliance_id),
            alliance_abbr=(profile.alliance_abbr
                           if profile.alliance_abbr is not None
                           else self.alliance_abbr),
            country=(profile.country if profile.country is not None
                     else self.country),
            uuid=self.uuid,
            power=profile.power, army_power=profile.army_power,
            army_kill=profile.army_kill, svip_level=profile.svip_level,
            # Carried, never taken from the profile: a remark comes from a
            # third source and a profile reply would otherwise erase it.
            remark=self.remark,
        )

    def as_dict(self) -> dict:
        return {
            "uid": self.uid, "server_id": self.server_id,
            "x": self.x, "y": self.y, "name": self.name, "level": self.level,
            "alliance_id": self.alliance_id, "alliance_abbr": self.alliance_abbr,
            "country": self.country, "uuid": self.uuid,
            "power": self.power, "army_power": self.army_power,
            "army_kill": self.army_kill, "svip_level": self.svip_level,
            "remark": self.remark,
        }

    @classmethod
    def from_dict(cls, record: dict) -> "PlayerBase":
        return cls(
            uid=record.get("uid"), server_id=record.get("server_id"),
            x=record.get("x"), y=record.get("y"), name=record.get("name"),
            level=record.get("level"),
            alliance_id=record.get("alliance_id"),
            alliance_abbr=record.get("alliance_abbr"),
            country=record.get("country"), uuid=record.get("uuid"),
            power=record.get("power"), army_power=record.get("army_power"),
            army_kill=record.get("army_kill"),
            svip_level=record.get("svip_level"),
            remark=record.get("remark"),
        )


def player_bases(payload: dict):
    """Yield every player base in one decoded `world.get.block` response.

    Coordinates come out **server-local**, exactly as in `secret_tasks()` and
    for the same reason — see the note there about the two different packings.

    A tile with no `f3.f1` is skipped: without an owner uid there is nothing to
    key a record on, and a nameless placeholder in the output would be
    indistinguishable from a real base whose fields failed to decode.
    """
    for block in payload.get("serverPointArr") or ():
        area = block.get("maxAreaSize") or 1000

        for point in block.get("points") or ():
            tile = point.get("_protobuf") or {}
            if tile.get("f2") != 6:
                continue
            detail = tile.get("f3") or {}
            uid = detail.get("f1")
            if uid is None:
                continue
            packed = tile.get("f1") or 0
            alliance_id = detail.get("f7")
            yield PlayerBase(
                uid=str(uid),
                server_id=tile.get("f102") or tile.get("f103"),
                x=packed % area,
                y=packed // area,
                name=detail.get("f14"),
                level=detail.get("f4"),
                alliance_id=str(alliance_id) if alliance_id is not None else None,
                alliance_abbr=detail.get("f15"),
                country=detail.get("f27"),
                uuid=tile.get("f100"),
            )


# --------------------------------------------------------------------------
# Player profiles: the `get.user.info.multi` reply
# --------------------------------------------------------------------------
#
# Clicking a base on the map makes the client ask `get.user.info.multi` for
# that one uid, and the reply carries the numbers the tile never does — total
# power, army power, lifetime army kills, SVIP level. Unlike a map response
# this one is plain JSON, not protobuf, and every entry names its own `uid`,
# so a reply needs no correlating back to the request that asked for it.
#
# The same command also arrives in batches (46 and 43 uids in the saved
# captures, an alliance roster fetched at login). Those entries are the same
# shape and just as real, so they are parsed identically; only how a caller
# got them differs.
#
# Field presence over the 95 profiles in the saved captures: `uid`, `power`,
# `armyPower`, `armyKill`, `svipLevel`, `level`, `mainBuildingLevel`,
# `serverId`, `name`, `country`, `allianceId` and `allianceAbbrName` are on
# every one. Where the same player also appeared as a map tile (59 uids), the
# two sources agreed 59/59 on level, server, name, alliance id and alliance
# abbreviation — so a profile can be merged onto a tile's record by
# `(server_id, uid)` without either contradicting the other.
PROFILE_COMMAND = "get.user.info.multi"


@dataclass(slots=True)
class PlayerProfile:
    uid: str
    server_id: int | None
    name: str | None
    level: int | None
    alliance_id: str | None
    alliance_abbr: str | None
    country: str | None
    power: int | None
    army_power: int | None
    army_kill: int | None
    svip_level: int | None

    def as_base(self) -> PlayerBase:
        """This profile as a base record with no coordinates.

        What a click on a player the sweep never saw as a tile produces: every
        field the profile knows, and None where only the map could have said.
        """
        return PlayerBase(
            uid=self.uid, server_id=self.server_id, x=None, y=None,
            name=self.name, level=self.level, alliance_id=self.alliance_id,
            alliance_abbr=self.alliance_abbr, country=self.country, uuid=None,
            power=self.power, army_power=self.army_power,
            army_kill=self.army_kill, svip_level=self.svip_level,
        )


def player_profiles(payload: dict):
    """Yield every player profile in one decoded `get.user.info.multi` reply.

    `mainBuildingLevel` is preferred over `level` for the level, because the
    tile's own level field is the HQ level and the two must stay comparable.
    They agreed on all 95 profiles seen, so the preference costs nothing and
    guards against the day they diverge.

    `serverId` is where the player is now, which is also where their base sits
    — it matched the tile's server on all 59 uids seen as both.
    """
    for entry in payload.get("uids") or ():
        if not isinstance(entry, dict):
            continue  # the request's own `uids` is a list of bare uid strings
        uid = entry.get("uid")
        if uid is None:
            continue
        alliance_id = entry.get("allianceId")
        yield PlayerProfile(
            uid=str(uid),
            server_id=(entry.get("serverId") or entry.get("currentServer")
                       or entry.get("srcServer")),
            name=entry.get("name"),
            level=entry.get("mainBuildingLevel") or entry.get("level"),
            alliance_id=str(alliance_id) if alliance_id else None,
            alliance_abbr=entry.get("allianceAbbrName") or None,
            country=entry.get("country"),
            power=entry.get("power"),
            army_power=entry.get("armyPower"),
            army_kill=entry.get("armyKill"),
            svip_level=entry.get("svipLevel"),
        )


# --------------------------------------------------------------------------
# Player remarks: the notes you wrote on other players
# --------------------------------------------------------------------------
#
# The client lets you write a private note on another player, and it is stored
# **server-side** rather than locally: `user.remark.list` returns the whole
# list, paginated, and the client fetches it once at login —
# `{"pageSize": 500, "page": 1}` per request. In the saved capture the two
# pages held 869 notes.
#
#     uid             the author — you; the same on every entry
#     targetUid       the player the note is about
#     remark          the note text
#     lastUpdateTime  when it was last edited, epoch ms
#
# A note is **not** on the `f2 = 6` tile and is not on the player's profile.
# That was tested rather than assumed: the literal text of the notes appears
# nowhere else in the capture, and of the 1094 base tiles seen, no field is
# present on the 276 belonging to noted players and absent from the other 818.
# The alliance fields do differ between those groups, but in the opposite
# direction — noted players are mostly *outside* an alliance, which says what
# the maintainer marks (farms), not that the tile carries a marker.
#
# Two consequences for anything merging these onto player records:
#
#   * the key is `targetUid` alone, with no server id — a note follows the
#     player, not their base, so it applies to that uid on any server;
#   * the list arrives at login, typically *before* any map data. A merge that
#     only looks at records already collected would therefore apply almost
#     nothing; it has to remember the notes and stamp records as they arrive.
#
# The command that *writes* a note has never been captured — every note in the
# capture was last edited 17 hours before it started. So this is read-only
# knowledge: the list can be read, and there is no evidence here about setting
# one.
REMARK_COMMAND = "user.remark.list"


def player_remarks(payload: dict):
    """Yield `(target_uid, remark, updated_at)` from a `user.remark.list` reply.

    An empty note comes back as None rather than an empty string, so a caller
    can treat "no note" uniformly however the server chose to spell it.
    """
    for entry in payload.get("list") or ():
        if not isinstance(entry, dict):
            continue
        target = entry.get("targetUid")
        if target is None:
            continue
        text = entry.get("remark")
        yield (str(target), text or None, entry.get("lastUpdateTime"))


# --------------------------------------------------------------------------
# Leaderboards: the ranking screens, as the server sends them
# --------------------------------------------------------------------------
#
# Opening a ranking in the client makes it ask one command and the whole board
# comes back in one reply — a list of dicts, one per player, each carrying at
# least a uid and a name. No paging was ever seen: `al.rank` returned all 99
# members and `champion.duel.result.show.rank.list` all 32 duellists in a
# single frame.
#
# **The field called `rank` is not always the position.** That is the one trap
# here, and it is not theoretical:
#
#   * in `champion.duel.result.show.rank.list` it is the position — the 32
#     entries carried exactly 1..32, in order;
#   * in `al.rank` it is the alliance *role* (R1..R5) — 99 entries carried
#     {3: 86, 4: 10, 1: 2, 5: 1}, and the list is in no sorted order at all
#     (not by power, not by weekly or daily donation). That board is really
#     the roster; the client sorts it locally by whichever column you picked,
#     so the position you see on screen was never on the wire.
#
# So a position is only ever reported when the candidate field actually is one
# — `is_position_sequence()` checks that before anything is believed — and is
# left None otherwise rather than guessed from the order of the list. The
# index within the reply is kept separately as `list_index`, which is a fact
# about the frame rather than a claim about the ranking.
#
# Two boards are described below because two are what the captures hold.
# Every other ranking screen is found by shape instead (see
# `discover_leaderboards`), so opening one the table has never seen still
# collects it.
LEADERBOARD_SCORE_FIELDS = (
    "score", "point", "points", "integral", "exp", "value", "num",
    "killNum", "armyKill", "weeklyProgress", "todayProgress", "power",
)


@dataclass(slots=True)
class Leaderboard:
    """Where the entries live in one ranking reply, and what they mean.

    `position` and `score` name the fields on an entry; either may be None
    when the board carries no such column.
    """
    command: str
    list_key: str
    label: str
    position: str | None = None
    score: str | None = None
    score_label: str | None = None
    server: str = "serverId"
    alliance: str | None = None


LEADERBOARDS = {
    board.command: board
    for board in (
        Leaderboard(
            command="al.rank",
            list_key="list",
            label="alliance roster",
            # Deliberately not "rank": see the note above — it is the R1..R5
            # role, and reading it as a position would number 86 of 99 members
            # third.
            position=None,
            score="weeklyProgress",
            score_label="weekly donation",
            alliance=None,
        ),
        Leaderboard(
            command="champion.duel.result.show.rank.list",
            list_key="rank",
            label="champion duel",
            position="rank",
            score=None,
            server="server",
            alliance="allianceName",
        ),
    )
}

# Commands whose replies carry a list of named players with a power or rank
# field, and which are *not* rankings — every one confirmed against the saved
# captures. Without this the shape test below claims them: a march's
# `plunderRecord` is a battle report, `get.user.info.multi` is the answer to a
# click, and the two activity rosters are sign-up sheets in no order.
NOT_LEADERBOARDS = frozenset({
    PROFILE_COMMAND, REMARK_COMMAND, "world.get.block", "init",
    "world.get.march.infos", "push.world.march.new",
    "push.world.march.world.get.new", "train.list",
    "get.alliance.world.mark.info", "dragon.assign.player.info",
    "quarantine.act.player.list",
})

# How many entries a list needs before its shape is taken as a ranking. Three
# is enough to be a board and enough to keep a two-element roster fragment
# from being announced as one.
LEADERBOARD_MIN_ENTRIES = 3


@dataclass(slots=True)
class LeaderboardEntry:
    board: str
    board_label: str | None
    uid: str
    name: str | None
    server_id: int | None
    position: int | None
    list_index: int
    score: int | None
    score_field: str | None
    power: int | None
    alliance: str | None
    # True when the board was found by shape rather than described in
    # LEADERBOARDS, so a reader can tell a column this file vouches for from
    # one a heuristic picked.
    discovered: bool = False

    def as_dict(self) -> dict:
        return {
            "leaderboard": self.board,
            "leaderboard_label": self.board_label,
            "uid": self.uid,
            "name": self.name,
            "server_id": self.server_id,
            "position": self.position,
            "list_index": self.list_index,
            "score": self.score,
            "score_field": self.score_field,
            "power": self.power,
            "alliance": self.alliance,
            "discovered": self.discovered,
        }


def is_position_sequence(values) -> bool:
    """Whether `values` really are ranking positions 1..N, in order.

    The guard that keeps `al.rank`'s R1..R5 role from being read as a
    placement. Demanding the exact sequence rather than merely "distinct and
    increasing" is what rejects it: the roles are neither, while both boards'
    genuine positions matched exactly.
    """
    numbers = list(values)
    if len(numbers) < 2:
        return False
    if any(not isinstance(v, int) or isinstance(v, bool) for v in numbers):
        return False
    return numbers == list(range(1, len(numbers) + 1))


def _entry_score(entry: dict, preferred: str | None):
    """The score column of one entry, as `(field, value)`.

    `preferred` wins when the described field is present; otherwise the first
    of LEADERBOARD_SCORE_FIELDS that the entry carries is taken, which is what
    lets an undescribed board still report a number.
    """
    if preferred and isinstance(entry.get(preferred), int):
        return preferred, entry[preferred]
    for field in LEADERBOARD_SCORE_FIELDS:
        value = entry.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            return field, value
    return None, None


def _read_board(command, label, entries, board, discovered):
    """Turn one reply's list into LeaderboardEntry objects."""
    positions = None
    if board is not None and board.position:
        candidates = [e.get(board.position) for e in entries]
        if is_position_sequence(candidates):
            positions = candidates
    elif discovered:
        # An undescribed board gets the same treatment, on whichever of the
        # usual names it happens to use — believed only if it checks out.
        for field in ("rank", "index", "pos", "position"):
            candidates = [e.get(field) for e in entries]
            if is_position_sequence(candidates):
                positions = candidates
                break

    server_key = board.server if board is not None else "serverId"
    alliance_key = board.alliance if board is not None else "allianceName"
    for index, entry in enumerate(entries):
        uid = entry.get("uid")
        if uid is None:
            continue
        field, score = _entry_score(entry, board.score if board else None)
        power = entry.get("power")
        yield LeaderboardEntry(
            board=command,
            board_label=label,
            uid=str(uid),
            name=entry.get("name"),
            server_id=(entry.get(server_key) or entry.get("serverId")
                       or entry.get("server") or entry.get("curServerId")),
            position=positions[index] if positions is not None else None,
            list_index=index,
            score=score,
            score_field=field,
            power=power if isinstance(power, int) else None,
            alliance=(entry.get(alliance_key) if alliance_key else None)
                     or entry.get("allianceName") or entry.get("abbr"),
            discovered=discovered,
        )


def leaderboard_entries(command: str | None, payload):
    """Yield every player in one ranking reply, described or not.

    A command in LEADERBOARDS is read where that table says. Anything else is
    offered to `discover_leaderboards`, so a ranking screen nobody has decoded
    yet still yields rows — marked `discovered` so the distinction survives
    into the JSON.
    """
    if not isinstance(payload, dict) or command is None:
        return
    board = LEADERBOARDS.get(command)
    if board is not None:
        entries = payload.get(board.list_key)
        if isinstance(entries, list):
            rows = [e for e in entries if isinstance(e, dict)]
            yield from _read_board(command, board.label, rows, board, False)
        return
    for path, rows in discover_leaderboards(command, payload):
        label = f"{command}{path}" if path else command
        yield from _read_board(command, label, rows, None, True)


def discover_leaderboards(command: str | None, payload):
    """Find ranking-shaped lists in a reply this file does not describe.

    Yields `(path, entries)`. The shape is "a list of at least
    LEADERBOARD_MIN_ENTRIES dicts, each with a uid and a name, and the first
    of them carrying a rank or a score column" — `name` is in there because
    every non-ranking that survived the other tests was a list of *things*
    rather than of players, and NOT_LEADERBOARDS holds the ones that are
    lists of players and still not boards.

    Nested lists are walked, because a board can arrive one level down inside
    a wrapper object, but only the outermost match on a branch is yielded: a
    board's entries are not themselves boards.
    """
    if command in NOT_LEADERBOARDS or not isinstance(payload, dict):
        return

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, f"{path}.{key}")
            return
        if not isinstance(node, list):
            return
        rows = [e for e in node if isinstance(e, dict)]
        if len(rows) >= LEADERBOARD_MIN_ENTRIES and _looks_like_board(rows[0]):
            yield path, rows
            return
        for index, item in enumerate(node[:3]):
            yield from walk(item, f"{path}[{index}]")

    yield from walk(payload, "")


def _looks_like_board(entry: dict) -> bool:
    """Whether one entry reads as a player's row in a ranking."""
    if entry.get("uid") is None or not entry.get("name"):
        return False
    if isinstance(entry.get("rank"), int):
        return True
    return any(isinstance(entry.get(f), int) for f in LEADERBOARD_SCORE_FIELDS)


def filter_players(players, level=None, alliance=None) -> list:
    """Narrow a base list. None means "any".

    `level` takes one HQ level or any iterable of them, matching the "or"
    reading `filter_tasks` gives it. `alliance` matches the abbreviation
    case-insensitively — the tag is drawn uppercase in game but nothing on the
    wire guarantees the case, and an exact-case filter that silently matches
    nothing is worse than a loose one.
    """
    levels = None
    if level is not None:
        levels = {level} if isinstance(level, int) else set(level)
    tag = alliance.strip().casefold() if alliance else None

    out = []
    for p in players:
        if levels is not None and p.level not in levels:
            continue
        if tag is not None and (p.alliance_abbr or "").casefold() != tag:
            continue
        out.append(p)
    # Highest level first — the bases worth looking at before the rest.
    out.sort(key=lambda p: (-(p.level or 0), p.uid))
    return out


# --------------------------------------------------------------------------
# Capture survey: every flow, classified
# --------------------------------------------------------------------------


def classify(data: bytes, transport: str = "tcp") -> str:
    if not data:
        return "empty"
    # The game protocol has only ever been seen over TCP. A lone 0x80 first
    # byte on UDP is a coincidence (LAN media streams hit it), so don't claim
    # GAME there — revisit if a UDP game channel ever shows up.
    if transport == "tcp" and (data[0] in SERVER_MAGICS or data[0] in CLIENT_MAGICS):
        return "GAME"
    # 0x16 handshake, 0x17 app-data, 0x15 alert — a capture that starts
    # mid-session shows app-data first, so accept any TLS record type.
    if data[0] in (0x14, 0x15, 0x16, 0x17) and data[1:2] == b"\x03" and data[2] <= 0x04:
        return "TLS"
    if re.match(rb"(GET|POST|PUT|HEAD|OPTIONS|DELETE) |HTTP/1", data[:16]):
        return "HTTP"
    if data[:4] == ZSTD_MAGIC:
        return "zstd"
    return "unknown"


def read_capture(pcap: str):
    """Reassemble TCP streams and bucket UDP, keeping per-offset timestamps."""
    from scapy.all import IP, TCP, UDP, PcapReader  # type: ignore

    tcp_segs: dict[tuple, dict[int, tuple[bytes, float]]] = defaultdict(dict)
    udp: dict[tuple, dict] = defaultdict(
        lambda: {"pkts": 0, "bytes": 0, "sample": b"", "t0": None}
    )

    for pkt in PcapReader(pcap):
        if not pkt.haslayer(IP):
            continue
        ts = float(pkt.time)
        if pkt.haslayer(TCP):
            tcp = pkt[TCP]
            body = bytes(tcp.payload)
            if not body:
                continue
            key = (pkt[IP].src, tcp.sport, pkt[IP].dst, tcp.dport)
            tcp_segs[key].setdefault(tcp.seq, (body, ts))
        elif pkt.haslayer(UDP):
            u = pkt[UDP]
            body = bytes(u.payload)
            if not body:
                continue
            peer = (
                (pkt[IP].dst, u.dport)
                if u.sport > u.dport or _is_local(pkt[IP].src)
                else (pkt[IP].src, u.sport)
            )
            slot = udp[peer]
            slot["pkts"] += 1
            slot["bytes"] += len(body)
            if not slot["sample"]:
                slot["sample"] = body[:48]
            if slot["t0"] is None:
                slot["t0"] = ts

    # Fold the two half-streams of each connection into one endpoint record.
    flows: dict[tuple, dict] = defaultdict(
        lambda: {"up": b"", "down": b"", "marks": [], "t0": None, "conns": 0}
    )
    for (src, sport, dst, dport), segs in tcp_segs.items():
        ordered = sorted(segs)
        data = b"".join(segs[s][0] for s in ordered)
        first = classify(data)
        if first == "GAME" and data[0] in SERVER_MAGICS:
            endpoint, direction = (src, sport), "down"
        elif first == "GAME":
            endpoint, direction = (dst, dport), "up"
        else:
            endpoint = (dst, dport) if sport > dport else (src, sport)
            direction = "up" if endpoint == (dst, dport) else "down"

        flow = flows[endpoint]
        base = len(flow[direction])
        offset = base
        for s in ordered:
            chunk, ts = segs[s]
            flow["marks"].append((direction, offset, ts))
            offset += len(chunk)
            if flow["t0"] is None or ts < flow["t0"]:
                flow["t0"] = ts
        flow[direction] += data
        flow["conns"] += 1

    for flow in flows.values():
        flow["marks"].sort(key=lambda m: (m[0], m[1]))
        flow["mark_index"] = {
            d: ([o for dd, o, _ in flow["marks"] if dd == d], [t for dd, _, t in flow["marks"] if dd == d])
            for d in ("up", "down")
        }
    return flows, udp


def _is_local(ip: str) -> bool:
    return ip.startswith(("192.168.", "10.", "172.1", "172.2", "172.3", "127."))


def time_at(flow: dict, direction: str, offset: int) -> float | None:
    offsets, times = flow["mark_index"][direction]
    if not offsets:
        return None
    i = bisect.bisect_right(offsets, offset) - 1
    return times[max(i, 0)]


def is_game(flow: dict) -> bool:
    """A flow is the game only if a frame actually decodes out of it.

    Checking the first byte alone is not enough: with three flag bits in play
    there are eight valid magic values per direction, so unrelated LAN traffic
    hits one by chance.
    """
    # Probing unrelated flows throws BadTag by design; those must not land in
    # unknown_tags, or the report invents protocol gaps that do not exist.
    saved = unknown_tags.copy()
    try:
        return _probe_game(flow)
    finally:
        unknown_tags.clear()
        unknown_tags.update(saved)


def _probe_game(flow: dict) -> bool:
    for direction in ("down", "up"):
        if classify(flow[direction]) != "GAME":
            continue
        window = flow[direction][:65536]
        covered = 0
        for env, start, end in iter_frames(window, direction):
            # The envelope is always a map carrying a "p" sub-map. Unrelated
            # traffic may hit a valid flag byte by chance, but it will not
            # decode into well-formed frames covering the whole stream.
            if isinstance(env, dict) and isinstance(env.get(K_PARAMS), dict):
                covered += end - start
        if covered >= 0.9 * len(window):
            return True
    return False


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def envelope_command(env) -> str | None:
    if not isinstance(env, dict):
        return None
    params = env.get(K_PARAMS)
    if isinstance(params, dict) and isinstance(params.get(K_COMMAND), str):
        return params[K_COMMAND]
    if isinstance(env.get(K_COMMAND), str):
        return env[K_COMMAND]
    return None


def envelope_payload(env):
    if isinstance(env, dict):
        params = env.get(K_PARAMS)
        if isinstance(params, dict):
            inner = params.get(K_PARAMS)
            return inner if inner is not None else params
    return env


def summarize(value, depth: int = 0) -> str:
    if isinstance(value, dict):
        if "_blob" in value:
            return f"<blob {len(value['_blob']) // 2}B>"
        if depth >= 2:
            return "{…}"
        return "{" + ", ".join(f"{k}={summarize(v, depth + 1)}" for k, v in list(value.items())[:8]) + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if depth >= 2:
            return f"[{len(value)}]"
        return f"[{len(value)}× {summarize(value[0], depth + 1)}]"
    if isinstance(value, str):
        return repr(value if len(value) <= 60 else value[:60] + "…")
    return str(value)


def clock(ts: float | None) -> str:
    if ts is None:
        return "--:--:--"
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().strftime("%H:%M:%S.%f")[:-3]


def print_survey(flows: dict, udp: dict) -> None:
    print(f"== TCP flows ({len(flows)}) ==")
    rows = sorted(flows.items(), key=lambda kv: -(len(kv[1]["up"]) + len(kv[1]["down"])))
    for (ip, port), flow in rows:
        kind = classify(flow["down"]) if flow["down"] else classify(flow["up"])
        tag = "GAME" if is_game(flow) else "    "
        sample = (flow["down"] or flow["up"])[:16].hex(" ")
        print(
            f"  {tag} {ip}:{port:<6} {kind:<8} up {len(flow['up']):>9,}B  "
            f"down {len(flow['down']):>9,}B  conns {flow['conns']}  {sample}"
        )
    if udp:
        print(f"\n== UDP flows ({len(udp)}) ==")
        for (ip, port), slot in sorted(udp.items(), key=lambda kv: -kv[1]["bytes"]):
            print(
                f"       {ip}:{port:<6} {classify(slot['sample'], 'udp'):<8} "
                f"{slot['pkts']:>7,} pkts  {slot['bytes']:>10,}B  {slot['sample'][:16].hex(' ')}"
            )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("pcap", help="capture.pcapng")
    ap.add_argument("--json", help="write the full decoded transcript here")
    ap.add_argument("--grep", help="only keep commands matching this regex")
    ap.add_argument("--timeline", action="store_true", help="print every message in time order")
    ap.add_argument("--survey-only", action="store_true", help="map the flows and stop")
    args = ap.parse_args()

    flows, udp = read_capture(args.pcap)
    print_survey(flows, udp)
    if args.survey_only:
        return 0

    game = {ep: f for ep, f in flows.items() if is_game(f)}
    if not game:
        print("\nno game flows found — wrong interface, or the game never connected.", file=sys.stderr)
        return 1

    pattern = re.compile(args.grep) if args.grep else None
    messages = []
    commands: Counter[str] = Counter()
    pushes: Counter[str] = Counter()
    fields: dict[str, Counter[str]] = defaultdict(Counter)

    for ep, flow in game.items():
        for direction in ("up", "down"):
            for env, offset, _ in iter_frames(flow[direction], direction):
                cmd = envelope_command(env) or "(keepalive)"
                payload = envelope_payload(env)
                (commands if direction == "up" else pushes)[cmd] += 1
                if isinstance(payload, dict):
                    for key in payload:
                        fields[cmd][key] += 1
                if pattern and not pattern.search(cmd):
                    continue
                messages.append(
                    {
                        "t": time_at(flow, direction, offset),
                        "endpoint": f"{ep[0]}:{ep[1]}",
                        "dir": direction,
                        "command": cmd,
                        "payload": payload,
                    }
                )

    messages.sort(key=lambda m: (m["t"] is None, m["t"]))

    if args.timeline:
        print(f"\n== timeline ({len(messages)} messages) ==")
        for m in messages:
            arrow = "-->" if m["dir"] == "up" else "<--"
            print(f"  {clock(m['t'])} {arrow} {m['command']}")
            print(f"                     {summarize(m['payload'])}")

    span = [m["t"] for m in messages if m["t"]]
    if span:
        print(f"\ncapture spans {clock(min(span))} .. {clock(max(span))} ({max(span) - min(span):.0f}s)")

    print(f"\n== client -> server ({sum(commands.values())} msgs) ==")
    for name, count in commands.most_common():
        print(f"  {count:<5} {name}")
        if fields[name]:
            print(f"        fields: {', '.join(k for k, _ in fields[name].most_common(12))}")

    print(f"\n== server -> client ({sum(pushes.values())} msgs) ==")
    for name, count in pushes.most_common():
        print(f"  {count:<5} {name}")
        if fields[name]:
            print(f"        fields: {', '.join(k for k, _ in fields[name].most_common(12))}")

    if unknown_tags:
        print("\n== unknown TLV tags (format gaps) ==")
        for tag, count in unknown_tags.most_common():
            print(f"  0x{tag:02x} × {count}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(messages, fh, ensure_ascii=False, indent=1)
        print(f"\nwrote {len(messages)} messages to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
