"""Navigate between the Base and World screens via the bottom-right toggle.

The toggle slot can show different icons depending on the current screen
and the world-map zoom level. Each visual variant is captured as its own
PNG template; in addition, the *presence* (or absence) of the persistent
right-column UI chrome is used as a second signal to disambiguate
maximum-zoom-out world from the regular screens, where the right-column
buttons (events, inventory, mail, alliance) disappear.

Templates currently recognised:

- ``toggle_to_world.png``    — visible on Base. Click → World. Indicator: base.
- ``toggle_to_base.png``     — visible on World (normal zoom). Click → Base. Indicator: world.
- ``world_zoom_reset.png``   — visible on World (max zoom-out, minimap UI). Click → resets zoom.
- ``inventory.png``          — chrome marker. Visible whenever the right-column UI is on screen.

Detection rule:

    chrome visible?
      yes  → look for toggle_to_world (base) / toggle_to_base (world)
      no   → look for world_zoom_reset (world, far). Otherwise → unknown
              (loading / modal / intro / other UI-hiding state).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import numpy as np

from ...inputs import click
from ...perception import templates
from ...perception.capture import grab

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_T_TO_WORLD = TEMPLATES_DIR / "toggle_to_world.png"
_T_TO_BASE = TEMPLATES_DIR / "toggle_to_base.png"
_T_ZOOM_RESET = TEMPLATES_DIR / "world_zoom_reset.png"
_T_INVENTORY = TEMPLATES_DIR / "inventory.png"  # right-column chrome proxy

Screen = Literal["base", "world"]

# Per-template match threshold. Empirical: clean UI captures score 0.95+;
# closest observed cross-scene false positive is 0.78. 0.85 is a safe margin.
MATCH_THRESHOLD = 0.85


@dataclass(slots=True)
class NavigateResult:
    target: Screen
    before: str | None
    after: str | None
    action: Literal["noop", "click", "no_button", "unknown_screen"]
    click_at: tuple[int, int] | None = None
    match_score: float | None = None
    attempts: int = 0
    success: bool = False


def _matches(image: np.ndarray, template_path: Path, threshold: float = MATCH_THRESHOLD) -> templates.Match | None:
    return templates.find(image, templates.cached_template(template_path), threshold)


def chrome_visible(image: np.ndarray) -> bool:
    """True if the persistent right-column UI is on screen.

    Uses the inventory button as a proxy for the whole right-column UI
    (events, mail, alliance, inventory). It disappears together with the
    other chrome whenever the game pulls UI out of the way (max world
    zoom, full-screen modals, loading screens, intro popups, ...).
    """
    return _matches(image, _T_INVENTORY) is not None


def identify_screen(image: np.ndarray) -> str | None:
    """Return 'base' / 'world' / None for the current screen.

    Multi-signal detection: the right-column chrome (presence / absence)
    gates the two regimes; within each, a specific toggle template
    disambiguates base vs. world.
    """
    if chrome_visible(image):
        if _matches(image, _T_TO_WORLD) is not None:
            return "base"
        if _matches(image, _T_TO_BASE) is not None:
            return "world"
        return None
    # Chrome absent. The only known chrome-absent regime is max-zoom world.
    if _matches(image, _T_ZOOM_RESET) is not None:
        return "world"
    return None


def _pick_next_action(image: np.ndarray, target: Screen) -> templates.Match | None:
    """Pick the highest-priority clickable template that advances toward `target`."""
    if target == "world":
        return _matches(image, _T_TO_WORLD)
    # target == "base"
    direct = _matches(image, _T_TO_BASE)
    if direct is not None:
        return direct
    # Preparatory step from max-zoom world: reset zoom first, then retry.
    return _matches(image, _T_ZOOM_RESET)


def _settle(hwnd: int, *, timeout: float, poll: float) -> tuple[str | None, np.ndarray]:
    """Poll `identify_screen` until it returns a known screen or `timeout` elapses.

    Used after each click to ride out transition animations where neither
    template is momentarily visible. Returns (screen, last_image).
    """
    deadline = time.monotonic() + timeout
    img = grab(hwnd)
    while True:
        screen = identify_screen(img)
        if screen is not None or time.monotonic() >= deadline:
            return screen, img
        time.sleep(poll)
        img = grab(hwnd)


def go_to(
    target: Screen,
    hwnd: int,
    *,
    settle_timeout: float = 5.0,
    poll_interval: float = 0.3,
    max_attempts: int = 4,
) -> NavigateResult:
    """Navigate to the requested screen.

    Each attempt: settle (poll until a known screen is visible) → if we're
    there, succeed → otherwise click the highest-priority action template
    (direct toggle or preparatory step) → next attempt. Multi-step paths
    such as `max-zoom world → zoom reset → toggle_to_base → base` are
    covered by the retry budget.
    """
    initial: str | None = None
    last_click: tuple[int, int] | None = None
    last_score: float | None = None
    attempt = 0

    for attempt in range(1, max_attempts + 1):
        current, before_img = _settle(hwnd, timeout=settle_timeout, poll=poll_interval)
        if initial is None:
            initial = current

        if current == target:
            return NavigateResult(
                target=target,
                before=initial,
                after=current,
                action="noop" if last_click is None else "click",
                click_at=last_click,
                match_score=last_score,
                attempts=attempt,
                success=True,
            )
        if current is None:
            return NavigateResult(
                target=target, before=initial, after=None, action="unknown_screen",
                attempts=attempt, success=False,
            )

        match = _pick_next_action(before_img, target)
        if match is None:
            return NavigateResult(
                target=target, before=initial, after=current, action="no_button",
                attempts=attempt, success=False,
            )

        cx, cy = match.center
        click(hwnd, cx, cy, mode="foreground")
        last_click = (cx, cy)
        last_score = match.score

    final, _ = _settle(hwnd, timeout=settle_timeout, poll=poll_interval)
    return NavigateResult(
        target=target,
        before=initial,
        after=final,
        action="click",
        click_at=last_click,
        match_score=last_score,
        attempts=attempt,
        success=(final == target),
    )
