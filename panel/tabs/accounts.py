"""The «Аккаунты» tab: the characters on this account, and switching between them.

One row per character with everything the server says about it — nickname, server,
zone, HQ level, power and alliance tag — and a button that moves the live client onto
it. The account summary strip — the day's budgets and everything waiting for the
person — is drawn above this list by the shell (panel/dashboard.py holds what it
reads).
"""
from __future__ import annotations

import threading
from tkinter import messagebox, ttk

from ..widgets import ScrollableFrame, font as ui_font
from ._data import DataTab, _group

class AccountsTab(DataTab):
    """The characters this login can switch between — the in-game «Account» screen.

    Every character this login still has is listed with its server, zone, HQ level,
    power and alliance tag; the one you are playing right now is marked and carries no
    button. Each of the others has a «Сменить» button that reconnects the client to
    that character — exactly what tapping the row in the game does. Because a switch
    tears down the current session and reconnects, the button asks first.

    The list comes from the server, not from the client's cache of past logins —
    tools/account_switch.py asks for it the way the game's own «Персонажи» screen
    does, without opening a window. CONFIRMED against a live capture (#1190): the
    server named two characters where the cache held six rows for them. Every column
    is a field of that same answer, so nothing here is inferred.

    The button plays `actions/switch_account.md` and shows what the scenario said —
    including its refusals ("no character on that server", "already the one in play")
    and the case where the client never came back. Degrades to an empty state with no
    daemon, no game, or when the server does not answer."""

    ID = "accounts"
    TITLE_KEY = "tab.accounts"
    ORDER = 240
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    LOCALE_NS = ('accounts', 'dash', 'tabx')

    COLUMNS = ("accounts.col.name", "accounts.col.server", "accounts.col.zone",
               "accounts.col.level", "accounts.col.power", "accounts.col.alliance",
               "accounts.col.action")

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

    def web_cards(self, rows) -> list:
        """Every character this login has. The switch itself stays in the window —
        moving the client to another account is not a thumb-sized decision, and it is
        one of the few presses that cannot be undone from a bus."""
        items = []
        for row in rows or ():
            items.append({"text": str(row.get("name") or row.get("nick") or "?"),
                          "detail": str(row.get("server") or row.get("serverId") or "")})
        return [{"title": "tab.accounts", "items": items, "empty": "tabx.no_game"}]

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
            # Power is the one number worth reading across rows, so it is grouped
            # (241 514 404, not 241514404); a character that has never been played
            # reports 0, which is drawn as a dash rather than a lie about its strength.
            ttk.Label(self._scroll, text=_group(acc.get("power")) or "—").grid(
                row=r, column=4, sticky="w", padx=(0, 16))
            # The alliance TAG is all the character list carries — the full name is
            # never in it, so an empty tag means "in no alliance", not "unknown".
            ttk.Label(self._scroll, text=acc.get("alliance") or "—",
                      foreground="#888").grid(row=r, column=5, sticky="w", padx=(0, 16))
            if current:
                self.rt.tr(ttk.Label(self._scroll, foreground="#5cd679",
                                      font=ui_font(weight="bold")),
                             "accounts.current").grid(row=r, column=6, sticky="w")
            else:
                self.rt.tr(
                    ttk.Button(self._scroll, width=12,
                              command=lambda a=acc: self._switch(a)),
                    "accounts.switch").grid(row=r, column=6, sticky="w")
        n = sum(1 for a in rows if a.get("is_current"))
        self._status_var.set(self.rt.t("accounts.count", n=len(rows) - n))

    def _switch(self, acc: dict) -> None:
        """Confirm, then move the client onto ``acc`` on a background thread."""
        if self._busy:
            return
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
        """Play the scenario. The game claim is held for the whole relog: everything
        else the panel drives would be talking to a client that is logging out."""
        ok, reason = False, ""
        if not self.rt.game.claim("panel/accounts"):
            reason = self.rt.t("busy.elsewhere")
        else:
            try:
                out = self.rt.actions.play(
                    "switch_account", {"server": serverid},
                    on_event=lambda msg: self.rt.put(f"[accounts] {msg}"))
                ok, reason = bool(out), out.reason
            except Exception as exc:      # noqa: BLE001 — the log gets the reason
                reason = str(exc)
            finally:
                self.rt.game.release()
        self.post(lambda: self._switch_done(serverid, name, ok, reason))

    def _switch_done(self, serverid, name, ok, reason) -> None:
        self._busy = False
        if ok:
            self.rt.put(self.rt.t("accounts.switched", name=name, server=serverid))
        else:
            self.rt.put(self.rt.t("accounts.switch_fail", name=name,
                                  state=reason or "?"))
        self._status_var.set("")
        # The client has just relogged (or is still trying); reread who is in play.
        self.rt.tick.arm("accounts_reread", 4000, self.refresh)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(AccountsTab))
