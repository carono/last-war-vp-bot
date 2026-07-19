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
# Level 99 is excluded from the concern above: those are internal
# one-per-player tasks that the UI does not draw, so they cannot be the
# starred markers a player sees.
#
# This constant is the single place the rule lives. To re-test it, run
# `live_tshark.py --tasks --families` and compare the tally with the stars
# actually drawn on that patch of map.
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
    def starred(self) -> bool:
        """Drawn with a star on the map — see STAR_TASK_FAMILIES."""
        return self.family in STAR_TASK_FAMILIES

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
            "starred": self.starred,
        }


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
                 min_free_slots=None, exclude_alliance=None) -> list:
    """Narrow a task list. Criteria are ANDed; None/False means "any".

    `can_loot` keeps only tasks that are raidable right now — dispatch
    completed, not expired, and a slot free (see `SecretTask.can_loot`).
    `min_free_slots` is a stricter *slot* count (3 = untouched) and does not by
    itself imply raidable. `exclude_alliance` drops your own alliance's tasks,
    which you cannot loot from.
    """
    out = []
    for t in tasks:
        if level is not None and t.level != level:
            continue
        if star_only and not t.starred:
            continue
        if can_loot and not t.can_loot:
            continue
        if min_free_slots is not None and t.free_slots < min_free_slots:
            continue
        if exclude_alliance is not None and t.alliance_id == exclude_alliance:
            continue
        out.append(t)
    # Least-looted first, then highest level — the order you would raid in.
    out.sort(key=lambda t: (t.loot_count, -t.level))
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
