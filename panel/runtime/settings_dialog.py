"""«Параметры»: one modal, a sidebar of sections, one door for every window-wide switch
(#1509).

There used to be four doors: «Профиль», «Веб», «Автозапуск» each its own entry on the
menu bar, «Язык» its own cascade. All four are the same KIND of thing —
`docs/panel-tabs.md` calls it out explicitly: a switch that belongs to the WINDOW rather
than to an account, so a page inside one profile would draw one answer with a different
account's name over it. Four separate doors to the same kind of room is not an
organising principle, it is a menu bar that grew one command at a time; a modern
settings dialog is one door with a list on the side.

THIS MODULE OWNS ONLY THE SHAPE — the Toplevel, the sidebar list, the content frame that
gets cleared and rebuilt when a row is picked. It knows nothing about profiles, the web
server or the scheduled task: those stay exactly where they were
(`panel/runtime/web_dialog.py`, `panel/runtime/autostart_dialog.py`) or, for «Профиль»
and «Язык» — which reach deep into the shell's own state (the workspace, the session
list, the translator) — as methods on `Panel` itself (`panel/__main__.py`). Each section
is handed to :func:`open_dialog` as a :class:`Section`: an id, a label key, and a
``build(parent) -> handle-or-None`` callable that fills ``parent`` with widgets. Nothing
here presses the game or reads a profile; it is UI plumbing only, same as
`panel/widgets.py`.

ONE MODAL AT A TIME. A second «Параметры» raises the one that is already open rather
than drawing a second copy of the same four sections — exactly the singleton the four
separate dialogs each kept for themselves before this replaced them.

CALLED «ПАРАМЕТРЫ», NOT «НАСТРОЙКИ». Every profile already has a tab by that name
(`panel/tabs/settings.py`, ``tab.settings``) — an account's own paths, budgets and
daemon. Naming this modal the same word would put it over two different things a
person has to tell apart at a glance: one belongs to the window, the other to
whichever profile is open. The menu key is `menu.settings`; what it SAYS differs from
the tab on purpose, in all eleven locales.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

#: The one dialog this process has open, if any.
_OPEN = None


class Section:
    """One row in the sidebar: an id, a label KEY, and what to draw when it is picked."""

    __slots__ = ("id", "label_key", "build")

    def __init__(self, section_id: str, label_key: str, build) -> None:
        self.id = section_id
        self.label_key = label_key
        self.build = build


def open_dialog(parent, sections, t, *, initial: str | None = None,
                on_close=None) -> "tk.Toplevel | None":
    """Show the modal, or raise it if it is already open.

    ``on_close`` is called once the window is gone — the shell's chance to forget
    whatever widget references a section handed it (`Panel._on_settings_dialog_closed`).
    """
    global _OPEN
    if _OPEN is not None and _OPEN.alive():
        _OPEN.lift()
        if initial:
            _OPEN.select(initial)
        return _OPEN.win
    _OPEN = _SettingsDialog(parent, sections, t, initial=initial, on_close=on_close)
    return _OPEN.win


def close_dialog() -> None:
    """Shut it if it is open — the window is closing."""
    global _OPEN
    dialog, _OPEN = _OPEN, None
    if dialog is not None:
        dialog.destroy()


class _SettingsDialog:
    """The modal itself: a `Listbox` on the left, one section's widgets on the right."""

    def __init__(self, parent, sections, t, *, initial: str | None = None,
                on_close=None) -> None:
        self._sections = list(sections)
        self._t = t
        self._on_close = on_close
        self._handle = None

        self.win = win = tk.Toplevel(parent)
        win.title(t("menu.settings"))
        win.transient(parent)
        win.protocol("WM_DELETE_WINDOW", self._close)
        win.geometry("760x520")
        win.minsize(600, 400)

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        side = ttk.Frame(body, width=180)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._list = tk.Listbox(side, exportselection=False, activestyle="none",
                                highlightthickness=0, bd=0)
        self._list.pack(fill="both", expand=True)
        for section in self._sections:
            self._list.insert("end", t(section.label_key))
        self._list.bind("<<ListboxSelect>>", self._on_select)

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=(10, 10))

        content = ttk.Frame(body)
        content.pack(side="left", fill="both", expand=True)
        self._content = content

        bottom = ttk.Frame(win)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bottom, text=t("profile.close"), command=self._close).pack(
            side="right")

        start_at = 0
        if initial:
            for i, section in enumerate(self._sections):
                if section.id == initial:
                    start_at = i
                    break
        self._list.selection_set(start_at)
        self._show(start_at)

        win.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - win.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - win.winfo_height()) // 4)
        win.geometry(f"+{x}+{y}")
        win.focus_set()

    def _on_select(self, _event=None) -> None:
        sel = self._list.curselection()
        if sel:
            self._show(sel[0])

    def _show(self, index: int) -> None:
        """Throw the previous section's widgets away and build the picked one.

        No section is kept alive off screen: every one of them is built off a live
        reading when it is opened (`web_control.settings()`, `autostartmod.status()`,
        the profile list), so redrawing from scratch costs a read that was going to
        happen on the next look anyway and never leaves a stale row behind.
        """
        handle, self._handle = self._handle, None
        if handle is not None and hasattr(handle, "destroy"):
            try:
                handle.destroy()
            except Exception:                # noqa: BLE001 — a section, never the modal
                pass
        for child in self._content.winfo_children():
            child.destroy()
        self._handle = self._sections[index].build(self._content)

    def select(self, section_id: str) -> None:
        for i, section in enumerate(self._sections):
            if section.id == section_id:
                self._list.selection_clear(0, "end")
                self._list.selection_set(i)
                self._show(i)
                return

    # -- lifecycle ------------------------------------------------------------
    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        try:
            self.win.lift()
            self.win.focus_set()
        except tk.TclError:
            pass

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def _close(self) -> None:
        global _OPEN
        handle, self._handle = self._handle, None
        if handle is not None and hasattr(handle, "destroy"):
            try:
                handle.destroy()
            except Exception:                # noqa: BLE001
                pass
        _OPEN = None
        cb, self._on_close = self._on_close, None
        self.destroy()
        if cb is not None:
            cb()
