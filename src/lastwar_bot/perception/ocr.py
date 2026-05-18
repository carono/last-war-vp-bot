"""OCR primitive backed by RapidOCR (ONNX models, no system deps).

Used by the DSL ``READ_TEXT`` statement to extract text from a region
of the captured screen. The OCR engine is lazy-loaded on first call —
it carries a few-hundred-MB model footprint, so we don't pay the cost
unless a script actually needs text.

For Last War's UI, text is usually a single-line label (name, level
number, server tag). The default ``read_text`` joins every detected
text box with a space, which is fine for short labels. If you need
structured output (per-box positions), use ``read_text_boxes``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from rapidocr_onnxruntime import RapidOCR  # noqa: F401

_ocr_instance: "RapidOCR | None" = None


def _ocr() -> "RapidOCR":
    """Return the cached RapidOCR instance, loading it on first access."""
    global _ocr_instance
    if _ocr_instance is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_instance = RapidOCR()
    return _ocr_instance


def read_text(
    image: np.ndarray,
    region: tuple[int, int, int, int] | None = None,
) -> str:
    """OCR a region of `image` and return concatenated text.

    `region` is `(x, y, w, h)` in image coordinates. If None, the whole
    image is OCRed.
    """
    crop = _crop(image, region) if region else image
    boxes = read_text_boxes(crop)
    return " ".join(text for _, text, _ in boxes).strip()


def read_text_boxes(
    image: np.ndarray,
) -> list[tuple[list[tuple[float, float]], str, float]]:
    """Return raw OCR boxes: [(polygon, text, confidence), ...].

    Useful when caller needs positional information (e.g. to align
    detected text against a known layout).
    """
    result, _elapsed = _ocr()(image)
    if not result:
        return []
    out: list[tuple[list[tuple[float, float]], str, float]] = []
    for item in result:
        if len(item) >= 3:
            poly, text, conf = item[0], item[1], float(item[2])
            out.append((poly, str(text).strip(), conf))
    return out


def _crop(image: np.ndarray, region: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = region
    h_img, w_img = image.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    if x2 <= x1 or y2 <= y1:
        return image[0:0, 0:0]
    return image[y1:y2, x1:x2]
