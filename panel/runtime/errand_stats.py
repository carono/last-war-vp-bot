"""One live number beside an errand — and never a reading taken to get it (#2019).

WHAT IT IS FOR. «Таймеры» lists what the panel does by itself, and until now a row said
only when it last ran and when it runs next. The person asked for the other half: what
the errand is FOR, right now — «сбор ресурсов» with the pile standing uncollected beside
it, so the row answers «стоит ли жать» without opening anything.

THE RULE THIS MODULE EXISTS TO OBEY. `CLAUDE.md`, «Read once, then LISTEN — and nothing
runs in the background unasked»: a line on a block must not cost a question to the game.
There are a dozen blocks on the page and the page is polled, so a stat that read anything
would instantly be the most frequent reading the panel takes — the exact shape the rule
forbids. **Every provider here reads something the panel ALREADY has**: this profile's
own database, a checkpoint a capture child writes anyway, or a cache another page filled
and the wire keeps up to date. Nothing plays a scenario, nothing touches the link, and
nothing subscribes — `BaseResources.cached` exists for precisely that reason.

WHAT AN ERRAND WITHOUT A FREE ANSWER GETS: nothing at all. A blank is honest; a number
bought with a round trip is not, and a number that is quietly hours old is worse than
both. So a stat travels WITH ITS AGE and the phone draws it, and an errand nobody can
answer for free is listed in the task's own report instead of being given a poll.

WHAT A PROVIDER RETURNS::

    {"key": "timers.stat.pending", "fmt": {"n": "377 023"}, "age": 12.4}

`key` is a locale key and `fmt` its placeholders, so nothing here writes a word a person
reads (`CLAUDE.md`, «Not one word of the panel is written in the panel»), and `age` is
seconds since the underlying reading — `None` when the source has no clock of its own
(a day's tally is «today», not «12 seconds ago»).
"""
from __future__ import annotations

import json
import os
import time

#: Milliseconds in a second — the two tile lists stamp `checked_at` on the GAME's clock
#: in ms, and this PC's clock is hours away from it (`tools/lib/game_clock.py`), so the
#: two are never mixed. See :func:`_freshest`.
_MS = 1000.0


# ---------------------------------------------------------------------------
# the sources, each of them free
# ---------------------------------------------------------------------------
def _blob(rt, name: str):
    """One row of this profile's `blobs` table, or `None` — never an exception.

    A stat is a garnish: a profile with no database yet, or one whose store is busy,
    must lose the line and nothing else.
    """
    try:
        return rt.store.blob_get(name)
    except Exception:                    # noqa: BLE001 — a reading, never the page
        return None


def _rows(value) -> list:
    """The rows inside a blob, whichever of the three shapes it is in.

    The ★ list is `{"rows": [...]}` with its own books beside it, the ghost list is a
    bare list, and a hand-mangled one is neither. A stat that guessed would say «0
    целей» over a full list, which reads exactly like «идти некуда».
    """
    if isinstance(value, dict):
        inner = value.get("rows")
        if isinstance(inner, list):
            value = inner
        else:
            value = list(value.values())
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _freshest(rows, now_ms: float) -> "float | None":
    """Seconds since the newest row, or `None` when not one of them says when.

    TWO CLOCKS, deliberately, because the two lists stamp their rows differently and
    subtracting one from the other is hours out: `checked_at` is when the GAME last
    confirmed a tile and it is the game's milliseconds (#1484), while `seen_at` is when
    a sniffer decoded it and it is this PC's epoch SECONDS. Each is judged against its
    own clock (`tools/lib/game_clock.py`), and the freshest of the two answers.
    """
    best = None
    now_s = time.time()
    for row in rows:
        stamp = _int(row.get("checked_at"))
        if stamp:
            age = max(0.0, (now_ms - stamp) / _MS)
        else:
            try:
                seen = float(row.get("seen_at") or 0)
            except (TypeError, ValueError):
                continue
            if not seen:
                continue
            age = max(0.0, now_s - seen)
        if best is None or age < best:
            best = age
    return best


def _file_rows(path: str) -> tuple:
    """`(rows, age)` for a capture checkpoint — `([], None)` when it is not there.

    The checkpoint is written by a child this profile spawned and read here as a FILE:
    its mtime is the age, which is the honest answer to «а не устарело ли» for a file
    that only exists while a capture is running.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return (), None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return (), None
    return tuple(_rows(data)), max(0.0, time.time() - stat.st_mtime)


def _number(value) -> str:
    """A count in the game's own grouping — «377 023», never «377023».

    A thin space, because the panel draws these beside four-figure and seven-figure
    numbers at once and an unbroken run of digits is unreadable at a glance.
    """
    return f"{int(value):,}".replace(",", " ")


# ---------------------------------------------------------------------------
# the providers
# ---------------------------------------------------------------------------
def _pending_resources(rt) -> "dict | None":
    """«+N ждёт сбора» — the pile standing in the base's buildings.

    Straight off the cache the stock card fills and the wire keeps current
    (`panel/runtime/resources.py`): the number is exactly what one press of «Сбор
    ресурсов» would add, the game states it per building, and this is a LOOK at what was
    read rather than a read. A profile nobody has asked the stock of has nothing here,
    and that is the right answer — not a zero.
    """
    try:
        held = rt.resources.cached()
    except Exception:                    # noqa: BLE001 — a reading, never the page
        return None
    rows, age = held.get("rows") or [], held.get("age", -1)
    if not rows or age is None or age < 0:
        return None
    total = sum(_int(row.get("pending")) for row in rows)
    if total <= 0:
        return None
    return {"key": "timers.stat.pending", "fmt": {"n": _number(total)}, "age": age}


def _collect_ready(rt) -> "dict | None":
    """The pile if the stock has been read, else how many BUILDINGS are ready.

    «Сколько ждёт» is the better answer and it comes off the stock cache — which is only
    filled once somebody has looked at the front page. The checklist reading counts the
    buildings with something in store (`base_ready`), and that answers the same question
    a person actually asks — «стоит ли жать» — on a panel where nobody has opened
    anything else.
    """
    pile = _pending_resources(rt)
    if pile is not None:
        return pile
    values, age = _daily(rt)
    if "base_ready" not in values:
        return None
    return {"key": "timers.stat.base_ready",
            "fmt": {"n": _int(values.get("base_ready"))}, "age": age}


def _rally_joins(rt) -> "dict | None":
    """«N стягов сегодня» — today's tally, off the day-keyed store the joiner writes."""
    from .. import rally_limits

    data = _blob(rt, rally_limits.COUNTS_BLOB)
    if not isinstance(data, dict):
        return None
    counts = data.get("counts")
    if not isinstance(counts, dict):
        return None
    total = sum(_int(n) for n in counts.values())
    # A DAY'S TALLY HAS NO AGE, and pretending otherwise would be the wrong kind of
    # honesty: it is «сегодня», complete as of the last join, and a «12 s ago» beside it
    # would say the panel had just looked at something.
    return {"key": "timers.stat.rallies", "fmt": {"n": total}, "age": None}


def _fireworks_taken(rt) -> "dict | None":
    """«N подарков сегодня» — the boxes this account actually took, off the ear's book."""
    from . import firework_wire

    data = _blob(rt, firework_wire.BLOB)
    if not isinstance(data, dict):
        return None
    return {"key": "timers.stat.fireworks",
            "fmt": {"n": _int(data.get("taken"))}, "age": None}


def _ripe(rows, now_ms: float) -> int:
    """How many tiles are worth a robbery RIGHT NOW, by the list's own marks.

    The same three clauses both robbers apply and no more: the tile has finished, its own
    clock has not run out, it is not ours and we have not already taken it. The level
    rule is deliberately NOT applied — that is the standing order's business and it can
    be changed while nobody is looking, whereas this line answers «есть ли вообще что
    брать».
    """
    ripe = 0
    for row in rows:
        if row.get("mine") or row.get("robbed"):
            continue
        done, ends = _int(row.get("completed_at")), _int(row.get("expires_at"))
        if not done or done > now_ms:
            continue
        if ends and ends <= now_ms:
            continue
        cap, looted = _int(row.get("loot_max")), row.get("loot_count")
        if cap and looted is not None and _int(looted) >= cap:
            continue
        ripe += 1
    return ripe


def _secret_targets(rt) -> "dict | None":
    """«N целей ★» — the starred tiles the list is holding, ripe ones counted."""
    from . import store as store_names
    import game_clock

    rows = _rows(_blob(rt, store_names.SECRET_TASKS_STATE))
    if not rows:
        return None
    now_ms = game_clock.now_ms()
    return {"key": "timers.stat.targets",
            "fmt": {"n": _ripe(rows, now_ms), "all": len(rows)},
            "age": _freshest(rows, now_ms)}


def _ghost_targets(rt) -> "dict | None":
    """«N целей» — the ghost squads on the map, by the same three clauses."""
    from . import store as store_names
    import game_clock

    rows = _rows(_blob(rt, store_names.GHOST_MAP_STATE))
    if not rows:
        return None
    now_ms = game_clock.now_ms()
    return {"key": "timers.stat.targets",
            "fmt": {"n": _ripe(rows, now_ms), "all": len(rows)},
            "age": _freshest(rows, now_ms)}


def _treasures(rt) -> "dict | None":
    """«N сундуков» — what the treasure capture last wrote down, with the file's age.

    A checkpoint and not a table on purpose (`CLAUDE.md`): it is worth nothing once the
    capture stops, which is exactly why the age travels with it.
    """
    rows, age = _file_rows(rt.profiles.treasures_json())
    if not rows:
        return None
    return {"key": "timers.stat.chests", "fmt": {"n": len(rows)}, "age": age}



# ---------------------------------------------------------------------------
# the one reading this page is allowed to take (#2019) — see `errand_reads.py`
# ---------------------------------------------------------------------------
def _daily(rt) -> tuple:
    """`(values, age)` of the checklist reading, or `({}, None)` when there is none.

    A LOOK and never a read: the read itself is booked by the route, once a minute at
    most and only while somebody is looking (`panel/runtime/errand_reads.py`). Every
    provider below shares that one round trip, which is why the truck's bubble costs the
    same as the eight lines beside it.
    """
    try:
        held = rt.daily_reads.cached()
    except Exception:                    # noqa: BLE001 — a reading, never the page
        return {}, None
    values, age = held.get("values") or {}, held.get("age", -1)
    if not values or age is None or age < 0:
        return {}, None
    return values, age


def _from_daily(key: str, field: str, *extra):
    """A provider drawing one number (and any companions) out of that one reading."""
    def provider(rt) -> "dict | None":
        values, age = _daily(rt)
        if field not in values:
            return None
        fmt = {"n": _int(values.get(field))}
        for name, other in extra:
            if other not in values:
                return None
            fmt[name] = _int(values.get(other))
        return {"key": key, "fmt": fmt, "age": age}

    return provider


def _visitors(rt) -> "dict | None":
    """Guests at the gate — the recruit queue and the gift queue are one line.

    Two errands draw it and they spend the same queue readings, so «сколько ждёт» is one
    number a person acts on rather than two they have to add up.
    """
    values, age = _daily(rt)
    if "recruit_pending" not in values and "gifts_pending" not in values:
        return None
    total = _int(values.get("recruit_pending")) + _int(values.get("gifts_pending"))
    return {"key": "timers.stat.visitors", "fmt": {"n": total}, "age": age}

def _golden_hunt(rt) -> "dict | None":
    """«412 атак · 6 сегодня» — what the energy still buys, and what today has spent.

    Off the reading «События» already holds and the day's own tally beside it, so the
    line costs the game nothing: an errand nobody can answer for free has no line at
    all, which is this module's whole rule. A profile with the tab switched off, or one
    where nobody has read the board yet, gets `None` rather than a zero that would read
    as «энергии нет».
    """
    tab = rt.tabs.get("events") if rt.tabs is not None else None
    if tab is None:
        return None
    state = tab.golden()
    if state is None or state.attacks is None:
        return None
    today = tab.today() or {}
    return {"key": "timers.stat.golden",
            "fmt": {"n": int(state.attacks),
                    "today": _int(today.get("attacks"))}}


#: Errand name -> what to draw under its block. An errand that is not here draws
#: nothing, and that is a deliberate answer rather than a gap to be filled in with a
#: poll: see the module docstring, and the survey in `docs/research/errand-stats.md`.
PROVIDERS: dict = {
    "collect_base_resources": _pending_resources,
    "rally_auto_join": _rally_joins,
    "rally_monitor": _rally_joins,
    "firework_collect": _fireworks_taken,
    "firework_watch": _fireworks_taken,
    "secret_autoloot": _secret_targets,
    "secret_tasks_day": _secret_targets,
    # «Автопомощь» spends the SAME list — it helps the starred tasks the ★ list
    # holds, so the line under it answers the same question.
    "secret_autoassist": _secret_targets,
    "ghost_autoloot": _ghost_targets,
    "treasure_auto": _treasures,
    # …and the eight that ride on the ONE reading the person allowed (#2019). The truck
    # is the one that was asked for; the rest answer out of the same chunk and cost
    # nothing more than it does.
    "collect_truck_resources": _from_daily("timers.stat.trucks", "trucks_ready"),
    "send_trucks": _from_daily("timers.stat.trucks_out", "trucks_send_left",
                               ("all", "trucks_send_cap")),
    "alliance_help": _from_daily("timers.stat.help", "help_waiting"),
    "donate_alliance_tech": _from_daily("timers.stat.donate", "donate_left"),
    "upgrade_decorations": _from_daily("timers.stat.decor", "decorations"),
    "collect_visitor_gifts": _visitors,
    "recruit_survivors": _visitors,
    # …and the explorer's chests (#2381), which ride on the same reading: how many
    # chests the keys buy right now, with the purse beside it. Both are a dash while
    # the activity is not running, and a dash draws nothing rather than a zero.
    "open_explorer_chests": _from_daily("timers.stat.explorer_chests",
                                        "explorer_chests", ("keys", "explorer_keys")),
    # …and the golden hunt (#2408), which became a row of its own when the person could
    # not find its card: «Не, делаем в таймерах, туда суём её, как обычную карточку».
    "attack_golden_zombies": _golden_hunt,
}


def of(rt, errand: str) -> "dict | None":
    """The line under one errand's block, or `None` when there is nothing free to say."""
    provider = PROVIDERS.get(errand)
    if provider is None:
        return None
    try:
        return provider(rt)
    except Exception:                    # noqa: BLE001 — one line, never the page
        return None
