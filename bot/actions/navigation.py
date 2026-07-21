"""Map navigation: switch between the base (CITY) and the world map (WORLD).

The reliable switch is a single touch on the shared bottom-right toggle button.
That button sits in the *same* screen position on both screens and only swaps
its icon ("go to world" on the base, "go to base" on the world), so one fixed
coordinate drives the round trip in either direction — no template matching, no
screenshot, no CV.

Confirmation is state-driven when a :class:`~bot.state.game_state.GameState` is
supplied: the passive stream reader flips ``scene`` when the server acknowledges
the switch, so navigation polls the state instead of guessing from pixels. With
no state to watch it falls back to a fixed settle delay.
"""
from __future__ import annotations

import time

from bot.actions import input as _input
from bot.state.game_state import GameState, Scene

# Absolute screen coordinate of the bottom-right map toggle. Shared by both
# directions because the button never moves — only its icon changes. Calibrated
# against the reference capture resolution (see tools/touch_click.py); override
# via the ``toggle`` argument if the window is a different size.
TOGGLE_BUTTON = (1713, 1095)

_POLL_INTERVAL = 0.25
_SETTLE_DELAY = 3.5  # fallback wait when there is no GameState to confirm against


def _tap_toggle(toggle) -> bool:
    """Tap the shared map-toggle button. Returns whether the tap was injected."""
    x, y = toggle
    return _input.touch_tap(x, y)


def _wait_for_scene(state: GameState, target: Scene, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state.scene is target:
            return True
        time.sleep(_POLL_INTERVAL)
    return state.scene is target


def _navigate(target: Scene, state, timeout, toggle) -> bool:
    """Shared body for :func:`go_to_world` / :func:`go_to_base`."""
    if state is not None and state.scene is target:
        return True  # already there — nothing to do

    if not _tap_toggle(toggle):
        return False

    if state is not None:
        return _wait_for_scene(state, target, timeout)
    time.sleep(_SETTLE_DELAY)
    return True


def go_to_world(state: GameState | None = None, timeout: float = 10.0,
                toggle=TOGGLE_BUTTON) -> bool:
    """Switch to the world map. Returns ``True`` once on WORLD (or tapped).

    With ``state`` given, returns ``True`` only after the stream reader confirms
    the scene is WORLD within ``timeout``; without it, taps and settles.
    """
    return _navigate(Scene.WORLD, state, timeout, toggle)


def go_to_base(state: GameState | None = None, timeout: float = 10.0,
               toggle=TOGGLE_BUTTON) -> bool:
    """Switch to the base (CITY). Returns ``True`` once on CITY (or tapped)."""
    return _navigate(Scene.CITY, state, timeout, toggle)


__all__ = ["go_to_world", "go_to_base", "TOGGLE_BUTTON"]
