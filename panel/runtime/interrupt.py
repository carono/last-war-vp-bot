"""«Прервать» — which scenarios are running right now, and the one press that ends them.

A scenario is the longest thing this panel ever does. A recipe with a `WAIT` in it holds
the game for minutes, `xall` spends a whole quota, a sweep walks the map — and until
this there was no way to end one that had started going wrong except to wait it out or
kill the panel. The Scenarios tab had a Stop, but only for a run IT had started: a
scenario played by a timer, by the checklist, by an auto-order or from the phone could
not be stopped by anybody, and «Стоп всё» said in its own docstring that it stopped «a
running scenario» while in fact reaching only that one tab's.

So the register lives here, beside the runtime that plays them, and every run goes into
it — because every run goes through one door
(:class:`~panel.runtime.actions.ActionRunner`), whoever opened it.

WHAT «PRESSED» COSTS. Setting a flag. No round trip into the game, no lock held, no
widget touched, so the press itself is instant from any thread — which is the whole
point: a Stop that has to ask the game whether it may stop is a Stop that hangs exactly
when it is needed. What is NOT instant is the run noticing: it halts at its next
checkpoint (between two statements, between the presses of a repeat, between the polls or
the slices of a `WAIT` — `lastwar_bot.script_engine.Interpreter._check_cancel`). That is
milliseconds for a headless recipe and up to a call's length when the thread is inside
one. Hence two lines in the log rather than one, said by whoever presses:

* **asked** — «прерываю X на шаге «…»», the moment the flag is set;
* **halted** — «X прерван», when the run has really unwound.

Between those two the game may finish a press that was already sent. Nothing can recall
it, and the asked-line says so in words: a Stop that implied otherwise would be worse
than none, because the person would go on believing the last press never landed.

WHAT IT DOES NOT TOUCH IS THE SCHEDULE. This ends what is RUNNING; the errand queue,
the monitors and the auto-orders keep their switches. That is deliberate and it is not a
half-measure: «Стоп всё» already exists for the other meaning, and it leaves a mark on
screen with an undo beside it (`panel/runtime/panic.py`) precisely because a profile
that has been silently switched off looks exactly like an idle one — seven hours once
went past that way. A Stop that quietly stopped the schedule too would be an invisible
«Стоп всё», with nothing to say it had happened and nothing to put it back. Two
presses, two meanings, in that order when both are wanted.

What DOES follow the current run is the rest of the run's own errand: a timer whose
scenario is a list of steps shares one context between them, and an interrupted context
stays interrupted, so the steps behind the one that was stopped are refused rather than
played into the mess that made somebody press the button.
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque

#: The reason the interpreter writes on a run the operator ended. Spelled here as well
#: because both front-ends have to be able to tell «прервали» from a scenario's own
#: `STOP`, and the string is the only thing that reaches them.
STOPPED_REASON = "stopped by the operator"

#: Global ordering, so two profiles' runs sort against each other the way the activity
#: strip's steps do.
_SEQ = itertools.count(1)


class Stop:
    """One stop flag the interpreter reads, over several reasons to stop.

    `ctx.cancel` is «anything with `is_set()`» by contract, and a run may now have two
    people entitled to end it: whoever started it (the Scenarios tab keeps its own
    `threading.Event` and has done since long before this) and «Прервать», which does
    not know who started anything. Rather than have the second overwrite the first —
    which is how a tab's Stop silently stops working — both are held and either answers.
    """

    __slots__ = ("_own", "_others")

    def __init__(self, *others) -> None:
        self._own = threading.Event()
        self._others = [flag for flag in others if flag is not None]

    def set(self) -> None:
        self._own.set()

    def is_set(self) -> bool:
        if self._own.is_set():
            return True
        for flag in self._others:
            try:
                if flag.is_set():
                    return True
            except Exception:                # noqa: BLE001 — a flag, never the run
                pass
        return False


class Run:
    """One scenario in flight: what it is, who started it, and how to end it."""

    __slots__ = ("seq", "name", "tag", "ctx", "flag", "started", "asked")

    def __init__(self, name: str, tag: str, ctx, flag: "Stop") -> None:
        self.seq = next(_SEQ)
        self.name = name or "?"
        #: Who asked for it — `action` for a press, `timer` for the schedule, `web` for
        #: the phone. The log line names it: «прервать» is pressed when something is
        #: happening that nobody expected, and «кто это вообще запустил» is half of it.
        self.tag = tag or ""
        self.ctx = ctx
        self.flag = flag
        self.started = time.monotonic()
        #: When it was asked to stop, or 0.0 — so a second press can say «уже прошу» and
        #: not pretend to have done something new.
        self.asked = 0.0

    @property
    def step(self) -> str:
        """The line of DSL it is on, as the script wrote it. Empty before the first one.

        Read off the context rather than remembered here: the interpreter is the only
        thing that knows where a run has got to, and it writes the statement it is about
        to run onto `ctx.step` (`lastwar_bot.script_engine`). A step is what makes the
        log line worth having — «прервали heal_units» says nothing that the press did not
        already say, and «прервали heal_units на `WAIT wounded == 0` (строка 7)» says
        which minute of waiting was thrown away.
        """
        return str(getattr(self.ctx, "step", "") or "")

    @property
    def secs(self) -> int:
        return int(time.monotonic() - self.started)

    def stop(self) -> None:
        self.flag.set()
        if not self.asked:
            self.asked = time.monotonic()

    def state(self) -> dict:
        """What a front-end draws. Numbers and names, never words (`CLAUDE.md`)."""
        return {"name": self.name, "tag": self.tag, "step": self.step,
                "secs": self.secs, "asked": bool(self.asked)}

    def __repr__(self) -> str:
        return f"<Run {self.name!r} tag={self.tag!r} step={self.step!r}>"


class Interrupts:
    """One profile's live runs, and the press that ends them.

    Thread-safe and never load-bearing, on the same terms as
    `panel/runtime/activity.py`: any thread may register, listeners are called outside
    the lock, and a listener that raises is swallowed. Nothing here may be the reason a
    scenario fails — it exists to describe and to stop runs, not to run them.
    """

    def __init__(self, history: int = 40) -> None:
        self._live: dict = {}
        self._lock = threading.RLock()
        self._listeners: list = []
        #: How many times this session, so «нажали один раз» and «жмут не переставая»
        #: do not look the same in a bug report.
        self.presses = 0
        #: THE RUNS THAT HAVE ENDED, newest last — the mini-top of «what took the
        #: longest recently» the busy debugger shows (#1392). A jam is read backwards:
        #: the run holding the client now is visible to anybody, the one that held it
        #: for four minutes ten minutes ago is not, and it is usually the answer.
        #: A ring, because this is a diagnostic and not a record — the log is the record.
        self._done: deque = deque(maxlen=int(history))

    # -- the register --------------------------------------------------------
    def enter(self, name: str, tag: str, ctx, flag: "Stop") -> "Run":
        """A run is starting. Keep the handle — :meth:`leave` takes it off the register."""
        run = Run(name, tag, ctx, flag)
        with self._lock:
            self._live[run.seq] = run
        self._changed()
        return run

    def leave(self, run: "Run | None") -> None:
        """A run has ended, however it ended. Harmless twice, and for ``None``."""
        if run is None:
            return
        with self._lock:
            if self._live.pop(run.seq, None) is None:
                return
            # Written down as it goes: what a jam is diagnosed from is the run that has
            # ALREADY finished, and by the time anybody opens the debugger it is gone
            # from the register. `state()` is taken here, while the context is still the
            # run's own — reading `run.step` afterwards would report whatever the
            # interpreter left on a context nothing is using.
            self._done.append(dict(run.state(), ended=time.monotonic()))
        self._changed()

    def history(self) -> list:
        """The runs that have ended, LONGEST first — the mini-top (:attr:`_done`)."""
        with self._lock:
            rows = list(self._done)
        rows.sort(key=lambda row: row.get("secs", 0), reverse=True)
        return rows

    # -- the press ----------------------------------------------------------
    def stop(self) -> list:
        """Ask every live run to stop. Returns the runs asked, newest first.

        The flags are set INSIDE the lock so that two presses cannot each see an empty
        register, and the answer is a list of snapshots taken while the runs were still
        there — the caller wants to say what it stopped, and by the time it gets to
        speaking one of them may already be gone.
        """
        with self._lock:
            runs = sorted(self._live.values(), key=lambda r: r.seq, reverse=True)
            said = [(run, run.state()) for run in runs]
            for run in runs:
                run.stop()
            self.presses += 1
        self._changed()
        return [state for _run, state in said]

    # -- reading ------------------------------------------------------------
    def running(self) -> list:
        """Every live run, newest first."""
        with self._lock:
            return sorted(self._live.values(), key=lambda r: r.seq, reverse=True)

    def busy(self) -> bool:
        with self._lock:
            return bool(self._live)

    def state(self) -> dict:
        """What both front-ends draw: what is running, and whether a stop is pending."""
        runs = self.running()
        return {"running": [run.state() for run in runs],
                "stopping": any(run.asked for run in runs),
                "presses": self.presses}

    def __len__(self) -> int:
        with self._lock:
            return len(self._live)

    # -- watching -----------------------------------------------------------
    def listen(self, func):
        """Be told, on the reporting thread, that a run started, ended or was stopped.

        The listener takes no arguments and asks for itself, exactly as an
        :class:`~panel.runtime.activity.Activity` listener does: it may be woken twice
        for one change and must answer «what is running now», not «what just happened».
        """
        with self._lock:
            self._listeners.append(func)

        def _off() -> None:
            with self._lock:
                try:
                    self._listeners.remove(func)
                except ValueError:
                    pass
        return _off

    def _changed(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for func in listeners:
            try:
                func()
            except Exception:                # noqa: BLE001 — a strip, never the run
                pass


# -- the press, for the front-end that is not the window ----------------------
#
# The phone has to be able to press this for the same reason it has «Включить обратно»:
# the moment a scenario is doing the wrong thing is very often a moment when nobody is
# standing at the machine. And it has to press THE SAME THING the window's footer
# presses — every open profile, not just the one whose page the phone happens to be
# showing — because a window holds several accounts and the run that has to stop is not
# reliably the one being looked at.
#
# Only the window knows which profiles are open, so the window registers how it is
# carried out and everything else only asks whether there is anybody to carry it out —
# exactly the arrangement `panel/runtime/panic.py` and `panel/runtime/panel_control.py`
# already use for the presses that belong to the shell rather than to a profile.
_handler = None


def set_handler(fn) -> None:
    """The shell says how «Прервать» reaches every open profile. A lone tab says nothing."""
    global _handler
    _handler = fn


def available() -> bool:
    """Is there anybody who can carry the press out?"""
    return _handler is not None


def request(rt) -> dict:
    """Press «Прервать». Answers what was stopped, without waiting for it to unwind.

    Through the shell's handler when there is one — that is the press that reaches every
    open profile — and through this runtime's own register otherwise, which is what a tab
    launched on its own has and all it needs.
    """
    if _handler is not None:
        try:
            return dict(_handler() or {})
        except Exception as exc:             # noqa: BLE001 — a press, never the server
            return {"ok": False, "error": str(exc)}
    return {"ok": True, "stopped": stop_one(rt)}


def stop_one(rt) -> list:
    """Stop everything running in ONE runtime, and say so in its log.

    The building block both callers share: the shell loops it over the open profiles,
    the standalone path calls it once. The log line belongs here rather than at either
    caller so that a run stopped from the phone and a run stopped from the footer leave
    the same record in the same place — which is the only way anybody reading `panel.log`
    a week later can tell what happened.
    """
    stopped = rt.interrupts.stop()
    if not stopped:
        rt.log.say("action", "interrupt.idle")
        return []
    for run in stopped:
        if run.get("asked"):
            # Already asked, and still going: it is inside a call into the game. Saying
            # «прерываю» again would read as a fresh stop of something that had not been
            # stopped, and the honest answer is that the first press is still in flight.
            rt.log.say("action", "interrupt.again", name=run["name"], secs=run["secs"])
            continue
        # `who=`, not `tag=`: the line is said through `LogBus.say(tag, key, **fmt)`,
        # whose own first argument is called `tag` — a placeholder of that name collides
        # with it and the call fails with «multiple values for argument».
        rt.log.say("action", "interrupt.asked", name=run["name"],
                   who=run["tag"] or "?", step=run["step"] or "—")
    return stopped
