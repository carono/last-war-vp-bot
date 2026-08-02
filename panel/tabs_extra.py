"""The «Ралли» tab — raise a rally on an elite, and loop it.

What is LEFT of this file. The five read-only tabs it used to hold (Alliance, Profile,
Inventory, Heroes, Accounts) are plugins now, one module each under `panel/tabs/`, built
from the runtime rather than from the app. This one follows in wave 2, together with the
monitor half that still lives in `panel/__main__.py`.
"""
from __future__ import annotations

import threading
import time
from tkinter import ttk

from .widgets import ScrollableFrame, install_numeric_field, font as ui_font
from .tabs._data import _card, _group, _int, _stringvar

# ---------------------------------------------------------------------------
# The two things a rally can be raised on: a «Роковая Элита» (searched under the
# «лупа»'s Boss tab) and an ordinary world monster (its Monster tab).
RALLY_KIND_ELITE, RALLY_KIND_MONSTER = "boss", "monster"
RALLY_KINDS = (RALLY_KIND_ELITE, RALLY_KIND_MONSTER)
# The level either of them may be searched at. One range for both kinds: a season puts
# levels far above the old elite ceiling on the map, and the game answers with whatever
# it has, so the tab offers the whole span and lets an empty answer say "not there".
# Same range as tools/rally_create.py SEARCH_LEVEL_RANGE — the search clamps to it too.
RALLY_LEVEL_MIN, RALLY_LEVEL_MAX = 1, 200
# The levels a rally is actually raised on, each a button of its own beside the level
# box. Two hundred levels on a slider meant a drag and a squint to land on one of them,
# and the four that matter are always the same four.
RALLY_QUICK_LEVELS = (30, 35, 60, 120)
RALLY_SQUADS = (1, 2, 3, 4)
# A «Роковая Элита» rally is an ordinary-monster rally, so it counts against the
# "monster" daily cap in panel/rally_limits.py (DEFAULT_RALLY_LIMITS).
RALLY_ELITE_TYPE = "monster"
# Seconds to pause between two sends so the previous banner settles before the next
# find; interruptible by Stop.
RALLY_BETWEEN_S = 6.0


def tk_stringvar(app):
    """Kept for the callers still passing the app (panel/secret_tasks.py)."""
    import tkinter as tk
    return tk.StringVar(master=app, value="")


def _kind_key(base: str, kind: str) -> str:
    """The locale key of a status line for the rallied kind.

    Elite and monster do not share a wording in Russian (gender and case differ, so a
    substituted noun would read wrong), so the three lines that name the target have a
    separate key per kind: `rally_tab.searching` / `rally_tab.searching_monster`.
    """
    return "rally_tab." + base + ("" if kind == RALLY_KIND_ELITE else "_" + kind)


class _Stopped(Exception):
    """Raised inside the run loop when Stop was pressed — unwinds to the finally."""


class RallyTab:
    """The «Ралли» tab: raise a rally on a world monster, one squad each, N times.

    The player picks what to rally — a «Роковая Элита» or an ordinary world monster —
    sets the level (1–200 for both, as high as a season goes: typed into the box, or one
    press on the button of a level actually rallied at), ticks the squads that should each
    raise a rally, and a repeat count; «Запустить» then loops «search the map «лупа» for a
    target of that kind and level → raise the rally with the next squad», N times over,
    and «Стоп» interrupts it. A status line narrates each step and the daily per-type cap
    (panel/rally_limits.py) is honoured — a run stops when the «monster» budget for today
    is spent.

    The game work is tools/rally_create.py (find the target, press «Стягивание», pick the
    squad, launch); this tab is the loop, the controls and the bookkeeping around it. It
    runs on a background thread, takes the panel's shared game-busy flag for each send so
    it never races the timers or a jump, and touches Tk only through ``app.after``.

    A rally only counts as raised when the game shows a new one of ours afterwards, so the
    status line distinguishes the ways a repeat can come to nothing: no target of that
    level on the map, the squad missing, the «Стягивание» press not bringing up the squad
    screen, the screen refusing the squad, or the launch leaving no banner behind.

    All four choices are remembered in the active profile — :meth:`config` /
    :meth:`apply_config` are what the panel saves and restores, and :meth:`persist_vars`
    says which variables a change of has to be written out. The tab used to open on «элита,
    уровень 1, ни одного отряда» every launch, so the same four fields were set by hand
    before every single run.
    """

    def __init__(self, app, parent):
        self.app = app
        self.parent = parent
        self._stop = None          # threading.Event while a run is in flight, else None
        self._done = 0             # rallies raised in the current/last run (for the status)
        import tkinter as tk
        self._kind_var = tk.StringVar(master=app, value=RALLY_KIND_ELITE)
        # The box and the quick-pick buttons share this one variable: each button is a
        # radio whose value is its level, so pressing it writes the number into the box,
        # and a level typed by hand lights the matching button back up. `_level()` is the
        # one place that turns whatever it holds into a level.
        self._level_var = tk.StringVar(master=app, value=str(RALLY_LEVEL_MIN))
        self._repeats_var = tk.StringVar(master=app, value="1")
        self._squad_vars: dict[int, tk.BooleanVar] = {
            s: tk.BooleanVar(master=app, value=False) for s in RALLY_SQUADS}
        self._status_var = tk_stringvar(app)
        self.build()

    # -- UI -----------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.app._tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                     "tab.rally").pack(side="left")

        form = ttk.LabelFrame(self.parent, padding=8)
        self.app._tr(form, "rally_tab.frame")
        form.pack(fill="x", padx=10, pady=(0, 8))

        krow = ttk.Frame(form)
        krow.pack(fill="x")
        self.app._tr(ttk.Label(krow), "rally_tab.kind").pack(side="left", padx=(0, 6))
        for kind in RALLY_KINDS:
            self.app._tr(
                ttk.Radiobutton(krow, value=kind, variable=self._kind_var),
                "rally_tab.kind_" + kind).pack(side="left", padx=(0, 10))

        lrow = ttk.Frame(form)
        lrow.pack(fill="x", pady=(6, 0))
        self.app._tr(ttk.Label(lrow), "rally_tab.level").pack(side="left", padx=(0, 6))
        # A digits-only box for any level in the range, and a button per level a rally is
        # actually raised on — one press, no dragging. The buttons are radios over the same
        # variable, so the pressed one is always the level the box holds (and none looks
        # pressed while the box holds some other level, which is the truth).
        level_entry = ttk.Entry(lrow, width=5, textvariable=self._level_var,
                                font=ui_font(weight="bold"))
        install_numeric_field(level_entry)
        # Leaving the box writes back the level the run would actually use, so a typed
        # «999» never sits there while the search goes out on 200 — the reading and the
        # number on screen are the same thing or the tab is lying about what it will do.
        level_entry.bind("<FocusOut>", self._normalise_level, add="+")
        level_entry.bind("<Return>", self._normalise_level, add="+")
        level_entry.pack(side="left")
        ttk.Label(lrow, text="(%d–%d)" % (RALLY_LEVEL_MIN, RALLY_LEVEL_MAX),
                  foreground="#888").pack(side="left", padx=(6, 0))
        self.app._tr(ttk.Label(lrow), "rally_tab.level_quick").pack(
            side="left", padx=(14, 4))
        self._quick_buttons = {}
        for quick in RALLY_QUICK_LEVELS:
            btn = ttk.Radiobutton(lrow, text=str(quick), value=str(quick), width=4,
                                  variable=self._level_var, style="Toolbutton")
            btn.pack(side="left", padx=2)
            self._quick_buttons[quick] = btn

        srow = ttk.Frame(form)
        srow.pack(fill="x", pady=(6, 0))
        self.app._tr(ttk.Label(srow), "rally_tab.squads").pack(side="left", padx=(0, 6))
        for squad in RALLY_SQUADS:
            ttk.Checkbutton(srow, text=str(squad),
                        variable=self._squad_vars[squad]).pack(side="left", padx=4)

        rrow = ttk.Frame(form)
        rrow.pack(fill="x", pady=(6, 0))
        self.app._tr(ttk.Label(rrow), "rally_tab.repeats").pack(side="left", padx=(0, 6))
        # The task asks for install_numeric_field specifically: a plain entry made
        # digits-only (no bounds), unlike the level's bounded slider.
        entry = ttk.Entry(rrow, width=6, textvariable=self._repeats_var)
        install_numeric_field(entry)
        entry.pack(side="left")

        brow = ttk.Frame(form)
        brow.pack(fill="x", pady=(8, 0))
        self._launch_btn = self.app._tr(
            ttk.Button(brow, command=self._launch), "rally_tab.launch")
        self._launch_btn.pack(side="left")
        self._stop_btn = self.app._tr(
            ttk.Button(brow, command=self._stop_run), "rally_tab.stop")
        self._stop_btn.pack(side="left", padx=(6, 0))
        self._set_running(False)

        ttk.Label(form, textvariable=self._status_var, foreground="#888").pack(
            anchor="w", pady=(8, 0))

        # The rally monitor — «слушай push.alliance.march.* и присоединяйся» — is the
        # other half of the same subject, so it belongs on this tab rather than on the
        # Main one it used to crowd (#1183). Its widgets are still built in
        # panel/__main__.py (`_build_rally_monitor`), because every variable and every
        # handler they touch lives on the app; this frame is only where they go.
        self.monitor_host = ttk.Frame(self.parent)
        self.monitor_host.pack(fill="x", padx=2, pady=(0, 4))

        self.app._tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                              justify="left"), "rally_tab.hint").pack(
            anchor="w", padx=10, pady=(0, 10))

    # -- reading the controls ----------------------------------------------
    def _kind(self) -> str:
        """What is being rallied: `boss` (Fatal Elite) or `monster` (ordinary monster)."""
        kind = self._kind_var.get()
        return kind if kind in RALLY_KINDS else RALLY_KIND_ELITE

    def _level(self) -> int:
        """The level in the box as a whole number, inside the range whatever it holds.

        An empty box, junk, or a profile saved when the level was a slider float ("35.0")
        all read as a level here rather than as an error — the box is the only thing the
        run is aimed with, so it always answers with one.
        """
        try:
            level = round(float(self._level_var.get()))
        except Exception:                          # noqa: BLE001 — TclError on a junk var too
            return RALLY_LEVEL_MIN
        return max(RALLY_LEVEL_MIN, min(RALLY_LEVEL_MAX, level))

    def _normalise_level(self, _event=None) -> None:
        """Put the level the run would use back into the box (on leaving it / on Enter)."""
        level = str(self._level())
        if self._level_var.get() != level:
            self._level_var.set(level)

    def _repeats(self) -> int:
        try:
            return max(1, int(self._repeats_var.get()))
        except (TypeError, ValueError):
            return 1

    def _selected_squads(self) -> list:
        return [s for s in RALLY_SQUADS if self._squad_vars[s].get()]

    # -- remembering the choices -------------------------------------------
    def config(self) -> dict:
        """The tab as it is stored in the profile: read through the same readers the run
        is aimed with, so what is saved is exactly what «Запустить» would have used."""
        return {
            "kind": self._kind(),
            "level": self._level(),
            "squads": self._selected_squads(),
            "repeats": self._repeats(),
        }

    def apply_config(self, raw) -> None:
        """Restore the tab from a profile's saved block; anything odd falls back to the
        default rather than being trusted (a hand-edited config cannot aim a run)."""
        raw = raw if isinstance(raw, dict) else {}
        kind = raw.get("kind")
        self._kind_var.set(kind if kind in RALLY_KINDS else RALLY_KIND_ELITE)
        level = raw.get("level")
        if not isinstance(level, (int, float)) or isinstance(level, bool):
            level = RALLY_LEVEL_MIN
        level = max(RALLY_LEVEL_MIN, min(RALLY_LEVEL_MAX, int(level)))
        self._level_var.set(str(level))
        squads = raw.get("squads")
        squads = squads if isinstance(squads, list) else []
        for squad, var in self._squad_vars.items():
            var.set(squad in squads)
        repeats = raw.get("repeats")
        if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
            repeats = 1
        self._repeats_var.set(str(repeats))

    def persist_vars(self) -> list:
        """Every control a change of has to be written to the profile (the panel traces
        these; the tab itself never saves, so a profile switch can set them quietly)."""
        return [self._kind_var, self._level_var, self._repeats_var,
                *self._squad_vars.values()]

    # -- start / stop -------------------------------------------------------
    def _launch(self) -> None:
        if self._stop is not None:                 # a run is already in flight
            return
        squads = self._selected_squads()
        if not squads:
            self._status("rally_tab.no_squads")
            return
        self._stop = threading.Event()
        self._done = 0
        self._set_running(True)
        threading.Thread(
            target=self._run_loop,
            args=(self._stop, self._kind(), self._level(), squads, self._repeats()),
            daemon=True).start()

    def _stop_run(self) -> None:
        if self._stop is not None:
            self._stop.set()

    def _set_running(self, running: bool) -> None:
        """Enable Stop and disable Launch while a run is in flight (Tk thread)."""
        try:
            self._launch_btn.configure(state="disabled" if running else "normal")
            self._stop_btn.configure(state="normal" if running else "disabled")
        except Exception:                          # noqa: BLE001 — widget may be gone
            pass

    # -- the loop -----------------------------------------------------------
    def _run_loop(self, stop, kind, level, squads, repeats) -> None:
        """find a `kind` of `level` → raise a rally with each squad, `repeats` times over.

        One send at a time under the panel's game-busy flag; the daily «monster» cap
        gates it and Stop unwinds it. Runs off the Tk thread; all UI via `app.after`.
        """
        total = repeats * len(squads)
        try:
            from . import rally_limits as rl
            limits = rl.load_limits(self.app._profiles.rally_limits_json())
            counts = rl.load_counts(self.app._profiles.rally_counts_json())
            for rep in range(1, repeats + 1):
                for squad in squads:
                    if stop.is_set():
                        raise _Stopped
                    if not counts.allowed(RALLY_ELITE_TYPE, limits):
                        self._status("rally_tab.capped",
                                     cap=limits.limit_for(RALLY_ELITE_TYPE))
                        raise _Stopped
                    self._status(_kind_key("searching", kind),
                                 level=level, rep=rep, total=repeats)
                    res = self._one_send(stop, kind, level, squad)
                    if res is None:                # Stop pressed while waiting for busy
                        raise _Stopped
                    if res.get("ok"):
                        counts = counts.record(RALLY_ELITE_TYPE)
                        rl.save_counts(counts, self.app._profiles.rally_counts_json())
                        self._done += 1
                        self._log(_kind_key("raised", kind), squad=squad, level=level)
                        self._status("rally_tab.progress",
                                     done=self._done, total=total, squad=squad)
                    elif res.get("reason") == "no_elite":
                        self._status(_kind_key("no_elite", kind), level=level)
                    elif res.get("reason") == "no_formation":
                        self._status("rally_tab.no_formation", squad=squad)
                    elif res.get("reason") == "no_panel":
                        self._status("rally_tab.no_panel")
                    elif res.get("reason") == "no_squad":
                        self._status("rally_tab.no_squad", squad=squad)
                    else:
                        self._status("rally_tab.not_armed", squad=squad)
                    if stop.wait(RALLY_BETWEEN_S):
                        raise _Stopped
            self._status("rally_tab.finished", done=self._done)
        except _Stopped:
            self._status("rally_tab.stopped", done=self._done)
        except Exception as exc:                   # noqa: BLE001 — never crash the panel
            self._log("rally_tab.error", error=exc)
            self._status("rally_tab.error_short")
        finally:
            self._stop = None
            self.app.after(0, lambda: self._set_running(False))

    def _one_send(self, stop, kind, level, squad):
        """One find+create under the shared busy flag. ``None`` if Stop won the wait.

        Waits (interruptibly) for the game-busy flag rather than skipping the
        iteration, so a timer coming due does not cost a repeat.
        """
        while not self.app._claim_busy():
            self._status("rally_tab.busy")
            if stop.wait(2.0):
                return None
        try:
            import lua_client
            import rally_create
            ev = lua_client.get_evaluator(port=self.app._daemon_port())
            try:
                return rally_create.create_on_level(ev, level, squad, search_type=kind)
            finally:
                try:
                    ev.close()
                except Exception:                  # noqa: BLE001
                    pass
        finally:
            self.app._release_busy()

    # -- talking to the panel (always from the worker thread) ---------------
    def _status(self, key: str, **fmt) -> None:
        text = self.app._t(key, **fmt)
        self.app.after(0, lambda: self._status_var.set(text))

    def _log(self, key: str, **fmt) -> None:
        self.app.after(0, lambda: self.app._say("rally", key, **fmt))


# ---------------------------------------------------------------------------
