"""The «Вышка оповещения» tab: the training run in the forbidden zone.

WHAT THE PAGE IS FOR. The alert tower sends a squad on a four-hour training march into
the forbidden zone; the zone hands out tasks while the march walks, and a finished task
is a reward nobody collects by itself. So the page answers three questions and offers
one press: how much is waiting to be claimed, whether a start is left today, and whether
anything the tasks ask for is already in the bag — then «Отработать» plays the ability.

NOTHING HERE DRIVES THE GAME. Both presses are scenarios (`CLAUDE.md`):
`read_alert_tower` for the readings and `work_alert_tower` for the routine, and the
routine ends with the same reading block, so a run started from the phone moves the
numbers in the window and nothing asks the game twice.

READ ONCE, THEN THE PERSON ASKS. The first look at the page reads the tower once
(`ensure_loaded`), and after that the numbers only move when somebody presses «Обновить»
or the errand fires. There is no clock here: the game announces a task's arrival to the
CLIENT, and until that announcement is subscribed to, a page that re-read itself every
minute would be a background poll of the game link (`CLAUDE.md`).

THE THREE KNOBS are what the routine is allowed to do — hand goods in, open the surprise
box, send the squad again — and they are the scenario's `ARGS` and nothing else. They
live in ONE place, the errand's own row on «Таймеры» (`panel/runtime/errand_args.py`),
and this page is a second DRAWING of them rather than a second copy: a box ticked here
is written through `Schedule.set_timer_arg`, so the schedule fires with what the page
shows and the gear beside the row shows what the page has (#2017). A press from this
page uses the same three values, so «Отработать» and the errand cannot behave
differently.
"""
from __future__ import annotations

from tkinter import ttk

from ..widgets import tk_stringvar
from .base import PanelTab

#: The two scenarios this page plays, and the whole of what it knows about the game.
READ_ACTION = "read_alert_tower"
WORK_ACTION = "work_alert_tower"

#: The errand the schedule runs, and the row that HOLDS the three permissions
#: (`panel/runtime/errand_args.py`). Every reader and writer below goes through it.
ERRAND = WORK_ACTION

#: The three permissions and what they mean when the row says nothing — the scenario's
#: own `ARGS` defaults, so a profile that has never touched them behaves as the recipe
#: says it does.
KNOBS = ("give_goods", "start_run", "take_box")

#: The readings, in the order the page draws them: the scenario's variable, and the
#: locale key that names it. `run_left` and `box` are drawn through their own formatters.
ROWS = (("level", "alerttower.level"),
        ("ready", "alerttower.ready"),
        ("open", "alerttower.open"),
        ("goods", "alerttower.goods"),
        ("starts", "alerttower.starts"),
        ("run_left", "alerttower.run_left"),
        ("box", "alerttower.box"),
        ("boss_power", "alerttower.boss"),
        ("squad_power", "alerttower.power"))

#: What a value looks like before anything has been read. Never a zero: «0 наград» and
#: «ничего не прочитано» are two different things and only one of them is a fact.
UNREAD = "—"


class AlertTowerTab(PanelTab):
    ID = "alert_tower"
    TITLE_KEY = "tab.alert_tower"
    ORDER = 62
    LOCALE_NS = ("alerttower",)
    WEB_SCREEN = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._values = {name: UNREAD for name, _key in ROWS}
        self._vars: dict = {}
        self._status_var = None
        self._status_key = ""
        self._loaded = False
        self._boxes: dict = {}

    # -- drawing -------------------------------------------------------------
    def build(self) -> None:
        frame = self.tr(ttk.LabelFrame(self.parent, padding=8), "alerttower.frame")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        grid = ttk.Frame(frame)
        grid.pack(fill="x")
        for row, (name, key) in enumerate(ROWS):
            self.tr(ttk.Label(grid, foreground="#888"), key).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=1)
            var = tk_stringvar(self.rt.root)
            var.set(self.shown(name))
            self._vars[name] = var
            ttk.Label(grid, textvariable=var).grid(row=row, column=1, sticky="w")
        self._status_var = tk_stringvar(self.rt.root)
        self._status_var.set(self.t(self._status_key) if self._status_key else "")
        ttk.Label(frame, textvariable=self._status_var, foreground="#888").pack(
            anchor="w", pady=(6, 0))
        knobs = ttk.Frame(frame)
        knobs.pack(fill="x", pady=(6, 0))
        for key, label, getter in (
                ("give_goods", "alerttower.give_goods", self.give_goods),
                ("start_run", "alerttower.start_run", self.start_run),
                ("take_box", "alerttower.take_box", self.take_box)):
            var = tk_stringvar(self.rt.root)
            var.set("1" if getter() else "0")
            self._boxes[key] = var
            box = self.tr(ttk.Checkbutton(knobs, variable=var, onvalue="1",
                                          offvalue="0",
                                          command=lambda k=key: self._on_box(k)), label)
            box.pack(anchor="w")
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(8, 0))
        self.tr(ttk.Button(bar, command=lambda: self.refresh(human=True)),
                "tabx.refresh").pack(side="left")
        self.tr(ttk.Button(bar, command=self.work_now), "alerttower.work").pack(
            side="left", padx=(6, 0))
        self.tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                "alerttower.hint").pack(anchor="w", pady=(8, 0))

    # -- what a reading looks like on screen ----------------------------------
    def shown(self, name: str) -> str:
        """One reading as a person reads it: a clock for the march, «да / нет» for the box."""
        raw = self._values.get(name, UNREAD)
        if raw == UNREAD:
            return UNREAD
        if name == "run_left":
            return self.clock(raw)
        if name == "box":
            return self.t("alerttower.yes" if str(raw) not in ("0", "")
                          else "alerttower.no")
        return str(raw)

    @staticmethod
    def clock(raw) -> str:
        """Seconds as «ч:мм», and a march that has finished as a plain zero."""
        try:
            left = int(float(raw))
        except (TypeError, ValueError):
            return UNREAD
        if left <= 0:
            return "0"
        return "%d:%02d" % (left // 3600, (left % 3600) // 60)

    # -- the knobs, and where their values really live -------------------------
    #
    # NOWHERE HERE, deliberately: the value is the errand row's own argument, read fresh
    # every time it is asked for. A copy kept on the tab would be a second answer the
    # first time somebody moved the knob from the gear on «Таймеры» or from the phone.
    def knob(self, key: str) -> bool:
        sched = getattr(self.rt, "schedule", None)
        if sched is None:
            return True
        value = sched.timer_arg(ERRAND, key, 1)
        return str(value) not in ("0", "", "False", "false", "None")

    def give_goods(self) -> bool:
        """May the routine hand over what a task asks for out of the bag."""
        return self.knob("give_goods")

    def start_run(self) -> bool:
        """May the routine send the squad in again when a start is left."""
        return self.knob("start_run")

    def take_box(self) -> bool:
        """May the routine open the surprise box when one is waiting."""
        return self.knob("take_box")

    def set_knob(self, key: str, on) -> None:
        """Move one knob — from this page, from the phone, or from the gear on «Таймеры».

        One value, several places that draw it: the write goes to the errand's row and
        the box on this page is merely kept in step with what was written.
        """
        value = on not in ("0", "", "false", "False", None, 0, False)
        sched = getattr(self.rt, "schedule", None)
        if sched is not None:
            sched.set_timer_arg(ERRAND, key, 1 if value else 0)
        var = self._boxes.get(key)
        if var is not None:
            self.post(lambda: var.set("1" if value else "0"))

    def _on_box(self, key: str) -> None:
        var = self._boxes.get(key)
        if var is not None:
            self.set_knob(key, var.get())

    def args(self) -> dict:
        """The three permissions as the scenario's `ARGS`. Nothing else is passed."""
        return {key: 1 if self.knob(key) else 0 for key in KNOBS}

    # -- playing the two scenarios ---------------------------------------------
    def ensure_loaded(self) -> None:
        """The first LOOK at the page reads the tower once, and never again by itself."""
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self, human: bool = False) -> None:
        """Read the tower. Opens nothing, spends nothing, presses nothing."""
        self._status("alerttower.loading")
        self.rt.play_async(READ_ACTION, tag="alerttower", human=human,
                           on_result=self.from_run)

    def work_now(self) -> None:
        """Play the ability once, with the three permissions as they stand here."""
        self._status("alerttower.working")
        self.rt.play_async(WORK_ACTION, self.args(), tag="alerttower", human=True,
                           on_result=self.from_run)

    def from_run(self, outcome) -> None:
        """Draw the page off the run's OWN variables — the scenario already read them."""
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        if not got.get("known"):
            self._status("alerttower.no_game")
            return
        values = {name: str(got.get(name, UNREAD)) for name, _key in ROWS}
        self._values = values
        self._status("")
        self.post(self._paint)

    def _paint(self) -> None:
        for name, _key in ROWS:
            var = self._vars.get(name)
            if var is not None:
                var.set(self.shown(name))

    def _status(self, key: str, **fmt) -> None:
        self._status_key = key
        text = self.t(key, **fmt) if key else ""
        var = self._status_var
        if var is not None:
            self.post(lambda: var.set(text))

    # -- persistence ------------------------------------------------------------
    #
    # THE TAB KEEPS NOTHING. Its three knobs are the errand row's arguments and the row
    # is written by the schedule; a block of its own here would be the second home this
    # page exists not to have.

    # -- the standing order's own knobs -------------------------------------------
    #
    # Declared in `panel/runtime/errand_args.py` rather than here, because they are the
    # ROW's arguments: a knob registered by a tab disappears with the tab, and this
    # errand runs in profiles that never open this page (#2010).

    # -- the phone ----------------------------------------------------------------
    def web_view(self) -> "dict | None":
        """One card: the readings, the three permissions as fields, and the two presses.

        Cheap by contract — every value here was read by the last run; the phone asks
        for a fresh one by pressing «Обновить».
        """
        rows = [{"label": key, "value": self.shown(name)} for name, key in ROWS]
        fields = [{"key": key, "label": "alerttower." + key,
                   "hint": "alerttower." + key + ".hint", "kind": "switch",
                   "value": getter()}
                  for key, getter in (("give_goods", self.give_goods),
                                      ("start_run", self.start_run),
                                      ("take_box", self.take_box))]
        card = {"title": "alerttower.frame", "note": "alerttower.hint",
                "rows": rows, "fields": fields}
        return {"cards": [card],
                "actions": [{"id": "refresh", "label": "tabx.refresh"},
                            {"id": "work", "label": "alerttower.work"}]}

    def web_press(self, action: str, args: dict) -> dict:
        """Two presses and one `set`; anything else is «unknown» rather than a guess."""
        if action == "refresh":
            self.refresh(human=True)
            return {"ok": True}
        if action == "work":
            self.work_now()
            return {"ok": True}
        if action == "set":
            key = str((args or {}).get("key") or "")
            if key not in ("give_goods", "start_run", "take_box"):
                return {"error": "unknown"}
            self.set_knob(key, (args or {}).get("value"))
            return {"ok": True}
        return {"error": "unknown"}


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(AlertTowerTab))
