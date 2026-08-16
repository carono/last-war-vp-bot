#!/usr/bin/env python3
r"""The star-secret-task day of a warzone — three states, and a schedule that is DERIVED.

## What the question is

The game runs a day on which star (`is_special`) secret tasks are handed out in numbers,
and the day after it they still come but far more rarely. Neighbouring warzones are on
the same cycle at different points: a run of consecutive ids has the day, the next couple
are on the day after it, and the ones after that are on ordinary days. So «is it the star
day» is a function of BOTH the warzone and the date — never a single global answer — and
there are **three** states rather than two:

    day    the star day itself
    post   the day after — star tasks still appear, noticeably less often
    plain  an ordinary day

The middle one is the one that matters in practice: it decides whether a monitor is worth
running, and a yes/no answer describes it wrongly whichever way it is rounded.

## Where the answer comes from — and where it does NOT

**The client does not ship this schedule.** Its config tables were read out of a live
client for this (task #1467, `docs/research/secret-task-day.md`): `lw_dispatch_settings`
keys the star-task COUNTS by base level and season, `lw_dispatch_tasks` is the pool of
task templates, `calendar` / `activity_clock` / `activity_calendargroup` are the entrance
buttons of the events screen, and none of the 742 tables carries a per-day, per-warzone
plan. What the client is TOLD is its own warzone's activity list, and that list is for
the warzone the account stands in and no other (`docs/research/server-events.md`).

So this module is the other half of the task's instruction: **when the fact is not in the
data, keep a schedule of our own — but keep it DERIVED, never typed in.** Observations go
in («on warzone X, on day Y, it was Z»), a cycle comes out, and everything the panel shows
says which of the two it is looking at.

## The model

One cycle, shared by every warzone, of a length nobody here decides: a word of states
`pattern` of length `period`, and a per-warzone `offset` into it. A warzone with no
observations of its own borrows the offset of the NEAREST one by number — that is the
whole content of «neighbouring warzones run the same cycle, shifted», and it is reported
as a borrowing (`neighbour`) rather than passed off as knowledge.

Both the period and the offsets are FITTED to the observations (:func:`fit`). Nothing in
this file knows a real warzone number, a real date or a real period, and no example here
is a live reading — the numbers in the tests are invented and shaped like the real thing.

## Saying it is wrong out loud

An observation is never overwritten by a prediction, and a prediction that disagrees with
an observation is not quietly dropped: :func:`conflicts` returns every one of them, and
both front-ends show the count. A schedule that has started to lie says so.

Nothing here touches Tk, the panel, the game or a database: it is arithmetic over plain
dicts, so it runs under any python and is tested without a client.
"""
from __future__ import annotations

#: A day, in milliseconds. The game's own day boundary is not midnight anywhere in
#: particular (`docs/research/server-info.md`), which is why every function here takes
#: the moment the game says the day turns over rather than assuming one.
DAY_MS = 86_400_000

#: The three states, and the fourth word that is not one of them.
STATE_DAY = "day"
STATE_POST = "post"
STATE_PLAIN = "plain"
STATE_UNKNOWN = "unknown"

#: The states an observation may carry, in the order they follow each other.
STATES = (STATE_DAY, STATE_POST, STATE_PLAIN)

#: Where an answer came from. `game` and `observed` are facts; `schedule` and `neighbour`
#: are this module's arithmetic, and they are labelled so nothing has to guess later.
SOURCE_GAME = "game"            # the client itself said so, about the account's warzone
SOURCE_OBSERVED = "observed"    # somebody wrote down what that warzone did that day
SOURCE_LAP = "lap"              # a lap of the map counted the stars among what it saw
SOURCE_CALENDAR = "calendar"    # the cycle read off the warzone's AGE — its opening date
SOURCE_SCHEDULE = "schedule"    # the fitted cycle, on a warzone that has observations
SOURCE_NEIGHBOUR = "neighbour"  # …the cycle again, on a warzone borrowing a neighbour's
SOURCE_UNKNOWN = "unknown"      # nothing is known and nothing is being claimed

#: The periods a fit will consider. A fortnight either side of a week covers everything
#: a live cycle has been seen to be and keeps the search a few thousand comparisons.
PERIODS = tuple(range(2, 29))

#: How many labelled observations, spread over how many distinct days, before a fit is
#: attempted at all. Below this any period fits perfectly and means nothing.
MIN_OBSERVATIONS = 3
MIN_DAYS = 2


# ---------------------------------------------------------------------------
# the game's day, counted the game's way
# ---------------------------------------------------------------------------
def day_index(ms, day_end_ms) -> int:
    """Which game-day `ms` falls in, counted from the game's own reset moment.

    `day_end_ms` is what the client answers for «when does this game-day turn over»
    (`UITimeManager:GetTomorrowZero`), on any day — its time OF DAY is what matters, and
    it is what makes the count agree with the daily quotas rather than with UTC midnight.
    """
    return int((int(ms) - _reset_offset(day_end_ms)) // DAY_MS)


def day_bounds(index, day_end_ms) -> tuple:
    """`(starts, ends)` of that game-day, epoch milliseconds on the game's clock."""
    start = int(index) * DAY_MS + _reset_offset(day_end_ms)
    return start, start + DAY_MS


def day_label(index, day_end_ms) -> str:
    """The day as a date, for a person to read. The game's clock, never the machine's."""
    import time
    start, _ends = day_bounds(index, day_end_ms)
    return time.strftime("%Y-%m-%d", time.gmtime(start / 1000.0))


def _reset_offset(day_end_ms) -> int:
    """The time of day the game-day turns over, as milliseconds into a UTC day."""
    try:
        return int(day_end_ms) % DAY_MS
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# observations
# ---------------------------------------------------------------------------
def observation(server, day, state=STATE_UNKNOWN, source=SOURCE_OBSERVED,
                stars=None, tiles=None, seen_at=0) -> dict:
    """One thing that was seen: what a warzone did on a day, and what it was counted from.

    `stars` / `tiles` are the evidence — how many star tasks were among how many the read
    could see. They are kept even when the state is unknown, because a labelled day
    elsewhere turns them into a label later (:func:`calibrate`).
    """
    return {"server": int(server), "day": int(day),
            "state": state if state in STATES else STATE_UNKNOWN,
            "source": str(source or SOURCE_OBSERVED),
            "stars": None if stars is None else int(stars),
            "tiles": None if tiles is None else int(tiles),
            "seen_at": int(seen_at or 0)}


def labelled(observations) -> list:
    """Only the observations that say which of the three states it was."""
    return [o for o in observations or () if o.get("state") in STATES]


# ---------------------------------------------------------------------------
# turning counted stars into a state — with thresholds LEARNT, not typed in
# ---------------------------------------------------------------------------
def ratio_of(obs) -> "float | None":
    """The share of star tasks in what that observation could see, or None."""
    tiles = obs.get("tiles")
    stars = obs.get("stars")
    if not tiles or stars is None:
        return None
    try:
        tiles = int(tiles)
        if tiles <= 0:
            return None
        return float(stars) / float(tiles)
    except (TypeError, ValueError):
        return None


def calibrate(observations) -> "dict | None":
    """Where the star-share of a day, a post-day and an ordinary day part company.

    Learnt from the observations that carry BOTH a state somebody was sure of and the
    counts behind it — never a constant in this file. Two thresholds come back, and only
    when the labelled examples actually separate: a rule fitted to one side of a boundary
    would label everything that side of it and call the result knowledge.
    """
    buckets = {state: [] for state in STATES}
    for obs in labelled(observations):
        share = ratio_of(obs)
        if share is not None:
            buckets[obs["state"]].append(share)
    days, posts, plains = (buckets[s] for s in STATES)
    if not days or not plains:
        return None
    if posts:
        high = (min(days) + max(posts)) / 2.0
        low = (min(posts) + max(plains)) / 2.0
    else:
        high = (min(days) + max(plains)) / 2.0
        low = high / 2.0
    if not high > low > 0:
        return None
    return {"day": high, "post": low}


def classify(obs, calibration) -> str:
    """What a counted observation says the state was — `unknown` without a calibration."""
    share = ratio_of(obs)
    if share is None or not calibration:
        return STATE_UNKNOWN
    if share >= calibration["day"]:
        return STATE_DAY
    if share >= calibration["post"]:
        return STATE_POST
    return STATE_PLAIN


def with_learnt_states(observations) -> list:
    """The observations, with the unlabelled ones labelled where the counts allow it.

    The learnt label is marked (`learnt: True`) so nothing downstream can mistake it for
    somebody's own reading of the map.
    """
    calibration = calibrate(observations)
    out = []
    for obs in observations or ():
        row = dict(obs)
        if row.get("state") not in STATES:
            guess = classify(row, calibration)
            if guess in STATES:
                row["state"] = guess
                row["learnt"] = True
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# the fit: one cycle, one word, an offset per warzone
# ---------------------------------------------------------------------------
class Schedule:
    """A fitted cycle: how long it is, what it says, and where each warzone stands in it.

    `pattern` maps a phase (0 … period-1) to one of the three states; a phase nothing has
    been seen at is simply absent, and asking about it answers `unknown` rather than
    inventing the tidiest word.
    """

    def __init__(self, period: int, pattern: dict, offsets: dict,
                 agree: int = 0, clash: int = 0) -> None:
        self.period = int(period)
        self.pattern = dict(pattern)
        self.offsets = dict(offsets)
        self.agree = int(agree)
        self.clash = int(clash)

    # -- what it is worth -----------------------------------------------------
    @property
    def score(self) -> int:
        """Agreements minus disagreements — what the search maximises."""
        return self.agree - self.clash

    @property
    def coverage(self) -> int:
        """How many phases of the cycle anything has ever been seen at."""
        return len(self.pattern)

    def phase(self, server, day) -> "int | None":
        """Where that warzone stands in the cycle on that day, if its offset is known."""
        offset = self.offsets.get(int(server))
        if offset is None:
            return None
        return (int(day) - int(offset)) % self.period

    def state(self, server, day) -> str:
        """What the cycle says that warzone does on that day."""
        phase = self.phase(server, day)
        if phase is None:
            return STATE_UNKNOWN
        return self.pattern.get(phase, STATE_UNKNOWN)

    def as_dict(self) -> dict:
        return {"period": self.period, "pattern": dict(self.pattern),
                "offsets": dict(self.offsets), "agree": self.agree,
                "clash": self.clash, "coverage": self.coverage}


def fit(observations, periods=PERIODS) -> "Schedule | None":
    """Fit one cycle to everything that has been written down. None when it is too soon.

    The search is small and deliberately plain: for each candidate period, the warzone
    with the most observations sets the pattern, every other warzone is slid against that
    pattern until it fits best, and whatever it adds becomes part of the pattern for the
    ones after it. The period with the best (agreements − disagreements) wins, ties going
    to the shorter cycle and then to the one that has been seen at more of its phases.

    It is order-dependent and says so: a different order can land on a different local
    best. What keeps that honest is that the result is scored against every observation
    afterwards (:func:`conflicts`), so a fit that fights the data is visible rather than
    authoritative.
    """
    rows = labelled(with_learnt_states(observations))
    if len(rows) < MIN_OBSERVATIONS:
        return None
    if len({row["day"] for row in rows}) < MIN_DAYS:
        return None

    by_server: dict = {}
    for row in rows:
        by_server.setdefault(int(row["server"]), []).append(row)
    order = sorted(by_server, key=lambda s: (-len(by_server[s]), s))

    best = None
    for period in periods:
        pattern: dict = {}
        offsets: dict = {}
        agree = clash = 0
        for server in order:
            pick, pick_agree, pick_clash = 0, -1, 0
            for offset in range(period):
                good = bad = 0
                for row in by_server[server]:
                    phase = (row["day"] - offset) % period
                    seen = pattern.get(phase)
                    if seen is None:
                        continue
                    if seen == row["state"]:
                        good += 1
                    else:
                        bad += 1
                if not pattern:
                    pick, pick_agree, pick_clash = 0, 0, 0
                    break
                if (good - bad) > (pick_agree - pick_clash):
                    pick, pick_agree, pick_clash = offset, good, bad
            offsets[server] = pick
            agree += max(0, pick_agree)
            clash += pick_clash
            # What this warzone adds to the shared word. A phase already spoken for is
            # left alone — the disagreement was counted above, not written in.
            for row in by_server[server]:
                phase = (row["day"] - pick) % period
                pattern.setdefault(phase, row["state"])
        candidate = Schedule(period, pattern, offsets, agree, clash)
        key = (candidate.score, -period, candidate.coverage)
        if best is None or key > (best.score, -best.period, best.coverage):
            best = candidate
    return best


# ---------------------------------------------------------------------------
# the other way to know where a warzone stands: its OWN AGE (#1467)
# ---------------------------------------------------------------------------
# A cycle keyed by how many days the warzone has been open, rather than by an offset
# fitted per warzone. Two things make it worth having beside the fit above:
#
#   * the panel already knows the opening moment of thousands of warzones
#     (`get.other.server.info`, docs/research/server-info.md), so a warzone nobody has
#     ever watched gets an answer that is grounded in a reading of the GAME rather than
#     in a neighbour's offset;
#   * a live cross-check against a third-party cycle chart partitioned a block of
#     neighbouring warzones into three groups by exactly this arithmetic — the panel's
#     own opening dates reproduced the chart's own group sizes to the warzone.
#
# What is NOT decided here: the length of the cycle and which state each phase carries.
# Both are FITTED from the observations, the same as everything else in this file, and a
# book that has only ever seen ONE of the three states fits nothing at all — every period
# explains a single-state pile perfectly, and the shortest one would then answer «day»
# about every warzone on every date.


class Calendar:
    """A cycle read off a warzone's AGE: `period`, and a state per phase of it."""

    def __init__(self, period: int, pattern: dict, agree: int = 0, clash: int = 0,
                 support: "dict | None" = None) -> None:
        self.period = int(period)
        self.pattern = dict(pattern)
        self.agree = int(agree)
        self.clash = int(clash)
        #: `{phase: {state: how many observations said so}}` — what the pattern is made
        #: of, kept so :func:`with_geometry` can tell a phase with one stray sighting
        #: from the one the star day is actually written all over.
        self.support = {ph: dict(counts) for ph, counts in (support or {}).items()}

    @property
    def score(self) -> int:
        return self.agree - self.clash

    @property
    def coverage(self) -> int:
        return len(self.pattern)

    def phase(self, age: int, ahead: int = 0) -> int:
        """Where a warzone that is `age` days old today stands `ahead` days from now."""
        return (int(age) + int(ahead)) % self.period

    def state(self, age: int, ahead: int = 0) -> str:
        return self.pattern.get(self.phase(age, ahead), STATE_UNKNOWN)

    def as_dict(self) -> dict:
        return {"period": self.period, "pattern": dict(self.pattern),
                "agree": self.agree, "clash": self.clash, "coverage": self.coverage}


def fit_calendar(observations, ages, today, periods=PERIODS) -> "Calendar | None":
    """Fit «the state follows the warzone's age» to the observations. None when it cannot.

    `ages` is `{server: how many days it has been open TODAY}` and `today` is the game-day
    the ages were taken on, so an observation from three days ago is judged against the
    age that warzone had THEN.

    Refuses two ways, both on purpose: too few observations, and observations that carry
    only ONE of the three states — a single-state pile is explained perfectly by every
    period there is, and accepting it would answer «star day» about the whole game.
    """
    rows = [row for row in labelled(with_learnt_states(observations))
            if int(row["server"]) in ages]
    if len(rows) < MIN_OBSERVATIONS:
        return None
    if len({row["state"] for row in rows}) < 2:
        return None
    best = None
    for period in periods:
        buckets: dict = {}
        for row in rows:
            age = int(ages[int(row["server"])]) + int(row["day"]) - int(today)
            buckets.setdefault(age % period, []).append(row["state"])
        pattern, agree, clash, support = {}, 0, 0, {}
        for phase, states in buckets.items():
            top = max(set(states), key=states.count)
            pattern[phase] = top
            support[phase] = {state: states.count(state) for state in set(states)}
            agree += states.count(top)
            clash += len(states) - states.count(top)
        candidate = Calendar(period, pattern, agree, clash, support)
        key = (candidate.score, -period, candidate.coverage)
        if best is None or key > (best.score, -best.period, best.coverage):
            best = candidate
    return best


def with_geometry(calendar) -> "Calendar | None":
    """Fill the rest of the word from the ONE phase that is the star day.

    The three states are not three independent things to be fitted separately — they are
    DEFINED by their distance from the star day: the day itself, the day after it (still
    handing stars out, far more rarely), and every other day. So a cycle that knows which
    phase carries the day knows the whole word, and a book that has only ever been told
    about star days can answer all three states instead of two unknowns.

    That is a definition rather than a guess, and it is deliberately kept SEPARATE from
    :func:`fit_calendar`, which stays a plain fit of what was actually written down. The
    completed word is what the panel shows and what :func:`calendar_conflicts` is judged
    against — so an observation that disagrees with the geometry (say, «ordinary» written
    down on the day after a star day) shows up as a disagreement instead of quietly
    rewriting the word. The observation still wins for its own warzone and its own day:
    :func:`answer` reaches it first.

    The star phase is the one the observations support most strongly; ties go to the
    lowest phase, so the answer does not depend on dictionary order.
    """
    if calendar is None:
        return None
    days = [ph for ph, state in calendar.pattern.items() if state == STATE_DAY]
    if not days:
        return calendar
    star = max(days, key=lambda ph: (calendar.support.get(ph, {}).get(STATE_DAY, 0), -ph))
    pattern = {}
    for phase in range(calendar.period):
        if phase == star:
            pattern[phase] = STATE_DAY
        elif phase == (star + 1) % calendar.period:
            # A warzone at this phase today was at the star phase YESTERDAY — its age is
            # one day further on — so today is the day after its star day.
            pattern[phase] = STATE_POST
        else:
            pattern[phase] = STATE_PLAIN
    return Calendar(calendar.period, pattern, calendar.agree, calendar.clash,
                    calendar.support)


def calendar_conflicts(calendar, observations, ages, today) -> list:
    """Every observation the AGE cycle contradicts — its half of the self-check."""
    if calendar is None:
        return []
    out = []
    for row in labelled(with_learnt_states(observations)):
        server = int(row["server"])
        if server not in ages:
            continue
        age = int(ages[server]) + int(row["day"]) - int(today)
        said = calendar.state(age)
        if said in STATES and said != row["state"]:
            out.append({"server": server, "day": row["day"], "observed": row["state"],
                        "predicted": said, "source": row.get("source", SOURCE_OBSERVED)})
    return out


def conflicts(schedule, observations) -> list:
    """Every observation the fitted cycle contradicts. The self-check, in one call.

    An empty list is a schedule that explains everything it was given; a non-empty one is
    the panel's own graph telling the person it has started to be wrong, which is the
    whole reason a derived schedule is allowed to exist at all.
    """
    if schedule is None:
        return []
    out = []
    for row in labelled(with_learnt_states(observations)):
        said = schedule.state(row["server"], row["day"])
        if said in STATES and said != row["state"]:
            out.append({"server": row["server"], "day": row["day"],
                        "observed": row["state"], "predicted": said,
                        "source": row.get("source", SOURCE_OBSERVED)})
    return out


# ---------------------------------------------------------------------------
# the answer for one warzone on one day
# ---------------------------------------------------------------------------
def answer(schedule, observations, server, day, fact=None,
           calendar=None, ages=None, today=None) -> dict:
    """What that warzone is doing that day, and how honestly it is known.

    The order is facts first: what the game itself said (`fact`), then what somebody
    wrote down for that very day, then the cycle for that warzone, then the cycle borrowed
    from the nearest warzone that has one. Anything below that is `unknown` — and the
    `source` field is on every answer so neither front-end has to guess which it has.
    """
    server, day = int(server), int(day)
    if fact in STATES:
        return {"state": fact, "source": SOURCE_GAME, "server": server, "day": day}
    for row in labelled(with_learnt_states(observations)):
        if int(row["server"]) == server and int(row["day"]) == day:
            # `learnt` says the label came from the counts through a calibration rather
            # than from somebody who looked — an observation either way, and the card
            # says which so the two are never read as the same kind of certainty.
            return {"state": row["state"], "source": SOURCE_OBSERVED,
                    "server": server, "day": day,
                    "learnt": bool(row.get("learnt"))}
    # THE WARZONE'S OWN AGE comes next, ahead of any fitted offset: it is arithmetic on a
    # reading of the game (when that warzone opened) rather than on a neighbour's habits.
    if calendar is not None and ages and server in ages and today is not None:
        age = int(ages[server]) + int(day) - int(today)
        said = calendar.state(age)
        if said in STATES:
            return {"state": said, "source": SOURCE_CALENDAR, "server": server,
                    "day": day, "age": age, "phase": calendar.phase(age)}
    if schedule is None:
        return {"state": STATE_UNKNOWN, "source": SOURCE_UNKNOWN,
                "server": server, "day": day}
    if server in schedule.offsets:
        return {"state": schedule.state(server, day), "source": SOURCE_SCHEDULE,
                "server": server, "day": day, "phase": schedule.phase(server, day)}
    near = nearest(schedule, server)
    if near is None:
        return {"state": STATE_UNKNOWN, "source": SOURCE_UNKNOWN,
                "server": server, "day": day}
    offsets = dict(schedule.offsets)
    offsets[server] = schedule.offsets[near]
    borrowed = Schedule(schedule.period, schedule.pattern, offsets)
    return {"state": borrowed.state(server, day), "source": SOURCE_NEIGHBOUR,
            "server": server, "day": day, "neighbour": near,
            "distance": abs(server - near), "phase": borrowed.phase(server, day)}


def nearest(schedule, server) -> "int | None":
    """The observed warzone closest in NUMBER — «the neighbours run the same cycle».

    Ties go to the lower number, so the answer does not depend on dictionary order.
    """
    if schedule is None or not schedule.offsets:
        return None
    return min(schedule.offsets, key=lambda other: (abs(int(other) - int(server)), other))


def next_change(schedule, observations, server, day, ahead=None, **known) -> "dict | None":
    """The first day ahead on which the answer becomes something else.

    `None` means nothing can be said — an unknown state now, or a cycle with a gap where
    the next days fall. A caller shows «—» for that rather than a date it made up.
    """
    calendar = known.get("calendar")
    if schedule is None and calendar is None:
        return None
    now = answer(schedule, observations, server, day, **known)
    if now["state"] not in STATES:
        return None
    span = int(ahead or (schedule.period if schedule is not None else calendar.period))
    for step in range(1, span + 1):
        later = answer(schedule, observations, server, day + step, **known)
        if later["state"] in STATES and later["state"] != now["state"]:
            return {"day": day + step, "state": later["state"], "in_days": step,
                    "source": later["source"]}
    return None


def summary(schedule, observations) -> dict:
    """The state of the graph itself — what a person needs to judge whether to trust it."""
    rows = list(observations or ())
    return {"observations": len(rows),
            "labelled": len(labelled(with_learnt_states(rows))),
            "servers": len({int(r["server"]) for r in rows}),
            "days": len({int(r["day"]) for r in rows}),
            "period": None if schedule is None else schedule.period,
            "coverage": 0 if schedule is None else schedule.coverage,
            "agree": 0 if schedule is None else schedule.agree,
            "clash": 0 if schedule is None else schedule.clash,
            "conflicts": len(conflicts(schedule, rows))}
