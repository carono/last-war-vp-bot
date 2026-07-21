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

# Centre of the map viewport and a horizontal swipe amplitude, in the same
# absolute-screen calibration as TOGGLE_BUTTON. A swipe here pans the map; on the
# *world* map that makes the client stream ``world.get.block`` — the continuous
# WORLD marker the passive scene detector keys on. On the base a swipe does not
# produce those queries, so it is a harmless no-op for scene purposes.
_PAN_CENTER = (956, 600)
_PAN_DX = 320

_POLL_INTERVAL = 0.25
_SETTLE_DELAY = 3.5  # fallback wait when there is no GameState to confirm against


def _tap_toggle(toggle) -> bool:
    """Tap the shared map-toggle button. Returns whether the tap was injected."""
    x, y = toggle
    return _input.touch_tap(x, y)


def pan_world() -> None:
    """Swipe the map once (there and back) to elicit ``world.get.block`` queries.

    Only the world map answers a pan with tile queries, so this is what turns the
    scene detector's WORLD marker fresh without depending on the one-shot
    ``go.to.world`` frame (which a mid-connection passive capture routinely drops)."""
    cx, cy = _PAN_CENTER
    _input.swipe(cx + _PAN_DX, cy, cx - _PAN_DX, cy)
    _input.swipe(cx - _PAN_DX, cy, cx + _PAN_DX, cy)


def _wait_for_scene(state: GameState, target: Scene, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state.scene is target:
            return True
        time.sleep(_POLL_INTERVAL)
    return state.scene is target


def _confirm_world(state: GameState, timeout: float) -> bool:
    """Poll for WORLD while panning to keep tile queries flowing until confirmed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pan_world()
        if state.scene is Scene.WORLD:
            return True
        time.sleep(_POLL_INTERVAL)
    return state.scene is Scene.WORLD


def _navigate(target: Scene, state, timeout, toggle) -> bool:
    """Shared body for :func:`go_to_world` / :func:`go_to_base`."""
    if state is not None and state.scene is target:
        return True  # already there — nothing to do

    if not _tap_toggle(toggle):
        return False

    if state is None:
        time.sleep(_SETTLE_DELAY)
        return True
    # WORLD is confirmed by eliciting continuous tile queries (a pan); CITY is the
    # quiet default, confirmed once the world markers age out of the detector window.
    if target is Scene.WORLD:
        return _confirm_world(state, timeout)
    return _wait_for_scene(state, target, timeout)


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


__all__ = ["go_to_world", "go_to_base", "pan_world", "TOGGLE_BUTTON"]
