r"""Scheduled repeats of the panel's actions — the timer module.

A *timer* is a scenario plus a period: "collect the base every hour", "keep the
alliance up — donate, then claim the gifts — every hour". While the panel is open
a background thread ticks; a timer whose last successful run is older than its
period runs its scenario headless (no window opened, no mouse) and writes down
when it finished. That record lives in the profile directory, so closing the
panel does not reset the clock — a timer that came due while it was shut fires
shortly after the next launch.

The list of timers is **data, not code, and it belongs to the profile**: it is
read from ``panel/profiles/<profile>/timers.json``, so a new timer is a new entry
in that file and nothing here has to change. Two accounts therefore keep two
different schedules — different timers, each with its own switch, period and args
— and switching profiles in the panel switches the whole set.

A profile that has none yet is seeded from the *template*, ``panel/timers.json``,
which is itself seeded from the hardcoded catalogue below the first time the
panel runs. So the chain is: built-in list → template (edit it to change what new
profiles start with) → the profile's own file (what actually runs, and what the
panel's checkboxes write to). The built-in list is also the last-resort fallback
if a profile's file is ever unreadable.

    [
      {
        "name": "collect_base_resources",       // id: config key and record key
        "scenario": "collect_base_resources",   // one action, or a list (below)
        "interval_sec": 3600,
        "enabled": false,
        "args": {}
      },
      {
        "name": "alliance_upkeep",
        "scenario": ["donate_alliance_tech", "collect_alliance_gifts"],
        "interval_sec": 3600,
        "enabled": false,
        "args": {},
        "title": "Alliance: donate, then claim the gifts"
      }
    ]

``scenario`` is one step or a list of them, run in order. A step is either the
name of an action script (``src/lastwar_bot/actions/<name>.md``) or, when no such
script exists, DSL source run as-is — so a timer can carry its commands inline::

    {"name": "quick_donate", "scenario": "TAP donate_1000 xall", "interval_sec": 1200}

``args`` is handed to the scenario as script variables (the same ``ctx.vars`` that
``READ_LUA … INTO x`` writes), so steps can test them with the ordinary
``IF x > 3`` conditions, and ``{name}`` in an inline step is replaced by the
matching value before it is parsed.

Every field except ``name`` and ``scenario`` may be left out: it then falls back
to the entry of the same name in the hardcoded catalogue, and failing that to the
module defaults. ``enabled`` and ``interval_sec`` are what the panel's own
checkbox and period write back to — the profile's file is the one source of truth
for its schedule, not a default some other setting overrides. **The whole entry is
editable from the Timers tab** (add / copy / edit / delete, steps and args
included, via :meth:`Catalogue.replace` and :meth:`Catalogue.remove`); the file
stays the record, and editing it by hand and pressing «⟳» works exactly as before.

What the module decides, and what it deliberately does not:

  * **A timer that has never run is due at once.** "Not collected for over an
    hour" is exactly what an empty record means, so the first tick after a fresh
    profile fires everything that is switched on.
  * **A failed run is not a run.** ``last_run`` only moves when the scenario
    really finished, so a run lost to a closed game is retried rather than
    silently skipped for another hour. To keep a permanently broken scenario from
    re-firing every tick, a failure parks that one timer for
    :data:`RETRY_HOLD_SEC`.
  * **One thing at a time, in one thread.** Every scheduled scenario runs on the
    single worker thread, fed by a queue — nothing ever runs in parallel with
    anything else. Two timers that come due in the same second go on the queue in
    order and the second waits for the first to finish; the "run now" button
    enqueues too, rather than starting a thread of its own. When the panel is busy
    with a button-driven action of its own, the errand stays queued and is taken
    up again a few seconds later, so it is delayed, never lost.

Nothing here imports Tk or the game: the panel passes in the settings, a runner
and a log sink, which keeps the decision — *what is due right now* — a plain
function that tests can call without a display or a running client.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field

from .profile import _write_json

# How often the scheduler wakes up to look for a due timer. Well under the
# shortest sensible period, so a timer fires within a few seconds of coming due,
# and a tick that finds nothing costs one dict comparison. A timer configured
# with a period shorter than this simply fires once a tick.
TICK_SEC = 20.0

# After a failed run, how long that timer is left alone before it is tried again.
# Without it a scenario that fails for a standing reason (game closed mid-run, a
# broken recipe) would re-fire every tick and fill the log with the same error.
RETRY_HOLD_SEC = 300.0

# How long the worker sits still after the panel turns an errand down as busy.
# The errand stays in the queue either way; this is only about not asking again
# in a tight loop while a person's own button press runs its course.
BUSY_RETRY_SEC = 5.0

# Bounds enforced on whatever the config asks for, so a hand-edited file cannot
# ask for a timer that fires every second or one that never fires at all.
MIN_INTERVAL_SEC = 10
MAX_INTERVAL_SEC = 7 * 24 * 3600
DEFAULT_INTERVAL_SEC = 3600

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
# The TEMPLATE, beside the panel: what a profile that has no timers of its own is
# seeded from, and nothing else. The catalogue a profile actually runs lives in
# its own directory (ProfileManager.timers_json), next to the record of when each
# of them last ran — so one account's schedule is not the other's.
TEMPLATE_FILE = os.path.join(PANEL_DIR, "timers.json")


@dataclass(frozen=True)
class Timer:
    """One schedulable errand, as configured.

    ``scenario`` is a *sequence* because an errand is not always one press: the
    alliance one is "donate, then claim the gifts", which is two recipes that
    belong to a single switch and a single clock. The runner walks them in order
    and the errand only counts as done when the last one has finished — a
    donation that went through followed by a failed gift claim is a failed
    errand, and the retry does both. That is the safe way round: both recipes
    no-op when there is nothing to take.
    """

    name: str                       # id — config key, record key, log name
    scenario: tuple[str, ...]       # action names and/or inline DSL source
    interval_sec: int = DEFAULT_INTERVAL_SEC
    enabled: bool = False
    args: dict = field(default_factory=dict)
    title: str | None = None        # row label straight from the config
    label_key: str | None = None    # …or a locale key, for the built-in entries

    def as_dict(self) -> dict:
        """The entry as it is written in the catalogue file."""
        out = {
            "name": self.name,
            "scenario": list(self.scenario) if len(self.scenario) != 1
            else self.scenario[0],
            "interval_sec": self.interval_sec,
            "enabled": self.enabled,
        }
        if self.args:
            out["args"] = dict(self.args)
        if self.title:
            out["title"] = self.title
        return out


# The fallback catalogue: what ships in the box, what a missing file is seeded
# from, and what each field falls back to when an entry leaves it out. Every
# recipe behind these is headless (the gift one opens the alliance window inside
# the game and closes it again, still without touching the mouse), so a timer
# firing never takes the machine away from whoever is using it.
DEFAULT_TIMERS: tuple[Timer, ...] = (
    Timer(
        name="collect_base_resources",
        scenario=("collect_base_resources",),
        # An hour. The production buildings keep banking while nobody collects,
        # so the period is about not letting them sit full, not about a cap.
        interval_sec=3600,
        label_key="timers.item.collect_base_resources",
    ),
    Timer(
        name="alliance_upkeep",
        # Donation first: it is the one with something to lose. Attempts bank up
        # on their own timer and the routine wants them spent every 20 minutes,
        # so if the pair is ever cut short it should be cut short at the gifts,
        # which simply wait in the window until the next round.
        scenario=("donate_alliance_tech", "collect_alliance_gifts"),
        interval_sec=3600,
        label_key="timers.item.alliance_upkeep",
    ),
    Timer(
        name="collect_truck_resources",
        scenario=("collect_truck_resources",),
        # Four hours. The base truck's idle-reward accumulator fills slowly and one
        # claim empties it, so there is nothing to gain from looking oftener.
        interval_sec=14400,
        enabled=False,
        label_key="timers.item.collect_truck_resources",
    ),
    Timer(
        name="collect_visitor_gifts",
        scenario=("collect_visitor_gifts",),
        # An hour. A gift-bearing survivor waits in the city queue until collected,
        # so hourly keeps the queue clear without pestering a mostly-empty one.
        interval_sec=3600,
        enabled=False,
        label_key="timers.item.collect_visitor_gifts",
    ),
    Timer(
        name="recruit_survivors",
        scenario=("recruit_survivors",),
        # An hour, the same cadence as the gifts — a recruitable survivor sits in the
        # same city queue, and the recipe no-ops when none is waiting.
        interval_sec=3600,
        enabled=False,
        label_key="timers.item.recruit_survivors",
    ),
)


def _as_scenario(raw) -> tuple[str, ...]:
    """Coerce a ``scenario`` field into a tuple of steps."""
    if isinstance(raw, str):
        steps = [raw]
    elif isinstance(raw, (list, tuple)):
        steps = [str(step) for step in raw]
    else:
        return ()
    return tuple(step for step in (s.strip() for s in steps) if step)


def _as_interval(raw, fallback: int) -> int:
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return fallback
    return max(MIN_INTERVAL_SEC, min(MAX_INTERVAL_SEC, value))


class Catalogue:
    """The configured list of timers, plus whatever was wrong with the file.

    ``errors`` is not an exception on purpose: a typo in one entry must cost that
    entry, not the whole schedule, and the panel prints the complaints into its
    log where the person who typed them will see them.
    """

    def __init__(self, timers, path: str | None = None, errors=()) -> None:
        self.timers: tuple[Timer, ...] = tuple(timers)
        self.path = path
        self.errors: tuple[str, ...] = tuple(errors)
        self._by_name = {timer.name: timer for timer in self.timers}

    # -- lookup -------------------------------------------------------------
    def __iter__(self):
        return iter(self.timers)

    def __len__(self) -> int:
        return len(self.timers)

    def by_name(self, name: str) -> Timer | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return [timer.name for timer in self.timers]

    # -- settings -----------------------------------------------------------
    def default_config(self) -> dict:
        """Each timer's switch and period as the catalogue asks for them.

        The panel's saved settings override this per profile; a timer the file
        marks ``"enabled": true`` therefore starts on for a profile that has
        never seen it, and stays as the operator left it afterwards.
        """
        return {timer.name: {"enabled": timer.enabled,
                             "interval_sec": timer.interval_sec}
                for timer in self.timers}

    def normalize_config(self, raw) -> dict:
        """Coerce stored/typed settings into ``{name: {enabled, interval_sec}}``.

        The panel's spinboxes hand over strings, a profile saved before a timer
        existed has no entry for it, and one saved after a timer was deleted has
        an entry for nothing — so every value is re-derived here against the
        current catalogue rather than trusted. An unreadable period falls back to
        the configured one instead of dropping the row: a mistyped number must
        not silently disable a timer the operator believes is on.
        """
        raw = raw if isinstance(raw, dict) else {}
        out = self.default_config()
        for timer in self.timers:
            item = raw.get(timer.name)
            if not isinstance(item, dict):
                continue
            out[timer.name]["enabled"] = bool(item.get("enabled", timer.enabled))
            out[timer.name]["interval_sec"] = _as_interval(
                item.get("interval_sec", timer.interval_sec), timer.interval_sec)
        return out

    def with_settings(self, config: dict) -> "Catalogue":
        """A copy carrying the panel's switches and periods, ready to be saved.

        Only those two fields move. The scenario, the args and the title are the
        operator's text: the Timers tab edits them through :meth:`replace`, which
        writes a whole entry deliberately, while a ticked box or a retyped period
        goes through here and must not be able to touch anything else on the row.
        """
        config = self.normalize_config(config)
        updated = []
        for timer in self.timers:
            item = config[timer.name]
            updated.append(Timer(
                name=timer.name, scenario=timer.scenario,
                interval_sec=int(item["interval_sec"]),
                enabled=bool(item["enabled"]),
                args=dict(timer.args), title=timer.title,
                label_key=timer.label_key))
        return Catalogue(updated, self.path, self.errors)

    # -- editing (the Timers tab's Add / Duplicate / Delete / Edit) ----------
    #
    # Every one returns a NEW catalogue rather than mutating this one: the
    # scheduler thread reads `catalogue()` on its own clock, and swapping the
    # object it will read next is atomic where editing the list under it is not.
    def replace(self, timer: Timer) -> "Catalogue":
        """This catalogue with ``timer`` in place of the entry of the same name.

        An unknown name is appended, so "save what the dialog holds" is one call
        whether the dialog was opened on an existing row or on a new one.
        """
        out, replaced = [], False
        for existing in self.timers:
            if existing.name == timer.name:
                out.append(timer)
                replaced = True
            else:
                out.append(existing)
        if not replaced:
            out.append(timer)
        return Catalogue(out, self.path, self.errors)

    def remove(self, name: str) -> "Catalogue":
        """This catalogue without the named entry (a no-op if it is not in it)."""
        return Catalogue([t for t in self.timers if t.name != name],
                         self.path, self.errors)

    def unique_name(self, base: str) -> str:
        """``base``, or ``base_2`` / ``base_3`` … — the first one not taken.

        What Duplicate needs: the name is the id the schedule keys its clock on,
        so a copy must not answer to the original's record.
        """
        base = (base or "timer").strip() or "timer"
        if base not in self._by_name:
            return base
        n = 2
        while f"{base}_{n}" in self._by_name:
            n += 1
        return f"{base}_{n}"

    # -- the decision -------------------------------------------------------
    def due_names(self, config: dict, records: dict, now: float) -> list[str]:
        """Which enabled timers are due at ``now``, the most overdue first.

        ``records`` is the last-run store's raw mapping (see
        :class:`LastRunStore`). A timer with no record has never run and is due
        immediately; one whose last attempt failed is held for
        :data:`RETRY_HOLD_SEC` before being offered again.
        """
        out = []
        for timer in self.timers:
            item = config.get(timer.name) or {}
            if not item.get("enabled"):
                continue
            rec = records.get(timer.name) or {}
            failed_at = float(rec.get("failed_at") or 0.0)
            if failed_at and now - failed_at < RETRY_HOLD_SEC:
                continue
            last = float(rec.get("last_run") or 0.0)
            period = _as_interval(item.get("interval_sec"), timer.interval_sec)
            overdue = now - last - period
            if overdue >= 0:
                out.append((overdue, timer.name))
        out.sort(key=lambda pair: pair[0], reverse=True)
        return [name for _overdue, name in out]

    def next_due(self, timer: Timer, config: dict, records: dict) -> float | None:
        """Wall clock the timer fires at, ``0.0`` for "now" and ``None`` when off."""
        item = config.get(timer.name) or {}
        if not item.get("enabled"):
            return None
        rec = records.get(timer.name) or {}
        last = float(rec.get("last_run") or 0.0)
        if not last:
            return 0.0
        return last + _as_interval(item.get("interval_sec"), timer.interval_sec)


def default_catalogue() -> Catalogue:
    """The hardcoded fallback, as a catalogue."""
    return Catalogue(DEFAULT_TIMERS)


def parse_catalogue(data, path: str | None = None,
                    fallback: "Catalogue | None" = None) -> Catalogue:
    """Build a catalogue from already-decoded JSON.

    Accepts either a bare list of entries or ``{"timers": [...]}``. The FILE owns
    the list — a timer deleted from it is gone — while each entry falls back
    field by field to the one of the same name in ``fallback`` (the template, and
    behind it the built-ins), so an entry may be as short as
    ``{"name": "collect_base_resources", "interval_sec": 1800}``.
    """
    fallback_timers = fallback.timers if fallback is not None else DEFAULT_TIMERS
    if isinstance(data, dict):
        data = data.get("timers")
    if not isinstance(data, list):
        return Catalogue(fallback_timers, path,
                         ["config is not a list of timers — using the defaults"])

    builtin = {timer.name: timer for timer in DEFAULT_TIMERS}
    builtin.update({timer.name: timer for timer in fallback_timers})
    timers, errors, seen = [], [], set()
    for index, raw in enumerate(data):
        if not isinstance(raw, dict):
            errors.append(f"entry #{index + 1} is not an object — skipped")
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            errors.append(f"entry #{index + 1} has no name — skipped")
            continue
        if name in seen:
            errors.append(f"{name}: listed twice — the later entry is ignored")
            continue
        base = builtin.get(name)
        scenario = _as_scenario(raw.get("scenario"))
        if not scenario:
            scenario = base.scenario if base else ()
        if not scenario:
            errors.append(f"{name}: no scenario to run — skipped")
            continue
        args = raw.get("args")
        timers.append(Timer(
            name=name,
            scenario=scenario,
            interval_sec=_as_interval(
                raw.get("interval_sec"),
                base.interval_sec if base else DEFAULT_INTERVAL_SEC),
            enabled=bool(raw.get("enabled", base.enabled if base else False)),
            args=dict(args) if isinstance(args, dict) else {},
            title=(str(raw["title"]).strip() or None) if raw.get("title") else None,
            label_key=base.label_key if base else None,
        ))
        seen.add(name)

    if not timers:
        # An empty list is a legitimate answer — "this account schedules nothing"
        # — but a file whose every entry was junk is not, and falling back is the
        # kinder reading of it. The complaints above say which it was.
        if not errors:
            return Catalogue((), path)
        errors.append("no usable timers in the config — using the defaults")
        return Catalogue(fallback_timers, path, errors)
    return Catalogue(timers, path, errors)


def load_catalogue(path: str, seed_from=None) -> Catalogue:
    """Read a catalogue file, falling back to ``seed_from`` / the built-in list.

    A file that does not exist yet is *written* from the seed, so there is always
    something on disk to edit — which is the whole point: a new timer must be a
    new entry in a file, not a code change. A file that exists but cannot be read
    is NOT overwritten: the panel runs on the fallback and says so, leaving
    whatever the operator typed there for them to fix.
    """
    seed = seed_from if seed_from is not None else Catalogue(DEFAULT_TIMERS)
    if not os.path.exists(path):
        fresh = Catalogue(seed.timers, path)
        save_catalogue(fresh, path)
        return fresh
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return Catalogue(seed.timers, path, [f"{os.path.basename(path)}: {exc}"])
    return parse_catalogue(data, path, fallback=seed)


def load_template() -> Catalogue:
    """The template new profiles are seeded from (``panel/timers.json``)."""
    return load_catalogue(TEMPLATE_FILE)


def load_profile_catalogue(path: str) -> Catalogue:
    """The catalogue a profile runs, seeded from the template when it has none."""
    return load_catalogue(path, seed_from=load_template())


def save_catalogue(catalogue: Catalogue, path: str | None = None) -> None:
    """Write a catalogue back out in the file's own format."""
    _write_json(path or catalogue.path or TEMPLATE_FILE,
                [timer.as_dict() for timer in catalogue.timers])


class LastRunStore:
    """When each timer last ran, kept next to the profile it belongs to.

    One small JSON file, ``{name: {"last_run": epoch, "failed_at": epoch}}``,
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

    def last_run(self, name: str) -> float:
        with self._lock:
            return float((self._data.get(name) or {}).get("last_run") or 0.0)

    # -- writing ------------------------------------------------------------
    def mark_run(self, name: str, when: float | None = None) -> None:
        """Record a successful run, clearing any earlier failure hold."""
        self._update(name, {"last_run": float(when if when is not None else time.time()),
                            "failed_at": 0.0})

    def mark_failed(self, name: str, when: float | None = None) -> None:
        """Record a failed attempt — the period keeps running, the retry waits."""
        self._update(name, {"failed_at": float(when if when is not None else time.time())})

    def _update(self, name: str, fields: dict) -> None:
        with self._lock:
            rec = dict(self._data.get(name) or {})
            rec.update(fields)
            self._data[name] = rec
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

    **No timer scenario ever runs in parallel with another.** The thread is both
    the clock and the only worker: on each tick it puts the errands that have come
    due on the queue, then takes them off one at a time and runs each to
    completion. Two timers that come due in the same second do not race — the
    second one waits in the queue until the first has finished. The row's "run
    now" button does not start a thread of its own either; it *enqueues*, so a
    press during a running errand takes its turn behind it instead of being
    dropped or overlapping it.

    Being both clock and worker is why the wait is on the queue rather than a
    sleep: an errand enqueued by hand is picked up at once, while an idle stretch
    still wakes on the tick.

    Collaborators are all callables, so nothing about Tk or the game leaks in:

      * ``catalogue()`` -> the current :class:`Catalogue` (a callable, so the file
                          can be re-read while the panel is open);
      * ``config()``   -> the normalised settings dict (read fresh every tick, so
                          a checkbox or period change applies without a restart);
      * ``runner(timer)`` -> ``True`` when the errand really ran, ``False`` when it
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

    def __init__(self, *, store: LastRunStore, catalogue, config, runner, log,
                 gate=None, tick: float = TICK_SEC,
                 busy_retry: float = BUSY_RETRY_SEC) -> None:
        self._store = store
        self._catalogue = catalogue
        self._config = config
        self._runner = runner
        self._log = log
        self._gate = gate
        self._tick = tick
        self._busy_retry = busy_retry
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._gate_said: str | None = None
        # The work queue. Items are (name, scheduled) — `scheduled` only picks the
        # log line. `_queued` keeps a name from being lined up twice: a second
        # press while the first is still waiting would run the errand twice in a
        # row for no reason.
        self._queue: "queue.Queue[tuple[str, bool]]" = queue.Queue()
        self._queued: set[str] = set()
        # Names the UI asked to take back off the queue. Marked rather than removed
        # (a Queue cannot be searched), and dropped by the worker when it gets there.
        self._cancelled: set[str] = set()
        # The errand being run right now, if any. `_queued` cannot tell waiting from
        # running (a claim covers both), and `cancel` has to: one is cancellable and
        # the other is not.
        self._running: str | None = None
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
    def request(self, timer: Timer) -> bool:
        """Ask for an errand by hand ("run now"). ``False`` if already queued.

        Called from the UI thread and returns immediately — the errand runs on the
        worker like a scheduled one, so it cannot overlap whatever is running.
        """
        return self._enqueue(timer.name, scheduled=False)

    def _enqueue(self, name: str, scheduled: bool) -> bool:
        with self._queue_lock:
            if name in self._queued:
                return False
            self._queued.add(name)
        self._queue.put((name, scheduled))
        return True

    def _requeue(self, name: str, scheduled: bool) -> None:
        """Put a turned-down errand back on the queue, still claimed.

        At the back, not the front: it was never started, so nothing is half done,
        and whatever is queued behind it came due just as much. Keeping its claim
        is what stops the next tick from lining the same errand up twice.
        """
        self._queue.put((name, scheduled))

    def _release(self, name: str) -> None:
        with self._queue_lock:
            self._queued.discard(name)
            # The cancel mark goes with the claim. A cancel that arrived while the
            # errand was already running is refused (see `cancel`), but a mark left
            # behind by any other race would silently swallow the NEXT run of the
            # same errand — a bug that would look like a timer that fires once and
            # then skips a turn for no reason.
            self._cancelled.discard(name)

    def pending(self) -> set[str]:
        """Names currently queued or being run — for tests and the row painter."""
        with self._queue_lock:
            return set(self._queued)

    def cancel(self, name: str) -> bool:
        """Take a WAITING errand back off the queue. ``False`` if there is none.

        The Timers tab had no cancel at all: a «Запустить» pressed by mistake, or a
        tick that queued three errands behind a slow one, could only be waited out.

        The item is not plucked out of the queue — a ``queue.Queue`` cannot be
        searched — it is *marked*, and the worker drops it when it comes off.

        An errand that is **already running** is not cancellable and says so
        (``False``): the press is in flight, and killing a scenario mid-call into
        the game is exactly what the Scenarios tab's Stop refuses to do too. Saying
        "taken off the queue" about a run that then completes would be a lie the
        operator acts on.
        """
        with self._queue_lock:
            if name not in self._queued or name == self._running:
                return False
            self._cancelled.add(name)
            return True

    def _take_cancelled(self, name: str) -> bool:
        """Was ``name`` cancelled while it waited? Clears the mark either way."""
        with self._queue_lock:
            if name in self._cancelled:
                self._cancelled.discard(name)
                return True
            return False

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
                    name, scheduled = self._queue.get(timeout=wait)
                except queue.Empty:
                    continue
                self._run_queued(name, scheduled)
            except Exception as exc:                      # noqa: BLE001
                # A scheduler that dies takes every timer with it, silently —
                # so nothing above is allowed to escape this loop.
                self._log("timers.log.tick_error", error=exc)
                self._stop.wait(self._tick)

    def enqueue_due(self, now: float | None = None) -> list[str]:
        """Queue every errand that has come due. Returns the names it queued."""
        now = time.time() if now is None else now
        catalogue = self._catalogue()
        config = catalogue.normalize_config(self._config())
        pending = catalogue.due_names(config, self._store.records(), now)
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
        return [name for name in pending if self._enqueue(name, scheduled=True)]

    def _run_queued(self, name: str, scheduled: bool) -> str:
        """Take one errand off the queue and run it.

        Returns ``"ran"`` / ``"skipped"`` / ``"busy"``. ``"busy"`` is the caller's
        signal to stop working the queue for now: the errand has been put back and
        re-running the pass would take the very same item straight off again.
        """
        if self._take_cancelled(name):       # the UI took it back while it waited
            self._log("timers.log.cancelled", name=name)
            self._release(name)
            return "skipped"
        timer = self._catalogue().by_name(name)
        if timer is None:                    # deleted from the config mid-run
            self._release(name)
            return "skipped"
        if self._gate is not None:
            reason = self._gate()
            if reason:
                # The game went away between queueing and running: drop it rather
                # than fail it — the next tick queues it again, unchanged.
                if reason != self._gate_said:
                    self._log(reason)
                    self._gate_said = reason
                self._release(name)
                return "skipped"
        # Mark it as running for the whole call, so `cancel` can tell "waiting in
        # the queue" (cancellable) from "in flight" (not).
        with self._queue_lock:
            self._running = name
        try:
            ok, busy = self.run_one(timer, scheduled=scheduled)
        finally:
            with self._queue_lock:
                self._running = None
        if busy:
            self._hold_until = time.time() + self._busy_retry
            self._requeue(name, scheduled)   # stays claimed: it is still waiting
            return "busy"
        self._release(name)
        return "ran" if ok else "skipped"

    def tick_once(self, now: float | None = None) -> list[str]:
        """Queue what is due and work the queue off, in order. Names that ran.

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
                name, scheduled = self._queue.get_nowait()
            except queue.Empty:
                break
            status = self._run_queued(name, scheduled)
            if status == "busy":
                # It went back on the queue: stop the pass, or the next lap would
                # pull the same item off again and ask the busy panel in a spin.
                break
            if status == "ran":
                ran.append(name)
        return ran

    def run_one(self, timer: Timer, scheduled: bool = False) -> tuple[bool, bool]:
        """Run one errand and record the outcome. Returns ``(ran, busy)``.

        ``busy`` is the one outcome that is not a verdict on the errand: the panel
        had a button-driven action of its own in flight, so the errand has not been
        tried at all and the caller keeps it queued. A raise is a real failure
        (recorded, held back); anything else is a run (recorded, clock reset).

        Both the tick and the "run now" button come through here, which is what
        makes a manual press restart the period exactly like an automatic run.
        """
        if scheduled:
            self._log("timers.log.fire", name=timer.name,
                      mins=self._minutes_since(timer.name))
        else:
            self._log("timers.log.manual", name=timer.name)
        try:
            started = self._runner(timer)
        except Exception as exc:                          # noqa: BLE001
            self._store.mark_failed(timer.name)
            self._log("timers.log.failed", name=timer.name, error=exc)
            return False, False
        if not started:
            self._log("timers.log.skip_busy", name=timer.name)
            return False, True
        self._store.mark_run(timer.name)
        self._log("timers.log.done", name=timer.name)
        return True, False

    def _minutes_since(self, name: str) -> int:
        last = self._store.last_run(name)
        if not last:
            return 0
        return int((time.time() - last) // 60)
