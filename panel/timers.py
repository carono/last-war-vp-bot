r"""Scheduled repeats of the panel's actions — the timer module.

A *timer* is a scenario plus a period: "collect the base every hour", "donate to
the alliance's technology every twenty minutes". While the panel is open
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

An errand that appears LATER — a new ability shipped with an update — is adopted
into every profile once, switched off, so it does not stay invisible to the
accounts that already had a file. It comes from the template *and* the built-in
list, because the template is a local file that an updated installation still has
last month's copy of. Deleting the errand afterwards keeps it deleted; the how and
the why are in :func:`adopt_new_errands` and :func:`offered_catalogue`.

    [
      {
        "name": "collect_base_resources",       // id: config key and record key
        "scenario": "collect_base_resources",   // one action, or a list (below)
        "interval_sec": 3600,
        "retry_sec": 300,                        // wait this long after a FAILED run
        "enabled": false,
        "args": {}
      },
      {
        "name": "quick_sweep",
        "scenario": ["collect_truck_resources", "collect_base_resources"],
        "interval_sec": 3600,
        "enabled": false,
        "args": {},
        "title": "Everything the base has banked"
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

from . import debug_log, paths
from .i18n import Message
from .profile import _write_json

# Component debug logger (panel/debug_log.py) — the panel wires the rotating file
# under it; here we only record the scheduler's key events.
_dbg = debug_log.get_logger("timers")

# How often the scheduler wakes up to look for a due timer. Well under the
# shortest sensible period, so a timer fires within a few seconds of coming due,
# and a tick that finds nothing costs one dict comparison. A timer configured
# with a period shorter than this simply fires once a tick.
TICK_SEC = 20.0

# Default hold after a failed run, before the timer is tried again. Per-timer now
# (``Timer.retry_sec``): a scenario that FAILs on a precondition it will soon meet
# (not on the base yet) wants a short retry, while a truly broken one should not
# re-fire every tick and fill the log with the same error. This is the fallback for
# an entry that does not set its own.
RETRY_HOLD_SEC = 300.0

# How long the worker sits still after the panel turns an errand down as busy.
# The errand stays in the queue either way; this is only about not asking again
# in a tight loop while a person's own button press runs its course.
BUSY_RETRY_SEC = 5.0

# How often ONE errand may repeat the same reason for being skipped. A skip has to be
# said — «тихо не поехали» is exactly what #1281 was about, and a wire trigger can be
# refused hundreds of times an hour (a profile whose client is down heard 10 035 rally
# pushes on 2026-08-07 and its log carried 31 lines about it, none of them attached to a
# rally). Saying every one would drown the log; saying only the first hides how much is
# being lost. So the first is said at once and the rest are rolled up: the same reason
# repeats at most this often, carrying the count it has gathered since.
SKIP_NOTE_SEC = 60.0

# Bounds enforced on whatever the config asks for, so a hand-edited file cannot
# ask for a timer that fires every second or one that never fires at all.
MIN_INTERVAL_SEC = 10
MAX_INTERVAL_SEC = 7 * 24 * 3600
DEFAULT_INTERVAL_SEC = 3600

PANEL_DIR = paths.PANEL_DIR
# The TEMPLATE, beside the profiles rather than beside the code (#1276): what a profile
# that has no timers of its own is seeded from, and nothing else. The catalogue a profile
# actually runs lives in its own directory (ProfileManager.timers_json), next to the
# record of when each of them last ran — so one account's schedule is not the other's.
TEMPLATE_FILE = paths.TIMERS_TEMPLATE


@dataclass(frozen=True)
class Timer:
    """One schedulable errand, as configured.

    ``scenario`` is a *sequence* because an errand is not always one press: a
    profile may want two recipes under a single switch and a single clock. The
    runner walks them in order and the errand only counts as done when the last
    one has finished — a first step that went through followed by a failed second
    is a failed errand, and the retry does both.

    That is a shape the operator may ask for, not one the built-ins reach for:
    two recipes on one clock can only ever have ONE period, and errands that
    genuinely want different ones — a donation every 20 minutes and a gift chest
    every six hours — must be two rows (:data:`SPLIT_ERRANDS`).
    """

    name: str                       # id — config key, record key, log name
    scenario: tuple[str, ...]       # action names and/or inline DSL source
    interval_sec: int = DEFAULT_INTERVAL_SEC
    # How long to wait before retrying after a FAILED run (a raised step or a FAIL in
    # the scenario). A success uses interval_sec; only a failure uses this.
    retry_sec: int = int(RETRY_HOLD_SEC)
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
            "retry_sec": self.retry_sec,
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
        name="donate_alliance_tech",
        scenario=("donate_alliance_tech",),
        # Twenty minutes, which is the rate the game hands the attempts back at.
        # This is the errand with something to lose: the attempts bank up to a cap
        # and every one that is still banked when the day turns is simply gone, so
        # it wants the short clock — and used to be denied it by sharing one with
        # the gifts.
        interval_sec=1200,
        # The press is headless and no-ops on an empty quota, so a failure means the
        # game was not answering; five minutes is soon enough to catch the attempts
        # before the next batch lands on top of them.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.donate_alliance_tech",
    ),
    Timer(
        name="collect_alliance_gifts",
        scenario=("collect_alliance_gifts",),
        # Six hours. Nothing about a gift expires while it waits in the chest, and
        # this recipe — unlike the donation — opens a window in the game and closes
        # it again, so looking oftener costs the player's view for nothing.
        interval_sec=21600,
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_alliance_gifts",
    ),
    Timer(
        name="collect_truck_resources",
        scenario=("collect_truck_resources",),
        # Four hours. The base truck's idle-reward accumulator fills slowly and one
        # claim empties it, so there is nothing to gain from looking oftener.
        interval_sec=14400,
        # These three FAIL when the base is not on screen (they can only act in the
        # city scene), so a short retry picks them up as soon as the player is home.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_truck_resources",
    ),
    Timer(
        name="collect_visitor_gifts",
        scenario=("collect_visitor_gifts",),
        # An hour. A gift-bearing survivor waits in the city queue until collected,
        # so hourly keeps the queue clear without pestering a mostly-empty one.
        interval_sec=3600,
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_visitor_gifts",
    ),
    Timer(
        name="recruit_survivors",
        scenario=("recruit_survivors",),
        # An hour, the same cadence as the gifts — a recruitable survivor sits in the
        # same city queue, and the recipe no-ops when none is waiting.
        interval_sec=3600,
        retry_sec=300,
        enabled=False,
        label_key="timers.item.recruit_survivors",
    ),
    Timer(
        name="apply_ministry_interior",
        scenario=("apply_ministry_interior",),
        # Half an hour, and the retry is the same half hour on purpose. The recipe ends
        # as a FAILURE whenever the application did not go through (another post in hand,
        # the client's pre-flight closed, the server did not seat us), so `last_run` only
        # moves on a real application — which is exactly the asked-for behaviour: the
        # clock restarts on success and on nothing else, and a refused attempt is made
        # again in half an hour rather than sitting out a longer hold.
        interval_sec=1800,
        retry_sec=1800,
        enabled=False,
        label_key="timers.item.apply_ministry_interior",
    ),
    Timer(
        name="restart_game",
        scenario=("restart_game",),
        # Six hours. Nothing in the game is spent by a restart and nothing is lost —
        # the point is the client itself, which gets slower and less answerable the
        # longer one session lasts. Four restarts a day costs four times two minutes
        # of loading and buys a client that still replies at the end of the day.
        interval_sec=21600,
        # Ten minutes after a restart that did not come back. The recipe FAILs when
        # the base never appeared or the game link would not re-attach, and either
        # of those is worth another go soon — but not every tick, because a client
        # that will not start would otherwise be killed and relaunched all night.
        retry_sec=600,
        # OFF by default, like every other errand here. This one ends the session it
        # is run in, so it is the operator's decision and not a default.
        enabled=False,
        label_key="timers.item.restart_game",
    ),
)


#: Errands that were ONE row and are now several — the old name mapped to the names it
#: became. Retired here rather than merely deleted, because a name has three lives: the
#: profile files that still list it, the local template that still offers it, and the
#: "already shown to this profile" record that must keep it from coming back. What is
#: done about each is in :func:`split_legacy_errands` and :func:`offered_catalogue`.
#:
#: `alliance_upkeep` was "donate, then claim the gifts" on a single switch and therefore
#: a single period — and the two halves do not want the same one. The donation attempts
#: bank up every 20 minutes and are lost at the end of the day if they are not spent,
#: while the gift chest keeps for hours; one clock could only ever be right for one of
#: them, and the hour it was set to was right for neither.
SPLIT_ERRANDS: dict[str, tuple[str, ...]] = {
    "alliance_upkeep": ("donate_alliance_tech", "collect_alliance_gifts"),
}

#: What a retired errand used to run. An entry in a profile's file may leave the scenario
#: out and lean on the built-in of the same name (:func:`parse_catalogue`) — and a
#: retired name has no built-in any more, so without this the row would be dropped as
#: "nothing to run" and the operator's switch would go with it, before anything had the
#: chance to split it.
RETIRED_SCENARIOS: dict[str, tuple[str, ...]] = {
    "alliance_upkeep": ("donate_alliance_tech", "collect_alliance_gifts"),
}


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
                retry_sec=timer.retry_sec,
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
            if failed_at and now - failed_at < timer.retry_sec:
                continue
            last = float(rec.get("last_run") or 0.0)
            period = _as_interval(item.get("interval_sec"), timer.interval_sec)
            overdue = now - last - period
            if overdue >= 0:
                out.append((overdue, timer.name))
        out.sort(key=lambda pair: pair[0], reverse=True)
        return [name for _overdue, name in out]

    def next_due(self, timer: Timer, config: dict, records: dict) -> float | None:
        """Wall clock the timer fires at, ``0.0`` for "now" and ``None`` when off.

        The retry hold counts. A failed attempt leaves ``last_run`` where it was, so
        without it the row would say «сейчас» for the whole half hour the scheduler is
        deliberately sitting out — the display disagreeing with the schedule exactly in
        the case a retry hold exists for. Whichever of the two waits ends later wins.
        """
        item = config.get(timer.name) or {}
        if not item.get("enabled"):
            return None
        rec = records.get(timer.name) or {}
        last = float(rec.get("last_run") or 0.0)
        failed_at = float(rec.get("failed_at") or 0.0)
        after_failure = failed_at + timer.retry_sec if failed_at else 0.0
        if not last:
            return max(0.0, after_failure)
        return max(last + _as_interval(item.get("interval_sec"), timer.interval_sec),
                   after_failure)


# How the last attempt ended — what the Timers tab's status column says. The three
# states live here rather than in the panel because telling them apart is a decision
# about the record, not a paint job: a run that FAILED and one that has never happened
# both leave `last_run` at zero, and a row that showed them the same way would hide a
# timer that has been trying and getting nowhere for hours.
ATTEMPT_NONE = "none"        # never tried (or the record was lost)
ATTEMPT_OK = "ok"            # the last attempt finished clean
ATTEMPT_FAILED = "failed"    # the last attempt failed and is waiting out its retry


def last_attempt(records: dict, name: str) -> tuple[str, float]:
    """How ``name`` last ended, and when: ``(state, when)``.

    The later of the two timestamps wins, which is what makes this readable at all: a
    success clears the failure mark (:meth:`LastRunStore.mark_run`), and a failure
    leaves ``last_run`` alone, so "failed at 12:30 having last succeeded at 09:00" is
    the normal shape of a timer that is stuck — and the one worth showing.
    """
    rec = records.get(name) or {}
    last = float(rec.get("last_run") or 0.0)
    failed_at = float(rec.get("failed_at") or 0.0)
    if failed_at > last:
        return ATTEMPT_FAILED, failed_at
    if last:
        return ATTEMPT_OK, last
    return ATTEMPT_NONE, 0.0


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
                         [Message("log.timers.not_a_list",
                                   "config is not a list of timers — using the defaults")])

    builtin = {timer.name: timer for timer in DEFAULT_TIMERS}
    builtin.update({timer.name: timer for timer in fallback_timers})
    timers, errors, seen = [], [], set()
    for index, raw in enumerate(data):
        if not isinstance(raw, dict):
            errors.append(Message("log.timers.not_an_object",
                                  f"entry #{index + 1} is not an object — skipped",
                                  n=index + 1))
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            errors.append(Message("log.timers.no_name",
                                  f"entry #{index + 1} has no name — skipped",
                                  n=index + 1))
            continue
        if name in seen:
            errors.append(Message("log.timers.twice",
                                  f"{name}: listed twice — the later entry is ignored",
                                  name=name))
            continue
        base = builtin.get(name)
        scenario = _as_scenario(raw.get("scenario"))
        if not scenario:
            scenario = base.scenario if base else RETIRED_SCENARIOS.get(name, ())
        if not scenario:
            errors.append(Message("log.timers.no_scenario",
                                  f"{name}: no scenario to run — skipped", name=name))
            continue
        args = raw.get("args")
        timers.append(Timer(
            name=name,
            scenario=scenario,
            interval_sec=_as_interval(
                raw.get("interval_sec"),
                base.interval_sec if base else DEFAULT_INTERVAL_SEC),
            retry_sec=_as_interval(
                raw.get("retry_sec"),
                base.retry_sec if base else int(RETRY_HOLD_SEC)),
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
        errors.append(Message("log.timers.none_usable",
                              "no usable timers in the config — using the defaults"))
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


#: Beside a profile's catalogue: every errand name this profile has ever been offered.
#: See :func:`adopt_new_errands` for why one file is not enough.
SEEN_SUFFIX = "_seen.json"


def seen_path(catalogue_path: str) -> str:
    """Where the record of "already offered to this profile" lives."""
    base, _ext = os.path.splitext(catalogue_path)
    return base + SEEN_SUFFIX


def _read_seen(path: str) -> "set[str] | None":
    """The names this profile has been offered, or ``None`` if never recorded."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return {str(name) for name in data} if isinstance(data, list) else None


def offered_catalogue(template: "Catalogue | None" = None) -> Catalogue:
    """Everything this version has to offer a profile: the template, plus the built-ins.

    The template is a local file and is not shipped (it is written once, on the first
    run, and an operator may edit it), so an installation updated today has last
    month's template on disk. The built-in list below is what actually ships, which
    makes the union — the template first, since it is the one that was edited on
    purpose — the honest answer to "what should a profile be offered".

    A RETIRED name (:data:`SPLIT_ERRANDS`) is dropped from the template's half of that
    union: last month's template still lists it, and a profile created today must not be
    seeded with an errand this version has already replaced.
    """
    template = load_template() if template is None else template
    names = set(template.names())
    offered = [t for t in template.timers if t.name not in SPLIT_ERRANDS]
    offered += [t for t in DEFAULT_TIMERS if t.name not in names]
    return Catalogue(offered, template.path, template.errors)


def adopt_new_errands(catalogue: Catalogue, offered: Catalogue,
                      path: str) -> Catalogue:
    """Add errands this version offers that the profile has never been shown.

    A profile's file is written once, from the template, and is its own from then on
    — which is right for what it holds, and wrong for what it does not: a NEW ability
    shipped as a built-in errand would never reach an account that already had a
    file. "New timer, so open a JSON and copy the entry across" is not a feature.

    Copying the whole template over the file is not the answer either: the file owns
    the list on purpose (:func:`parse_catalogue`), and a deleted errand must stay
    deleted. So a second, tiny file remembers every name this profile has ever been
    OFFERED, and only names in neither are adopted — once. Delete a built-in
    afterwards and it stays gone, because it is in the record.

    The first run after this existed has no record; the profile's current names are
    taken as the record then, so an errand that shipped today is adopted and one the
    operator deleted long ago comes back that one time.

    Adopted entries arrive exactly as they are offered, which for every built-in means
    switched off: nothing starts pressing because the bot was updated.
    """
    record = seen_path(path)
    stored = _read_seen(record)
    first_time = stored is None
    known = set(catalogue.names())
    seen = set(known) if first_time else set(stored)
    fresh = [timer for timer in offered.timers
             if timer.name not in known and timer.name not in seen]
    if fresh:
        catalogue = Catalogue(list(catalogue.timers) + fresh,
                              catalogue.path or path, catalogue.errors)
        save_catalogue(catalogue, path)
    wanted = known | seen | set(offered.names())
    if first_time or wanted != seen:
        _write_json(record, sorted(wanted))
    return catalogue


def split_legacy_errands(catalogue: Catalogue, offered: Catalogue,
                         path: str) -> Catalogue:
    """Replace a retired errand with the rows it became, keeping its switch.

    The profile's file owns its list (:func:`parse_catalogue`) and nothing else may
    rewrite it — which is right for everything except this: an errand that was SPLIT is
    not a row the operator chose to keep, it is one this version no longer knows how to
    run on a single clock. Left alone, an account that had `alliance_upkeep` switched on
    would go on donating once an hour for ever while the panel showed it two new rows,
    switched off, doing the same work on the right periods.

    So the old row is taken out and the ones it became are put IN ITS PLACE, each with
    its own built-in period and **the switch the operator had set** — an errand that was
    running keeps running, one that was off stays off. Nothing is invented: if the
    profile already has one of the new rows (adopted, or typed by hand) that one is left
    exactly as it is.

    The retired name also goes into the "already shown" record, so a stale local template
    that still offers it cannot hand it back on the next launch.
    """
    stale = [t for t in catalogue.timers if t.name in SPLIT_ERRANDS]
    if not stale:
        return catalogue
    builtin = {timer.name: timer for timer in DEFAULT_TIMERS}
    before = set(catalogue.names())
    out: list[Timer] = []
    for timer in catalogue.timers:
        parts = SPLIT_ERRANDS.get(timer.name)
        if parts is None:
            out.append(timer)
            continue
        for part in parts:
            base = offered.by_name(part) or builtin.get(part)
            if base is None or any(t.name == part for t in out) or part in before:
                continue
            out.append(Timer(
                name=base.name, scenario=base.scenario,
                interval_sec=base.interval_sec, retry_sec=base.retry_sec,
                # The one thing carried across the split: the operator's decision.
                enabled=timer.enabled,
                args=dict(base.args), title=base.title, label_key=base.label_key))
    fresh = Catalogue(out, catalogue.path or path, catalogue.errors)
    save_catalogue(fresh, path)

    record = seen_path(path)
    stored = _read_seen(record)
    if stored is None:
        # No record yet, and :func:`adopt_new_errands` is about to take the profile's
        # list as one. Its list no longer holds the retired name, so write the record
        # HERE from the list as it was — otherwise a stale template would offer the old
        # errand straight back, and the split would undo itself on every launch. What
        # goes in is exactly what that first-time branch would have written.
        stored = before | set(offered.names())
    _write_json(record, sorted(stored | before | {t.name for t in out}))
    return fresh


def load_profile_catalogue(path: str) -> Catalogue:
    """The catalogue a profile runs, seeded from the template when it has none.

    A file that did not exist is written from the template; one that did keeps every
    word of what is in it, gains the errands this version has learnt since
    (:func:`adopt_new_errands`), and has any errand this version has SPLIT replaced by
    the rows it became (:func:`split_legacy_errands`).
    """
    template = load_template()
    offered = offered_catalogue(template)
    fresh_profile = not os.path.exists(path)
    catalogue = load_catalogue(path, seed_from=offered)
    if fresh_profile:
        # It IS everything on offer, so all of it counts as offered — otherwise a row
        # deleted tomorrow would be re-adopted the day after as "new".
        _write_json(seen_path(path),
                    sorted(set(offered.names()) | set(catalogue.names())))
        return catalogue
    if not _readable(path):
        # Unreadable: what came back is the FALLBACK, not this profile's list. Deciding
        # what it is missing from that would write our guess over the operator's file.
        return catalogue
    # The split runs FIRST: it is the one that has to see the file as it was written,
    # and it settles the "already shown" record the adoption below reads.
    catalogue = split_legacy_errands(catalogue, offered, path)
    return adopt_new_errands(catalogue, offered, path)


def _readable(path: str) -> bool:
    """Is the file there and still valid JSON? (Cheap: these are a few hundred bytes.)"""
    try:
        with open(path, encoding="utf-8") as fh:
            json.load(fh)
    except (OSError, ValueError):
        return False
    return True


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
                 busy_retry: float = BUSY_RETRY_SEC, debug=None,
                 translate=None) -> None:
        # `debug` is the OWNING RUNTIME's technical logger (`rt.dbg("timers")`), so two
        # open profiles keep two debug.logs (#1206). The module-level one is the
        # fallback for a scheduler built without a runtime, which is what the tests do.
        self._dbg = debug if debug is not None else _dbg
        self._store = store
        self._catalogue = catalogue
        self._config = config
        self._runner = runner
        self._log = log
        # `log` says a locale KEY as a whole line; `translate` turns one into words that
        # can go INSIDE a line. A skip needs the second: the errand's name, the count and
        # the reason belong in one sentence (:meth:`note_skip`). Optional, so a test can
        # build a scheduler without an i18n at all and read the raw key back.
        self._translate = translate
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
        # Errands NOT in the catalogue that were handed to the queue directly —
        # a trigger's scenario (panel/triggers.py). They share the one worker and the
        # dedup set, but the worker cannot look them up in `catalogue()`, so it keeps
        # them here by name for the length of the run. Anything with `.name` and
        # `.scenario` (a Trigger) works — the runner only reads those.
        self._adhoc: dict = {}
        # Names the UI asked to take back off the queue. Marked rather than removed
        # (a Queue cannot be searched), and dropped by the worker when it gets there.
        self._cancelled: set[str] = set()
        # The errand being run right now, if any. `_queued` cannot tell waiting from
        # running (a claim covers both), and `cancel` has to: one is cancellable and
        # the other is not.
        self._running: str | None = None
        # Names whose moment came again WHILE they were running. A push that lands
        # mid-run used to be dropped by the claim below, which is how a second banner
        # raised while the first was being joined was lost without a word (#1281): the
        # run in flight had already read the map and could not know about it. Marked
        # here and re-queued the moment the run lets go, so the burst costs one extra
        # run rather than a rally. A name merely WAITING in the queue is still
        # coalesced — that run has not looked at anything yet and will see the new
        # rally by itself.
        self._refire: set[str] = set()
        # Names parked because the panel was busy, so the retries stay quiet: the
        # queue re-offers them every `BUSY_RETRY_SEC` and only the first offer is
        # worth a «стартую» line. Emptied the moment one of them actually runs.
        self._busy_held: set[str] = set()
        # Repeated skips, rolled up: name -> [reason, count, last-said-monotonic].
        self._skips: dict = {}
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
        self._dbg.info("scheduler started")

    def stop(self) -> None:
        self._stop.set()
        self._dbg.info("scheduler stopped")

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

    def submit(self, errand) -> bool:
        """Queue an errand that is NOT in the catalogue — a trigger's scenario.

        The trigger watcher (panel/triggers.py) calls this when a push lands, so the
        scenario runs on THIS one worker, single-file with the scheduled timers and
        never in parallel with them. ``errand`` needs only ``.name`` and
        ``.scenario`` (a :class:`~panel.triggers.Trigger`); it is remembered by name
        for the run because the worker looks errands up in the catalogue and this one
        is not there.

        Returns WHAT HAPPENED to the fire, because «dropped» and «will run» used to be
        the same `False` and the caller logged «запускаю сценарий» over both (#1281):

        * ``"queued"``  — it is on the queue and will run;
        * ``"waiting"`` — one of the same name is already queued and has not looked at
          anything yet, so it will see whatever this fire was about; the burst
          coalesces to one press, which is what that coalescing is for;
        * ``"refired"`` — one of the same name is RUNNING. It has already read the
          game and cannot know about this, so the name is marked and re-queued the
          moment it lets go (:meth:`_release`). This is the case that used to lose a
          rally: a second banner going up while the first was being joined.

        Every one of the three is truthy, so a caller that only asked «did it take it»
        still gets a yes — none of these three means the fire was thrown away.
        """
        with self._queue_lock:
            if errand.name in self._queued:
                self._adhoc.setdefault(errand.name, errand)
                if errand.name == self._running:
                    self._refire.add(errand.name)
                    return "refired"
                return "waiting"
            self._queued.add(errand.name)
            self._adhoc[errand.name] = errand
        self._queue.put((errand.name, False))
        return "queued"

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
            # Its moment came again while it was running (:meth:`submit`): put it
            # straight back rather than letting go of it. The claim is KEPT — it never
            # leaves the queued set — so nothing else can line the same name up twice
            # in between, and the errand it re-runs is the same one it just finished.
            if name in self._refire:
                self._refire.discard(name)
                self._queue.put((name, False))
                return
            self._queued.discard(name)
            self._adhoc.pop(name, None)   # a submitted trigger errand is done with
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
                self._dbg.error("tick error", exc_info=True)
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
            # PER ERRAND, not per tick. The gate that matters is «the game is not
            # running», and the errand that PUTS IT BACK is on this very list: a
            # blanket refusal dropped `restart_game` for the one reason it exists,
            # and a client that died at eight in the evening was still dead at ten
            # with the schedule reporting «пропускаю: игра не запущена» all night
            # (#1259). So each name is asked about separately, and the recovery ones
            # are let through.
            allowed, refused = [], None
            for name in pending:
                reason = self._gate(name)
                if reason:
                    refused = reason
                else:
                    allowed.append(name)
            if refused and refused != self._gate_said:
                self._log(refused)
                self._gate_said = refused
            if not allowed:
                return []
            pending = allowed
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
        if timer is None:                    # a submitted trigger errand, or…
            with self._queue_lock:
                timer = self._adhoc.get(name)
        if timer is None:                    # …deleted from the config mid-run
            self._release(name)
            return "skipped"
        if self._gate is not None:
            reason = self._gate(name)
            if reason:
                # The game went away between queueing and running: drop it rather
                # than fail it — the next tick queues it again, unchanged. SAID WITH
                # THE ERRAND'S NAME AND A COUNT (#1281): «жду запуска игры» once an
                # hour told nobody that two hundred rally pushes had been refused for
                # it, and a skip with nothing attached to it reads as nothing at all.
                self.note_skip(name, reason)
                self._gate_said = reason
                self._release(name)
                return "skipped"
        # Mark it as running for the whole call, so `cancel` can tell "waiting in
        # the queue" (cancellable) from "in flight" (not) — and so a fire landing
        # mid-run is re-armed rather than coalesced away (`submit`). Cleared inside
        # `_release`, under the same lock, or a fire arriving in the gap between the
        # two would see neither a running errand nor a free queue and be dropped.
        with self._queue_lock:
            self._running = name
        try:
            ok, busy = self.run_one(timer, scheduled=scheduled)
        finally:
            if busy:
                with self._queue_lock:
                    self._running = None
        if busy:
            self._hold_until = time.time() + self._busy_retry
            self._requeue(name, scheduled)   # stays claimed: it is still waiting
            return "busy"
        self._release(name)
        return "ran" if ok else "skipped"

    def note_skip(self, name: str, reason: str, **fmt) -> bool:
        """Say that ``name`` did not run, and why — rolled up when it keeps happening.

        The first time a reason appears it is said at once. While the SAME reason keeps
        coming back for the same errand it is said again at most every
        :data:`SKIP_NOTE_SEC`, carrying how many skips have piled up since the last
        line. A different reason starts over, because that is news.

        Returns whether a line was written, which is what the tests read.
        """
        now = time.monotonic()
        with self._queue_lock:
            note = self._skips.get(name)
            if note is not None and note[0] == reason:
                note[1] += 1
                if now - note[2] < SKIP_NOTE_SEC:
                    return False
                count, note[1], note[2] = note[1], 0, now
            else:
                self._skips[name] = [reason, 0, now]
                count = 1
        if count > 1:
            self._log("timers.log.skipped_times", name=name, count=count,
                      reason=self._reason_text(reason, **fmt))
        else:
            self._log("timers.log.skipped_once", name=name,
                      reason=self._reason_text(reason, **fmt))
        self._dbg.info("skipped %s x%d — %s", name, count, reason)
        return True

    def _reason_text(self, reason: str, **fmt) -> str:
        """A skip's reason as WORDS, whether it arrived as a locale key or a sentence.

        The gate answers in locale keys (`timers.log.skip_game`) and a caller may hand in
        a finished sentence; both have to end up inside one line rather than being logged
        as a line of their own, which is what let «жду запуска игры» float free of the
        errand it was about.
        """
        translate = getattr(self, "_translate", None)
        if translate is not None:
            try:
                return str(translate(reason, **fmt))
            except Exception:                # noqa: BLE001 — a word, never the skip
                pass
        return reason

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
            # A NAME WAITING OUT A BUSY PANEL SAYS «стартую» ONCE, NOT EVERY RETRY.
            # The queue re-offers it every `BUSY_RETRY_SEC`, and each offer used to
            # write two lines — one claiming it was starting and one saying it was
            # not. Two errands parked behind a stuck run buried an evening's log in
            # 1698 lines of it, which is the log being useless exactly when somebody
            # is reading it to find out what went wrong (#1281).
            if timer.name not in self._busy_held:
                self._log("timers.log.fire", name=timer.name,
                          mins=self._minutes_since(timer.name))
            self._dbg.info("fire %s (scheduled)", timer.name)
        else:
            self._log("timers.log.manual", name=timer.name)
            self._dbg.info("fire %s (manual)", timer.name)
        try:
            started = self._runner(timer)
        except Exception as exc:                          # noqa: BLE001
            self._store.mark_failed(timer.name)
            self._log("timers.log.failed", name=timer.name, error=exc)
            self._dbg.error("run of %s failed", timer.name, exc_info=True)
            return False, False
        if not started:
            # Rolled up like any other reason an errand did not run: said at once,
            # then at most once a minute with how many attempts piled up behind it.
            self.note_skip(timer.name, "timers.reason.busy")
            self._busy_held.add(timer.name)
            self._dbg.warning("skipped %s — panel busy", timer.name)
            return False, True
        self._busy_held.discard(timer.name)
        self._store.mark_run(timer.name)
        self._log("timers.log.done", name=timer.name)
        self._dbg.info("done %s", timer.name)
        return True, False

    def _minutes_since(self, name: str) -> int:
        last = self._store.last_run(name)
        if not last:
            return 0
        return int((time.time() - last) // 60)
