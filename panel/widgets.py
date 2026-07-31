"""Small tk/ttk helpers shared across the panel.

The panel is a plain tkinter/ttk application. This module holds the few reusable
pieces that are not a single stock widget: a scrollable frame (a Canvas with a
scrollbar), a font-tuple builder, and the panel-wide numeric-field rule (digits
only, layout-independent clipboard) applied to entries and spinboxes.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk


def font(size=None, weight=None, slant=None):
    """A font *tuple* derived from ``TkDefaultFont`` — usable as ``font=`` on any
    widget. Only the attributes given are overridden; the rest stay the default."""
    try:
        base = tkfont.nametofont("TkDefaultFont")
        family = base.actual("family")
        base_size = base.actual("size")
    except Exception:       # noqa: BLE001 — no root yet; fall back to a safe default
        family, base_size = "TkDefaultFont", 9
    sz = int(size) if size is not None else base_size
    styles = []
    if weight == "bold":
        styles.append("bold")
    if slant == "italic":
        styles.append("italic")
    return (family, sz, " ".join(styles)) if styles else (family, sz)


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable container. Build children with THIS as their master.

    This instance IS the content frame — a ``ttk.Frame`` placed as a window inside a
    ``tk.Canvas``, with a ``ttk.Scrollbar`` beside it (both held in an outer frame).
    Geometry calls on the group (``pack``/``grid``/``place``) are proxied to the
    outer frame, so a caller manages the whole scroll area while its children land in
    the scrollable content. The content is kept as wide as the canvas, the scroll
    region tracks its height, and the mouse wheel scrolls while the pointer is over
    the area.
    """

    def __init__(self, master=None, **kw):
        self._outer = ttk.Frame(master)
        self._canvas = tk.Canvas(self._outer, highlightthickness=0, borderwidth=0)
        self._bar = ttk.Scrollbar(self._outer, orient="vertical",
                                  command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._bar.set)
        self._bar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        super().__init__(self._canvas, **kw)        # self is the content frame
        self._win = self._canvas.create_window((0, 0), window=self, anchor="nw")
        self.bind("<Configure>", self._on_interior)
        self._canvas.bind("<Configure>", self._on_canvas)
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    # -- geometry: the caller manages the *group*, i.e. the outer frame ---------
    def pack(self, **kw):
        self._outer.pack(**kw)
        return self

    def grid(self, **kw):
        self._outer.grid(**kw)
        return self

    def place(self, **kw):
        self._outer.place(**kw)
        return self

    def pack_forget(self):
        self._outer.pack_forget()

    def grid_forget(self):
        self._outer.grid_forget()

    def _on_interior(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas(self, event):
        self._canvas.itemconfigure(self._win, width=event.width)

    def _bind_wheel(self, _event=None):
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)
        self._canvas.bind_all("<Button-4>", self._on_wheel)
        self._canvas.bind_all("<Button-5>", self._on_wheel)

    def _unbind_wheel(self, _event=None):
        self._canvas.unbind_all("<MouseWheel>")
        self._canvas.unbind_all("<Button-4>")
        self._canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(delta, "units")


# ---------------------------------------------------------------------------
# Numeric fields — the panel-wide rule for every field that expects a number
# (timer intervals, the elite level, coordinate boxes, spinboxes, …):
#
#   1. Typing accepts only digits 0-9 (plus, where the field needs it, a single
#      leading '-' for a coordinate or one '.' for a float knob). Letters and
#      punctuation are rejected on the keystroke, via Tk's validate="key" — which
#      checks the *resulting* text, so it is immune to the keyboard layout.
#   2. Copy / cut / paste / select-all keep working in these fields. A paste is
#      NEVER blocked: its non-digit characters are filtered out and the digits
#      inserted. The clipboard keys are matched by physical VK code (C=67, X=88,
#      V=86, A=65 — the same trick the log copy uses), so they fire under a
#      Cyrillic layout where Tk's Latin-only <<Copy>>/<<Paste>> never would.
#
# Apply it with numeric_spinbox()/NumericEntry below, or install_numeric_field()
# on an existing widget. Leave it OFF for text fields (paths, args, chat, names).
# ---------------------------------------------------------------------------

# Physical-key VK codes, layout-invariant (Windows). Named Cyrillic keysyms are a
# cross-platform fallback for the same physical keys (С=copy, Ч=cut, М=paste, Ф=all).
_CLIP_COPY = (67, "c", "cyrillic_es")
_CLIP_CUT = (88, "x", "cyrillic_che")
_CLIP_PASTE = (86, "v", "cyrillic_em")
_CLIP_ALL = (65, "a", "cyrillic_ef")


def is_number(text: str, signed=False, decimal=False) -> bool:
    """Whether ``text`` is an acceptable in-progress numeric value (empty is ok, a
    lone '-' is ok when signed, one '.' is ok when decimal) — the predicate behind
    the typing validation."""
    if text == "" or (signed and text == "-"):
        return True
    body = text[1:] if signed and text.startswith("-") else text
    if decimal:
        return body.count(".") <= 1 and all(ch.isdigit() or ch == "." for ch in body)
    return body.isdigit()


def filter_number(text: str, signed=False, decimal=False) -> str:
    """Reduce ``text`` to a number: keep digits (and one '.' when decimal, one
    leading '-' when signed), drop the rest — what a paste becomes instead of
    being rejected."""
    out, seen_dot = [], False
    for ch in text:
        if ch.isdigit():
            out.append(ch)
        elif decimal and ch == "." and not seen_dot:
            out.append(ch)
            seen_dot = True
    result = "".join(out)
    if signed and text.lstrip().startswith("-"):
        result = "-" + result
    return result


def install_numeric_field(widget, signed=False, decimal=False):
    """Make ``widget`` (a ttk.Entry or a ttk.Spinbox) a numeric field (digits only;
    a leading '-' when ``signed``; one '.' when ``decimal``) with layout-independent
    clipboard support. See the module comment above for the rule."""
    entry = widget                              # ttk.Entry and ttk.Spinbox are both entries

    entry.configure(validate="key",
                    validatecommand=(entry.register(
                        lambda p: is_number(p, signed, decimal)), "%P"))

    def _clean(text: str) -> str:
        return filter_number(text, signed, decimal)

    def _drop_selection():
        # Delete the selection AND leave the cursor where it was, so a following
        # insert replaces the selection in place instead of appending at the end.
        try:
            if entry.selection_present():
                first = entry.index("sel.first")
                entry.delete("sel.first", "sel.last")
                entry.icursor(first)
        except tk.TclError:
            pass

    def _selected_text():
        try:
            if not entry.selection_present():
                return ""
            first, last = entry.index("sel.first"), entry.index("sel.last")
            return entry.get()[first:last]
        except tk.TclError:
            return ""

    def _paste():
        try:
            clip = entry.clipboard_get()
        except tk.TclError:
            return "break"
        # A programmatic edit must not run through key-validation (Tk would turn
        # validation off if it ever saw a reject), so suspend it around the insert.
        entry.configure(validate="none")
        _drop_selection()
        entry.insert("insert", _clean(clip))
        entry.configure(validate="key")
        return "break"

    def _copy():
        sel = _selected_text()
        if sel:
            entry.clipboard_clear()
            entry.clipboard_append(sel)
        return "break"

    def _cut():
        _copy()
        entry.configure(validate="none")
        _drop_selection()
        entry.configure(validate="key")
        return "break"

    def _select_all():
        entry.select_range(0, "end")
        entry.icursor("end")
        return "break"

    def _on_ctrl(event):
        code, sym = event.keycode, (event.keysym or "").lower()
        if code == _CLIP_COPY[0] or sym in _CLIP_COPY[1:]:
            return _copy()
        if code == _CLIP_CUT[0] or sym in _CLIP_CUT[1:]:
            return _cut()
        if code == _CLIP_PASTE[0] or sym in _CLIP_PASTE[1:]:
            return _paste()
        if code == _CLIP_ALL[0] or sym in _CLIP_ALL[1:]:
            return _select_all()
        return None

    entry.bind("<Control-KeyPress>", _on_ctrl)
    # Exposed so a test can exercise the clipboard paths without synthesising a
    # keystroke (headless key events are unreliable); the real trigger is Ctrl+key.
    entry._numeric_paste = _paste
    entry._numeric_copy = _copy
    return widget


class NumericEntry(ttk.Entry):
    """A ttk.Entry restricted to a number — see install_numeric_field / the rule above."""

    def __init__(self, master=None, signed=False, decimal=False, **kw):
        super().__init__(master, **kw)
        install_numeric_field(self, signed=signed, decimal=decimal)


def numeric_spinbox(master=None, signed=False, decimal=False, **kw):
    """A ttk.Spinbox restricted to a number — see install_numeric_field / the rule above."""
    spinbox = ttk.Spinbox(master, **kw)
    install_numeric_field(spinbox, signed=signed, decimal=decimal)
    return spinbox
