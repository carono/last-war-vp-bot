"""Region-picker window used to calibrate READ_TEXT regions and crop templates.

Workflow:

1. Caller (UI Debug tab) captures a frame via ``perception.capture.grab``.
2. Opens ``RegionPickerWindow(parent, image_bgr)``.
3. Operator drags a rectangle on the displayed image.
4. Operator either:
   - clicks **Copy coords** -> ``(x, y, w, h)`` lands in the clipboard,
     ready to paste into a ``READ_TEXT (x, y, w, h) INTO ...`` line;
   - clicks **Save as template...** -> the cropped region is written
     as a PNG under ``src/lastwar_bot/game/templates/``.

Coordinates are reported in ORIGINAL image space — if the image is
scaled down to fit the screen, the displayed rectangle is rescaled
back to original pixels before being copied / saved.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

TEMPLATES_DIR = Path(__file__).parent / "game" / "templates"

# Maximum on-screen size of the preview. Anything larger is scaled down
# (uniform aspect-ratio preserving). The user still selects in original
# pixels — the scale factor is undone before reporting coords.
_MAX_DISPLAY_W = 1600
_MAX_DISPLAY_H = 900


class RegionPickerWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, image_bgr: np.ndarray) -> None:
        super().__init__(parent)
        self.title("Pick a region")
        self.transient(parent)

        self._original_bgr = image_bgr
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)

        self._scale = min(
            _MAX_DISPLAY_W / pil_img.width,
            _MAX_DISPLAY_H / pil_img.height,
            1.0,
        )
        if self._scale < 1.0:
            display_size = (
                int(round(pil_img.width * self._scale)),
                int(round(pil_img.height * self._scale)),
            )
            try:
                resample = Image.Resampling.LANCZOS  # Pillow >= 10
            except AttributeError:
                resample = Image.LANCZOS
            display_img = pil_img.resize(display_size, resample)
        else:
            display_img = pil_img

        self._photo = ImageTk.PhotoImage(display_img)

        self._canvas = tk.Canvas(
            self,
            width=display_img.width,
            height=display_img.height,
            cursor="cross",
            highlightthickness=0,
            background="#222",
        )
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._canvas.pack(side="top", padx=6, pady=6)

        info = ttk.Frame(self)
        info.pack(side="top", fill="x", padx=6)
        ttk.Label(
            info,
            text=f"Source: {image_bgr.shape[1]}x{image_bgr.shape[0]} px"
            + (f" (display scale {self._scale:.2f})" if self._scale < 1.0 else ""),
            foreground="#888",
        ).pack(side="left")

        self._status_var = tk.StringVar(value="Drag to select a region")
        ttk.Label(self, textvariable=self._status_var, anchor="w").pack(
            side="top", fill="x", padx=6, pady=(2, 4)
        )

        actions = ttk.Frame(self, padding=(6, 0, 6, 6))
        actions.pack(side="top", fill="x")
        self._copy_btn = ttk.Button(
            actions, text="Copy coords", state="disabled", command=self._copy_coords,
        )
        self._copy_btn.pack(side="left")
        self._save_btn = ttk.Button(
            actions, text="Save as template...", state="disabled", command=self._save_as_template,
        )
        self._save_btn.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right")

        # Drag state in display coordinates.
        self._start_xy: tuple[int, int] | None = None
        self._rect_id: int | None = None
        # Final region in ORIGINAL image coordinates (x, y, w, h).
        self._region: tuple[int, int, int, int] | None = None

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Motion>", self._on_hover)

    # ----- mouse handlers -----

    def _on_press(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._start_xy = (event.x, event.y)
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
        self._rect_id = self._canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#00ff66", width=2,
        )

    def _on_drag(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if self._start_xy is None or self._rect_id is None:
            return
        x1, y1 = self._start_xy
        self._canvas.coords(self._rect_id, x1, y1, event.x, event.y)
        self._update_status_from_display(x1, y1, event.x, event.y, in_drag=True)

    def _on_release(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if self._start_xy is None:
            return
        x1, y1 = self._start_xy
        x2, y2 = event.x, event.y
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        ox, oy, ow, oh = self._display_to_original(x1, y1, x2 - x1, y2 - y1)
        if ow < 2 or oh < 2:
            self._region = None
            self._copy_btn.configure(state="disabled")
            self._save_btn.configure(state="disabled")
            self._status_var.set("Selection too small — try again")
            return
        self._region = (ox, oy, ow, oh)
        self._copy_btn.configure(state="normal")
        self._save_btn.configure(state="normal")
        self._update_status_from_display(x1, y1, x2, y2, in_drag=False)

    def _on_hover(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if self._start_xy is not None:
            return
        ox = int(round(event.x / self._scale))
        oy = int(round(event.y / self._scale))
        self._status_var.set(f"cursor: ({ox}, {oy})  —  drag to select a region")

    # ----- helpers -----

    def _display_to_original(self, dx: int, dy: int, dw: int, dh: int) -> tuple[int, int, int, int]:
        return (
            int(round(dx / self._scale)),
            int(round(dy / self._scale)),
            int(round(dw / self._scale)),
            int(round(dh / self._scale)),
        )

    def _update_status_from_display(
        self, dx1: int, dy1: int, dx2: int, dy2: int, *, in_drag: bool,
    ) -> None:
        if dx2 < dx1:
            dx1, dx2 = dx2, dx1
        if dy2 < dy1:
            dy1, dy2 = dy2, dy1
        ox, oy, ow, oh = self._display_to_original(dx1, dy1, dx2 - dx1, dy2 - dy1)
        suffix = " — drag…" if in_drag else " — ready"
        self._status_var.set(f"region: ({ox}, {oy}, {ow}, {oh}){suffix}")

    # ----- actions -----

    def _copy_coords(self) -> None:
        if self._region is None:
            return
        x, y, w, h = self._region
        text = f"({x}, {y}, {w}, {h})"
        self.clipboard_clear()
        self.clipboard_append(text)
        # Tk's clipboard is cleared when the widget is destroyed unless we
        # let the OS take ownership — update() forces that exchange.
        self.update()
        self._status_var.set(f"Copied to clipboard: {text}")

    def _save_as_template(self) -> None:
        if self._region is None:
            return
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        path_str = filedialog.asksaveasfilename(
            parent=self,
            initialdir=str(TEMPLATES_DIR),
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            title="Save template",
        )
        if not path_str:
            return
        x, y, w, h = self._region
        crop = self._original_bgr[y: y + h, x: x + w]
        cv2.imwrite(path_str, crop)
        rel = Path(path_str)
        try:
            rel = rel.relative_to(TEMPLATES_DIR.parent.parent.parent)
        except ValueError:
            pass
        self._status_var.set(f"Saved {w}x{h} crop to {rel}")
