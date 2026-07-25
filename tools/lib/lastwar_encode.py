"""Client-frame encoder — the mirror of the decoder in `lastwar_proto.py`.

The decoder turns wire bytes into Python values. This turns Python values back
into wire bytes: TLV writer, XOR mask, zlib, and the 5-byte client header.

Everything here is derived from the decoder, so the two cannot drift: the
`--verify` mode below re-encodes every client frame of a saved capture and
compares byte for byte. See `docs/research/protocol.md` §2-4 for the format.

    python3 tools/lastwar_encode.py --verify capture.pcapng

**This module only builds bytes; it does not open a socket.** Sending frames to
a live server is active protocol work, which the project deliberately did not
take on (task #366, `protocol.md` §10). Read that before wiring this to a
socket.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, "tools/lib")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lastwar_proto import (  # noqa: E402
    CLIENT_MAGIC,
    CLIENT_MAGICS,
    FLAG_COMPRESSED,
    FLAG_LEN32,
    T_BLOB,
    T_BOOL,
    T_DOUBLE,
    T_FLOAT,
    T_INT8,
    T_INT16,
    T_INT32,
    T_INT32_ARRAY,
    T_INT64,
    T_INT64_ARRAY,
    T_LIST,
    T_MAP,
    T_STRING,
    T_STRING_ARRAY,
    Reader,
    Truncated,
    decompress_zlib,
    read_capture,
    unmask,
)

# The mask is its own inverse — XOR with the same two key bytes either way.
mask = unmask


# --------------------------------------------------------------------------
# Typed tree — what a byte-exact round-trip needs
# --------------------------------------------------------------------------
#
# `read_value()` collapses four integer widths onto Python `int` and decodes
# strings with errors="replace", so a decoded tree cannot be re-encoded to the
# same bytes. `read_typed()` below keeps the tag and the raw string bytes, which
# is what makes `--verify` a real test of the writer rather than of a heuristic.


class Typed(NamedTuple):
    tag: int
    value: Any


def read_typed(r: Reader) -> Typed:
    """Decode one value, preserving its tag and undecoded string bytes."""
    tag = r.u8()
    if tag == T_BOOL:
        return Typed(tag, bool(r.u8()))
    if tag == T_INT8:
        return Typed(tag, r.u8())
    if tag == T_INT16:
        return Typed(tag, int.from_bytes(r.take(2), "big", signed=True))
    if tag == T_INT32:
        return Typed(tag, r.i32())
    if tag == T_INT64:
        return Typed(tag, r.i64())
    if tag == T_FLOAT:
        return Typed(tag, struct.unpack(">f", r.take(4))[0])
    if tag == T_DOUBLE:
        return Typed(tag, struct.unpack(">d", r.take(8))[0])
    if tag == T_STRING:
        return Typed(tag, r.take(r.u16()))
    if tag == T_BLOB:
        return Typed(tag, r.take(r.u32()))
    if tag == T_INT32_ARRAY:
        return Typed(tag, [r.i32() for _ in range(r.u16())])
    if tag == T_INT64_ARRAY:
        return Typed(tag, [r.i64() for _ in range(r.u16())])
    if tag == T_STRING_ARRAY:
        return Typed(tag, [r.take(r.u16()) for _ in range(r.u16())])
    if tag == T_LIST:
        return Typed(tag, [read_typed(r) for _ in range(r.u16())])
    if tag == T_MAP:
        out = []
        for _ in range(r.u16()):
            out.append((r.take(r.u16()), read_typed(r)))
        return Typed(tag, out)
    raise ValueError(f"unknown TLV tag 0x{tag:02x} at offset {r.pos - 1}")


# --------------------------------------------------------------------------
# TLV writer
# --------------------------------------------------------------------------


def _u16(n: int) -> bytes:
    if not 0 <= n <= 0xFFFF:
        raise ValueError(f"uint16 out of range: {n}")
    return n.to_bytes(2, "big")


def _utf8(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode("utf-8")


def write_typed(node: Typed) -> bytes:
    """Serialise a `Typed` tree back to TLV bytes."""
    tag, value = node
    if tag == T_BOOL:
        return bytes([tag, 1 if value else 0])
    if tag == T_INT8:
        return bytes([tag, value & 0xFF])
    if tag == T_INT16:
        return bytes([tag]) + int(value).to_bytes(2, "big", signed=True)
    if tag == T_INT32:
        return bytes([tag]) + int(value).to_bytes(4, "big", signed=True)
    if tag == T_INT64:
        return bytes([tag]) + int(value).to_bytes(8, "big", signed=True)
    if tag == T_FLOAT:
        return bytes([tag]) + struct.pack(">f", value)
    if tag == T_DOUBLE:
        return bytes([tag]) + struct.pack(">d", value)
    if tag == T_STRING:
        raw = _utf8(value)
        return bytes([tag]) + _u16(len(raw)) + raw
    if tag == T_BLOB:
        raw = value if isinstance(value, bytes) else bytes.fromhex(value)
        return bytes([tag]) + len(raw).to_bytes(4, "big") + raw
    if tag == T_INT32_ARRAY:
        return bytes([tag]) + _u16(len(value)) + b"".join(
            int(v).to_bytes(4, "big", signed=True) for v in value
        )
    if tag == T_INT64_ARRAY:
        return bytes([tag]) + _u16(len(value)) + b"".join(
            int(v).to_bytes(8, "big", signed=True) for v in value
        )
    if tag == T_STRING_ARRAY:
        items = [_utf8(v) for v in value]
        return bytes([tag]) + _u16(len(items)) + b"".join(
            _u16(len(raw)) + raw for raw in items
        )
    if tag == T_LIST:
        return bytes([tag]) + _u16(len(value)) + b"".join(write_typed(v) for v in value)
    if tag == T_MAP:
        pairs = value.items() if isinstance(value, dict) else value
        pairs = list(pairs)
        out = bytes([tag]) + _u16(len(pairs))
        for key, val in pairs:
            raw = _utf8(key)
            out += _u16(len(raw)) + raw + write_typed(val)
        return out
    raise ValueError(f"cannot write TLV tag 0x{tag:02x}")


def infer(value) -> Typed:
    """Tag a plain Python value for the writer.

    Only used when *authoring* a request; decoding a captured one goes through
    `read_typed()`, which knows the real tags. Integer width is the narrowest
    that fits, matching how `read_value()` reads each tag back — note `int8` is
    read **unsigned** while the wider widths are signed, so 0..255 stays int8
    and -1 has to widen to int16.
    """
    if isinstance(value, Typed):
        return value
    if isinstance(value, bool):
        return Typed(T_BOOL, value)
    if isinstance(value, int):
        if 0 <= value <= 0xFF:
            return Typed(T_INT8, value)
        if -(1 << 15) <= value < (1 << 15):
            return Typed(T_INT16, value)
        if -(1 << 31) <= value < (1 << 31):
            return Typed(T_INT32, value)
        if -(1 << 63) <= value < (1 << 63):
            return Typed(T_INT64, value)
        raise ValueError(f"integer too wide for the protocol: {value}")
    if isinstance(value, float):
        return Typed(T_DOUBLE, value)
    if isinstance(value, str):
        return Typed(T_STRING, value.encode("utf-8"))
    if isinstance(value, bytes):
        return Typed(T_BLOB, value)
    if isinstance(value, (list, tuple)):
        return Typed(T_LIST, [infer(v) for v in value])
    if isinstance(value, dict):
        return Typed(T_MAP, [(_utf8(k), infer(v)) for k, v in value.items()])
    raise TypeError(f"no TLV tag for {type(value).__name__}")


def write(value) -> bytes:
    """Serialise a plain Python value (tags inferred) to TLV bytes."""
    return write_typed(infer(value))


# --------------------------------------------------------------------------
# Client framing
# --------------------------------------------------------------------------


def build_client_frame(body: bytes, server_id: int, k1: int, k2: int,
                       compress: bool = False) -> bytes:
    """Wrap a TLV body in the 5-byte client header.

        c4  <uint16 serverId>  K2  K1   <masked body>

    Order is deflate-then-mask, because the decoder unmasks before inflating.
    (`protocol.md` §2 words this the other way round — the decoder is what the
    round-trip test agrees with.)

    Client headers carry no length: the TLV tree, or the zlib stream's own end,
    delimits the frame.
    """
    flags = CLIENT_MAGIC | (FLAG_COMPRESSED if compress else 0)
    payload = zlib.compress(body) if compress else body
    header = bytes([flags]) + _u16(server_id) + bytes([k2 & 0xFF, k1 & 0xFF])
    return header + mask(payload, k1, k2)


def build_request(command: str, params: dict, server_id: int, k1: int, k2: int,
                  request_id: int = -1, channel: int = 1, opcode: int = 13,
                  compress: bool = False) -> bytes:
    """Build a complete client RPC frame for `command`.

    The envelope shape is `{"c": channel, "a": opcode, "p": {"c": command,
    "r": request_id, "p": params}}` — see `protocol.md` §4. `request_id` is -1
    when the caller does not correlate the reply.
    """
    envelope = {"c": channel, "a": opcode,
                "p": {"c": command, "r": request_id, "p": params}}
    return build_client_frame(write(envelope), server_id, k1, k2, compress)


# --------------------------------------------------------------------------
# Round-trip verification against a saved capture
# --------------------------------------------------------------------------


def _iter_client_frames(stream: bytes):
    """Yield (start, end, header, tlv_body, compressed) per client frame.

    A narrower walker than `iter_frames()`: it keeps the raw bytes of each
    frame, which is what the comparison needs.
    """
    pos = 0
    while pos + 5 <= len(stream):
        flags = stream[pos]
        if flags not in CLIENT_MAGICS or flags & FLAG_LEN32:
            pos += 1
            continue
        k2, k1 = stream[pos + 3], stream[pos + 4]
        body = unmask(stream[pos + 5:], k1, k2)
        compressed = bool(flags & FLAG_COMPRESSED)
        try:
            if compressed:
                tlv, consumed = decompress_zlib(body)
                end = pos + 5 + consumed
            else:
                r = Reader(body)
                read_typed(r)
                tlv, end = body[: r.pos], pos + 5 + r.pos
        except (Truncated, ValueError, zlib.error, IndexError):
            pos += 1
            continue
        yield pos, end, stream[pos : pos + 5], tlv, compressed
        pos = end


def verify(pcap: str) -> int:
    """Re-encode every client frame of a capture and compare byte for byte."""
    flows, _ = read_capture(pcap)
    total = ok = 0
    failures: list[str] = []

    for endpoint, flow in flows.items():
        stream = flow["up"]
        if not stream or stream[0] not in CLIENT_MAGICS:
            continue
        for start, end, header, tlv, compressed in _iter_client_frames(stream):
            total += 1
            server_id = int.from_bytes(header[1:3], "big")
            k2, k1 = header[3], header[4]

            rebuilt_tlv = write_typed(read_typed(Reader(tlv)))
            if rebuilt_tlv != tlv:
                failures.append(f"{endpoint} @{start}: TLV body differs")
                continue

            rebuilt = build_client_frame(rebuilt_tlv, server_id, k1, k2, compressed)
            if compressed:
                # zlib output depends on the compressor, so a compressed frame
                # cannot be diffed byte for byte. Decode the rebuilt frame
                # instead: same header, same plaintext body.
                round_tripped = list(_iter_client_frames(rebuilt))
                if len(round_tripped) != 1:
                    failures.append(f"{endpoint} @{start}: rebuilt frame does not re-parse")
                    continue
                _, _, new_header, new_tlv, _ = round_tripped[0]
                if (new_header, new_tlv) != (header, tlv):
                    failures.append(f"{endpoint} @{start}: compressed frame differs")
                    continue
            elif rebuilt != stream[start:end]:
                failures.append(f"{endpoint} @{start}: frame bytes differ")
                continue
            ok += 1

    print(f"client frames: {total}   byte-exact: {ok}   failed: {len(failures)}")
    for line in failures[:20]:
        print(f"  FAIL {line}")
    if len(failures) > 20:
        print(f"  … and {len(failures) - 20} more")
    return 0 if total and not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", metavar="PCAP",
                    help="re-encode every client frame of a capture and diff it")
    args = ap.parse_args()
    if not args.verify:
        ap.print_help()
        return 2
    return verify(args.verify)


if __name__ == "__main__":
    raise SystemExit(main())
