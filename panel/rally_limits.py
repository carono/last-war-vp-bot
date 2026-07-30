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
  * ``rally_counts.json`` — ``{"date": "2026-07-30", "counts": {key: n}}``. How many of
    each type were joined *today*; it resets itself the first time it is read on a new
    day, so a cap is a per-day budget, not a running total.

Nothing here imports Tk or the game or picks the day for itself in a way a test cannot
control: :meth:`RallyCounts.allowed` / :meth:`RallyCounts.record` take the day as an
argument (defaulting to today), so the date-reset is a plain function a test can drive.
"""
from __future__ import annotations

import datetime
import json
import os

from .profile import _write_json

# The built-in vocabulary and its caps: what a profile with no limits file is seeded
# from, and the last-resort fallback. Keys are monster-type categories a rally can be
# classified into (panel/__main__.py `_rally_monster_type`); a cap of 0 means the type
# is never held back. The starting numbers are the ones the task named — normal
# monsters and the alliance drill are worth capping, the zombie invasion is not.
DEFAULT_RALLY_LIMITS: dict[str, int] = {
    "monster": 20,           # ordinary world monsters
    "zombie_invasion": 0,    # зомби-вторжение — no cap
    "alliance_drill": 20,    # учения альянса
}

# A monster type the resolver could not classify falls back to this key, so an
# unknown rally is still counted (and capped) under a real budget rather than slipping
# past every limit. It is one of DEFAULT_RALLY_LIMITS on purpose.
UNKNOWN_TYPE = "monster"


def _today() -> str:
    return datetime.date.today().isoformat()


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
    merged = dict(DEFAULT_RALLY_LIMITS)
    merged.update({str(k): v for k, v in data.items()})
    return RallyLimits(merged, path)


def save_limits(limits: RallyLimits, path: str | None = None) -> None:
    _write_json(path or limits.path, limits.as_dict())


class RallyCounts:
    """Today's per-type join count, reset the first time it is read on a new day."""

    def __init__(self, date: str, counts: dict, path: str | None = None) -> None:
        self.date = date
        self.counts: dict[str, int] = {}
        for key, value in (counts or {}).items():
            try:
                self.counts[str(key)] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        self.path = path

    # -- day roll -----------------------------------------------------------
    def rolled(self, today: str | None = None) -> "RallyCounts":
        """This store, or an empty one if the day has changed since it was written."""
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
        return RallyCounts(cur.date, counts, cur.path)


def load_counts(path: str, today: str | None = None) -> RallyCounts:
    """Read today's counts, rolling the day over if the file is from an earlier one."""
    today = today or _today()
    data = _read_json(path)
    if not isinstance(data, dict):
        return RallyCounts(today, {}, path)
    store = RallyCounts(str(data.get("date") or today),
                        data.get("counts") if isinstance(data.get("counts"), dict) else {},
                        path)
    return store.rolled(today)


def save_counts(counts: RallyCounts, path: str | None = None) -> None:
    _write_json(path or counts.path,
                {"date": counts.date, "counts": dict(counts.counts)})
