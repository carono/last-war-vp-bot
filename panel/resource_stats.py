r"""Daily tally of resources *gained* — the store and the day roll.

The «resource_tracker» trigger (panel/triggers.py) fires on every
``push.resource.item.update`` — the game's "your balance changed" push — and asks
this to write down what went UP. Only increases are counted: a spend lowers the
balance and is ignored, so the tally answers "how much did I take in today", not
"what is my balance".

A day-keyed running total, kept in `panel.db`'s `blobs` table since #1465 (it used to
be one file per profile, ``resource_stats.json`` — a WHOLE-file rewrite on every gain,
exactly the cost `panel.db` exists to remove, since a resource push can arrive several
times a minute)::

    {
      "2026-07-30": {"food": 12000, "wood": 5000, "metal": 3000, "oil": 800, "gold": 150},
      "2026-07-29": {...}
    }

A new day is simply a new key — nothing is reset or deleted, so the history
accumulates and a reader can chart a week. The gain itself is worked out by
*diffing balances*: the panel reads the current balance on each push and compares
it to the one it saw last (``positive_deltas`` below), because the push says a
balance changed, not by how much. Diffing is why only net increases are seen — a
resource that rose and fell between two pushes shows its net, and a pure spend
shows nothing.

Nothing here reads the game or picks the day in a way a test cannot control:
:meth:`ResourceStats.add` takes the day as an argument (defaulting to today), so the
roll-over is a plain function. ``load_stats``/``save_stats`` still take a bare path and
are kept for the pre-#1465 file shape and for tests; every call site in the panel goes
through :func:`load_stats_from_store` / :func:`save_stats_to_store` instead.
"""
from __future__ import annotations

import datetime
import json
import os

from .profile import _write_json

# The resources the tally tracks, in display order — the four the base produces. The
# keys are the tracker's own vocabulary; `panel/runtime/reads.py` maps the game's
# resource TYPES onto them, because the client's own field names no longer say what the
# game shows (the field spelled `wood` is drawn as «Золотые монеты»).
#
# «wood» WAS A FIFTH COLUMN HERE and it was never a resource (#1990). It came from the
# wire's field names, where `wood` is the engine's original spelling of what the game
# now calls gold — so the tally carried a column that could only ever be zero next to a
# «gold» column meaning the same thing.
RESOURCES: tuple[str, ...] = ("food", "metal", "oil", "gold")


def _today() -> str:
    """The PC's date — the LAST RESORT, and never what a caller should pass.

    A day's statistic is filed under the GAME's day (`CLAUDE.md`, «A DAY'S STATISTIC IS
    A HISTORY»): the boundary that hands the account a fresh quota is the warzone's own
    reset, hours away from this computer's midnight, so a tally keyed by the PC's date
    splits one game day across two rows and merges two halves of different ones. Every
    caller in the panel passes `rt.day.day_key()` (`panel/runtime/day_reset.py`); this
    is what is left when a profile has never had a client to ask.
    """
    return datetime.date.today().isoformat()


def positive_deltas(current: dict, last: dict) -> dict:
    """The per-resource increase from ``last`` to ``current`` — gains only.

    A resource missing from ``last`` (the first reading of a session) is NOT counted:
    there is no baseline to say it went up, only that it exists, and counting the whole
    balance as "gained" the moment the panel opened would be a lie. A drop counts as no
    gain. Returns ``{resource: amount_up}`` for the resources that rose.
    """
    out = {}
    for key in RESOURCES:
        if key not in current or key not in last:
            continue
        try:
            delta = int(current[key]) - int(last[key])
        except (TypeError, ValueError):
            continue
        if delta > 0:
            out[key] = delta
    return out


class ResourceStats:
    """The day-keyed tally, loaded from and saved to a profile's file."""

    def __init__(self, days: dict, path: str | None = None) -> None:
        # {date: {resource: int}} — coerced so a hand-edited file cannot crash a read.
        self._days: dict[str, dict[str, int]] = {}
        for date, counts in (days or {}).items():
            if not isinstance(counts, dict):
                continue
            row = {}
            for key, value in counts.items():
                try:
                    row[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
            self._days[str(date)] = row
        self.path = path

    # -- reading ------------------------------------------------------------
    def dates(self) -> list[str]:
        """Days that have a tally, newest first."""
        return sorted(self._days.keys(), reverse=True)

    def on(self, date: str) -> dict:
        """The tally for one day — every resource present, zero-filled."""
        row = self._days.get(date, {})
        return {key: int(row.get(key, 0)) for key in RESOURCES}

    def as_dict(self) -> dict:
        return {date: dict(row) for date, row in self._days.items()}

    # -- writing ------------------------------------------------------------
    def add(self, gains: dict, today: str | None = None) -> "ResourceStats":
        """Fold a batch of gains into today's row; returns a new stats (or self).

        A new day is a new key, so nothing is reset — the older days stay. An empty
        ``gains`` (a push that was a spend, or the first read of a session) changes
        nothing and returns ``self`` so a caller can skip the save.
        """
        gains = {k: int(v) for k, v in (gains or {}).items()
                 if k in RESOURCES and _pos(v)}
        if not gains:
            return self
        today = today or _today()
        days = {d: dict(r) for d, r in self._days.items()}
        row = days.setdefault(today, {})
        for key, amount in gains.items():
            row[key] = row.get(key, 0) + amount
        return ResourceStats(days, self.path)


def _pos(value) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def load_stats(path: str) -> ResourceStats:
    """Read a profile's tally (an empty one when the file is missing/unreadable)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = None
    return ResourceStats(data if isinstance(data, dict) else {}, path)


def save_stats(stats: ResourceStats, path: str | None = None) -> None:
    _write_json(path or stats.path, stats.as_dict())


#: The name this store's row lives under in `panel.db`'s `blobs` table.
STATS_BLOB = "resource_stats"

#: …and the row of the SAME shape holding only what the base's own buildings paid
#: (#2743). Everything that raises a balance lands in :data:`STATS_BLOB` — a truck coming
#: home, a gift, a chest, a robbery — and a card that says «сколько собрано с базы» must
#: not count any of them. There is no field on the wire saying where a gain came from:
#: the balance push says a number moved, so the SOURCE is the panel's own knowledge that
#: it was playing `collect_base_resources` at that moment (`panel/tabs/stats.py`). A
#: harvest somebody makes with their own thumb in the game is therefore not counted here,
#: which is the honest answer rather than a guess — and the total tally still has it.
BASE_BLOB = "resource_stats_base"


def load_stats_from_store(store, path: "str | None",
                          blob: str = STATS_BLOB) -> ResourceStats:
    """Read the tally out of `panel.db`, importing `path` the first time (#1465).

    ``path`` is the pre-#1465 file this row was carried across from, and may be `None`
    for a tally that never had one (:data:`BASE_BLOB`) — then nothing is imported.
    """
    from .runtime.store import blob_import_once
    data = store.blob_get(blob)
    if data is None and path:
        blob_import_once(store, blob, path)
        data = store.blob_get(blob)
    return ResourceStats(data if isinstance(data, dict) else {}, path)


def save_stats_to_store(store, stats: ResourceStats,
                        blob: str = STATS_BLOB) -> None:
    """Checkpoint the tally into `panel.db`."""
    store.blob_set(blob, stats.as_dict())
