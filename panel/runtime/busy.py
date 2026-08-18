"""WHAT THE PANEL IS BUSY WITH, at one instant — the reading a jam is diagnosed from.

The panel already says a great deal about itself and none of it answers «почему ничего
не происходит». The log is what HAPPENED, and a run that is stuck writes nothing. The
activity strip is what is being DONE, and it shows one step of one profile. The stall
watch (`panel/runtime/stall.py`) is what is holding the TK thread, which is a different
fault — a jam is usually four threads politely waiting for one claim, and the window
redraws perfectly the whole time.

So this takes ONE SNAPSHOT of everything that can make work wait, in the order a person
actually asks about it (#1392):

* **потоки** — the scenarios running right now: name, who started them, the DSL step
  they are on and for how long (`panel/runtime/interrupt.py`), plus the profile's live
  activity steps beside them;
* **очередь** — the errands lined up behind the single scheduler worker, longest wait
  first, and the ones parked because the panel was busy (`panel/timers.py`);
* **замок** — who holds the game claim and the desktop's foreground, for how long, who
  is queued behind them at what urgency, and how many claims each key has turned away
  (`panel/runtime/claims.py`);
* **таймеры** — the errands on a clock: next due, last attempt, what is overdue; and the
  window's own armed `after` chains, where a NEGATIVE `due_in` means the event loop has
  not got round to a chain whose moment has passed (`panel/runtime/tick.py`);
* **самое долгое** — the runs that have already finished, longest first, because the run
  that held the client for four minutes is gone from every live reading by the time
  anybody looks.

THREE RULES IT IS WRITTEN UNDER, and each of them is a project rule rather than taste:

1. **It costs nothing.** Dict reads under locks that are already held for microseconds,
   plain arithmetic, and `sys._current_frames()` for the thread list. NO Tk — a reading
   taken from a worker thread must never touch a widget (#1226) — and NO game: the whole
   point is to explain a panel that is not answering, and asking the client would join
   the very queue being measured.
2. **It is a profile's own.** Everything read off `rt` is this profile's: its runs, its
   steps, its schedule, its `after` chains. The two things that are genuinely shared —
   the claim registry and the process's threads — are shown as shared and every row
   carries WHOSE it is, which is what `docs/research/profile-isolation.md` asks for.
   That is why `play_async` names its worker `lw:<profile>:<tag>:<scenario>` and why a
   scheduler thread is `panel-timers:<profile>`.
3. **It says nothing.** Every value here is a number or a name; not one word of it is a
   sentence. Whoever draws it says the words in whatever language that window is showing
   (`CLAUDE.md`, «Not one word of the panel is written in the panel»).

Read with no window at all:

    python3 tests/test_panel_busy.py
"""
from __future__ import annotations

import sys
import threading
import time

from . import claims

#: A thread sitting in one of these has released Python's lock: it is WAITING, not
#: working, and listing it would bury the two or three threads that are. The same set
#: the stall watch filters by, and for the same reason.
_PARKED = frozenset({"wait", "acquire", "sleep", "select", "poll", "read", "readline",
                     "recv", "recv_into", "accept", "join", "_wait_for_tstate_lock",
                     "_worker", "get", "_poll"})

#: The prefix `panel/runtime/host.py::play_async` gives a scenario's worker thread, and
#: `panel/timers.py` its scheduler. Spelled here so the snapshot can say which profile a
#: thread belongs to without a registry of threads that would have to be kept in step.
RUN_PREFIX = "lw:"
TIMER_PREFIX = "panel-timers"

#: How many finished runs the mini-top shows.
TOP = 5


def _short(path: str) -> str:
    """`…/panel/tabs/chat.py` → `panel/tabs/chat.py`, and leave the rest alone."""
    parts = str(path).replace("\\", "/").split("/")
    for anchor in ("panel", "tools", "src", "tests"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor):])
    return parts[-1]


def threads(profile: str = "") -> list:
    """Every living thread with Python on it: name, whose it is, innermost frame.

    The last resort of a jam diagnosis, and the reason the names above exist. A thread
    parked in a wait is left out (see :data:`_PARKED`) — otherwise the list is three
    quarters idle pollers and the one thread doing something is lost in it.

    ``profile`` marks the rows that belong to the asking profile: a thread name carries
    it (`lw:<profile>:…`), so «чей поток» is answered without a registry that could drift.
    One pass over `sys._current_frames()`, which is a snapshot of the interpreter's own
    dict — no stack is walked beyond its innermost frame.
    """
    frames = sys._current_frames()
    living = {t.ident: t for t in threading.enumerate()}
    me = threading.get_ident()
    out = []
    for ident, frame in list(frames.items()):
        thread = living.get(ident)
        name = thread.name if thread is not None else f"thread-{ident}"
        try:
            where = f"{_short(frame.f_code.co_filename)}:{frame.f_lineno} " \
                    f"{frame.f_code.co_name}"
            parked = frame.f_code.co_name in _PARKED
        except Exception:                    # noqa: BLE001 — a racing frame
            continue
        if parked and ident != me:
            continue
        owner = ""
        if name.startswith(RUN_PREFIX):
            owner = name.split(":")[1] if len(name.split(":")) > 1 else ""
        elif name.startswith(TIMER_PREFIX) and ":" in name:
            owner = name.split(":", 1)[1]
        out.append({"name": name, "where": where, "owner": owner,
                    "mine": bool(profile) and owner == profile,
                    "daemon": bool(getattr(thread, "daemon", False))})
    out.sort(key=lambda row: (not row["mine"], row["name"]))
    return out


def _queue(rt) -> dict:
    """This profile's errand queue, or an empty one when it has never been built.

    ASKED THROUGH `_schedule` AND NOT `rt.schedule`, deliberately: the property builds
    the schedule on first ask, which reads two catalogue files off disk. A debugger that
    quietly constructs the thing it is measuring is a debugger that lies about a panel
    which does not have one (a tab opened on its own has none).
    """
    schedule = getattr(rt, "_schedule", None)
    if schedule is None:
        return {}
    try:
        from .. import timers as timersmod

        state = schedule.timers.queue_state()
        # WHEN A GATED FIRE'S PATIENCE RUNS OUT (#1500) — derived here, once, from the
        # scheduler's own constant, rather than a copy of `GATE_KEEP_SEC` kept beside
        # it: the row already carries its age, and this is arithmetic on it, not a
        # second reading of anything.
        for row in state.get("gated") or ():
            row["expires_in"] = max(0.0, timersmod.GATE_KEEP_SEC - row["secs"])
            row["retry_sec"] = int(timersmod.GATE_RETRY_SEC)
        return state
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        return {}


def _timers(rt, now: float, limit: int = 12) -> list:
    """The errands on a clock: when each is next due, and how the last attempt ended.

    Sorted by how soon they fire, so what is OVERDUE (a negative `due_in`) is at the top
    — which is the row a jam shows itself in: an errand whose moment passed ten minutes
    ago and which is still not running is waiting for something.
    """
    schedule = getattr(rt, "_schedule", None)
    if schedule is None:
        return []
    try:
        from .. import timers as timersmod

        catalogue = schedule.timer_catalogue
        config = catalogue.normalize_config(schedule.timer_config())
        records = schedule.store.records()
        rows = []
        for timer in catalogue:
            due = catalogue.next_due(timer, config, records, getattr(rt, "day", None))
            if due is None:
                continue                     # switched off — not a timer that is late
            state, when = timersmod.last_attempt(records, timer.name)
            rows.append({"name": timer.name, "due_in": due - now if due else 0.0,
                         "last": when, "state": state})
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        return []
    rows.sort(key=lambda row: row["due_in"])
    return rows[:limit]


def snapshot(rt, *, top: int = TOP) -> dict:
    """Everything above, at this instant, as plain data. No Tk, no game, no I/O.

    ``rt`` is ONE profile's runtime and the answer is that profile's, except for the two
    sections that are honestly shared — `claims` and `threads` — which name whose each
    row is. See the module docstring for why the split is where it is.
    """
    now = time.monotonic()
    wall = time.time()
    profile = ""
    try:
        profile = rt.profiles.active
    except Exception:                        # noqa: BLE001 — a bare harness
        pass

    runs = []
    interrupts = getattr(rt, "interrupts", None)
    if interrupts is not None:
        runs = [run.state() for run in interrupts.running()]

    steps = []
    activity = getattr(rt, "activity", None)
    if activity is not None:
        steps = [{"key": step.key, "fmt": dict(step.fmt),
                  "secs": max(0.0, now - step.started)}
                 for step in activity.live()]

    ticks = []
    tick = getattr(rt, "tick", None)
    if tick is not None and hasattr(tick, "pending"):
        ticks = tick.pending()

    registry = claims.state()
    endpoint = ""
    try:
        endpoint = rt.game.endpoint()
    except Exception:                        # noqa: BLE001 — no link in a bare harness
        endpoint = ""
    for row in registry["held"] + registry["waiting"]:
        row["mine"] = bool(profile) and str(row["owner"]).startswith(f"{profile}/")
        row["client"] = row["key"] == endpoint

    history = interrupts.history()[:top] if interrupts is not None else []

    return {
        "profile": profile,
        "now": now,
        "wall": wall,
        "runs": runs,
        "steps": steps,
        "queue": _queue(rt),
        "claims": registry["held"],
        "waiting": registry["waiting"],
        "timers": _timers(rt, wall),
        "ticks": ticks,
        "threads": threads(profile),
        "slowest": history,
        "posted": _posted(rt),
        # …and what this profile is LISTENING to, which is the other half of «почему
        # ничего не происходит»: the sections above say what is being done, and this one
        # says what should have woken it (#1416).
        "listeners": listeners(rt, now),
    }


#: What counts as «дольше обычного» before a symptom is worth naming. Round numbers
#: rather than measured ones on purpose: they are the threshold of somebody LOOKING at a
#: row, not a rule anything acts on — nothing here changes what the panel does.
CLAIM_LONG_SEC = 120.0      #: a claim held this long is worth a second look
WAIT_LONG_SEC = 10.0        #: …and a press waiting this long is being made to queue
QUEUE_LONG_SEC = 60.0       #: an errand that has been in the queue this long
TIMER_LATE_SEC = 120.0      #: a timer whose moment passed this long ago
TICK_LATE_SEC = 2.0         #: an `after` chain the event loop has not got to
POSTED_MANY = 50            #: hand-overs waiting for the Tk thread


def verdicts(snap: dict) -> list:
    """The signs of a jam in one snapshot: ``[{key, fmt}]`` — keys, never sentences.

    Everything here is already visible in the sections above; what this adds is the
    ORDER OF SUSPICION, which is the whole difference between a diagnostic and a wall of
    numbers. Each entry names a locale key and the values that go in it, and whoever
    draws it says the words.
    """
    out = []
    for row in snap.get("claims", []):
        if row["secs"] >= CLAIM_LONG_SEC:
            out.append({"key": "busy.jam.claim",
                        "fmt": {"owner": row["owner"], "secs": int(row["secs"])}})
    for row in snap.get("waiting", []):
        if row["secs"] >= WAIT_LONG_SEC:
            out.append({"key": "busy.jam.waiting",
                        "fmt": {"owner": row["owner"], "secs": int(row["secs"])}})
    queue = snap.get("queue") or {}
    late = [row for row in queue.get("waiting", []) if row["secs"] >= QUEUE_LONG_SEC]
    if late:
        out.append({"key": "busy.jam.queue",
                    "fmt": {"count": len(queue.get("waiting", [])),
                            "name": late[0]["name"], "secs": int(late[0]["secs"])}})
    if queue.get("held"):
        out.append({"key": "busy.jam.held",
                    "fmt": {"count": len(queue["held"]),
                            "secs": int(queue.get("hold_secs", 0))}})
    refused = sum(int(row.get("refused", 0)) for row in snap.get("claims", []))
    if refused:
        out.append({"key": "busy.jam.refused", "fmt": {"count": refused}})
    overdue = [row for row in snap.get("timers", [])
               if row["due_in"] <= -TIMER_LATE_SEC]
    if overdue:
        out.append({"key": "busy.jam.timer",
                    "fmt": {"name": overdue[0]["name"],
                            "secs": int(-overdue[0]["due_in"]), "count": len(overdue)}})
    slow_tick = [row for row in snap.get("ticks", []) if row["due_in"] <= -TICK_LATE_SEC]
    if slow_tick:
        out.append({"key": "busy.jam.tick",
                    "fmt": {"name": slow_tick[0]["name"],
                            "secs": int(-slow_tick[0]["due_in"])}})
    if int(snap.get("posted", 0)) >= POSTED_MANY:
        out.append({"key": "busy.jam.posted", "fmt": {"count": int(snap["posted"])}})
    return out


class StepWatch:
    """The mini-top of «what STEP took longest», sampled off the snapshots (#1392).

    A run's step is on its context and nowhere else, and it changes as the interpreter
    walks the recipe — so the only way to know a step took forty seconds is to have
    noticed it before and after. That could be done in the engine; it is done here
    instead, by comparing one snapshot with the last, because a debugger has no business
    adding a hook to the path every scenario runs through.

    The resolution is therefore the refresh interval and no better: a step shorter than
    one refresh is not seen at all, which is exactly right — this exists to find the long
    ones. Fed on the thread that refreshes (the Tk one), holds a bounded ring, and costs
    a dict lookup per running scenario.
    """

    def __init__(self, keep: int = 40) -> None:
        from collections import deque

        self._seen: dict = {}
        self._done: deque = deque(maxlen=int(keep))

    def feed(self, snap: dict) -> None:
        now = float(snap.get("now") or time.monotonic())
        live = {}
        for run in snap.get("runs", []):
            key = (run.get("name", ""), run.get("tag", ""))
            step = str(run.get("step") or "")
            was = self._seen.get(key)
            if was is not None and was[0] != step:
                self._finish(key[0], was, now)
            live[key] = (step, now if was is None or was[0] != step else was[1])
        for key, was in self._seen.items():
            if key not in live:              # the run ended: its last step ended too
                self._finish(key[0], was, now)
        self._seen = live

    def _finish(self, name: str, was: tuple, now: float) -> None:
        step, since = was
        if not step:
            return
        self._done.append({"name": name, "step": step,
                           "secs": max(0.0, now - since)})

    def top(self, limit: int = TOP) -> list:
        """The longest steps seen since this watch started, longest first."""
        rows = sorted(self._done, key=lambda row: row["secs"], reverse=True)
        return rows[:limit]

    def clear(self) -> None:
        self._seen.clear()
        self._done.clear()


#: The capture children this panel starts, keyed by the tool that IS the listener, and
#: the locale key that says what each one is FOR. A tag alone («secret», «trigger») names
#: the slot rather than the job, and two very different sniffers share one tag.
#:
#: A tool this table has never heard of still gets a row — its own file name in the
#: «what» column and no description — because a listener nobody wrote a line for is
#: exactly the one somebody will be hunting (#1416).
CHILD_KINDS = {
    "secret_task_capture.py": "busy.listener.secret_tasks",
    "secret_mission_capture.py": "busy.listener.ghost",
    "secret_share_autoloot.py": "busy.listener.share_autoloot",
    "rally_monitor.py": "busy.listener.rally",
    "scan_leaderboard.py": "busy.listener.leaderboard",
    "wire_event_monitor.py": "busy.listener.ear",
    "chat_reader.py": "busy.listener.chat",
    "map_capture.py": "busy.listener.map",
}


def _tool(cmd) -> str:
    """`…/tools/secret_task_capture.py --json …` → `secret_task_capture.py`."""
    for part in reversed(list(cmd or ())):
        text = str(part)
        if text.endswith(".py"):
            return text.replace("\\", "/").rsplit("/", 1)[-1]
    return str((cmd or [""])[0]).replace("\\", "/").rsplit("/", 1)[-1]


def listeners(rt, now: "float | None" = None) -> list:
    """EVERYTHING THIS PROFILE IS LISTENING TO, and whether any of it is arriving (#1416).

    «Пропускаются события» is unanswerable from a list of subscriptions: a listener that
    has gone deaf and one over a quiet map look exactly the same — both are switched on,
    both say nothing. So each row here carries three things, and the third is the one
    that was missing:

    * **what** — the stream or the event, as a key whoever draws it can say in words;
    * **is it working** — `alive` (the process / the watch is up) AND `last` (when
      something last came through it, `0.0` for never). Neither alone is proof: a live
      process that has heard nothing since it started is the failure being hunted;
    * **why it exists** — a `desc` key, so the row explains itself to somebody who did
      not switch it on.

    Three sources, because there are three kinds of listener in this panel:

    1. **the profile's ear** (`rt.wire`) — one capture carrying every push pattern
       anybody subscribed to, with the count per pattern;
    2. **the standing orders** (`rt.triggers`) — the catalogue, INCLUDING the ones
       switched off, because «выключен» is an answer;
    3. **the capture children** (`rt.children`) — the sniffers with a life of their own:
       the ★ tiles, the ghost squads, the rally banners, the leaderboards.

    No Tk, no game, no I/O — dict reads and `time.monotonic`, like the rest of this
    module. Not one word of it is a sentence.
    """
    now = time.monotonic() if now is None else now
    out = []

    hub = getattr(rt, "wire", None)
    if hub is not None and hasattr(hub, "report"):
        try:
            rows = hub.report()
        except Exception:                     # noqa: BLE001 — a debugger never raises
            rows = []
        for row in rows:
            last = float(row.get("last") or 0.0)
            out.append({"kind": "wire", "what": str(row.get("pattern") or ""),
                        "desc": "busy.listener.push", "alive": bool(row.get("alive")),
                        "heard": int(row.get("heard") or 0),
                        "since": (now - last) if last else None,
                        "detail": str(row.get("command") or ""),
                        "who": str(row.get("subscribers") or "")})

    watcher = getattr(rt, "triggers", None)
    if watcher is not None and hasattr(watcher, "report"):
        try:
            rows = watcher.report()
        except Exception:                     # noqa: BLE001
            rows = []
        for row in rows:
            last = float(row.get("last") or 0.0)
            out.append({"kind": "poll" if row.get("poll") else "trigger",
                        "what": str(row.get("name") or ""),
                        "desc": str(row.get("label") or ""),
                        "alive": bool(row.get("watching")),
                        "heard": int(row.get("fires") or 0),
                        "since": (now - last) if last else None,
                        # A poll's `check` is a Lua chunk and a wire trigger's signal is
                        # a command name; both are the answer to «на что смотрит».
                        "detail": str(row.get("signal") or ""),
                        "who": str(row.get("title") or "")})

    factory = getattr(rt, "children", None)
    if factory is not None:
        try:
            # A PROPERTY, not a call (`ChildFactory.live`) — and asking it is also what
            # tidies a child that ended on its own, so the list here can never name a
            # process that has been handed back to the machine.
            kids = list(getattr(factory, "live", ()) or ())
        except Exception:                     # noqa: BLE001
            kids = []
        for kid in kids:
            tool = _tool(getattr(kid, "cmd", ()))
            last = float(getattr(kid, "last_line_at", 0.0) or 0.0)
            out.append({"kind": "capture", "what": tool,
                        "desc": CHILD_KINDS.get(tool, ""),
                        "alive": bool(getattr(kid, "alive", False)),
                        "heard": int(getattr(kid, "lines", 0) or 0),
                        "since": (now - last) if last else None,
                        "detail": str(getattr(kid, "tag", "") or ""),
                        "who": str(getattr(kid, "pid", "") or "")})
    return out


#: How long a listener may say nothing before the row is worth a second look. Not a rule
#: anything acts on — a quiet map genuinely produces nothing — but five minutes is where
#: «тихо» stops being ordinary for a ★ capture on a moving map or an ear with the rally
#: pattern on it, which are the two people ask about.
LISTENER_QUIET_SEC = 300.0


def _posted(rt) -> int:
    """How many hand-overs are queued for the Tk thread — the other kind of jam.

    Everything a worker wants drawn goes through one queue per WINDOW
    (`panel/runtime/tick.py::TkPost`). A number that keeps growing says the event loop is
    not draining it, which is the difference between «the game is holding us up» and «the
    window is».
    """
    tick = getattr(rt, "tick", None)
    widget = getattr(tick, "_w", None)
    if widget is None:
        return 0
    try:
        from .tick import poster

        post = poster(widget)
        return post.pending() if post is not None else 0
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        return 0
