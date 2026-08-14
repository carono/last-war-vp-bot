r"""The log PANE, and the spool behind it — everything the shell used to hold itself.

`panel/runtime/log.py` is the SINK: a line goes into it from any thread, is mirrored
into the debug log, is handed to whoever is tapping, and waits in a queue. What was
missing was the other half — the stamped history and the widget drawing it — and it
lived in `panel/__main__.py`, which is why the log could only ever be where the shell
drew it. It is a tab's now (#1391), so both halves moved here:

    LogBus.put ──> queue ──> LogSpool.pump ──┬──> panel.log       (the record)
      (any thread)           (the Tk thread) ├──> the history     (a filter redraw,
                                             │                     and a pane opened
                                             │                     an hour in)
                                             └──> LogPane, if one is drawn

THE SPOOL RUNS WHETHER OR NOT ANYBODY IS DRAWING. That is the whole reason it is not
part of the pane: «Разработка» is off in most profiles and LAZY in the rest, so for a
long stretch of an ordinary session there is no widget at all — and a queue nobody
drains grows without bound, while a `panel.log` nobody writes is a session with no
record of itself. The shell pumps this once a tick per profile and the pane is optional
throughout; opening one an hour into a session shows the hour, because the spool kept it.

ONE PANE AT A TIME, like `LogBus.drain` has one drainer. A second one would not see half
the lines — it would see all of them, and every line would be drawn twice in the first.
:meth:`LogSpool.attach` therefore replaces rather than appends, and says so in the debug
log if it ever has to.

WHY A WIDGET LIVES UNDER `runtime/`. Because the rule in `CLAUDE.md` is that
`panel/__main__.py` is the shell — window, notebook, menu, «Главная» — and anything a
tab needs out of it moves here first. `panel/runtime/web_dialog.py` is the same shape:
drawing that belongs to the panel rather than to any one page.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .. import widgets
from .log import FILTER_ALL, severity_of, strip_ansi, tag_of

#: Every producer that writes a `[tag]` into the log, in the order the filter offers
#: them. Adding a producer without adding it here costs nothing — its lines are always
#: shown, and only «show just this one» cannot single it out.
TAGS: tuple = ("panel", "action", "timer", "trigger", "secret", "autoloot", "ghost",
               "sweep", "rally", "help", "chat", "coord", "scene", "server", "game",
               "daemon", "profile", "traffic", "trace", "sniff", "dash", "cmd",
               "debug")

#: How many lines the widget keeps. An overnight session with a tracer running writes
#: tens of thousands of them, and a Text widget that large makes every subsequent insert
#: visibly slow — the panel froze once for exactly this reason. The on-disk mirror
#: (panel.log) is NOT trimmed: the widget is a window onto the session, the file is the
#: record.
MAX_LINES = 4000
#: Trimming a line at a time would run on every insert; drop a block instead, so the
#: cost is paid once every this many lines.
TRIM_BLOCK = 500
#: Severity colours, on the log's dark background.
COLOURS = {"sev_error": "#ff6b6b", "sev_warn": "#e8c069", "sev_ok": "#7bd88f",
           "stamp": "#6a6a6a"}


class LogSpool:
    """One profile's stamped history, and the pump that fills it. NO WIDGET.

    Made per runtime beside the :class:`~panel.runtime.log.LogBus` it drains, and
    pumped by whoever owns the clock — the shell, once per profile, every 120 ms.
    """

    def __init__(self, bus, cap: int = MAX_LINES) -> None:
        self.bus = bus
        #: How many lines to keep for a redraw. Twice this is held, so narrowing the
        #: filter and widening it again still has more history than the widget showed.
        self.cap = max(int(cap), 1)
        self._kept: list = []
        self._lock = threading.RLock()
        self._pane = None

    # -- the pump ------------------------------------------------------------
    def pump(self, cap: "int | None" = None) -> int:
        """Drain the bus: stamp, remember, mirror to panel.log, draw. Tk thread.

        Returns how many lines the pane drew, which is 0 whenever there is no pane —
        everything else it does happens either way, and that is the point of it.
        """
        if cap:
            self.cap = max(int(cap), 1)
        pane = self._pane
        drawn = 0
        while True:
            line = self.bus.take()
            if line is None:
                break
            stamp = time.strftime("%H:%M:%S")
            with self._lock:
                self._kept.append((stamp, line))
            if pane is not None:
                try:
                    # One scroll for the whole drain, below: a tracer streaming a
                    # thousand lines a second must not make Tk chase the tail a
                    # thousand times in the same tick.
                    drawn += 1 if pane.append(stamp, line, scroll=False) else 0
                except Exception:            # noqa: BLE001 — a widget, never the record
                    pane = None
            self.bus.append_file(line)
        self._trim()
        if drawn and pane is not None:
            try:
                pane.settle()
            except Exception:                # noqa: BLE001
                pass
        return drawn

    def _trim(self) -> None:
        with self._lock:
            if len(self._kept) > self.cap * 2:
                del self._kept[:len(self._kept) - self.cap]

    # -- reading -------------------------------------------------------------
    def lines(self) -> list:
        """The history, oldest first, as ``(stamp, line)``. A copy."""
        with self._lock:
            return list(self._kept)

    def clear(self) -> None:
        """Forget the history. `panel.log` is untouched — it is the record."""
        with self._lock:
            self._kept.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._kept)

    # -- the one pane --------------------------------------------------------
    def attach(self, pane) -> None:
        """This pane draws from now on, and seeds itself from the history."""
        self._pane = pane

    def detach(self, pane=None) -> None:
        """Stop drawing — the tab was closed, or the profile went away."""
        if pane is None or self._pane is pane:
            self._pane = None

    @property
    def pane(self):
        return self._pane


class LogPane:
    """The widget: a producer filter, Clear, and the coloured text with the clock.

    Built into ``parent`` and packed by its owner (``pane.frame``). Everything it says
    is a locale key through the runtime, and everything it draws comes from the spool —
    so a pane made an hour into a session opens on that hour rather than on a blank
    screen.
    """

    def __init__(self, parent, rt, *, spool=None, height: int = 16,
                 on_coord=None) -> None:
        self.rt = rt
        self.spool = spool if spool is not None else rt.log_spool
        self._lines = 0
        self.frame = ttk.Frame(parent)

        # The strip above the log: which producer to show, and Clear. Two dozen
        # producers write into one widget, so «давно ли пришёл этот запрос помощи»
        # otherwise means reading past everything else that happened meanwhile.
        strip = ttk.Frame(self.frame)
        strip.pack(fill="x", pady=(0, 3))
        rt.tr(ttk.Label(strip), "log.filter").pack(side="left")
        self.filter_var = tk.StringVar(master=rt.root, value=FILTER_ALL)
        combo = ttk.Combobox(strip, textvariable=self.filter_var, state="readonly",
                             width=10, values=(FILTER_ALL,) + TAGS)
        combo.pack(side="left", padx=(4, 8))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.redraw())
        rt.tr(ttk.Button(strip, command=self.clear), "log.clear").pack(side="left")
        rt.tr(ttk.Label(strip, foreground="#888"),
              "log.filter_hint").pack(side="left", padx=(10, 0))

        # Plain native Text widget: state="normal" (never toggled to "disabled", which
        # would block interactive selection). The log stays technically editable, but
        # stray typed edits to a log are harmless.
        self.text = ScrolledText(self.frame, wrap="word", height=height,
                                 font=("Consolas", 9),
                                 background="#111", foreground="#ddd")
        self.text.pack(fill="both", expand=True)
        self.text.tag_config(widgets.COORD_TAG, foreground="#5cf", underline=True)
        widgets.bind_coord_links(self.text, on_coord or self._jump)
        for tag, colour in COLOURS.items():
            self.text.tag_config(tag, foreground=colour)
        self._install_copy()

        self.spool.attach(self)
        self.redraw()
        # Tk tears the widgets down when the page goes; the spool must not be left
        # holding a pane whose Text no longer exists.
        self.frame.bind("<Destroy>", self._on_destroy, add="+")

    # -- what the spool calls ------------------------------------------------
    def append(self, stamp: str, text: str, scroll: bool = True) -> bool:
        """One stamped line. ``True`` if the filter let it onto the screen.

        The clock is the thing that was missed every single session — «когда собралась
        база?» used to mean opening panel.log, because the widget carried no time at all
        while the file did.
        """
        if not self.shown(text):
            return False
        clean = strip_ansi(text)
        level = severity_of(clean)
        body_tags = (f"sev_{level}",) if level else ()
        import coords                  # tools/lib, on sys.path once panel.runtime is in

        self.text.insert("end", stamp + " ", ("stamp",))
        pos = 0
        for (s, e, _x, _y, _srv) in coords.parse(clean):
            if s > pos:
                self.text.insert("end", clean[pos:s], body_tags)
            widgets.insert_coord_link(self.text, clean[s:e])
            pos = e
        if pos < len(clean):
            self.text.insert("end", clean[pos:], body_tags)
        self.text.insert("end", "\n", body_tags)
        self._lines += 1
        self._trim()
        if scroll:
            self.settle()
        return True

    def settle(self) -> None:
        """Follow the tail. Once per drain, not once per line."""
        try:
            self.text.see("end")
        except tk.TclError:
            pass

    # -- the filter ----------------------------------------------------------
    def shown(self, line: str) -> bool:
        """Does the filter let this line through?

        Display-only: everything is still written to panel.log and still kept in the
        spool, so narrowing to `[secret]` and back loses nothing.
        """
        try:
            chosen = self.filter_var.get()
        except tk.TclError:                  # the variable's interpreter is going away
            return True
        return not chosen or chosen == FILTER_ALL or tag_of(line) == chosen

    def redraw(self) -> None:
        """Repaint from the spool — after a filter change, and when the pane is made.

        Only the last `cap` matching lines: a session that has scrolled far past the cap
        must not become slow the moment somebody narrows the filter.
        """
        try:
            self.text.delete("1.0", "end")
        except tk.TclError:
            return
        self._lines = 0
        shown = [(s, ln) for s, ln in self.spool.lines() if self.shown(ln)]
        for stamp, line in shown[-self.spool.cap:]:
            self.append(stamp, line, scroll=False)
        self.settle()

    def clear(self) -> None:
        """Empty the widget AND the history behind it. panel.log is untouched."""
        self.spool.clear()
        try:
            self.text.delete("1.0", "end")
        except tk.TclError:
            pass
        self._lines = 0

    def _trim(self) -> None:
        """Keep the widget bounded — drop the oldest block when it overflows.

        A block at a time, not a line: trimming per insert would run the delete on every
        single line once the cap is reached, which is the cost this is here to avoid.
        """
        cap = self.spool.cap
        if self._lines <= cap + TRIM_BLOCK:
            return
        drop = self._lines - cap
        try:
            self.text.delete("1.0", f"{drop + 1}.0")
        except tk.TclError:
            return
        self._lines -= drop

    # -- copy, whatever the keyboard layout ----------------------------------
    def _install_copy(self) -> None:
        """Make the log copyable regardless of keyboard layout.

        Tk's default Text bindings copy on the Latin ``<Control-c>`` only, so a Cyrillic
        (or any non-Latin) layout leaves Ctrl+C dead. Explicit bindings for the Cyrillic
        keysyms, plus a right-click menu, which is fully layout-independent.
        """
        self.text.bind("<Control-KeyPress>", self._on_ctrl_key)
        menu = tk.Menu(self.text, tearoff=0)
        menu.add_command(command=self.copy_selection)        # idx 0: Copy
        menu.add_command(command=self.select_all)            # idx 1: Select All
        self._menu = menu
        self._retranslate_menu()
        self.rt.i18n.hook(self._retranslate_menu)
        # Button-3 is right-click on Windows/X11; Button-2 covers macOS.
        self.text.bind("<Button-3>", self._popup_menu)
        self.text.bind("<Button-2>", self._popup_menu)

    def _retranslate_menu(self) -> None:
        try:
            self._menu.entryconfigure(0, label=self.rt.t("log.copy"))
            self._menu.entryconfigure(1, label=self.rt.t("log.select_all"))
        except tk.TclError:                  # the menu went with the page
            pass

    def _on_ctrl_key(self, event):
        """Route Ctrl+C / Ctrl+A independently of keyboard layout."""
        keysym = (event.keysym or "").lower()
        # keycode: Windows VK code (physical key). Cyrillic_es/ef cover X11.
        if event.keycode == 67 or keysym in ("c", "cyrillic_es"):
            return self.copy_selection()
        if event.keycode == 65 or keysym in ("a", "cyrillic_ef"):
            return self.select_all()
        return None                          # let other Ctrl+combos pass through

    def copy_selection(self, _event=None) -> str:
        try:
            sel = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"                   # nothing selected
        if sel:
            self.text.clipboard_clear()
            self.text.clipboard_append(sel)
        return "break"

    def select_all(self, _event=None) -> str:
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _popup_menu(self, event) -> str:
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()
        return "break"

    # -- a coordinate in a line is a place to go -----------------------------
    def _jump(self, x: int, y: int, server) -> None:
        """The default click: say where, and walk the camera there.

        The runtime's jump and not the window's, so a pane in a tab launched on its own
        works exactly as one in the panel does.
        """
        import coords

        self.rt.say("coord", "log.coord.clicked", where=coords.fmt(x, y, server))
        try:
            self.rt.game.jump(x, y, server)
        except Exception:                    # noqa: BLE001 — a link, never the page
            self.rt.dbg("log").error("jump from the log failed", exc_info=True)

    # -- going away ----------------------------------------------------------
    def _on_destroy(self, event) -> None:
        if event.widget is self.frame:
            self.spool.detach(self)

    def destroy(self) -> None:
        """Take this pane off the spool and off the screen."""
        self.spool.detach(self)
        try:
            self.frame.destroy()
        except tk.TclError:
            pass
