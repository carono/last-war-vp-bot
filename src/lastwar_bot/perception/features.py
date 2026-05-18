"""Feature-based object detection (ORB + RANSAC homography).

For finding objects in the game world (player bases, monsters, resource
nodes, etc.) where:

- Position is unknown.
- Scale and rotation may vary between captures.
- Background varies significantly.

NOT suitable for small flat UI icons — ORB needs corners/edges, and tiny
or smooth-shaded icons (<64x64, uniform colour) yield zero keypoints. For
UI, use template matching from `perception.templates`.

CLI:
    python -m lastwar_bot.perception.features template.png image.png [--save out.png]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


@dataclass(slots=True)
class FeatureMatch:
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]
    center: tuple[int, int]
    inliers: int                       # RANSAC-confirmed pairs (strongest signal)
    good_matches: int                  # Lowe's-ratio survivors
    template_keypoints: int            # raw keypoints found in the template
    homography: np.ndarray | None = None  # populated by `find()` (ORB path) only


def _orb(nfeatures: int) -> cv2.ORB:
    return cv2.ORB_create(nfeatures=nfeatures)


_DEFAULT_SIFT: cv2.SIFT | None = None
_DEFAULT_FLANN: cv2.FlannBasedMatcher | None = None
_SIFT_TEMPLATE_CACHE: dict[str, tuple[np.ndarray, tuple, np.ndarray | None]] = {}


def default_sift() -> cv2.SIFT:
    """Lazy-initialised SIFT detector tuned for small UI icons.

    ``contrastThreshold=0.02`` (default 0.04) and ``edgeThreshold=20``
    (default 10) loosen the keypoint selection enough to find features
    on flat-shaded buttons rendered at different resolutions. Empirically
    this is what makes a 60x40 toggle template still match on a
    1920x1200 fullscreen capture.
    """
    global _DEFAULT_SIFT
    if _DEFAULT_SIFT is None:
        _DEFAULT_SIFT = cv2.SIFT_create(nfeatures=5000, contrastThreshold=0.02, edgeThreshold=20)
    return _DEFAULT_SIFT


def _default_flann() -> cv2.FlannBasedMatcher:
    global _DEFAULT_FLANN
    if _DEFAULT_FLANN is None:
        _DEFAULT_FLANN = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=50))
    return _DEFAULT_FLANN


def load_template(path: Path | str) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Template not found or unreadable: {path}")
    return img


@lru_cache(maxsize=64)
def _cached(path_str: str) -> np.ndarray:
    return load_template(path_str)


def cached_template(path: Path | str) -> np.ndarray:
    return _cached(str(path))


def _sift_template_features(path: Path | str):
    """Compute (and cache) SIFT keypoints+descriptors for a template path."""
    key = str(path)
    cached = _SIFT_TEMPLATE_CACHE.get(key)
    if cached is not None:
        return cached
    img = load_template(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    kp, des = default_sift().detectAndCompute(gray, None)
    entry = (img, kp, des)
    _SIFT_TEMPLATE_CACHE[key] = entry
    return entry


def find(
    image: np.ndarray,
    template: np.ndarray,
    *,
    nfeatures: int = 2000,
    ratio: float = 0.75,
    ransac_threshold: float = 5.0,
    min_inliers: int = 8,
) -> FeatureMatch | None:
    """Find a single instance of `template` in `image`.

    Returns None when ORB can't extract enough features from either
    image, when too few pairs survive Lowe's ratio test, or when RANSAC
    can't fit a stable homography.
    """
    orb = _orb(nfeatures)
    kp1, des1 = orb.detectAndCompute(template, None)
    kp2, des2 = orb.detectAndCompute(image, None)

    if des1 is None or des2 is None:
        return None
    if len(kp1) < min_inliers or len(kp2) < min_inliers:
        return None

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    pairs = bf.knnMatch(des1, des2, k=2)

    good = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < ratio * n.distance:
            good.append(m)
    if len(good) < min_inliers:
        return None

    src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, ransac_threshold)
    if H is None or mask is None:
        return None

    inliers = int(mask.sum())
    if inliers < min_inliers:
        return None

    h, w = template.shape[:2]
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
    x1, y1 = projected.min(axis=0).astype(int)
    x2, y2 = projected.max(axis=0).astype(int)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

    return FeatureMatch(
        top_left=(int(x1), int(y1)),
        bottom_right=(int(x2), int(y2)),
        center=(int(cx), int(cy)),
        inliers=inliers,
        good_matches=len(good),
        template_keypoints=len(kp1),
        homography=H,
    )


@dataclass(slots=True)
class SiftMatch:
    """A single SIFT-RANSAC match. `inliers` is the strongest signal."""
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]
    center: tuple[int, int]
    inliers: int
    good_matches: int
    template_keypoints: int


class SceneIndex:
    """Pre-computes SIFT keypoints/descriptors for an image so that
    repeated template lookups against the same scene share the cost.

    Typical use:

        scene = SceneIndex(captured_frame)
        if scene.find_sift(inventory_path).inliers >= 10:
            ...
    """

    def __init__(self, image: np.ndarray) -> None:
        self.image = image
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        self._sift = default_sift()
        self._kp, self._des = self._sift.detectAndCompute(gray, None)

    def find_sift(
        self,
        template_path: Path | str,
        *,
        ratio: float = 0.8,
        ransac_threshold: float = 8.0,
        min_inliers: int = 4,
    ) -> SiftMatch | None:
        """Match the cached scene against the template at `template_path`."""
        if self._des is None or len(self._kp) < 4:
            return None
        tpl_img, kp1, des1 = _sift_template_features(template_path)
        if des1 is None or len(kp1) < 4:
            return None

        flann = _default_flann()
        try:
            pairs = flann.knnMatch(des1, self._des, k=2)
        except cv2.error:
            return None
        good = []
        for pair in pairs:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < ratio * n.distance:
                good.append(m)
        # estimateAffinePartial2D needs at least 2 correspondences; we
        # require 3 for a healthy RANSAC and let the caller demand more.
        if len(good) < max(min_inliers, 3):
            return None

        src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([self._kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        # Use a partial affine fit (translation + uniform scale + rotation —
        # 4 parameters) instead of a full homography (8 params, projective).
        # The game's UI doesn't introduce perspective distortion; a
        # homography fitted on only a handful of inliers overfits and
        # produces wildly stretched bounding boxes (observed: a 33x33
        # template projected to 59x30, shifting the click point by ~50 px).
        M, mask = cv2.estimateAffinePartial2D(
            src, dst,
            method=cv2.RANSAC,
            ransacReprojThreshold=ransac_threshold,
        )
        if M is None or mask is None:
            return None
        inliers = int(mask.sum())
        if inliers < min_inliers:
            return None

        h, w = tpl_img.shape[:2]
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        projected = cv2.transform(corners, M).reshape(-1, 2)
        x1, y1 = projected.min(axis=0).astype(int)
        x2, y2 = projected.max(axis=0).astype(int)
        # Centre = direct transform of the template midpoint. Identical to
        # bbox-centre under affine, but spelled out so future tweaks don't
        # accidentally compute it from a skewed bounding box.
        mid = np.float32([[[w / 2.0, h / 2.0]]])
        mid_proj = cv2.transform(mid, M).reshape(2)
        cx, cy = int(round(mid_proj[0])), int(round(mid_proj[1]))

        # Sanity-check the homography. A degenerate fit on too few inliers
        # can project the template's corners to wild locations — reject if:
        #  - the projected centre lands outside the scene image
        #  - the projected bounding box is degenerate or unreasonably scaled
        img_h, img_w = self.image.shape[:2]
        if not (0 <= cx < img_w and 0 <= cy < img_h):
            return None
        proj_w = max(1, x2 - x1)
        proj_h = max(1, y2 - y1)
        scale_x = proj_w / max(w, 1)
        scale_y = proj_h / max(h, 1)
        if scale_x < 0.3 or scale_x > 5.0 or scale_y < 0.3 or scale_y > 5.0:
            return None

        return SiftMatch(
            top_left=(int(x1), int(y1)),
            bottom_right=(int(x2), int(y2)),
            center=(cx, cy),
            inliers=inliers,
            good_matches=len(good),
            template_keypoints=len(kp1),
        )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="ORB-based feature matching.")
    parser.add_argument("template", help="Template image path")
    parser.add_argument("image", help="Image to search in")
    parser.add_argument("--save", help="Save annotated image with bbox", default=None)
    parser.add_argument("--nfeatures", type=int, default=2000)
    parser.add_argument("--min-inliers", type=int, default=8)
    parser.add_argument("--ratio", type=float, default=0.75)
    args = parser.parse_args()

    tpl = load_template(args.template)
    img = load_template(args.image)
    print(f"Template: {tpl.shape[1]}x{tpl.shape[0]}")
    print(f"Image:    {img.shape[1]}x{img.shape[0]}")

    match = find(img, tpl, nfeatures=args.nfeatures, ratio=args.ratio, min_inliers=args.min_inliers)
    if match is None:
        print("No match.")
        return 1

    print(
        f"Match: center={match.center} bbox={match.top_left}->{match.bottom_right}\n"
        f"  inliers={match.inliers} / good={match.good_matches} / template_kp={match.template_keypoints}"
    )
    if args.save:
        out = img.copy()
        cv2.rectangle(out, match.top_left, match.bottom_right, (0, 255, 0), 3)
        cv2.circle(out, match.center, 8, (0, 0, 255), 2)
        cv2.putText(
            out, f"inliers={match.inliers}", (match.top_left[0], max(0, match.top_left[1] - 8)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
        )
        cv2.imwrite(args.save, out)
        print(f"Saved -> {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
