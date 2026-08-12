"""«Автосбор» — the block on the «Ралли» tab that decides which squads go where.

IT USED TO BE A PAGE INSIDE «НАСТРОЙКИ», contributed by the rally tab through
`settings_page()`, and it moved onto the tab itself in #1237. Two reasons, and the
second is the one that matters: nothing here is a knob of the PANEL — not a path, not a
port, not an interpreter — it is all about rallies, and it belongs beside the switches
that spend it. And while it lived under an aggregator it could go missing without a
sound: the Settings tab drew the tabs it happened to have been built before, rally was
not one of them, and the squad list the auto-join spends was simply not on screen for
anybody to fill in.

Four blocks, and they share the block because they are the same decision asked four
ways — which squads may go to a rally:

* **the join list** — the squads an auto-join may spend. This list IS what the recipe
  is handed: `actions/join_rally.md`'s `squads` argument, for the «Присоединиться»
  button, for the monitor's own auto-join and for the «rally_auto_join» trigger.
* **the alliance drill** — the same question with a third state, because a drill also
  needs to know WHO raises the banner. Exactly one squad can lead.
* **creating a rally** — one banner-carrier and the elite level it goes out on.
* **the day's ceiling** — how many rallies this account joins in a day, and how many the
  GAME says it has joined so far (#1317). The number is the only thing the panel keeps:
  the count comes from the client's own daily rally-boss counter and the door itself is
  in `actions/join_rally.md`, which is handed the ceiling as `max_joins`.
* **the daily cap per KIND of banner** — how many Doom Elites, Doom Walkers, Zombie
  Bosses, General's Trial instructors… a day, with what the panel has counted today
  beside each (panel/rally_limits.py). The names are the game's own
  (`tools/game_locale.py`), and the numbers behind them are the PANEL's: the client keeps
  one daily rally counter and no per-species number at all — every manager was walked for
  #1317 — so this is the one budget here that can drift, and it was chosen knowing that
  (docs/research/rally-join.md).

* **the soldier floor** — one number, typed by hand, compared with the soldiers standing
  in the base: below it the auto-join does not go out at all (#1317). «Сделай число в
  панели, и будем сравнивать кол солдат в казарме с указанным, если меньше, автостяги
  останавливаем» — no shares, no sums of squad ceilings, no arithmetic about how many
  squads it would fill. The comparison is in `actions/join_rally.md` (`min_soldiers`);
  the panel keeps the number and draws the reading beside it, «N / M», so what it is
  compared with is on screen.

All of them are the AUTOMATIC side, and since #1317 they are drawn inside one group on
the tab («Автостяг») so that nothing about it can be mistaken for the manual «Запустить»
form below.

THE VARIABLES EXIST WITHOUT THE WIDGETS, and that is still true now the block is on the
tab: the auto-join runs at boot, from `ensure_loaded`, in a profile nobody has opened
the tab in — and it still has to know which squads it may send. So the state is built in
the constructor and `build()` only draws controls onto it. That is also why a profile
applies cleanly before anything is on screen.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import rally_limits as rallylimitsmod
from ...widgets import numeric_spinbox
from . import limits as rallygate

# The vocabulary of kinds, read out of the live game config rather than written here
# (#1317). `tools/lib` is on the path by the time the panel imports this.
import rally_kinds                                                    # noqa: E402

# The squads the page offers. The game's own squad slots are read live where they
# matter (the formation whose `index` is the slot, tools/lib/lua_actions.py); this is
# only how many the page draws.
RALLY_SQUADS = (1, 2, 3, 4)
# The elite-monster level a created rally may target.
RALLY_ELITE_MIN, RALLY_ELITE_MAX = 1, 35

# The three states of a drill squad, in the order a click walks them.
DRILL_OFF, DRILL_ON, DRILL_FLAG = "", "on", "flag"
DRILL_MARKS = {DRILL_OFF: " ", DRILL_ON: "✓", DRILL_FLAG: "🚩"}

#: How many rallies a day the auto-join may spend, and the range the box offers. `0` is
#: «no ceiling», and the default is the game's own threshold — `kill_boss_max_num` reads
#: 20 on a live account, so a panel that has never been touched behaves like the game's
#: own idea of a day (#1317).
DAILY_MAX_DEFAULT, DAILY_MAX_TOP = 20, 999

#: What the reading shows before the game has been asked. Not «0 / 20», which is a
#: statement about the day and would be a lie on a client nobody has read yet.
DAILY_UNREAD = "—"

#: The soldier floor: how many soldiers must be standing in the base before the
#: auto-join spends a squad on a banner, and the range the box offers (#1317).
#:
#: `0` is «no floor», and it is the default on purpose: this is a number only the person
#: whose base it is can choose, and a made-up one would silently stop somebody's joining
#: the first time they updated. The gate itself is in `actions/join_rally.md`
#: (`min_soldiers`) — all the panel keeps is the number.
MIN_SOLDIERS_DEFAULT, MIN_SOLDIERS_TOP = 0, 9_999_999


class AutoRallyPage:
    """The «Авторалли» page's state, and the widgets over it."""

    def __init__(self, rt) -> None:
        self.rt = rt
        master = rt.root
        self._squad_vars: dict = {s: tk.BooleanVar(master=master, value=False)
                                  for s in RALLY_SQUADS}
        self._drill_on_var = tk.BooleanVar(master=master, value=False)
        self._drill_banner_var = tk.BooleanVar(master=master, value=False)
        self._drill_state: dict = {s: DRILL_OFF for s in RALLY_SQUADS}
        self._drill_buttons: dict = {}
        self._create_flagship = None
        self._create_buttons: dict = {}
        self._create_elite_var = tk.StringVar(master=master, value=str(RALLY_ELITE_MIN))
        # The day's ceiling and the game's count of it. Both live here rather than in
        # `build()`, for the reason the whole page does: the auto-join runs at boot in a
        # profile nobody has opened this tab in, and the ceiling has to travel with it.
        self._daily_var = tk.StringVar(master=master, value=str(DAILY_MAX_DEFAULT))
        self._today_var = tk.StringVar(master=master, value=DAILY_UNREAD)
        # The soldier floor and what the base holds right now — the same pair, and here
        # for the same reason: the door is read at boot in a profile whose tab nobody has
        # opened, and the reading beside it is what makes the number choosable (#1317).
        self._min_soldiers_var = tk.StringVar(master=master,
                                              value=str(MIN_SOLDIERS_DEFAULT))
        self._pool = None                      # soldiers in the base; None = never asked
        self._pool_var = tk.StringVar(master=master,
                                      value="%s / %s" % (DAILY_UNREAD, DAILY_UNREAD))
        self._limits = None            # loaded when the page is drawn
        self._limit_vars: dict = {}
        self._count_vars: dict = {}    # what the panel has counted today, per kind
        # WHICH KINDS OF BANNER TO LEAVE ALONE (#1317). The set is the state and the
        # checkboxes are a view of it, because the auto-join runs at boot in a profile
        # whose tab was never built — see `kind_skip`. Empty means «go for everything».
        self._kinds_off: set = set()
        self._kind_vars: dict = {}
        # …and, under it, the kinds that have gone PAST their cap (#1322). Empty is the
        # only thing a working door can produce — the press passes a kind over the moment
        # it has nothing left — so anything here is the gate having failed, which is
        # precisely what nobody could see when «Элитные инструкторы» reached 30 of 20.
        self._over_var = tk.StringVar(master=master, value="")
        # «наша сумма / игра» for today, drawn under the table so the drift of a
        # panel-kept tally is visible rather than quiet (#1317).
        self._tally_var = tk.StringVar(master=master, value=DAILY_UNREAD)

    # -- the page -----------------------------------------------------------
    def build(self, parent: ttk.Frame) -> None:
        tr = self.rt.tr
        rally = tr(ttk.LabelFrame(parent, padding=8), "autorally.frame")
        rally.pack(fill="x")
        tr(ttk.Label(rally), "autorally.squads").pack(side="left", padx=(0, 6))
        for squad in RALLY_SQUADS:
            ttk.Checkbutton(rally, text=str(squad),
                            variable=self._squad_vars[squad]).pack(side="left", padx=4)
        tr(ttk.Label(parent, foreground="#888", wraplength=620, justify="left"),
           "autorally.hint").pack(anchor="w", pady=(4, 0))

        drill = tr(ttk.LabelFrame(parent, padding=8), "autorally.drill.frame")
        drill.pack(fill="x", pady=(10, 0))
        tr(ttk.Checkbutton(drill, variable=self._drill_on_var),
           "autorally.drill.enabled").pack(anchor="w")
        tr(ttk.Checkbutton(drill, variable=self._drill_banner_var),
           "autorally.drill.banner").pack(anchor="w", pady=(2, 6))

        row = ttk.Frame(drill)
        row.pack(fill="x")
        tr(ttk.Label(row), "autorally.drill.squads").pack(side="left", padx=(0, 6))
        # Tri-state, so a checkbox will not do: each squad is a button whose text is
        # its state, and a click walks the states round.
        for squad in RALLY_SQUADS:
            btn = ttk.Button(row, width=5,
                             command=lambda s=squad: self.cycle_drill_squad(s))
            btn.pack(side="left", padx=3)
            self._drill_buttons[squad] = btn
        tr(ttk.Label(drill, foreground="#888", wraplength=620, justify="left"),
           "autorally.drill.hint").pack(anchor="w", pady=(6, 0))
        self.paint_drill_squads()

        # -- creating a rally ------------------------------------------------
        # The creator is a banner, so at most one squad carries it — the squad buttons
        # toggle blank <-> 🚩 and picking one clears any other, the same one-banner rule
        # the drill enforces.
        create = tr(ttk.LabelFrame(parent, padding=8), "autorally.create.frame")
        create.pack(fill="x", pady=(10, 0))
        crow = ttk.Frame(create)
        crow.pack(fill="x")
        tr(ttk.Label(crow), "autorally.create.squads").pack(side="left", padx=(0, 6))
        for squad in RALLY_SQUADS:
            btn = ttk.Button(crow, width=5,
                             command=lambda s=squad: self.cycle_create_squad(s))
            btn.pack(side="left", padx=3)
            self._create_buttons[squad] = btn

        erow = ttk.Frame(create)
        erow.pack(fill="x", pady=(6, 0))
        tr(ttk.Label(erow), "autorally.create.elite").pack(side="left", padx=(0, 6))
        numeric_spinbox(erow, from_=RALLY_ELITE_MIN, to=RALLY_ELITE_MAX, width=5,
                        textvariable=self._create_elite_var).pack(side="left")
        tr(ttk.Label(create, foreground="#888", wraplength=620, justify="left"),
           "autorally.create.hint").pack(anchor="w", pady=(6, 0))
        self.paint_create_squads()

        # -- the day's ceiling, and the game's count of it --------------------
        # One number the person sets and one number the game answers with — and never a
        # tally of ours between them (#1317). The door is in `actions/join_rally.md`; all
        # this does is hold the ceiling and draw what the client says it has spent.
        day = tr(ttk.LabelFrame(parent, padding=8), "rally_day.frame")
        day.pack(fill="x", pady=(10, 0))
        drow = ttk.Frame(day)
        drow.pack(fill="x")
        tr(ttk.Label(drow), "rally_day.max").pack(side="left", padx=(0, 6))
        numeric_spinbox(drow, from_=0, to=DAILY_MAX_TOP, width=6,
                        textvariable=self._daily_var).pack(side="left")
        tr(ttk.Label(drow), "rally_day.today").pack(side="left", padx=(16, 6))
        ttk.Label(drow, textvariable=self._today_var,
                  font=("TkDefaultFont", 10, "bold")).pack(side="left")
        tr(ttk.Label(day, foreground="#888", wraplength=620, justify="left"),
           "rally_day.hint").pack(anchor="w", pady=(6, 0))

        # -- the soldier floor, and what the base holds right now ---------------
        # ONE NUMBER, TYPED BY HAND, COMPARED WITH ONE READING (#1317): «сделай число в
        # панели, и будем сравнивать кол солдат в казарме с указанным, если меньше,
        # автостяги останавливаем». No shares, no sums of squad ceilings, no arithmetic
        # about three squads — the panel holds the number, the scenario does the
        # comparing (`actions/join_rally.md`), and the reading is drawn beside the box so
        # that what it is compared with is on screen: «в казарме: N / порог M».
        troops = tr(ttk.LabelFrame(parent, padding=8), "rally_troops.frame")
        troops.pack(fill="x", pady=(10, 0))
        trow = ttk.Frame(troops)
        trow.pack(fill="x")
        tr(ttk.Label(trow), "rally_troops.min").pack(side="left", padx=(0, 6))
        numeric_spinbox(trow, from_=0, to=MIN_SOLDIERS_TOP, width=9,
                        textvariable=self._min_soldiers_var).pack(side="left")
        tr(ttk.Label(trow), "rally_troops.now").pack(side="left", padx=(16, 6))
        ttk.Label(trow, textvariable=self._pool_var,
                  font=("TkDefaultFont", 10, "bold")).pack(side="left")
        # BOTH SIDES OF THE COMPARISON IN ONE LINE, so the reading moves when the box
        # does: a «в казарме» on its own answers nothing — what the person is looking at
        # is whether it is over the number they just typed.
        self._min_soldiers_var.trace_add("write", lambda *a: self.paint_pool())
        self.paint_pool()
        tr(ttk.Label(troops, foreground="#888", wraplength=620, justify="left"),
           "rally_troops.hint").pack(anchor="w", pady=(6, 0))

        # -- EVERY KIND OF BANNER: go for it? how many a day? how many today? ---
        # ONE TABLE, because they are one decision asked three ways (#1317). The
        # vocabulary is the game's (`tools/lib/rally_kinds.py`, read off the live config)
        # and so are the labels — `rally_limit.type.<kind>` is filled from the game's own
        # tables, never translated here.
        #
        # The tick counts nothing and cannot drift; the number is a budget the PANEL keeps,
        # because the client has no per-species counter — which is why the line under the
        # table shows our sum and the game's own count side by side. That comparison is a
        # READING and nothing more since #1322: it used to switch the budgets off whenever
        # ours ran ahead, which is every hour of every day, so no kind was ever capped.
        # A «today» that has gone past its cap is the door having failed, and the log says
        # so in words (`limits.over_budget`).
        kinds = tr(ttk.LabelFrame(parent, padding=8), "rally_kind.frame")
        kinds.pack(fill="x", pady=(10, 0))
        self._limits = rallylimitsmod.load_limits(self.rt.profiles.rally_limits_json())
        grid = ttk.Frame(kinds)
        grid.pack(fill="x")
        columns = 2                 # sixty-eight rows: two columns of (tick, cap, today)
        for head, col in (("rally_kind.col.on", 0), ("rally_limit.col.cap", 1),
                          ("rally_limit.col.today", 2)):
            for block in range(columns):
                tr(ttk.Label(grid), head).grid(row=0, column=block * 4 + col,
                                               sticky="w", padx=(0, 6))
        per = (len(rally_kinds.KIND_ORDER) + columns - 1) // columns
        for n, kind in enumerate(rally_kinds.KIND_ORDER):
            block, line = n // per, n % per + 1
            var = tk.BooleanVar(master=self.rt.root, value=kind not in self._kinds_off)
            self._kind_vars[kind] = var
            box = ttk.Checkbutton(
                grid, variable=var,
                command=lambda k=kind, v=var: self.set_kind(k, bool(v.get())))
            tr(box, f"rally_limit.type.{kind}")
            box.grid(row=line, column=block * 4, sticky="w", padx=(0, 6))
            cap = tk.StringVar(master=self.rt.root,
                               value=str(self._limits.limit_for(kind)))
            self._limit_vars[kind] = cap
            numeric_spinbox(grid, from_=0, to=999, width=5,
                            textvariable=cap).grid(row=line, column=block * 4 + 1,
                                                   sticky="w")
            cap.trace_add("write", lambda *a: self.save_limits())
            spent = tk.StringVar(master=self.rt.root, value="0")
            self._count_vars[kind] = spent
            ttk.Label(grid, textvariable=spent).grid(row=line, column=block * 4 + 2,
                                                     sticky="w", padx=(6, 18))
        self.paint_counts()

        row = ttk.Frame(kinds)
        row.pack(fill="x", pady=(6, 0))
        tr(ttk.Button(row, command=lambda: self.set_all_kinds(True)),
           "rally_kind.all").pack(side="left")
        tr(ttk.Button(row, command=lambda: self.set_all_kinds(False)),
           "rally_kind.none").pack(side="left", padx=(6, 0))
        # BOTH NUMBERS, SIDE BY SIDE — the panel's sum for today and the game's own count.
        # A tally the panel keeps is only honest while anybody can see how far it has
        # wandered; the person asked for exactly this (#1317).
        tr(ttk.Label(row), "rally_kind.tally").pack(side="left", padx=(16, 4))
        ttk.Label(row, textvariable=self._tally_var,
                  font=("TkDefaultFont", 10, "bold")).pack(side="left")
        # …and the overspend, in red and in words, or nothing at all (#1322). A cap that
        # has been passed is the door having failed, and the table alone said it in two
        # digits nobody was reading: `paint_counts` fills this line whenever a kind is
        # over, and leaves it empty — invisible — on the ordinary day.
        ttk.Label(kinds, textvariable=self._over_var, foreground="#c00",
                  wraplength=620, justify="left").pack(anchor="w", pady=(4, 0))
        tr(ttk.Label(kinds, foreground="#888", wraplength=620, justify="left"),
           "rally_kind.hint").pack(anchor="w", pady=(6, 0))

    def set_all_kinds(self, wanted: bool) -> None:
        """«Все» / «Никакие» — sixty-eight boxes is too many to click one at a time."""
        for kind, var in self._kind_vars.items():
            var.set(bool(wanted))
            if wanted:
                self._kinds_off.discard(kind)
            else:
                self._kinds_off.add(kind)
        self.rt.settings.changed()

    # -- the caps file (its own per-profile file, not the settings blob) -----
    def save_limits(self) -> None:
        """Persist the edited per-type caps to the profile's rally_limits.json."""
        if self.rt.settings.loading or not self._limit_vars or self._limits is None:
            return
        limits = self._limits
        for key, var in self._limit_vars.items():
            limits = limits.with_limit(key, var.get())
        self._limits = limits
        rallylimitsmod.save_limits(limits, self.rt.profiles.rally_limits_json())

    def paint_counts(self) -> None:
        """Put today's per-kind tally beside the caps (Tk thread, cheap: a file read).

        The very numbers the auto-join is gated on (`limits.kind_left`), so the person
        reading the box can see why a kind stopped being joined.
        """
        if not self._count_vars:
            return
        counts = rallylimitsmod.load_counts(self.rt.profiles.rally_counts_json())
        for key, var in self._count_vars.items():
            try:
                var.set(str(counts.count_for(key)))
            except tk.TclError:                # the page is going away
                return
        # …and the same reading said as a sentence when a kind has gone past its cap
        # (#1322). The phone draws the identical row; the log says it out loud once, at
        # the run that put it over (`limits.record_joins`).
        limits = self._limits or rallylimitsmod.load_limits(
            self.rt.profiles.rally_limits_json())
        over = rallygate.over_budget(self.rt, counts, limits)
        try:
            self._over_var.set(
                self.rt.t("rally_kind.over_line",
                          kinds=rallygate.over_text(self.rt, over)) if over else "")
        except tk.TclError:                    # the page is going away
            return

    def set_tally(self, ours, game, top) -> None:
        """Draw «our sum / the game's count» under the table (Tk thread, #1317).

        `game < 0` is «the client could not be asked», which is a dash rather than a zero:
        a confident «12 / 0» would be the panel accusing the game of having done nothing.
        """
        try:
            if game is None or int(game) < 0:
                self._tally_var.set("%d / %s" % (int(ours or 0), DAILY_UNREAD))
            else:
                self._tally_var.set("%d / %d" % (int(ours or 0), int(game)))
        except (TypeError, ValueError, tk.TclError):
            pass

    def tally_text(self) -> str:
        """What the tally line says right now — the phone shows the same string."""
        return str(self._tally_var.get() or DAILY_UNREAD)

    def counts_today(self) -> dict:
        """`{kind: joined today}` for whoever draws it — the phone included."""
        counts = rallylimitsmod.load_counts(self.rt.profiles.rally_counts_json())
        return {key: counts.count_for(key) for key in self.limit_keys()}

    def limit_keys(self) -> list:
        """The kinds this profile has caps for, in the file's own order."""
        limits = self._limits or rallylimitsmod.load_limits(
            self.rt.profiles.rally_limits_json())
        return list(limits.types())

    def cap_for(self, key: str) -> int:
        """The cap this profile has for one kind (`0` = no cap)."""
        limits = self._limits or rallylimitsmod.load_limits(
            self.rt.profiles.rally_limits_json())
        return limits.limit_for(key)

    def reload_limits(self) -> None:
        """Re-read the active profile's caps into the fields (on a profile switch).

        Done inside the binder's `loading` guard, or setting the fields would write
        them straight back into the profile just switched away from.
        """
        if not self._limit_vars:
            return
        was, self.rt.settings.loading = self.rt.settings.loading, True
        try:
            self._limits = rallylimitsmod.load_limits(
                self.rt.profiles.rally_limits_json())
            for key, var in self._limit_vars.items():
                var.set(str(self._limits.limit_for(key)))
            self.paint_counts()          # the tally belongs to the profile too
        finally:
            self.rt.settings.loading = was

    # -- the tri-state buttons ----------------------------------------------
    def cycle_create_squad(self, squad: int) -> None:
        """Toggle the banner between blank and this squad — only one may carry it."""
        self._create_flagship = None if self._create_flagship == squad else squad
        self.paint_create_squads()
        self.rt.settings.changed()

    def paint_create_squads(self) -> None:
        """Redraw the creator buttons: the flagship shows 🚩, the rest blank."""
        for squad, btn in self._create_buttons.items():
            mark = "🚩" if self._create_flagship == squad else " "
            try:
                btn.configure(text=f"{squad} {mark}")
            except tk.TclError:
                pass

    def cycle_drill_squad(self, squad: int) -> None:
        """Walk one squad's state: out -> in -> leading -> out.

        `leading` is skipped when another squad already holds the banner, so a click
        can never quietly take it away from the squad the operator chose; clearing that
        one first is how it moves.
        """
        state = self._drill_state.get(squad, DRILL_OFF)
        if state == DRILL_OFF:
            self._drill_state[squad] = DRILL_ON
        elif state == DRILL_ON:
            taken = any(s != squad and st == DRILL_FLAG
                        for s, st in self._drill_state.items())
            self._drill_state[squad] = DRILL_OFF if taken else DRILL_FLAG
        else:
            self._drill_state[squad] = DRILL_OFF
        if self._drill_state[squad] == DRILL_FLAG:
            # One banner: whatever else claimed it stays in, just not leading.
            for other in self._drill_state:
                if other != squad and self._drill_state[other] == DRILL_FLAG:
                    self._drill_state[other] = DRILL_ON
        self.paint_drill_squads()
        self.rt.settings.changed()

    def paint_drill_squads(self) -> None:
        """Redraw the four buttons from the drill state."""
        for squad, btn in self._drill_buttons.items():
            mark = DRILL_MARKS[self._drill_state.get(squad, DRILL_OFF)]
            try:
                btn.configure(text=f"{squad} {mark}")
            except tk.TclError:
                pass

    # -- reading the controls -----------------------------------------------
    def create_elite_level(self) -> int:
        """The chosen elite level, clamped to the allowed range (bad input -> min)."""
        try:
            level = int(self._create_elite_var.get())
        except (TypeError, ValueError):
            return RALLY_ELITE_MIN
        return max(RALLY_ELITE_MIN, min(RALLY_ELITE_MAX, level))

    def join_squads(self) -> list:
        """The squads a join may spend, as `join_rally` wants them."""
        return [s for s in RALLY_SQUADS if self._squad_vars[s].get()]

    def kind_skip(self) -> str:
        """`kind,kind,…` — the kinds of banner the auto-join must LEAVE ALONE (#1317).

        The shape `join_rally` wants, and it is read off the SET rather than off the
        widgets: the auto-join runs at boot in a profile whose tab was never built, and a
        list of unbuilt checkboxes would answer «skip everything» — a new switch must
        never quietly stop somebody's joining. Empty is «go for everything», which is what
        a profile that has never opened the list says and what the bot did before the list
        existed.
        """
        return ",".join(kind for kind in rally_kinds.KIND_ORDER
                        if kind in self._kinds_off)

    def kinds_on(self) -> list:
        """The kinds the auto-join may go for, in the order the panel draws them."""
        return [kind for kind in rally_kinds.KIND_ORDER
                if kind not in self._kinds_off]

    def set_kind(self, kind: str, wanted: bool) -> None:
        """Tick or untick one kind (the checkbox's own handler)."""
        if wanted:
            self._kinds_off.discard(kind)
        else:
            self._kinds_off.add(kind)
        self.rt.settings.changed()

    def daily_max(self) -> int:
        """The day's ceiling as `join_rally` wants it — `0` is «no ceiling» (#1317).

        A half-typed box reads as the default rather than as 0, because 0 here means «join
        for ever» and a box being edited must never quietly turn the door off.
        """
        raw = str(self._daily_var.get()).strip()
        if not raw.isdigit():
            return DAILY_MAX_DEFAULT
        return max(0, min(DAILY_MAX_TOP, int(raw)))

    def min_soldiers(self) -> int:
        """The soldier floor as `join_rally` wants it — `0` is «no floor» (#1317).

        A half-typed box reads as 0 rather than as whatever digits are already in it: 0
        here means «join whatever the base holds», which is what the bot did before this
        existed, and a box being edited must never quietly TIGHTEN a door.
        """
        raw = str(self._min_soldiers_var.get()).strip()
        if not raw.isdigit():
            return MIN_SOLDIERS_DEFAULT
        return max(0, min(MIN_SOLDIERS_TOP, int(raw)))

    def pool_text(self) -> str:
        """«N / M» — what the base holds against the floor it is compared with (#1317).

        One string, because they are one fact: «в казарме: N / порог M». The phone shows
        exactly this, and `—` on the left is «nothing has asked a client yet» rather than
        an empty base.
        """
        return str(self._pool_var.get() or DAILY_UNREAD)

    def set_pool(self, soldiers) -> None:
        """Write the base's own soldier count onto the page (Tk thread, #1317).

        `soldiers < 0` is «the client could not be asked» and draws the dash: a confident
        «0» would read as an empty base, which is exactly the state the floor refuses on.
        """
        try:
            self._pool = None if soldiers is None or int(soldiers) < 0 else int(soldiers)
        except (TypeError, ValueError):
            self._pool = None
        self.paint_pool()

    def paint_pool(self) -> None:
        """Redraw «in the base / the floor» — after a read, and after the box is typed in."""
        floor = self.min_soldiers()
        left = DAILY_UNREAD if self._pool is None else str(self._pool)
        try:
            self._pool_var.set("%s / %s" % (left, floor if floor else DAILY_UNREAD))
        except tk.TclError:                    # the page is going away
            pass

    def today_text(self) -> str:
        """What the game last said about today — `«done / max»`, or `—` if never read."""
        return str(self._today_var.get() or DAILY_UNREAD)

    def set_today(self, done, top) -> None:
        """Write the game's own count onto the page (Tk thread).

        `done < 0` is «unreadable» and draws the dash — a client at the login screen
        answers plausibly to almost everything (`docs/research/game-clock.md`), and a
        confident «0 / 20» there is exactly the shape of that lie.
        """
        try:
            if done is None or int(done) < 0:
                self._today_var.set(DAILY_UNREAD)
            else:
                self._today_var.set("%d / %d" % (int(done), self.daily_max()
                                                 or int(top or 0)))
        except (TypeError, ValueError, tk.TclError):
            pass

    # -- persistence ---------------------------------------------------------
    def config(self) -> dict:
        """The page as it is stored: squad lists, not a widget per squad.

        `[1, 3]` says what it means to a reader of the config file, and survives the
        page offering a different number of squads later. The drill's leader is a
        separate field rather than a fourth list, because there is only ever one of it —
        and it is always also in `squads`.
        """
        drill_squads = [s for s in RALLY_SQUADS
                        if self._drill_state.get(s, DRILL_OFF) != DRILL_OFF]
        flagship = next((s for s in RALLY_SQUADS
                         if self._drill_state.get(s) == DRILL_FLAG), None)
        return {
            "squads": self.join_squads(),
            "drill": {
                "enabled": bool(self._drill_on_var.get()),
                "create_banner": bool(self._drill_banner_var.get()),
                "squads": drill_squads,
                "flagship": flagship,
            },
            "create": {
                "flagship": self._create_flagship,
                "elite_level": self.create_elite_level(),
            },
            # The day's ceiling — the ONE number the panel keeps about the budget, and
            # the one the auto-join is handed (#1317).
            "daily_max": self.daily_max(),
            # …and the soldiers that must be standing in the base for a banner to be
            # worth a squad at all. `0` is «no floor» and is what every profile written
            # before #1317 answers — a door nobody set must not start refusing.
            "min_soldiers": self.min_soldiers(),
            # …and the kinds of banner to leave alone. Stored as what is OFF, so a season
            # that adds a boss is joined by default rather than silently ignored by every
            # profile written before it existed.
            "kinds_off": sorted(self._kinds_off),
        }

    def apply_config(self, raw) -> None:
        """Restore the page from a profile's saved block (anything odd -> off)."""
        raw = raw if isinstance(raw, dict) else {}
        squads = raw.get("squads")
        squads = squads if isinstance(squads, list) else []
        for squad, var in self._squad_vars.items():
            var.set(squad in squads)

        drill = raw.get("drill")
        drill = drill if isinstance(drill, dict) else {}
        self._drill_on_var.set(bool(drill.get("enabled", False)))
        self._drill_banner_var.set(bool(drill.get("create_banner", False)))
        chosen = drill.get("squads")
        chosen = chosen if isinstance(chosen, list) else []
        flagship = drill.get("flagship")
        self._drill_state = {
            s: (DRILL_ON if s in chosen else DRILL_OFF) for s in RALLY_SQUADS
        }
        # The leader is only honoured if it is in the list at all, and only once — a
        # hand-edited config cannot end up with two banners.
        if flagship in self._drill_state and flagship in chosen:
            self._drill_state[flagship] = DRILL_FLAG
        self.paint_drill_squads()

        create = raw.get("create")
        create = create if isinstance(create, dict) else {}
        creator = create.get("flagship")
        self._create_flagship = creator if creator in RALLY_SQUADS else None
        level = create.get("elite_level")
        if not isinstance(level, int) or not RALLY_ELITE_MIN <= level <= RALLY_ELITE_MAX:
            level = RALLY_ELITE_MIN
        self._create_elite_var.set(str(level))
        self.paint_create_squads()

        # A profile that predates the ceiling gets the game's own threshold rather than
        # «no ceiling»: the point of #1317 is that a day HAS an end, and an absent value
        # meaning «join for ever» would keep the bug for everyone who never opens the box.
        daily = raw.get("daily_max")
        if not isinstance(daily, int) or not 0 <= daily <= DAILY_MAX_TOP:
            daily = DAILY_MAX_DEFAULT
        self._daily_var.set(str(daily))

        # …and the soldier floor, which is the OPPOSITE default: an absent value is «no
        # floor», because it is a number only the person whose base it is can choose, and
        # inventing one would stop the joining of every profile that has never seen the
        # box (#1317).
        floor = raw.get("min_soldiers")
        if not isinstance(floor, int) or not 0 <= floor <= MIN_SOLDIERS_TOP:
            floor = MIN_SOLDIERS_DEFAULT
        self._min_soldiers_var.set(str(floor))

        off = raw.get("kinds_off")
        self._kinds_off = {str(k) for k in off} if isinstance(off, list) else set()
        for kind, var in self._kind_vars.items():
            var.set(kind not in self._kinds_off)

    def persist_vars(self) -> list:
        """Every control whose change has to reach the profile.

        The two tri-state button rows are NOT here — a button's state is not a Tk
        variable, so those call `rt.settings.changed()` from their own handler instead.
        """
        return [self._drill_on_var, self._drill_banner_var, self._create_elite_var,
                self._daily_var, self._min_soldiers_var, *self._squad_vars.values()]
