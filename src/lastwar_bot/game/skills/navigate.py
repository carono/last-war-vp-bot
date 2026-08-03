"""Navigate between the Base and World screens via the bottom-right toggle.

Detection uses SIFT feature matching (see `perception.features.SceneIndex`)
rather than per-pixel template matching. SIFT survives the game's UI
re-rendering at different window sizes, so a single set of templates
captured at a "minimum supported" window size keeps matching at larger
windows up to fullscreen. The minimum is currently ~1638x1026; smaller
windows may still fail because the icons rasterise too small for SIFT
to extract enough keypoints.

Detection strategy (chrome-gated):

    1. Look for the inventory icon (the right-column UI chrome's proxy).
       Inliers >= INVENTORY_MIN_INLIERS  =>  chrome present.
    2. If chrome present:
         - Try toggle_to_world (visible on Base) and toggle_to_base
           (visible on World). Whichever scores more inliers >= TOGGLE_MIN
           identifies the screen.
    3. If chrome absent:
         - Try world_zoom_reset. >= ZOOM_RESET_MIN inliers  =>  World (max zoom).
         - Otherwise the screen is unknown (loading, modal, intro, ...).

Multiple template variants per logical button are still supported and
used (one captured at a baseline window size, plus fullscreen captures).
SIFT picks the best across variants automatically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import numpy as np

from ...inputs import click
from ...perception import features
from ...perception.capture import grab

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_T_TO_WORLD: list[Path] = [
    TEMPLATES_DIR / "toggle_to_world.png",
    TEMPLATES_DIR / "toggle_to_world_fs.png",
]
_T_TO_BASE: list[Path] = [
    TEMPLATES_DIR / "toggle_to_base.png",
    TEMPLATES_DIR / "toggle_to_base_fs.png",
]
_T_ZOOM_RESET: list[Path] = [
    TEMPLATES_DIR / "world_zoom_reset.png",
]
_T_INVENTORY: list[Path] = [
    TEMPLATES_DIR / "inventory.png",
    TEMPLATES_DIR / "inventory_fs.png",
    TEMPLATES_DIR / "inventory_world_fs.png",
]

# Inliers thresholds, empirically tuned (see `perception.features.default_sift`):
# - chrome (inventory): real matches 14..47 across all tested sizes;
#   world_far drops to ~5. Pick a margin between these two clusters.
# - toggles / zoom_reset: real matches 6..22; cross-screen false positives
#   for to_world vs zoom_reset (same map+pin icon) cap at ~14 — chrome-gate
#   handles them. zoom_reset is only consulted when chrome is absent.
INVENTORY_MIN_INLIERS = 10
TOGGLE_MIN_INLIERS = 4
ZOOM_RESET_MIN_INLIERS = 10

Screen = Literal["base", "world"]


@dataclass(slots=True)
class NavigateResult:
    target: Screen
    before: str | None
    after: str | None
    action: Literal["noop", "click", "no_button", "unknown_screen"]
    click_at: tuple[int, int] | None = None
    match_inliers: int | None = None
    attempts: int = 0
    success: bool = False


#: Said once per process when a template is missing. The templates are NOT shipped —
#: see the note in :data:`TEMPLATES_DIR`'s directory README — so «missing» is the
#: ordinary state of a fresh clone, not a corrupted install.
_warned_missing: set[str] = set()


def _best_of(scene: features.SceneIndex, paths: Iterable[Path]) -> features.SiftMatch | None:
    """Highest-inliers SIFT match across multiple template variants.

    **A template that is not on disk is skipped, not raised on.** The cropped UI
    images are git-ignored (they are screenshots of somebody's game), so a fresh
    clone has none of them and every vision path here has to degrade to «I cannot
    tell» rather than to a `FileNotFoundError` from three frames down. The
    difference matters: the first is a feature the user has not set up, the second
    looks like the bot is broken.
    """
    best: features.SiftMatch | None = None
    for path in paths:
        if not path.exists():
            if str(path) not in _warned_missing:
                _warned_missing.add(str(path))
                print(f"[navigate] no template {path.name} — screen detection is off "
                      f"until it is cropped; see {TEMPLATES_DIR / 'README.md'}")
            continue
        m = scene.find_sift(path)
        if m is None:
            continue
        if best is None or m.inliers > best.inliers:
            best = m
    return best


def chrome_visible(image: np.ndarray) -> bool:
    """True if the persistent right-column UI is on screen."""
    scene = features.SceneIndex(image)
    m = _best_of(scene, _T_INVENTORY)
    return m is not None and m.inliers >= INVENTORY_MIN_INLIERS


def _identify(scene: features.SceneIndex) -> str | None:
    inv = _best_of(scene, _T_INVENTORY)
    chrome = inv is not None and inv.inliers >= INVENTORY_MIN_INLIERS

    if chrome:
        m_world = _best_of(scene, _T_TO_WORLD)
        m_base = _best_of(scene, _T_TO_BASE)
        w_inl = m_world.inliers if m_world else 0
        b_inl = m_base.inliers if m_base else 0
        if max(w_inl, b_inl) < TOGGLE_MIN_INLIERS:
            return None
        return "base" if w_inl > b_inl else "world"
    # Chrome absent — only known regime is max-zoom world.
    zr = _best_of(scene, _T_ZOOM_RESET)
    if zr is not None and zr.inliers >= ZOOM_RESET_MIN_INLIERS:
        return "world"
    return None


def identify_screen(image: np.ndarray) -> str | None:
    """Return 'base' / 'world' / None for the current screen (SIFT-based)."""
    return _identify(features.SceneIndex(image))


def _pick_next_action(scene: features.SceneIndex, target: Screen) -> features.SiftMatch | None:
    """Highest-priority clickable element that advances toward `target`."""
    if target == "world":
        return _best_of(scene, _T_TO_WORLD)
    # target == "base"
    direct = _best_of(scene, _T_TO_BASE)
    if direct is not None and direct.inliers >= TOGGLE_MIN_INLIERS:
        return direct
    # Preparatory step from max-zoom world: reset zoom first, then retry.
    zr = _best_of(scene, _T_ZOOM_RESET)
    if zr is not None and zr.inliers >= ZOOM_RESET_MIN_INLIERS:
        return zr
    return None


def _settle(hwnd: int, *, timeout: float, poll: float) -> tuple[str | None, np.ndarray]:
    """Poll identify_screen until a known screen appears or timeout elapses."""
    deadline = time.monotonic() + timeout
    img = grab(hwnd)
    while True:
        scene = features.SceneIndex(img)
        screen = _identify(scene)
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

    Multi-step paths (max-zoom world -> zoom reset -> toggle_to_base ->
    base) are covered by the retry budget. After each click we re-detect
    the screen via SIFT, polling for up to ``settle_timeout`` seconds to
    ride out transition animations.
    """
    initial: str | None = None
    last_click: tuple[int, int] | None = None
    last_inliers: int | None = None
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
                match_inliers=last_inliers,
                attempts=attempt,
                success=True,
            )
        if current is None:
            return NavigateResult(
                target=target, before=initial, after=None, action="unknown_screen",
                attempts=attempt, success=False,
            )

        scene = features.SceneIndex(before_img)
        action = _pick_next_action(scene, target)
        if action is None:
            return NavigateResult(
                target=target, before=initial, after=current, action="no_button",
                attempts=attempt, success=False,
            )

        cx, cy = action.center
        click(hwnd, cx, cy, mode="foreground")
        last_click = (cx, cy)
        last_inliers = action.inliers

    final, _ = _settle(hwnd, timeout=settle_timeout, poll=poll_interval)
    return NavigateResult(
        target=target,
        before=initial,
        after=final,
        action="click",
        click_at=last_click,
        match_inliers=last_inliers,
        attempts=attempt,
        success=(final == target),
    )
