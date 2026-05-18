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


def _nms(boxes: np.ndarray, scores: np.ndarray, overlap_threshold: float) -> np.ndarray:
    """Non-Maximum Suppression. Returns indices of boxes to keep.

    Sorts by score desc, keeps the top box, discards any later box whose
    intersection-over-area against an already-kept box exceeds the
    overlap threshold.
    """
    if len(boxes) == 0:
        return np.empty(0, dtype=int)

    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = np.argsort(scores)[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)
        overlap = (w * h) / area[rest]
        order = rest[overlap <= overlap_threshold]
    return np.array(keep, dtype=int)


def find_all(
    image: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.85,
    *,
    max_matches: int = 0,
    nms_threshold: float = 0.3,
) -> list[Match]:
    """Find every place where `template` matches `image` above `threshold`.

    Detections are deduplicated with NMS (`nms_threshold` is the maximum
    allowed IoU-like overlap before the lower-scoring detection is
    dropped). Returns matches sorted by score, highest first. `max_matches=0`
    means unlimited; otherwise truncated to the best N.

    Use this when the same template is expected to appear at multiple
    positions in the image (resource trucks on the world map, alliance
    bases, monster markers, ...). For a single best target, prefer `find`.
    """
    if image.dtype != template.dtype:
        raise ValueError(f"Image and template dtypes differ: {image.dtype} vs {template.dtype}")
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    th, tw = template.shape[:2]
    ys, xs = np.where(result >= threshold)
    if len(ys) == 0:
        return []

    boxes = np.column_stack((xs, ys, xs + tw - 1, ys + th - 1)).astype(np.int32)
    scores = result[ys, xs].astype(np.float32)

    keep = _nms(boxes, scores, nms_threshold)
    boxes = boxes[keep]
    scores = scores[keep]

    order = np.argsort(scores)[::-1]
    boxes = boxes[order]
    scores = scores[order]

    if max_matches > 0:
        boxes = boxes[:max_matches]
        scores = scores[:max_matches]

    return [
        Match(top_left=(int(x1), int(y1)), size=(tw, th), score=float(s))
        for (x1, y1, _, _), s in zip(boxes, scores)
    ]
