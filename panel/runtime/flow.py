"""IS THE DATA ARRIVING, AND ARE WE TAKING IT — one badge, drawn ON the grid (#1549).

WHY THIS EXISTS. The operator's report was one sentence: «Я хожу по карте, и грид не
заполняется.» An empty table cannot answer it, because four completely different things
draw the same empty table:

* nothing is being sent — the map is quiet, the event is over, the client is in the base;
* something IS being sent and the panel is not taking it — the receiver is asleep, or
  nobody is asking the source at all;
* it was taken and thrown away — the `lost` number `panel/runtime/intake.py` exists for;
* the source is dead — the capture child exited, the trigger was switched off.

Those four cost days, one at a time, because from outside the window they are one blank
page. `intake.py` already counts what each receiver did with what it was handed, and
`busy.listeners` already says whether the SOURCE is alive — but both of them are read on
«Занятость», in the «Разработка» tab, which is a place a person walking the map is not.
So this module joins the two halves into ONE small record per receiver, and every grid
that is fed by a stream draws it above its own table.

THE DISTINCTION THAT MATTERS, and it is the whole point:

    seen == 0 while the source is alive and has heard things  ->  STARVING
    seen == 0 while the source has heard nothing at all       ->  QUIET / NEVER

«Данных нет, потому что их не присылают» and «данные идут, но мы их не берём» are
different sentences, they lead a person to do different things, and until now the panel
said neither.

NOT ONE WORD OF IT IS A SENTENCE. Every field is a number, a key or a bool; whoever draws
it says the words in whatever language that window is showing (`CLAUDE.md`).

WHAT IT COSTS. `busy.listeners` walks the profile's ear, its triggers and its capture
children — dict reads, no I/O — and the ledger is four integers under a microsecond lock.
Nine grids asking once a second each would still be nothing, but they do not: the board is
built at most once per :data:`CACHE_SEC` per profile and every grid reads that. No Tk, no
game, no I/O, the same three rules `busy.py` and `intake.py` are written under.

WHOSE IT IS. A profile's own, like the ledger it reads — the cache hangs off the runtime,
so four open accounts have four boards and no row of one can be read as the other's.

Read with no window at all:

    python3 tests/test_panel_flow.py
"""
from __future__ import annotations

import time

from . import busy as busymod
from . import intake as intakemod

#: How long a board is reused before it is rebuilt. A second is under the eye's own
#: resolution for a counter, and it is what keeps nine grids on four profiles from
#: walking the child list nine times a second between them.
CACHE_SEC = 1.0

#: Anything heard inside this window is «идёт прямо сейчас». Deliberately short: the
#: question the badge answers is «сейчас», and a minute-old arrival is already history to
#: somebody watching a grid while they walk.
FRESH_SEC = 60.0

#: …and past this, the row has been silent long enough to be worth a second look. The
#: same number, and the same caveat, as `intake.QUIET_SEC` and `busy.LISTENER_QUIET_SEC`:
#: a quiet map genuinely produces nothing, so this COLOURS a row rather than deciding
#: anything.
QUIET_SEC = intakemod.QUIET_SEC

# -- the states a badge can be in, worst first ------------------------------------
#: Something was accepted and thrown away. Never ordinary — see `intake.py`.
LOSING = "losing"
#: The source is heard from and the receiver has taken nothing. THE ONE THIS EXISTS FOR.
STARVING = "starving"
#: The source that should be feeding this receiver ran and is not running any more.
DEAD = "dead"
#: …and it has NEVER been started, which is a switch to flip rather than a bug to chase
#: (#1549). Kept apart from :data:`DEAD` after the first live reading said «источник не
#: работает» about a chat sniffer nobody had switched on — true, and the wrong thing to
#: send somebody looking for.
OFF = "off"
#: Nothing has ever arrived here, from anywhere.
NEVER = "never"
#: THE ASK ITSELF IS NOT GETTING THROUGH (#1549). Refusals are being recorded right now
#: and nothing has ARRIVED for a while — a poll that cannot run (the client is in the
#: base, the daemon is down, a read failed). Kept apart from :data:`QUIET`, which is «the
#: map has nothing to say»: the operator asked «пока таймаут, данные пропадают?» and a
#: strip reading «тихо» over 223 refused polls answers the wrong question.
REFUSED = "refused"
#: Something arrived within :data:`FRESH_SEC` — the live signal.
FLOWING = "flowing"
#: It worked, and has said nothing for a while.
QUIET = "quiet"

#: What each state is drawn in. Keys rather than colours would be one indirection too
#: many for three shades; the grids and the phone use the same three so a person reading
#: one recognises the other.
COLOURS = {
    LOSING: "#e04f4f",
    STARVING: "#e0a84f",
    DEAD: "#e04f4f",
    OFF: "#888888",
    REFUSED: "#e0a84f",
    NEVER: "#888888",
    FLOWING: "#4fe08a",
    QUIET: "#e0d84f",
}

#: WHICH LISTENER FEEDS WHICH RECEIVER — the join the two halves were missing.
#:
#: The keys are `intake` receiver names, the values the `what` of a row in
#: `busy.listeners` (a capture child's tool file, or an ear pattern). A receiver with an
#: EMPTY tuple has no listener at all and says so: the monster page is asked, never told
#: (nothing on the wire names a monster — #1289), and a badge that invented a source for
#: it would be the same lie in a new place.
SOURCES = {
    "secret.tiles": ("secret_task_capture.py",),
    "secret.areas": ("secret_task_capture.py",),
    "secret.alliance": (),
    "world.checkpoint": ("secret_task_capture.py",),
    "ghost.map": ("secret_mission_capture.py",),
    "ghost.squads": ("secret_mission_capture.py",),
    "world.monsters": (),
    "rally.banners": ("rally_monitor.py",),
    "chat.messages": ("chat_reader.py",),
    "stats.gains": (),
}


def sources_of(receiver: str) -> tuple:
    """The listener names that feed ``receiver`` — empty when it is ASKED, not told."""
    return SOURCES.get(str(receiver), ())


def _source(rows, names, now: float) -> "dict | None":
    """The best row among ``names``: alive beats dead, then whatever heard most."""
    if not names:
        return None
    found = [row for row in rows or () if str(row.get("what") or "") in names]
    if not found:
        return {"alive": False, "heard": 0, "since": None, "known": False}
    found.sort(key=lambda row: (not row.get("alive"), -int(row.get("heard") or 0)))
    best = found[0]
    return {"alive": bool(best.get("alive")),
            "heard": int(best.get("heard") or 0),
            "since": best.get("since"),
            "known": True}


def _state(row: dict, source: "dict | None") -> str:
    """Which of the six a receiver is in. The order IS the diagnosis (see the docstring)."""
    if int(row.get("lost") or 0) > 0:
        return LOSING
    heard = int((source or {}).get("heard") or 0)
    seen = int(row.get("seen") or 0)
    if source is not None and not source.get("alive"):
        # A dead source with nothing taken is a dead source; a dead source we DID take
        # from is still a dead source — the rows on screen are the last it ever sent.
        # …and one that was never STARTED says that instead: the answer to it is a
        # switch, not a bug report.
        return DEAD if source.get("known") else OFF
    if seen == 0:
        # THE SPLIT THIS MODULE EXISTS FOR. Heard something and took none of it is not
        # the same fact as «nobody sent anything», and drawing them alike is what cost
        # the days this task is about.
        return STARVING if heard > 0 else NEVER
    # …and the freshness is of an ARRIVAL, never of a refusal (`intake.since_in`). A
    # receiver polled every twenty seconds with the client in the base records a drop on
    # every tick; reading `since` there would paint «идёт прямо сейчас» over a page
    # nothing has reached for an hour.
    since = row.get("since_in", row.get("since"))
    if since is None:
        return NEVER
    if float(since) <= FRESH_SEC:
        return FLOWING
    # …and «тихо» only when the silence is the SOURCE's. Something happened here just
    # now and it was not an arrival, so it was a refusal — the ask is not getting
    # through, which is a different sentence and a different thing to do about it.
    last = row.get("since")
    if (int(row.get("dropped") or 0) > 0 and last is not None
            and float(last) <= FRESH_SEC):
        return REFUSED
    return QUIET


def badge(rt, receiver: str, *, now: "float | None" = None) -> dict:
    """One receiver's whole answer, as plain data. Never raises, never blocks.

    ``{what, state, colour, seen, kept, dropped, lost, since, reasons, losses, source}``
    — where ``source`` is ``None`` for a receiver nobody feeds (it is ASKED), and
    otherwise ``{alive, heard, since, known}``.
    """
    return board(rt, now=now).get(str(receiver)) or _empty(receiver)


def _empty(receiver: str) -> dict:
    """A receiver that has never recorded anything and has no listener behind it."""
    return {"what": str(receiver), "state": NEVER, "colour": COLOURS[NEVER],
            "seen": 0, "kept": 0, "dropped": 0, "lost": 0, "since": None,
            "reasons": {}, "losses": {}, "source": None}


def build(rt, *, now: "float | None" = None) -> dict:
    """Every receiver's badge, keyed by name — the board, built fresh."""
    now = time.monotonic() if now is None else now
    try:
        heard = busymod.listeners(rt, now)
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        heard = []
    rows = {row["what"]: row for row in intakemod.of(rt).report(now)}
    out = {}
    # Every receiver the ledger knows about, PLUS every one the table names: a grid whose
    # feed has not fired once this session still has a badge, and it says «ни разу».
    for name in set(rows) | set(SOURCES):
        row = rows.get(name) or {"what": name, "seen": 0, "kept": 0, "dropped": 0,
                                 "lost": 0, "since": None, "since_in": None,
                                 "reasons": {}, "losses": {}}
        source = _source(heard, sources_of(name), now)
        state = _state(row, source)
        out[name] = {"what": name, "state": state, "colour": COLOURS[state],
                     "seen": int(row.get("seen") or 0),
                     "kept": int(row.get("kept") or 0),
                     "dropped": int(row.get("dropped") or 0),
                     "lost": int(row.get("lost") or 0),
                     "since": row.get("since_in", row.get("since")),
                     "reasons": dict(row.get("reasons") or {}),
                     "losses": dict(row.get("losses") or {}),
                     "source": source}
    return out


def board(rt, *, now: "float | None" = None) -> dict:
    """The board for this profile, rebuilt at most once per :data:`CACHE_SEC`.

    Cached ON THE RUNTIME, so it is a profile's own and a window with four accounts open
    keeps four of them. A runtime that will not hold an attribute (a bare harness, a
    `types.SimpleNamespace` in a test) is answered without a cache rather than refused.
    """
    stamp = time.monotonic() if now is None else now
    got = getattr(rt, "_flow_board", None)
    if got is not None and stamp - got[0] < CACHE_SEC:
        return got[1]
    made = build(rt, now=stamp)
    try:
        rt._flow_board = (stamp, made)       # noqa: SLF001 — the cache is the runtime's
    except Exception:                        # noqa: BLE001 — a harness with no slots
        pass
    return made


def ago(seconds) -> str:
    """`0:42` — how long ago, in the same shape every countdown on these grids uses."""
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def why(badge_row: dict) -> str:
    """The reasons behind a badge, as a plain comma list — keys, never sentences.

    The LOSSES first, because they are the ones that are never ordinary, then the
    deliberate drops. Empty when a receiver has neither, which is the ordinary case.
    """
    names = list((badge_row.get("losses") or {})) + list((badge_row.get("reasons") or {}))
    return ", ".join(names)


#: The locale key each state's one-line summary is said with. Every one takes the SAME
#: fields — `seen` `kept` `dropped` `lost` `since` `heard` `why` — so a caller fills one
#: dict and does not branch on the state to know what to pass.
LINE_KEYS = {
    LOSING: "flow.state.losing",
    STARVING: "flow.state.starving",
    DEAD: "flow.state.dead",
    OFF: "flow.state.off",
    REFUSED: "flow.state.refused",
    NEVER: "flow.state.never",
    FLOWING: "flow.state.flowing",
    QUIET: "flow.state.quiet",
}


def line(badge_row: dict) -> dict:
    """``{key, fmt, colour}`` — what to say about this badge and what colour to say it in.

    The words are the caller's: this hands over a locale key and the numbers that go in
    it, exactly as `busy.verdicts` does, so the same badge reads in Russian in one window
    and in Turkish in the next.
    """
    source = badge_row.get("source") or {}
    return {"key": LINE_KEYS.get(badge_row.get("state"), LINE_KEYS[NEVER]),
            "colour": badge_row.get("colour") or COLOURS[NEVER],
            "fmt": {"seen": badge_row.get("seen", 0),
                    "kept": badge_row.get("kept", 0),
                    "dropped": badge_row.get("dropped", 0),
                    "lost": badge_row.get("lost", 0),
                    "since": ago(badge_row.get("since")),
                    "heard": int(source.get("heard") or 0),
                    "why": why(badge_row) or "—"}}
