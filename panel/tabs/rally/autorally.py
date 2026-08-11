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
* **the daily caps per monster type** — the older, panel-counted budget (panel/
  rally_limits.py). It bounds the «Запустить» run on this tab and NOTHING ELSE: the
  auto-join is bounded by the ceiling above, because the game keeps one total and no
  per-kind number exists to enforce a per-kind cap with
  (docs/research/rally-join.md, «The game keeps the count itself»).

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
        self._limits = None            # loaded when the page is drawn
        self._limit_vars: dict = {}

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

        # -- daily caps per monster type -------------------------------------
        limits_frame = tr(ttk.LabelFrame(parent, padding=8), "rally_limit.frame")
        limits_frame.pack(fill="x", pady=(10, 0))
        self._limits = rallylimitsmod.load_limits(self.rt.profiles.rally_limits_json())
        lgrid = ttk.Frame(limits_frame)
        lgrid.pack(fill="x")
        for r, key in enumerate(self._limits.types()):
            tr(ttk.Label(lgrid), f"rally_limit.type.{key}").grid(
                row=r, column=0, sticky="w", padx=(0, 10), pady=2)
            var = tk.StringVar(master=self.rt.root,
                               value=str(self._limits.limit_for(key)))
            self._limit_vars[key] = var
            numeric_spinbox(lgrid, from_=0, to=999, width=6,
                            textvariable=var).grid(row=r, column=1, sticky="w")
            var.trace_add("write", lambda *a: self.save_limits())
        tr(ttk.Label(limits_frame, foreground="#888", wraplength=620, justify="left"),
           "rally_limit.hint").pack(anchor="w", pady=(6, 0))

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

    def daily_max(self) -> int:
        """The day's ceiling as `join_rally` wants it — `0` is «no ceiling» (#1317).

        A half-typed box reads as the default rather than as 0, because 0 here means «join
        for ever» and a box being edited must never quietly turn the door off.
        """
        raw = str(self._daily_var.get()).strip()
        if not raw.isdigit():
            return DAILY_MAX_DEFAULT
        return max(0, min(DAILY_MAX_TOP, int(raw)))

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

    def persist_vars(self) -> list:
        """Every control whose change has to reach the profile.

        The two tri-state button rows are NOT here — a button's state is not a Tk
        variable, so those call `rt.settings.changed()` from their own handler instead.
        """
        return [self._drill_on_var, self._drill_banner_var, self._create_elite_var,
                self._daily_var, *self._squad_vars.values()]
