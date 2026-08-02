"""The «Аккаунты» tab: the characters on this account, and switching between them.

One row per character with the server it is on; the button switches the live client to
it. The account summary strip — the day's budgets and everything waiting for the person
— is drawn above this list by the shell (panel/dashboard.py holds what it reads).
"""
from __future__ import annotations

import threading
from tkinter import messagebox, ttk

from ..widgets import ScrollableFrame, font as ui_font
from ._data import DataTab, _group, _int, _marker_payloads, _run_lua

class AccountsTab(DataTab):
    """The characters this login can switch between — the in-game «Account» screen.

    Every character this login still has is listed with its server, zone, HQ level
    and name; the one you are playing right now is highlighted and carries no button.
    Each of the others has a «Switch» button that reconnects the client to that
    character — exactly what tapping the row in the game does. Because a switch tears
    down the current session and reconnects, the button asks for confirmation first.

    What the game hands over is a cache of every login it has ever made, so one
    character shows up once per server it has ever been on and abandoned characters
    linger; tools/account_switch.py trims that to the characters themselves before we
    draw it. The read is CONFIRMED against a live client; the switch reproduces the
    game's own select handler. Degrades to an empty state with no daemon, no game, or
    before the account manager has loaded."""

    ID = "accounts"
    TITLE_KEY = "tab.accounts"
    ORDER = 240
    LOCALE_NS = ('accounts', 'dash', 'tabx')

    COLUMNS = ("accounts.col.name", "accounts.col.server", "accounts.col.zone",
               "accounts.col.level", "accounts.col.action")
    #: A faint tint on the row of the character currently in play.
    _CURRENT_BG = "#2a4d33"

    def build(self) -> None:
        body = self._header("tab.accounts")
        self._scroll = ScrollableFrame(body)
        self._scroll.pack(fill="both", expand=True)
        self.rt.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                              justify="left"),
                     "accounts.hint").pack(anchor="w", padx=10, pady=(0, 10))

    def fetch(self):
        try:
            import account_switch      # tools/ is on sys.path once the panel started
            import lua_client
            ev = lua_client.get_evaluator(port=self.rt.game.port())
            return account_switch.read_accounts(ev)
        except Exception:              # noqa: BLE001 — a failed read is an empty tab
            return []

    def render(self, rows) -> None:
        for child in self._scroll.winfo_children():
            child.destroy()
        for col, key in enumerate(self.COLUMNS):
            self.rt.tr(ttk.Label(self._scroll, foreground="#888",
                                  font=ui_font(weight="bold")), key).grid(
                row=0, column=col, sticky="w", padx=(0, 16), pady=(0, 6))
        if not rows:
            self.rt.tr(ttk.Label(self._scroll, foreground="#888"),
                         "accounts.empty").grid(row=1, column=0, columnspan=len(self.COLUMNS),
                                                sticky="w", pady=6)
            self._status_var.set(self.rt.t("tabx.no_game"))
            return
        for r, acc in enumerate(rows, start=1):
            current = acc.get("is_current")
            name = acc.get("nickname") or f"#{acc.get('gameUid', '')}"
            weight = "bold" if current else "normal"
            ttk.Label(self._scroll, text=name,
                     font=ui_font(weight=weight)).grid(
                row=r, column=0, sticky="w", padx=(0, 16), pady=2)
            ttk.Label(self._scroll, text=str(acc.get("serverid", ""))).grid(
                row=r, column=1, sticky="w", padx=(0, 16))
            ttk.Label(self._scroll, text=acc.get("zone", ""), foreground="#888").grid(
                row=r, column=2, sticky="w", padx=(0, 16))
            ttk.Label(self._scroll, text=str(acc.get("level") or "—")).grid(
                row=r, column=3, sticky="w", padx=(0, 16))
            if current:
                self.rt.tr(ttk.Label(self._scroll, foreground="#5cd679",
                                      font=ui_font(weight="bold")),
                             "accounts.current").grid(row=r, column=4, sticky="w")
            else:
                self.rt.tr(
                    ttk.Button(self._scroll, width=12,
                              command=lambda a=acc: self._switch(a)),
                    "accounts.switch").grid(row=r, column=4, sticky="w")
        n = sum(1 for a in rows if a.get("is_current"))
        self._status_var.set(self.rt.t("accounts.count", n=len(rows) - n))

    def _switch(self, acc: dict) -> None:
        """Confirm, then reconnect the client to ``acc`` on a background thread."""
        if self._busy:
            return
        from tkinter import messagebox
        name = acc.get("nickname") or acc.get("serverid")
        if not messagebox.askyesno(
                self.rt.t("tab.accounts"),
                self.rt.t("accounts.confirm", name=name, server=acc.get("serverid")),
                parent=self.rt.root):
            return
        self._busy = True
        self._status_var.set(self.rt.t("accounts.switching"))
        serverid = acc.get("serverid")
        threading.Thread(target=self._switch_work, args=(serverid, name),
                         daemon=True).start()

    def _switch_work(self, serverid, name) -> None:
        state = ""
        try:
            import account_switch
            import lua_client
            ev = lua_client.get_evaluator(port=self.rt.game.port())
            state = account_switch.switch_account(ev, serverid)
        except Exception:              # noqa: BLE001
            state = ""
        self.rt.root.after(0, lambda: self._switch_done(serverid, name, state))

    def _switch_done(self, serverid, name, state) -> None:
        self._busy = False
        if state == "sent":
            self.rt.put(self.rt.t("accounts.switched", name=name,
                                          server=serverid))
        else:
            self.rt.put(self.rt.t("accounts.switch_fail", name=name,
                                          state=state or "?"))
        # The client is reconnecting; give it a moment, then reread the list.
        self.rt.tick.arm("accounts_reread", 4000, self.refresh)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(AccountsTab))
