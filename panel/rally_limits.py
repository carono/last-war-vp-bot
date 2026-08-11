r"""Per-monster-type daily caps on rally auto-join — the limits and the day's count.

The «rally_auto_join» trigger (panel/triggers.py) joins every banner that goes out.
Some rallies are worth a squad and some are not, and a squad spent is a squad that
cannot go elsewhere for the march's length — so this puts a **daily cap per monster
type** in front of it: join at most N of that type today, and 0 means "no cap".

Two small files, both per profile, both plain JSON — the same shape and spirit as the
timers/triggers catalogues:

  * ``rally_limits.json`` — ``{monster_type_key: max_count}``. ``0`` = unlimited. Seeded
    from :data:`DEFAULT_RALLY_LIMITS` on first run, and edited from the «Авторалли»
    settings page. The keys are the vocabulary of monster types the caps apply to.
  * ``rally_counts.json`` — ``{"date": "2026-07-30", "day_end_ms": …, "counts": {key: n}}``.
    How many of each type were joined *today*; it resets itself the first time it is read
    on a new day, so a cap is a per-day budget, not a running total. **The day is the
    SERVER's** (#1317): `day_end_ms` is the client's own `GetTomorrowZero()`, written by
    whoever last recorded a join, and the roll prefers it over any date this machine can
    work out for itself.

Nothing here imports Tk or the game or picks the day for itself in a way a test cannot
control: :meth:`RallyCounts.allowed` / :meth:`RallyCounts.record` take the day as an
argument (defaulting to today), so the date-reset is a plain function a test can drive.
"""
from __future__ import annotations

import datetime
import json
import os

from .profile import _write_json

# The vocabulary itself — every kind of banner the game knows, read off the live config
# (#1317). `tools/lib` is on the path by the time the panel imports this.
import rally_kinds                                                    # noqa: E402

# The built-in vocabulary and its caps: what a profile with no limits file is seeded
# from, and the last-resort fallback. A cap of 0 means the key is never held back.
#
# THE KEYS ARE THE GAME'S OWN SPECIES, AND THEY ARE NAMED OFF THE GAME'S OWN TABLES
# (#1281, corrected and widened in #1317). A rally's `targetContentId` — carried by
# `push.alliance.march.*` and dropped from the client's march record — is a row in
# `lw_world_monster`, and what identifies the SPECIES there is its `name` key rather
# than its `type`: «Роковая Элита» (`300602`) appears under three different types across
# seasons, and type 8 is not it at all — it is the Doom WALKER line
# (`monster_boss_name_001`, «Разрушитель»), which is what the old `doom_elite` key was
# really counting. The name keys were read out of the live config for #1317 and each is
# translated with `tools/game_locale.py`, never by hand.
#
# Events are matched off their own managers instead, because they are not tiles: the
# alliance exercise by the boss the drill manager names, the invasion by its own monster
# lists, and the General's Trial by the `activity == 107` column its instructors carry.
#
# A species nobody has seen before still lands under `monster_type_<n>` and is folded in
# on the next read rather than being silently counted as something it is not.
#
# THE NUMBERS ARE THE PLAYER'S, IN THEIR OWN WORDS (#1317): «по умолчанию на всех по 20,
# на золотых оставляем без лимита». So every kind the game knows starts at twenty and the
# Golden line's boss — `desert_boss`, which the game calls «Золотой вожак» — starts
# uncapped. A profile's own file always wins over this; these are only what a profile that
# has never been edited is seeded with.
DEFAULT_CAP = 20

#: The kinds that ship UNCAPPED. One so far, and it is the one the person named.
UNCAPPED_KINDS = ("desert_boss",)

DEFAULT_RALLY_LIMITS: dict[str, int] = {
    kind: (0 if kind in UNCAPPED_KINDS else DEFAULT_CAP)
    for kind in rally_kinds.KIND_ORDER
}

#: What #1317 renamed, and why the values travel rather than the key.
#:
#: `doom_elite` counted `lw_world_monster.type == 8`, which the game calls **Doom Walker**
#: («Разрушитель») — the panel's label said «Роковая Элита» and was wrong. Doom Elite is a
#: different species (`300602`) and now has a key of its own. So the stored number is
#: copied into BOTH: into `doom_walker` because that is what it was counting, and into
#: `doom_elite` because that is the row the person was setting when they typed it.
RENAMED_KINDS: dict[str, tuple] = {"doom_elite": ("doom_walker", "doom_elite")}

#: The file format's own version, and the ONLY thing that says a stored `doom_elite` is
#: the old meaning (#1317). Both keys are legitimate now — `doom_elite` is a real species
#: again — so a file has to say whether it predates the rename; an unversioned one does,
#: a versioned one does not, and the rename is applied exactly once either way.
FILE_VERSION = 2

# A monster type the resolver could not classify falls back to this key, so an
# unknown rally is still counted (and capped) under a real budget rather than slipping
# past every limit. It is one of DEFAULT_RALLY_LIMITS on purpose.
UNKNOWN_TYPE = "monster"


def _today() -> str:
    """The day these counts belong to — the GAME's day, whenever the game has said so.

    A daily budget resets when the SERVER's day turns, and the server's day is not this
    machine's: it was measured at 02:00 UTC on this account's warzone, and the client
    answers it exactly (`UITimeManager:GetTomorrowZero()`, docs/research/rally-join.md and
    ghost-recon-steal.md §4.1). The PC clock is not even reliably in the same minute —
    it was eleven seconds out when `game_clock` was written.

    So the day key is derived from the GAME's clock when the offset has been sampled this
    process, and from the local one only when nothing has ever asked the client. The
    boundary itself is carried in the counts file (`day_end_ms`, written by whoever
    recorded a join while a client was there); this is the fallback that still rolls a
    file over when that stamp is missing.
    """
    try:
        import game_clock                      # lazy: tools/lib is on the path in the panel
        stamp = game_clock.now_ms()
    except Exception:                          # noqa: BLE001 — no tools path, no game
        stamp = None
    if not stamp:
        return datetime.date.today().isoformat()
    when = datetime.datetime.fromtimestamp(stamp / 1000.0, datetime.timezone.utc)
    return (when - datetime.timedelta(hours=SERVER_DAY_HOUR_UTC)).date().isoformat()


#: When the server's day turns, in hours UTC. Measured on the live warzone for #1188 —
#: `GetTomorrowZero()` answered 02:00 UTC and 597 of 636 tile expiries shared `01:59:59`.
#: It is a FALLBACK: a counts file that carries the client's own `day_end_ms` is rolled
#: on that instead, because the client is the authority and this number is one warzone's.
SERVER_DAY_HOUR_UTC = 2


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class RallyLimits:
    """The per-type caps, as configured. ``{type: max}``; ``max == 0`` is unlimited."""

    def __init__(self, limits: dict, path: str | None = None) -> None:
        # Coerce to {str: non-negative int}, dropping anything unreadable, so a
        # hand-edited file cannot make a cap crash the join.
        self._limits: dict[str, int] = {}
        for key, value in (limits or {}).items():
            try:
                self._limits[str(key)] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        self.path = path

    # -- reading ------------------------------------------------------------
    def types(self) -> list[str]:
        """The monster-type keys the caps cover, in a stable order."""
        return list(self._limits.keys())

    def limit_for(self, type_key: str) -> int:
        """The cap for a type (``0`` = unlimited); ``0`` for a type not in the file."""
        return int(self._limits.get(type_key, 0))

    def as_dict(self) -> dict:
        return dict(self._limits)

    # -- editing ------------------------------------------------------------
    def with_limit(self, type_key: str, value) -> "RallyLimits":
        """A copy with one type's cap set (the «Авторалли» field writes through here)."""
        merged = dict(self._limits)
        try:
            merged[str(type_key)] = max(0, int(value))
        except (TypeError, ValueError):
            merged[str(type_key)] = 0
        return RallyLimits(merged, self.path)


def default_limits() -> RallyLimits:
    return RallyLimits(DEFAULT_RALLY_LIMITS)


def load_limits(path: str) -> RallyLimits:
    """Read a profile's limits, seeding the file from the built-ins when it has none.

    A file that exists but is unreadable falls back to the built-ins WITHOUT being
    overwritten — the same rule the timers/triggers catalogues follow.
    """
    if not os.path.exists(path):
        fresh = RallyLimits(DEFAULT_RALLY_LIMITS, path)
        save_limits(fresh, path)
        return fresh
    data = _read_json(path)
    if not isinstance(data, dict):
        return RallyLimits(DEFAULT_RALLY_LIMITS, path)
    # New built-in types added after this profile's file was written are folded in so
    # the caps vocabulary grows without a hand edit; the file's own values win.
    stored = {str(k): v for k, v in data.items() if k != "v"}
    merged = dict(DEFAULT_RALLY_LIMITS)
    merged.update(migrate_kinds(stored) if not data.get("v") else stored)
    return RallyLimits(merged, path)


def migrate_kinds(stored: dict, tally: bool = False) -> dict:
    """Carry a renamed kind's number onto its new key(s) — nobody's value is lost (#1317).

    Applied to whatever is read off disk, and it never OVERWRITES a value the file
    already has under the new name: a profile edited since the rename keeps what the
    person typed.

    `tally=True` is the COUNTS file, and there the number MOVES rather than being copied:
    a cap is a wish and may honestly sit on both rows, but a count is a fact about today,
    and one join must appear exactly once. Copying it would spend a budget nothing was
    spent from AND double the sum the game's own count is checked against (#1317).
    """
    out = dict(stored)
    for old, news in RENAMED_KINDS.items():
        if old not in stored:
            continue
        for new in (news[:1] if tally else news):
            if new not in stored:
                out[new] = stored[old]
        if tally:
            out.pop(old, None)
    return out


def save_limits(limits: RallyLimits, path: str | None = None) -> None:
    stored = limits.as_dict()
    stored["v"] = FILE_VERSION
    _write_json(path or limits.path, stored)


class RallyCounts:
    """Today's per-type join count, reset the first time it is read on a new day.

    `day_end_ms` is the client's own «when this day ends» (`GetTomorrowZero()`), written
    by whoever recorded a join while a client was there (#1317). It is what the roll
    prefers, because the day that matters is the SERVER's; the date string is the
    fallback for a store nothing has ever been able to ask.
    """

    def __init__(self, date: str, counts: dict, path: str | None = None,
                 day_end_ms: int = 0) -> None:
        self.date = date
        self.counts: dict[str, int] = {}
        for key, value in (counts or {}).items():
            try:
                self.counts[str(key)] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        self.path = path
        try:
            self.day_end_ms = max(0, int(day_end_ms or 0))
        except (TypeError, ValueError):
            self.day_end_ms = 0

    # -- day roll -----------------------------------------------------------
    def rolled(self, today: str | None = None, now_ms: int = 0) -> "RallyCounts":
        """This store, or an empty one if the day has turned since it was written.

        The client's own boundary wins when the store carries one: `now_ms` is the GAME's
        clock (`game_clock.now_ms()`, sampled by the caller), and a store whose day has
        ended is empty whatever the date strings say. Only a store with no boundary falls
        back to comparing day keys.
        """
        if self.day_end_ms:
            stamp = now_ms or _game_now_ms()
            if stamp and stamp >= self.day_end_ms:
                return RallyCounts(today or _today(), {}, self.path)
            if stamp:
                return self
        today = today or _today()
        if self.date == today:
            return self
        return RallyCounts(today, {}, self.path)

    def count_for(self, type_key: str) -> int:
        return int(self.counts.get(type_key, 0))

    # -- the decision -------------------------------------------------------
    def allowed(self, type_key: str, limits: RallyLimits,
                today: str | None = None) -> bool:
        """Is another join of ``type_key`` allowed today? ``0`` cap = always yes."""
        cur = self.rolled(today)
        cap = limits.limit_for(type_key)
        if cap <= 0:
            return True
        return cur.count_for(type_key) < cap

    def record(self, type_key: str, today: str | None = None) -> "RallyCounts":
        """A copy with one more join of ``type_key`` counted for today (day-rolled)."""
        cur = self.rolled(today)
        counts = dict(cur.counts)
        counts[type_key] = counts.get(type_key, 0) + 1
        return RallyCounts(cur.date, counts, cur.path, cur.day_end_ms)

    def with_day_end(self, day_end_ms) -> "RallyCounts":
        """A copy carrying the client's own «this day ends at» stamp (#1317)."""
        try:
            stamp = max(0, int(day_end_ms or 0))
        except (TypeError, ValueError):
            return self
        if not stamp or stamp == self.day_end_ms:
            return self
        return RallyCounts(self.date, dict(self.counts), self.path, stamp)

    def left_for(self, type_key: str, limits: RallyLimits) -> int:
        """How many more of this kind today — `-1` for «no cap» (#1317).

        The shape the recipe is handed: it gates per banner on this, so «no cap» has to be
        a value rather than an absence, and a spent kind is `0`.
        """
        cap = limits.limit_for(type_key)
        if cap <= 0:
            return -1
        return max(0, cap - self.count_for(type_key))


def _game_now_ms() -> int:
    """«Now» on the GAME's clock, or 0 when nothing has ever asked a client."""
    try:
        import game_clock                      # lazy: tools/lib is on the path in the panel
        return int(game_clock.now_ms() or 0)
    except Exception:                          # noqa: BLE001 — no tools path, no game
        return 0


def load_counts(path: str, today: str | None = None) -> RallyCounts:
    """Read today's counts, rolling the day over if the day has turned since."""
    today = today or _today()
    data = _read_json(path)
    if not isinstance(data, dict):
        return RallyCounts(today, {}, path)
    raw = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    kept = {str(k): v for k, v in raw.items()}
    store = RallyCounts(str(data.get("date") or today),
                        kept if data.get("v") else migrate_kinds(kept, tally=True),
                        path, data.get("day_end_ms"))
    return store.rolled(today)


def save_counts(counts: RallyCounts, path: str | None = None) -> None:
    _write_json(path or counts.path,
                {"v": FILE_VERSION, "date": counts.date,
                 "day_end_ms": counts.day_end_ms, "counts": dict(counts.counts)})
