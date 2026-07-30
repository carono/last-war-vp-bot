"""The «Secret Tasks» tab: the starred hero-dispatch tiles the alliance can raid.

The client already keeps a parsed, always-current copy of the alliance's secret
tasks in `ActDispatchTaskDataManager.allianceTask`; `steal_secret_task._vm_raidable_tasks`
reads the raidable ones straight out of the live VM through the warm daemon (dispatch
finished, not expired, a free loot slot) with no capture and no map panning. This tab
keeps the **starred** ones — the raids worth a march — on screen, counts each tile's
expiry down every second, and offers the two things a person does with one: rob it
(`hero.dispatch.steal`) or forward it into chat.

What is on the tab is an in-memory list for the session, not a store — closing the
panel forgets it, which is fine: the list is re-read from the game the moment the tab
is opened again. While the «secret_task_share» trigger is switched on, an alliancemate
sharing a task (`alliance.share.mission.add`) re-reads the game so the new tile appears
without a manual «Обновить».

Kept Tk-thin: the two game round trips (scan, steal) and the share run on background
threads and degrade gracefully — no daemon, no game, or a manager not loaded yet leaves
the list empty and never crashes the tab.
"""
from __future__ import annotations

import threading

import customtkinter as ctk

from .ctk_widgets import CTkButton, CTkFrame, CTkLabel
from .tabs_extra import tk_stringvar

# The star glyph in front of a row and the icon that says «secret task».
STAR_GLYPH = "⭐"
TYPE_GLYPH = "🗡️"

# The two channels a task can be forwarded to. The room ids are built from the
# player's own server / alliance, read once and cached (see `_self_ids`).
SHARE_ALLIANCE = "alliance"
SHARE_WORLD = "world"


class SecretTasksTab:
    """The starred-secret-task list, its per-second timers and its two actions.

    Not a :class:`panel.tabs_extra._DataTab`: the countdown loop, the per-row buttons
    and the collected/expired bookkeeping do not fit the load-once/refresh shape. The
    threading is the same idea, though — :meth:`fetch` runs off the Tk thread and the
    render is marshalled back with ``app.after``.
    """

    def __init__(self, app, parent) -> None:
        self.app = app
        self.parent = parent
        self._loaded = False
        self._busy = False
        self._ticking = False
        # uuid (str) -> row record. The record carries the task data, its countdown
        # StringVar and the row's frame, so a tick can update the timer in place and a
        # collect/clear can drop the row without a full re-read.
        self._rows: dict[str, dict] = {}
        # Tasks robbed by hand this session: a rescan must not re-add one that the
        # server has not yet dropped from `allianceTask`.
        self._collected: set[str] = set()
        # Cached (server, allianceId) for the chat room ids — read once, live.
        self._ids: tuple[str, str] | None = None
        self._status_var = None
        self._build()

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """First time the tab is shown: start the countdown loop and read the game."""
        if not self._loaded:
            self._loaded = True
            self._start_ticking()
            self.refresh()

    def refresh(self) -> None:
        """Re-read the raidable starred tasks and merge them into the list."""
        if self._busy:
            return
        self._busy = True
        if self._status_var is not None:
            self._status_var.set(self.app._t("tabx.loading"))
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            tasks = self._fetch()
        except Exception:                     # noqa: BLE001 — a failed read is an empty tab
            tasks = []
        self.app.after(0, lambda: self._merge(tasks))

    # -- reading the game ---------------------------------------------------
    def _fetch(self) -> list:
        """The raidable, starred alliance secret tasks, straight from the live VM.

        Reuses `steal_secret_task._vm_raidable_tasks`, the one reader the auto-loot
        already trusts, so a tile shown here is picked identically to one it would rob.
        """
        import lua_client
        import steal_secret_task
        ev = lua_client.get_evaluator(port=self.app._daemon_port())
        tasks = steal_secret_task._vm_raidable_tasks(ev)
        return [t for t in tasks if t.starred and t.can_loot]

    def _merge(self, tasks) -> None:
        """Add tiles the list does not have yet; keep the ones it does.

        A rescan only ADDS — an existing row keeps its place and its timer, a tile
        robbed by hand this session is skipped, and nothing already on screen is torn
        out from under the operator. Expiry is the tick loop's job.
        """
        self._busy = False
        added = 0
        for t in tasks:
            key = str(t.uuid)
            if key in self._rows or key in self._collected:
                continue
            self._rows[key] = {
                "uuid": t.uuid, "server": t.server_id, "x": t.x, "y": t.y,
                "level": t.level, "cfg_id": t.cfg_id,
                "expires_at": t.expires_at, "completed_at": t.completed_at,
                "timer": tk_stringvar(self.app), "frame": None,
            }
            added += 1
        self._render()
        if self._status_var is not None:
            # An empty list after a clean read is "no starred tile right now", not "no
            # game" — the scroll's own hint says so, so the status stays blank rather
            # than crying about a game that may be perfectly up.
            self._status_var.set(self.app._t("secrettasks.count", n=len(self._rows))
                                 if self._rows else "")

    # -- UI -----------------------------------------------------------------
    def _build(self) -> None:
        bar = CTkFrame(self.parent, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.app._tr(CTkLabel(bar, font=ctk.CTkFont(size=15, weight="bold")),
                     "tab.secret_tasks").pack(side="left")
        self.app._tr(CTkButton(bar, width=12, command=self.refresh),
                     "tabx.refresh").pack(side="right")
        self.app._tr(CTkButton(bar, width=12, command=self._clear),
                     "secrettasks.clear").pack(side="right", padx=(0, 6))
        self._status_var = tk_stringvar(self.app)
        CTkLabel(bar, textvariable=self._status_var, text_color="#888").pack(
            side="right", padx=8)

        self.app._tr(CTkLabel(self.parent, text_color="#888", wraplength=640,
                              justify="left"), "secrettasks.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

        self._scroll = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _render(self) -> None:
        """Rebuild the scroll from the current rows, newest raids on top.

        Sorted the way the auto-loot prizes them: the highest star first, and within a
        level the tile that expires soonest — the one a person would grab before it is
        gone. Called on a merge / collect / clear, NOT every second: the countdown is a
        StringVar the tick loop writes in place.
        """
        for child in self._scroll.winfo_children():
            child.destroy()
        if not self._rows:
            self.app._tr(CTkLabel(self._scroll, text_color="#888"),
                         "secrettasks.empty").grid(row=0, column=0, sticky="w", pady=6)
            return
        rows = sorted(self._rows.values(),
                      key=lambda r: (-int(r["level"] or 0),
                                     r["expires_at"] or float("inf")))
        for r in rows:
            r["frame"] = self._row_widget(r)
            r["frame"].pack(fill="x", pady=1)
        self._refresh_timers()

    # The row is packed left-to-right: icon, stars, coords, countdown, uuid, then the
    # two action buttons on the right. Built one row at a time (not a shared grid) so a
    # collect can drop a single row without re-flowing the columns of the rest.
    def _row_widget(self, row):
        import coords as coords_fmt
        frame = CTkFrame(self._scroll, fg_color="transparent")
        CTkLabel(frame, text=TYPE_GLYPH, font=ctk.CTkFont(size=15)).pack(
            side="left", padx=(0, 6))
        CTkLabel(frame, text=self.app._t("secrettasks.stars", n=int(row["level"] or 0)),
                 font=ctk.CTkFont(weight="bold"), width=52).pack(side="left", padx=(0, 8))
        CTkLabel(frame, text=coords_fmt.fmt(row["x"], row["y"], row["server"]),
                 width=110).pack(side="left", padx=(0, 8))
        CTkLabel(frame, textvariable=row["timer"], text_color="#e0a84f",
                 width=150, anchor="w").pack(side="left", padx=(0, 8))
        CTkLabel(frame, text=self._short_uuid(row["uuid"]), text_color="#888").pack(
            side="left", padx=(0, 8))
        share = CTkButton(frame, width=12)
        share.configure(command=lambda b=share, r=row: self._open_share_menu(b, r))
        self.app._tr(share, "secrettasks.share").pack(side="right", padx=(4, 0))
        self.app._tr(CTkButton(frame, width=12,
                               command=lambda r=row: self._collect(r)),
                     "secrettasks.collect").pack(side="right")
        return frame

    @staticmethod
    def _short_uuid(uuid) -> str:
        """The last 8 digits of a uuid — the full value is 18+ digits and only its
        tail tells two tiles apart on screen."""
        s = str(uuid)
        return "…" + s[-8:] if len(s) > 8 else s

    # -- the countdown ------------------------------------------------------
    def _start_ticking(self) -> None:
        if not self._ticking:
            self._ticking = True
            self._tick()

    def _tick(self) -> None:
        """Every second: write each row's remaining time, drop the ones that expired.

        A tile that has run out is off the map and can no longer be robbed, so it comes
        off the list on its own — the operator never presses «Собрать» on a dead tile.
        """
        try:
            expired = self._refresh_timers()
            if expired:
                for key in expired:
                    self._rows.pop(key, None)
                self._render()
                if self._status_var is not None and self._rows:
                    self._status_var.set(self.app._t("secrettasks.count", n=len(self._rows)))
        finally:
            try:
                self.app.after(1000, self._tick)
            except Exception:                 # noqa: BLE001 — panel gone, stop ticking
                self._ticking = False

    def _refresh_timers(self) -> list:
        """Set every row's countdown text; return the keys of rows that have expired."""
        import time
        now = int(time.time() * 1000)
        expired = []
        for key, row in self._rows.items():
            exp = row["expires_at"]
            if exp is None:
                row["timer"].set(self.app._t("secrettasks.left", t="—"))
                continue
            left = exp - now
            if left <= 0:
                expired.append(key)
                continue
            row["timer"].set(self.app._t("secrettasks.left", t=_fmt_left(left)))
        return expired

    # -- actions ------------------------------------------------------------
    def _collect(self, row) -> None:
        """Rob one tile: `hero.dispatch.steal {uuid, targetServer}`, off the Tk thread.

        The steal is budget-gated in the VM (a spent account sends nothing), so a
        confirmed send is the honest success signal here — whether the server pays out
        is its call, the same as every other route into the robbery.
        """
        key = str(row["uuid"])

        def work():
            ok = False
            try:
                import lua_actions
                import lua_client
                ev = lua_client.get_evaluator(port=self.app._daemon_port())
                lines = ev.run(lua_actions.secret_task_steal(int(row["uuid"]),
                                                             int(row["server"])),
                               marker="ACT", settle=1.4)
                ok = any("steal_sent" in ln for ln in (lines or []))
            except Exception:                 # noqa: BLE001
                ok = False
            self.app.after(0, lambda: self._collect_done(key, ok))

        threading.Thread(target=work, daemon=True).start()

    def _collect_done(self, key: str, ok: bool) -> None:
        if ok:
            self._collected.add(key)
            self._rows.pop(key, None)
            self._render()
            self.app._log_put("[secret] " + self.app._t("secrettasks.collect_ok"))
            if self._status_var is not None:
                self._status_var.set(self.app._t("secrettasks.count", n=len(self._rows)))
        else:
            self.app._log_put("[secret] " + self.app._t("secrettasks.collect_fail"))

    def _open_share_menu(self, button, row) -> None:
        """Pop the «alliance / world» choice under the «Поделиться» button."""
        import tkinter as tk
        menu = tk.Menu(self.app, tearoff=0)
        menu.add_command(label=self.app._t("secrettasks.share_alliance"),
                         command=lambda: self._share(row, SHARE_ALLIANCE))
        menu.add_command(label=self.app._t("secrettasks.share_world"),
                         command=lambda: self._share(row, SHARE_WORLD))
        try:
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _share(self, row, scope: str) -> None:
        """Forward one tile into the alliance or world chat, off the Tk thread.

        Outgoing chat cannot be unsent, but the target is a raidable star the operator
        chose from a menu — the same deliberate act as the in-game share button.
        """
        def work():
            ok = False
            try:
                import chat_share
                import lua_client
                ev = lua_client.get_evaluator(port=self.app._daemon_port())
                room = self._room_id(ev, scope)
                att = chat_share.task_attachment({
                    "x": row["x"], "y": row["y"], "srv": row["server"],
                    "uuid": row["uuid"], "cfgId": row["cfg_id"],
                    "name": "", "abbr": ""})
                ok = bool(room) and chat_share.share_point(ev, room, att)
            except Exception:                 # noqa: BLE001
                ok = False
            self.app.after(0, lambda: self._share_done(scope, ok))

        threading.Thread(target=work, daemon=True).start()

    def _share_done(self, scope: str, ok: bool) -> None:
        where = self.app._t("secrettasks.share_alliance" if scope == SHARE_ALLIANCE
                            else "secrettasks.share_world")
        key = "secrettasks.shared_ok" if ok else "secrettasks.share_fail"
        self.app._log_put("[secret] " + self.app._t(key, where=where))

    def _room_id(self, ev, scope: str) -> str:
        srv, aid = self._self_ids(ev)
        if scope == SHARE_WORLD:
            return "country_%s" % srv if srv else ""
        if scope == SHARE_ALLIANCE:
            return "alliance_%s_%s" % (srv, aid) if srv and aid else ""
        return ""

    def _self_ids(self, ev) -> tuple[str, str]:
        """`(serverId, allianceId)` for the logged-in player — read once, then cached.

        The chat room ids are `country_<server>` and `alliance_<server>_<allianceId>`;
        both come straight off `ChatInterface`. Cached for the session because they do
        not change while the panel is open.
        """
        if self._ids is not None:
            return self._ids
        chunk = (
            "pcall(function() "
            "local uid = ChatInterface.getPlayerUid() "
            "local srv = ChatInterface.getSelfServerId() "
            "local ud = ChatInterface.getUserData(uid) "
            "local aid = ud and ud.allianceId or '' "
            "CS.UnityEngine.Debug.LogError('ACT selfids srv='..tostring(srv)"
            "..' aid='..tostring(aid)) end)"
        )
        srv = aid = ""
        for ln in ev.run(chunk, marker="ACT", settle=1.0) or ():
            if "selfids " not in ln:
                continue
            for tok in ln.split("selfids ", 1)[1].split(" "):
                k, sep, v = tok.partition("=")
                if sep and k == "srv":
                    srv = v.strip()
                elif sep and k == "aid":
                    aid = v.strip()
        if srv or aid:
            self._ids = (srv, aid)            # cache only a real read, retry a blank one
        return (srv, aid)

    def _clear(self) -> None:
        """«Очистить список»: drop the expired and hand-collected rows.

        Expired tiles fall off on their own each second; this is the manual «tidy now»
        that also forgets the session's collected set, so a task robbed earlier can be
        re-listed by the next scan if the server still shows it raidable.
        """
        import time
        now = int(time.time() * 1000)
        for key in list(self._rows):
            exp = self._rows[key]["expires_at"]
            if exp is not None and exp <= now:
                self._rows.pop(key, None)
        self._collected.clear()
        self._render()
        if self._status_var is not None:
            self._status_var.set(self.app._t("secrettasks.count", n=len(self._rows))
                                 if self._rows else "")


def _fmt_left(ms: int) -> str:
    """Milliseconds remaining as ``H:MM:SS`` (or ``MM:SS`` under an hour).

    Locale-neutral on purpose: the surrounding «expires in …» carries the language, the
    clock itself does not need translating.
    """
    total = max(0, ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)
