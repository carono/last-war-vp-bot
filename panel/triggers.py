r"""Wire-driven errands — the triggers module (config, catalogue, watcher).

A *timer* runs its scenario when a period has passed (panel/timers.py). A *trigger*
runs one when a particular message crosses the wire: an alliancemate's help request
pays points only while it is open and the game announces it (``push.al.help.new``),
so the useful thing is not a periodic sweep but a standing ear on the stream — the
push arrives and the errand fires in the same second, with nobody watching.

The two are separate on purpose — a trigger has no period, no retry and no "next
run", only an event and a scenario — so triggers keep their **own catalogue** and
their **own file**, exactly the way timers do:

    built-in DEFAULT_TRIGGERS  →  template panel/triggers.json  →  the profile's own
    profiles/<name>/triggers.json  (what actually runs; the checkboxes write here).

A trigger is::

    {
      "name": "alliance_help",          // id: config key, log name
      "event_pattern": "al.help.new",   // substring of the wire command that fires it
      "scenario": "help_ally",          // one action, or a list, like a timer's
      "enabled": false,
      "args": {}
    }

Where triggers and timers DO meet is the **single work queue**: when a trigger's push
lands the watcher hands the scenario to :meth:`panel.timers.TimerScheduler.submit`,
so a triggered errand runs on the very worker the schedule feeds and never drives the
game in parallel with a scheduled one.

Two classes, both Tk-free and game-free so a test can drive them without a display:

  * :class:`TriggerCatalogue` — the configured list plus whatever was wrong with the
    file (a typo costs that entry, not the whole set);
  * :class:`TriggerWatcher` — keeps one live listener per switched-on trigger and, on
    a fired push, submits the scenario. The panel passes the listener spawn and the
    submit in, so this module spawns nothing itself.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field

from . import debug_log
from .profile import _write_json

# Component debug logger (panel/debug_log.py) — the panel wires the rotating file
# under it; here we only record when a listener comes up, fires or dies.
_dbg = debug_log.get_logger("triggers")

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
# The TEMPLATE, beside the panel (gitignored, seeded from DEFAULT_TRIGGERS on first
# run): what a profile with no triggers of its own is seeded from. The catalogue a
# profile actually runs lives in its own directory.
TEMPLATE_FILE = os.path.join(PANEL_DIR, "triggers.json")

# The marker line a listener prints on every match, keyed on by the panel's reader
# and swallowed there. It MUST match ``FIRE`` in ``tools/wire_event_monitor.py`` —
# the two processes agree on this string and nothing else.
FIRE_MARKER = "##TRIGGER##"


# The two ways a trigger can watch for its moment. A *wire* trigger listens for a
# command on the traffic (a listener child); a *poll* trigger asks the game's own Lua
# VM a yes/no question every so often (a background thread through the daemon). Both
# end the same way: the scenario goes on the shared queue.
KIND_WIRE = "wire"
KIND_POLL = "poll"

# Defaults for a poll trigger's cadence. `interval` is how often the check runs;
# `cooldown` is how long the poll sits quiet AFTER it has fired, so a detection that
# takes a while to clear (a kick modal that stays up until the relaunch lands) does
# not re-fire the recovery every interval while it is still on screen.
DEFAULT_POLL_INTERVAL_SEC = 15
DEFAULT_POLL_COOLDOWN_SEC = 90
MIN_POLL_INTERVAL_SEC = 5


@dataclass(frozen=True)
class Trigger:
    """One wire- or poll-driven errand, as configured.

    ``scenario`` is a *sequence* because an errand is not always one press — the
    runner walks the steps in order, exactly like a timer's. A step is the name of
    an action script or DSL source run as it stands.

    ``kind`` picks how it watches. A ``wire`` trigger carries an ``event_pattern`` (a
    substring of a down command) and is answered by a listener child. A ``poll``
    trigger carries a ``check`` — a Lua expression the daemon evaluates every
    ``interval_sec`` — and fires when it comes back truthy; ``cooldown_sec`` is how
    long it then sits quiet before checking again. The session-kick trigger is a poll:
    the game stays alive behind a modal, so there is no packet to hear — the only
    headless tell is a state read.
    """

    name: str                       # id — config key, log name
    scenario: tuple[str, ...]       # action names and/or inline DSL source
    kind: str = KIND_WIRE
    event_pattern: str = ""         # wire: substring of the down command that fires it
    check: str = ""                 # poll: Lua expression -> truthy when it should fire
    interval_sec: int = DEFAULT_POLL_INTERVAL_SEC   # poll: how often the check runs
    cooldown_sec: int = DEFAULT_POLL_COOLDOWN_SEC   # poll: quiet time after a fire
    enabled: bool = False
    args: dict = field(default_factory=dict)
    title: str | None = None        # row label straight from the config
    label_key: str | None = None    # …or a locale key, for the built-in entries

    @property
    def is_poll(self) -> bool:
        return self.kind == KIND_POLL

    def signal(self) -> str:
        """What the row shows in the «on event» column — the wire event or the poll."""
        return self.check if self.is_poll else self.event_pattern

    def as_dict(self) -> dict:
        """The entry as it is written in the catalogue file."""
        out = {
            "name": self.name,
            "scenario": list(self.scenario) if len(self.scenario) != 1
            else self.scenario[0],
            "enabled": self.enabled,
        }
        if self.is_poll:
            out["kind"] = KIND_POLL
            out["check"] = self.check
            out["interval_sec"] = self.interval_sec
            out["cooldown_sec"] = self.cooldown_sec
        else:
            out["event_pattern"] = self.event_pattern
        if self.args:
            out["args"] = dict(self.args)
        if self.title:
            out["title"] = self.title
        return out


# The fallback catalogue: what ships in the box, what a missing file is seeded from,
# and what each field falls back to when an entry leaves it out. The one recipe behind
# it is headless (the help press opens no window and touches no mouse), so a trigger
# firing never takes the machine away from whoever is using it.
# The Lua the session-kick poll asks the game every interval. The client stays alive
# behind a "logged in from another device" modal, so there is no packet to hear — the
# tell is a state read. Each signal is its own pcall so a missing manager cannot take
# the check down: ChatManager2's connection-error flag, its status code (>=5 is the
# disconnected range), or the modal's own error code 110006 on an open message tip.
# Any one true → the recovery fires. Kept on one line: it is an expression the poll
# wraps in `pcall(function() return <check> end)` and reads the boolean back from.
_KICK_CHECK = (
    "(function() "
    "local CM = ChatManager2 "
    "if CM then local inst = CM.GetInstance and CM.GetInstance(CM) or CM "
    "local ok, e = pcall(function() return inst:IsConnectionError() end) "
    "if ok and e then return true end "
    "local st = inst.status if type(st) == 'number' and st >= 5 then return true end end "
    "local ok2, tip = pcall(function() "
    "return UIManager and UIManager.Instance "
    "and UIManager.Instance:IsWindowOpen(UIWindowNames.UICommonMessageTip) end) "
    "if ok2 and tip then return true end "
    "return false end)()"
)

DEFAULT_TRIGGERS: tuple[Trigger, ...] = (
    Trigger(
        name="alliance_help",
        # An alliancemate's help request pays points only while it is open and the
        # game announces it on the wire; the watcher presses "Help All" the instant
        # this push lands. Opt-in (off by default): it answers on its own.
        kind=KIND_WIRE,
        event_pattern="al.help.new",
        scenario=("help_ally",),
        enabled=False,
        label_key="triggers.item.alliance_help",
    ),
    Trigger(
        name="session_kick",
        # A login on another device kicks this session: the client stays alive behind
        # a modal that locks it, so nothing on screen changes on its own and no packet
        # says so. The poll reads the disconnect state through the daemon every few
        # seconds and, when it sees it, runs the recovery — acknowledge the modal and
        # relaunch the client. Replaces the pixel-based actions/dev/watchdog.md.
        kind=KIND_POLL,
        check=_KICK_CHECK,
        interval_sec=DEFAULT_POLL_INTERVAL_SEC,
        cooldown_sec=DEFAULT_POLL_COOLDOWN_SEC,
        scenario=("recover_from_kick",),
        enabled=False,
        label_key="triggers.item.session_kick",
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
    """A poll cadence in seconds, floored so a hand-edited file cannot ask for a
    check every fraction of a second."""
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return fallback
    return max(MIN_POLL_INTERVAL_SEC, value)


class TriggerCatalogue:
    """The configured list of triggers, plus whatever was wrong with the file.

    ``errors`` is not an exception on purpose: a typo in one entry must cost that
    entry, not the whole set, and the panel prints the complaints into its log.
    """

    def __init__(self, triggers, path: str | None = None, errors=()) -> None:
        self.triggers: tuple[Trigger, ...] = tuple(triggers)
        self.path = path
        self.errors: tuple[str, ...] = tuple(errors)
        self._by_name = {t.name: t for t in self.triggers}

    def __iter__(self):
        return iter(self.triggers)

    def __len__(self) -> int:
        return len(self.triggers)

    def by_name(self, name: str) -> Trigger | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return [t.name for t in self.triggers]

    def enabled_config(self) -> dict:
        """Each trigger's switch as the catalogue asks for it — ``{name: enabled}``."""
        return {t.name: bool(t.enabled) for t in self.triggers}

    def normalize_config(self, raw) -> dict:
        """Coerce stored/typed switches into ``{name: enabled}`` against this list.

        A profile saved before a trigger existed has no entry for it, one saved after
        a trigger was removed has an entry for nothing — so every value is re-derived
        here rather than trusted.
        """
        raw = raw if isinstance(raw, dict) else {}
        out = self.enabled_config()
        for t in self.triggers:
            item = raw.get(t.name)
            if isinstance(item, dict):
                out[t.name] = bool(item.get("enabled", t.enabled))
            elif isinstance(item, bool):
                out[t.name] = item
        return out

    def with_enabled(self, config: dict) -> "TriggerCatalogue":
        """A copy carrying the panel's switches, ready to be saved.

        Only ``enabled`` moves. The event pattern, the scenario and the args are the
        operator's text; a ticked box must not be able to touch anything else.
        """
        config = self.normalize_config(config)
        updated = [Trigger(
            name=t.name, scenario=t.scenario, kind=t.kind,
            event_pattern=t.event_pattern, check=t.check,
            interval_sec=t.interval_sec, cooldown_sec=t.cooldown_sec,
            enabled=bool(config[t.name]), args=dict(t.args),
            title=t.title, label_key=t.label_key) for t in self.triggers]
        return TriggerCatalogue(updated, self.path, self.errors)


def default_catalogue() -> TriggerCatalogue:
    """The hardcoded fallback, as a catalogue."""
    return TriggerCatalogue(DEFAULT_TRIGGERS)


def parse_catalogue(data, path: str | None = None,
                    fallback: "TriggerCatalogue | None" = None) -> TriggerCatalogue:
    """Build a catalogue from already-decoded JSON.

    Accepts either a bare list of entries or ``{"triggers": [...]}``. The FILE owns
    the list — a trigger deleted from it is gone — while each entry falls back field
    by field to the one of the same name in ``fallback`` (the template, and behind it
    the built-ins).
    """
    fallback_triggers = fallback.triggers if fallback is not None else DEFAULT_TRIGGERS
    if isinstance(data, dict):
        data = data.get("triggers")
    if not isinstance(data, list):
        return TriggerCatalogue(fallback_triggers, path,
                                ["config is not a list of triggers — using the defaults"])

    builtin = {t.name: t for t in DEFAULT_TRIGGERS}
    builtin.update({t.name: t for t in fallback_triggers})
    triggers, errors, seen = [], [], set()
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
        kind = str(raw.get("kind") or (base.kind if base else KIND_WIRE)).strip()
        if kind not in (KIND_WIRE, KIND_POLL):
            errors.append(f"{name}: unknown kind '{kind}' — skipped")
            continue
        scenario = _as_scenario(raw.get("scenario"))
        if not scenario:
            scenario = base.scenario if base else ()
        if not scenario:
            errors.append(f"{name}: no scenario to run — skipped")
            continue
        # A wire trigger needs a pattern to listen for; a poll trigger needs a check
        # to evaluate. Missing the one its kind requires costs the entry, not the set.
        pattern = str(raw.get("event_pattern") or "").strip() or \
            (base.event_pattern if base else "")
        check = str(raw.get("check") or "").strip() or (base.check if base else "")
        if kind == KIND_WIRE and not pattern:
            errors.append(f"{name}: no event_pattern to watch for — skipped")
            continue
        if kind == KIND_POLL and not check:
            errors.append(f"{name}: no check to poll — skipped")
            continue
        args = raw.get("args")
        triggers.append(Trigger(
            name=name,
            scenario=scenario,
            kind=kind,
            event_pattern=pattern,
            check=check,
            interval_sec=_as_interval(
                raw.get("interval_sec"),
                base.interval_sec if base else DEFAULT_POLL_INTERVAL_SEC),
            cooldown_sec=_as_interval(
                raw.get("cooldown_sec"),
                base.cooldown_sec if base else DEFAULT_POLL_COOLDOWN_SEC),
            enabled=bool(raw.get("enabled", base.enabled if base else False)),
            args=dict(args) if isinstance(args, dict) else {},
            title=(str(raw["title"]).strip() or None) if raw.get("title") else None,
            label_key=base.label_key if base else None,
        ))
        seen.add(name)

    if not triggers:
        if not errors:
            return TriggerCatalogue((), path)     # "this account watches nothing"
        errors.append("no usable triggers in the config — using the defaults")
        return TriggerCatalogue(fallback_triggers, path, errors)
    return TriggerCatalogue(triggers, path, errors)


def load_catalogue(path: str, seed_from=None) -> TriggerCatalogue:
    """Read a catalogue file, falling back to ``seed_from`` / the built-in list.

    A file that does not exist yet is *written* from the seed, so there is always
    something on disk to edit. A file that exists but cannot be read is NOT
    overwritten: the panel runs on the fallback and says so.
    """
    seed = seed_from if seed_from is not None else TriggerCatalogue(DEFAULT_TRIGGERS)
    if not os.path.exists(path):
        fresh = TriggerCatalogue(seed.triggers, path)
        save_catalogue(fresh, path)
        return fresh
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return TriggerCatalogue(seed.triggers, path,
                                [f"{os.path.basename(path)}: {exc}"])
    return parse_catalogue(data, path, fallback=seed)


def load_template() -> TriggerCatalogue:
    """The template new profiles are seeded from (``panel/triggers.json``)."""
    return load_catalogue(TEMPLATE_FILE)


def load_profile_catalogue(path: str) -> TriggerCatalogue:
    """The catalogue a profile runs, seeded from the template when it has none."""
    return load_catalogue(path, seed_from=load_template())


def save_catalogue(catalogue: TriggerCatalogue, path: str | None = None) -> None:
    """Write a catalogue back out in the file's own format."""
    _write_json(path or catalogue.path or TEMPLATE_FILE,
                [t.as_dict() for t in catalogue.triggers])


class TriggerWatcher:
    """Keeps one listener alive per enabled trigger; submits the scenario on a push.

    :meth:`sync` is the whole engine: it reconciles the running listeners with the
    triggers the operator has switched on. Call it after start, after a box is
    ticked, and after the catalogue is re-read or the profile switched — it starts
    the listeners newly wanted and stops the ones no longer wanted, and is a no-op
    when the two already agree.

    Collaborators are all callables, so nothing about Tk or the game leaks in:

      * ``catalogue()``      -> the current :class:`TriggerCatalogue`;
      * ``config()``         -> the switches read fresh (``{name: enabled}``), so a
                              ticked box applies without a restart;
      * ``spawn(trigger, fire)`` -> start a WIRE listener that calls ``fire()`` on
                              every matching push; returns a handle with ``.stop()``
                              (or ``None`` if it would not start);
      * ``poll(trigger)``    -> evaluate a POLL trigger's check once, returning truthy
                              when it should fire (the panel reads it through the
                              daemon). Runs on the watcher's own poll thread, so it may
                              block; it must not touch Tk.
      * ``submit(trigger)``  -> put the scenario on the shared work queue (the panel
                              hands this to ``TimerScheduler.submit``);
      * ``log(key, **fmt)``  -> a locale key plus its placeholders.

    Two kinds of listener, one bookkeeping. A *wire* trigger's listener is the child
    ``spawn`` returns; a *poll* trigger's is an internal thread that calls ``poll``
    every ``interval_sec`` and fires when it comes back true, then sits out
    ``cooldown_sec``. Both are stored the same way and stopped the same way.
    """

    def __init__(self, *, catalogue, config, spawn, submit, log, poll=None) -> None:
        self._catalogue = catalogue
        self._config = config
        self._spawn = spawn
        self._submit = submit
        self._log = log
        self._poll = poll
        self._lock = threading.Lock()
        self._listeners: dict[str, object] = {}   # trigger name -> handle (.stop())
        self._started = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Begin watching: bring up a listener for every enabled trigger."""
        self._started = True
        _dbg.info("watcher started")
        self.sync()

    def stop(self) -> None:
        """Stop every listener; no trigger fires until :meth:`start` again."""
        self._started = False
        for name in list(self._listeners):
            self._stop_one(name)
        _dbg.info("watcher stopped")

    @property
    def running(self) -> bool:
        return self._started

    # -- reconciliation -----------------------------------------------------
    def sync(self) -> None:
        """Match the running listeners to the triggers switched on right now.

        The one call the panel makes for every reason a listener might need to come
        up or go down: started, a box toggled, the file re-read, the profile
        switched. Idempotent.
        """
        if not self._started:
            return
        catalogue = self._catalogue()
        config = catalogue.normalize_config(self._config())
        wanted = {t.name: t for t in catalogue if config.get(t.name)}
        for name in list(self._listeners):
            if name not in wanted:
                self._stop_one(name)
        for name, trigger in wanted.items():
            if name not in self._listeners:
                self._start_one(trigger)

    def _start_one(self, trigger) -> None:
        if trigger.is_poll:
            handle = _PollHandle(trigger, self._poll,
                                 lambda t=trigger: self._fire(t), self._log)
            with self._lock:
                self._listeners[trigger.name] = handle
            self._log("triggers.log.on", name=trigger.name, event=trigger.signal())
            _dbg.info("listening on %s (poll) for %s", trigger.name, trigger.signal())
            handle.start()
            # No arm-sweep: the poll's own first iteration reads the current state, so
            # a kick already on screen is caught at once — submitting here would run
            # the recovery every time the box is ticked.
            return
        handle = self._spawn(trigger, lambda t=trigger: self._fire(t))
        if handle is None:               # the child would not start; spawn logged it
            return
        with self._lock:
            self._listeners[trigger.name] = handle
        self._log("triggers.log.on", name=trigger.name, event=trigger.signal())
        _dbg.info("listening on %s for %s", trigger.name, trigger.signal())
        # An initial sweep: a request already waiting when the ear opens had its push
        # sent before we started listening, so no trigger is coming for it. Run the
        # errand once to clear whatever is already there. Safe because the scenario is
        # gated — it no-ops when there is nothing to do — and the scheduler drops the
        # run if the game is closed rather than failing it.
        self._submit(trigger)

    def _stop_one(self, name: str) -> None:
        with self._lock:
            handle = self._listeners.pop(name, None)
        if handle is None:
            return
        try:
            handle.stop()
        except Exception:                # noqa: BLE001 — already gone is fine
            pass
        self._log("triggers.log.off", name=name)
        _dbg.info("stopped listening on %s", name)

    def _fire(self, trigger) -> None:
        """The trigger's moment came — put the scenario on the shared queue.

        Runs on the listener's thread (a wire child's reader, or a poll thread).
        ``submit`` is thread-safe (it hands to the scheduler's queue) and coalesces a
        burst: a second fire while the errand is still queued or running is dropped, so
        a flurry of pushes — or a modal seen twice — costs one press.
        """
        self._log("triggers.log.fire", name=trigger.name, event=trigger.signal())
        _dbg.info("fire %s on %s", trigger.name, trigger.signal())
        self._submit(trigger)

    def on_listener_exit(self, name: str) -> None:
        """A listener died on its own — forget the handle so :meth:`sync` respawns."""
        _dbg.warning("listener %s exited on its own", name)
        with self._lock:
            self._listeners.pop(name, None)

    def watching(self) -> set[str]:
        """Names of the triggers with a live listener — for the row painter."""
        with self._lock:
            return set(self._listeners)


class _PollHandle:
    """A poll trigger's "listener": a thread that checks, and fires when it's true.

    The wire triggers hand their watching to a child process; a poll trigger has no
    packet to hear, so the watcher runs it here — every ``interval_sec`` it asks
    ``poll(trigger)``, and on a truthy answer it fires and then sits out
    ``cooldown_sec`` before checking again (so a kick modal that lingers until the
    relaunch lands does not re-fire the recovery each interval). Same ``.stop()`` the
    watcher calls on a wire child, so the two are managed identically.
    """

    def __init__(self, trigger, poll, on_fire, log) -> None:
        self._trigger = trigger
        self._poll = poll
        self._on_fire = on_fire
        self._log = log
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f"trigger-poll-{trigger.name}")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        t = self._trigger
        while not self._stop.is_set():
            fired = False
            try:
                if self._poll is not None and self._poll(t):
                    self._on_fire()
                    fired = True
            except Exception as exc:              # noqa: BLE001 — a bad read must not
                # kill the watch; log once and carry on to the next interval.
                self._log("triggers.log.poll_error", name=t.name, error=exc)
            # Wait on the stop event so a stop is noticed at once, not at the end of a
            # full interval: `wait` returns True the moment it is set.
            self._stop.wait(t.cooldown_sec if fired else t.interval_sec)
