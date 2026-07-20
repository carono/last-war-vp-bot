r"""Userland asyncio MITM relay for the Last War game connection.

This is Vector A from ``docs/research/command-injection-vectors.md``: instead of
forging a TCP frame into the client's stream from the outside (a kernel driver
ACE bans) or borrowing the client's own socket (``steal_via_socket.py`` — sends
blind, no reply path), stand up an ordinary application-layer man-in-the-middle::

    game  ──real TCP──▶  this relay  ──real TCP──▶  real gateway :17935

Both legs are normal OS sockets, so the kernel owns both TCP state machines and
seq/ack are correct for free — the client's stream is never spliced mid-frame.
The same connection carries end to end, so the login/auth is untouched. And the
crucial win over the two prior attempts: **the server's reply flows back through
us**, so a `go.to.world` injection is finally *observable* — we see the
`{success, _id}` come back rather than sending into the dark.

What this file does NOT do is get the game's packets onto the relay. The client
dials a bare gateway IP on :17935 with no DNS and races three gateways at login,
so redirection has to key on *destination port*, not a name or a fixed IP. That
front-end is a separate concern (see the module epilogue and the research doc):

  * Linux / Android emulator: an ``iptables -t nat`` REDIRECT of dst-port 17935
    to this relay's ``--listen`` port. Run with ``--transparent`` so the relay
    recovers the real gateway from ``SO_ORIGINAL_DST`` — no ``--upstream`` needed.
  * Windows: a userland redirector (the existing tolerated TUN with a dst-port
    rule, or a wintun + tun2socks of our own) points the :17935 flow at the
    relay, and ``--upstream <gateway-ip>:17935`` names where to forward. The
    gateway IP is read off a passive capture (`live_tshark.py`) beforehand.

Decoding reuses ``lastwar_proto`` and injection reuses ``lastwar_encode``, so the
relay never re-implements the wire format.

Run it with the Windows Python when the game is on Windows, so the relay and the
game share a loopback; it is pure-stdlib asyncio and also runs under WSL/Linux
for a loopback self-test or an emulator run::

    # observe only — decode and log every frame through both legs
    python tools/relay.py --upstream 1.2.3.4:17935

    # inject a safe go.to.world 20s after the client connects, then swallow its reply
    python tools/relay.py --upstream 1.2.3.4:17935 --inject-cmd go.to.world --inject-after 20

    # Linux transparent mode (iptables REDIRECT front-end), inject after 20s
    sudo iptables -t nat -A OUTPUT -p tcp --dport 17935 -j REDIRECT --to-ports 17935
    python tools/relay.py --transparent --inject-cmd go.to.world --inject-after 20

The `_id` counter is the one real subtlety and the research doc leaves the crux
open: is the server's check *strictly sequential* (renumber every later client
frame) or *monotonic with gaps allowed* (inject at last+1 and leave the client
alone)? ``--id-mode`` picks which hypothesis to run — ``passive`` (default) is
the simplest and the experiment to try first; ``nat`` shifts subsequent client
`_id`s to test the strict case. See ``IdTranslator`` for the details.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lastwar_proto as proto  # noqa: E402
from lastwar_encode import (  # noqa: E402
    Reader,
    Typed,
    build_request,
    decompress_zlib,
    infer,
    read_typed,
    unmask,
    write_typed,
)

GAME_PORT = 17935

# SO_ORIGINAL_DST is Linux-only (netfilter). Guard the import so the module
# still loads on Windows, where transparent mode is not available anyway.
SO_ORIGINAL_DST = 80

C_RESET = "\033[0m"
C_UP = "\033[96m"      # client -> server
C_DOWN = "\033[93m"    # server -> client
C_INJECT = "\033[92m"
C_WARN = "\033[91m"
C_DIM = "\033[90m"


def _now() -> str:
    return time.strftime("%H:%M:%S")


# --------------------------------------------------------------------------
# Frame boundary detection over a live byte stream
# --------------------------------------------------------------------------


class FrameChannel:
    """Split one direction of a live connection into whole game frames.

    A relay attaches at the true start of each TCP connection and knows which
    side is the client (the accepted socket, ``up``) and which is the server
    (the upstream socket, ``down``), so unlike the passive sniffer there is no
    direction probing — the frame walker in ``lastwar_proto`` is driven with a
    known direction.

    ``feed`` returns the list of complete frames now available as
    ``(raw_bytes, envelope)`` pairs and holds the partial tail for the next
    segment. ``raw_bytes`` is the exact on-wire slice, so a passthrough forwards
    it untouched and only an injection or a rewrite substitutes different bytes.
    """

    # If the buffer grows past this without a single frame decoding, the stream
    # has desynced (a frame shape the decoder cannot follow). Rather than stall
    # the connection, flush the buffer verbatim and carry on in raw passthrough
    # — correctness of the byte stream must never depend on the decoder.
    DESYNC_LIMIT = 1 << 20

    def __init__(self, direction: str):
        self.direction = direction
        self.buf = b""
        self.frames = 0
        self.desynced = False

    def feed(self, data: bytes):
        """Return ``[(raw, env), ...]`` for every frame now complete."""
        self.buf += data
        out: list[tuple[bytes, object]] = []
        consumed = 0
        try:
            for env, start, end in proto.iter_frames(self.buf, self.direction):
                if end is None or end <= start:
                    continue
                # Forward the contiguous span up to this frame's end, including
                # any bytes the decoder resynced past, so the wire stream stays
                # byte-perfect even when a frame fails to decode.
                out.append((self.buf[consumed:end], env))
                consumed = end
                self.frames += 1
        except IndexError:
            # Buffer ends inside a header (a client header is 5 bytes, the
            # walker bounds on 3) — "need more data", not a failure.
            pass
        if consumed:
            self.buf = self.buf[consumed:]
        if len(self.buf) > self.DESYNC_LIMIT:
            # Desync: hand back the whole tail as a raw, envelope-less frame so
            # the caller forwards it and the stream keeps flowing.
            self.desynced = True
            out.append((self.buf, None))
            self.buf = b""
        return out


# --------------------------------------------------------------------------
# `_id` translation — the crux the research doc leaves open
# --------------------------------------------------------------------------


def _find_id_node(node, delta: int) -> bool:
    """Add ``delta`` to the ``_id`` value inside a decoded ``Typed`` tree.

    ``_id`` lives in the params map (``envelope.p.p._id``), but rather than
    hard-code the path this walks the tree and rewrites the first ``_id`` key it
    finds under any map, re-inferring the integer width so a carry into a wider
    type is handled. Returns True if an ``_id`` was found and changed.
    """
    if not isinstance(node, Typed):
        return False
    tag, value = node
    if tag == proto.T_MAP:
        pairs = list(value)
        for i, (key, val) in enumerate(pairs):
            name = key.decode("utf-8", "replace") if isinstance(key, bytes) else key
            if name == "_id" and isinstance(val, Typed) and isinstance(val.value, int):
                pairs[i] = (key, infer(val.value + delta))
                node.value[:] = pairs
                return True
            if _find_id_node(val, delta):
                return True
    elif tag == proto.T_LIST:
        for item in value:
            if _find_id_node(item, delta):
                return True
    return False


def read_client_id(env) -> int | None:
    """The ``_id`` this client frame carries, or None."""
    payload = proto.envelope_payload(env)
    if isinstance(payload, dict):
        rid = payload.get("_id")
        if isinstance(rid, int):
            return rid
    return None


def rewrite_client_id(raw: bytes, delta: int) -> bytes | None:
    """Return ``raw`` with its ``_id`` shifted by ``delta``, or None if it can't.

    Byte-exact for the common uncompressed client frame (the writer is the
    verified mirror of the reader); a compressed frame is re-deflated, which is
    valid but not byte-identical. None is returned for anything this cannot
    safely rewrite, so the caller falls back to forwarding the original.
    """
    if delta == 0 or len(raw) < 5:
        return None
    flags = raw[0]
    if flags not in proto.CLIENT_MAGICS or flags & proto.FLAG_LEN32:
        return None
    compressed = bool(flags & proto.FLAG_COMPRESSED)
    server_id = int.from_bytes(raw[1:3], "big")
    k2, k1 = raw[3], raw[4]
    body = unmask(raw[5:], k1, k2)
    try:
        if compressed:
            tlv, _consumed = decompress_zlib(body)
        else:
            tlv = body
        node = read_typed(Reader(tlv))
    except Exception:
        return None
    if not _find_id_node(node, delta):
        return None
    try:
        new_tlv = write_typed(node)
    except Exception:
        return None
    # build_request is the whole-frame builder; reuse its inner framing by hand
    # so the TLV is our rewritten tree rather than a re-authored envelope.
    from lastwar_encode import build_client_frame

    return build_client_frame(new_tlv, server_id, k1, k2, compress=compressed)


class IdTranslator:
    """Keeps the client's `_id` sequence consistent after an injection.

    Injecting one frame consumes an `_id`, so every later client frame is now
    off by the number injected. Two hypotheses, selected by ``mode``:

    * ``passive`` — do nothing to client frames. This is right if the server
      accepts a *monotonic* sequence with gaps: our injection takes ``last+1``
      and the client's next real frame (still ``last+1`` from its view) is a
      duplicate the server may tolerate or ignore. Simplest, and the experiment
      the research doc says to run first.
    * ``nat`` — shift every subsequent client frame's `_id` up by ``offset`` so
      the server sees a strictly increasing sequence with no collision. This is
      right if the server's check is strict-sequential. The matching down-side
      remap (rewriting the server's echoed `_id` back for the client) is **not**
      performed — server frames are length-prefixed and compressed and rewriting
      them is far riskier; so in ``nat`` mode the client may reject the shifted
      replies. That is acceptable because the point of ``nat`` is to learn
      whether the *server* accepts the shifted client frames, which its
      responses reveal.
    """

    def __init__(self, mode: str):
        self.mode = mode
        self.offset = 0

    def note_injection(self):
        self.offset += 1

    def on_client_frame(self, raw: bytes, env) -> bytes:
        if self.mode != "nat" or self.offset == 0:
            return raw
        rewritten = rewrite_client_id(raw, self.offset)
        if rewritten is None:
            return raw
        return rewritten


# --------------------------------------------------------------------------
# One relayed connection
# --------------------------------------------------------------------------


class Connection:
    _counter = 0

    def __init__(self, relay: "Relay", reader, writer, upstream):
        Connection._counter += 1
        self.id = Connection._counter
        self.relay = relay
        self.creader, self.cwriter = reader, writer
        self.upstream = upstream          # (host, port)
        self.sreader = self.swriter = None
        self.up = FrameChannel("up")      # client -> server
        self.down = FrameChannel("down")  # server -> client
        # Header params snooped off client frames, needed to build an injection.
        self.server_id = None
        self.k1 = self.k2 = None
        self.max_id = -1
        self.up_frames = 0
        self.started = time.monotonic()
        self.alive = True

    @property
    def peer(self) -> str:
        try:
            host, port = self.cwriter.get_extra_info("peername")[:2]
            return f"{host}:{port}"
        except Exception:
            return "?"

    async def run(self):
        try:
            self.sreader, self.swriter = await asyncio.open_connection(*self.upstream)
        except Exception as exc:
            self.relay.log(f"conn#{self.id} upstream {self.upstream[0]}:"
                           f"{self.upstream[1]} failed: {exc}", C_WARN)
            self.cwriter.close()
            return
        self.relay.log(f"conn#{self.id} {self.peer} → "
                       f"{self.upstream[0]}:{self.upstream[1]} open")
        self.relay.register(self)
        try:
            await asyncio.gather(self._pump_up(), self._pump_down())
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.alive = False
            for w in (self.cwriter, self.swriter):
                try:
                    w.close()
                except Exception:
                    pass
            self.relay.log(f"conn#{self.id} closed "
                           f"(up {self.up.frames} frames, down {self.down.frames})",
                           C_DIM)

    async def _pump_up(self):
        """Client → server: frame it, snoop `_id`, forward, allow injection."""
        while True:
            data = await self.creader.read(65536)
            if not data:
                break
            for raw, env in self.up.feed(data):
                self._snoop(raw, env)
                out = self.relay.ids.on_client_frame(raw, env)
                self.swriter.write(out)
                self._log_frame("up", env, len(raw))
            await self.swriter.drain()
            # Inject only between whole client frames, never mid-frame.
            await self.relay.maybe_inject(self)
        try:
            self.swriter.write_eof()
        except Exception:
            pass

    async def _pump_down(self):
        """Server → client: frame it, swallow our injection's reply, forward."""
        while True:
            data = await self.sreader.read(65536)
            if not data:
                break
            for raw, env in self.down.feed(data):
                if self.relay.should_swallow(env):
                    self._log_frame("down", env, len(raw), swallowed=True)
                    continue
                self.cwriter.write(raw)
                self._log_frame("down", env, len(raw))
            await self.cwriter.drain()
        try:
            self.cwriter.write_eof()
        except Exception:
            pass

    def _snoop(self, raw: bytes, env):
        """Learn server_id / k1 / k2 / max `_id` from a client frame header."""
        self.up_frames += 1
        if len(raw) >= 5 and raw[0] in proto.CLIENT_MAGICS:
            self.server_id = int.from_bytes(raw[1:3], "big")
            self.k2, self.k1 = raw[3], raw[4]
        rid = read_client_id(env)
        if rid is not None and rid > self.max_id:
            self.max_id = rid

    def _log_frame(self, direction, env, nbytes, swallowed=False):
        if not self.relay.verbose and env is not None and not swallowed:
            cmd = proto.envelope_command(env)
            if cmd in self.relay.quiet_commands:
                return
        colour = C_DOWN if direction == "down" else C_UP
        arrow = "←" if direction == "down" else "→"
        cmd = proto.envelope_command(env) or "?"
        rid = read_client_id(env) if direction == "up" else None
        payload = proto.envelope_payload(env)
        rid_txt = f" _id={rid}" if rid is not None else ""
        if direction == "down" and isinstance(payload, dict) and "_id" in payload:
            rid_txt = f" _id={payload['_id']}"
        tag = f"{C_WARN}[SWALLOW]{C_RESET} " if swallowed else ""
        self.relay.log(f"conn#{self.id} {arrow} {tag}{cmd}{rid_txt} ({nbytes}B)",
                       colour)


# --------------------------------------------------------------------------
# Relay: server socket, connection registry, injection scheduler
# --------------------------------------------------------------------------


class Relay:
    def __init__(self, args):
        self.args = args
        self.verbose = args.verbose
        self.transparent = args.transparent
        self.upstream = args.upstream           # (host, port) or None
        self.ids = IdTranslator(args.id_mode)
        self.conns: list[Connection] = []
        self.inject_cmd = args.inject_cmd
        self.inject_after = args.inject_after
        self.inject_params = args.inject_params
        self.injected = False
        self.inject_deadline = None
        self.swallow_id = None
        # Keepalives and map scrolls dominate the log; hide them unless -v.
        self.quiet_commands = {"heart.beat", "world.get.block", "get.user.info.multi"}

    def log(self, message: str, colour: str = ""):
        stamp = f"{C_DIM}{_now()}{C_RESET}"
        print(f"{stamp} {colour}{message}{C_RESET}", flush=True)

    def register(self, conn: Connection):
        self.conns.append(conn)
        if self.inject_after is not None and self.inject_deadline is None:
            self.inject_deadline = time.monotonic() + self.inject_after
            self.log(f"injection armed: '{self.inject_cmd}' in "
                     f"{self.inject_after:g}s (id-mode={self.ids.mode})", C_INJECT)

    def _upstream_for(self, conn: Connection):
        """Where a freshly accepted client connection should be forwarded.

        Transparent mode reads the real gateway the client dialed from the
        socket's SO_ORIGINAL_DST; otherwise every connection goes to the single
        ``--upstream`` gateway.
        """
        return self.upstream

    def surviving(self) -> Connection | None:
        """The connection to inject on: the live one carrying the most frames.

        At login the client races three :17935 gateways and keeps one; the
        survivor is the connection still alive and still carrying client frames
        after the first second. Picking the busiest live connection with a known
        header selects it without having to watch the other two die.
        """
        ready = [c for c in self.conns
                 if c.alive and c.server_id is not None and c.k1 is not None]
        if not ready:
            return None
        return max(ready, key=lambda c: c.up_frames)

    async def maybe_inject(self, conn: Connection):
        if self.injected or self.inject_deadline is None:
            return
        if time.monotonic() < self.inject_deadline:
            return
        target = self.surviving()
        if target is None or target is not conn:
            # Only inject from the surviving connection's own up-pump, so we are
            # guaranteed to be at a frame boundary on that exact socket.
            return
        rid = conn.max_id + 1
        params = dict(self.inject_params)
        params["_id"] = rid
        try:
            frame = build_request(self.inject_cmd, params,
                                  server_id=conn.server_id,
                                  k1=conn.k1, k2=conn.k2, request_id=-1)
        except Exception as exc:
            self.log(f"inject build failed: {exc}", C_WARN)
            self.injected = True
            return
        conn.swriter.write(frame)
        await conn.swriter.drain()
        self.injected = True
        self.swallow_id = rid
        self.ids.note_injection()
        self.log(f"conn#{conn.id} ⇑ INJECT {self.inject_cmd} _id={rid} "
                 f"({len(frame)}B) — awaiting reply", C_INJECT)

    def should_swallow(self, env) -> bool:
        """True for the server's reply to our own injection (never the client's).

        The reply echoes the `_id` we chose, which the client never sent, so it
        would confuse the client's own reply matching. Swallow exactly one and
        report whether the server accepted the command.
        """
        if self.swallow_id is None:
            return False
        payload = proto.envelope_payload(env)
        if not isinstance(payload, dict):
            return False
        if payload.get("_id") != self.swallow_id:
            return False
        success = payload.get("success")
        self.log(f"⇓ injection reply _id={self.swallow_id} "
                 f"success={success!r} — {'ACCEPTED' if success else 'see payload'}",
                 C_INJECT)
        if self.verbose:
            self.log(json.dumps(payload, default=str)[:500], C_DIM)
        self.swallow_id = None
        return True

    async def handle(self, reader, writer):
        upstream = self.upstream
        if self.transparent:
            upstream = self._original_dst(writer)
            if upstream is None:
                writer.close()
                return
        conn = Connection(self, reader, writer, upstream)
        await conn.run()

    def _original_dst(self, writer):
        """Recover the real gateway from a transparently redirected socket.

        Linux netfilter stashes the pre-REDIRECT destination on the socket; read
        it with the SO_ORIGINAL_DST getsockopt. Returns (host, port) or None.
        """
        try:
            sock = writer.get_extra_info("socket")
            raw = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
            port, host = struct.unpack("!2xH4s8x", raw)
            return (socket.inet_ntoa(host), port)
        except Exception as exc:
            self.log(f"SO_ORIGINAL_DST failed ({exc}); is this a REDIRECT socket "
                     f"on Linux?", C_WARN)
            return None

    async def serve(self):
        host, port = self.args.listen
        server = await asyncio.start_server(self.handle, host, port)
        mode = "transparent (SO_ORIGINAL_DST)" if self.transparent \
            else f"→ {self.upstream[0]}:{self.upstream[1]}"
        self.log(f"relay listening on {host}:{port}  {mode}", C_INJECT)
        async with server:
            await server.serve_forever()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _hostport(text: str, default_port: int = GAME_PORT):
    if ":" in text:
        host, _, port = text.rpartition(":")
        return (host, int(port))
    return (text, default_port)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", type=_hostport, default=("0.0.0.0", GAME_PORT),
                    metavar="HOST:PORT",
                    help="where the relay accepts the redirected game connection "
                         "(default 0.0.0.0:17935)")
    ap.add_argument("--upstream", type=_hostport, metavar="HOST:PORT",
                    help="the real gateway to forward to; required unless "
                         "--transparent")
    ap.add_argument("--transparent", action="store_true",
                    help="Linux only: read the real gateway from SO_ORIGINAL_DST "
                         "(iptables REDIRECT front-end), no --upstream needed")
    ap.add_argument("--inject-cmd", metavar="NAME",
                    help="command to inject once, e.g. go.to.world")
    ap.add_argument("--inject-after", type=float, metavar="SECONDS",
                    help="inject that many seconds after the first connection")
    ap.add_argument("--inject-params", metavar="JSON", default="{}",
                    help="extra params for the injected command (JSON object); "
                         "_id is added automatically")
    ap.add_argument("--id-mode", choices=("passive", "nat"), default="passive",
                    help="passive: leave client frames alone (monotonic-gaps "
                         "hypothesis). nat: shift later client _ids by the "
                         "injection offset (strict-sequential hypothesis)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="log every frame, including keepalives and map scrolls")
    args = ap.parse_args()

    if not args.transparent and not args.upstream:
        ap.error("either --upstream HOST:PORT or --transparent is required")
    if bool(args.inject_cmd) ^ (args.inject_after is not None):
        ap.error("--inject-cmd and --inject-after go together")
    try:
        args.inject_params = json.loads(args.inject_params)
        if not isinstance(args.inject_params, dict):
            raise ValueError("must be a JSON object")
    except ValueError as exc:
        ap.error(f"--inject-params: {exc}")

    relay = Relay(args)
    try:
        asyncio.run(relay.serve())
    except KeyboardInterrupt:
        relay.log("stopped", C_DIM)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
