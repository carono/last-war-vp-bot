"""Detect red notification dots on the game UI.

Red dots appear in the corner of buttons / tabs whenever something
behind that button is new or ready to collect. They are the bot's
primary "is there work to do" cue (see docs/game/overview.md).

Detection uses HSV colour thresholding — independent of window size and
much faster than template matching. Each candidate region is filtered by
area and circularity so that long red strips (health bars, fire effects)
are rejected.

CLI:
    python -m lastwar_bot.perception.red_dots [--out path] [--source image]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(slots=True)
class RedDot:
    center: tuple[int, int]
    bbox: tuple[int, int, int, int]  # x, y, w, h
    area: float
    circularity: float


# HSV thresholds for saturated bright red.
# Red wraps around the hue circle, so two ranges are unioned.
_RED_LOW1 = np.array([0, 120, 110], dtype=np.uint8)
_RED_HIGH1 = np.array([10, 255, 255], dtype=np.uint8)
_RED_LOW2 = np.array([170, 120, 110], dtype=np.uint8)
_RED_HIGH2 = np.array([180, 255, 255], dtype=np.uint8)


def find_red_dots(
    image: np.ndarray,
    *,
    min_area: float = 60.0,
    max_area: float = 200.0,
    min_circularity: float = 0.85,
    edge_margin: int | None = None,
) -> list[RedDot]:
    """Find red notification dots in `image` (BGR).

    Returns dots that pass area and circularity filters. Searches the
    whole image by default — attention markers can appear anywhere,
    including in the centre of the screen when a modal is open and the
    dot sits on one of its tabs. If `edge_margin` is given, only the
    perimeter strip of that thickness is searched (use with care; only
    valid when we know no modal is on screen).

    Defaults are tuned empirically against a live 1638×1026 capture:
    real attention dots score area 96–126 px², circularity 0.88–0.94.
    Tighter than these would drop borderline real dots; looser starts
    picking up other red UI (X-close buttons, sale badges, build-progress
    markers, chat/rally count bubbles).
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, _RED_LOW1, _RED_HIGH1),
        cv2.inRange(hsv, _RED_LOW2, _RED_HIGH2),
    )

    if edge_margin is not None and edge_margin > 0:
        h, w = mask.shape[:2]
        m = min(edge_margin, h // 2, w // 2)
        # Zero out the central rectangle, keep only the outer frame.
        mask[m: h - m, m: w - m] = 0

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dots: list[RedDot] = []
    for c in contours:
        area = float(cv2.contourArea(c))
        if not (min_area <= area <= max_area):
            continue
        perimeter = float(cv2.arcLength(c, True))
        if perimeter <= 0.0:
            continue
        circularity = 4.0 * np.pi * area / (perimeter * perimeter)
        if circularity < min_circularity:
            continue
        x, y, w, h = cv2.boundingRect(c)
        cx, cy = x + w // 2, y + h // 2
        dots.append(RedDot(center=(cx, cy), bbox=(x, y, w, h), area=area, circularity=circularity))
    return dots


def annotate(image: np.ndarray, dots: list[RedDot]) -> np.ndarray:
    """Draw a circle and an index over each detected dot."""
    out = image.copy()
    for i, d in enumerate(dots, 1):
        x, y, w, h = d.bbox
        radius = max(w, h) // 2 + 6
        cv2.circle(out, d.center, radius, (0, 255, 0), 2)
        label = f"#{i}"
        cv2.putText(
            out, label, (x, max(0, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA,
        )
    return out


def _main() -> int:
    import argparse

    from .capture import find_window, grab

    parser = argparse.ArgumentParser(description="Detect red notification dots.")
    parser.add_argument("--source", help="PNG file instead of live capture", default=None)
    parser.add_argument("--out", default="screenshots/red_dots.png", help="Annotated output path")
    parser.add_argument("--title", default="Last War-Survival Game")
    parser.add_argument("--process", default="LastWar.exe")
    parser.add_argument("--min-area", type=float, default=60.0)
    parser.add_argument("--max-area", type=float, default=200.0)
    parser.add_argument("--min-circ", type=float, default=0.85)
    parser.add_argument(
        "--edge-margin", type=int, default=0,
        help="If >0, search only the outer N-pixel strip. Default 0 = whole image, "
             "required for modal contexts where attention markers can be centred.",
    )
    args = parser.parse_args()

    if args.source:
        img = cv2.imread(args.source)
        if img is None:
            print(f"Cannot read {args.source}", file=sys.stderr)
            return 2
        src_label = args.source
    else:
        info = find_window(args.title, args.process or None)
        img = grab(info.hwnd)
        src_label = f"live capture ({info.title!r}, hwnd=0x{info.hwnd:x})"

    height, width = img.shape[:2]
    print(f"Source: {src_label}, {width}x{height}")

    dots = find_red_dots(
        img,
        min_area=args.min_area,
        max_area=args.max_area,
        min_circularity=args.min_circ,
        edge_margin=args.edge_margin if args.edge_margin > 0 else None,
    )
    print(f"Detected {len(dots)} red dot(s):")
    for i, d in enumerate(dots, 1):
        print(f"  #{i} center={d.center}  bbox={d.bbox}  area={d.area:.1f}  circ={d.circularity:.2f}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    annotated = annotate(img, dots)
    cv2.imwrite(str(out_path), annotated)
    print(f"Saved annotated -> {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
