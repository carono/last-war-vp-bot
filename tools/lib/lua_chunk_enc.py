r"""The wrapper a Lua chunk must wear before this client's VM will parse it.

Since the client update of 2026-08-19 the game's Lua loader decrypts every buffer
before it parses it, so a chunk of plain source — even one that is nothing but a
comment — comes back as ``xLua exception : syntax error``. It is not a rejection of
our text; it is our text decrypted into noise. The break, the measurements that
found it and the checklist it produced are
`docs/research/client-update-encrypted-lua.md`.

What the loader wants, read out of `xlua.dll` itself:

    LENC <ChaCha8 keystream XOR> ( raw source | zlib stream )

* ``LENC`` — four bytes, and they are MANDATORY. A buffer without them makes the
  loader return failure before a single character is lexed, which is the whole of the
  outage.
* the body is XORed with a **ChaCha8** keystream — four double rounds, and **no final
  feed-forward addition** of the starting state, which is what makes it not ChaCha20
  and not any stock ChaCha. Key 32 bytes, nonce 12, block counter starts at 0.
* what comes out is inflated when it starts with a zlib header (``78 DA``) and taken
  as source otherwise. The game ships bytecode compressed that way; we send source.

**Nothing here is written down as a constant.** The key and the nonce belong to a
BUILD, not to this repository — the next patch may roll them, and a pinned copy would
fail exactly the way the port did (`docs/research/client-update-encrypted-lua.md` §3).
They are read out of the installed `xlua.dll` every time this module is first used, by
the shape of the code that assembles them, and then CHECKED against a file the client
wrote for itself — so a patch that changes the scheme says so loudly instead of
producing chunks the game silently refuses.

    python3 tools/lib/lua_chunk_enc.py            # what this install's loader wants
"""
from __future__ import annotations
import os
import struct
import sys
import zlib

sys.path.insert(0, "tools/lib")
import game_paths

#: The four bytes the loader looks for before it will read a chunk at all.
MAGIC = b"LENC"

#: A zlib stream the loader inflates after decrypting. We never produce one — source
#: is smaller than a deflate of itself at the sizes a chunk has — but the client's own
#: scripts are all like this, and that is what makes them a test sample.
ZLIB_HEAD = b"\x78\xda"

#: The dispatcher the key bytes come out of: a 44-way jump table of one-byte returns.
#: Two of them, XORed index by index, are the key and the nonce, which is why neither
#: is a run of bytes anywhere in the file to be found by looking for one.
#:
#:     cmp cl, N ; jae short ; movzx eax, ecx ; lea rcx, [rip+table] ; jmp [rcx+rax*8]
_THUNK_HEAD = b"\x0f\xb6\xc1\x48\x8d\x0d"
_THUNK_TAIL = b"\x48\xff\x24\xc1"

#: `mov al, imm8 ; ret` — every arm of that jump table.
_ARM = (b"\xb0", b"\xc3")

#: Key and nonce lengths, in that order: the loader's own initialiser fills 0x20 bytes
#: of one and 0x0c of the other out of one table walk.
KEY_LEN, NONCE_LEN = 32, 12

#: The round counts and feed-forward choices tried against the client's own scripts,
#: cheapest first. The live build is 4 double rounds without the addition; the rest are
#: here so that a patch which merely re-tunes the cipher is recognised rather than
#: reported as «no key».
_VARIANTS = ((4, False), (10, False), (4, True), (10, True), (8, False), (8, True))


def _rotl(v: int, n: int) -> int:
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF


def _quarter(x: list, a: int, b: int, c: int, d: int) -> None:
    x[a] = (x[a] + x[b]) & 0xFFFFFFFF; x[d] = _rotl(x[d] ^ x[a], 16)
    x[c] = (x[c] + x[d]) & 0xFFFFFFFF; x[b] = _rotl(x[b] ^ x[c], 12)
    x[a] = (x[a] + x[b]) & 0xFFFFFFFF; x[d] = _rotl(x[d] ^ x[a], 8)
    x[c] = (x[c] + x[d]) & 0xFFFFFFFF; x[b] = _rotl(x[b] ^ x[c], 7)


def keystream_block(key: bytes, nonce: bytes, counter: int,
                    rounds: int = 4, feedforward: bool = False) -> bytes:
    """One 64-byte block of the loader's keystream.

    `rounds` counts DOUBLE rounds (a column pass and a diagonal pass), which is how
    ChaCha is always counted: 4 here, 10 in ChaCha20. `feedforward` is the final
    addition of the starting state that every published ChaCha does and this one does
    not — kept as a switch because it is the one difference a patch is most likely to
    put back, and telling the two apart is a single decryption.
    """
    state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
    state += list(struct.unpack("<8I", key)) + [counter] + list(struct.unpack("<3I", nonce))
    work = state[:]
    for _ in range(rounds):
        _quarter(work, 0, 4, 8, 12); _quarter(work, 1, 5, 9, 13)
        _quarter(work, 2, 6, 10, 14); _quarter(work, 3, 7, 11, 15)
        _quarter(work, 0, 5, 10, 15); _quarter(work, 1, 6, 11, 12)
        _quarter(work, 2, 7, 8, 13); _quarter(work, 3, 4, 9, 14)
    if feedforward:
        work = [(work[i] + state[i]) & 0xFFFFFFFF for i in range(16)]
    return struct.pack("<16I", *work)


def crypt(key: bytes, nonce: bytes, data: bytes,
          rounds: int = 4, feedforward: bool = False) -> bytes:
    """XOR `data` with the keystream — the same call encrypts and decrypts."""
    out = bytearray(len(data))
    for i in range(0, len(data), 64):
        block = keystream_block(key, nonce, i // 64, rounds, feedforward)
        piece = data[i:i + 64]
        out[i:i + len(piece)] = bytes(a ^ b for a, b in zip(piece, block))
    return bytes(out)


class Scheme:
    """What THIS install's loader wants, and everything needed to give it that."""

    def __init__(self, key: bytes, nonce: bytes, rounds: int, feedforward: bool,
                 source: str = "", verified: bool = False):
        self.key, self.nonce = key, nonce
        self.rounds, self.feedforward = rounds, feedforward
        self.source, self.verified = source, verified

    def pack(self, chunk) -> bytes:
        """`chunk` — plain Lua source — as the loader expects to receive it.

        Takes text or bytes. Every caller in the tree holds a chunk as `str`, and the
        one that did not encode it first got `unsupported operand type(s) for ^: 'str'
        and 'int'` out of the daemon — five probes deep, against a live client, where a
        type error reads exactly like the game refusing us.
        """
        raw = chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
        return MAGIC + crypt(self.key, self.nonce, raw, self.rounds, self.feedforward)

    def unpack(self, blob: bytes) -> bytes:
        """The other direction, for reading the client's own scripts."""
        if blob[:4] != MAGIC:
            raise ValueError("not a LENC chunk")
        body = crypt(self.key, self.nonce, blob[4:], self.rounds, self.feedforward)
        return zlib.decompress(body) if body[:2] == ZLIB_HEAD else body

    def describe(self) -> str:
        return (f"ChaCha8 rounds={self.rounds * 2} feedforward={self.feedforward} "
                f"key={len(self.key)}B nonce={len(self.nonce)}B "
                f"{'verified' if self.verified else 'UNVERIFIED'} via {self.source}")


# --- reading the scheme out of the client -------------------------------------------

def _sections(blob: bytes):
    """``[(rva, raw_offset, size)]`` of a PE, enough to turn one into the other."""
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[pe:pe + 4] != b"PE\x00\x00":
        raise ValueError("not a PE file")
    n_sec = struct.unpack_from("<H", blob, pe + 6)[0]
    opt = struct.unpack_from("<H", blob, pe + 20)[0]
    base = pe + 24 + opt
    out = []
    for i in range(n_sec):
        head = base + 40 * i
        vsize, rva = struct.unpack_from("<II", blob, head + 8)
        rsize, roff = struct.unpack_from("<II", blob, head + 16)
        out.append((rva, roff, max(vsize, rsize), rsize))
    return out


def _image_base(blob: bytes) -> int:
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    return struct.unpack_from("<Q", blob, pe + 24 + 24)[0]


def _rva_to_off(secs, rva: int):
    for sec_rva, roff, size, rsize in secs:
        if sec_rva <= rva < sec_rva + size:
            delta = rva - sec_rva
            return roff + delta if delta < rsize else None
    return None


def _byte_tables(blob: bytes):
    """Every 44-way «return this byte» dispatcher in the file, as byte strings.

    Found by the shape of the thunk rather than by an address, because an address is
    the one thing guaranteed to move when the file is rebuilt.
    """
    secs = _sections(blob)
    base = _image_base(blob)
    tables = []
    at = 0
    while True:
        at = blob.find(_THUNK_HEAD, at)
        if at < 0:
            break
        head = at
        at += 1
        if blob[head + 10:head + 14] != _THUNK_TAIL:
            continue
        # …the count, three instructions earlier: cmp cl, N ; jae short
        if blob[head - 5:head - 3] != b"\x80\xf9" or blob[head - 2] != 0x73:
            continue
        count = blob[head - 3]
        if count != KEY_LEN + NONCE_LEN:
            continue
        rel = struct.unpack_from("<i", blob, head + 6)[0]
        table_rva = _off_to_rva(secs, head + 10) + rel
        table_off = _rva_to_off(secs, table_rva)
        if table_off is None:
            continue
        arms = bytearray()
        for i in range(count):
            target = struct.unpack_from("<Q", blob, table_off + 8 * i)[0] - base
            arm = _rva_to_off(secs, target)
            if arm is None or blob[arm:arm + 1] != _ARM[0] or blob[arm + 2:arm + 3] != _ARM[1]:
                arms = None
                break
            arms.append(blob[arm + 1])
        if arms is not None:
            tables.append(bytes(arms))
    return tables


def _off_to_rva(secs, off: int) -> int:
    for rva, roff, size, rsize in secs:
        if roff <= off < roff + rsize:
            return rva + (off - roff)
    raise ValueError("offset outside every section")


def loader_wants_magic(dll: bytes) -> bool:
    """Whether this `xlua.dll` is one that refuses a plain chunk."""
    return MAGIC in dll


def _sample() -> bytes:
    """One encrypted chunk the CLIENT wrote, to check a candidate key against.

    The script bundle beside `Player.log` is a flat archive of them; the first `LENC`
    in it is enough, and reading a few kilobytes of a 40 MB file costs nothing.
    """
    path = game_paths.lua_bundle()
    try:
        with open(path, "rb") as fh:
            head = fh.read(1 << 16)
    except OSError:
        return b""
    at = head.find(MAGIC)
    return head[at:at + 4096] if at >= 0 else b""


def _plausible(body: bytes) -> bool:
    """Whether a decryption looks like what the client stores: a zlib stream, Lua
    bytecode, or plain source. Anything else is a wrong key, and a wrong key is
    indistinguishable from noise — which is the point of checking."""
    if body[:2] == ZLIB_HEAD:
        return True
    if body[:4] == b"\x1bLua":
        return True
    return all(9 <= b < 0x7F for b in body[:64])


def extract(dll_path: str = "", sample: bytes = b"") -> "Scheme | None":
    """Read the scheme out of an `xlua.dll`, or ``None`` if this one has no LENC.

    `sample` overrides the client's own script bundle, for a test that must not need
    an installed game.
    """
    path = dll_path or game_paths.xlua_dll()
    # An unreadable plugin is NOT this module's to decide about — see :func:`scheme`,
    # which turns it into «assume plain source» rather than into a dead daemon.
    with open(path, "rb") as fh:
        blob = fh.read()
    if not loader_wants_magic(blob):
        return None
    tables = _byte_tables(blob)
    if len(tables) < 2:
        raise RuntimeError(
            f"{path}: found {len(tables)} key tables, need 2 — the loader's key "
            "assembly has changed shape; re-read it (docs/research/"
            "client-update-encrypted-lua.md §2)")
    probe = sample if sample else _sample()
    best = None
    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            mixed = bytes(a ^ b for a, b in zip(tables[i], tables[j]))
            key, nonce = mixed[:KEY_LEN], mixed[KEY_LEN:KEY_LEN + NONCE_LEN]
            for rounds, feed in _VARIANTS:
                cand = Scheme(key, nonce, rounds, feed, source=os.path.basename(path))
                if not probe:
                    return cand      # nothing to check against; the shape is all there is
                body = crypt(key, nonce, probe[4:], rounds, feed)
                if _plausible(body):
                    cand.verified = True
                    return cand
                best = best or cand
    raise RuntimeError(
        f"{path}: the key tables read, but nothing they make decrypts the client's own "
        "scripts — the cipher has changed (docs/research/client-update-encrypted-lua.md §2)")


_CACHED: "Scheme | None | str" = "unasked"


def scheme() -> "Scheme | None":
    """This install's scheme, read once. ``None`` when the client takes plain source.

    `LW_LUA_ENC=off` forces the old behaviour — for a build that has rolled back, and
    as the one lever a person has if this module ever gets it wrong.
    """
    global _CACHED
    if _CACHED != "unasked":
        return _CACHED
    if (os.environ.get("LW_LUA_ENC") or "").strip().lower() in ("off", "0", "no"):
        _CACHED = None
        return None
    try:
        _CACHED = extract()
    except OSError as exc:
        print(f"[lua] the client's Lua plugin cannot be read ({exc}) — chunks are sent "
              "as plain source", flush=True)
        _CACHED = None
    return _CACHED


def forget() -> None:
    """Ask the client again — after a patch, or in a test."""
    global _CACHED
    _CACHED = "unasked"


def pack(chunk: str) -> bytes:
    """A chunk of Lua source, ready for the VM: encrypted where the build wants it."""
    raw = chunk.encode("utf-8")
    live = scheme()
    return live.pack(raw) if live else raw


def main() -> int:
    live = scheme()
    print(f"xlua.dll : {game_paths.xlua_dll()}")
    if live is None:
        print("loader   : plain source (no LENC in this build)")
        return 0
    print(f"loader   : {live.describe()}")
    probe = _sample()
    if probe:
        body = crypt(live.key, live.nonce, probe[4:68], live.rounds, live.feedforward)
        print(f"sample   : {body[:16].hex()}  {'zlib' if body[:2] == ZLIB_HEAD else 'raw'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
