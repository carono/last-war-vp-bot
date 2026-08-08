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

Each file is read at every start and *grown*: a built-in name it has never heard of
is appended, switched off, and the file rewritten (:func:`merge_new`), so a profile
made before a trigger shipped picks it up instead of having to be recreated. What is
already in the file — the switch, the event, the scenario, the args — is never
touched.

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
game in parallel with a scheduled one — **unless it is marked `"immediate": true`**,
which runs it on a thread of its own and makes an ordinary errand step aside for it at
its next step (#1288, `docs/research/panel-priorities.md`). Even then only one of them
holds the client at a time: the claim is handed over, never shared.

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
import sys
import threading
import time
from dataclasses import dataclass, field

# tools/lib is already on sys.path when the panel imports us; a bare import keeps this
# module usable from a test that only put the repo root there. A poll trigger's `check`
# is a Lua expression, and a Lua expression belongs where every other one lives — the
# catalogue names the chunk, it does not spell it out (`panel/dashboard.py` does the
# same). `_KICK_CHECK` below predates that and is debt, not precedent.
_TOOLS_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tools", "lib")
if _TOOLS_LIB not in sys.path:
    sys.path.insert(0, _TOOLS_LIB)
import lua_actions      # noqa: E402

from . import debug_log, paths
from .i18n import Message
from .profile import _write_json

# Component debug logger (panel/debug_log.py) — the panel wires the rotating file
# under it; here we only record when a listener comes up, fires or dies.
_dbg = debug_log.get_logger("triggers")

PANEL_DIR = paths.PANEL_DIR
# The TEMPLATE, beside the profiles (gitignored, seeded from DEFAULT_TRIGGERS on first
# run): what a profile with no triggers of its own is seeded from. The catalogue a
# profile actually runs lives in its own directory.
TEMPLATE_FILE = paths.TRIGGERS_TEMPLATE

# The marker line a listener prints on every match, keyed on by the panel's reader
# and swallowed there. It MUST match ``FIRE`` in ``tools/wire_event_monitor.py`` —
# the two processes agree on this string and nothing else.
FIRE_MARKER = "##TRIGGER##"

# The marker a POLL trigger's check answers under, and the two halves of reading it.
# They live together, in this Tk-free module, because they were apart: the chunk was
# built in `panel/runtime/schedule.py` and its answer matched there too, with the needle
# spelled in capitals against a haystack that had been lowered — so `poll` returned False
# for every reading the game could give and NO poll trigger had ever fired (#1296). A
# contract that is one string in two places is a contract nothing can test.
POLL_MARKER = "TRIGCHK"


def poll_chunk(check: str) -> str:
    """The Lua a poll trigger's ``check`` is asked with — one line, one answer.

    The expression is wrapped in a `pcall` so a check that throws reads as «no» rather
    than taking the watch down, and the answer is logged under :data:`POLL_MARKER`.
    """
    return ('local ok, v = pcall(function() return %s end) '
            'CS.UnityEngine.Debug.LogError("%s=" .. tostring(ok and v and true or false))'
            % (check, POLL_MARKER))


def poll_said_yes(lines) -> bool:
    """Did the check come back true? The other half of :func:`poll_chunk`.

    Case-insensitive on BOTH sides on purpose: the daemon hands the log line back as the
    client wrote it, and a comparison that lowers only one of them is false for every
    input there is — which is exactly the bug this pair was extracted to make testable.
    """
    needle = POLL_MARKER.lower() + "=true"
    return any(needle in str(line).lower() for line in (lines or ()))


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

# How often ONE trigger may say the same thing about its fires. A push that arrives all
# day arrives thousands of times — one live log carried 6 675 «пришло
# push.alliance.march — запускаю сценарий» lines for a single trigger (#1293) — and a
# line each buries everything else in the log. Same answer as a repeated skip
# (`timers.SKIP_NOTE_SEC`, #1281) and the same shape: the first is said at once, and
# while nothing about it changes the rest are rolled up into one line carrying the
# count. A DIFFERENT outcome (queued → already running) is news and is said at once.
FIRE_NOTE_SEC = 60.0


@dataclass(frozen=True)
class BackoffPolicy:
    """An adaptive delay before a trigger's scenario runs, that grows while the fault
    it recovers from keeps returning and resets once it stays away.

    Generic on purpose — any trigger whose recovery should ease off under a repeating
    fault can carry one; it lives in the trigger's config, not in a scenario. The
    first user is ``session_kick``: a login on another device that keeps kicking the
    session must not be answered by an instant relaunch each time (that is a relaunch
    war — kick, relaunch, kick), but by waiting longer and longer before trying
    again, and forgetting that escalation once the session finally holds.

    All fields are seconds:

      * ``initial_sec``       — the first delay, and the value a reset falls back to;
      * ``step_sec``          — how much each consecutive quick fire adds;
      * ``max_sec``           — the ceiling the delay never grows past;
      * ``stability_sec``     — a fire this long or longer after the last run is a
                                fresh incident: reset the delay to ``initial_sec``;
      * ``refire_window_sec`` — a fire sooner than this after the last run is the
                                same fault returning: add ``step_sec`` (capped).

    Elapsed is measured from when the scenario last ran (the restart), not from the
    fire that queued it, because "did the session hold?" is a question about the time
    after the relaunch. Between the two windows
    (``refire_window_sec <= elapsed < stability_sec``) the delay is held where it is —
    neither escalated nor reset; with the two equal (the ``session_kick`` default,
    both 10 min) there is no such gap.

    A missing or malformed field falls back to the default here rather than costing
    the whole policy, so a hand-edited catalogue that sets only ``max_sec`` still
    parses.
    """

    initial_sec: int = 900
    step_sec: int = 900
    max_sec: int = 2700
    stability_sec: int = 600
    refire_window_sec: int = 600

    def as_dict(self) -> dict:
        """The policy as it is written under a trigger's ``backoff`` key."""
        return {
            "initial_sec": self.initial_sec,
            "step_sec": self.step_sec,
            "max_sec": self.max_sec,
            "stability_sec": self.stability_sec,
            "refire_window_sec": self.refire_window_sec,
        }

    @classmethod
    def from_raw(cls, raw, base: "BackoffPolicy | None" = None) -> "BackoffPolicy | None":
        """Build a policy from a decoded ``backoff`` object, field by field.

        Returns ``None`` when ``raw`` is not an object (the trigger simply has no
        backoff). Each field falls back to ``base`` — the same-named trigger's policy,
        and behind it these defaults — so an entry may set only what it wants to change.
        """
        if not isinstance(raw, dict):
            return None
        ref = base or cls()

        def _num(key: str, fallback: int) -> int:
            try:
                return max(0, int(float(str(raw[key]).strip())))
            except (KeyError, TypeError, ValueError):
                return fallback

        return cls(
            initial_sec=_num("initial_sec", ref.initial_sec),
            step_sec=_num("step_sec", ref.step_sec),
            max_sec=_num("max_sec", ref.max_sec),
            stability_sec=_num("stability_sec", ref.stability_sec),
            refire_window_sec=_num("refire_window_sec", ref.refire_window_sec),
        )


class BackoffState:
    """The running state of one trigger's :class:`BackoffPolicy` — how long to wait
    before the next run, and when the last run was.

    Mutable and not thread-safe: it is only ever touched from one poll thread. Kept
    apart from the (frozen) policy so the same policy can drive many triggers while
    each keeps its own escalation. The watcher holds one per trigger by name, so it
    survives a listener respawn (a :meth:`TriggerWatcher.sync` after a re-read).
    """

    def __init__(self, policy: BackoffPolicy) -> None:
        self._policy = policy
        self._current = policy.initial_sec
        self._last_run_ts: float | None = None

    @property
    def policy(self) -> BackoffPolicy:
        return self._policy

    @property
    def current_delay(self) -> int:
        return self._current

    @property
    def last_run_ts(self) -> float | None:
        return self._last_run_ts

    def plan(self, now: float) -> int:
        """A fire landed at ``now`` — pick and remember the delay before the run.

        The delay is the current one; whether it escalates, resets or holds is decided
        by how long the session held since the last run (see :class:`BackoffPolicy`).
        Returns the number of seconds to wait before the scenario runs.
        """
        p = self._policy
        if self._last_run_ts is not None:
            elapsed = now - self._last_run_ts
            if elapsed < p.refire_window_sec:
                self._current = min(self._current + p.step_sec, p.max_sec)
            elif elapsed >= p.stability_sec:
                self._current = p.initial_sec
            # else: between the windows — hold the delay where it is.
        return self._current

    def mark_run(self, now: float) -> None:
        """The scenario has just run (the restart): remember when, so the next fire
        can tell a quick refire from a session that settled."""
        self._last_run_ts = now


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
    backoff: BackoffPolicy | None = None            # adaptive pre-run delay (opt-in)
    enabled: bool = False
    # «СРАЗУ, БЕЗ ОЧЕРЕДИ» — the same flag a timer carries, and it means the same thing
    # here (`panel/timers.py::Timer.immediate`, #1288): the fire does not queue behind
    # the ordinary work, it runs on a thread of its own, and it asks for the client at
    # a level that makes an ordinary errand park at its next statement.
    #
    # A wire trigger is where it earns most: the push has already happened by the time
    # the panel hears it, so every second between the queue and the run is spent on
    # something the game is counting down. `alliance_help` is the one shipped with it
    # on — measured p90 8–10 s of waiting, maximum 1276 s, for a press that takes two.
    immediate: bool = False
    # WATCHES AND DOES NOT ACT. A trigger whose condition is real but whose CURE belongs
    # to somebody else: it polls, it says what it sees, and it never runs its scenario.
    #
    # `session_kick` is the first (#1296). Two mechanisms were aimed at one event — this
    # poll and `panel/runtime/recovery.py` — with different criteria (one truthy reading
    # here, two consecutive ones there) and, for a while, an escalating wait each. Only
    # one of them had ever actually recovered a kick, so the act stays with that one and
    # this side keeps the eyes. The switch on the row therefore means «наблюдаю»: leaving
    # it on is how the disagreement stays VISIBLE instead of being hidden by turning it
    # off.
    #
    # NOT read from the catalogue file on purpose (see `load_catalogue`): who is allowed
    # to act is a property of the code, not a per-profile setting — a hand-edited
    # `triggers.json` must not be able to grant a second executor.
    observe: bool = False
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
            if self.backoff is not None:
                out["backoff"] = self.backoff.as_dict()
        else:
            out["event_pattern"] = self.event_pattern
        if self.immediate:
            out["immediate"] = True
        # `observe` is deliberately NOT written: it belongs to the built-in entry, and a
        # profile file that carried it could be edited into granting a second executor.
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
        # «Сразу, без очереди» (#1288). The one entry that ships with the flag on, and
        # the one the person named when asking for it: the request pays only while it
        # is open, the press is two seconds of headless Lua, and on 2026-08-07 the fire
        # waited a p90 of 8–10 s — and once 1276 s — for its turn behind the schedule.
        immediate=True,
        label_key="triggers.item.alliance_help",
    ),
    Trigger(
        name="rally_monitor",
        # An alliance banner (стяг) going out is announced on the wire
        # (push.alliance.march.*); the watcher reads the rally off the game the
        # instant it lands and logs it — the leader's teamUuid, the target and
        # server, and every member with the squad they sent. Records, does not act.
        kind=KIND_WIRE,
        event_pattern="push.alliance.march",
        scenario=("rally_monitor",),
        enabled=False,
        label_key="triggers.item.rally_monitor",
    ),
    Trigger(
        name="rally_auto_join",
        # The active half of the same banner event: when a rally goes out, join it —
        # with the squads the «Авторалли» page allows for joining, one squad per
        # rally, skipping any the player is already in. The squads are read LIVE from
        # the profile at fire time (panel/__main__.py `_errand_args`), not stored on
        # the trigger, so changing them on the Settings page takes effect at once. The
        # join_rally recipe itself gates — no free squad / already-joined / no rally is
        # a clean no-op. Opt-in.
        kind=KIND_WIRE,
        event_pattern="push.alliance.march",
        scenario=("join_rally",),
        enabled=False,
        label_key="triggers.item.rally_auto_join",
    ),
    Trigger(
        name="resource_tracker",
        # The game pushes «your balance changed» on every resource move
        # (push.resource.item.update). On each one the panel reads the current balance
        # and writes down what went UP since the last read — a daily tally of what was
        # taken in (panel/resource_stats.py, the «Статистика» tab). Records, does not
        # act; the work is a Python handler (`_track_resources`), not a DSL scenario,
        # so `scenario` is a nominal placeholder the runner intercepts. Opt-in.
        kind=KIND_WIRE,
        event_pattern="push.resource.item.update",
        scenario=("track_resources",),
        enabled=False,
        label_key="triggers.item.resource_tracker",
    ),
    Trigger(
        name="inventory_refresh",
        # The same «balance changed» push (push.resource.item.update) fires after a
        # resource OR item count moves in the bag. While this is on, each push re-reads
        # the bag and refreshes the «Инвентарь» tab, so its counts stay live without a
        # manual «Обновить». Python handler (`_refresh_inventory_tab`), not a DSL
        # scenario; the runner intercepts the placeholder. Opt-in.
        kind=KIND_WIRE,
        event_pattern="push.resource.item.update",
        scenario=("__inventory_refresh__",),
        enabled=False,
        label_key="triggers.item.inventory_refresh",
    ),
    Trigger(
        name="leaderboard_collect",
        # A ranking board crosses the wire when the client opens it (al.rank,
        # champion.duel.result.show.rank.list, activity.get.rank.reward — no unsolicited
        # push exists). While this is on, the panel keeps a capture that decodes every
        # board and appends it as a timestamped snapshot to the profile's
        # leaderboard_history.db, so the boards accumulate a history. The listener is a
        # specialised collector (tools/scan_leaderboard.py --sqlite), not the generic
        # marker child — the board data is in the payload, so it is decoded, not read
        # off a mark. Records, does not act. Opt-in.
        kind=KIND_WIRE,
        event_pattern="rank",
        scenario=("__leaderboard_collect__",),
        enabled=False,
        label_key="triggers.item.leaderboard_collect",
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
        # WATCHES, DOES NOT ACT (#1296). Two mechanisms were aimed at this one event —
        # this poll and `panel/runtime/recovery.py` — and only the second had ever
        # actually recovered a kick (fourteen times live against zero fires here, because
        # no poll trigger could fire at all). So the act stays with the module that has
        # done it and this side keeps the eyes: the row's switch means «наблюдаю», and
        # leaving it ON is what keeps the two criteria disagreeing IN VIEW rather than
        # hidden by an unticked box.
        #
        # ITS OWN BACKOFF IS GONE for the same reason. 15 → 30 → 45 min now lives in
        # `recovery.py` (`KICK_HOLD_STEP_SEC`, `KICK_HOLD_MAX_SEC`, `KICK_STABILITY_SEC`)
        # beside the act it delays. Two independent escalations with identical numbers is
        # two executors deferred, not one policy.
        #
        # The scenario is kept although nothing plays it: it is what this trigger would
        # run on the day `recover_from_kick` is PROVEN live and becomes the act — the
        # order of work is written down in `docs/research/session-kick.md`.
        observe=True,
        scenario=("recover_from_kick",),
        enabled=False,
        label_key="triggers.item.session_kick",
    ),
    Trigger(
        name="secret_task_share",
        # An alliancemate sharing a raidable secret task announces it on the wire
        # (alliance.share.mission.add). While this is on, each such push re-reads the
        # game and adds any newly shared starred tile to the «Secret Tasks» tab, so its
        # list stays live without a manual «Обновить». Python handler
        # (`_refresh_secret_tasks_tab`), not a DSL scenario; the runner intercepts the
        # placeholder. Opt-in.
        kind=KIND_WIRE,
        event_pattern="alliance.share.mission.add",
        scenario=("__secret_task_share__",),
        enabled=False,
        label_key="triggers.item.secret_task_share",
    ),
    Trigger(
        name="treasure_auto",
        # A world-map chest announced in alliance chat: send the nearest free squad to
        # dig it and take the gift when it is dug (#1296, `actions/auto_treasure.md`).
        #
        # A POLL, AND NOT BECAUSE A WIRE LISTENER WOULD BE SLOWER — because it would be
        # DEAF. The announcement is a chat post and the chat broadcast rides a TLS
        # websocket this repository cannot decode (`docs/research/chat-system.md`): the
        # 2026-08-08 recording has the message in the Lua trace and not in the capture
        # taken beside it. So the ear is a hook inside the client (#1277) and what this
        # poll asks is the panel's OWN table in the game VM — a local read, one daemon
        # round trip, no request to the server and nothing the map is asked about. The
        # cost is the same read the session-kick poll pays, and the chest is heard in the
        # same second the client hears it.
        #
        # The check is true while a chest is unfinished AND whenever nothing is listening,
        # so a client restart — which wipes the VM and the hook with it — is picked up on
        # the next tick instead of leaving the errand silently deaf.
        kind=KIND_POLL,
        check=lua_actions.treasure_auto_check(),
        # Ten seconds, because the whole point is to be early: the chest is out for
        # minutes and the alliance is already digging. The cooldown is short for the same
        # reason — a chest is worked over several ticks (march, wait for the dig, claim),
        # so sitting quiet for a minute and a half after each fire would be sitting out
        # the claim.
        interval_sec=10,
        cooldown_sec=20,
        scenario=("auto_treasure",),
        enabled=False,
        # «Сразу, без очереди» (#1288), for the reason that flag exists: the chest is
        # being dug by the alliance while the fire waits its turn, and a march that
        # leaves after the chest is gone pays nothing at all.
        immediate=True,
        label_key="triggers.item.treasure_auto",
    ),
    Trigger(
        name="ghost_recon_alliance",
        # The alliance's ghost-recon squads announce themselves on the wire
        # (push.ghost.recon.alliance.single, add/change/remove). The client keeps the
        # full list itself, so this trigger re-READS that local list rather than asking
        # the server anything — which is what makes it cheap enough to run on a push.
        # Python handler on the «Secret Tasks» tab (`refresh_ghost_allies`). Opt-in.
        kind=KIND_WIRE,
        event_pattern="push.ghost.recon.alliance.single",
        scenario=("__ghost_recon_alliance__",),
        enabled=False,
        label_key="triggers.item.ghost_recon_alliance",
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

    def with_enabled(self, config: dict,
                     immediate: "dict | None" = None) -> "TriggerCatalogue":
        """A copy carrying the panel's switches, ready to be saved.

        Only the row's own two move — ``enabled`` and, when the caller offers a second
        dict for it, ``immediate``. The event pattern, the scenario and the args are the
        operator's text; a ticked box must not be able to touch anything else.

        ``immediate`` is a separate argument rather than a second key inside ``config``
        because ``config`` has one other reader — `Schedule.trigger_config`, which turns
        it into «is this trigger listening at all» — and a dict that means two things to
        two callers is how a switch ends up meaning the wrong one.
        """
        config = self.normalize_config(config)
        flags = immediate if isinstance(immediate, dict) else {}
        updated = [Trigger(
            name=t.name, scenario=t.scenario, kind=t.kind,
            event_pattern=t.event_pattern, check=t.check,
            interval_sec=t.interval_sec, cooldown_sec=t.cooldown_sec,
            backoff=t.backoff,
            enabled=bool(config[t.name]),
            immediate=bool(flags.get(t.name, t.immediate)), args=dict(t.args),
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
                                [Message("log.triggers.not_a_list",
                                          "config is not a list of triggers — using the defaults")])

    builtin = {t.name: t for t in DEFAULT_TRIGGERS}
    builtin.update({t.name: t for t in fallback_triggers})
    triggers, errors, seen = [], [], set()
    for index, raw in enumerate(data):
        if not isinstance(raw, dict):
            errors.append(Message("log.triggers.not_an_object",
                                  f"entry #{index + 1} is not an object — skipped",
                                  n=index + 1))
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            errors.append(Message("log.triggers.no_name",
                                  f"entry #{index + 1} has no name — skipped",
                                  n=index + 1))
            continue
        if name in seen:
            errors.append(Message("log.triggers.twice",
                                  f"{name}: listed twice — the later entry is ignored",
                                  name=name))
            continue
        base = builtin.get(name)
        kind = str(raw.get("kind") or (base.kind if base else KIND_WIRE)).strip()
        if kind not in (KIND_WIRE, KIND_POLL):
            errors.append(Message("log.triggers.unknown_kind",
                                  f"{name}: unknown kind '{kind}' — skipped",
                                  name=name, kind=kind))
            continue
        scenario = _as_scenario(raw.get("scenario"))
        if not scenario:
            scenario = base.scenario if base else ()
        if not scenario:
            errors.append(Message("log.triggers.no_scenario",
                                  f"{name}: no scenario to run — skipped", name=name))
            continue
        # A wire trigger needs a pattern to listen for; a poll trigger needs a check
        # to evaluate. Missing the one its kind requires costs the entry, not the set.
        pattern = str(raw.get("event_pattern") or "").strip() or \
            (base.event_pattern if base else "")
        check = str(raw.get("check") or "").strip() or (base.check if base else "")
        if kind == KIND_WIRE and not pattern:
            errors.append(Message("log.triggers.no_pattern",
                                  f"{name}: no event_pattern to watch for — skipped",
                                  name=name))
            continue
        if kind == KIND_POLL and not check:
            errors.append(Message("log.triggers.no_check",
                                  f"{name}: no check to poll — skipped", name=name))
            continue
        args = raw.get("args")
        triggers.append(Trigger(
            name=name,
            scenario=scenario,
            kind=kind,
            # WHO MAY ACT IS THE CODE'S ANSWER, not the file's (#1296). Taken from the
            # built-in entry of the same name and never read out of `triggers.json`: a
            # hand-edited catalogue must not be able to hand a second executor to an event
            # that already has one. A name the code has never heard of is an ordinary
            # trigger, which is what an entry somebody wrote themselves should be.
            observe=bool(base.observe) if base is not None else False,
            event_pattern=pattern,
            check=check,
            interval_sec=_as_interval(
                raw.get("interval_sec"),
                base.interval_sec if base else DEFAULT_POLL_INTERVAL_SEC),
            cooldown_sec=_as_interval(
                raw.get("cooldown_sec"),
                base.cooldown_sec if base else DEFAULT_POLL_COOLDOWN_SEC),
            backoff=BackoffPolicy.from_raw(
                raw.get("backoff"), base.backoff if base else None)
            if "backoff" in raw else (base.backoff if base else None),
            enabled=bool(raw.get("enabled", base.enabled if base else False)),
            immediate=bool(raw.get("immediate",
                                   base.immediate if base else False)),
            args=dict(args) if isinstance(args, dict) else {},
            title=(str(raw["title"]).strip() or None) if raw.get("title") else None,
            label_key=base.label_key if base else None,
        ))
        seen.add(name)

    if not triggers:
        if not errors:
            return TriggerCatalogue((), path)     # "this account watches nothing"
        errors.append(Message("log.triggers.none_usable",
                              "no usable triggers in the config — using the defaults"))
        return TriggerCatalogue(fallback_triggers, path, errors)
    return TriggerCatalogue(triggers, path, errors)


def merge_new(catalogue: TriggerCatalogue,
              seed: "tuple[Trigger, ...] | None" = None,
              ) -> "tuple[TriggerCatalogue, tuple[str, ...]]":
    """Append the triggers the file has never heard of; leave the rest alone.

    A profile written before a trigger shipped has no entry for it, and the file
    owns the list — so without this the operator would have to throw the profile
    away to get at, say, ``session_kick`` at all. Every start the built-in list is
    compared to what was loaded **by name only**, and the names missing from the
    file are appended, in built-in order, exactly as they ship: opt-in, switched
    OFF, so a start can never make the panel begin acting on its own.

    Nothing already in the file is touched — not the switch, not the event, not the
    scenario or the args — and nothing is removed, so a trigger the operator has
    tuned by hand stays tuned. The one thing this gives up is deleting a built-in
    entry: drop it from the file and the next start writes it back (off), which is
    the price of the new ones arriving without a fresh profile.

    Returns the catalogue and the names that were added (empty when nothing was).
    """
    seed = DEFAULT_TRIGGERS if seed is None else seed
    have = {t.name for t in catalogue.triggers}
    added = tuple(t for t in seed if t.name not in have)
    if not added:
        return catalogue, ()
    grown = TriggerCatalogue(tuple(catalogue.triggers) + added,
                             catalogue.path, catalogue.errors)
    return grown, tuple(t.name for t in added)


def load_catalogue(path: str, seed_from=None) -> TriggerCatalogue:
    """Read a catalogue file, falling back to ``seed_from`` / the built-in list.

    A file that does not exist yet is *written* from the seed, so there is always
    something on disk to edit. A file that exists but cannot be read is NOT
    overwritten: the panel runs on the fallback and says so.

    A file that reads fine but predates a trigger gets the missing ones appended
    (:func:`merge_new`) and written back, so an old profile grows the new rows —
    switched off — instead of having to be recreated.
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
    parsed = parse_catalogue(data, path, fallback=seed)
    # The seed already carries the built-ins (the template is itself loaded through
    # here), so merging against it covers both the template and a profile. A file
    # too broken to parse comes back AS the seed, so nothing is missing, nothing is
    # written, and the unreadable file is left as the operator wrote it.
    merged, added = merge_new(parsed, seed.triggers)
    if added:
        save_catalogue(merged, path)
        _dbg.info("%s: added new trigger(s) %s", os.path.basename(path),
                  ", ".join(added))
    return merged


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

    def __init__(self, *, catalogue, config, spawn, submit, log, poll=None,
                 debug=None) -> None:
        # `debug` is the OWNING RUNTIME's technical logger (`rt.dbg("triggers")`),
        # so two open profiles keep two debug.logs (#1206). The module-level one is
        # the fallback for a watcher built without a runtime.
        self._dbg = debug if debug is not None else _dbg
        self._catalogue = catalogue
        self._config = config
        self._spawn = spawn
        self._submit = submit
        self._log = log
        self._poll = poll
        self._lock = threading.Lock()
        self._listeners: dict[str, object] = {}   # trigger name -> handle (.stop())
        # One BackoffState per trigger that carries a BackoffPolicy, kept here (not on
        # the handle) so the escalation survives a listener respawn — a re-read or a
        # profile switch runs `sync`, which stops and re-starts the handle, but a kick
        # war in progress must not have its count reset by that.
        self._backoff: dict[str, BackoffState] = {}
        # The fire roll-up, per trigger: [locale key last said, fires counted since,
        # monotonic of that line]. See :data:`FIRE_NOTE_SEC`.
        self._fires: dict[str, list] = {}
        self._started = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Begin watching: bring up a listener for every enabled trigger."""
        self._started = True
        self._dbg.info("watcher started")
        self.sync()

    def stop(self) -> None:
        """Stop every listener; no trigger fires until :meth:`start` again."""
        self._started = False
        for name in list(self._listeners):
            self._stop_one(name)
        self._dbg.info("watcher stopped")

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
            state = self._backoff_state(trigger)
            handle = _PollHandle(trigger, self._poll,
                                 lambda t=trigger: self._fire(t), self._log,
                                 state=state)
            with self._lock:
                self._listeners[trigger.name] = handle
            self._log("triggers.log.on", name=trigger.name, event=trigger.signal())
            self._dbg.info("listening on %s (poll) for %s", trigger.name, trigger.signal())
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
        self._dbg.info("listening on %s for %s", trigger.name, trigger.signal())
        # An initial sweep: a request already waiting when the ear opens had its push
        # sent before we started listening, so no trigger is coming for it. Run the
        # errand once to clear whatever is already there. Safe because the scenario is
        # gated — it no-ops when there is nothing to do — and the scheduler drops the
        # run if the game is closed rather than failing it.
        self._submit(trigger)

    def _backoff_state(self, trigger) -> "BackoffState | None":
        """The trigger's :class:`BackoffState`, made on first need and kept by name.

        ``None`` when the trigger carries no policy — the poll handle then fires at
        once, the way it always did. A stored state is reused across respawns; if the
        policy has since changed (a hand-edited catalogue re-read), it is rebuilt.
        """
        # AN OBSERVER HAS NO WAIT OF ITS OWN (#1296). Two independent escalations with
        # the same numbers — one here, one in `recovery.py` — is the same duplication as
        # two executors, merely deferred: whichever fired first would look like the
        # policy while the other quietly counted too. The owner of the wait is the module
        # that acts.
        if trigger.observe or trigger.backoff is None:
            self._backoff.pop(trigger.name, None)
            return None
        state = self._backoff.get(trigger.name)
        if state is None or state.policy != trigger.backoff:
            state = BackoffState(trigger.backoff)
            self._backoff[trigger.name] = state
        return state

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
        self._dbg.info("stopped listening on %s", name)

    #: What `TimerScheduler.submit` can answer → the locale key that says it. A fire is
    #: not a run, and until #1281 the log said «запускаю сценарий» over all three: a
    #: profile whose client was down printed that line 10 035 times in a day and ran the
    #: scenario not once. The line now says what actually became of the push.
    _FIRE_WORDS = {
        "queued": "triggers.log.fire",
        # One of the same name is already waiting and has read nothing yet, so it will
        # see whatever this push was about. Coalescing working as intended, said out
        # loud rather than silently.
        "waiting": "triggers.log.fire_waiting",
        # One of the same name is RUNNING and has already read the game. It is marked
        # and will run again the moment it lets go — the case that used to lose the
        # second banner of a burst.
        "refired": "triggers.log.fire_again",
    }

    def _fire(self, trigger) -> None:
        """The trigger's moment came — put the scenario on the shared queue.

        Runs on the listener's thread (a wire child's reader, or a poll thread).
        ``submit`` is thread-safe (it hands to the scheduler's queue); what it does with
        a fire that arrives while one of the same name is already in flight is its
        business, and the WORD it answers with is what this logs (:data:`_FIRE_WORDS`).

        A submit that answers something this does not recognise — an older scheduler, a
        test's stub returning a plain bool — is said the way it always was. A fire is
        never silent.
        """
        if trigger.observe:
            # Says what it sees and stops there. The cure is somebody else's — for
            # `session_kick` it is `recovery.py` — and a second executor on one event is
            # the thing this flag exists to prevent (`docs/research/session-kick.md`).
            self._dbg.info("observe %s on %s", trigger.name, trigger.signal())
            self._note_fire(trigger, "triggers.log.observed")
            return
        self._dbg.info("fire %s on %s", trigger.name, trigger.signal())
        outcome = self._submit(trigger)
        key = self._FIRE_WORDS.get(outcome, "triggers.log.fire")
        self._note_fire(trigger, key)

    def _note_fire(self, trigger, key: str) -> bool:
        """Say what became of this fire — rolled up while it keeps saying the same.

        The first fire, and any fire whose outcome differs from the last one said, is
        said at once in its own words. While the SAME outcome keeps coming back for the
        same trigger it is said again at most every :data:`FIRE_NOTE_SEC`, carrying how
        many fires have piled up since. Returns whether a line was written, which is
        what the tests read.
        """
        now = time.monotonic()
        with self._lock:
            note = self._fires.get(trigger.name)
            if note is not None and note[0] == key:
                note[1] += 1
                if now - note[2] < FIRE_NOTE_SEC:
                    return False
                count, note[1], note[2] = note[1], 0, now
            else:
                self._fires[trigger.name] = [key, 0, now]
                count = 1
        if count > 1:
            self._log("triggers.log.fire_more", name=trigger.name,
                      event=trigger.signal(), count=count)
        else:
            self._log(key, name=trigger.name, event=trigger.signal())
        return True

    def on_listener_exit(self, name: str) -> None:
        """A listener died on its own — forget the handle so :meth:`sync` respawns."""
        self._dbg.warning("listener %s exited on its own", name)
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

    When the trigger carries a :class:`BackoffPolicy`, a truthy answer does not fire
    at once: the handle waits the policy's current delay first (:class:`BackoffState`),
    so a fault that keeps returning is answered later and later instead of instantly.
    ``state`` is that running delay (shared by the watcher across respawns) and ``now``
    is the clock it reads — injected so a test can drive time by hand.
    """

    def __init__(self, trigger, poll, on_fire, log, state=None, now=None) -> None:
        self._trigger = trigger
        self._poll = poll
        self._on_fire = on_fire
        self._log = log
        self._state = state          # a BackoffState, or None for fire-at-once
        self._now = now or time.monotonic   # injectable clock, for the tests
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
                hit = self._poll is not None and bool(self._poll(t))
            except Exception as exc:              # noqa: BLE001 — a bad read must not
                # kill the watch; log once and carry on to the next interval.
                self._log("triggers.log.poll_error", name=t.name, error=exc)
                hit = False
            if hit and self._state is not None:
                # Adaptive backoff: wait longer and longer before each run while the
                # fault keeps returning, so a repeating kick is not met with a relaunch
                # war. The wait itself sits quiet — no polling until it is over.
                delay = self._state.plan(self._now())
                self._log("triggers.log.backoff", name=t.name,
                          minutes=max(1, int(round(delay / 60.0))))
                if self._stop.wait(delay):        # stopped while waiting → clean exit
                    break
                # …AND THE CONDITION IS ASKED AGAIN BEFORE FIRING (#1296). The wait used
                # to be blind: whatever the check said a quarter of an hour ago was acted
                # on now, however things stood by then. For the kick that means a modal
                # that merely flickered — one truthy reading — buys a relaunch of a
                # perfectly healthy client fifteen minutes later, and nothing in between
                # is ever asked. The fault is not the kick's: ANY poll trigger carrying a
                # backoff fires on a reading that may be long gone.
                #
                # A re-read that cannot be taken (the daemon went away, the game closed)
                # answers False, and False here means «do not act» — which is the safe
                # direction for a cure: not acting costs a later fire, acting on nothing
                # costs a live client.
                try:
                    still = self._poll is not None and bool(self._poll(t))
                except Exception as exc:          # noqa: BLE001 — same rule as above
                    self._log("triggers.log.poll_error", name=t.name, error=exc)
                    still = False
                if not still:
                    # A fire that did NOT happen is an event too, and this whole area is
                    # about events that cannot be told apart: a wait that ended in
                    # nothing must not look like a wait that never happened.
                    self._log("triggers.log.stale", name=t.name)
                    self._state.mark_run(self._now())
                    self._stop.wait(t.cooldown_sec)
                    continue
                self._on_fire()
                self._state.mark_run(self._now())
                fired = True
            elif hit:
                self._on_fire()
                fired = True
            # Wait on the stop event so a stop is noticed at once, not at the end of a
            # full interval: `wait` returns True the moment it is set. cooldown_sec is
            # a short settle after a run so the fading state is not read as a new fire.
            self._stop.wait(t.cooldown_sec if fired else t.interval_sec)
