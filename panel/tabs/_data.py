"""The read-only tab shape: load once when first shown, refresh on a button.

Five tabs are the same story — read something off the live game, draw it, offer
«Обновить». The heavy lifting runs on a background thread and always degrades
gracefully: no daemon, no game, or a manager that is not loaded yet shows an empty
state, never a crash.

The data reads are BEST-EFFORT. The exact Lua accessors for level/power, the inventory
and the alliance roster are not confirmed against a live client, so each is wrapped in
`pcall` and a field that cannot be read is simply omitted.

This is `panel/tabs_extra.py`'s `_DataTab`, re-parented onto :class:`PanelTab` and
speaking to the runtime instead of reaching into the app.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..widgets import font as ui_font
from .base import PanelTab

# Resource keys, in display order, with a glyph fallback for the icon.
RESOURCE_GLYPHS = {"food": "🍖", "wood": "🌲", "metal": "⚙️", "oil": "🛢️", "gold": "🪙"}
RESOURCE_ORDER = ("food", "wood", "metal", "oil", "gold")


def _run_lua(rt, chunk: str, marker: str, settle: float = 0.6):
    """Run ``chunk`` through the warm daemon and return the Player.log lines that carry
    ``marker``. Returns ``[]`` on any failure (no daemon / no game / error).

    `settle` is a deadline, not a pause (`early`): these are readings of what the game
    already knows, they answer in one call, and the daemon serialises every chunk — so a
    tab refreshing itself used to hold the game for six tenths of a second in front of
    whatever the person pressed next (#1230).
    """
    try:
        return rt.game.evaluator().run(chunk, marker=marker, settle=settle,
                                       early=True) or []
    except Exception:       # noqa: BLE001 — a failed read is an empty tab, never a crash
        return []


def _marker_payloads(lines, marker: str):
    """Every ``<marker> …`` line's payload, in order."""
    out = []
    for line in lines or ():
        _head, sep, tail = line.partition(marker + " ")
        if sep:
            out.append(tail.rstrip("\n"))
    return out


def _stringvar(rt):
    return tk.StringVar(master=rt.root, value="")


def _card(parent):
    """A bordered card frame (a plain ttk.LabelFrame carries a title via `tr`)."""
    return ttk.LabelFrame(parent, padding=8)


def _int(value) -> int:
    """Parse an integer, returning 0 on anything unparseable."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _group(value) -> str:
    """A number with thousands separators; passes through non-numbers unchanged."""
    if value in (None, ""):
        return ""
    try:
        return f"{int(str(value).replace(',', '').strip()):,}"
    except (TypeError, ValueError):
        return str(value)


class DataTab(PanelTab):
    """A tab that loads once when first shown and refreshes on a button.

    Subclasses fill :meth:`build` (UI), :meth:`fetch` (background, returns data) and
    :meth:`render` (Tk thread, paints the data). :meth:`fetch` runs off the Tk thread —
    and `build()` never touches the game, which is what lets the tab open standalone
    with no daemon at all.
    """

    #: These tabs all have a phone screen: they are a reading and a «Обновить», which
    #: is exactly what the web front-end draws with one renderer.
    WEB_SCREEN = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._loaded = False
        self._busy = False
        self._status_var = None
        #: The last reading, kept so the phone can be handed what the tab ALREADY has.
        #: Before this, the data went straight into widgets and was gone — and a phone
        #: opening a screen would have had to read the game to see anything, on every
        #: open, for every screen. Now the game is read when somebody asks for it.
        self._last_data = None

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """First time the tab is shown: kick off the initial load."""
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh_live(self) -> None:
        """Re-read because something on the wire said to — but only if this tab has
        been opened at all. An unopened one reads fresh when it is first shown, so a
        push landing behind it costs nothing."""
        if self._loaded:
            self.refresh()

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        if self._status_var is not None:
            self._status_var.set(self.rt.t("tabx.loading"))
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            data = self.fetch()
        except Exception as exc:        # noqa: BLE001
            self.post(lambda e=exc: self._finish_error(e))
            return
        self.post(lambda: self._finish_ok(data))

    def _finish_ok(self, data) -> None:
        self._busy = False
        self._last_data = data
        try:
            self.render(data)
        except Exception:               # noqa: BLE001 — a render slip must not wedge the tab
            if self._status_var is not None:
                self._status_var.set(self.rt.t("tabx.error"))

    def _finish_error(self, exc) -> None:
        self._busy = False
        if self._status_var is not None:
            self._status_var.set(self.rt.t("tabx.error"))

    # -- small helpers for subclasses ---------------------------------------
    def _header(self, title_key: str):
        """A title row with a «Обновить» button and a status label; returns the body
        frame the subclass fills."""
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.rt.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                   title_key).pack(side="left")
        self.rt.tr(ttk.Button(bar, width=12, command=self.refresh),
                   "tabx.refresh").pack(side="right")
        self._status_var = _stringvar(self.rt)
        ttk.Label(bar, textvariable=self._status_var, foreground="#888").pack(
            side="right", padx=8)
        body = ttk.Frame(self.parent)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        return body

    # -- the phone ----------------------------------------------------------
    def web_view(self) -> "dict | None":
        """The tab's last reading, as cards. Never reads the game (see `PanelTab`).

        The CARDS are the subclass's — :meth:`web_cards` maps its own `fetch()` shape,
        which is the only part that differs between these six tabs. Everything around
        them is here: the «Обновить» action, the «nothing read yet» state, and the
        «reading…» one, so no tab spells those three out again.
        """
        cards = []
        if self._last_data is None:
            cards = [{"empty": "tabx.loading" if self._busy else "web.ui.not_read"}]
        else:
            try:
                cards = self.web_cards(self._last_data) or []
            except Exception:            # noqa: BLE001 — a screen, never the panel
                cards = [{"empty": "tabx.error"}]
        return {"cards": cards,
                "actions": [{"id": "refresh", "label": "tabx.refresh"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """«Обновить» — the tab's own button, on the tab's own background thread."""
        if action != "refresh":
            return {"error": "unknown"}
        self.refresh()
        return {"ok": True, "busy": True}

    def web_cards(self, data) -> list:
        """This tab's reading as cards. Overridden by each of the six."""
        return []

    # subclasses override these
    def build(self) -> None: ...
    def fetch(self): ...
    def render(self, data) -> None: ...
