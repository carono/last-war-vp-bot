"""The single, plain snapshot of what the game is currently showing.

``GameState`` is deliberately dumb: it holds values, not logic. The
:class:`~bot.state.stream_reader.StreamReader` mutates it from decoded server
messages; actions read it to decide what to do. Everything here is inferred from
the network stream, never from screenshots.

Scene is derived from a **sliding window of markers**, not from one-shot switch
commands. The one-shot ``go.to.world`` / ``user.leave.world`` frames are easy for
a passive capture that joined the connection mid-stream to miss, but each scene
has *continuous* traffic that is trivial to catch: the world map streams tile
queries (``world.get.block`` &c.) the whole time it is open, while the base does
not. So the rule is: **seen a WORLD marker within the last few seconds → WORLD;
otherwise, once any traffic has been decoded → CITY** (the base is the quiet
default). See :attr:`GameState.scene`.
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class Scene(enum.Enum):
    """Which top-level view the client is on.

    Derived from the recent-marker window (see :attr:`GameState.scene`): world-map
    tile/march queries mean WORLD; their absence, once traffic is flowing, means
    the client is back in its base (CITY).
    """

    UNKNOWN = "unknown"
    CITY = "city"    # the player's own base
    WORLD = "world"  # the world / big map

    def __str__(self) -> str:  # nicer logs
        return self.value


# How long a WORLD marker keeps the scene classified as WORLD after the last one
# was seen. The world map emits tile queries continuously (multiple per second
# while panning, and march/refresh pushes when idle), so a few seconds of silence
# is decisive evidence the client has left it. Wide enough to ride out a brief lull
# between queries, tight enough that a City<->World switch is confirmed promptly.
SCENE_WORLD_TTL = 12.0


def _clock() -> float:
    """Wall-clock reference for the scene window (seconds).

    ``time.time()`` (not ``monotonic``) so it is directly comparable with the
    capture (pcap) timestamps the markers are stamped with — the live decoder
    re-reads a rolling pcap, so a marker's age must be measured against real time,
    not against how long ago the decoder happened to process it."""
    return time.time()


@dataclass(slots=True)
class GameState:
    """A mutable snapshot of the observable game state.

    Attributes
    ----------
    zoom:
        World-map view level (the ``viewLvl`` of ``world.get.block``). ``None``
        off the world map or before any tile query. Lower = more zoomed in.
    resources:
        Latest known resource balances keyed by resource/item id, from
        ``push.resource.item.update``. Empty until the first update arrives.
    last_command:
        The most recent decoded command name — useful for debugging/telemetry.
    last_update_ts:
        Wall/stream timestamp of the last applied message, or ``None``.
    world_ts / city_ts:
        Monotonic time of the last WORLD / CITY marker. Drive :attr:`scene`.
    """

    zoom: int | None = None
    resources: dict[str, int] = field(default_factory=dict)
    last_command: str | None = None
    last_update_ts: float | None = None
    world_ts: float | None = None
    city_ts: float | None = None

    # -- marker stamping (called by the reader) ------------------------------
    def mark_world(self, ts: float | None = None) -> None:
        """Record a WORLD-only signal, stamped with the message time (``ts``)."""
        self.world_ts = _clock() if ts is None else ts

    def mark_city(self, ts: float | None = None) -> None:
        """Record a CITY-only signal, stamped with the message time (``ts``)."""
        self.city_ts = _clock() if ts is None else ts

    # -- derived scene -------------------------------------------------------
    @property
    def scene(self) -> Scene:
        """The current view, from the recent-marker window.

        WORLD while a WORLD marker is fresh (and newer than the last CITY marker);
        otherwise CITY as soon as *any* command has been decoded (the base is the
        quiet default — no world-map queries flow there); UNKNOWN only before the
        very first decoded command.
        """
        wt, ct = self.world_ts, self.city_ts
        if wt is not None and (_clock() - wt) <= SCENE_WORLD_TTL \
                and (ct is None or wt > ct):
            return Scene.WORLD
        if self.last_command is not None or ct is not None or wt is not None:
            return Scene.CITY
        return Scene.UNKNOWN

    def is_world(self) -> bool:
        return self.scene is Scene.WORLD

    def is_city(self) -> bool:
        return self.scene is Scene.CITY

    def summary(self) -> str:
        res = f" res={len(self.resources)}" if self.resources else ""
        zoom = f" zoom={self.zoom}" if self.zoom is not None else ""
        return f"<GameState scene={self.scene}{zoom}{res} last={self.last_command}>"


__all__ = ["GameState", "Scene", "SCENE_WORLD_TTL"]
