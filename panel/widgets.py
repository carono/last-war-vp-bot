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


# ---------------------------------------------------------------------------
# clickable coordinates
# ---------------------------------------------------------------------------
#
# A coordinate printed anywhere in the panel is a place you can go, so it is drawn as
# a link. Two widgets carry them — the log and the chat views — which is why this is
# here rather than on either of them.
#
# ONE TAG PER WIDGET, BOUND ONCE. The first version tagged every coordinate uniquely
# and gave each its own three callbacks closing over its x/y/server. Nothing ever took
# them off: trimming the log drops the TEXT, and a chat rebuild clears the view, but a
# Tk tag and its bindings outlive the characters they were laid over. A panel left
# running overnight accumulated a tag, three Tcl commands and three Python closures per
# coordinate it had ever printed. The link needs no state of its own — the tagged text
# IS the coordinate, and `coords.parse` reads it back — so the shared tag is bound once
# per widget and a click resolves what was clicked from the range under the pointer.
COORD_TAG = "coordlink"
COORD_COLOR = "#5cf"

#: How many links have been drawn this session. Diagnostics only (the health snapshot
#: watches it), and the reason it is a module counter is that nobody owns the widgets.
_coord_links = 0


def coord_link_count() -> int:
    return _coord_links


def bind_coord_links(widget, on_jump):
    """Make ``widget``'s coordinate links clickable. ``on_jump(x, y, server)``.

    Call once per widget, after tagging it with :data:`COORD_TAG`. Returns the click
    handler it bound, so a test can aim one without a real pointer.
    """
    import coords                    # tools/lib, on sys.path once panel.runtime is in

    # The cursor to put back on Leave is whatever the widget normally shows — "" in the
    # log, "arrow" in a chat view — not a hardcoded one.
    try:
        rest = widget.cget("cursor")
    except tk.TclError:
        rest = ""

    def click(event, w=widget) -> None:
        try:
            here = w.index(f"@{event.x},{event.y}")
            span = w.tag_prevrange(COORD_TAG, f"{here} +1c")
            text = w.get(*span) if span else ""
        except tk.TclError:
            return
        hits = coords.parse(text)
        if hits:
            _s, _e, x, y, srv = hits[0]
            on_jump(x, y, srv)

    widget.tag_bind(COORD_TAG, "<Button-1>", click)
    widget.tag_bind(COORD_TAG, "<Enter>",
                    lambda ev, w=widget: w.configure(cursor="hand2"))
    widget.tag_bind(COORD_TAG, "<Leave>",
                    lambda ev, w=widget, c=rest: w.configure(cursor=c))
    return click


def insert_coord_link(widget, text: str) -> None:
    """Write ``text`` into ``widget`` as a coordinate that jumps when clicked."""
    global _coord_links
    _coord_links += 1
    widget.insert("end", text, (COORD_TAG,))


def tk_stringvar(master):
    """An empty ``StringVar`` owned by ``master`` — a status line's variable.

    Owned explicitly: a variable created with no master belongs to whichever root Tk
    happened to be made first, which in a panel that opens a dialog is not the window
    the label is in.
    """
    return tk.StringVar(master=master, value="")


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


class Tooltip:
    """A borderless window with a few lines of text, shown beside the pointer.

    One per thing that explains itself, reused for every hover rather than built and
    destroyed per motion event: a `Toplevel` is a native window, and making one sixty
    times a second while a pointer crosses a tab strip is visible as a flicker on
    Windows and as leaked handles everywhere.

    It exists because a coloured dot is half a tool (#1299). The colour is read in a
    glance and says «something is wrong»; the words say WHICH READING said so, which is
    the difference between «fix the client» and «fix the daemon». Whoever shows one is
    responsible for the text being locale keys already said — this class formats
    nothing and translates nothing.
    """

    def __init__(self, master) -> None:
        self._master = master
        self._win = None
        self._label = None
        #: Whether it is on screen NOW — not whether the window has ever been built.
        #: The two came apart in the first draft: `hide` withdraws rather than destroys
        #: (that is the whole point of reusing the window), so «is there a Toplevel» is
        #: True for the rest of the session and a hover after a hide drew nothing.
        self._shown = False

    @property
    def showing(self) -> bool:
        return self._shown

    def show(self, text: str, x: int, y: int) -> None:
        """Put ``text`` at screen position ``(x, y)``. Building the window if needed."""
        if not text:
            self.hide()
            return
        try:
            if self._win is None:
                self._win = tk.Toplevel(self._master)
                self._win.wm_overrideredirect(True)      # no title bar, no border
                self._win.attributes("-topmost", True)
                self._label = tk.Label(self._win, justify="left", anchor="w",
                                       background="#ffffe0", foreground="#222",
                                       relief="solid", borderwidth=1, padx=6, pady=4)
                self._label.pack()
            self._label.configure(text=text)
            self._win.wm_geometry(f"+{int(x)}+{int(y)}")
            self._win.deiconify()
            self._shown = True
        except tk.TclError:                              # the window is going away
            self._win = self._label = None
            self._shown = False

    def hide(self) -> None:
        self._shown = False
        if self._win is None:
            return
        try:
            self._win.withdraw()
        except tk.TclError:
            self._win = self._label = None


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
        # The wheel: see `_install_wheel_router`. Entering the area makes this frame
        # the one the router scrolls; leaving it hands the wheel back.
        self._canvas.bind("<Enter>", self._enter)
        self._canvas.bind("<Leave>", self._leave)
        _install_wheel_router(self._canvas)

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

    def _enter(self, _event=None):
        global _wheel_target
        _wheel_target = self

    def _leave(self, _event=None):
        global _wheel_target
        if _wheel_target is self:
            _wheel_target = None

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(delta, "units")


# -- the wheel, routed instead of re-bound ------------------------------------
#
# A scroll has to reach the area under the pointer wherever inside it the pointer
# sits — over a child row, a label, a button — so the binding has to be an
# application-wide one. It used to be *taken and given back*: `bind_all` on every
# <Enter>, `unbind_all` on every <Leave>. Each `bind_all` registers a fresh Tcl
# command, and `unbind_all` clears the binding script without freeing the command
# behind it, so every pass of the mouse across a scrollable page — the Command
# Post, the Inventory, the Profile — left three orphaned callbacks behind, for as
# long as the panel stayed open.
#
# Now the binding is installed once per interpreter and never taken down; what
# <Enter>/<Leave> change is only which frame it forwards to.
_wheel_target: "ScrollableFrame | None" = None
# Whether an interpreter already carries the binding is remembered IN that
# interpreter (a Tcl variable), not in a Python set: a set keyed by object id would
# go stale the moment an interpreter is torn down and a new one reuses the address,
# which is exactly what a test that builds a root per case does.
_ROUTER_FLAG = "::lw_wheel_router"


def _route_wheel(event) -> None:
    global _wheel_target
    frame = _wheel_target
    if frame is None:
        return
    try:
        if not frame._canvas.winfo_exists():
            _wheel_target = None        # its page went away without a <Leave>
            return
        frame._on_wheel(event)
    except tk.TclError:
        _wheel_target = None


def _install_wheel_router(widget) -> None:
    """Bind the wheel on this widget's interpreter, once."""
    try:
        if str(widget.tk.call("info", "exists", _ROUTER_FLAG)) == "1":
            return
        widget.tk.call("set", _ROUTER_FLAG, 1)
    except tk.TclError:               # no interpreter to ask: bind and hope
        pass
    # Registered on the ROOT window, whose Tcl commands outlive every page: a
    # binding whose callback was registered on a widget that is later destroyed
    # would fire into a deleted command.
    root = widget._root()
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        root.bind_all(seq, _route_wheel, add="+")


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
