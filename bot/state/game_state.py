"""The single, plain snapshot of what the game is currently showing.

``GameState`` is deliberately dumb: it holds values, not logic. The
:class:`~bot.state.stream_reader.StreamReader` mutates it from decoded server
messages; actions read it to decide what to do. Everything here is inferred from
the network stream, never from screenshots.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Scene(enum.Enum):
    """Which top-level view the client is on.

    Derived from push/response commands: e.g. ``go.to.world`` and world-map tile
    queries mean WORLD; leaving the world and base building collection mean CITY.
    """

    UNKNOWN = "unknown"
    CITY = "city"    # the player's own base
    WORLD = "world"  # the world / big map

    def __str__(self) -> str:  # nicer logs
        return self.value


@dataclass(slots=True)
class GameState:
    """A mutable snapshot of the observable game state.

    Attributes
    ----------
    scene:
        Current view (:class:`Scene`). ``UNKNOWN`` until the first decisive
        message is seen.
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
    """

    scene: Scene = Scene.UNKNOWN
    zoom: int | None = None
    resources: dict[str, int] = field(default_factory=dict)
    last_command: str | None = None
    last_update_ts: float | None = None

    def is_world(self) -> bool:
        return self.scene is Scene.WORLD

    def is_city(self) -> bool:
        return self.scene is Scene.CITY

    def summary(self) -> str:
        res = f" res={len(self.resources)}" if self.resources else ""
        zoom = f" zoom={self.zoom}" if self.zoom is not None else ""
        return f"<GameState scene={self.scene}{zoom}{res} last={self.last_command}>"


__all__ = ["GameState", "Scene"]
