"""CustomTkinter widgets that speak the panel's legacy tk/ttk dialect.

The panel was written against tkinter/ttk, whose widgets accept options
CustomTkinter does not (``foreground``, ``padding``, ``relief``, a character
based ``width``) and expose a couple of methods CustomTkinter lacks
(``ttk.Combobox.current``, ``ttk.Notebook.add(frame, text=...)``). Rather than
rewrite several hundred call sites, every widget the panel builds is one of the
adapters below: a thin CustomTkinter subclass that translates the old keyword
arguments and re-implements the handful of old methods, so the migration stays a
widget swap.

Widgets with no CustomTkinter counterpart (Treeview, Spinbox, Listbox, Menu,
PanedWindow, Style) keep coming from ttk/tk in ``__main__`` — those are not here.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

# ttk measures Entry/Button/Combobox width in characters; CustomTkinter measures
# it in pixels. This is the average glyph width used to translate the former into
# the latter, and the per-line height used for text boxes.
_CHAR_PX = 8
_LINE_PX = 19

# ttk-only options that carry no meaning in CustomTkinter and are simply dropped.
_DROP = ("padding", "relief", "borderwidth", "bd", "highlightthickness",
         "highlightbackground", "highlightcolor", "takefocus")


def _translate(kw: dict) -> None:
    """Map/strip ttk-only keyword arguments in place (colours + dropped options)."""
    for key in _DROP:
        kw.pop(key, None)
    if "foreground" in kw:
        colour = kw.pop("foreground")
        kw["text_color"] = colour if colour else None
    if "background" in kw:
        colour = kw.pop("background")
        kw["fg_color"] = colour if colour else None


def _chars_to_px(kw: dict) -> None:
    """Turn a character-count ``width`` (ttk) into pixels (CustomTkinter)."""
    if "width" in kw:
        try:
            kw["width"] = max(int(kw["width"]) * _CHAR_PX, 1)
        except (TypeError, ValueError):
            pass


def _measure(widget, text: str) -> int:
    """Pixel width of ``text`` in ``widget``'s font — for auto-sizing buttons."""
    if not text:
        return 0
    try:
        font = widget.cget("font")
        if not isinstance(font, tkfont.Font):
            font = tkfont.Font(font=font)
        return int(font.measure(text))
    except Exception:       # noqa: BLE001 — a size hint must never break a build
        return len(text) * _CHAR_PX


class CTkFrame(ctk.CTkFrame):
    """A frame that is transparent by default, so container frames read as flat
    like ``ttk.Frame`` instead of a patchwork of grey cards."""

    def __init__(self, master=None, **kw):
        _translate(kw)
        if "fg_color" not in kw:
            kw["fg_color"] = "transparent"
        super().__init__(master, **kw)

    def configure(self, **kw):
        _translate(kw)
        super().configure(**kw)


class CTkLabel(ctk.CTkLabel):
    """A label that accepts ``foreground``/``background``, a character ``width``,
    ``justify``/``textvariable`` (which CTkLabel lacks) and ``cursor``."""

    def __init__(self, master=None, **kw):
        _translate(kw)
        _chars_to_px(kw)
        cursor = kw.pop("cursor", None)
        justify = kw.pop("justify", None)
        var = kw.pop("textvariable", None)
        if var is not None:
            kw.setdefault("text", str(var.get()))
        kw.setdefault("text", "")
        super().__init__(master, **kw)
        self._cursor = cursor
        self._textvariable = var
        if cursor:
            self._apply_cursor(cursor)
        if justify:
            self._apply_justify(justify)
        if var is not None:
            var.trace_add("write", lambda *_: self._on_var())

    def _on_var(self):
        try:
            self.configure(text=str(self._textvariable.get()))
        except tk.TclError:
            pass

    def _apply_cursor(self, cursor):
        try:
            self._label.configure(cursor=cursor)
        except Exception:       # noqa: BLE001
            pass

    def _apply_justify(self, justify):
        try:
            self._label.configure(justify=justify)
        except Exception:       # noqa: BLE001
            pass

    def configure(self, **kw):
        _translate(kw)
        _chars_to_px(kw)
        if "cursor" in kw:
            self._apply_cursor(kw.pop("cursor"))
        if "justify" in kw:
            self._apply_justify(kw.pop("justify"))
        super().configure(**kw)


class _AutoWidthMixin:
    """Shared auto-sizing for widgets CustomTkinter gives a fixed width but ttk
    grew to fit their text (Button, CheckBox)."""

    _extra_px = 24

    def _init_autowidth(self, explicit):
        self._explicit_width = explicit
        self._autosize()

    def _autosize(self):
        if getattr(self, "_explicit_width", False):
            return
        try:
            width = _measure(self, self.cget("text")) + self._extra_px
            super().configure(width=max(width, 12))
        except Exception:       # noqa: BLE001
            pass


class CTkButton(_AutoWidthMixin, ctk.CTkButton):
    def __init__(self, master=None, **kw):
        _translate(kw)
        explicit = "width" in kw
        _chars_to_px(kw)
        kw.setdefault("text", "")
        super().__init__(master, **kw)
        self._init_autowidth(explicit)

    def configure(self, **kw):
        _translate(kw)
        if "width" in kw:
            self._explicit_width = True
            _chars_to_px(kw)
        retext = "text" in kw
        super().configure(**kw)
        if retext:
            self._autosize()


class CTkCheckBox(_AutoWidthMixin, ctk.CTkCheckBox):
    _extra_px = 40      # room for the box itself plus its gap to the label

    def __init__(self, master=None, **kw):
        style = kw.pop("style", None)
        _translate(kw)
        kw.pop("width", None)       # ttk checkbuttons never set a meaningful width
        var = kw.get("variable")
        if isinstance(var, tk.BooleanVar):
            kw.setdefault("onvalue", True)
            kw.setdefault("offvalue", False)
        kw.setdefault("text", "")
        super().__init__(master, **kw)
        self._bold = False
        if style:
            self._apply_style(style)
        self._init_autowidth(False)

    def _apply_style(self, style):
        self._bold = "Selected" in (style or "")
        super().configure(font=ctk.CTkFont(weight="bold" if self._bold else "normal"))

    def configure(self, **kw):
        if "style" in kw:
            self._apply_style(kw.pop("style"))
            self._autosize()
        _translate(kw)
        retext = "text" in kw
        super().configure(**kw)
        if retext:
            self._autosize()


class CTkEntry(ctk.CTkEntry):
    def __init__(self, master=None, **kw):
        _translate(kw)
        _chars_to_px(kw)
        justify = kw.pop("justify", None)
        super().__init__(master, **kw)
        if justify:
            try:
                self._entry.configure(justify=justify)
            except Exception:       # noqa: BLE001
                pass

    def configure(self, **kw):
        _translate(kw)
        _chars_to_px(kw)
        super().configure(**kw)


class CTkComboBox(ctk.CTkComboBox):
    """``ttk.Combobox`` shim: ``textvariable`` → ``variable``, a working
    ``state="readonly"`` (CustomTkinter's readonly kills the dropdown, so instead
    the list stays pickable and only typing is blocked), a character ``width`` and
    the ``current()`` method ttk has and CustomTkinter does not."""

    def __init__(self, master=None, **kw):
        _translate(kw)
        _chars_to_px(kw)
        if "textvariable" in kw:
            kw["variable"] = kw.pop("textvariable")
        if "values" in kw and kw["values"] is not None:
            kw["values"] = list(kw["values"])
        readonly = kw.pop("state", None) == "readonly"
        if not readonly and "state" in kw:
            pass
        super().__init__(master, **kw)
        if readonly:
            try:
                self._entry.bind("<KeyPress>", lambda _e: "break")
            except Exception:       # noqa: BLE001
                pass

    def configure(self, **kw):
        _translate(kw)
        _chars_to_px(kw)
        if "textvariable" in kw:
            kw["variable"] = kw.pop("textvariable")
        if "values" in kw and kw["values"] is not None:
            kw["values"] = list(kw["values"])
        if kw.get("state") == "readonly":
            kw.pop("state")
        super().configure(**kw)

    def current(self, index=None):
        """Get (no arg) or set (int arg) the selected index — the ttk method."""
        values = list(self.cget("values"))
        if index is None:
            try:
                return values.index(self.get())
            except ValueError:
                return -1
        if 0 <= index < len(values):
            self.set(values[index])
        return None

    def bind(self, sequence=None, command=None, add=None):
        # The panel wires selection through <<ComboboxSelected>>; CustomTkinter
        # reports it through the `command` callback instead.
        if sequence == "<<ComboboxSelected>>":
            self.configure(command=lambda _choice: command(None))
            return
        return super().bind(sequence, command, add)


class CTkLabelFrame(ctk.CTkFrame):
    """A titled group box — CustomTkinter has no ``LabelFrame``.

    It is a composite: an *outer* card holds a bold title along its top edge and a
    *content* frame below it. This instance IS the content frame (so widgets built
    with it as their master land inside the group and can freely pack **or** grid —
    the title lives in the outer frame, so the two never fight over one geometry
    manager). Geometry calls on the group (``pack``/``grid``/``place``) are proxied
    to the outer card, and ``configure(text=...)`` retitles it, which is how the
    panel's per-language retranslation reaches the title.
    """

    def __init__(self, master=None, text="", **kw):
        _translate(kw)
        kw.pop("width", None)
        self._outer = ctk.CTkFrame(master)
        super().__init__(self._outer, fg_color="transparent", **kw)
        self._title = ctk.CTkLabel(self._outer, text=text, anchor="w",
                                   font=ctk.CTkFont(weight="bold"))
        self._title.pack(anchor="w", fill="x", padx=10, pady=(6, 0))
        ctk.CTkFrame.pack(self, fill="both", expand=True, padx=8, pady=(2, 8))

    # -- geometry: the caller manages the *group*, i.e. the outer card ----------
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

    # No destroy() override: the group is torn down when its parent destroys the
    # outer card, which cascades into this content frame. Overriding destroy() to
    # forward to the outer would recurse (outer → content → outer → …).

    def configure(self, **kw):
        if "text" in kw:
            self._title.configure(text=kw.pop("text"))
        _translate(kw)
        if kw:
            super().configure(**kw)

    def cget(self, key):
        if key == "text":
            return self._title.cget("text")
        return super().cget(key)


class CTkNotebook(ctk.CTkFrame):
    """A tabbed container with the ``ttk.Notebook`` API the panel relies on.

    CustomTkinter's ``CTkTabview`` owns its pages and cannot adopt frames built
    ahead of time (which is how the panel constructs every tab), nor rename a tab
    after the fact (which its per-language relabelling needs). So this is a small
    reimplementation over CustomTkinter widgets: a row of tab buttons plus the
    caller's own page frames, shown one at a time.
    """

    def __init__(self, master=None, **kw):
        _translate(kw)
        if "fg_color" not in kw:
            kw["fg_color"] = "transparent"
        super().__init__(master, **kw)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._bar = ctk.CTkFrame(self, fg_color="transparent")
        self._bar.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        self._pages = []            # [child, button, text]
        self._current = None
        self._change_cb = None
        self._sel_color = self._theme("CTkButton", "fg_color", ("#3B8ED0", "#1F6AA5"))
        self._norm_color = self._theme("CTkButton", "hover_color", ("#325882", "#14375e"))

    @staticmethod
    def _theme(section, key, default):
        try:
            return ctk.ThemeManager.theme[section][key]
        except Exception:       # noqa: BLE001
            return default

    def add(self, child, text=""):
        button = ctk.CTkButton(self._bar, text=text, height=28, corner_radius=6,
                               fg_color=self._norm_color,
                               command=lambda c=child: self.select(c))
        button.pack(side="left", padx=(0, 4))
        child.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        child.grid_remove()
        self._pages.append([child, button, text])
        if self._current is None:
            self.select(child)

    def tabs(self):
        """The tab ids, as ttk.Notebook returns them (page widget path strings)."""
        return [str(child) for child, _button, _text in self._pages]

    def _find(self, tab_id):
        for entry in self._pages:
            if entry[0] is tab_id or str(entry[0]) == str(tab_id):
                return entry
        return None

    def tab(self, tab_id, option=None, **kw):
        """ttk.Notebook.tab: ``tab(id, text="x")`` sets, ``tab(id, "text")`` /
        ``tab(id)`` gets the label."""
        entry = self._find(tab_id)
        if entry is None:
            return None
        if "text" in kw:
            entry[2] = kw["text"]
            entry[1].configure(text=kw["text"])
            return None
        if option in (None, "text"):
            return entry[2]
        return None

    def select(self, child=None):
        if child is None:
            return str(self._current) if self._current is not None else ""
        changed = self._current is not child
        for page_child, button, _text in self._pages:
            if page_child is child:
                page_child.grid()
                button.configure(fg_color=self._sel_color)
            else:
                page_child.grid_remove()
                button.configure(fg_color=self._norm_color)
        self._current = child
        if changed and self._change_cb is not None:
            self._change_cb(None)
        return None

    def index(self, arg=None):
        if arg == "end":
            return len(self._pages)
        for i, (child, _b, _t) in enumerate(self._pages):
            if child is arg or str(child) == str(arg):
                return i
        return -1

    def bind(self, sequence=None, command=None, add=None):
        if sequence == "<<NotebookTabChanged>>":
            self._change_cb = command
            return
        return super().bind(sequence, command, add)


class CTkScrollbar(ctk.CTkScrollbar):
    """``ttk.Scrollbar`` uses ``orient=``; CustomTkinter uses ``orientation=``."""

    def __init__(self, master=None, **kw):
        if "orient" in kw:
            kw["orientation"] = kw.pop("orient")
        _translate(kw)
        super().__init__(master, **kw)


class CTkTextbox(ctk.CTkTextbox):
    """``tk.Text`` / ``ScrolledText`` shim: character ``height``/``width`` →
    pixels, ``foreground``/``background`` → CustomTkinter colours, the built-in
    scrollbars stand in for a manually attached one, and stray ttk options are
    dropped. Every ``tk.Text`` method is proxied by ``CTkTextbox`` already."""

    def __init__(self, master=None, **kw):
        for key in ("relief", "borderwidth", "bd", "highlightthickness"):
            kw.pop(key, None)
        if "foreground" in kw:
            colour = kw.pop("foreground")
            kw["text_color"] = colour if colour else None
        if "background" in kw:
            colour = kw.pop("background")
            kw["fg_color"] = colour if colour else None
        if "height" in kw:
            try:
                kw["height"] = int(kw["height"]) * _LINE_PX
            except (TypeError, ValueError):
                pass
        if "width" in kw:
            try:
                kw["width"] = int(kw["width"]) * _CHAR_PX
            except (TypeError, ValueError):
                pass
        super().__init__(master, **kw)
        self._default_text_color = self._text_color

    def tag_configure(self, *args, **kwargs):
        # CTkTextbox wraps tag_config but not its tkinter alias tag_configure.
        return self._textbox.tag_configure(*args, **kwargs)

    def destroy(self):
        # CTkTextbox schedules an after-loop to auto-hide its scrollbars; if the
        # widget is torn down while that callback is still pending (e.g. a headless
        # test that never ran a mainloop), CustomTkinter's own destroy raises
        # "can't delete Tcl command" and aborts the parent's teardown cascade.
        # Swallow it: the widget is already gone by that final cleanup step.
        try:
            super().destroy()
        except tk.TclError:
            pass

    def image_create(self, index, **kwargs):
        # CTkTextbox forbids image_create (its scaling can't follow embeds); the
        # chat view draws inline emoji/sticker sprites, so forward straight to the
        # inner Text. The sprites are pre-sized, so lost auto-scaling is a non-issue.
        return self._textbox.image_create(index, **kwargs)

    def window_create(self, index, **kwargs):
        return self._textbox.window_create(index, **kwargs)

    def __getattr__(self, name):
        # Proxy any tkinter.Text method CTkTextbox left unwrapped to the inner
        # Text widget (rather than tkinter's default forward to the Tcl interp).
        textbox = self.__dict__.get("_textbox")
        if textbox is None:
            raise AttributeError(name)
        return getattr(textbox, name)

    def configure(self, **kw):
        for key in ("relief", "borderwidth", "bd", "highlightthickness"):
            kw.pop(key, None)
        if "foreground" in kw:
            colour = kw.pop("foreground")
            kw["text_color"] = colour if colour else getattr(
                self, "_default_text_color", None)
        if "background" in kw:
            colour = kw.pop("background")
            if colour:
                kw["fg_color"] = colour
        super().configure(**kw)
