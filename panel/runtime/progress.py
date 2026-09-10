"""What a lifecycle press is DOING, step by step, with a final point.

A press on «Перезапустить игру» used to be a sentence in the log and then nothing for
half a minute. The log is the record of what happened; it is not an answer to «идёт ли
оно ещё» — a person watching a phone sees one line («перезапускаю клиент рецептом
restart_game…») and then either a client or silence, with no way to tell which of the
two they are looking at. Live on 2026-09-10 the silence was real: at 19:49:32 the line
was written, the claim refused the run, and nothing else was said about it at all.

So the recipe says where it is. `STEP <key>` in the scenario (`docs/dsl.md`) announces
one named step; this object holds the steps of the run that is in flight, how long each
took, and how the run ENDED — «готово, клиент в игре» or «встало на шаге X, причина Y».
Both front-ends draw the same object, because it is the same run.

WHY THE RECIPE AND NOT THE PANEL. The ability is the scenario (`CLAUDE.md`), so the
steps of the ability are the scenario's to name. A panel that recognised phases by
matching log lines would be a second, silently wrong copy of the recipe the first time
somebody edited one line of it.

WHAT IT IS NOT. Not a schedule, not a gate, not a retry: nothing here decides anything.
It is a reading with an age on it, held in memory, thrown away when the next press
starts. Nothing polls it — it changes when a step is reported, and listeners are told.
"""
from __future__ import annotations

import threading
import time

#: How long a finished run stays readable. Long enough that a person who pressed and
#: put the phone down still finds the final point when they pick it up, short enough
#: that yesterday's restart is not on the page as if it were news.
KEEP_SEC = 600.0

RUNNING = "running"
DONE = "done"
FAILED = "failed"


class _Step:
    __slots__ = ("key", "fmt", "started", "ended", "state")

    def __init__(self, key: str, fmt: dict) -> None:
        self.key = key
        self.fmt = dict(fmt or {})
        self.started = time.monotonic()
        self.ended = 0.0
        self.state = RUNNING

    def secs(self, now: float) -> float:
        return round((self.ended or now) - self.started, 1)


class Progress:
    """The steps of the lifecycle press this profile is playing right now."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: list = []
        self._action = ""
        self._label = ""
        self._steps: list = []
        self._started = 0.0
        self._ended = 0.0
        self._ok: "bool | None" = None
        self._final_key = ""
        self._final_fmt: dict = {}

    # -- writing -------------------------------------------------------------
    def begin(self, action: str, label: str) -> None:
        """A press was accepted — forget the last run and start describing this one."""
        with self._lock:
            self._action = str(action or "")
            self._label = str(label or "")
            self._steps = []
            self._started = time.monotonic()
            self._ended = 0.0
            self._ok = None
            self._final_key = ""
            self._final_fmt = {}
        self._changed()

    def step(self, key: str, **fmt) -> None:
        """The run reached a named step. The one before it is done by definition.

        Reported from whatever thread the scenario runs on, and never load-bearing: a
        `STEP` for a run nobody began is kept anyway, so a scenario played by hand still
        describes itself.
        """
        if not key:
            return
        with self._lock:
            if not self._started:
                self._started = time.monotonic()
            self._close_open(DONE)
            self._steps.append(_Step(key, fmt))
        self._changed()

    def finish(self, ok: bool, key: str = "", **fmt) -> None:
        """The final point: it worked, or it stopped here and this is why."""
        with self._lock:
            if not self._started:
                return
            self._close_open(DONE if ok else FAILED)
            self._ended = time.monotonic()
            self._ok = bool(ok)
            self._final_key = str(key or ("progress.done" if ok else "progress.failed"))
            self._final_fmt = dict(fmt or {})
        self._changed()

    def _close_open(self, state: str) -> None:
        for step in self._steps:
            if step.state == RUNNING:
                step.state = state
                step.ended = time.monotonic()

    # -- reading -------------------------------------------------------------
    def running(self) -> str:
        """The id of the press in flight, or ``""``."""
        with self._lock:
            return self._action if (self._started and not self._ended) else ""

    def starting(self) -> bool:
        """Is a client being PUT UP right now?

        The one question the status word needs answered: «игра не найдена» is a true
        sentence about the process table and a misleading one about the panel, which is
        standing over a launcher it started four seconds ago (#2742).
        """
        return self.running() in ("launch", "restart", "recover")

    def state(self) -> "dict | None":
        """The whole run as both front-ends draw it, or ``None`` when there is nothing.

        Keys, never sentences: the words are said by whoever paints them, in whatever
        language that front-end is showing (`CLAUDE.md`).
        """
        now = time.monotonic()
        with self._lock:
            if not self._started:
                return None
            if self._ended and (now - self._ended) > KEEP_SEC:
                return None
            return {
                "action": self._action,
                "label": self._label,
                "running": not self._ended,
                "ok": self._ok,
                "secs": round((self._ended or now) - self._started, 1),
                "age": round(now - self._ended, 1) if self._ended else 0.0,
                "final": ({"key": self._final_key, "fmt": dict(self._final_fmt)}
                          if self._final_key else None),
                "steps": [{"key": s.key, "fmt": dict(s.fmt), "state": s.state,
                           "secs": s.secs(now)} for s in self._steps],
            }

    # -- listeners -----------------------------------------------------------
    def listen(self, callback) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def forget(self, callback) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _changed(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(self)
            except Exception:             # noqa: BLE001 — a painter, never the run
                pass
