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

import game_clock

# Every timestamp decoded below is epoch milliseconds on the GAME's clock, and
# that clock is not this computer's — the two were eleven seconds apart when last
# measured, with the PC the one that was slow (#1227). So a record
# is judged against `game_clock.now_ms()`, never against `time.time()`, and the
# two differ by whatever the last live read said. Wall-clock `time.time()` is
# still right for the *host's* own bookkeeping — how long ago the capture saw a
# tile — and stays where it is used for that.

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

# A checkpoint is rewritten in place while readers poll it, so a read can land in
# the middle of a flush and see broken JSON. How many times to look again, and how
# long to wait in between — the writer takes milliseconds, so this is a blink.
CHECKPOINT_TRIES = 3
CHECKPOINT_RETRY_PAUSE = 0.25

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
#   * a 2026-07-19 live run (`--tasks --families`, server 100, 32 tasks) re-
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
#
# ALL OF IT IS THE FALLBACK NOW (#1244, #1267). Where the reading comes from a live
# CLIENT the answer is in the game's own `lw_dispatch_tasks` row — `level` and
# `is_special`, reached through `v.cfg:getValue(...)` — and the digits are consulted
# only when that row is missing (a template the client has not loaded) or when there
# is no client at all, which is every pcap and every chat-share record. `task_rank`
# below is where the two meet; nothing else may re-implement the precedence.
STAR_TASK_FAMILIES = frozenset({"6000"})


def starred_by_digits(family, level) -> bool:
    """The star, worked out from a cfgId alone — the FALLBACK half of :func:`task_rank`.

    Its own function because the callers that have nothing else are real and are not
    going away: a pcap tile, a chat-share record, a capture's printed finding. None of
    them is next to a client that could be asked for `is_special`, so all of them get
    the family rule with the `99` class taken out (:data:`STAR_TASK_FAMILIES`) — and all
    of them get it from HERE, so «the rule» stays one thing that can be corrected once.

    It is wrong for some templates. That is not a defect of this function; it is why
    anything reading a live client must go through :func:`task_rank` instead.
    """
    return family in STAR_TASK_FAMILIES and level != SPECIAL_TASK_LEVEL


def task_rank(cfg_id, cfg_level=None, cfg_special=None) -> "tuple[str, int, bool]":
    """``(family, level, starred)`` for a secret task — the CONFIG first, digits after.

    THE ONE PLACE THAT RULE LIVES. It was written twice, and the two copies drifted:
    #1244 taught the panel's read to prefer the config row and left the tool's own read
    parsing `ACT VT …` lines that never carried one, so on 2026-08-06 the same live tile
    was «level 7, no star» to the tab and «level 99» to `steal_secret_task --from-vm` —
    four of fifty-two rows, and the tool sorts its targets by level, so the mislabelled
    ones went to the head of the queue and spent the day's raids (#1267).

    ``cfg_level`` / ``cfg_special`` are the `level` and `is_special` columns as the
    client hands them over — 0 or None meaning «the client had no row for this
    template», which is the only case the arithmetic is still allowed to answer.

    The digits' answer is kept honest about its own limits: `LL` is read straight as the
    level and the `99` class is excluded from the star, because family alone over-reports
    (see :data:`STAR_TASK_FAMILIES`). Both of those are wrong for some templates — that
    is exactly why the config wins whenever there is one.

    Raises `ValueError`/`TypeError` for a cfgId that is not one, like `split_cfg_id`:
    a caller that cannot rank a record must drop it rather than invent a rank.
    """
    family, level, _variant = split_cfg_id(cfg_id)
    starred = starred_by_digits(family, level)
    if cfg_level:                     # 0 / None / "" all mean «the config said nothing»
        level, starred = int(cfg_level), bool(cfg_special)
    return family, level, starred


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
    #: The `is_special` column of the game's own config row, when the reading came from
    #: a client that had one (`task_rank`). `None` is «nobody asked the game», not
    #: «the game said no» — the two must not be the same value, or a pcap record would
    #: silently claim the config had denied the star (#1267).
    starred_cfg: "bool | None" = None

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
        compared against the GAME's now (`game_clock`), not this machine's: the
        two were eleven seconds apart when it was last measured — the PC being the
        slow one — and on the wrong side of that a tile the server would already pay
        out on reads «ещё выполняется» (#1227).
        """
        now = game_clock.now_ms()
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
        now = game_clock.now_ms()
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
        now = game_clock.now_ms()
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return (self.completed_at is not None
                and self.completed_at > now + PENDING_WINDOW_MS)

    @property
    def starred(self) -> bool:
        """Drawn with a star on the map — the game's own answer where there is one.

        `starred_cfg` is `is_special` off the client's `lw_dispatch_tasks` row and
        outranks everything below it (`task_rank`, #1244/#1267). Only a reading taken
        without a client — a pcap, a chat share, a template the client had not loaded —
        falls through to the digits, where the `99` class is excluded because family
        alone over-reports (see the note by STAR_TASK_FAMILIES).
        """
        if self.starred_cfg is not None:
            return self.starred_cfg
        return starred_by_digits(self.family, self.level)

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
            # …and WHERE the star came from, so a checkpoint written off a live client
            # is not re-derived from the digits when it is read back (#1267).
            "starred_cfg": self.starred_cfg,
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
            starred_cfg=record.get("starred_cfg"),
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


def load_fresh_tasks(path, max_age_seconds: "float | None" = TASK_FRESH_SECONDS,
                     now: float | None = None) -> list:
    """Load a capture checkpoint, keeping only tiles re-seen this scan window.

    ``max_age_seconds=None`` keeps EVERYTHING the checkpoint holds. That is what a
    panel list wants (#1251): the capture is a SOURCE, and what it finds belongs to the
    panel's own list from then on — kept, checkpointed, and removed when the panel's own
    rules say so (the task expired, it was robbed, a live read no longer confirms it),
    not because nobody has driven the map past it lately. A robbery decision is a
    different question and still asks for the window: see `AUTOLOOT_FRESH_SECONDS`'s
    callers.

    A raid decision must ignore any tile last observed outside the current
    window: its cached state is unverifiable and looks identical to a live one
    (the (159,90) false positive — still raidable a day after its dispatch
    "completed"). Each record carries `seen_at` (epoch seconds on the capture
    host); records without it, or older than `max_age_seconds`, are dropped.
    What survives comes back as `SecretTask` objects, so can_loot/pending are
    recomputed against the current clock rather than trusted as written.

    Accepts both the bare-list checkpoint and a ``{"tasks": [...]}`` wrapper.

    A read caught mid-flush is retried rather than raised. The capture rewrites
    the checkpoint in place every couple of seconds and deliberately does NOT
    rename a temp file over it (`map_capture.dump_records` explains why: on
    Windows that costs whole capture sessions), so a poller sees a half-written
    file every so often. Raising there cost the auto-loot the entire tick — the
    watcher logged «ошибка опроса скана» and robbed nothing until the next poll
    (#1227). The writer is finished in milliseconds, so a couple of short retries
    turn it into a delay nobody notices; only a file that is still broken after
    them is a real one, and that still raises.
    """
    now = time.time() if now is None else now
    data = None
    for attempt in range(CHECKPOINT_TRIES):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            break
        except json.JSONDecodeError:
            if attempt == CHECKPOINT_TRIES - 1:
                raise
            time.sleep(CHECKPOINT_RETRY_PAUSE)
    records = data.get("tasks") if isinstance(data, dict) else data
    fresh = []
    for record in records or ():
        seen = record.get("seen_at")
        if max_age_seconds is not None and (seen is None
                                            or now - seen > max_age_seconds):
            continue
        fresh.append(SecretTask.from_dict(record))
    return fresh


# --------------------------------------------------------------------------
# Alliance-shared secret missions (`push.alliance.share.mission.add`)
# --------------------------------------------------------------------------
#
# A *secret task* (§7, `f2 = 17`) is a tile the map hands out on `world.get.block`
# to everyone who pans over it. A *shared secret mission* is a different thing:
# an alliance member found one worth raiding and pressed "share", and the server
# broadcast it to the whole alliance so anyone can go assist/steal it. It never
# rides `world.get.block` — it arrives as its own push, keyed by the same
# `missionUuid` / `missionCfgId` a tile would carry, so the two streams line up
# but are captured in completely different ways: a task needs the map moving, a
# shared mission needs nobody but an ally pressing the button.
#
# Two commands carry them, and both go through `_share_mission_from_dict`:
#
#   * `push.alliance.share.mission.add` — the live broadcast, one mission per
#     frame. Confirmed on the wire (`results/rob_trap.jsonl`):
#         {missionCfgId: 60000701, missionUuid: 1394584906709054020,
#          missionCurrentServerId: 946, shareUid: "<uid>",
#          shareAllianceId: "<allianceId>", missionPlayerServerId: 946}
#     `missionCfgId 60000701` is family "6000" level 7 — a *starred* mission,
#     which is exactly what a player bothers to share.
#   * `get.alliance.share.mission.list` → `shareMissionArr[]` — the snapshot the
#     client pulls on login. Every capture caught it **empty**, so the element
#     field names are inferred from the push above, not observed. The parser is
#     deliberately tolerant of a missing key so a differently-named array
#     element still yields a partial record rather than nothing.
SHARE_MISSION_COMMANDS = (
    "push.alliance.share.mission.add",
    "get.alliance.share.mission.list",
)


@dataclass(slots=True)
class ShareMission:
    uuid: int | None
    cfg_id: int | None
    family: str | None
    level: int | None
    server_id: int | None         # missionCurrentServerId — where the tile sits now
    owner_server_id: int | None   # missionPlayerServerId — the owner's home server
    share_uid: str | None         # who shared it
    share_alliance_id: str | None

    @property
    def is_special(self) -> bool:
        """The level-99 template class — see SPECIAL_TASK_LEVEL / SecretTask."""
        return self.level == SPECIAL_TASK_LEVEL

    @property
    def starred(self) -> bool:
        """Drawn with a star — the family "6000" rule shared with SecretTask.

        A shared mission that is *not* starred is unusual: sharing is what a
        player does with a raid worth a march, and those are the starred ones.
        The rule lives in one place (`starred_by_digits`) so a task and the
        mission that references the same tile always agree on the star. A share
        push carries no config row — there is no client in it to ask — so this is
        the fallback by necessity, and it is wrong on the templates whose digits
        lie (#1267). Whoever robs off a share is robbing on the digits' word.
        """
        return starred_by_digits(self.family, self.level)

    def as_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "cfg_id": self.cfg_id,
            "family": self.family,
            "level": self.level,
            "server_id": self.server_id,
            "owner_server_id": self.owner_server_id,
            "share_uid": self.share_uid,
            "share_alliance_id": self.share_alliance_id,
        }

    @classmethod
    def from_dict(cls, record: dict) -> "ShareMission":
        return cls(
            uuid=record.get("uuid"),
            cfg_id=record.get("cfg_id"),
            family=record.get("family"),
            level=record.get("level"),
            server_id=record.get("server_id"),
            owner_server_id=record.get("owner_server_id"),
            share_uid=record.get("share_uid"),
            share_alliance_id=record.get("share_alliance_id"),
        )


def _share_mission_from_dict(item: dict) -> ShareMission | None:
    """One shared-mission record → `ShareMission`, or None if it is not one.

    `missionCfgId` is the anchor: without it there is no level, no star and no
    way to tell this dict from any other. `family`/`level` come off the cfgId
    the same way a task's do (`split_cfg_id`); a cfgId that does not split is
    kept as a raw number with no family/level rather than dropped, so a fifth
    family (see the `5000302` note in §7) still surfaces.
    """
    if not isinstance(item, dict):
        return None
    cfg = item.get("missionCfgId")
    uuid = item.get("missionUuid")
    if cfg is None and uuid is None:
        return None  # not a shared-mission record at all
    family = level = None
    if cfg is not None:
        try:
            family, level, _variant = split_cfg_id(cfg)
        except (ValueError, TypeError):
            family = level = None
    return ShareMission(
        uuid=uuid,
        cfg_id=int(cfg) if isinstance(cfg, int) else cfg,
        family=family,
        level=level,
        server_id=item.get("missionCurrentServerId"),
        owner_server_id=item.get("missionPlayerServerId"),
        share_uid=item.get("shareUid"),
        share_alliance_id=item.get("shareAllianceId"),
    )


def share_missions(command: str | None, payload):
    """Yield every shared secret mission in one decoded frame.

    Routes on `command`: the `.add` push carries one mission *as* the payload,
    the `.list` response wraps them in `shareMissionArr`. Anything else yields
    nothing, so a caller can hand every frame through without pre-filtering —
    though `command in SHARE_MISSION_COMMANDS` is the cheap guard.
    """
    if not isinstance(payload, dict):
        return
    if command == "get.alliance.share.mission.list":
        items = payload.get("shareMissionArr") or ()
        for item in items:
            mission = _share_mission_from_dict(item)
            if mission is not None:
                yield mission
    elif command == "push.alliance.share.mission.add":
        mission = _share_mission_from_dict(payload)
        if mission is not None:
            yield mission


def filter_share_missions(missions, level=None, star_only=False,
                          server=None) -> list:
    """Narrow a shared-mission list. None/False means "any".

    `level` takes one level or any iterable of them (matches any — see
    `filter_tasks`). `star_only` keeps only starred missions. `server` keeps
    only missions whose tile currently sits on that server
    (`missionCurrentServerId`), which is the one you would march to.
    """
    levels = None
    if level is not None:
        levels = {level} if isinstance(level, int) else set(level)

    out = []
    for m in missions:
        if levels is not None and m.level not in levels:
            continue
        if star_only and not m.starred:
            continue
        if server is not None and m.server_id != server:
            continue
        out.append(m)
    # Starred first, then highest level — the order you would raid in.
    out.sort(key=lambda m: (not m.starred, -(m.level or 0)))
    return out


# --------------------------------------------------------------------------
# Secret missions — "Операция Призрак" / ghost recon (`ghost.recon.*`)
# --------------------------------------------------------------------------
#
# The in-game "секретная миссия" — the **Secret Command Post** ("Секретный
# командный пункт"), its "Операция Призрак" tab (a helmet icon). Confirmed live
# 2026-07-23 (a Thursday — the feature runs weekly): opening that panel fires
# `ghost.recon.get.task.list`, and "Команда союзников" (the ally-help list)
# fires `ghost.recon.get.alliance.task.list`. This is a third, distinct thing
# from the two above — not a `world.get.block` tile (a *secret task*), not an
# `alliance.share.mission` push (a *shared* task). A ghost-recon mission is a
# co-op dispatch: an ally sends a squad, others join to help, everyone loots.
#
# Raw sample: results/task1004/ghost_recon_task_list.json (6 tasks). The
# response wraps them in `taskList`, with a dispatch window around it:
#
#     {dispatchBeginTime, dispatchEndTime, openTime, autoStart, taskList: [ ... ]}
#
# Per task (all fields observed):
#
# | Field | Meaning |
# |---|---|
# | `uuid` | mission id |
# | `cfgId` | config id — rarity/type/level (see below) |
# | `state` | 0 empty slot · 2 running · 3 done (lootable / help-rewardable) |
# | `pointId` | target coordinate, `y*1000+x` (0 while `state` 0) |
# | `targetServer` | server the mission targets |
# | `ownerId` / `ownerServer` / `allianceId` | who launched it |
# | `allianceShow` | 1 = visible to the alliance (joinable), 0 = private |
# | `memberList[]` | the squads: leader + helpers, each `heroList` + `memberInfo` + `canReward`/`rewarded`/`helpRewarded` |
# | `stealList[]` | who already looted it — `{uid, name, abbr, reward[], time}` |
# | `teamStartTime` / `completionTime` / `taskExpireTime` / `actEndTime` | epoch-ms timers |
#
# `cfgId` is five digits `F` + `MM` + `VV`: a single-digit rarity family "4"/"5"/"6"
# (the UI colours SSR / UR★ / …), the two `MM` digits, then a variant. The generic
# `split_cfg_id` reads `MM` straight as the level and reports 1/2/3, but the game's
# level ("ур.5") is `MM + 2` — the "lvl3 for an ур.5 mission" bug, task #1137.
# `ghost_recon_level` applies the corrected mapping (see `GHOST_LEVEL_OFFSET`,
# read off the live `ActGhostreconTaskTemplate`). The rarity family is a separate
# axis from the level (family "6" is the star, not level 6). Raw `cfg_id` is kept.
GHOST_RECON_COMMANDS = (
    "ghost.recon.get.task.list",
    "ghost.recon.get.alliance.task.list",
)

# `state` values, named. 1 is unobserved (no task carried it) — left out rather
# than guessed at.
GHOST_STATE_EMPTY = 0     # a dispatch slot nobody has filled yet
GHOST_STATE_RUNNING = 2   # squad is out; not lootable yet
GHOST_STATE_DONE = 3      # completed — lootable, and helpers can claim reward

# The top rarity tier, the ghost-recon analogue of a secret task's star
# (STAR_TASK_FAMILIES). cfgId families run 4/5/6 (see split_cfg_id); "6" is the
# rarest, the one worth calling out with a star — same idea, different digits.
GHOST_STAR_FAMILY = "6"

# A ghost cfgId is `F` + `MM` + `VV`: rarity family (4/5/6), the two `MM` digits,
# then a variant. `split_cfg_id` reads `MM` straight as the level and so reports
# 1/2/3 — but the game's `ActGhostreconTaskTemplate.level` is exactly `MM + 2`:
# `01`→ур.3, `02`→ур.4, `03`→ур.5, the same for every family. This was read off
# the live template for every real ghost cfgId (task #1137): only `MM` in 01..03
# has a template, family never changes the level, and each shifts the wire number
# up by two. The rarity family is a separate axis (the star, GHOST_STAR_FAMILY),
# not the level. Only these three tiers exist today; a higher `MM` would extend
# the same `+2` line but none has been seen, so it stays a documented assumption.
GHOST_LEVEL_OFFSET = 2


def ghost_recon_level(cfg_id) -> tuple[str | None, int | None]:
    """`(family, level)` for a ghost-recon cfgId — the *player-facing* level.

    `level` is the game's ("ур.5"), not the wire's raw `MM` digits: those read
    1/2/3 where the UI shows 3/4/5, the "lvl3 for an ур.5 mission" bug fixed in
    task #1137. See `GHOST_LEVEL_OFFSET` for the `MM + 2` mapping and how it was
    read off the live template. `family` is the rarity string `split_cfg_id`
    returns, kept as-is so `GHOST_STAR_FAMILY`/`filter_ghost_recon` keep working;
    a cfgId that does not split degrades to `(None, None)`.
    """
    try:
        family, mid_level, _variant = split_cfg_id(cfg_id)
    except (ValueError, TypeError):
        return None, None
    return family, mid_level + GHOST_LEVEL_OFFSET


@dataclass(slots=True)
class GhostReconMission:
    uuid: int | None
    cfg_id: int | None
    family: str | None
    level: int | None
    state: int | None
    target_server: int | None
    owner_id: str | None
    owner_server: int | None
    alliance_id: str | None
    alliance_show: bool
    point_id: int | None
    x: int | None
    y: int | None
    member_count: int
    steal_count: int
    team_start_time: int | None
    completion_time: int | None
    expire_time: int | None
    #: When the capture last SAW this tile (epoch seconds on the capture host), or None
    #: for a record that carries no stamp. Not a wire field — the checkpoint's own — and
    #: kept because a reader should be able to say how old its information is instead of
    #: hiding a row for being old (#1251).
    seen_at: float | None = None

    @property
    def running(self) -> bool:
        return self.state == GHOST_STATE_RUNNING

    @property
    def done(self) -> bool:
        """Completed — the squad is back, so it can be looted / rewarded."""
        return self.state == GHOST_STATE_DONE

    @property
    def empty(self) -> bool:
        """A slot nobody has dispatched into yet (no coordinate, no members)."""
        return self.state == GHOST_STATE_EMPTY

    @property
    def joinable(self) -> bool:
        """Shown to the alliance and actually dispatched — an ally can help.

        A private (`allianceShow` 0) or still-empty slot is not something a
        teammate can join, so those are excluded even though they are real rows.
        """
        return self.alliance_show and not self.empty

    @property
    def can_loot(self) -> bool:
        """Lootable right now: the squad is back and the mission has not expired.

        On a `world.get.block` tile the numeric `state` (f9) is not a reliable
        "done" flag — every ghost tile observed carried `f9 = 3` whether or not
        its squad had actually returned — so lootability is read off the clock,
        exactly as a secret task's is (`SecretTask.can_loot`). `completion_time`
        (the tile's f3, the squad's return time) must be set and no longer in the
        future; `expire_time` (f7 / taskExpireTime, the weekly window end) must
        still be ahead. Both are epoch milliseconds on the game's clock.

        The polled list carries a trustworthy `state`, so there `done` and
        `can_loot` agree; only on the map does the timer override a bogus `f9`.
        """
        now = game_clock.now_ms()
        if self.completion_time is None or self.completion_time > now:
            return False
        if self.expire_time is not None and self.expire_time <= now:
            return False
        return True

    @property
    def starred(self) -> bool:
        """Top rarity tier — the ghost-recon analogue of a secret task's star.

        The rule lives in one place (GHOST_STAR_FAMILY) so a mission and the
        scanner agree on what a star is.
        """
        return self.family == GHOST_STAR_FAMILY

    def as_dict(self) -> dict:
        return {
            "uuid": self.uuid, "cfg_id": self.cfg_id, "family": self.family,
            "level": self.level, "state": self.state,
            "target_server": self.target_server, "owner_id": self.owner_id,
            "owner_server": self.owner_server, "alliance_id": self.alliance_id,
            "alliance_show": self.alliance_show, "point_id": self.point_id,
            "x": self.x, "y": self.y, "member_count": self.member_count,
            "steal_count": self.steal_count,
            "team_start_time": self.team_start_time,
            "completion_time": self.completion_time,
            "expire_time": self.expire_time,
        }

    @classmethod
    def from_dict(cls, record: dict) -> "GhostReconMission":
        return cls(
            uuid=record.get("uuid"), cfg_id=record.get("cfg_id"),
            family=record.get("family"), level=record.get("level"),
            state=record.get("state"),
            target_server=record.get("target_server"),
            owner_id=record.get("owner_id"),
            owner_server=record.get("owner_server"),
            alliance_id=record.get("alliance_id"),
            alliance_show=bool(record.get("alliance_show")),
            point_id=record.get("point_id"), x=record.get("x"),
            y=record.get("y"), member_count=record.get("member_count", 0),
            steal_count=record.get("steal_count", 0),
            team_start_time=record.get("team_start_time"),
            completion_time=record.get("completion_time"),
            expire_time=record.get("expire_time"),
        )


def _ghost_task_from_dict(task: dict) -> GhostReconMission | None:
    """One `taskList[]` entry → `GhostReconMission`, or None if not one.

    `uuid` is the anchor: a row without it is not a mission. `cfgId` may be
    absent on an empty slot in principle, so a missing/odd cfgId degrades to raw
    number with no family/level rather than dropping the row — an empty slot is
    still information (a server the alliance has not filled yet).
    """
    if not isinstance(task, dict):
        return None
    uuid = task.get("uuid")
    if uuid is None:
        return None
    cfg = task.get("cfgId")
    family = level = None
    if cfg is not None:
        family, level = ghost_recon_level(cfg)
    point = task.get("pointId") or 0
    x = point % 1000 if point else None
    y = point // 1000 if point else None
    members = task.get("memberList")
    steals = task.get("stealList")
    return GhostReconMission(
        uuid=uuid,
        cfg_id=int(cfg) if isinstance(cfg, int) else cfg,
        family=family, level=level,
        state=task.get("state"),
        target_server=task.get("targetServer"),
        owner_id=task.get("ownerId"),
        owner_server=task.get("ownerServer"),
        alliance_id=task.get("allianceId"),
        alliance_show=bool(task.get("allianceShow")),
        point_id=point or None, x=x, y=y,
        member_count=len(members) if isinstance(members, list) else 0,
        steal_count=len(steals) if isinstance(steals, list) else 0,
        team_start_time=task.get("teamStartTime") or None,
        completion_time=task.get("completionTime") or None,
        expire_time=task.get("taskExpireTime") or None,
    )


def ghost_recon_missions(command: str | None, payload):
    """Yield every ghost-recon mission in one decoded frame.

    Both `ghost.recon.get.task.list` and `ghost.recon.get.alliance.task.list`
    wrap the rows in `taskList`, so the command only has to be one of them; the
    shape is identical. `command` is accepted (and ignored beyond the guard) to
    match `share_missions`' signature so callers route the same way.
    """
    if command not in GHOST_RECON_COMMANDS or not isinstance(payload, dict):
        return
    for task in payload.get("taskList") or ():
        mission = _ghost_task_from_dict(task)
        if mission is not None:
            yield mission


# The live alliance ghost-recon stream. Unlike the two `get.*.task.list`
# commands, which only answer when the client polls the panel, this one is
# *pushed*: the server sends one team the instant it appears, changes, or ends.
# It is the ghost-recon analogue of `push.alliance.share.mission.*` — the command
# that makes real-time detection (not just on-demand listing) possible.
GHOST_ALLIANCE_PUSH = "push.ghost.recon.alliance.single"


def ghost_recon_alliance_push(payload):
    """Decode one ``push.ghost.recon.alliance.single`` frame.

    The server pushes a single alliance ghost-recon team, tagged by ``type``:

      * ``add``    — a teammate just dispatched a ghost-recon squad;
      * ``change`` — that team changed (a helper joined, reward state moved, ...);
      * ``remove`` — the team is gone (completed / expired / recalled).

    ``add``/``change`` carry a mission-shaped ``info`` — the same fields a
    ``taskList`` entry has, minus ``state``/``stealList`` (the push does not carry
    a numeric state; the ``type`` *is* the state signal). ``remove`` carries only
    the bare ``uuid``.

    Returns ``(kind, mission)`` — ``kind`` one of add/change/remove and
    ``mission`` a `GhostReconMission` (for ``remove``, one that carries only its
    ``uuid``) — or ``None`` if the frame is not a recognisable push of this
    command. ``point_id`` on the mission decodes to ``x``/``y`` exactly as it does
    for the polled list.
    """
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    if kind == "remove":
        uuid = payload.get("uuid")
        if uuid is None:
            return None
        return kind, GhostReconMission.from_dict({"uuid": uuid})
    if kind not in ("add", "change"):
        return None
    mission = _ghost_task_from_dict(payload.get("info"))
    if mission is None:
        return None
    return kind, mission


# The ghost-recon squad drawn on the world map — object type `f2 = 29` on
# `world.get.block`, alongside secret tasks (`f2 = 17`), bases (`6`), mines (`7`).
GHOST_RECON_TILE_TYPE = 29


def ghost_recon_tiles(payload: dict):
    """Yield every ghost-recon squad drawn on the map as an `f2 = 29` tile.

    Confirmed live 2026-07-23 (task #1010, `results/task1010/tiles.jsonl`): a
    ghost-recon dispatch ("Операция Призрак") is NOT only a `ghost.recon.*` poll
    row — it is also a `world.get.block` tile, handed to anyone who pans over it,
    exactly like a secret task. This overturns the earlier "ghost recon never
    rides world.get.block" conclusion: it does, under a tile type we had been
    discarding as an unknown. The tile packs the same mission in protobuf field
    numbers under `f14` that the poll carries under named keys:

        f14.f1  ownerId            f14.f6  targetServer
        f14.f2  cfgId (fam 4/5/6)  f14.f7  taskExpireTime (weekly, shared)
        f14.f3  completionTime     f14.f8  mission uuid (32-hex form)
        f14.f5  memberList[]       f14.f9  state (see the f9 caveat below)
        f14.f11 teamStartTime      f14.f10 2147483647000 (no-expiry sentinel)

    Two field pairings matter and are *not* what a first read suggests. `f3` is
    the **completionTime** — when the dispatched squad returns and the mission
    becomes lootable — and `f11` is the earlier **teamStartTime**; the poll's
    named keys prove the ordering (`completionTime > teamStartTime` always) and
    `f3 > f11` holds for every tile, with `f3 - f11` (~45-86 min) matching the
    poll's dispatch duration. This is the same `f3 = completed_at` the secret-task
    tile uses (`SecretTask.can_loot`), the shared tile format.

    **The `f9` state is NOT a reliable done flag on the map** — every ghost tile
    in the confirming capture carried `f9 = 3` regardless of whether its squad had
    actually returned, so a scan that trusted it announced still-running missions
    as lootable. Lootability is therefore read off the clock instead
    (`GhostReconMission.can_loot`): completionTime (`f3`) in the past and
    taskExpireTime (`f7`) still ahead. What does tell the tile apart from every
    other kind is cfgId family 4/5/6 (the ghost rarity tiers) plus the shared
    weekly `f7`. Coordinates come out server-local (`f1 % maxAreaSize`), the
    mission's `pointId`. `owner_server` is the tile's own server (`f102`/`f103`),
    where the squad is drawn; `target_server` (`f14.f6`) is the different id it
    attacks.
    """
    for block in payload.get("serverPointArr") or ():
        area = block.get("maxAreaSize") or 1000
        for point in block.get("points") or ():
            tile = point.get("_protobuf") or {}
            if tile.get("f2") != GHOST_RECON_TILE_TYPE:
                continue
            detail = tile.get("f14") or {}
            cfg = detail.get("f2")
            family = level = None
            if cfg is not None:
                family, level = ghost_recon_level(cfg)
            # `f5` is the squad: a list of members, or a bare dict when the
            # dispatch has only its leader so far.
            members = detail.get("f5")
            member_count = (len(members) if isinstance(members, list)
                            else 1 if isinstance(members, dict) else 0)
            packed = tile.get("f1") or 0
            yield GhostReconMission(
                uuid=tile.get("f100"),
                cfg_id=int(cfg) if isinstance(cfg, int) else cfg,
                family=family, level=level,
                state=detail.get("f9"),
                target_server=detail.get("f6"),
                owner_id=detail.get("f1"),
                owner_server=tile.get("f102") or tile.get("f103"),
                alliance_id=None,
                alliance_show=True,
                point_id=packed or None,
                x=packed % area, y=packed // area,
                member_count=member_count,
                steal_count=0,
                team_start_time=detail.get("f11"),
                completion_time=detail.get("f3"),
                expire_time=detail.get("f7"),
            )


def filter_ghost_recon(missions, level=None, family=None, star_only=False,
                       state=None, server=None, joinable=False,
                       done=False, can_loot=False) -> list:
    """Narrow a ghost-recon list. None/False means "any".

    `level`/`family`/`state`/`server` each take one value or an iterable
    (matches any). `star_only` keeps only the top rarity tier (family
    GHOST_STAR_FAMILY), the analogue of `filter_tasks`' `star_only`; it ANDs
    with an explicit `--family` the same way the secret-task scan lets you say
    `--star --level 7`. `joinable` keeps only alliance-visible, dispatched
    missions an ally can help; `done` keeps only ones the numeric state calls
    completed (trustworthy on the *poll*); `can_loot` keeps only ones lootable
    right now by the clock (`completion_time` past, not expired) — the correct
    gate on a *map tile*, where `state` (f9) is not a reliable done flag. These
    three are ANDed with the rest but ORed with each other — the same "one
    dimension, several values" rule as `filter_tasks`' can_loot/pending.
    """
    def _set(v):
        return None if v is None else ({v} if isinstance(v, (int, str)) else set(v))

    levels, families, states, servers = map(
        _set, (level, family, state, server))

    out = []
    for m in missions:
        if levels is not None and m.level not in levels:
            continue
        if families is not None and m.family not in families:
            continue
        if star_only and not m.starred:
            continue
        if states is not None and m.state not in states:
            continue
        if servers is not None and m.target_server not in servers:
            continue
        if joinable or done or can_loot:
            if not ((joinable and m.joinable) or (done and m.done)
                    or (can_loot and m.can_loot)):
                continue
        out.append(m)
    # Done first (act on those now), then running, then empty; then most-looted
    # last so the freshest loot is on top.
    out.sort(key=lambda m: (m.state != GHOST_STATE_DONE, m.steal_count))
    return out


def load_fresh_ghost_recon(path, max_age_seconds: "float | None" = TASK_FRESH_SECONDS,
                           now: float | None = None) -> list:
    """Load a ghost-recon scan checkpoint, keeping only tiles re-seen this window.

    The `load_fresh_tasks` rule applied to the `f2 = 29` scan: a squad the map has
    stopped re-sending may have returned, been looted out or expired, and a stale
    record is indistinguishable from a live one. What survives comes back as
    `GhostReconMission` objects, so `can_loot` is recomputed against the clock.

    ``max_age_seconds=None`` keeps everything, for the same reason as above (#1251):
    the panel's list is the panel's, and the capture only fills it.

    Each mission comes back with the `seen_at` it was checkpointed with, so a reader
    can SAY how old a row's information is instead of hiding the row for being old.
    """
    now = time.time() if now is None else now
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    records = data.get("missions") if isinstance(data, dict) else data
    fresh = []
    for record in records or ():
        seen = record.get("seen_at")
        if max_age_seconds is not None and (seen is None
                                            or now - seen > max_age_seconds):
            continue
        mission = GhostReconMission.from_dict(record)
        # Not a field of the wire record — the capture stamps it — so it rides on the
        # object rather than in the dataclass, which mirrors the game's own message.
        try:
            mission.seen_at = seen
        except AttributeError:               # slots: an older build without the field
            pass
        fresh.append(mission)
    return fresh


# --------------------------------------------------------------------------
# World-map treasures — the detect-event chests (`f2 = 21`)
# --------------------------------------------------------------------------
#
# A treasure is a map point like every other interactable: `world.get.block`
# hands it to anyone who pans over it, and `push.world.point.update` re-sends it
# whenever it changes. Decoded from the live capture of task #1107
# (`results/traffic/20260728_155731_сокровище_traffic.jsonl`, eleven frames of the
# same chest plus the `push.detect.treasure.claim` that finished it), so every
# field below was read off a real treasure rather than inferred:
#
#     f1   500553                 packed pointId
#     f2   21                     WorldPointType.TREASURE
#     f100 1397117530950313784    uuid — what `detect.event.claim.treasure` takes
#     f102/f103 100               the server the chest sits on
#     f11  the treasure record:
#          f1  uuid (again)       f9  placed-at
#          f2  owner uid          f12 name          ("Uzilla")
#          f3  cfgId  ("25193")   f13 expiry ts
#          f5  alliance uuid      f7  **operator uid — the dug flag**
#          f6  alliance abbr      f16 {uuid, pointId, …}
#
# `f7` is the one field that carries a decision. It is ABSENT in the first ten
# frames — the chest is still being dug — and appears in the eleventh, the same
# frame the alliance got `push.detect.treasure.claim {uuid, operator}` for. So
# "still digging vs already dug" is `f7` present, exactly as
# docs/research/world-treasures.md predicted from the same session.
#
# ⚠ The x/y below are unpacked the way every other tile in this module is
# (`packed % area`, `packed // area`), which puts this chest at (553,500). The
# game's own `SceneUtils.IndexToTilePos(500553)` answered (552,500) and the
# in-game system line agreed with the game — so a treasure ROW may sit one tile
# east of where the game names it. Nothing that acts is affected: the dig and the
# claim take `point_id` and `uuid`, never x/y, and the panel's other treasure
# list reads its coordinates through `IndexToTilePos` itself.
WORLD_TREASURE_TILE_TYPE = 21


@dataclass(slots=True)
class WorldTreasure:
    uuid: int | None
    cfg_id: str | None
    server_id: int | None
    point_id: int | None
    x: int | None
    y: int | None
    name: str | None
    owner_uid: str | None
    alliance_id: str | None
    alliance_abbr: str | None
    operator_uid: str | None      # who finished the dig; None while it is still on
    expires_at: int | None

    @property
    def dug(self) -> bool:
        """Fully dug — the point carries the finisher's uid (`f11.f7`).

        This is the split the whole feature turns on: a chest still being dug wants
        a march, a dug one wants the claim.
        """
        return bool(self.operator_uid)

    @property
    def expired(self) -> bool:
        return (self.expires_at is not None
                and self.expires_at <= game_clock.now_ms())

    def as_dict(self) -> dict:
        return {
            "uuid": self.uuid, "cfg_id": self.cfg_id, "server_id": self.server_id,
            "point_id": self.point_id, "x": self.x, "y": self.y, "name": self.name,
            "owner_uid": self.owner_uid, "alliance_id": self.alliance_id,
            "alliance_abbr": self.alliance_abbr, "operator_uid": self.operator_uid,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, record: dict) -> "WorldTreasure":
        return cls(
            uuid=record.get("uuid"), cfg_id=record.get("cfg_id"),
            server_id=record.get("server_id"), point_id=record.get("point_id"),
            x=record.get("x"), y=record.get("y"), name=record.get("name"),
            owner_uid=record.get("owner_uid"), alliance_id=record.get("alliance_id"),
            alliance_abbr=record.get("alliance_abbr"),
            operator_uid=record.get("operator_uid"),
            expires_at=record.get("expires_at"),
        )


def _treasure_from_point(point: dict, area: int, server=None):
    """One decoded map point → `WorldTreasure`, or None if it is not a treasure."""
    tile = (point or {}).get("_protobuf") or {}
    if tile.get("f2") != WORLD_TREASURE_TILE_TYPE:
        return None
    detail = tile.get("f11") or {}
    packed = tile.get("f1") or 0
    return WorldTreasure(
        uuid=tile.get("f100") or detail.get("f1"),
        cfg_id=detail.get("f3"),
        server_id=tile.get("f102") or tile.get("f103") or server,
        point_id=packed or None,
        x=packed % area, y=packed // area,
        name=detail.get("f12"),
        owner_uid=detail.get("f2"),
        alliance_id=detail.get("f5"),
        alliance_abbr=detail.get("f6"),
        operator_uid=detail.get("f7"),
        expires_at=detail.get("f13"),
    )


def world_treasures(payload: dict):
    """Yield every treasure drawn on the map in one `world.get.block` response."""
    for block in payload.get("serverPointArr") or ():
        area = block.get("maxAreaSize") or 1000
        for point in block.get("points") or ():
            treasure = _treasure_from_point(point, area)
            if treasure is not None:
                yield treasure


def world_treasure_points(command: str | None, payload):
    """Yield every treasure in a `push.world.point.update` frame.

    This is the stream the chest was actually captured on, and the one that carries
    the moment it is dug: the push repeats the point on every change, so the row
    flips from digging to dug without anyone panning over it again. A `remove`
    update is skipped — the point is gone, and yielding it would put a chest that
    no longer exists on a list.

    The push has no `maxAreaSize`, so the coordinates use the standard 1000-wide
    server; the `point_id` it also yields is exact regardless.
    """
    if command != "push.world.point.update" or not isinstance(payload, dict):
        return
    if payload.get("type") == "remove":
        return
    server = payload.get("sid")
    for point in payload.get("points") or ():
        treasure = _treasure_from_point(point, 1000, server=server)
        if treasure is not None:
            yield treasure


def load_fresh_treasures(path, max_age_seconds: float = TASK_FRESH_SECONDS,
                         now: float | None = None) -> list:
    """Load a treasure-scan checkpoint, keeping only points re-seen this window.

    Same rule as `load_fresh_tasks`, and for the same reason: a chest the map has
    stopped re-sending may have been dug and taken minutes ago, and a stale record
    reads exactly like a live one.
    """
    now = time.time() if now is None else now
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    records = data.get("treasures") if isinstance(data, dict) else data
    fresh = []
    for record in records or ():
        seen = record.get("seen_at")
        if seen is None or now - seen > max_age_seconds:
            continue
        fresh.append(WorldTreasure.from_dict(record))
    return fresh


# --------------------------------------------------------------------------
# Map semantics: trucks, the march-type-37 `train` objects
# --------------------------------------------------------------------------
#
# A truck is not a tile. It never appears in `world.get.block` at all, which is
# why a scan built on map blocks alone finds none: it rides the *march* stream,
# as an ordinary march of type 37 (`_proto._protobuf.f11`) carrying an extra
# `train` object beside it. Three commands deliver them, and all three nest the
# march the same way apart from the wrapper:
#
#     push.world.march.world.get.new   .serverMarchArr[].marchInfos[]
#     world.get.march.infos            .marchInfos[]
#     push.world.march.new             the payload itself is one march
#     push.world.march.del             {ownerUid, uuid, isBattleFail} — gone
#
# Of the 158 trucks in the saved captures, 157 are `type: 1` (a player's own
# truck, the robbable one) and 1 is `type: 2` — the alliance train, which has
# no owner and a `carriageList` instead of a squad. Only type 1 is yielded.
#
# The march protobuf carries the geometry, the `train` object the cargo:
#
#     f9  / f10   current leg, packed y * 1000 + x, server-local
#     f13 / f14   when that leg started / ends, epoch ms
#     f26         serverId
#     train.uid           owner uid (== the wrapper's ownerUid, 177/177)
#     train.name          owner name        train.country   country code
#     train.allianceId    alliance uuid     train.abbr      alliance tag
#     train.cfgId         tier + level, see split_truck_cfg_id()
#     train.startPos      where it set out (the owner's city)
#     train.arriveTime    when the whole run ends and it leaves the map
#     train.marchInfo.robTimes       how many times it has been robbed
#     train.marchInfo.plunderRecord  who did it, with their power
#     train.marchInfo.power          escort power
#     train.marchInfo.heroInfo       escort squad, keyed by slot
#     train.baseGoods.full           the cargo it set out with
#
# `startPos` is NOT the current position and `arriveTime` is NOT the leg's end:
# a truck hops station to station, so f9/f10/f13/f14 describe only the hop it
# is on right now (0/177 matches against startPos, 0/177 against arriveTime).
# Position therefore has to be interpolated along the current leg — see
# `Truck.position`.

# --------------------------------------------------------------------------
# Resource mines (`world.get.block` f2 = 7)
# --------------------------------------------------------------------------
#
# The most common thing on the map by a wide margin — one recorded whole-server
# lap at height 600 held 12 725 of them against 6 723 bases and 982 secret
# tasks. The tile is tiny: everything is in the `f6` sub-message.
#
#     f6.f1   resource family * 100 + level, levels 1..10 (12 during a season)
#     f6.f2   1 on all 12 725 mines of that lap — no meaning read off it yet
#     f6.f3   the gathering activity's uuid, present only while it is taken
#     f6.f8   the gathering player's uid        f6.f9   their server
#     f6.f10  their alliance uuid
#
# The family → resource mapping was confirmed against the game screen by the
# maintainer (docs/research/protocol.md, «Resource mines»); nothing on the wire
# names them, so this table is a reading of the screen and not of the protocol.
MINE_TILE_TYPE = 7

#: `f6.f1 // 100` → what the mine yields. Families 0/1/2 are the ordinary three.
#: A fourth family, 80, turned up FOUR times in the same lap (`8001`, `8004`,
#: carrying an occupier under `f6.f7` instead of `f6.f8`) and is deliberately
#: NOT named here: two tiles are not enough to say what a player sees on them,
#: and a guessed name is worse than an honest «unknown» (see `Mine.resource`).
MINE_RESOURCES = {0: "bread", 1: "iron", 2: "gold"}

#: The stride the family and the level are packed with.
MINE_FAMILY_STRIDE = 100


def split_mine_value(value) -> tuple:
    """`f6.f1` → `(family, level)`, or `(None, None)` when it is not a number."""
    try:
        packed = int(value)
    except (TypeError, ValueError):
        return None, None
    family, level = divmod(packed, MINE_FAMILY_STRIDE)
    return family, level


@dataclass(slots=True)
class Mine:
    """One resource node on the world map, free or being gathered."""

    point_id: int | None
    server_id: int | None
    x: int | None
    y: int | None
    family: int | None
    level: int | None
    #: The uid of whoever is gathering it, None while it is free.
    owner_uid: str | None
    owner_server: int | None
    alliance_id: str | None
    activity_uuid: int | None

    @property
    def resource(self) -> str | None:
        """`"bread"` / `"iron"` / `"gold"`, or None for a family nobody has named."""
        return MINE_RESOURCES.get(self.family)

    @property
    def free(self) -> bool:
        """Nobody is gathering it — which is the only reason to march on one."""
        return not self.owner_uid

    @property
    def uuid(self):
        """What a list keys a mine BY, and it is the tile rather than an entity.

        A mine carries no uuid of its own on the wire — `tools/dev/gather.py`
        marches on one with `targetUuid = 0` — so the tile id is its identity.
        Paired with the server, because a point id is only unique within one.
        """
        return "%s:%s" % (self.server_id, self.point_id)

    def as_dict(self) -> dict:
        return {
            "uuid": self.uuid, "point_id": self.point_id,
            "server_id": self.server_id, "x": self.x, "y": self.y,
            "family": self.family, "level": self.level,
            "resource": self.resource, "free": self.free,
            "owner_uid": self.owner_uid, "owner_server": self.owner_server,
            "alliance_id": self.alliance_id,
            "activity_uuid": self.activity_uuid,
        }


def mines(payload: dict):
    """Yield every resource mine in one decoded `world.get.block` response.

    Coordinates come out **server-local**, exactly as in `secret_tasks()` and
    `player_bases()` — the numbers the game shows on screen.
    """
    for block in payload.get("serverPointArr") or ():
        area = block.get("maxAreaSize") or 1000
        server = block.get("serverId")
        for point in block.get("points") or ():
            tile = (point or {}).get("_protobuf") or {}
            if tile.get("f2") != MINE_TILE_TYPE:
                continue
            node = tile.get("f6") or {}
            family, level = split_mine_value(node.get("f1"))
            packed = tile.get("f1") or 0
            # The fourth family parks its occupier one field over (`f6.f7.f1`),
            # which is why the uid is read from both places rather than from
            # the one the ordinary three use.
            other = node.get("f7") if isinstance(node.get("f7"), dict) else {}
            yield Mine(
                point_id=packed or None,
                server_id=tile.get("f102") or tile.get("f103") or server,
                x=packed % area, y=packed // area,
                family=family, level=level,
                owner_uid=node.get("f8") or other.get("f1") or None,
                owner_server=node.get("f9"),
                alliance_id=node.get("f10"),
                activity_uuid=node.get("f3") or other.get("f2"),
            )


def filter_mines(items, resource=None, level=None, free_only=False) -> list:
    """Narrow a mine list. None/False means «any».

    `resource` is a set of family names (`{"gold"}`) and/or family numbers, so a
    caller can ask for the family the wire actually says as well as the one the
    screen shows.
    """
    out = []
    for mine in items:
        if resource:
            if mine.resource not in resource and mine.family not in resource:
                continue
        if level and mine.level not in level:
            continue
        if free_only and not mine.free:
            continue
        out.append(mine)
    return out


# `completeness` is exactly `1 - 0.25 * robTimes` on all 158 captured trucks
# (110 at 0/1.0, 46 at 1/0.75, 2 at 2/0.5), so four robberies empty one. Three
# and four were never observed, so the ceiling is read off the arithmetic
# rather than seen; if a truck ever shows robTimes 4 with completeness above 0,
# this constant is what to revisit.
MAX_TRUCK_ROBS = 4

# Marches pack their coordinates server-local the same way tiles do, but a
# march response carries no `maxAreaSize` to divide by the way a map block
# does. Every server in the captures is 1000 wide, which is what tiles report,
# so that is the divisor. A server of another width would skew truck positions
# and nothing else.
TRUCK_AREA_SIZE = 1000

# `cfgId` encodes tier and level in two schemes, and which one applies is read
# off the magnitude. Both were verified against the `level` field the server
# sends alongside: 156 of 156 trucks decode to exactly the level they claim,
# with no mismatch.
#
#   cfgId >= 1000   `TLLL` — tier * 1000 + level. Levels 31+ only.
#   200..299        `2LL`  — the sled, a family of its own; level = cfgId - 200
#   1..150          `(tier-1) * 30 + level`, a flat table capped at level 30
#
# The tiers are graded, and the grading is what the cargo confirms. Totalling
# `baseGoods.full` per (level, tier) comes out monotone in tier at every level
# that has more than one — e.g. at level 33: 7.1M, 8.9M, 10.7M, 13.3M for tiers
# 2..5, and 23.1M for the sled, which is roughly double the best graded truck.
# The two schemes agree with each other across the level-30/31 seam (tier 4:
# 8.04M then 8.36M; tier 5: 10.05M then 9.20M), so the tier digit means the
# same thing in both.
#
# The colour names below are the standard five-grade ramp and are an
# **inference, never checked by eye** — the same standing as the star in
# STAR_TASK_FAMILIES. What the evidence actually establishes is the *order*;
# which colour the client paints each rank is not on the wire. A caller that
# only trusts what was measured should filter on `tier`, not on the name. To
# settle it, run this scanner beside the map and compare a named truck with the
# one drawn on screen.
TRUCK_TIER_NAMES = {1: "white", 2: "green", 3: "blue", 4: "purple", 5: "gold"}
SLED = "sled"

# What `--type` accepts, over and above the names above. "yellow" is what the
# top grade gets called in the field; both reach tier 5.
TRUCK_TIER_ALIASES = {"yellow": 5, "orange": 5, "grey": 1, "gray": 1}

# The flat table's stride: five tiers of thirty levels each, 1..150.
_TRUCK_TABLE_STRIDE = 30
_TRUCK_TABLE_MAX = _TRUCK_TABLE_STRIDE * 5


def split_truck_cfg_id(cfg_id) -> tuple:
    """Return `(tier, level)` for a truck cfgId — see the note above.

    `tier` is 1..5 for a graded truck and the string `SLED` for a sled, which
    is a family rather than a rank. Raises ValueError on anything outside both
    schemes, so a caller can tell "a truck this decoder does not understand"
    from one it read as tier 0.
    """
    value = int(cfg_id)
    if value >= 1000:
        tier, level = divmod(value, 1000)
        if 1 <= tier <= 5 and 1 <= level <= 99:
            return tier, level
    elif 200 <= value < 300:
        return SLED, value - 200
    elif 1 <= value <= _TRUCK_TABLE_MAX:
        index = value - 1
        return index // _TRUCK_TABLE_STRIDE + 1, index % _TRUCK_TABLE_STRIDE + 1
    raise ValueError(f"not a truck cfgId: {cfg_id!r}")


def truck_type_set(text: str) -> set:
    """Parse `--type` — colour names, `sled`, or bare tier numbers.

    Returns a set of tiers (ints) and/or `SLED`, so it drops straight into
    `filter_trucks(types=...)`. Mixing forms is allowed: `--type gold,sled,2`.
    """
    by_name = {name: tier for tier, name in TRUCK_TIER_NAMES.items()}
    by_name.update(TRUCK_TIER_ALIASES)
    wanted = set()
    for part in text.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part == SLED:
            wanted.add(SLED)
        elif part in by_name:
            wanted.add(by_name[part])
        elif part.isdigit() and 1 <= int(part) <= 5:
            wanted.add(int(part))
        else:
            known = ", ".join(sorted(by_name) + [SLED])
            raise ValueError(f"{part!r} is not a truck type; expected one of "
                             f"{known}, or a tier number 1-5")
    if not wanted:
        raise ValueError("no truck type given")
    return wanted


def march_position(leg_from, leg_to, start_ms, end_ms, now_ms=None) -> tuple:
    """Where a march is RIGHT NOW, walked along the hop the server last described.

    **The server never sends a position.** It sends the hop's two endpoints and
    the two times it runs between, and the client draws the vehicle by walking
    one towards the other on the game's own clock — so a stored `(x, y)` is not
    «where it is», it is «where it was when that frame was decoded». Anything
    drawing a truck or a train has to walk the leg itself, which is why this is
    a function and not two copies of the same five lines.

    Outside the leg's window it clamps to the endpoints: before it starts the
    vehicle is still at `leg_from`, and after `end_ms` it is parked at `leg_to`
    until the next hop is pushed — which is what the client draws in the gap too.

    `now_ms` is for a caller that already has the game's clock (or a test);
    left out, the game clock is asked. **Never the PC's** — the two differ, and
    on a leg that runs a couple of minutes the difference is tiles.
    """
    x0, y0 = leg_from
    x1, y1 = leg_to
    if start_ms is None or end_ms is None or end_ms <= start_ms:
        return x1, y1
    now = game_clock.now_ms() if now_ms is None else now_ms
    share = min(1.0, max(0.0, (now - start_ms) / float(end_ms - start_ms)))
    return (int(round(x0 + (x1 - x0) * share)), int(round(y0 + (y1 - y0) * share)))


@dataclass(slots=True)
class Truck:
    uuid: int
    march_uuid: int
    server_id: int
    owner_uid: str | None
    owner_name: str | None
    alliance_id: str | None
    alliance_abbr: str | None
    country: str | None
    cfg_id: int
    tier: object          # 1..5, or SLED
    level: int
    rob_times: int
    robbed_by: tuple
    power: int | None
    squad: tuple          # (hero id, level, power) per escort slot
    cargo: int            # summed numeric `baseGoods.full`, the full haul
    leg_from: tuple       # (x, y) the current hop started at
    leg_to: tuple         # (x, y) it ends at
    leg_start_ms: int | None
    leg_end_ms: int | None
    arrive_at: int | None
    start_pos: tuple | None

    @property
    def tier_name(self) -> str:
        """`white`..`gold`, or `sled`. An inference — see TRUCK_TIER_NAMES."""
        if self.tier == SLED:
            return SLED
        return TRUCK_TIER_NAMES.get(self.tier, f"tier{self.tier}")

    @property
    def is_sled(self) -> bool:
        return self.tier == SLED

    @property
    def free_robs(self) -> int:
        return max(0, MAX_TRUCK_ROBS - self.rob_times)

    @property
    def position(self) -> tuple:
        """`(x, y)` right now, interpolated along the current leg.

        See :func:`march_position` — the one place the arithmetic lives, so a
        truck, a train and the panel's own tables all say the same tile.
        """
        return march_position(self.leg_from, self.leg_to,
                              self.leg_start_ms, self.leg_end_ms)

    @property
    def arrived(self) -> bool:
        """Its run is over, so it is off the map whatever else it still says.

        Trucks that have not been dispatched at all report `arriveTime` 0 —
        those are listed by `alliance.train.info` and the login payload, never
        by the march stream, and they are not on the map either.
        """
        if not self.arrive_at:
            return True
        return self.arrive_at <= game_clock.now_ms()

    @property
    def can_loot(self) -> bool:
        """Robbable right now: still running, and not yet robbed dry.

        This is the wire's answer, and it is narrower than the game's: whether
        *you* may rob this particular truck also depends on your own alliance
        (you cannot rob your own) and on your remaining daily attempts, neither
        of which is in this payload. Pass `exclude_alliance` to
        `filter_trucks()` for the first; the second is not on the wire at all.
        """
        return not self.arrived and self.free_robs > 0

    def as_dict(self) -> dict:
        x, y = self.position
        return {
            "uuid": self.uuid, "march_uuid": self.march_uuid,
            "server_id": self.server_id, "owner_uid": self.owner_uid,
            "owner_name": self.owner_name, "alliance_id": self.alliance_id,
            "alliance_abbr": self.alliance_abbr, "country": self.country,
            "cfg_id": self.cfg_id, "tier": self.tier,
            "tier_name": self.tier_name, "level": self.level,
            "x": x, "y": y,
            "leg_from": list(self.leg_from), "leg_to": list(self.leg_to),
            "leg_start_ms": self.leg_start_ms, "leg_end_ms": self.leg_end_ms,
            "arrive_at": self.arrive_at,
            "start_pos": list(self.start_pos) if self.start_pos else None,
            "rob_times": self.rob_times, "robbed_by": list(self.robbed_by),
            "free_robs": self.free_robs, "power": self.power,
            "squad": [list(hero) for hero in self.squad], "cargo": self.cargo,
            "can_loot": self.can_loot,
        }

    @classmethod
    def from_dict(cls, record: dict) -> "Truck":
        """Rebuild a truck from an as_dict() record — e.g. a checkpoint.

        Only stored fields are restored. `position` and `can_loot` are
        recomputed against the current clock when read, never taken from the
        record, so a checkpoint written minutes ago is re-evaluated: a truck
        keeps moving after it is written down.
        """
        def pair(value, fallback=(0, 0)):
            return tuple(value) if value else fallback

        return cls(
            uuid=record.get("uuid"), march_uuid=record.get("march_uuid"),
            server_id=record.get("server_id"),
            owner_uid=record.get("owner_uid"),
            owner_name=record.get("owner_name"),
            alliance_id=record.get("alliance_id"),
            alliance_abbr=record.get("alliance_abbr"),
            country=record.get("country"), cfg_id=record.get("cfg_id"),
            tier=record.get("tier"), level=record.get("level"),
            rob_times=record.get("rob_times") or 0,
            robbed_by=tuple(record.get("robbed_by") or ()),
            power=record.get("power"),
            squad=tuple(tuple(hero) for hero in record.get("squad") or ()),
            cargo=record.get("cargo") or 0,
            leg_from=pair(record.get("leg_from")),
            leg_to=pair(record.get("leg_to")),
            leg_start_ms=record.get("leg_start_ms"),
            leg_end_ms=record.get("leg_end_ms"),
            arrive_at=record.get("arrive_at"),
            start_pos=pair(record.get("start_pos"), None),
        )


def _unpack_march_pos(packed, area: int = TRUCK_AREA_SIZE):
    """`y * area + x` -> `(x, y)`, or None when the field is absent."""
    if packed is None:
        return None
    return int(packed) % area, int(packed) // area


def _truck_squad(hero_info) -> tuple:
    """`marchInfo.heroInfo` -> `((hero id, level, power), ...)` by slot.

    Keyed by slot number as a string ("1".."6"), so it is sorted numerically
    rather than left in dict order — the escort reads as a squad list.
    """
    if not isinstance(hero_info, dict):
        return ()
    def slot(item):
        key = item[0]
        return int(key) if str(key).isdigit() else 0
    return tuple(
        (hero.get("id"), hero.get("level"), hero.get("power"))
        for _key, hero in sorted(hero_info.items(), key=slot)
        if isinstance(hero, dict)
    )


def _truck_cargo(goods) -> int:
    """Total the numeric entries of a `baseGoods` bundle.

    Entries are `{"type": N, "value": ...}` where value is a number for the
    resource types and a `{"num", "id"}` item for everything else. Only the
    numbers are summed, so this is "how much resource is aboard" and not a
    count of the item rewards, which are not comparable to each other anyway.
    """
    if not isinstance(goods, dict):
        return 0
    total = 0
    for entry in goods.get("full") or ():
        value = entry.get("value") if isinstance(entry, dict) else None
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def _iter_marches(payload: dict):
    """Yield every march entry in one decoded response, whatever the wrapper.

    The three commands that carry trucks nest their marches differently and
    `push.world.march.new` does not nest at all — its payload *is* the march.
    Each is checked for independently rather than switched on the command
    name, so a fourth wrapper (or the same march arriving under a name this
    was never told about) still decodes.
    """
    if not isinstance(payload, dict):
        return
    if "_proto" in payload:
        yield payload
    for block in payload.get("serverMarchArr") or ():
        if isinstance(block, dict):
            yield from block.get("marchInfos") or ()
    yield from payload.get("marchInfos") or ()


def trucks(payload: dict):
    """Yield every player truck in one decoded march response.

    Coordinates come out **server-local**, paired with `server_id`, exactly as
    in `secret_tasks()` and `player_bases()` — the numbers the game shows on
    screen. No world-space lift happens here; see `secret_tasks()` for why
    that would be wrong.

    Alliance trains (`type` 2) are skipped: they belong to no player, cannot be
    robbed the way a truck can, and carry a `carriageList` where a truck has a
    squad, so a caller would have to special-case every field.
    """
    for march in _iter_marches(payload):
        if not isinstance(march, dict):
            continue
        train = march.get("train")
        if not isinstance(train, dict) or train.get("type") != 1:
            continue
        info = (march.get("_proto") or {}).get("_protobuf") or {}
        march_info = train.get("marchInfo") or {}
        try:
            tier, level = split_truck_cfg_id(train["cfgId"])
        except (KeyError, ValueError, TypeError):
            continue  # shaped like a truck, but no usable cfgId
        leg_from = _unpack_march_pos(info.get("f9")) or (0, 0)
        leg_to = _unpack_march_pos(info.get("f10")) or leg_from
        robbed_by = tuple(
            str(entry.get("uid")) for entry in march_info.get("plunderRecord") or ()
            if isinstance(entry, dict) and entry.get("uid")
        )
        yield Truck(
            uuid=train.get("uuid"),
            march_uuid=train.get("marchUid") or march.get("uuid"),
            server_id=train.get("serverId") or info.get("f26"),
            owner_uid=train.get("uid") or march.get("ownerUid"),
            owner_name=train.get("name"),
            alliance_id=train.get("allianceId"),
            alliance_abbr=train.get("abbr"),
            country=train.get("country"),
            cfg_id=int(train["cfgId"]),
            tier=tier,
            level=level,
            rob_times=march_info.get("robTimes") or 0,
            robbed_by=robbed_by,
            power=march_info.get("power"),
            squad=_truck_squad(march_info.get("heroInfo")),
            cargo=_truck_cargo(train.get("baseGoods")),
            leg_from=leg_from,
            leg_to=leg_to,
            leg_start_ms=info.get("f13"),
            leg_end_ms=info.get("f14"),
            arrive_at=train.get("arriveTime"),
            start_pos=_unpack_march_pos(train.get("startPos")),
        )


def filter_trucks(items, types=None, level=None, can_loot=False,
                  min_free_robs=None, exclude_alliance=None) -> list:
    """Narrow a truck list. None/False means "any".

    `types` is a set of tiers (1..5) and/or `SLED`, as `truck_type_set()`
    returns; a truck passes if it matches any, because tier is one dimension
    and listing several reads as "or". `level` works the same way and takes
    either one level or an iterable of them. Criteria from *different*
    dimensions are ANDed, so `--type gold,sled --level 35 --can-loot` reads as
    (gold OR sled) AND level 35 AND robbable.

    `can_loot` keeps only trucks still running with a robbery left in them.
    `exclude_alliance` drops your own alliance's trucks, which you cannot rob —
    pass your allianceId, not the tag.
    """
    levels = None
    if level is not None:
        levels = {level} if isinstance(level, int) else set(level)

    out = []
    for truck in items:
        if types is not None and truck.tier not in types:
            continue
        if levels is not None and truck.level not in levels:
            continue
        if can_loot and not truck.can_loot:
            continue
        if min_free_robs is not None and truck.free_robs < min_free_robs:
            continue
        if exclude_alliance is not None and truck.alliance_id == exclude_alliance:
            continue
        out.append(truck)
    # Fattest haul first, then least robbed — the order you would raid in.
    out.sort(key=lambda t: (-t.cargo, t.rob_times))
    return out


# --------------------------------------------------------------------------
# Alliance trains (`train.type` = 2)
# --------------------------------------------------------------------------
#
# The OTHER thing that rides the truck shape, and `trucks()` deliberately skips
# it: an alliance train belongs to no player and carries a `carriageList` of
# seats where a truck has an escort squad. It is rare — 3 of the 1174 trains in
# every recording on disk — because it runs as an alliance event rather than
# all day, which is exactly why it wants a list of its own: one row a week is
# a row nobody would find mixed into a hundred trucks.
#
# What one carries, over and above the march geometry the two share:
#
#     train.alliancename / .allianceId / .icon   whose train it is
#     train.uid / .name                          the member who set it running
#     train.seasonCfgId                          the season's train, not a tier
#     train.completeness                         1.0 → nothing taken off it yet
#     train.marchInfo.giftLv                     the reward tier it is at
#     train.marchInfo.carriageList[]             the seats: `seatNum`,
#         `passengerList[]` (uid, name, level, abbr), `trainGoods.full[]` and
#         its `quality`, and `plunder[]` — who has robbed that carriage
TRAIN_TYPE = 2


@dataclass(slots=True)
class Train:
    """One alliance train, as the march stream describes it."""

    uuid: int | None
    march_uuid: int | None
    server_id: int | None
    owner_uid: str | None
    owner_name: str | None
    alliance_id: str | None
    alliance_abbr: str | None
    alliance_name: str | None
    cfg_id: int | None
    #: How full it still is — the game's own `completeness`, 1.0 down to 0.
    completeness: float | None
    gift_level: int | None
    rob_times: int
    seats: int
    passengers: int
    leg_from: tuple
    leg_to: tuple
    leg_start_ms: int | None
    leg_end_ms: int | None
    arrive_at: int | None

    @property
    def position(self) -> tuple:
        """Where it is right now, interpolated along the leg it is on.

        The very same :func:`march_position` a truck walks: the server describes
        one hop at a time, so the tile it is standing on is never a field.
        """
        return march_position(self.leg_from, self.leg_to,
                              self.leg_start_ms, self.leg_end_ms)

    def as_dict(self) -> dict:
        x, y = self.position
        return {
            "uuid": self.uuid, "march_uuid": self.march_uuid,
            "server_id": self.server_id, "owner_uid": self.owner_uid,
            "owner_name": self.owner_name, "alliance_id": self.alliance_id,
            "alliance_abbr": self.alliance_abbr,
            "alliance_name": self.alliance_name, "cfg_id": self.cfg_id,
            "completeness": self.completeness, "gift_level": self.gift_level,
            "rob_times": self.rob_times, "seats": self.seats,
            "passengers": self.passengers, "x": x, "y": y,
            "leg_from": list(self.leg_from), "leg_to": list(self.leg_to),
            "leg_start_ms": self.leg_start_ms, "leg_end_ms": self.leg_end_ms,
            "arrive_at": self.arrive_at,
        }


def trains(payload: dict):
    """Yield every ALLIANCE train in one decoded march response.

    The mirror of `trucks()`, which skips exactly what this keeps. Coordinates
    come out server-local, as everywhere else here.
    """
    for march in _iter_marches(payload):
        if not isinstance(march, dict):
            continue
        train = march.get("train")
        if not isinstance(train, dict) or train.get("type") != TRAIN_TYPE:
            continue
        info = (march.get("_proto") or {}).get("_protobuf") or {}
        march_info = train.get("marchInfo") or {}
        carriages = [c for c in march_info.get("carriageList") or ()
                     if isinstance(c, dict)]
        leg_from = _unpack_march_pos(info.get("f9")) or (0, 0)
        leg_to = _unpack_march_pos(info.get("f10")) or leg_from
        yield Train(
            uuid=train.get("uuid"),
            march_uuid=train.get("marchUid") or march.get("uuid"),
            server_id=train.get("serverId") or info.get("f26"),
            owner_uid=train.get("uid") or march.get("ownerUid"),
            owner_name=info.get("f1") or train.get("name"),
            alliance_id=train.get("allianceId"),
            alliance_abbr=info.get("f34"),
            alliance_name=train.get("alliancename"),
            cfg_id=train.get("seasonCfgId") or train.get("cfgId"),
            completeness=train.get("completeness"),
            gift_level=march_info.get("giftLv"),
            rob_times=march_info.get("robTimes") or 0,
            seats=len(carriages),
            passengers=sum(len(c.get("passengerList") or ()) for c in carriages),
            leg_from=leg_from,
            leg_to=leg_to,
            leg_start_ms=info.get("f13"),
            leg_end_ms=info.get("f14"),
            arrive_at=train.get("arriveTime"),
        )


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
    # An alliance board scores in `fightpower`, and has no `power` at all.
    "fightpower", "alliancepoint",
)


@dataclass(slots=True)
class Leaderboard:
    """Where the entries live in one ranking reply, and what they mean.

    `position` and `score` name the fields on an entry; either may be None
    when the board carries no such column.

    `ordered` says the server sends the list already in ranking order, so the
    position can be read off the index. That is only ever set for a board
    where the capture *shows* it sorted — `al.rank` is the standing proof that
    it cannot be assumed.

    `variant` names a payload key that multiplexes several boards onto one
    command: `rank.get` answers with alliances at `type = 2` and would answer
    something else at another type. The board id then carries it
    (`rank.get/type=2`) so two different rankings never share a key.

    `entity` is what a row *is* — a player or an alliance. Both kinds carry a
    `uid`, but an alliance's is an alliance id, and joining the two sets on
    uid would be nonsense.
    """
    command: str
    list_key: str
    label: str
    position: str | None = None
    score: str | None = None
    score_label: str | None = None
    server: str = "serverId"
    alliance: str | None = None
    name: str = "name"
    entity: str = "player"
    ordered: bool = False
    variant: str | None = None


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
        # The alliance ranking screen. Rows are alliances, not players: `uid`
        # is an alliance id and the name is under `alliancename`, which is
        # exactly why the shape test used to walk straight past this board —
        # it demanded a `name`. `leader`/`leaderUid` name the R5, who *is* a
        # player, but the row is still the alliance's.
        #
        # There is no rank field at all. The 44 entries came back strictly
        # sorted by `fightpower` descending, so the order is the ranking and
        # `ordered` says so — the opposite finding to `al.rank`, and the
        # reason that flag exists per board rather than as a global rule.
        #
        # `type = 2` is the alliance board. The command is multiplexed, so the
        # type rides in the board id.
        Leaderboard(
            command="rank.get",
            list_key="allianceRanking",
            label="alliance ranking",
            position=None,
            ordered=True,
            score="fightpower",
            score_label="fightpower",
            name="alliancename",
            entity="alliance",
            alliance="abbr",
            server="srcServer",
            variant="type",
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
    # The alliance *recruitment browser*, not a ranking — the client opens it
    # from the same part of the UI, and it carries 39 alliances with a name
    # and a `fightpower`, so it passes the shape test. Its list came back in
    # no fightpower order at all (24.4G, 15.0G, 9.5G, 3.1G, 197M, then back
    # up), which is what tells the two apart.
    "al.search",
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
    # What this row is — "player" or "alliance". Both carry a uid, but an
    # alliance's uid is an alliance id, so the two must not be joined.
    entity: str = "player"
    # How `position` was arrived at: "field" if the board numbered the row
    # itself, "order" if the server sent the list already sorted and the index
    # was used, None if no position could be had honestly.
    position_source: str | None = None
    # True when the board was found by shape rather than described in
    # LEADERBOARDS, so a reader can tell a column this file vouches for from
    # one a heuristic picked.
    discovered: bool = False

    def as_dict(self) -> dict:
        return {
            "leaderboard": self.board,
            "leaderboard_label": self.board_label,
            "entity": self.entity,
            "uid": self.uid,
            "name": self.name,
            "server_id": self.server_id,
            "position": self.position,
            "position_source": self.position_source,
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


def as_number(value):
    """`value` as an int, whether the server sent it as one or as a string.

    The big counters cross the wire inconsistently — `rank.get` sent
    `fightpower` as an int and `armyKill` as a string in the *same* entry, and
    `al.search` sent `fightpower` as a string. They are past 2^32, so the
    likeliest reason is a server-side JSON encoder widening the ones that
    would lose precision in a double. Returns None for anything that is not a
    number, which includes bools: `True` is an int in Python and would
    otherwise be reported as a score of 1.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _entry_score(entry: dict, preferred: str | None):
    """The score column of one entry, as `(field, value)`.

    `preferred` wins when the described field is present; otherwise the first
    of LEADERBOARD_SCORE_FIELDS that the entry carries is taken, which is what
    lets an undescribed board still report a number.
    """
    if preferred:
        value = as_number(entry.get(preferred))
        if value is not None:
            return preferred, value
    for field in LEADERBOARD_SCORE_FIELDS:
        value = as_number(entry.get(field))
        if value is not None:
            return field, value
    return None, None


def _read_board(command, label, entries, board, discovered):
    """Turn one reply's list into LeaderboardEntry objects."""
    if not entries:
        return
    positions = None
    source = None
    if board is not None and board.position:
        candidates = [e.get(board.position) for e in entries]
        if is_position_sequence(candidates):
            positions = candidates
            source = "field"
    elif board is not None and board.ordered:
        # The server sorted it, so the index is the placement. Recorded as
        # position_source="order" rather than passed off as a number the
        # board stated, because those are different degrees of certainty.
        positions = list(range(1, len(entries) + 1))
        source = "order"
    elif discovered:
        # An undescribed board gets the same treatment, on whichever of the
        # usual names it happens to use — believed only if it checks out.
        for field in ("rank", "index", "pos", "position"):
            candidates = [e.get(field) for e in entries]
            if is_position_sequence(candidates):
                positions = candidates
                source = "field"
                break

    server_key = board.server if board is not None else "serverId"
    alliance_key = board.alliance if board is not None else "allianceName"
    name_key = board.name if board is not None else "name"
    entity = board.entity if board is not None else _entry_entity(entries[0])
    for index, entry in enumerate(entries):
        uid = entry.get("uid")
        if uid is None:
            continue
        field, score = _entry_score(entry, board.score if board else None)
        yield LeaderboardEntry(
            board=command,
            board_label=label,
            uid=str(uid),
            name=entry.get(name_key) or entry.get("name")
                 or entry.get("alliancename"),
            server_id=(entry.get(server_key) or entry.get("serverId")
                       or entry.get("server") or entry.get("srcServer")
                       or entry.get("curServerId")),
            position=positions[index] if positions is not None else None,
            position_source=source if positions is not None else None,
            list_index=index,
            score=score,
            score_field=field,
            power=as_number(entry.get("power")),
            alliance=(entry.get(alliance_key) if alliance_key else None)
                     or entry.get("allianceName") or entry.get("abbr"),
            entity=entity,
            discovered=discovered,
        )


def _entry_entity(entry: dict) -> str:
    """Whether an undescribed board's rows are players or alliances.

    An alliance row names itself `alliancename` and has no player name of its
    own; a player row has `name`. Only consulted for boards found by shape —
    a described one states its entity outright.
    """
    if entry.get("name"):
        return "player"
    return "alliance" if entry.get("alliancename") else "player"


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
            yield from _read_board(board_id(board, payload), board.label,
                                   rows, board, False)
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


def board_id(board: Leaderboard, payload: dict) -> str:
    """The board's key, carrying its variant where the command has one.

    `rank.get` is the reason: one command, several rankings, told apart by
    `type` in both the request and the reply. Without the variant in the key
    two different boards would dedup into each other the moment a second type
    was opened.
    """
    if not board.variant:
        return board.command
    value = payload.get(board.variant)
    if value is None:
        return board.command
    return f"{board.command}/{board.variant}={value}"


def _looks_like_board(entry: dict) -> bool:
    """Whether one entry reads as a row in a ranking.

    A row needs a uid, something to call it by, and a number. The name is
    accepted under `alliancename` as well as `name`, because an alliance board
    has no player name on the row — that gap is what made `rank.get` invisible
    to this test until the alliance ranking was captured.
    """
    if entry.get("uid") is None:
        return False
    if not (entry.get("name") or entry.get("alliancename")):
        return False
    if isinstance(entry.get("rank"), int):
        return True
    return any(as_number(entry.get(f)) is not None
               for f in LEADERBOARD_SCORE_FIELDS)


def filter_players(players, level=None, alliance=None, name=None,
                   uid=None) -> list:
    """Narrow a base list. None means "any".

    `level` takes one HQ level or any iterable of them, matching the "or"
    reading `filter_tasks` gives it. `alliance` matches the abbreviation
    case-insensitively — the tag is drawn uppercase in game but nothing on the
    wire guarantees the case, and an exact-case filter that silently matches
    nothing is worse than a loose one.

    `name` is a **substring** of the player's name, case-insensitively: names
    carry spacing, decoration and mixed scripts nobody retypes exactly, so an
    equality test would be a filter that never fires. A base whose tile carried
    no name cannot match one.

    `uid` is the opposite — an **exact** id, one or any iterable of them, and
    compared as text because that is how a uid is kept everywhere else here
    (`PlayerBase.uid` is a str). Every filter is an "and": `--name vp --level
    30` keeps HQ-30 bases whose name contains "vp".
    """
    levels = None
    if level is not None:
        levels = {level} if isinstance(level, int) else set(level)
    tag = alliance.strip().casefold() if alliance else None
    needle = name.strip().casefold() if name else None
    uids = None
    if uid is not None:
        one = (uid,) if isinstance(uid, (str, int)) else uid
        uids = {str(u).strip() for u in one}

    out = []
    for p in players:
        if levels is not None and p.level not in levels:
            continue
        if tag is not None and (p.alliance_abbr or "").casefold() != tag:
            continue
        if needle is not None and needle not in (p.name or "").casefold():
            continue
        if uids is not None and p.uid not in uids:
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
