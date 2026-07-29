r"""Scheduled repeats of the panel's actions — the timer module.

A *timer* is an errand plus a period: "collect the base every hour", "keep the
alliance up — donate, then claim the gifts — every hour". While the panel is open
a background thread ticks; a timer whose last successful run is older than its
period runs its recipes in order, headless (no window opened, no mouse), and
writes down when it finished. The record lives in the profile directory, so
closing the panel does not reset the clock — a timer that came due while it was
shut fires shortly after the next launch.

What the module decides, and what it deliberately does not:

  * **A timer that has never run is due at once.** "Not collected for over an
    hour" is exactly what an empty record means, so the first tick after a fresh
    profile fires everything that is switched on.
  * **A failed run is not a run.** ``last_run`` only moves when the action really
    finished, so a run lost to a closed game is retried rather than silently
    skipped for another hour. To keep a permanently broken action from re-firing
    every tick, a failure parks that one timer for :data:`RETRY_HOLD_SEC`.
  * **One thing at a time, in one thread.** Every scheduled script runs on the
    single worker thread, fed by a queue — nothing ever runs in parallel with
    anything else. Two errands that come due in the same second go on the queue
    in order and the second waits for the first to finish; the "run now" button
    enqueues too, rather than starting a thread of its own. When the panel is
    busy with a button-driven action of its own, the errand stays queued and is
    taken up again a few seconds later, so it is delayed, never lost.

Nothing here imports Tk or the game: the panel passes in the settings dict, a
runner and a log sink, which keeps the decision — *what is due right now* — a
plain function that tests can call without a display or a running client.

The catalogue below is the whole list of timers; adding one is adding an entry
(an action name from ``src/lastwar_bot/actions/`` plus a default period) and the
two locale strings its label needs.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass

from .profile import _write_json

# How often the scheduler wakes up to look for a due timer. Well under the
# shortest sensible period (a minute), so a timer fires within a few seconds of
# coming due, and a tick that finds nothing costs one dict comparison.
TICK_SEC = 20.0

# After a failed run, how long that timer is left alone before it is tried again.
# Without it an action that fails for a standing reason (game closed mid-run, a
# broken recipe) would re-fire every tick and fill the log with the same error.
RETRY_HOLD_SEC = 300.0

# How long the worker sits still after the panel turns an errand down as busy.
# The errand stays at the head of the queue either way; this is only about not
# asking again in a tight loop while a person's own button press runs its course.
BUSY_RETRY_SEC = 5.0

# Bounds offered in the UI and enforced here, so a hand-edited config cannot ask
# for a timer that fires every second or one that never fires at all.
MIN_MINUTES = 1
MAX_MINUTES = 24 * 60


@dataclass(frozen=True)
class TimerSpec:
    """One schedulable errand: what to run, how often by default, what to call it.

    ``actions`` is a *sequence* because an errand is not always one press: the
    alliance one below is "donate, then claim the gifts", which is two recipes
    that belong to a single switch and a single clock. The runner walks them in
    order and the errand only counts as done when the last one has finished — a
    donation that went through followed by a failed gift claim is a failed
    errand, and the retry does both. That is the safe way round: both recipes
    no-op when there is nothing to take.
    """

    key: str                        # stable id — config key and last-run key
    actions: tuple[str, ...]        # action scripts (src/lastwar_bot/actions/<name>.md)
    label_key: str                  # locale key for the row label
    default_minutes: int


# The two errands task #1118 asks for. Every recipe behind them is headless (the
# gift one opens the alliance window inside the game and closes it again, still
# without touching the mouse), so a timer firing never takes the machine away
# from whoever is using it.
TIMERS: tuple[TimerSpec, ...] = (
    TimerSpec(
        key="collect_base_resources",
        actions=("collect_base_resources",),
        label_key="timers.item.collect_base_resources",
        # An hour, as asked. The production buildings keep banking while nobody
        # collects, so the period is about not letting them sit full, not about
        # a cap being missed.
        default_minutes=60,
    ),
    TimerSpec(
        key="alliance_upkeep",
        # Donation first: it is the one with something to lose. Attempts bank up
        # on their own timer and the routine wants them spent every 20 minutes,
        # so if the pair is ever cut short it should be cut short at the gifts,
        # which simply wait in the window until the next round.
        actions=("donate_alliance_tech", "collect_alliance_gifts"),
        label_key="timers.item.alliance_upkeep",
        # An hour by default, as asked, and the spinbox goes down to a minute —
        # 20 is the period the daily routine actually calls for.
        default_minutes=60,
    ),
)

BY_KEY: dict[str, TimerSpec] = {spec.key: spec for spec in TIMERS}


def get(key: str) -> TimerSpec | None:
    return BY_KEY.get(key)


def default_config() -> dict:
    """Every timer, switched off, at its default period.

    Off by default on purpose: a timer presses buttons in the live game on its
    own, so it is opted into like «Автолут ★», never out of.
    """
    return {spec.key: {"enabled": False, "minutes": spec.default_minutes}
            for spec in TIMERS}


def normalize_config(raw) -> dict:
    """Coerce a stored/typed config into ``{key: {"enabled": bool, "minutes": int}}``.

    The panel's spinboxes hand over strings and an older profile may carry no
    ``timers`` block at all, so every value is re-derived here rather than
    trusted. An unreadable period falls back to the timer's default instead of
    dropping the row — a mistyped number must not silently disable a timer the
    operator believes is on.
    """
    raw = raw if isinstance(raw, dict) else {}
    out = default_config()
    for spec in TIMERS:
        item = raw.get(spec.key)
        if not isinstance(item, dict):
            continue
        out[spec.key]["enabled"] = bool(item.get("enabled", False))
        try:
            minutes = int(str(item.get("minutes", spec.default_minutes)).strip())
        except (TypeError, ValueError):
            minutes = spec.default_minutes
        out[spec.key]["minutes"] = max(MIN_MINUTES, min(MAX_MINUTES, minutes))
    return out


def due_keys(config: dict, records: dict, now: float) -> list[str]:
    """Which enabled timers are due at ``now``, the most overdue first.

    ``records`` is the last-run store's raw mapping (see :class:`LastRunStore`).
    A timer with no record has never run and is due immediately; one whose last
    attempt failed is held for :data:`RETRY_HOLD_SEC` before being offered again.
    """
    out = []
    for spec in TIMERS:
        item = config.get(spec.key) or {}
        if not item.get("enabled"):
            continue
        rec = records.get(spec.key) or {}
        failed_at = float(rec.get("failed_at") or 0.0)
        if failed_at and now - failed_at < RETRY_HOLD_SEC:
            continue
        last = float(rec.get("last_run") or 0.0)
        period = max(MIN_MINUTES, int(item.get("minutes") or spec.default_minutes)) * 60
        overdue = now - last - period
        if overdue >= 0:
            out.append((overdue, spec.key))
    out.sort(key=lambda pair: pair[0], reverse=True)
    return [key for _overdue, key in out]


def next_due(spec: TimerSpec, config: dict, records: dict) -> float | None:
    """Wall clock the timer fires at, ``0.0`` for "now" and ``None`` when off."""
    item = config.get(spec.key) or {}
    if not item.get("enabled"):
        return None
    rec = records.get(spec.key) or {}
    last = float(rec.get("last_run") or 0.0)
    if not last:
        return 0.0
    period = max(MIN_MINUTES, int(item.get("minutes") or spec.default_minutes)) * 60
    return last + period


class LastRunStore:
    """When each timer last ran, kept next to the profile it belongs to.

    One small JSON file, ``{key: {"last_run": epoch, "failed_at": epoch}}``,
    rewritten whole on every mark. Read errors degrade to "nothing ever ran",
    which makes a corrupted file cost one extra run rather than a crash at
    launch. A profile switch calls :meth:`set_path` — the clock belongs to the
    account, not to the panel.
    """

    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._path = path
        self._data = self._read(path)

    # -- location -----------------------------------------------------------
    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        """Point at another profile's file and reload from it."""
        with self._lock:
            self._path = path
            self._data = self._read(path)

    # -- reading ------------------------------------------------------------
    def records(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._data.items()}

    def last_run(self, key: str) -> float:
        with self._lock:
            return float((self._data.get(key) or {}).get("last_run") or 0.0)

    # -- writing ------------------------------------------------------------
    def mark_run(self, key: str, when: float | None = None) -> None:
        """Record a successful run, clearing any earlier failure hold."""
        self._update(key, {"last_run": float(when if when is not None else time.time()),
                           "failed_at": 0.0})

    def mark_failed(self, key: str, when: float | None = None) -> None:
        """Record a failed attempt — the period keeps running, the retry waits."""
        self._update(key, {"failed_at": float(when if when is not None else time.time())})

    def _update(self, key: str, fields: dict) -> None:
        with self._lock:
            rec = dict(self._data.get(key) or {})
            rec.update(fields)
            self._data[key] = rec
            _write_json(self._path, self._data)

    @staticmethod
    def _read(path: str) -> dict:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}


class TimerScheduler:
    """One background thread and a queue: everything scheduled runs single-file.

    **No timer script ever runs in parallel with another.** The thread is both the
    clock and the only worker: on each tick it puts the errands that have come due
    on the queue, then takes them off one at a time and runs each to completion.
    Two timers that come due in the same second do not race — the second one waits
    in the queue until the first has finished. The row's "run now" button does not
    start a thread of its own either; it *enqueues*, so a press during a running
    errand takes its turn behind it instead of being dropped or overlapping it.

    Being both clock and worker is why the wait is on the queue rather than a
    sleep: an errand enqueued by hand is picked up at once, while an idle stretch
    still wakes on the tick.

    Collaborators are all callables, so nothing about Tk or the game leaks in:

      * ``config()``   -> the normalised settings dict (read fresh every tick, so
                          a checkbox or period change applies without a restart);
      * ``runner(spec)`` -> ``True`` when the errand really ran, ``False`` when it
                          could not be started right now (the panel is busy with a
                          button-driven action) — then it stays queued and is
                          retried — and it raises for a real failure;
      * ``log(key, **fmt)`` -> a locale key plus its placeholders;
      * ``gate()``     -> a locale key explaining why nothing may run yet
                          (game not running), or ``None`` to proceed.

    The gate's complaint is said once per stretch, not once per tick: with the
    game closed overnight a 20-second tick would otherwise write 1800 identical
    lines into the log.
    """

    def __init__(self, *, store: LastRunStore, config, runner, log,
                 gate=None, tick: float = TICK_SEC,
                 busy_retry: float = BUSY_RETRY_SEC) -> None:
        self._store = store
        self._config = config
        self._runner = runner
        self._log = log
        self._gate = gate
        self._tick = tick
        self._busy_retry = busy_retry
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._gate_said: str | None = None
        # The work queue. Items are (key, scheduled) — `scheduled` only picks the
        # log line. `_queued` keeps a key from being lined up twice: a second
        # press while the first is still waiting would run the errand twice in a
        # row for no reason.
        self._queue: "queue.Queue[tuple[str, bool]]" = queue.Queue()
        self._queued: set[str] = set()
        self._queue_lock = threading.Lock()
        # Wall clock the worker may take from the queue again, set when the panel
        # turns an errand down as busy. Without it the item goes straight back on
        # the queue and the thread spins on a button press that takes a minute.
        self._hold_until = 0.0

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="panel-timers")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- the queue ----------------------------------------------------------
    def request(self, spec: TimerSpec) -> bool:
        """Ask for an errand by hand ("run now"). Returns ``False`` if already queued.

        Called from the UI thread and returns immediately — the errand runs on the
        worker like a scheduled one, so it cannot overlap whatever is running.
        """
        return self._enqueue(spec.key, scheduled=False)

    def _enqueue(self, key: str, scheduled: bool) -> bool:
        with self._queue_lock:
            if key in self._queued:
                return False
            self._queued.add(key)
        self._queue.put((key, scheduled))
        return True

    def _requeue(self, key: str, scheduled: bool) -> None:
        """Put a turned-down errand back on the queue, still claimed.

        At the back, not the front: it was never started, so nothing is half done,
        and whatever is queued behind it came due just as much. Keeping its claim
        is what stops the next tick from lining the same errand up twice.
        """
        self._queue.put((key, scheduled))

    def _release(self, key: str) -> None:
        with self._queue_lock:
            self._queued.discard(key)

    def pending(self) -> set[str]:
        """Keys currently queued or being run — for tests and the row painter."""
        with self._queue_lock:
            return set(self._queued)

    # -- the clock ----------------------------------------------------------
    def _loop(self) -> None:
        next_tick = 0.0                      # tick immediately on the first pass
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if now >= next_tick:
                    self.enqueue_due()
                    next_tick = now + self._tick
                # Wait on the QUEUE, not on a sleep: a "run now" press has to be
                # picked up at once, and an idle stretch still wakes on the tick.
                wait = max(0.05, next_tick - time.monotonic())
                if self._hold_until > time.time():
                    # The panel is busy with a button-driven action; sit the hold
                    # out rather than taking work we cannot start.
                    self._stop.wait(min(wait, self._hold_until - time.time()))
                    continue
                try:
                    key, scheduled = self._queue.get(timeout=wait)
                except queue.Empty:
                    continue
                self._run_queued(key, scheduled)
            except Exception as exc:                      # noqa: BLE001
                # A scheduler that dies takes every timer with it, silently —
                # so nothing above is allowed to escape this loop.
                self._log("timers.log.tick_error", error=exc)
                self._stop.wait(self._tick)

    def enqueue_due(self, now: float | None = None) -> list[str]:
        """Queue every errand that has come due. Returns the keys it queued."""
        now = time.time() if now is None else now
        config = normalize_config(self._config())
        pending = due_keys(config, self._store.records(), now)
        if not pending:
            return []
        if self._gate is not None:
            reason = self._gate()
            if reason:
                if reason != self._gate_said:
                    self._log(reason)
                    self._gate_said = reason
                return []
        self._gate_said = None
        return [key for key in pending if self._enqueue(key, scheduled=True)]

    def _run_queued(self, key: str, scheduled: bool) -> str:
        """Take one errand off the queue and run it.

        Returns ``"ran"`` / ``"skipped"`` / ``"busy"``. ``"busy"`` is the caller's
        signal to stop working the queue for now: the errand has been put back and
        re-running the pass would take the very same item straight off again.
        """
        spec = BY_KEY.get(key)
        if spec is None:                     # a key from an older config — drop it
            self._release(key)
            return "skipped"
        if self._gate is not None:
            reason = self._gate()
            if reason:
                # The game went away between queueing and running: drop it rather
                # than fail it — the next tick queues it again, unchanged.
                if reason != self._gate_said:
                    self._log(reason)
                    self._gate_said = reason
                self._release(key)
                return "skipped"
        ok, busy = self.run_one(spec, scheduled=scheduled)
        if busy:
            self._hold_until = time.time() + self._busy_retry
            self._requeue(key, scheduled)    # stays claimed: it is still waiting
            return "busy"
        self._release(key)
        return "ran" if ok else "skipped"

    def tick_once(self, now: float | None = None) -> list[str]:
        """Queue what is due and work the queue off, in order. Keys that ran.

        Exactly what the loop does over one tick, minus the waiting — which is
        what makes the schedule's behaviour testable without threads at all.
        """
        self.enqueue_due(now)
        return self.drain()

    def drain(self) -> list[str]:
        """Run the queue down, one errand at a time, until it is empty or held."""
        ran = []
        while not self._stop.is_set():
            if self._hold_until > time.time():
                break                        # the panel is busy — the rest waits
            try:
                key, scheduled = self._queue.get_nowait()
            except queue.Empty:
                break
            status = self._run_queued(key, scheduled)
            if status == "busy":
                # It went back on the queue: stop the pass, or the next lap would
                # pull the same item off again and ask the busy panel in a spin.
                break
            if status == "ran":
                ran.append(key)
        return ran

    def run_one(self, spec: TimerSpec, scheduled: bool = False) -> tuple[bool, bool]:
        """Run one errand and record the outcome. Returns ``(ran, busy)``.

        ``busy`` is the one outcome that is not a verdict on the errand: the panel
        had a button-driven action of its own in flight, so the errand has not been
        tried at all and the caller keeps it queued. A raise is a real failure
        (recorded, held back); anything else is a run (recorded, clock reset).

        Both the tick and the "run now" button come through here, which is what
        makes a manual press restart the period exactly like an automatic run.
        """
        name = "+".join(spec.actions)
        if scheduled:
            self._log("timers.log.fire", name=name,
                      mins=self._minutes_since(spec.key))
        else:
            self._log("timers.log.manual", name=name)
        try:
            started = self._runner(spec)
        except Exception as exc:                          # noqa: BLE001
            self._store.mark_failed(spec.key)
            self._log("timers.log.failed", name=name, error=exc)
            return False, False
        if not started:
            self._log("timers.log.skip_busy", name=name)
            return False, True
        self._store.mark_run(spec.key)
        self._log("timers.log.done", name=name)
        return True, False

    def _minutes_since(self, key: str) -> int:
        last = self._store.last_run(key)
        if not last:
            return 0
        return int((time.time() - last) // 60)
