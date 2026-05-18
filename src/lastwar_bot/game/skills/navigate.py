"""Navigate between the Base and World screens via the bottom-right toggle.

Both target screens carry the toggle button in the same slot — only its
icon swaps. Detection is symmetric: whichever toggle icon is visible
tells us which screen we're currently on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from ...inputs import click
from ...perception import templates
from ...perception.capture import grab

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
T_TO_WORLD = TEMPLATES_DIR / "toggle_to_world.png"  # visible on BASE  → press to go to WORLD
T_TO_BASE = TEMPLATES_DIR / "toggle_to_base.png"    # visible on WORLD → press to go to BASE

Screen = Literal["base", "world"]

# Per-screen match score threshold. Empirical: clean UI captures score
# 0.95+. Set conservative; lower if false negatives appear.
MATCH_THRESHOLD = 0.85


@dataclass(slots=True)
class NavigateResult:
    target: Screen
    before: str | None        # detected screen before the action
    after: str | None         # detected screen after the action (or None for noop)
    action: Literal["noop", "click", "no_button", "unknown_screen"]
    click_at: tuple[int, int] | None = None
    match_score: float | None = None
    success: bool = False


def identify_screen(image: np.ndarray) -> str | None:
    """Return 'base' / 'world' / `None` based on which toggle icon is visible."""
    if templates.find(image, templates.cached_template(T_TO_WORLD), MATCH_THRESHOLD) is not None:
        return "base"
    if templates.find(image, templates.cached_template(T_TO_BASE), MATCH_THRESHOLD) is not None:
        return "world"
    return None


def go_to(target: Screen, hwnd: int, *, wait_after: float = 1.5) -> NavigateResult:
    """Navigate to the requested screen. No-op if already there."""
    before_img = grab(hwnd)
    current = identify_screen(before_img)

    if current == target:
        return NavigateResult(target=target, before=current, after=current, action="noop", success=True)
    if current is None:
        return NavigateResult(target=target, before=None, after=None, action="unknown_screen", success=False)

    template_path = T_TO_WORLD if target == "world" else T_TO_BASE
    match = templates.find(before_img, templates.cached_template(template_path), MATCH_THRESHOLD)
    if match is None:
        return NavigateResult(target=target, before=current, after=current, action="no_button", success=False)

    cx, cy = match.center
    click(hwnd, cx, cy, mode="foreground")
    time.sleep(wait_after)

    after_img = grab(hwnd)
    new = identify_screen(after_img)
    return NavigateResult(
        target=target,
        before=current,
        after=new,
        action="click",
        click_at=(cx, cy),
        match_score=match.score,
        success=(new == target),
    )
