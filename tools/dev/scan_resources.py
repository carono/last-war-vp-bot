"""Benchmark: find all res_* resource icons on a live game screenshot.

Usage:
    python tools/scan_resources.py [--out results/scan.png] [--threshold 0.80]
    python tools/scan_resources.py --sift

Two modes:
  - Default: fast NCC template matching via perception.templates.find_all
  - --sift:  SIFT+FLANN via perception.features.SceneIndex (more robust, slower)

Output: annotated PNG with colored bounding boxes + console timing breakdown.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# ── repo path wiring ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lastwar_bot.perception.capture import find_window, grab, WindowNotFoundError
from lastwar_bot.perception import templates as tpl_mod
from lastwar_bot.perception import features as feat_mod

TEMPLATES_DIR = ROOT / "src" / "lastwar_bot" / "game" / "templates"

# Distinct BGR colours per template so boxes don't blend together.
PALETTE = [
    (0, 255, 0),    # green
    (0, 128, 255),  # orange
    (255, 0, 255),  # magenta
    (0, 255, 255),  # yellow
    (255, 128, 0),  # blue-ish
    (128, 0, 255),  # purple
    (0, 200, 100),  # teal
]


def scan_ncc(image: np.ndarray, paths: list[Path], threshold: float) -> dict[str, list]:
    results: dict[str, list] = {}
    for path in paths:
        tpl = tpl_mod.cached_template(path)
        matches = tpl_mod.find_all(image, tpl, threshold=threshold)
        results[path.stem] = matches
    return results


def scan_ncc_multiscale(
    image: np.ndarray,
    paths: list[Path],
    threshold: float,
    scale_min: float,
    scale_max: float,
    scale_step: float,
) -> dict[str, list]:
    scales = np.arange(scale_min, scale_max + scale_step * 0.5, scale_step).tolist()
    img_h, img_w = image.shape[:2]
    results: dict[str, list] = {}

    for path in paths:
        raw = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if raw is None:
            results[path.stem] = []
            continue

        orig_h, orig_w = raw.shape[:2]
        all_boxes: list[tuple] = []
        all_scores: list[float] = []
        all_sizes: list[tuple] = []

        for scale in scales:
            new_w = max(4, int(round(orig_w * scale)))
            new_h = max(4, int(round(orig_h * scale)))
            if new_w >= img_w or new_h >= img_h:
                continue
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            tpl = cv2.resize(raw, (new_w, new_h), interpolation=interp)

            res = cv2.matchTemplate(image, tpl, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= threshold)
            if len(ys) == 0:
                continue

            scores = res[ys, xs].astype(np.float32)
            for x, y, s in zip(xs.tolist(), ys.tolist(), scores.tolist()):
                all_boxes.append((x, y, x + new_w - 1, y + new_h - 1))
                all_scores.append(float(s))
                all_sizes.append((new_w, new_h))

        if not all_boxes:
            results[path.stem] = []
            continue

        boxes_arr = np.array(all_boxes, dtype=np.int32)
        scores_arr = np.array(all_scores, dtype=np.float32)
        keep = tpl_mod._nms(boxes_arr, scores_arr, 0.3)

        matches = []
        for i in keep:
            x1, y1 = all_boxes[i][0], all_boxes[i][1]
            w, h = all_sizes[i]
            s = all_scores[i]
            matches.append(tpl_mod.Match(top_left=(x1, y1), size=(w, h), score=s))
        matches.sort(key=lambda m: m.score, reverse=True)
        results[path.stem] = matches

    return results


def scan_sift(image: np.ndarray, paths: list[Path]) -> dict[str, list]:
    scene = feat_mod.SceneIndex(image)
    results: dict[str, list] = {}
    for path in paths:
        m = scene.find_sift(path, min_inliers=4)
        results[path.stem] = [m] if m is not None else []
    return results


def annotate(image: np.ndarray, results: dict[str, list], names: list[str]) -> np.ndarray:
    out = image.copy()
    for i, name in enumerate(names):
        colour = PALETTE[i % len(PALETTE)]
        for m in results.get(name, []):
            tl = m.top_left
            br = (tl[0] + m.size[0], tl[1] + m.size[1]) if hasattr(m, "size") else m.bottom_right
            cv2.rectangle(out, tl, br, colour, 2)
            cv2.circle(out, m.center, 6, colour, -1)
            label = f"{name.replace('res_', '')}:{getattr(m, 'score', getattr(m, 'inliers', '?')):.2f}"
            lx, ly = tl[0], max(0, tl[1] - 6)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(out, (lx, ly - th - 2), (lx + tw + 2, ly + 2), colour, -1)
            cv2.putText(out, label, (lx + 1, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Resource icon scanner benchmark")
    parser.add_argument("--out", type=Path, default=Path("results/scan_resources.png"))
    parser.add_argument("--threshold", type=float, default=0.80,
                        help="NCC match threshold (default 0.80)")
    parser.add_argument("--sift", action="store_true",
                        help="Use SIFT+FLANN instead of NCC template matching")
    parser.add_argument("--screenshot", type=Path, default=None,
                        help="Use an existing PNG instead of capturing the game window")
    parser.add_argument("--save-raw", type=Path, default=None,
                        help="Save the captured screenshot as a raw PNG before scanning")
    parser.add_argument("--only", nargs="+", metavar="NAME",
                        help="Scan only these template stems, e.g. --only res_gold res_oil")
    parser.add_argument("--multiscale", action="store_true",
                        help="Search across multiple scales (finds smaller/larger copies of template)")
    parser.add_argument("--scale-min", type=float, default=0.25)
    parser.add_argument("--scale-max", type=float, default=1.3)
    parser.add_argument("--scale-step", type=float, default=0.05)
    args = parser.parse_args()

    # ── 1. Capture ────────────────────────────────────────────────────────────
    if args.screenshot:
        print(f"Loading screenshot from {args.screenshot} …")
        image = cv2.imread(str(args.screenshot))
        if image is None:
            print(f"ERROR: cannot read {args.screenshot}", file=sys.stderr)
            return 2
    else:
        print("Connecting to game window …")
        t0 = time.perf_counter()
        try:
            info = find_window("Last War-Survival Game", "LastWar.exe")
        except WindowNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        image = grab(info.hwnd)
        t_cap = time.perf_counter() - t0
        print(f"  Captured {image.shape[1]}x{image.shape[0]} px in {t_cap*1000:.1f} ms")
        if args.save_raw:
            args.save_raw.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(args.save_raw), image)
            print(f"  Raw saved: {args.save_raw.resolve()}")

    # ── 2. Collect templates ──────────────────────────────────────────────────
    paths = sorted(TEMPLATES_DIR.glob("res_*.png"))
    if args.only:
        paths = [p for p in paths if p.stem in args.only]
    if not paths:
        print("ERROR: no res_*.png templates found", file=sys.stderr)
        return 2
    print(f"\nTemplates ({len(paths)}): {[p.stem for p in paths]}")

    # ── 3. Search ─────────────────────────────────────────────────────────────
    if args.sift:
        mode = "SIFT+FLANN"
    elif args.multiscale:
        mode = f"NCC multiscale {args.scale_min:.2f}-{args.scale_max:.2f} step={args.scale_step} threshold={args.threshold}"
    else:
        mode = f"NCC threshold={args.threshold}"
    print(f"\nSearching with {mode} …")

    t1 = time.perf_counter()
    if args.sift:
        results = scan_sift(image, paths)
    elif args.multiscale:
        results = scan_ncc_multiscale(
            image, paths, args.threshold,
            args.scale_min, args.scale_max, args.scale_step,
        )
    else:
        results = scan_ncc(image, paths, args.threshold)
    t_search = time.perf_counter() - t1

    # ── 4. Report ─────────────────────────────────────────────────────────────
    total_hits = 0
    print(f"\n{'Template':<18} {'Hits':>5}  Details")
    print("-" * 60)
    for path in paths:
        name = path.stem
        hits = results[name]
        total_hits += len(hits)
        if hits:
            detail = "  ".join(
                f"center={m.center} score={getattr(m,'score',getattr(m,'inliers','?')):.2f}"
                for m in hits
            )
        else:
            detail = "—"
        print(f"  {name:<16} {len(hits):>5}  {detail}")
    print("-" * 60)
    print(f"  {'TOTAL':<16} {total_hits:>5}")
    print(f"\n  Search time : {t_search*1000:.1f} ms")
    print(f"  Templates   : {len(paths)}")
    print(f"  Avg per tpl : {t_search/len(paths)*1000:.1f} ms")

    # ── 5. Annotate & save ────────────────────────────────────────────────────
    names = [p.stem for p in paths]
    annotated = annotate(image, results, names)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), annotated)
    print(f"\nAnnotated image saved: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
