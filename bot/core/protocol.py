"""The Last War wire protocol — the single source of truth for the bot.

The full, battle-tested decoder (TLV tree, client XOR mask, zstd/zlib frames,
embedded protobuf and every domain parser) lives in ``tools/lastwar_proto.py``.
Re-implementing any of it here would be duplication, so this module is a thin,
stable facade: it re-exports the transport primitives under clean names and adds
two small conveniences (``decode_frames`` and the ``Envelope`` view) that the
rest of ``bot`` builds on. If the protocol implementation ever moves, this file
is the one seam to update.

Nothing here parses the *meaning* of a message — that is the stream reader's job.
This layer only turns bytes on the wire into decoded envelopes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

# The transport lives in tools/ (put on sys.path by bot/__init__.py). Importing
# the whole module keeps a single implementation; we alias the pieces we expose.
import lastwar_proto as _p

# --- direction / framing constants -------------------------------------------
SERVER_MAGICS = _p.SERVER_MAGICS
CLIENT_MAGICS = _p.CLIENT_MAGICS
FLAG_COMPRESSED = _p.FLAG_COMPRESSED
FLAG_ZSTD = _p.FLAG_ZSTD
FLAG_LEN32 = _p.FLAG_LEN32

# --- primitives (re-exported verbatim, one implementation) -------------------
Reader = _p.Reader
Truncated = _p.Truncated
BadTag = _p.BadTag
read_value = _p.read_value
unmask = _p.unmask
decompress_zstd = _p.decompress_zstd
decompress_zlib = _p.decompress_zlib
iter_frames = _p.iter_frames
is_magic = _p.is_magic
classify = _p.classify
parse_protobuf = _p.parse_protobuf

# --- envelope helpers --------------------------------------------------------
envelope_command = _p.envelope_command
envelope_payload = _p.envelope_payload

# Direction literals, named once so callers stop passing bare strings around.
DOWN = "down"  # server -> client
UP = "up"      # client -> server

__all__ = [
    "SERVER_MAGICS", "CLIENT_MAGICS",
    "FLAG_COMPRESSED", "FLAG_ZSTD", "FLAG_LEN32",
    "Reader", "Truncated", "BadTag", "read_value",
    "unmask", "decompress_zstd", "decompress_zlib",
    "iter_frames", "is_magic", "classify", "parse_protobuf",
    "envelope_command", "envelope_payload",
    "DOWN", "UP", "Envelope", "decode_frames",
]


@dataclass(slots=True)
class Envelope:
    """A decoded frame with its command name and payload already extracted.

    ``raw`` is the full envelope dict as it came off the wire; ``command`` and
    ``payload`` are the two fields every caller actually wants, computed once via
    the same helpers the tools use.
    """

    direction: str          # DOWN (server) or UP (client)
    command: str | None     # e.g. "world.get.block", or None for keepalives
    payload: object         # inner "p" map, or the raw envelope when absent
    raw: dict

    @classmethod
    def from_raw(cls, direction: str, raw: dict) -> "Envelope":
        return cls(
            direction=direction,
            command=envelope_command(raw),
            payload=envelope_payload(raw),
            raw=raw,
        )


def decode_frames(data: bytes, direction: str) -> Iterator[tuple[Envelope, int, int]]:
    """Decode a (partial) half-stream into ``(Envelope, start, end)`` tuples.

    Thin wrapper over :func:`iter_frames`: same "stop at the first partial frame"
    contract, but each yielded envelope is already wrapped so callers get the
    command/payload without repeating the extraction. ``start``/``end`` are byte
    offsets into ``data`` so a caller can track how much of its buffer was
    consumed and keep the tail for the next chunk.
    """
    for raw, start, end in iter_frames(data, direction):
        if isinstance(raw, dict):
            yield Envelope.from_raw(direction, raw), start, end
