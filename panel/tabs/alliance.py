"""The «Альянс» tab: who is in the alliance, and when each was last seen.

Roster — name / level / power / online / last seen — in a scrollable list, read live
through the warm daemon. `al.rank` is the only place that carries a per-member `online`
flag and an `offLineTime`, which is what makes «был N минут назад» possible at all
(docs/research/alliance-presence.md).
"""
from __future__ import annotations

import time
from tkinter import ttk

from ..runtime import players
from ..widgets import ScrollableFrame, font as ui_font
from ._data import DataTab, _group, _int, _marker_payloads, _run_lua

class AllianceTab(DataTab):
    """Alliance roster — name / level / power / online / last seen — in a scrollable
    grid. A stub for now: presence comes from `al.rank` (the roster screen), which the
    panel cannot sample passively, so an empty read shows a hint to open the roster."""

    ID = "alliance"
    TITLE_KEY = "tab.alliance"
    ORDER = 200
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    LOCALE_NS = ('alliance', 'tabx')

    COLUMNS = ("alliance.col.name", "alliance.col.level", "alliance.col.power",
               "alliance.col.status", "alliance.col.seen")

    def build(self) -> None:
        body = self._header("tab.alliance")
        self._scroll = ScrollableFrame(body)
        self._scroll.pack(fill="both", expand=True)
        self.rt.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                              justify="left"),
                     "alliance.hint").pack(anchor="w", padx=10, pady=(0, 10))

    def fetch(self):
        # BEST-EFFORT: try a couple of plausible roster managers; log one line per
        # member as «ALLY uid\tname\tlevel\tpower\tonline\toffLineTime».
        #
        # THE UID IS A FIELD OF A READ THAT ALREADY HAPPENS (#1371), not a second read:
        # the member objects are in hand, and without their uid the roster is five
        # facts about somebody the register cannot recognise. With it, every refresh of
        # this page tops up the register's level and power for the whole alliance.
        chunk = (
            "local M = DataCenter.AllianceMemberDataManager or "
            "DataCenter.AllianceDataManager "
            "local ok, list = pcall(function() return M:GetMemberList() end) "
            "if not ok or type(list) ~= 'table' then "
            "ok, list = pcall(function() return M.memberList end) end "
            "if type(list) == 'table' then for _, m in ipairs(list) do "
            "local u = tostring(m.uid or m.playerUid or m.uuid or '') "
            "local n = tostring(m.name or m.playerName or '?') "
            "local lv = tostring(m.level or m.lv or 0) "
            "local pw = tostring(m.power or m.armyPower or 0) "
            "local on = (m.online and 1 or 0) "
            "local off = tostring(m.offLineTime or 0) "
            "CS.UnityEngine.Debug.LogError('ALLY '..u..'\\t'..n..'\\t'..lv..'\\t'..pw"
            "..'\\t'..on..'\\t'..off) "
            "end end"
        )
        rows = []
        for payload in _marker_payloads(_run_lua(self.rt, chunk, "ALLY"), "ALLY"):
            parts = payload.split("\t")
            if len(parts) >= 6:
                uid, name, level, power, online, off = parts[:6]
                rows.append({"uid": uid, "name": name, "level": level,
                             "power": power, "online": online == "1", "off": off})
        self._register(rows)
        return rows

    def _register(self, rows) -> None:
        """Fold the roster into the register of players (#1371).

        Runs on the tab's own worker thread (`DataTab._work`), which is where `fetch`
        already is — nothing is asked of the game, this is the reply that just arrived.
        A member with no uid is skipped rather than filed under their nickname: two
        players may share a name, and a row keyed by one is a row about neither.
        """
        seen = []
        for row in rows:
            uid = (row.get("uid") or "").strip()
            if not uid or not uid.isdigit():
                continue
            seen.append({"uid": uid, "name": row.get("name") or None,
                         "level": _int(row.get("level")) or None,
                         "power": _int(row.get("power")) or None,
                         "online": bool(row.get("online"))})
        if not seen:
            return
        try:
            self.rt.players.sighted(seen, source=players.SRC_ALLIANCE)
        except Exception as exc:                                        # noqa: BLE001
            self.rt.dbg("alliance").warning("players.sighted failed: %s", exc)

    def web_cards(self, rows) -> list:
        """One card, one item per member: who, and when they were last seen."""
        items = []
        for row in rows or ():
            items.append({
                "text": str(row.get("name") or "?"),
                "detail": f"{row.get('level') or '?'} · {_group(row.get('power'))}",
                "pill": "alliance.online" if row.get("online") else None,
            })
        return [{"title": "tab.alliance", "items": items, "empty": "tabx.no_game"}]

    def render(self, rows) -> None:
        for child in self._scroll.winfo_children():
            child.destroy()
        for col, key in enumerate(self.COLUMNS):
            self.rt.tr(ttk.Label(self._scroll, foreground="#888",
                                  font=ui_font(weight="bold")), key).grid(
                row=0, column=col, sticky="w", padx=(0, 16), pady=(0, 6))
        if not rows:
            self.rt.tr(ttk.Label(self._scroll, foreground="#888"),
                         "alliance.empty").grid(row=1, column=0, columnspan=5,
                                                sticky="w", pady=6)
            self._status_var.set("")
            return
        for r, row in enumerate(rows, start=1):
            online = bool(row.get("online"))
            status = self.rt.t("alliance.online" if online else "alliance.offline")
            seen = "" if online else self._fmt_seen(row.get("off"))
            for col, text in enumerate((row.get("name") or "?",
                                        row.get("level") or "",
                                        _group(row.get("power")), status, seen)):
                ttk.Label(self._scroll, text=text).grid(
                    row=r, column=col, sticky="w", padx=(0, 16), pady=1)
        self._status_var.set(self.rt.t("alliance.count", n=len(rows)))

    def _fmt_seen(self, off_ms: str) -> str:
        try:
            off = int(off_ms)
        except (TypeError, ValueError):
            return ""
        if off <= 0:
            return ""
        import time
        mins = max(0, int((time.time() * 1000 - off) // 60000))
        if mins < 60:
            return self.rt.t("alliance.seen_min", n=mins)
        if mins < 1440:
            return self.rt.t("alliance.seen_hour", n=mins // 60)
        return self.rt.t("alliance.seen_day", n=mins // 1440)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(AllianceTab))
