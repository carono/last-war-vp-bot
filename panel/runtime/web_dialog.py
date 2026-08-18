"""«Веб»: the switch, the address and the token — one section of «Параметры» (#1313, #1509).

The knobs behind it are the WINDOW's (`panel/runtime/web_control.py`), so a page inside
one profile was the wrong shape for them: whichever profile you happened to be looking
at drew a copy of one answer, and the other profiles drew the same answer again with a
different label on it. It used to be its own entry on the menu bar (#1313); now it is
one row in the sidebar of the single «Параметры» modal (`panel/runtime/settings_dialog.py`,
#1509) beside «Профиль», «Язык» and «Автозапуск» — every switch that belongs to the
window rather than to an account, behind one door instead of four.

THE PHONE HAS NO COPY OF THIS, on purpose and by agreement — it is the door the person
came in through, and managing the door from the far side of it is how somebody locks
themselves out. `CLAUDE.md` and `docs/panel-tabs.md` carry the reasoning and
`tests/test_panel_web_screens.py` pins it.
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from . import web_control


def build(parent, rt_get, t) -> "_WebSection":
    """Build the section INTO ``parent`` — a content frame `settings_dialog.py` owns.

    ``rt_get()`` is the profile on screen NOW. A callable rather than a runtime because
    the section outlives a profile switch: the log line a press produces belongs in
    whichever profile the person is looking at when they press it, not in the one that
    was showing when the modal opened.
    """
    return _WebSection(parent, rt_get, t)


class _WebSection:
    """Six knobs, three buttons and the link to type into a phone."""

    def __init__(self, parent, rt_get, t) -> None:
        self._rt_get = rt_get
        self._t = t
        values = web_control.settings()

        self._on = tk.BooleanVar(value=bool(values["enabled"]))
        self._port = tk.StringVar(value=values["port"])
        self._host = tk.StringVar(value=values["host"])
        self._token = tk.StringVar(value=values["token"])
        self._cert = tk.StringVar(value=values["cert"])
        self._key = tk.StringVar(value=values["key"])

        frm = ttk.Frame(parent)
        frm.pack(fill="both", expand=True)
        self._frame = frm

        head = ttk.Frame(frm)
        head.pack(fill="x")
        ttk.Checkbutton(head, text=t("web.enabled"), variable=self._on,
                        command=self._toggled).pack(side="left")
        self._state = ttk.Label(head, text="")
        self._state.pack(side="right")

        # THE ONE SENTENCE THAT EXPLAINS WHY THIS IS NOT ON A TAB. Without it the person
        # who has three profiles open has no way to tell whether they are setting all of
        # them or only the one whose page is behind this modal.
        ttk.Label(frm, text=t("web.shared"), foreground="#888", wraplength=480,
                  justify="left").pack(anchor="w", pady=(6, 0))

        grid = ttk.Frame(frm)
        grid.pack(fill="x", pady=(8, 0))
        rows = ((t("web.port"), self._port, 8), (t("web.host"), self._host, 16),
                (t("web.token"), self._token, 24), (t("web.cert"), self._cert, 24),
                (t("web.key"), self._key, 24))
        for row, (label, var, width) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w",
                                             pady=(0 if not row else 4, 0))
            ttk.Entry(grid, textvariable=var, width=width).grid(
                row=row, column=1, sticky="w", padx=6, pady=(0 if not row else 4, 0))
        ttk.Button(grid, text=t("web.token.new"), command=self._new_token).grid(
            row=2, column=2, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(frm)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text=t("web.apply"), command=self._apply_now).pack(
            side="left")
        ttk.Button(buttons, text=t("web.copy"), command=self._copy).pack(
            side="left", padx=6)
        ttk.Button(buttons, text=t("web.open"), command=self._open).pack(side="left")

        ttk.Label(frm, text=t("web.address")).pack(anchor="w", pady=(12, 0))
        # An Entry rather than a Label so the address can be selected and copied on a
        # machine where the clipboard button is not what the person reaches for.
        self._link = ttk.Entry(frm)
        self._link.pack(fill="x")
        ttk.Label(frm, text=t("web.hint"), wraplength=480,
                  justify="left").pack(anchor="w", pady=(10, 0))
        ttk.Label(frm, text=t("web.https"), wraplength=480,
                  justify="left").pack(anchor="w", pady=(8, 0))
        # Not a fixed label: which of the two warnings is true depends on whether the
        # server answering has a certificate, so `_paint` says it.
        self._warning = ttk.Label(frm, wraplength=480, justify="left")
        self._warning.pack(anchor="w", pady=(6, 0))
        self._paint()

    # -- the switch ---------------------------------------------------------
    def _fields(self) -> dict:
        return {"enabled": bool(self._on.get()), "port": self._port.get().strip(),
                "host": self._host.get().strip(), "token": self._token.get().strip(),
                "cert": self._cert.get().strip(), "key": self._key.get().strip()}

    def _toggled(self) -> None:
        web_control.save(self._fields())
        web_control.apply(self._rt_get())
        self._reload()

    def _apply_now(self) -> None:
        """«Применить» — a knob was retyped, so let the socket go and bind it again."""
        web_control.save(self._fields())
        web_control.restart(self._rt_get())
        self._reload()

    def _new_token(self) -> None:
        web_control.save(self._fields())
        token = web_control.new_token()
        self._token.set(token)
        self._rt_say("web.log.token")
        if web_control.running():
            web_control.restart(self._rt_get())
        self._reload()

    def _copy(self) -> None:
        try:
            top = self._frame.winfo_toplevel()
            top.clipboard_clear()
            top.clipboard_append(web_control.address())
        except tk.TclError:                   # no clipboard, no crash
            return
        self._rt_say("web.log.copied")

    def _open(self) -> None:
        """Open it here, on the machine the panel is on — the quickest way to look."""
        try:
            webbrowser.open(web_control.address())
        except Exception as exc:             # noqa: BLE001
            self._rt_say("web.log.error", error=exc)

    # -- what the section shows ----------------------------------------------
    def _reload(self) -> None:
        """Re-read the saved answer: a failure to bind switches the setting back off."""
        values = web_control.settings()
        self._on.set(bool(values["enabled"]))
        self._token.set(values["token"])
        self._paint()

    def _paint(self) -> None:
        if not self._frame.winfo_exists():
            return
        server = web_control.serving()
        self._state.configure(
            text=self._t("web.state.on", port=server.bound_port()) if server is not None
            else self._t("web.state.off"))
        self._link.delete(0, "end")
        if server is not None:
            self._link.insert(0, web_control.address())
        self._warning.configure(text=self._t(
            "web.warning.tls" if web_control.scheme() == "https" else "web.warning"))

    def _rt_say(self, key: str, **fmt) -> None:
        try:
            self._rt_get().say(web_control.TAG, key, **fmt)
        except Exception:                    # noqa: BLE001 — a log line, never the section
            pass
