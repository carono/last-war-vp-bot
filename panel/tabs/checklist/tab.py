"""The «Чеклист» tab: what this account does every day, and what is left of it today.

A LIST THE PERSON WRITES, not one the panel knows. It starts empty on purpose — every
account plays a different day, and a list somebody else wrote is a list you scroll past
rather than read. Add the errands you actually do, in the order you do them, and the tab
answers one question all day: what is still outstanding.

Three things it does beyond holding ticks:

* **It clears itself on the game's day, not on this computer's.** A tick is stamped with
  the game-day it was made on and «done» is «that stamp is today» (:mod:`.model`), so
  nothing has to be running at the reset for the list to be right the next morning.
  The hour the day rolls over at is a box, because a server's reset is not everybody's
  midnight.
* **An errand may name a scenario.** Then the row grows a «Выполнить» button that plays
  that `actions/*.md` and ticks the box itself when the scenario says it worked. The
  panel plays scenarios and writes none (`CLAUDE.md`) — this tab assembles nothing, holds
  no gate and knows nothing about what any of them do; it runs the name it was given and
  believes the outcome.
* **It is on the phone too**, with the ticking, the running and the reset — see
  :meth:`web_view`. What is NOT on the phone is EDITING the list: adding, renaming,
  re-ordering and deleting stay in the window, because the web front-end has no text
  field at all (`panel/web/static/app.js` draws cards and buttons and nothing else) and
  growing one for this would be a change to every screen rather than to this tab. Agreed
  with the operator and written down in `CLAUDE.md` and `docs/panel-tabs.md`; pinned by
  `tests/test_panel_checklist.py`.

Nothing here is a schedule. «Таймеры» is the tab that makes something happen on a clock;
this is the paper by the keyboard — including for the errands nothing in the bot can do
yet, which is most of a real day (`docs/farming.md`).
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from ...runtime import list_actions
from ...widgets import ScrollableFrame, numeric_spinbox, tk_stringvar
from ..base import PanelTab
from . import model as modelmod


class ChecklistTab(PanelTab):
    """The list, the ticks, the countdown to the reset — and one press per row."""

    ID = "checklist"
    TITLE_KEY = "tab.checklist"
    ORDER = 20
    PREFERRED_SIZE = "720x620"
    LOCALE_NS = ("checklist",)
    #: Only what a row with a scenario spends. A list of things a person does by hand
    #: needs nothing at all, which is why this tab opens with the client down.
    NEEDS = frozenset({"actions"})
    WEB_SCREEN = True

    #: How often the countdown is redrawn, and the day re-asked. Half a minute is far
    #: more often than a day boundary and cheap enough to leave running: it reads a
    #: clock and sets one string.
    TICK_MS = 30_000

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._list = modelmod.Checklist()
        self._body = None               # the scrollable area the rows live in
        self._status = None             # StringVar: «сделано 3 из 8 · до сброса 5:12»
        self._hour_var = None           # the hour the day rolls over at
        self._rows: dict = {}           # uid -> the BooleanVar of its box
        #: The day the rows on screen were drawn for — how the tick notices midnight.
        self._drawn_day = None
        #: Which uids have a scenario in flight, so a second press cannot start it twice.
        self._running: set = set()

    # -- the tab ------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Button(bar, command=self._on_add), "checklist.add").pack(side="left")
        self.tr(ttk.Button(bar, command=self._on_reset),
                "checklist.reset").pack(side="left", padx=(6, 0))

        self._hour_var = tk.StringVar(master=self.rt.root, value="0")
        self.tr(ttk.Label(bar), "checklist.reset_hour").pack(side="left", padx=(18, 4))
        numeric_spinbox(bar, from_=0, to=23, width=4,
                        textvariable=self._hour_var).pack(side="left")
        self._hour_var.trace_add("write", lambda *_a: self._on_hour())

        self._status = tk_stringvar(self.rt.root)
        ttk.Label(self.parent, textvariable=self._status,
                  foreground="#888").pack(anchor="w", padx=10)

        self._body = ScrollableFrame(self.parent)
        self._body.pack(fill="both", expand=True, padx=6, pady=(6, 10))
        self._render()

    def ensure_loaded(self) -> None:
        """The countdown, and the watch on the day. No game, no file — a clock."""
        self._tick()

    def on_show(self) -> None:
        self._refresh_status()

    def on_language_change(self) -> None:
        self._refresh_status()

    def on_profile_switch(self) -> None:
        """A different account's day. The container re-applies the config; this only
        makes sure nothing of the old one is still drawn if it does not."""
        self._render()

    def shutdown(self) -> None:
        self.rt.tick.disarm("checklist_day")

    # -- the clock ----------------------------------------------------------
    def _tick(self) -> None:
        """Redraw the countdown, and the whole list when the day has turned over."""
        try:
            if self._drawn_day is not None and self._list.today() != self._drawn_day:
                self._render()
            else:
                self._refresh_status()
        finally:
            self.rt.tick.arm("checklist_day", self.TICK_MS, self._tick)

    def _refresh_status(self) -> None:
        if self._status is None:
            return
        day = self._list.today()
        try:
            self._status.set(self.t("checklist.status",
                                    done=self._list.done_count(day),
                                    total=len(self._list.items),
                                    left=modelmod.hhmm(self._list.seconds_to_reset())))
        except tk.TclError:                 # the window is going away
            pass

    # -- the rows -----------------------------------------------------------
    def _render(self) -> None:
        """Rebuild every row. Cheap — a checklist is tens of lines, not thousands."""
        if self._body is None:
            return
        for child in list(self._body.winfo_children()):
            child.destroy()
        self._rows.clear()
        day = self._list.today()
        self._drawn_day = day

        if not self._list.items:
            self.tr(ttk.Label(self._body, foreground="#888", wraplength=560,
                              justify="left"),
                    "checklist.empty").pack(anchor="w", padx=8, pady=12)
            self._refresh_status()
            return

        titles = self._scenario_titles()
        for index, item in enumerate(self._list.items):
            self._render_row(item, index, day, titles)
        self._refresh_status()

    def _render_row(self, item, index: int, day: int, titles: dict) -> None:
        row = ttk.Frame(self._body)
        row.pack(fill="x", padx=4, pady=1)

        var = tk.BooleanVar(master=self.rt.root, value=item.is_done(day))
        self._rows[item.uid] = var
        # The title is what the PERSON typed — data, not a word of the panel's.
        box = ttk.Checkbutton(row, text=item.title, variable=var,
                              command=lambda uid=item.uid: self._on_toggle(uid))
        box.pack(side="left")

        # …and so is the scenario's own title line, in the panel's language.
        if item.scenario:
            ttk.Label(row, text=titles.get(item.scenario, item.scenario),
                      foreground="#888").pack(side="left", padx=(8, 0))

        for key, command, width in (
                ("checklist.delete", lambda uid=item.uid: self._on_delete(uid), 3),
                ("checklist.edit", lambda uid=item.uid: self._on_edit(uid), 3),
                ("checklist.down", lambda uid=item.uid: self._on_move(uid, 1), 3),
                ("checklist.up", lambda uid=item.uid: self._on_move(uid, -1), 3)):
            button = self.tr(ttk.Button(row, width=width, command=command), key)
            button.pack(side="right", padx=1)
            if ((key == "checklist.up" and index == 0)
                    or (key == "checklist.down"
                        and index == len(self._list.items) - 1)):
                button.state(["disabled"])

        if item.scenario:
            run = self.tr(ttk.Button(row, command=lambda uid=item.uid: self.run(uid)),
                          "checklist.run")
            run.pack(side="right", padx=(8, 6))
            if item.uid in self._running:
                run.state(["disabled"])

    def _scenario_titles(self) -> dict:
        """`{name: its own title line}`, in the panel's language — for the row's note."""
        try:
            return {a["name"]: a["title"]
                    for a in list_actions(include_dev=True, lang=self.rt.i18n.lang)}
        except Exception:                   # noqa: BLE001 — a note is not worth a crash
            return {}

    # -- what the buttons do ------------------------------------------------
    def _on_toggle(self, uid: str) -> None:
        done = self._list.toggle(uid)
        if done is None:
            return
        item = self._list.get(uid)
        self.say("checklist",
                 "checklist.log.ticked" if done else "checklist.log.unticked",
                 title=item.title)
        self._saved()
        self._refresh_status()

    def _on_reset(self) -> None:
        cleared = self._list.clear()
        self.say("checklist", "checklist.log.reset", count=cleared)
        self._saved()
        self._render()

    def _on_hour(self) -> None:
        self._list.reset_hour = modelmod.hour_of(self._hour_var.get())
        self._render()

    def _on_move(self, uid: str, delta: int) -> None:
        if self._list.move(uid, delta):
            self._saved()
            self._render()

    def _on_delete(self, uid: str) -> None:
        item = self._list.get(uid)
        if item is None:
            return
        if not messagebox.askyesno(self.t("checklist.delete.window"),
                                   self.t("checklist.delete.confirm",
                                          title=item.title),
                                   parent=self.rt.root):
            return
        self._list.remove(uid)
        self.say("checklist", "checklist.log.removed", title=item.title)
        self._saved()
        self._render()

    def _on_add(self) -> None:
        self._editor(None)

    def _on_edit(self, uid: str) -> None:
        self._editor(self._list.get(uid))

    def _saved(self) -> None:
        """The list is not a Tk variable, so the container is told by hand (§5)."""
        self.rt.settings.changed()

    # -- running the errand -------------------------------------------------
    def run(self, uid: str) -> bool:
        """Play the scenario this row names, and tick the box if it worked.

        `False` when there is nothing to play or the game is already busy — the claim is
        `play_async`'s, and it says «busy» in the log for itself.
        """
        item = self._list.get(uid)
        if item is None or not item.scenario or uid in self._running:
            return False
        self._running.add(uid)
        self._render()
        self.say("checklist", "checklist.log.run", title=item.title)
        started = self.rt.play_async(
            item.scenario, tag="checklist",
            on_result=lambda outcome, uid=uid: self._ran(uid, outcome),
            on_done=lambda uid=uid: self._done_running(uid))
        if not started:
            self._done_running(uid)
        return started

    def _ran(self, uid: str, outcome) -> None:
        """The scenario finished (on the Tk thread). Its own verdict decides the tick."""
        if not getattr(outcome, "ok", False):
            return
        item = self._list.get(uid)
        if item is None:
            return
        self._list.set_done(uid, True)
        self.say("checklist", "checklist.log.ticked", title=item.title)
        self._saved()

    def _done_running(self, uid: str) -> None:
        self._running.discard(uid)
        self._render()

    # -- the editor ---------------------------------------------------------
    def _editor(self, item) -> None:
        """Add or change one errand: what it is called, and what plays it.

        `item` is `None` for «Добавить». Nothing is written until Save, and Save refuses
        a nameless errand — a row with no words in it is a row nobody can act on.
        """
        # rt.root, not `self`: a PanelTab is not a widget and Tk wants a window path.
        win = tk.Toplevel(self.rt.root)
        win.title(self.t("checklist.editor.window"))
        win.transient(self.rt.root)
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        title_var = tk.StringVar(master=win,
                                 value=item.title if item is not None else "")
        self.tr(ttk.Label(frm), "checklist.editor.title").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        entry = ttk.Entry(frm, textvariable=title_var, width=44)
        entry.grid(row=0, column=1, sticky="we", pady=3)
        entry.focus_set()

        # The picker: every action script, plus «nothing» for an errand done by hand.
        # In the panel's language — a scenario carries a title line per language tag.
        actions = list_actions(include_dev=True, lang=self.rt.i18n.lang)
        names = [""] + [a["name"] for a in actions]
        labels = [self.t("checklist.editor.scenario_none")] + [
            "%s — %s" % (a["name"], a["title"]) for a in actions]
        pick_var = tk.StringVar(master=win)
        chosen = item.scenario if item is not None else ""
        pick_var.set(labels[names.index(chosen)] if chosen in names else labels[0])
        self.tr(ttk.Label(frm), "checklist.editor.scenario").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Combobox(frm, textvariable=pick_var, state="readonly", values=labels,
                     width=42).grid(row=1, column=1, sticky="we", pady=3)
        self.tr(ttk.Label(frm, foreground="#888", wraplength=420, justify="left"),
                "checklist.editor.hint").grid(row=2, column=0, columnspan=2,
                                              sticky="w", pady=(6, 2))

        def save() -> None:
            title = title_var.get().strip()
            if not title:
                messagebox.showerror(self.t("checklist.error.window"),
                                     self.t("checklist.error.no_title"), parent=win)
                return
            at = labels.index(pick_var.get()) if pick_var.get() in labels else 0
            scenario = names[at]
            if item is None:
                added = self._list.add(title, scenario)
                self.say("checklist", "checklist.log.added", title=added.title)
            else:
                item.title, item.scenario = title, scenario
            self._saved()
            self._render()
            win.destroy()

        buttons = ttk.Frame(frm)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.tr(ttk.Button(buttons, command=save),
                "checklist.editor.save").pack(side="left", padx=4)
        self.tr(ttk.Button(buttons, command=win.destroy),
                "checklist.editor.cancel").pack(side="left")
        win.bind("<Return>", lambda _e: save())
        win.bind("<Escape>", lambda _e: win.destroy())

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> "dict | None":
        """The same list, the same ticks, the same countdown — and the same three presses.

        What is missing against the window is only the EDITING (add, rename, re-order,
        delete): the renderer has no text field, and this tab is not the place to invent
        one. Written down as an agreed divergence in `CLAUDE.md` and `docs/panel-tabs.md`.

        Cheap by construction: everything here is already in memory, and no clock read
        goes further than `time.time()` plus the offset.
        """
        day = self._list.today()
        items = []
        for item in self._list.items:
            actions = [{"id": "toggle", "label": "checklist.web.toggle",
                        "args": {"uid": item.uid}}]
            if item.scenario:
                actions.append({"id": "run", "label": "checklist.run",
                                "args": {"uid": item.uid}})
            items.append({
                "text": item.title,
                "detail": item.scenario or "",
                "pill": ("checklist.state.done" if item.is_done(day)
                         else "checklist.state.todo"),
                "actions": actions,
            })
        card = {
            "title": "tab.checklist",
            "rows": [
                {"label": "checklist.web.progress",
                 "value": "%d/%d" % (self._list.done_count(day),
                                     len(self._list.items))},
                {"label": "checklist.web.until_reset",
                 "value": modelmod.hhmm(self._list.seconds_to_reset())},
            ],
            "items": items,
            "empty": "checklist.empty",
        }
        return {"cards": [card], "now": time.time(),
                "actions": [{"id": "reset", "label": "checklist.reset"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """Tick one off, play one, or clear the day. On the Tk thread — the API's hop."""
        uid = str((args or {}).get("uid") or "")
        if action == "toggle":
            if self._list.get(uid) is None:
                return {"error": "unknown"}
            self._on_toggle(uid)
            self._render()
            return {"ok": True}
        if action == "run":
            return {"ok": self.run(uid)}
        if action == "reset":
            self._on_reset()
            return {"ok": True}
        return {"error": "unknown"}

    # -- what the profile keeps ---------------------------------------------
    def config(self) -> dict:
        return self._list.as_config()

    def apply_config(self, raw: dict) -> None:
        self._list = modelmod.Checklist.from_config(raw)
        if self._hour_var is not None:
            self._hour_var.set(str(self._list.reset_hour))
        self._render()

    def persist_vars(self) -> list:
        """The hour box. Everything else here is a press, and says so itself (§5)."""
        return [self._hour_var] if self._hour_var is not None else []
