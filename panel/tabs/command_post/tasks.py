"""«Свои задания» — the player's OWN secret tasks: refresh them, then send every squad.

The fourth page of the Secret Command Post, and the only one that spends a CURRENCY.
The other three spend daily counters the server hands out free; this one spends
«Секретные приказы» and, once those run out, diamonds — so every control on it is a
price gate, and the page's whole job is to make the rule visible before it is pressed.

THE ABILITY IS THE SCENARIO, as `CLAUDE.md` requires: `actions/refresh_secret_tasks.md`
holds the rule, the gates and every press; `actions/read_secret_post.md` is its reading
half. This module has widgets and nothing else — it plays one of the two and draws what
came back out of the run's own variables (`outcome.ctx.vars`), the way the treasure page
already does. No Lua is assembled here and no gate is held here.

WHAT THE NUMBERS MEAN. Only the IDLE tasks are counted: one with a squad already out
cannot be re-rolled, the mega refresh skips it, and the batch dispatch has nothing to
send for it. That is also how the person playing counts them, and it is the answer they
gave when asked («считать только свободные задания»).

THE PRICES ARE THE GAME'S, read live rather than believed (#1903): an ordinary refresh
costs one «Секретный приказ» and only asks for diamonds when the bag is empty; the mega
refresh costs a handful of the same item and its price is DRAWN in the dialog its button
raises, so the scenario opens that dialog to read it and closes it unpressed when the
rule says no.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ...widgets import NumericEntry, font as ui_font, tk_stringvar

#: The grey the rest of this tab draws its secondary lines in (`tab.py`'s `DIM`), spelled
#: here rather than imported: `tab.py` imports THIS module, so the arrow only goes one way.
DIM = "#888"

#: The two scenarios this page plays — the ability and its reading half.
RUN_ACTION = "refresh_secret_tasks"
READ_ACTION = "read_secret_post"

#: The defaults the page starts with, and what the scenario's own `ARGS` say.
DEFAULT_KEEP = 3
DEFAULT_BUDGET = 1200

#: What a reading that has not been made yet shows. Not a locale key: it is a dash, and
#: a dash reads the same in all eleven languages.
UNREAD = "—"


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class TasksPane:
    """The page: five readings, four knobs and one press.

    Deliberately not a `_Pane` subclass: that base reads the game on a worker thread
    (`fetch`), and everything this page knows comes out of a scenario instead. What it
    keeps of the shape — a title, a «Обновить», a status line — is drawn here, because
    borrowing the base would mean inheriting the read it must not make.
    """

    TITLE_KEY = "cmdpost.tasks.title"
    HINT_KEY = "cmdpost.tasks.hint"
    LOG_TAG = "action"

    def __init__(self, rt, tab, parent) -> None:
        self.rt = rt
        self.tab = tab
        self.parent = parent
        self._loaded = False
        self._status_var = tk_stringvar(self.rt.root)
        #: The readings, in the order they are drawn.
        self._vars = {name: tk_stringvar(self.rt.root)
                      for name in ("nonur", "ur", "running", "tickets",
                                   "diamonds", "marches", "next_free")}
        for var in self._vars.values():
            var.set(UNREAD)
        #: The rule. Every one of them is an `ARGS` of the scenario and travels as one.
        self.keep_var = tk_stringvar(self.rt.root)
        self.keep_var.set(str(DEFAULT_KEEP))
        self.budget_var = tk_stringvar(self.rt.root)
        self.budget_var.set(str(DEFAULT_BUDGET))
        self.gold_var = tk.BooleanVar(master=self.rt.root, value=True)
        self.mega_var = tk.BooleanVar(master=self.rt.root, value=True)
        self.send_var = tk.BooleanVar(master=self.rt.root, value=True)
        self.build()

    # -- the window ----------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.rt.tr(ttk.Label(bar, font=ui_font(size=14, weight="bold")),
                   self.TITLE_KEY).pack(side="left")
        self.rt.tr(ttk.Button(bar, width=12, command=self.refresh),
                   "tabx.refresh").pack(side="right")
        ttk.Label(bar, textvariable=self._status_var, foreground=DIM).pack(
            side="right", padx=8)
        self.rt.tr(ttk.Label(self.parent, foreground=DIM, wraplength=760,
                             justify="left"), self.HINT_KEY).pack(
            anchor="w", padx=10, pady=(0, 6))

        body = ttk.Frame(self.parent)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        state = self.rt.tr(ttk.LabelFrame(body, padding=8), "cmdpost.tasks.state")
        state.pack(fill="x")
        for row, (key, name) in enumerate((("cmdpost.tasks.nonur", "nonur"),
                                           ("cmdpost.tasks.ur", "ur"),
                                           ("cmdpost.tasks.running", "running"),
                                           ("cmdpost.tasks.tickets", "tickets"),
                                           ("cmdpost.tasks.diamonds", "diamonds"),
                                           ("cmdpost.tasks.marches", "marches"),
                                           # «Почему не отправлено» is answered by a
                                           # clock: there are more tasks than heroes, and
                                           # the ones out say when they are home (#1903).
                                           ("cmdpost.tasks.next_free", "next_free"))):
            self.rt.tr(ttk.Label(state), key).grid(row=row, column=0, sticky="w",
                                                   padx=(0, 8), pady=1)
            ttk.Label(state, textvariable=self._vars[name]).grid(
                row=row, column=1, sticky="w", pady=1)

        rule = self.rt.tr(ttk.LabelFrame(body, padding=8), "cmdpost.tasks.rule")
        rule.pack(fill="x", pady=(8, 0))
        line = ttk.Frame(rule)
        line.pack(fill="x")
        self.rt.tr(ttk.Label(line), "cmdpost.tasks.keep").pack(side="left")
        NumericEntry(line, textvariable=self.keep_var, width=4).pack(
            side="left", padx=(4, 12))
        self.rt.tr(ttk.Checkbutton(line, variable=self.gold_var,
                                   command=self._on_rule_change),
                   "cmdpost.tasks.use_diamonds").pack(side="left")
        self.rt.tr(ttk.Label(line), "cmdpost.tasks.budget").pack(
            side="left", padx=(12, 2))
        NumericEntry(line, textvariable=self.budget_var, width=6).pack(side="left")
        boxes = ttk.Frame(rule)
        boxes.pack(fill="x", pady=(6, 0))
        self.rt.tr(ttk.Checkbutton(boxes, variable=self.mega_var,
                                   command=self._on_rule_change),
                   "cmdpost.tasks.mega").pack(side="left")
        self.rt.tr(ttk.Checkbutton(boxes, variable=self.send_var,
                                   command=self._on_rule_change),
                   "cmdpost.tasks.send").pack(side="left", padx=(12, 0))
        # A button that STARTS the ability, never one that MARKS anything (`CLAUDE.md`):
        # what it changes is in the game, and every reading above it comes back from the
        # run itself.
        self.rt.tr(ttk.Button(rule, width=24, command=self.run_now),
                   "cmdpost.tasks.run").pack(anchor="w", pady=(8, 0))
        self._keep_trace = self.keep_var.trace_add(
            "write", lambda *_a: self._on_rule_change())
        self.budget_var.trace_add("write", lambda *_a: self._on_rule_change())

    def _on_rule_change(self) -> None:
        self.rt.settings.changed()

    # -- the rule, as the scenario's arguments -------------------------------
    def args(self) -> dict:
        """The four knobs as the scenario's `ARGS`. Nothing else is passed.

        A half-typed box falls back to the scenario's own default rather than to zero:
        `keep = 0` would refresh until every idle task were UR and `diamond_budget = 0`
        would silently switch the diamonds off — two very different mistakes, both made
        by the same empty box.
        """
        return {"keep": _int(self.keep_var.get(), DEFAULT_KEEP),
                "use_diamonds": 1 if self.gold_var.get() else 0,
                "diamond_budget": _int(self.budget_var.get(), DEFAULT_BUDGET),
                "mega": 1 if self.mega_var.get() else 0,
                "dispatch": 1 if self.send_var.get() else 0}

    # -- playing the two scenarios -------------------------------------------
    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self) -> None:
        """Read the post — the scenario's reading half. Opens nothing, spends nothing."""
        self._status("cmdpost.loading")
        self.rt.play_async(READ_ACTION, tag=self.LOG_TAG, on_result=self.from_run)

    def run_now(self) -> None:
        """Play the ability once, with the rule as it stands on this page."""
        self._status("cmdpost.tasks.running_now")
        self.rt.play_async(RUN_ACTION, self.args(), tag=self.LOG_TAG,
                           on_result=self.from_run)

    def from_run(self, outcome) -> None:
        """Draw the page off the run's OWN variables — the scenario already read them.

        Both scenarios end with the same block of `READ_LUA … INTO`, so a run started
        from the phone moves the numbers in the window too, and nothing here asks the
        game a second time (`CLAUDE.md`).
        """
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        if "tickets" not in got:
            self._status("cmdpost.no_game")
            return
        values = {name: str(got.get(name, UNREAD)) for name in self._vars}
        values["marches"] = "%s / %s" % (got.get("marching", UNREAD),
                                         got.get("marches", UNREAD))
        self.rt.post(lambda: self._paint(values))

    def _paint(self, values: dict) -> None:
        for name, text in values.items():
            self._vars[name].set(text)
        self._status_var.set("")

    def _status(self, key: str, **fmt) -> None:
        text = self.rt.t(key, **fmt) if key else ""
        self.rt.post(lambda: self._status_var.set(text))

    # -- what the phone sees -------------------------------------------------
    def web_card(self) -> dict:
        """The same readings as one card. Drawn from what the last run left behind.

        No game read of its own: a phone opening the tab sees whatever the window (or a
        previous press from the phone) last read, and «Обновить» is the press that makes
        it current — exactly like the three pages beside it.
        """
        rows = [{"label": "cmdpost.tasks." + name, "value": self._vars[name].get()}
                for name in ("nonur", "ur", "running", "tickets", "diamonds",
                             "marches", "next_free")]
        rows.append({"label": "cmdpost.tasks.rule",
                     "value": self.rt.t("cmdpost.tasks.rule_text",
                                        keep=_int(self.keep_var.get(), DEFAULT_KEEP),
                                        budget=(_int(self.budget_var.get(),
                                                     DEFAULT_BUDGET)
                                                if self.gold_var.get() else 0))})
        return {"title": "cmdpost.tasks.title", "rows": rows}

    # -- what is remembered between sessions ---------------------------------
    def config(self) -> dict:
        return {"keep": _int(self.keep_var.get(), DEFAULT_KEEP),
                "use_diamonds": bool(self.gold_var.get()),
                "diamond_budget": _int(self.budget_var.get(), DEFAULT_BUDGET),
                "mega": bool(self.mega_var.get()),
                "dispatch": bool(self.send_var.get())}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.keep_var.set(str(_int(raw.get("keep"), DEFAULT_KEEP)))
        self.budget_var.set(str(_int(raw.get("diamond_budget"), DEFAULT_BUDGET)))
        self.gold_var.set(bool(raw.get("use_diamonds", True)))
        self.mega_var.set(bool(raw.get("mega", True)))
        self.send_var.set(bool(raw.get("dispatch", True)))

    def persist_vars(self) -> list:
        return [self.keep_var, self.budget_var, self.gold_var, self.mega_var,
                self.send_var]

    # -- lifecycle the tab expects ------------------------------------------
    def shutdown(self) -> None:
        """Nothing of its own runs here — the scenarios are the panel's to stop."""

    def restart(self) -> None:
        """Profile switched: the readings belong to the account that left them."""
        self._loaded = False
        for var in self._vars.values():
            var.set(UNREAD)
