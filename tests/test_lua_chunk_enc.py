r"""The wrapper a chunk must wear on an encrypted-Lua client, pinned without a client.

No game, no Windows, no installed plugin: the cipher is checked against a published
test vector, and the reader that lifts the key out of `xlua.dll` is run over a PE this
test builds itself. Run it anywhere::

    python3 tests/test_lua_chunk_enc.py

What is worth pinning (#1556, docs/research/client-update-encrypted-lua.md):

  * the loader takes ``LENC`` + a keystream XOR, and the MAGIC is not optional — a
    buffer without it is refused before a character is lexed, which is the whole of the
    outage the update caused;
  * the cipher is a ChaCha of **eight** rounds with **no** feed-forward addition, which
    is not any published one — so the quarter-round and the state layout are pinned
    against RFC 8439 (which the same code produces at 20 rounds with the addition), and
    the live variant is then a two-flag difference rather than an article of faith;
  * the key is never a constant in this repository. It is read out of the plugin every
    time, by the SHAPE of the code that assembles it, and checked against a file the
    client wrote — a build that rolls the key moves this by itself;
  * a plugin with no ``LENC`` in it means a client that takes plain source, and the old
    route must stay reachable for exactly that.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_chunk_enc as enc  # noqa: E402

IMAGE_BASE = 0x180000000
SEC_RVA, SEC_OFF = 0x1000, 0x400

#: Invented, and deliberately not the live build's — see the module note. Any 44 bytes
#: split into 32 + 12 exercise the same reader.
KEY = bytes((i * 7 + 11) & 0xFF for i in range(enc.KEY_LEN))
NONCE = bytes((i * 13 + 5) & 0xFF for i in range(enc.NONCE_LEN))


def _thunk(rel: int) -> bytes:
    """`cmp cl,44 ; jae +0e ; movzx eax,ecx ; lea rcx,[rip+rel] ; jmp [rcx+rax*8]`."""
    return (b"\x80\xf9" + bytes([enc.KEY_LEN + enc.NONCE_LEN]) + b"\x73\x0e"
            + enc._THUNK_HEAD + struct.pack("<i", rel) + enc._THUNK_TAIL)


def _fake_plugin(key: bytes, nonce: bytes, magic: bool = True) -> bytes:
    """A PE holding two byte-table dispatchers whose arms XOR to `key` + `nonce`."""
    mixed = key + nonce
    first = bytes((i * 31 + 3) & 0xFF for i in range(len(mixed)))
    second = bytes(a ^ b for a, b in zip(first, mixed))

    body = bytearray()

    def place(chunk: bytes) -> int:
        at = len(body)
        body.extend(chunk)
        return at

    arms = []
    for table in (first, second):
        arms.append([place(b"\xb0" + bytes([b]) + b"\xc3") for b in table])
    if magic:
        place(enc.MAGIC + b"\x1bLua\x00")
    while len(body) % 8:
        body.append(0xCC)
    tables = [place(b"".join(struct.pack("<Q", IMAGE_BASE + SEC_RVA + a) for a in row))
              for row in arms]
    for table in tables:
        at = place(_thunk(0))
        # the displacement is measured from the END of the lea, which sits 10 bytes
        # into the thunk's own opcodes — the same arithmetic the reader undoes
        lea_end = at + 5 + len(enc._THUNK_HEAD) + 4
        struct.pack_into("<i", body, at + 5 + len(enc._THUNK_HEAD), table - lea_end)

    raw = bytes(body).ljust(0x200, b"\xcc")
    pe_off = 0x80
    opt = struct.pack("<H", 0x20B) + b"\x00" * 22 + struct.pack("<Q", IMAGE_BASE)
    opt = opt.ljust(0xF0, b"\x00")
    head = bytearray(b"MZ".ljust(0x3C, b"\x00") + struct.pack("<I", pe_off))
    head = head.ljust(pe_off, b"\x00")
    head += b"PE\x00\x00" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, len(opt), 0x2022)
    head += opt
    head += (b".text\x00\x00\x00" + struct.pack("<IIII", len(raw), SEC_RVA, len(raw), SEC_OFF)
             + b"\x00" * 16)
    return bytes(head).ljust(SEC_OFF, b"\x00") + raw


def _write(blob: bytes) -> str:
    fh = tempfile.NamedTemporaryFile(suffix=".dll", delete=False)
    fh.write(blob)
    fh.close()
    return fh.name


def test_chacha_matches_rfc8439_at_twenty_rounds():
    """The state layout and the quarter-round, against published truth.

    Same code, ten double rounds and the feed-forward addition: RFC 8439 §2.3.2.
    """
    block = enc.keystream_block(bytes(range(32)),
                                bytes.fromhex("000000090000004a00000000"),
                                1, rounds=10, feedforward=True)
    assert block[:16].hex() == "10f1e7e4d13b5915500fdd1fa32071c4", block[:16].hex()


def test_crypt_is_its_own_inverse():
    data = b"CS.UnityEngine.Debug.LogError('LW ok')" * 5
    once = enc.crypt(KEY, NONCE, data)
    assert once != data
    assert enc.crypt(KEY, NONCE, once) == data


def test_crypt_spans_block_boundaries():
    """A chunk is longer than 64 bytes, so the counter has to advance."""
    data = bytes(range(256)) * 3
    back = enc.crypt(KEY, NONCE, enc.crypt(KEY, NONCE, data))
    assert back == data


def test_pack_wears_the_magic_and_unpacks():
    scheme = enc.Scheme(KEY, NONCE, 4, False)
    blob = scheme.pack(b"-- LW1556")
    assert blob[:4] == enc.MAGIC, blob[:8]
    assert blob[4:] != b"-- LW1556"
    assert scheme.unpack(blob) == b"-- LW1556"


def test_pack_takes_the_text_every_caller_actually_holds():
    """A chunk is a `str` everywhere in the tree, and it must not have to be encoded.

    It did once, and the daemon reported the resulting TypeError as "the probe did not
    reach the client" — indistinguishable, from outside, from the game refusing us.
    """
    scheme = enc.Scheme(KEY, NONCE, 4, False)
    assert scheme.pack("-- LW1556") == scheme.pack(b"-- LW1556")


def test_unpack_inflates_what_the_client_stores():
    """The client's own chunks are deflated inside the encryption; ours are not."""
    scheme = enc.Scheme(KEY, NONCE, 4, False)
    payload = zlib.compress(b"\x1bLuaS" + b"\x00" * 40, 9)
    assert payload[:2] == enc.ZLIB_HEAD
    blob = enc.MAGIC + enc.crypt(KEY, NONCE, payload)
    assert scheme.unpack(blob).startswith(b"\x1bLua")


def test_unpack_refuses_a_chunk_without_the_magic():
    scheme = enc.Scheme(KEY, NONCE, 4, False)
    try:
        scheme.unpack(b"print('hi')")
    except ValueError:
        return
    raise AssertionError("a buffer with no LENC was accepted")


def test_key_is_read_out_of_the_plugin():
    path = _write(_fake_plugin(KEY, NONCE))
    try:
        sample = enc.MAGIC + enc.crypt(KEY, NONCE, zlib.compress(b"-- sample", 9))
        scheme = enc.extract(path, sample=sample)
    finally:
        os.unlink(path)
    assert scheme is not None
    assert scheme.key == KEY, scheme.key.hex()
    assert scheme.nonce == NONCE, scheme.nonce.hex()
    assert scheme.verified, "the sample decrypted, so it should be marked verified"


def test_a_plugin_without_the_magic_means_plain_source():
    path = _write(_fake_plugin(KEY, NONCE, magic=False))
    try:
        assert enc.extract(path) is None
    finally:
        os.unlink(path)


def test_a_wrong_sample_is_reported_and_not_guessed_past():
    """A key that decrypts nothing is a changed cipher, and must SAY so."""
    path = _write(_fake_plugin(KEY, NONCE))
    try:
        enc.extract(path, sample=enc.MAGIC + b"\x00" * 64)
    except RuntimeError:
        return
    finally:
        os.unlink(path)
    raise AssertionError("a key that decrypts nothing was accepted")


def test_the_switch_turns_the_wrapper_off():
    before = os.environ.get("LW_LUA_ENC")
    os.environ["LW_LUA_ENC"] = "off"
    enc.forget()
    try:
        assert enc.scheme() is None
        assert enc.pack("print('hi')") == b"print('hi')"
    finally:
        enc.forget()
        if before is None:
            os.environ.pop("LW_LUA_ENC", None)
        else:
            os.environ["LW_LUA_ENC"] = before


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
