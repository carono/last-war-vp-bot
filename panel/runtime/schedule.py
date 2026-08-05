"""The schedule: errands on a clock, and errands the wire sets off.

Two halves of one thing, and they share a queue on purpose. `panel/timers.py` is the
clock (which errand is due, when each last ran, the retry hold); `panel/triggers.py` is
the wire watcher (a listener per switched-on trigger, a fire on a matching push). Both
hand what they want run to the SAME single-file queue, so two errands coming due in the
same second press the game one after the other rather than at once.

WHY IT IS IN THE RUNTIME AND NOT ON THE TIMERS TAB. The schedule is what the panel does
while nobody is looking at it, and an operator may well switch the Timers tab off — it
is an editor for a list, not the list itself. So the tab edits the profile's
`timers.json` / `triggers.json` and draws the rows; everything here keeps running
whether or not that tab was ever built, which is exactly the acceptance criterion the
plan sets for this wave (docs/research/panel-tabs-refactor.md §10, wave 5).

THE SENTINELS ARE GONE. Four errands were not scenarios at all but panel-internal
hooks (`__inventory_refresh__`, `__leaderboard_collect__`, `__secret_task_share__`,
`resource_tracker`), dispatched by a chain of `if timer.name == …` inside the runner.
A tab now CONTRIBUTES its handler (`TriggerSpec(handler="refresh")`, §3.2) and this
registers it — which also answers the question the `if` chain could not: a trigger
whose tab is not in this profile is not offered, so nothing listens for it and nothing
fires into a tab that does not exist.
"""
from __future__ import annotations

import os
import threading

from .. import i18n as i18nmod
from .. import timers as timersmod
from .. import triggers as triggersmod
from .paths import TOOLS, repo_rel
from . import game_process

#: How long a tick waits for the Tk thread to read the switches off the widgets
#: (:meth:`Schedule._ask`). Short on purpose: missing one tick's widget state and
#: falling back to the saved catalogue is a great deal better than a scheduler thread
#: parked behind a window that is busy.
ASK_TIMEOUT_SEC = 3.0


class _Subscription:
    """A wire subscription wearing the shape the trigger watcher expects.

    The watcher stores whatever `spawn` hands back and only ever calls `.stop()` on it
    — so a subscription and a child process are the same thing to it, which is what let
    the ears be consolidated without touching a line of the watcher.
    """

    __slots__ = ("_off",)

    def __init__(self, off) -> None:
        self._off = off

    def stop(self) -> None:
        off, self._off = self._off, None
        if off is not None:
            off()


class Schedule:
    """The clock, the wire watcher, the queue they share, and who handles what."""

    def __init__(self, rt) -> None:
        self.rt = rt
        # The store is per profile, so it is re-pointed on a switch; the scheduler is
        # created here and only STARTED once the UI exists, because a fired timer logs.
        self.store = timersmod.LastRunStore(rt.profiles.timers_state())
        # WHICH errands exist comes from the PROFILE's own files — not from code: one
        # account's schedule is not the other's. A profile with none yet is seeded from
        # the templates in panel/.
        self.timer_catalogue = timersmod.default_catalogue()
        self.trigger_catalogue = triggersmod.default_catalogue()
        # What a tab brought with it: `name -> bound method`, and the names whose
        # handler needs the game up before it is called.
        self._handlers: dict = {}
        self._needs_game: set = set()
        # Per-errand gates and argument sources, registered by whoever owns the rule.
        # Keeps this class free of knowing what a rally is.
        self._gates: dict = {}
        self._args: dict = {}
        # Read the switches off the widgets when there are any, off the catalogue when
        # there are not — which is the case for a profile that does not show the tab.
        self.timer_config_source = None
        self.trigger_config_source = None

        self.load_timers()
        self.load_triggers()
        self.timers = timersmod.TimerScheduler(
            store=self.store,
            catalogue=lambda: self.timer_catalogue,
            config=self.timer_config,
            runner=self.run_errand,
            log=lambda key, **fmt: rt.put("[timer] " + rt.t(key, **fmt)),
            gate=self.gate,
            debug=rt.dbg("timers"),
        )
        self.triggers = triggersmod.TriggerWatcher(
            catalogue=lambda: self.trigger_catalogue,
            config=self.trigger_config,
            spawn=self.spawn_listener,
            submit=self.timers.submit,
            poll=self.poll,
            log=lambda key, **fmt: rt.put("[trigger] " + rt.t(key, **fmt)),
            debug=rt.dbg("triggers"),
        )

    # -- what a tab brings with it ------------------------------------------
    def register(self, tab) -> None:
        """Adopt one tab's contributed errands (§3.2).

        A spec naming a `handler` binds that method; a spec naming a `scenario` is
        data and needs nothing from us. Registration is what makes the trigger
        OFFERED — see :meth:`trigger_config`.
        """
        for spec in getattr(tab, "TRIGGERS", ()):
            handler = getattr(spec, "handler", None)
            if not handler:
                continue
            self._handlers[spec.name] = getattr(tab, handler)
            if getattr(spec, "needs_game", False):
                self._needs_game.add(spec.name)

    def register_gate(self, name: str, gate, record=None) -> None:
        """A gate that decides whether one named errand may run, and what it costs.

        ``gate()`` answers ``None`` (no opinion — let it run, uncounted), ``[]`` (skip
        it entirely) or a list of whatever ``record`` is to be told about afterwards.
        The rally auto-join's daily cap is the one user; the rule lives with the rally
        code and only the wiring is here.
        """
        self._gates[name] = (gate, record)

    def register_args(self, name: str, source) -> None:
        """Variables one named errand must read LIVE rather than carry (:meth:`args`)."""
        self._args[name] = source

    def handles(self, name: str) -> bool:
        return name in self._handlers

    # -- the catalogues ------------------------------------------------------
    def load_timers(self) -> None:
        """Read the active profile's catalogue, reporting what it made no sense of.

        Seeded from the template on a profile that has none yet, so a new account
        starts with the same schedule and can then diverge freely.
        """
        path = self.rt.profiles.timers_json()
        self.timer_catalogue = timersmod.load_profile_catalogue(path)
        for problem in self.timer_catalogue.errors:
            # The problem knows its own locale key (panel/i18n.Message): the tag and
            # the path are not words, the sentence after them is.
            self.rt.put(f"[timer] {repo_rel(path)}: "
                        f"{i18nmod.translated(self.rt.t, problem)}")

    def load_triggers(self) -> None:
        """The same for the trigger catalogue, seeded from its own template."""
        path = self.rt.profiles.triggers_json()
        self.trigger_catalogue = triggersmod.load_profile_catalogue(path)
        for problem in self.trigger_catalogue.errors:
            self.rt.put(f"[trigger] {repo_rel(path)}: "
                        f"{i18nmod.translated(self.rt.t, problem)}")

    def timer_config(self) -> dict:
        """The timers' switches and periods — off the widgets when there are any.

        Read fresh on every tick, so ticking a box or changing a period applies at
        once. With no Timers tab in this profile there are no widgets, and the saved
        catalogue IS the answer — which is what keeps the schedule running without it.
        """
        raw = self._ask(self.timer_config_source)
        if not raw:
            return self.timer_catalogue.default_config()
        return self.timer_catalogue.normalize_config(raw)

    def trigger_config(self) -> dict:
        """Which triggers are switched on — and which are even OFFERED.

        A trigger whose work is a tab's method is only offered while that tab is in
        this window: firing it into a tab that was switched off would be a listener
        burning a capture for nothing. A trigger naming a scenario is always offered —
        a scenario belongs to the bot, not to a tab.
        """
        raw = self._ask(self.trigger_config_source)
        if not raw:
            raw = self.trigger_catalogue.enabled_config()
        return {name: bool(on) and self.offered(name) for name, on in raw.items()}

    def offered(self, name: str) -> bool:
        """Whether this window can carry out the named trigger at all."""
        trigger = self.trigger_catalogue.by_name(name)
        wants_handler = trigger is not None and str(
            getattr(trigger, "scenario", ("",))[0] or "").startswith("__")
        if not wants_handler:
            return True
        return name in self._handlers or name in _LISTENER_ONLY

    # -- the clock's gate ----------------------------------------------------
    def gate(self) -> "str | None":
        """Why no timer may fire right now — or ``None`` to let the tick through.

        Only the game itself is a hard gate: a recipe fired at a closed client would
        fail, be recorded as a failure and sit out the retry hold for nothing. The
        daemon is not checked here — the runner starts it on demand, exactly as a
        button press does.
        """
        running, _text = game_process.profile_status(self.rt.settings)
        return None if running else "timers.log.skip_game"

    # -- running one errand --------------------------------------------------
    def run_errand(self, errand) -> bool:
        """Run one errand to completion. ``False`` = the game is busy, try later.

        Called on the scheduler thread, so it blocks there rather than spawning
        another: that is what keeps two due errands from pressing at once. Raises on a
        real failure — the scheduler turns that into a logged failure and a retry hold,
        and `last_run` is deliberately left where it was.

        A scenario of several steps — an errand the operator wrote that way — runs under
        ONE claim and in ONE script context: nothing may slip between the halves, `args` and
        anything a step reads stay visible to the next one, and a failing step aborts
        the rest, so the retry replays the whole errand rather than half of it.

        A step is the name of an action script when one exists by that name, and
        otherwise DSL source run as it stands — which is what lets an errand in the
        JSON carry its commands inline.
        """
        name = getattr(errand, "name", "")
        if not self.rt.game.claim("timer"):
            return False
        try:
            handler = self._handlers.get(name)
            # A tab's own handler that needs nothing from the game runs BEFORE the
            # daemon gate: its read degrades gracefully, so a missing daemon must not
            # fault the trigger.
            if handler is not None and name not in self._needs_game:
                self._on_tk(handler)
                return True
            if name in _LISTENER_ONLY:
                # The child does all the work (a standing capture that writes its own
                # store), so a fire is a no-op here — the arm-sweep submit must not try
                # to run the placeholder scenario.
                return True
            if not self.rt.game.up() and not self.rt.game.ensure():
                raise RuntimeError(self.rt.t("timers.log.no_daemon"))
            if handler is not None:
                handler()
                return True
            gate, record = self._gates.get(name, (None, None))
            spent = None
            if gate is not None:
                spent = gate()
                if spent is not None and not spent:
                    return True              # the budget says no — a clean no-op
            ctx = self.rt.actions.context(
                hwnd=0,
                on_event=lambda msg: self.rt.put(f"[timer] {name}: {msg}"),
                variables=self.args(errand),
            )
            for step in errand.scenario:
                if self.rt.actions.resolve(step) is not None:
                    ok = self.rt.actions.run(step, hwnd=0, ctx=ctx)
                else:
                    ok = self.rt.actions.run_text(step, ctx=ctx,
                                                  label=step.splitlines()[0])
                if not ok:
                    # The scenario's own FAIL reason when it left one. It is what the
                    # row's status column will show, and «the step did not work: X»
                    # tells the operator nothing they cannot already see in the name.
                    reason = str(getattr(ctx, "fail_reason", "") or "").strip()
                    raise RuntimeError(
                        reason or self.rt.t("timers.log.step_failed", step=step))
            if spent and record is not None:
                record(spent)
            return True
        finally:
            self.rt.game.release()
            self.rt.game.on_settled()

    def args(self, errand) -> dict:
        """The variables an errand runs with: its own, plus the ones read LIVE.

        The rally auto-join is the case that needs it — which squads it joins with is a
        settings page's list, and it must be able to change without editing the errand.
        """
        out = dict(getattr(errand, "args", {}) or {})
        source = self._args.get(getattr(errand, "name", ""))
        if source is not None:
            out.update(source())
        return out

    # -- the wire watcher's listeners ----------------------------------------
    def spawn_listener(self, trigger, on_fire):
        """Start a wire listener for one trigger; call ``on_fire`` on every match.

        Returns the child handle (a ChildMonitor, which has the `.stop()` the watcher
        wants) or ``None`` if it would not start. The reader swallows the marker line
        and lets the human line through into the log.

        Most wire triggers listen with the generic wire_event_monitor (a marker on
        every match). «leaderboard_collect» is different: the board data is in the push
        payload, not readable off a mark, so its listener is the specialised collector
        which decodes each board and appends it to this profile's history itself —
        nothing is submitted, the child does the work.
        """
        if trigger.name == "leaderboard_collect":
            return self._spawn_leaderboard(trigger)

        # A SUBSCRIPTION, not a process. Every enabled trigger used to be its own
        # capture, decoding the whole of the game's traffic to read one command name
        # out of it — with a runtime per open profile, the bill was listeners ×
        # profiles and every term was the same work done again. `rt.wire` is one ear
        # per profile carrying the union of the patterns, and this is a handle over it
        # (panel/runtime/wire.py). The watcher above cannot tell the difference: it
        # holds something with `.stop()` either way.
        def on_event(command):
            if command is None:
                # The ear closed under us. Same meaning as the child dying used to
                # have, and the same answer: forget this listener, and the next sync
                # brings it back.
                self.on_listener_exit(trigger.name)
                return
            on_fire()                   # thread-safe: submit hands to the queue

        return _Subscription(self.rt.wire.subscribe(trigger.event_pattern, on_event))

    def _spawn_leaderboard(self, trigger):
        mon = self.rt.children.spawn(
            "trigger",
            [self.rt.children.python(), "-u",
             os.path.join(TOOLS, "scan_leaderboard.py"),
             "--sqlite", self.rt.profiles.leaderboard_db()],
            on_exit=lambda n=trigger.name: self.on_listener_exit(n))
        return mon if mon.start() else None

    def on_listener_exit(self, name: str) -> None:
        """A trigger's listener died on its own — forget it and say so.

        The next `sync()` (a box toggled, the game relaunched) brings it back if the
        trigger is still switched on.
        """
        self.triggers.on_listener_exit(name)
        self.rt.say("trigger", "triggers.log.died", name=name)

    def poll(self, trigger) -> bool:
        """Evaluate a poll trigger's check through the daemon; ``True`` to fire.

        Runs on the watcher's own poll thread, every ``interval_sec``. A closed game /
        no daemon reads as ``False`` — there is no kick to recover from if the client
        is not even up, and firing then would relaunch a game nobody started.
        """
        if not self.rt.game.up():
            return False
        chunk = ('local ok, v = pcall(function() return %s end) '
                 'CS.UnityEngine.Debug.LogError("TRIGCHK=" .. tostring(ok and v and true or false))'
                 % trigger.check)
        try:
            lines = self.rt.game.evaluator().run(chunk, marker="TRIGCHK", settle=0.6)
        except Exception:                       # noqa: BLE001 — a bad read is not a kick
            return False
        return any("TRIGCHK=true" in ln.lower() for ln in (lines or []))

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self.timers.start()
        self.triggers.start()

    def stop(self) -> None:
        self.triggers.stop()
        self.timers.stop()

    def on_profile_switch(self) -> None:
        """The schedule belongs to the ACCOUNT: its errands, their switches and periods,
        and the clock that says when each last ran. Re-read all of it, or the profile
        just switched to would run the other one's errands."""
        self.store.set_path(self.rt.profiles.timers_state())
        self.load_timers()
        self.load_triggers()
        self.triggers.sync()

    def _ask(self, source):
        """Read a WIDGET-BACKED config, from whatever thread this happens to be on.

        The sources are the Timers tab's Tk variables and everything that reads them
        runs on the scheduler's own thread. A Tk variable read off the Tk thread raises
        «main thread is not in main loop» whenever the main thread is not inside the
        event loop — which during the boot is most of the time, and which took the
        whole of `_startup` with it: no daemon ensured, no dashboard, and a panel that
        looked up and was running nothing. It was always a race (one profile's debug
        log had thirty-six of them); two profiles booting at once made it reliable.

        So the read is HANDED to the Tk thread and waited for. If it cannot be handed
        over — no root, or nobody pumping — the answer is ``None`` and the caller falls
        back to the SAVED catalogue, which is exactly what a profile with no Timers tab
        already does.
        """
        if source is None:
            return None
        # `rt` may be absent entirely: the trigger tests build a bare Schedule to ask it
        # what it offers, which needs no window and must not grow one.
        rt = getattr(self, "rt", None)
        root = getattr(rt, "root", None) if rt is not None else None
        if root is None or threading.current_thread() is threading.main_thread():
            try:
                return source()
            except Exception:                    # noqa: BLE001 — the file is the fallback
                return None
        box: dict = {}

        def read() -> None:
            try:
                box["value"] = source()
            except Exception:                    # noqa: BLE001
                pass

        rt.tick.on_tk(read, timeout=ASK_TIMEOUT_SEC)
        return box.get("value")

    def _on_tk(self, func) -> None:
        # Through the runtime's queue, never `root.after` — the scheduler thread is a
        # worker, and a worker calling Tk waits for the event loop that draws every
        # other open profile (#1226, panel/runtime/tick.py).
        self.rt.post(func)


#: Triggers whose listener IS the work — nothing is submitted and no tab is needed.
_LISTENER_ONLY = frozenset({"leaderboard_collect"})
