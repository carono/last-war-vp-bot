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

WHAT AN ERRAND WITHOUT A FREE ANSWER GETS: the truth, in words. A number bought with a
round trip is not honest, and one that is quietly hours old is worse still — so a stat
travels WITH ITS AGE and the phone draws it. What changed in #2579 is only that the
blank became a SENTENCE: a row with no reading falls back on the panel's own count of
today's runs, and one that has not even that says «живого показания нет». An empty line
under a card cannot be told from a card whose reading is broken, and the person asked for
cards that show work is happening — «карточки должны быть живыми, чтобы было видно, что
работа идет». Still nothing here asks the game.

WHAT A PROVIDER RETURNS::

    {"key": "timers.stat.pending", "fmt": {"n": "377 023"}, "age": 12.4}

`key` is a locale key and `fmt` its placeholders, so nothing here writes a word a person
reads (`CLAUDE.md`, «Not one word of the panel is written in the panel»), and `age` is
seconds since the underlying reading — `None` when the source has no clock of its own
(a day's tally is «today», not «12 seconds ago»).
"""
from __future__ import annotations

import contextlib
import functools
import json
import os
import threading
import time

#: Milliseconds in a second — the two tile lists stamp `checked_at` on the GAME's clock
#: in ms, and this PC's clock is hours away from it (`tools/lib/game_clock.py`), so the
#: two are never mixed. See :func:`_freshest`.
_MS = 1000.0


# ---------------------------------------------------------------------------
# the sources, each of them free
# ---------------------------------------------------------------------------
#: ONE PAGE'S WORTH OF READINGS (#2660). `/api/timers` walks every errand and asks each
#: one for its line, and several of those lines come off the SAME blob — the star list is
#: read by the auto-loot row and by the star round, the ghost map by two more. Each read
#: is a SELECT and a JSON parse of a list that can be thousands of rows, and the phone
#: asks for this page on its ordinary poll. Inside a :func:`batch` each blob is read once.
#: Thread-local, because two front-ends ask at the same time and a profile's store is its
#: own; and scoped to the call rather than kept, because a cache with a lifetime would be
#: a second, staler copy of the database.
_BATCH = threading.local()


@contextlib.contextmanager
def batch():
    """Read each blob once for the length of this block. Re-entrant, never required."""
    outer = getattr(_BATCH, "cache", None)
    _BATCH.cache = {} if outer is None else outer
    try:
        yield
    finally:
        _BATCH.cache = outer


def batched(func):
    """Run `func` inside a :func:`batch` — for a caller that walks every errand."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with batch():
            return func(*args, **kwargs)
    return wrapper


def _blob(rt, name: str):
    """One row of this profile's `blobs` table, or `None` — never an exception.

    A stat is a garnish: a profile with no database yet, or one whose store is busy,
    must lose the line and nothing else.
    """
    cache = getattr(_BATCH, "cache", None)
    key = (id(rt), str(name))
    if cache is not None and key in cache:
        return cache[key]
    try:
        value = rt.store.blob_get(name)
    except Exception:                    # noqa: BLE001 — a reading, never the page
        value = None
    if cache is not None:
        cache[key] = value
    return value


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


def _golden_hunt(rt) -> "dict | None":
    """«412 атак · 6 сегодня» — what the energy still buys, and what today has spent.

    …or, while «Вторжение зомби» is not running, that fact and when the next window is:
    a purse nobody can spend is not news (#2647).

    Off the reading «События» already holds and the day's own tally beside it, so the
    line costs the game nothing: an errand nobody can answer for free has no line at
    all, which is this module's whole rule. A profile with the tab switched off, or one
    where nobody has read the board yet, gets `None` rather than a zero that would read
    as «энергии нет».
    """
    # THE EVENT FIRST, AND IT OUTRANKS THE PURSE (#2647). The golden zombies are
    # «Вторжение зомби»'s own monsters: outside its window the energy line is true and
    # useless, and a card promising «412 атак» while every run stops at the gate is
    # exactly the «работает и без события» the person reported. The reading is
    # `invasion_live` — the client entering the game, the invasion's own record, and
    # each hunt run; never a clock — and it carries its age like every other.
    from . import invasion_live

    inv, inv_age = invasion_live.state(rt)
    if inv and inv_age is not None and not inv.get("open"):
        day, next_day = _int(inv.get("day")), _int(inv.get("next_day"))
        if next_day > day > 0:
            return {"key": "timers.stat.golden.closed",
                    "fmt": {"day": next_day, "left": next_day - day}, "age": inv_age}
        return {"key": "timers.stat.golden.off", "fmt": {}, "age": inv_age}
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


def _runs_today(rt, errand: str) -> "dict | None":
    """«Сегодня: 3 раза» — the panel's own record of its own schedule (#2579).

    THE LAST FREE ANSWER THERE IS, and the reason it exists: the person asked for cards
    that show work is happening — «карточки должны быть живыми, чтобы было видно, что
    работа идет» — and a dozen errands have nothing the game will count for us. What the
    panel does know, without asking anything, is how many times it ran the errand since
    the SERVER's midnight, because it writes that down as it goes (`panel/timers.py`,
    `LastRunStore.mark_run`).

    It is deliberately weaker than the readings above and always loses to them: «сколько
    осталось» is what a person acts on, «сколько раз запускали» is only proof the row is
    alive. A row that is not a timer at all — a listener, a standing order — has no such
    record and gets `None`, which the caller turns into the honest line.
    """
    try:
        schedule = rt.schedule
        if errand not in {t.name for t in schedule.timer_catalogue}:
            return None
        runs = int(schedule.store.runs_today(errand))
    except Exception:                    # noqa: BLE001 — a reading, never the page
        return None
    if runs <= 0:
        return {"key": "timers.stat.today_none", "fmt": {}, "age": None}
    return {"key": "timers.stat.today", "fmt": {"n": runs}, "age": None}


def _with_today(rt, errand: str, stat: "dict | None") -> "dict | None":
    """Put today's run count into a line that has a `{today}` slot for it."""
    if stat is None:
        return None
    try:
        runs = int(rt.schedule.store.runs_today(errand))
    except Exception:                    # noqa: BLE001
        runs = 0
    stat["fmt"]["today"] = runs
    return stat


def _trucks_send(rt) -> "dict | None":
    """«2 из 4 · 1 готов» — dispatches left today and the trucks standing ready.

    The person asked for this row by name: «отправка грузовиков, нужно написать, сколько
    осталось рейсов, сколько в пути». What the client answers for free is the two halves
    of the quota and how many trucks could go out RIGHT NOW (`trucks_idle`) — the
    difference between the two is what is on the road, and it is drawn as «готовы» rather
    than «в пути» because that is the number the reading actually is.

    «ВОЗВРАЩЁННЫХ N» joins it when there is one (#2605): the day-pools behind the trade
    station's «Вернуть», holding what trucks earned and nobody took. It is only drawn when
    it is not zero — a permanent «возвращённых 0» is noise on every card every day, and
    the number matters exactly when it is not zero.
    """
    values, age = _daily(rt)
    if "trucks_send_left" not in values or "trucks_send_cap" not in values:
        return None
    fmt = {"n": _int(values.get("trucks_send_left")),
           "all": _int(values.get("trucks_send_cap"))}
    back = _int(values.get("recover_trucks"))
    if "trucks_idle" not in values:
        if back:
            fmt["back"] = back
            return {"key": "timers.stat.trucks_out_back", "fmt": fmt, "age": age}
        return {"key": "timers.stat.trucks_out", "fmt": fmt, "age": age}
    fmt["ready"] = _int(values.get("trucks_idle"))
    if back:
        fmt["back"] = back
        return {"key": "timers.stat.trucks_send_back", "fmt": fmt, "age": age}
    return {"key": "timers.stat.trucks_send", "fmt": fmt, "age": age}


def _gifts_waiting(rt) -> "dict | None":
    """«Подарки выжившего»: guests bearing one, and how many runs took them today.

    Split from `recruit_survivors` in #2579 — the two used to share one number, and the
    person asked each card for its own: «Подарки выжившего, нужно писать, сколько
    выживших ждет, сколько сегодня собрали. Сбор выживших аналогично.»
    """
    values, age = _daily(rt)
    if "gifts_pending" not in values:
        return None
    return _with_today(rt, "collect_visitor_gifts",
                       {"key": "timers.stat.gifts_waiting",
                        "fmt": {"n": _int(values.get("gifts_pending"))}, "age": age})


def _recruit_waiting(rt) -> "dict | None":
    """«Сбор выживших»: survivors standing in the queues, and today's runs."""
    values, age = _daily(rt)
    if "recruit_pending" not in values:
        return None
    return _with_today(rt, "recruit_survivors",
                       {"key": "timers.stat.recruit_waiting",
                        "fmt": {"n": _int(values.get("recruit_pending"))}, "age": age})


def _ministry(rt) -> "dict | None":
    """«Министр сейчас · сегодня 2» — the post held, and how often it was won today.

    «Министр внутренних дел, сколько раз был министром сегодня» has no counter in the
    game: what there is, is the post held right now (`ministry_post`) and the panel's own
    record of the applications that went through since the reset — a run of this errand
    only succeeds when the application took (`actions/apply_ministry_interior.md`), so
    the count is exactly «сколько раз был министром сегодня».
    """
    values, age = _daily(rt)
    if "ministry_post" not in values:
        return _runs_today(rt, "apply_ministry_interior")
    key = ("timers.stat.ministry_held" if _int(values.get("ministry_post")) > 0
           else "timers.stat.ministry_free")
    return _with_today(rt, "apply_ministry_interior",
                       {"key": key, "fmt": {}, "age": age})


def _tavern(rt) -> "dict | None":
    """«Бесплатных: 2 · сегодня 1» — pulls waiting, and runs that took them today."""
    values, age = _daily(rt)
    if "tavern_free" not in values:
        return _runs_today(rt, "tavern_free_pull")
    return _with_today(rt, "tavern_free_pull",
                       {"key": "timers.stat.tavern",
                        "fmt": {"n": _int(values.get("tavern_free"))}, "age": age})


def _steals(rt) -> "dict | None":
    """«Осталось 3 из 5 · взято 2» — the day's secret-task robberies.

    «Секретки за день, сколько осталось, сколько собрал», and both halves come out of the
    one reading: the cap the game states and what is left of it.

    …and «возвращённых N» beside them when the command post's own «Вернуть» is holding
    day-pools nobody has claimed (#2605), on the same terms as the trucks': drawn only
    when it is not zero.
    """
    values, age = _daily(rt)
    if "steal_left" not in values or "steal_cap" not in values:
        return None
    left, cap = _int(values.get("steal_left")), _int(values.get("steal_cap"))
    fmt = {"n": left, "all": cap, "done": max(0, cap - left)}
    back = _int(values.get("recover_tasks"))
    if back:
        fmt["back"] = back
        return {"key": "timers.stat.steals_back", "fmt": fmt, "age": age}
    return {"key": "timers.stat.steals", "fmt": fmt, "age": age}


def _ghost_steals(rt) -> "dict | None":
    """The ghost quota while the event is on, and «сегодня не проводится» when it is not.

    A number over a shut event is worse than no line: «Операция Призрак» runs one day a
    week, and its two counts mean nothing on the other six (`read_daily_checklist.md`).
    """
    values, age = _daily(rt)
    if "ghost_open" not in values:
        return None
    if not _int(values.get("ghost_open")):
        return {"key": "timers.stat.ghost_closed", "fmt": {}, "age": age}
    if "ghost_left" not in values or "ghost_cap" not in values:
        return None
    left, cap = _int(values.get("ghost_left")), _int(values.get("ghost_cap"))
    return {"key": "timers.stat.steals",
            "fmt": {"n": left, "all": cap, "done": max(0, cap - left)}, "age": age}


def _hospital(rt) -> "dict | None":
    """Wounded waiting, or a finished heal standing uncollected — one line for both."""
    values, age = _daily(rt)
    if "wounded" not in values:
        return None
    hurt = _int(values.get("wounded"))
    if not hurt and _int(values.get("healed_ready")):
        return {"key": "timers.stat.healed", "fmt": {}, "age": age}
    return {"key": "timers.stat.wounded", "fmt": {"n": hurt}, "age": age}


def _radar(rt) -> "dict | None":
    """«Мест: 3 · помочь: 2» — room on the board and the errands needing no march."""
    values, age = _daily(rt)
    if "radar_free" not in values and "radar_helpable" not in values:
        return None
    return {"key": "timers.stat.radar",
            "fmt": {"n": _int(values.get("radar_free")),
                    "help": _int(values.get("radar_helpable"))}, "age": age}


def _alliance_star(rt) -> "dict | None":
    """«Лайков 14 из 14 · сундуков 2 из 2» — the week's ceremony, off the one reading.

    Four more fields in the chunk «Таймеры» already asks for (#2584), so the card costs
    the game nothing: whether a ceremony is running, how many stars are on its board, how
    many of them carry a like of ours, and how many of the two chests have been taken.

    A ceremony that is not running says so in words — the event is held one day a week
    and a «0 из 0» on the other six reads as a broken card rather than as a shut event,
    which is the same distinction `_ghost_steals` makes. A client that has never been
    told about a ceremony at all answers a dash, and a dash is `None` here: the row then
    falls back on the panel's own count of today's runs.
    """
    values, age = _daily(rt)
    if "alstar_open" not in values:
        return None
    if not _int(values.get("alstar_open")):
        return {"key": "timers.stat.alliance_star_closed", "fmt": {}, "age": age}
    if "alstar_stars" not in values:
        return None
    return {"key": "timers.stat.alliance_star",
            "fmt": {"n": _int(values.get("alstar_liked")),
                    "all": _int(values.get("alstar_stars")),
                    "chests": _int(values.get("alstar_chests")),
                    "boxes": 2},
            "age": age}


def _alliance_gifts(rt) -> "dict | None":
    """«ждут: 51 · обычных 6 · премиальных 45» — the alliance chests, off the one reading.

    Two more fields of the chunk «Таймеры» already asks for (#2588), so the line costs
    the game nothing, and the day's take beside them off the panel's own book. They are a dash — and a dash is `None` here — until somebody has
    asked the server for the gift list at all: a client that has never asked holds no
    gift records, and a «0 подарков» over that is the one lie this line exists to
    prevent. `collect_alliance_gifts` does the asking, and the server's own
    `push.alliance.reward.new` keeps the counts up to date afterwards.
    """
    from . import gift_book
    values, age = _daily(rt)
    if "algift_ord" not in values or "algift_prem" not in values:
        return None
    ordinary, premium = _int(values.get("algift_ord")), _int(values.get("algift_prem"))
    return {"key": "timers.stat.alliance_gifts",
            "fmt": {"n": ordinary + premium, "ord": ordinary, "prem": premium,
                    # …and what the DAY took, which is gifts and not runs: the recipe
                    # counts the unclaimed gifts before and after its claim, and the
                    # book keeps the difference (`panel/runtime/gift_book.py`).
                    "today": gift_book.today(rt)},
            "age": age}


def _timer_args(rt, errand: str) -> dict:
    """One errand's `args` block, or `{}` — the row is where its knobs live (#2597)."""
    try:
        for timer in rt.schedule.timer_catalogue:
            if timer.name == errand:
                return dict(timer.args or {})
    except Exception:                    # noqa: BLE001 — a reading, never the page
        return {}
    return {}


def _hidden_treasures(rt) -> "dict | None":
    """«Очков 750 из 6000 · копок в запасе 12 · до цели ещё 17» — the week's board.

    Off the ONE reading «Таймеры» already takes (`errand_reads.py`), so the card that
    replaced the old page costs the game nothing. «До цели» is the distance divided by
    what one dig pays on average — the row's own `pay`, the same number the recipe plans
    with — and never «сколько копок возможно», which is `digs` and is drawn beside it.

    A week that is over says so in words: a «0 из 6000» over a shut event reads as a
    broken card rather than as nothing to do, which is the distinction `_ghost_steals`
    makes for the same reason. And the score LAGS on purpose — the compasses a dig pays
    do not reach the client's own count until it is restarted
    (`docs/research/hidden-treasures.md`) — which is why the age travels with the line.
    """
    values, age = _daily(rt)
    if "hidden_score" not in values or "hidden_goal" not in values:
        return None
    if not _int(values.get("hidden_open"), 1):
        return {"key": "timers.stat.hidden_closed", "fmt": {}, "age": age}
    args = _timer_args(rt, "dig_hidden_treasures")
    cap = _int(values.get("hidden_goal"))
    goal = _int(args.get("goal"))
    if goal <= 0 or (cap > 0 and goal > cap):
        goal = cap
    score = _int(values.get("hidden_score"))
    pay = max(1, _int(args.get("pay"), 1) or 1)
    short = max(0, goal - score)
    return _with_today(rt, "dig_hidden_treasures",
                       {"key": "timers.stat.hidden",
                        "fmt": {"n": score, "all": goal,
                                "digs": _int(values.get("hidden_digs")),
                                "left": -(-short // pay)}, "age": age})


def _arms_chests(rt) -> "dict | None":
    """«Сундуков сегодня: 9 · фаз: 3» — what «Гонка вооружений» has paid today.

    Off the day's own book (`panel/runtime/arms_book.py`), which is the panel writing
    down what the GAME said while each phase was running: the client keeps no history of
    a phase that has ended, so this is the only free answer there is — and it is free,
    because every entry in it was an answer that had already arrived.

    A book with nothing in it draws no line rather than a zero: «0 сундуков» over a day
    nobody has read is «мы не смотрели», and the two must not look the same.
    """
    from . import arms_book

    chests, seen, age = arms_book.total(rt)
    if not seen:
        return None
    return {"key": "timers.stat.arms",
            "fmt": {"n": chests, "phases": seen}, "age": age}


#: Errand name -> what to draw under its block. An errand that is not here draws
#: nothing, and that is a deliberate answer rather than a gap to be filled in with a
#: poll: see the module docstring, and the survey in `docs/research/errand-stats.md`.
def _arena(rt) -> "dict | None":
    """The arena: WHICH event the building is running, and how the account stands (#2688).

    The person asked for both in those words — «пусть в карточке будет написано, какая
    сейчас арена активна и счет нужен» — and the two arenas do not count the same thing,
    so neither is made to look like the other: the 3v3 challenge's day is counted in
    WINS and the storm arena's in BATTLES (`docs/research/arena-3v3.md` §4).

    The reading is `panel/runtime/arena_live.py` — taken when the client got into the
    game and then at the event's own end or the day's reset, never on a clock — so this
    line costs nothing and carries its own AGE, which is what makes a stale number
    honest rather than wrong.

    `done` is a dash on the 3v3 until a battle has answered, and the target is the
    errand's own `wins` argument rather than a number invented here: the server does not
    carry one, and the row is where that knob lives.
    """
    from . import arena_live

    fields, age = arena_live.state(rt)
    if age is None:
        return None
    which = str(fields.get("which") or "")
    if which == "none":
        return {"key": "timers.stat.arena.closed", "fmt": {}, "age": age}
    if which not in ("3v3", "storm"):
        return None
    dash = "—"
    score = fields.get("score")
    rank = fields.get("rank")
    done = fields.get("done")
    left = fields.get("left")
    if which == "storm":
        need = fields.get("need")
        return {"key": "timers.stat.arena.storm",
                "fmt": {"score": score if score is not None else dash,
                        "rank": rank if rank is not None else dash,
                        "done": done if done is not None else dash,
                        "need": need if need is not None else dash,
                        "left": left if left is not None else dash},
                "age": age}
    return {"key": "timers.stat.arena.3v3",
            "fmt": {"score": score if score is not None else dash,
                    "rank": rank if rank is not None else dash,
                    "done": done if done is not None else dash,
                    "need": _int(_timer_args(rt, "arena_3v3_battles").get("wins"), 5),
                    "left": left if left is not None else dash},
            "age": age}


def _shop_likes(rt) -> "dict | None":
    """The free diamonds the two arenas pay for a LIKE, on the card that takes them (#2689).

    The person put the likes on «Магазин: бесплатное» themselves, and asked the card to
    say what is left of them on BOTH arenas — «3 раза там и 3 раза там». So the line is
    the two counts the server keeps, and when both are spent it says the day's diamonds
    are in rather than drawing two zeros nobody can read.

    The reading is `panel/runtime/arena_live.py` — taken when the client got into the
    game, at the day's reset and on the answer to a like — so this line costs nothing and
    carries its own AGE, which is what makes a stale number honest rather than wrong.
    """
    from . import arena_live

    fields, age = arena_live.state(rt)
    if age is None:
        return None
    storm = fields.get("like_storm")
    three = fields.get("like_three")
    if storm is None and three is None:
        return None
    if storm == 0 and three == 0:
        return {"key": "timers.stat.shop.likes_done", "fmt": {}, "age": age}
    dash = "—"
    return {"key": "timers.stat.shop.likes",
            "fmt": {"storm": storm if storm is not None else dash,
                    "three": three if three is not None else dash},
            "age": age}


def _market(rt) -> "dict | None":
    """«Сверкающий рынок»: what is free right now, off the last reading (#2636).

    The reading is `panel/runtime/market_live.py` — taken when the client got into the
    game and on the event's own push, never on a clock — so this line costs nothing and
    carries its own AGE, which is what makes a stale number honest rather than wrong.
    """
    from . import market_live

    fields, age = market_live.state(rt)
    if age is None:
        return None
    if not fields.get("open"):
        return {"key": "timers.stat.market.closed", "fmt": {}, "age": age}
    free, goods = _int(fields.get("free")), _int(fields.get("goods_free"))
    boxes = _int(fields.get("boxes_due"))
    if free:
        return {"key": "timers.stat.market.free",
                "fmt": {"item": fields.get("free_item") or "?",
                        "n": goods + boxes}, "age": age}
    if goods or boxes:
        return {"key": "timers.stat.market.goods",
                "fmt": {"n": goods + boxes}, "age": age}
    return {"key": "timers.stat.market.done", "fmt": {}, "age": age}


def _market_coins(rt) -> "dict | None":
    """«Сверкающий рынок»: the coins in the bag and how many rows are still on sale."""
    from . import market_live

    fields, age = market_live.state(rt)
    if age is None:
        return None
    if not fields.get("open"):
        return {"key": "timers.stat.market.closed", "fmt": {}, "age": age}
    return {"key": "timers.stat.market.coins",
            "fmt": {"coins": _int(fields.get("coins")),
                    "n": _int(fields.get("priced_rows"))}, "age": age}


PROVIDERS: dict = {
    "collect_base_resources": _pending_resources,
    "rally_auto_join": _rally_joins,
    "rally_monitor": _rally_joins,
    "firework_collect": _fireworks_taken,
    "firework_watch": _fireworks_taken,
    "secret_autoloot": _secret_targets,
    # «Секретки за день» is the QUOTA rather than the map (#2579): what the day has left
    # of the five and what has already been taken. The ★ autoloot keeps the list, because
    # that is the question that row is about.
    "secret_tasks_day": _steals,
    # «Автопомощь» spends the SAME list — it helps the starred tasks the ★ list
    # holds, so the line under it answers the same question.
    "secret_autoassist": _secret_targets,
    "ghost_autoloot": _ghost_targets,
    "treasure_auto": _treasures,
    # …and the eight that ride on the ONE reading the person allowed (#2019). The truck
    # is the one that was asked for; the rest answer out of the same chunk and cost
    # nothing more than it does.
    "collect_truck_resources": _from_daily("timers.stat.trucks", "trucks_ready"),
    "send_trucks": _trucks_send,
    "alliance_help": _from_daily("timers.stat.help", "help_waiting"),
    "donate_alliance_tech": _from_daily("timers.stat.donate", "donate_left"),
    "upgrade_decorations": _from_daily("timers.stat.decor", "decorations"),
    # …and the two that used to SHARE a number and now each have their own (#2579).
    "collect_visitor_gifts": _gifts_waiting,
    "recruit_survivors": _recruit_waiting,
    # …and the explorer's chests (#2381), which ride on the same reading: how many
    # chests the keys buy right now, with the purse beside it. Both are a dash while
    # the activity is not running, and a dash draws nothing rather than a zero.
    "open_explorer_chests": _from_daily("timers.stat.explorer_chests",
                                        "explorer_chests", ("keys", "explorer_keys")),
    # …and the golden hunt (#2408), which became a row of its own when the person could
    # not find its card: «Не, делаем в таймерах, туда суём её, как обычную карточку».
    "attack_golden_zombies": _golden_hunt,
    # …and the two cards of «Сверкающий рынок» (#2636). Both off ONE reading kept by
    # `panel/runtime/market_live.py`, which is taken on the client entering the game and
    # on the event's own push — no clock, and no «Обновить» anywhere.
    "collect_glittering_market": _market,
    # …and the free diamonds the arenas pay for a like, on the card the person asked for
    # them on (#2689). Same reading as the arena card, no question of its own.
    "collect_shop_freebies": _shop_likes,
    "buy_glitter_market_goods": _market_coins,
    # …and the arena building (#2688), whose card had to say WHICH of the two events is
    # in it: the row is named for the 3v3 challenge only because renaming a timer throws
    # away the schedule somebody set on it, and its scenario plays whichever is open.
    "arena_3v3_battles": _arena,
    # …and the rows #2579 gave a line to, every one of them off the SAME reading the
    # eight above ride on or off the panel's own record — not one new question.
    "heal_units": _hospital,
    "occupation_skills": _from_daily("timers.stat.skills", "skills_ready"),
    "apply_ministry_interior": _ministry,
    "tavern_free_pull": _tavern,
    "do_radar_tasks": _radar,
    "do_radar_marches": _radar,
    "radar_full_cycle": _radar,
    "ghost_recon_alliance": _ghost_steals,
    "mail_gifts": _from_daily("timers.stat.mail", "mail_gifts"),
    # …and the arms race, whose day the panel books itself because the game forgets a
    # phase the moment it ends (#2579).
    "perform_arms_race": _arms_chests,
    # …and the week's ceremony (#2584), whose two numbers ride on the same reading.
    "work_alliance_star": _alliance_star,
    # …and the alliance chests, read rather than collected blind (#2588).
    "collect_alliance_gifts": _alliance_gifts,
    # …and the hidden treasures (#2597), whose page became a card on this board: the
    # week's compasses and the digs the bag still holds, off the same reading.
    "dig_hidden_treasures": _hidden_treasures,
    "alliance_star_ceremony": _alliance_star,
    # …the listener that watches the same pile the errand collects, and the one that
    # watches the same chests.
    "resource_tracker": _pending_resources,
    "explorer_chests": _from_daily("timers.stat.explorer_chests",
                                   "explorer_chests", ("keys", "explorer_keys")),
}


def of(rt, errand: str) -> "dict | None":
    """The line under one errand's block — and never a blank one (#2579).

    Three answers, strongest first, because the person asked that every card say
    something: what the errand is FOR right now, else how many times the panel ran it
    today, else — for a listener or a standing order, which keep no such record — the
    honest sentence that there is nothing free to say. None of the three costs a question
    to the game, which is the rule this module exists to obey.
    """
    provider = PROVIDERS.get(errand)
    if provider is not None:
        try:
            stat = provider(rt)
        except Exception:                # noqa: BLE001 — one line, never the page
            stat = None
        if stat is not None:
            return stat
    runs = _runs_today(rt, errand)
    if runs is not None:
        return runs
    return {"key": "timers.stat.none", "fmt": {}, "age": None}
