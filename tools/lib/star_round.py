"""Which warzones this lap of the star-secret-task round walks, and what it has walked.

## What the round is for

A star secret task is not robbed where it is found: it is found *ripening*. A lap of a
fresh warzone measured live (#1479) brought 91 star tiles of which 86 were still
maturing and 0-5 were raidable that second — so one walk of one warzone is nearly
useless, and the useful thing is to keep FILLING the list all day and let the standing
order («Автолут ★») take each tile the moment it matures.

That is what this module chooses for: a handful of warzones per lap, a different handful
next lap, all day, until the day's five robberies are spent.

## The three rules, and why each one is here

* **Only warzones a robbery is POSSIBLE on.** The slice is `server_list.same_phase` —
  the warzones standing in the same season and the same stage of it as the account's
  own (#1471). Anything else is a warzone the game does not open to us: walking it costs
  a lap and can never produce a robbery.
* **Only warzones having their star day.** The state comes from the profile's book of
  observations and the cycle fitted to it (`panel/runtime/secret_day.py`, #1467).
  Nothing here decides what today is; it is handed the answer.
* **Never the same handful twice in a row.** What has already been walked TODAY is
  written down (:func:`mark`) and taken out of the choice, so a day covers different
  warzones rather than circling the nearest five. When the available ones run out the
  circle starts again on purpose — the tiles walked three hours ago have ripened since.

**HOME IS NEVER WALKED.** The account's own warzone is not a robbery target at all
(«не грабить на своём сервере», #1188), so a lap of it fills the list with tiles the
standing order is forbidden to take.

## Where the round's memory lives

In the profile's database, as one named row of `blobs` (:data:`BLOB`) — read and written
whole, never queried by a `WHERE` clause, which is exactly what that table is for
(`CLAUDE.md`, «Game data lives only in the database»). It is keyed by the GAME day
(`secret_day.day_index`), so a day that turns over while the panel is running empties it
by itself and nothing has to be cleaned up.

Pure arithmetic and one small store: no game read, no Tk, no panel import — so the whole
rule is testable without a client (`tests/test_star_round.py`).
"""
from __future__ import annotations

#: The named row of the profile's `blobs` table this round keeps its memory in.
BLOB = "star_round_state"

#: How many warzones one lap may walk, at the least and at the most. The operator's own
#: bounds («5-10 серверов за заход»): fewer than five is not worth the round trip of
#: starting a round, and more than ten is a minute of camera walking during which the
#: standing order is looking at a list nobody is adding to.
COUNT_MIN = 5
COUNT_MAX = 10

#: The star-day state a warzone must be in to be worth walking. Spelled here rather than
#: imported so this module stays free of everything — it is the same string
#: `secret_day.STATE_DAY` carries, and `tests/test_star_round.py` pins the two together.
STATE_DAY = "day"


def clamp_count(count) -> int:
    """How many warzones a lap walks, held inside the operator's own bounds."""
    try:
        wanted = int(count)
    except (TypeError, ValueError):
        wanted = COUNT_MIN
    return max(COUNT_MIN, min(COUNT_MAX, wanted))


def choose(slice_ids, states, home, walked, count) -> dict:
    """Pick this lap's warzones out of the ones a robbery is possible on.

    `slice_ids`  the warzones in reach (`server_list.same_phase`)
    `states`     `{warzone: star-day state}` as the profile's book answers today
    `home`       the account's own warzone — excluded, never a target
    `walked`     what this game-day has already walked
    `count`      how many are wanted (clamped to :data:`COUNT_MIN`/:data:`COUNT_MAX`)

    Comes back as `{"servers": [...], "pool": n, "fresh": n, "cycled": bool}`:
    which to walk, how many warzones are having their star day at all, how many of those
    had not been walked yet, and whether the circle had to be started again.

    **Nearest to home first**, and that is not decoration: distance in warzone numbers
    tracks how likely the game is to let a march happen at all, and the ones next door
    are the ones a robbery has already been proven on.
    """
    try:
        centre = int(home or 0)
    except (TypeError, ValueError):
        centre = 0
    seen = {int(s) for s in (walked or ())}
    pool = [int(s) for s in (slice_ids or ())
            if int(s) != centre and str(states.get(int(s)) or "") == STATE_DAY]
    fresh = [s for s in pool if s not in seen]
    cycled = False
    if not fresh and pool:
        # THE CIRCLE STARTS AGAIN, rather than the round going quiet for the rest of the
        # day. Everything available has been walked once; the tiles found on the first
        # lap have been ripening since, and the whole point of coming back is to catch
        # them mature (#1479).
        fresh = list(pool)
        cycled = True
    order = sorted(fresh, key=lambda s: (abs(s - centre) if centre else s, s))
    return {"servers": order[:clamp_count(count)], "pool": len(pool),
            "fresh": len(fresh), "cycled": cycled}


# ---------------------------------------------------------------------------
# the round's memory — one row of the profile's `blobs` table
# ---------------------------------------------------------------------------
def load(store) -> dict:
    """What the round remembers, as `{"day": n, "walked": [...], "laps": n}`.

    Anything unreadable — no store, no row yet, junk from a hand edit — is a round that
    has walked nothing, which is the safe answer: a lap too many costs a few seconds of
    camera and a lap missed costs a day's robberies.
    """
    raw = None
    if store is not None:
        try:
            raw = store.blob_get(BLOB)
        except Exception:                     # noqa: BLE001 — a memory, never the run
            raw = None
    if not isinstance(raw, dict):
        return {"day": 0, "walked": [], "laps": 0}
    walked = []
    for item in raw.get("walked") or ():
        try:
            walked.append(int(item))
        except (TypeError, ValueError):
            continue
    try:
        day = int(raw.get("day") or 0)
    except (TypeError, ValueError):
        day = 0
    try:
        laps = int(raw.get("laps") or 0)
    except (TypeError, ValueError):
        laps = 0
    return {"day": day, "walked": walked, "laps": laps}


def walked_on(state, day) -> list:
    """What was walked on that game-day — empty when the day has turned over.

    The day is part of the record rather than a thing that gets reset: a panel that was
    shut over midnight, or one whose day boundary moved when the client finally answered
    `GetTomorrowZero`, then reads yesterday's list as what it is instead of as today's.
    """
    if int((state or {}).get("day") or 0) != int(day):
        return []
    return list((state or {}).get("walked") or ())


def mark(store, day, server) -> dict:
    """Write down that this game-day has walked `server`. Returns the new memory.

    Called as each warzone is taken off the lap's queue rather than after its lap, and
    that is deliberate: a run that dies half way has still SENT the camera there, and the
    warzone it was walking is the one it would otherwise repeat first on the retry. The
    cost of the other way round is a day spent re-walking one warzone; the cost of this
    way is one warzone skipped until the circle comes round, which it does.
    """
    state = load(store)
    day = int(day)
    if state["day"] != day:
        state = {"day": day, "walked": [], "laps": 0}
    server = int(server)
    if server not in state["walked"]:
        state["walked"].append(server)
    if store is not None:
        try:
            store.blob_set(BLOB, state)
        except Exception:                     # noqa: BLE001 — a memory, never the run
            pass
    return state


def note_lap(store, day, cycled=False) -> dict:
    """Count one lap of the round, and empty the memory when the circle restarted.

    `cycled` is :func:`choose`'s own verdict — everything available had been walked, so
    this lap is the second (or fifth) time round and the record of the first is what the
    NEXT lap must not be filtered by.
    """
    state = load(store)
    day = int(day)
    if state["day"] != day:
        state = {"day": day, "walked": [], "laps": 0}
    if cycled:
        state["walked"] = []
    state["laps"] = int(state.get("laps") or 0) + 1
    if store is not None:
        try:
            store.blob_set(BLOB, state)
        except Exception:                     # noqa: BLE001 — a tally, never the run
            pass
    return state
