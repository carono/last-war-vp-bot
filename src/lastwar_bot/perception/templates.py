"""Template matching utilities (OpenCV).

The bot's fast perception path: given a screenshot and a small reference
PNG of a known UI element, find where (and whether) the element appears.
Used to detect screens, locate buttons for clicking, and verify state
transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


@dataclass(slots=True)
class Match:
    top_left: tuple[int, int]
    size: tuple[int, int]  # (width, height)
    score: float

    @property
    def center(self) -> tuple[int, int]:
        x, y = self.top_left
        w, h = self.size
        return (x + w // 2, y + h // 2)


def load_template(path: Path | str) -> np.ndarray:
    """Load a PNG/JPEG template as a BGR ndarray."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Template not found or unreadable: {path}")
    return img


@lru_cache(maxsize=64)
def _cached(path_str: str) -> np.ndarray:
    return load_template(path_str)


def cached_template(path: Path | str) -> np.ndarray:
    """Load and cache a template (templates are immutable during a session)."""
    return _cached(str(path))


def find(image: np.ndarray, template: np.ndarray, threshold: float = 0.85) -> Match | None:
    """Find the single best match for `template` in `image`.

    Returns `None` if the best score is below `threshold`. Uses
    `cv2.TM_CCOEFF_NORMED`; threshold 0.85 is a reasonable default for
    pristine UI captures, can be lowered for noisier targets.
    """
    if image.dtype != template.dtype:
        raise ValueError(f"Image and template dtypes differ: {image.dtype} vs {template.dtype}")
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    th, tw = template.shape[:2]
    return Match(top_left=tuple(max_loc), size=(tw, th), score=float(max_val))
