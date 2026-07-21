"""Passive TCP decoder: keep a :class:`GameState` current from server pushes.

The client's traffic is plain TCP with no TLS, so we never inject or query the
game — we just watch the bytes it exchanges and infer state. Scene, zoom and
resources all come from the *commands* on the wire, not from screenshots:

* ``go.to.world`` / ``meteorite.enter.world`` and world-map tile queries
  (``world.get.block``, ``world.get.march.infos``) mean the client is on the
  WORLD map.
* ``user.leave.world`` and base building collection
  (``building.production.collect``) mean it is in the CITY (base).
* ``world.get.block`` carries ``viewLvl`` — the world-map zoom level.
* ``push.resource.item.update`` carries the current resource balances.

Usage is transport-agnostic. Feed it bytes from whatever tap is available:

    reader = StreamReader()
    reader.feed("down", server_bytes)   # from a live tshark/pcap follow
    reader.feed("up", client_bytes)
    print(reader.state.summary())

or replay a capture offline (great for tests — no game, no Windows needed):

    reader = StreamReader.from_pcap("capture.pcapng")
    print(reader.state.summary())
"""
from __future__ import annotations

from typing import Callable

from bot.core import protocol
from bot.core.protocol import DOWN, UP, Envelope
from bot.state.game_state import GameState, Scene

# --- command -> scene classification -----------------------------------------
# Curated on purpose. Broad prefix matching ("anything with 'city'") is wrong:
# world.get.alliance.city.* is world-map data, not the player's base. Only
# commands that can *only* happen in one view are used as scene evidence.
_WORLD_COMMANDS = frozenset({
    "go.to.world",            # explicit switch to the world map
    "meteorite.enter.world",  # cross-server travel lands you on the world map
    "world.get.block",        # rectangular world-tile query (world view only)
    "world.get.march.infos",  # march overlay on the world map
})
_CITY_COMMANDS = frozenset({
    "user.leave.world",           # explicit return to base
    "building.production.collect",  # collecting from your own base buildings
})

# world.get.block field that encodes the current world-map zoom.
_ZOOM_FIELD = "viewLvl"
# Push that restates resource balances.
_RESOURCE_COMMAND = "push.resource.item.update"
_RESOURCE_FIELD = "resource_items"


class StreamReader:
    """Decode both half-streams of the game connection into a live GameState."""

    def __init__(self, state: GameState | None = None,
                 on_command: Callable[[Envelope], None] | None = None) -> None:
        self.state = state if state is not None else GameState()
        # Optional observer, invoked for every decoded command (telemetry/tests).
        self._on_command = on_command
        # Per-direction reassembly tails: bytes that arrived mid-frame and must
        # be prepended to the next chunk.
        self._buffers: dict[str, bytes] = {DOWN: b"", UP: b""}

    # -- feeding -------------------------------------------------------------
    def feed(self, direction: str, data: bytes, ts: float | None = None) -> int:
        """Append ``data`` to a half-stream and apply every complete frame.

        ``direction`` is ``"down"`` (server) or ``"up"`` (client). Returns the
        number of frames applied. Any trailing partial frame is retained and
        re-tried when more bytes arrive.
        """
        if direction not in self._buffers:
            raise ValueError(f"direction must be 'down' or 'up', got {direction!r}")
        buf = self._buffers[direction] + data
        consumed = 0
        applied = 0
        for env, _start, end in protocol.decode_frames(buf, direction):
            self._apply(env, ts)
            applied += 1
            if end is not None:
                consumed = end
        # Keep only the unconsumed tail. Cap growth so a stream that never
        # resyncs can't grow without bound.
        self._buffers[direction] = buf[consumed:][-(1 << 20):]
        return applied

    def apply(self, env: Envelope, ts: float | None = None) -> None:
        """Apply an already-decoded :class:`Envelope` to the state.

        The :meth:`feed` path decodes raw bytes itself, but a live capture
        engine (``tools/live_tshark``) has *already* turned the wire into
        envelopes. This is the seam that lets such a source update the same
        GameState without a second, redundant decode — see ``bot.state.live``.
        """
        self._apply(env, ts)

    # -- state transitions ---------------------------------------------------
    def _apply(self, env: Envelope, ts: float | None) -> None:
        command = env.command
        if command is None:
            return  # keepalive / unrecognised — carries no state
        self.state.last_command = command
        if ts is not None:
            self.state.last_update_ts = ts

        if command in _WORLD_COMMANDS:
            self.state.scene = Scene.WORLD
        elif command in _CITY_COMMANDS:
            self.state.scene = Scene.CITY

        if command == "world.get.block":
            self._update_zoom(env.payload)
        elif command == _RESOURCE_COMMAND:
            self._update_resources(env.payload)

        if self._on_command is not None:
            self._on_command(env)

    def _update_zoom(self, payload: object) -> None:
        if isinstance(payload, dict):
            lvl = payload.get(_ZOOM_FIELD)
            if isinstance(lvl, (int, float)):
                self.state.zoom = int(lvl)

    def _update_resources(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        items = payload.get(_RESOURCE_FIELD)
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            rid = item.get("id") or item.get("cfgId") or item.get("itemId")
            amount = item.get("count")
            if amount is None:
                amount = item.get("num")
            if rid is not None and isinstance(amount, (int, float)):
                self.state.resources[str(rid)] = int(amount)

    # -- offline replay ------------------------------------------------------
    @classmethod
    def from_pcap(cls, path: str, state: GameState | None = None,
                  on_command: Callable[[Envelope], None] | None = None) -> "StreamReader":
        """Build a reader and replay a capture file through it, in time order.

        Reassembles the game flow(s) with the tools' pcap reader, then merges the
        frames of both directions by their capture timestamp so scene changes are
        applied in the order they actually happened. Pure decode — no game and no
        Windows APIs, so this runs anywhere scapy is installed.
        """
        import lastwar_proto as lp

        reader = cls(state=state, on_command=on_command)
        flows, _udp = lp.read_capture(path)
        for flow in flows.values():
            if not lp.is_game(flow):
                continue
            # Collect (ts, direction, envelope) for every frame in both halves,
            # dating each frame by the byte offset it starts at.
            events: list[tuple[float, str, Envelope]] = []
            for direction in (DOWN, UP):
                stream = flow[direction]
                if not stream:
                    continue
                for env, start, _end in protocol.decode_frames(stream, direction):
                    ts = lp.time_at(flow, direction, start)
                    events.append((ts if ts is not None else 0.0, direction, env))
            events.sort(key=lambda e: e[0])
            for ts, _direction, env in events:
                reader._apply(env, ts)
        return reader


__all__ = ["StreamReader"]
