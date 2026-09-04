"""A squad that is out means SKIP, never wait — the second rule of #2404.

The operator's, in their words: «Если мы отправили отряд по одному сценарию, другой
сценарий, использующий этот же отряд, просто должен перезапуститься позже или пропустить
свою очередь».

It is a different rule from the game claim and it removes a class of waiting the claim
never could. The claim answers «is somebody else DRIVING the client»; this answers «is
the thing I am about to spend already spent», and the two have nothing to do with each
other — a slot may be marching while the client sits idle. Until now the second question
was answered by the recipe, AFTER it had taken the client, sent, and then asked the game
six times over whether a squad had appeared. Measured live: 64 of 122 auto-join runs
spent about thirty seconds each confirming that no squad turned up, because the slot they
were given had gone out with something else minutes before.

FOUR THINGS IT IS NOT, and each is a rule of this repository rather than taste:

* **not a wait.** A held errand returns at once and comes back on its own next tick, or
  on the next push. Nothing is retried in a loop and no clock is armed for it — «read
  once, then LISTEN» is not repaid by inventing a poll to enforce it.
* **not a claim.** It is asked BEFORE the client is claimed
  (`panel/runtime/schedule.py::run_errand`), so an errand that has nothing to send never
  joins the queue at all. That is the whole point: the arms race must not take the link
  in order to find out that its squad is away.
* **not a poll, and it never reads the game itself.** It looks at the reading the panel
  already has (`SquadReader.latest`) and at nothing else. That matters more than it
  looks: a refused errand is PARKED and re-offered whenever the gate might have opened
  (`panel/timers.py::_park_gated`), so a gate that took a reading would turn one held
  errand into a question at the client every few seconds — the background poll this
  repository forbids, invented in the name of the rule against waiting. The reading is
  refreshed by EVENTS instead: a march crossing the wire, and a run that has just spent
  a squad (`panel/runtime/schedule.py`, `SquadReader.refresh_async`).
* **not a stale belief.** A reading older than :data:`FRESH_SEC` is not used at all, and
  neither is a missing one: with nothing recent to go on the errand runs exactly as it
  did before this module existed.
* **not a refusal when it cannot see.** `at_base` answers `None` for «no reading» — no
  client, nothing parsed — and a gate that cannot see must never claim a squad is out.
  An unreadable state runs exactly as it did before this module existed.

WHICH SLOTS AN ERRAND SPENDS IS THE ERRAND'S OWN ARGUMENTS, not a table here. A recipe
that spends squads declares them (`ARGS squads = [1, 2, 3, 4]`, or `ARGS squad = 1`), and
the schedule already builds those values from the squad picker before it runs anything
(`Schedule.args`). So a new ability that picks squads is gated the day it is written, and
nothing here has to learn its name.

**ALL of them, not any.** An errand handed four slots with three of them marching still
has one to send, and skipping it would be inventing a shortage. It is held only when
every slot it was given is away.
"""
from __future__ import annotations

#: The argument names a recipe declares its slots under. Two, because the catalogue has
#: both shapes: `squads` is a list (the rally join, the treasure dig), `squad` is one
#: (the arms race, the golden hunt, a rally raised by hand).
SQUAD_ARGS = ("squads", "squad")

#: How old the panel's squad reading may be and still decide this. A march is minutes
#: and a gather is hours, so a reading from two minutes ago is still about the same
#: journey — but a squad that came home in between must not be held out of its next tick
#: for longer than that. It is a CEILING on a belief, not an interval: nothing here goes
#: and looks when the reading is older, it simply stops answering.
FRESH_SEC = 120.0

#: How many squads a player has. A slot outside it is somebody's typo, not a squad, and
#: is dropped rather than asked about — a reading for slot 9 would answer `None` and turn
#: the whole gate off for that errand.
MAX_SLOT = 4


def slots(args) -> tuple:
    """The squad slots ``args`` names, in order, without repeats.

    Everything that is not a slot number is dropped in silence: these values come from a
    settings page and from an errand's own JSON, and a gate is not the place to fail a run
    over a bad one.
    """
    found: list = []
    for key in SQUAD_ARGS:
        raw = (args or {}).get(key)
        if raw is None:
            continue
        items = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for item in items:
            try:
                slot = int(str(item).strip())
            except (TypeError, ValueError):
                continue
            if 1 <= slot <= MAX_SLOT and slot not in found:
                found.append(slot)
    return tuple(found)


def held(rt, args) -> tuple:
    """The slots this errand may spend that are AWAY — empty when it may run.

    Empty for every case that is not «I know where they are and they are all out»: an
    errand that names no squad, a runtime with no reader, a reading that could not be
    taken, and a set with one slot still standing in the base.
    """
    wanted = slots(args)
    if not wanted:
        return ()
    reader = getattr(rt, "squads", None)
    if reader is None:
        return ()
    try:
        state = reader.latest()
    except Exception:                         # noqa: BLE001 — a reading, never the run
        return ()
    if state is None or not getattr(state, "ok", False):
        return ()                             # nothing has been read ⇒ never refuse
    try:
        if state.age() > FRESH_SEC:
            return ()                         # too old to decide anything with
    except Exception:                         # noqa: BLE001
        return ()
    away: list = []
    for slot in wanted:
        squad = state.squad(slot)
        if squad is None:
            return ()                         # cannot see this one ⇒ never refuse
        if squad.at_base:
            return ()                         # one is home: there is work to do
        away.append(slot)
    return tuple(away)


def said(slots_away) -> str:
    """The slots, for the log line. Numbers only — the words are the locale's."""
    return ", ".join(str(slot) for slot in slots_away)
