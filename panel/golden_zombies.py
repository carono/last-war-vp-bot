r"""What the golden-zombie chain did — the parser of a run's report and the day's tally.

**No Tk, and no counting of its own.** Every number here comes out of the scenario's own
closing report (`actions/attack_golden_zombies.md`), which in turn is the GAME's answer:
how many golden zombies the client knew about, how many marches the server actually
charged for, and what the game priced one attack at. The panel adds those up per day and
draws them; it never decides that an attack happened.

That distinction is the whole reason the tally is worth keeping. A run reports what it
sent; a person attacking on the screen in front of them spends from the same energy purse
and is not in this table at all — so «сколько энергии потрачено» here means «what THIS
panel's runs spent», and the live energy reading beside it is the truth about the purse.

The store is a day-keyed running total in `panel.db`'s `blobs` table — never a file, per
`CLAUDE.md` («Game data lives only in the database»)::

    {
      "2026-08-19": {"attacks": 6, "spent": 60, "found": 135, "runs": 2},
      "2026-08-18": {...}
    }

A new day is a new key and nothing is reset or deleted, so a week is readable. There is
no legacy file to import: this store was born in the database (#1519).
"""
from __future__ import annotations

import datetime

#: The name this store's row lives under in `panel.db`'s `blobs` table.
GOLDEN_BLOB = "golden_zombie_runs"

#: The fields a day's row carries, in the order a reader wants them.
FIELDS: tuple[str, ...] = ("attacks", "spent", "found", "runs")


def today() -> str:
    return datetime.date.today().isoformat()


def parse_report(raw) -> dict:
    """Turn the scenario's `key=value` closing line into numbers.

    The shape is exactly what `golden_report()` prints::

        found=143 attacks=6 spent=60 cost=10 energy=45 queued=137 squad=1

    A field the line does not carry is left out rather than guessed at, and a field that
    is not a number is dropped: half a reading is still worth drawing, and a zero we
    invented is indistinguishable from one the game gave us.
    """
    out: dict = {}
    for chunk in str(raw or "").split():
        key, _, value = chunk.partition("=")
        if not key or not value:
            continue
        try:
            out[key] = int(float(value))
        except (TypeError, ValueError):
            continue
    return out


def add_run(days: dict, report: dict, day: str | None = None) -> dict:
    """Fold one finished run into the day's row. Returns a NEW dict, never mutates.

    `found` is the widest the client saw during that run and not a sum: the same zombie
    is counted once per run, and adding two runs' sightings together would report twice
    the map. `attacks` and `spent` ARE sums — those are marches, and each one happened.
    """
    day = day or today()
    out = {d: dict(row) for d, row in (days or {}).items()}
    row = out.setdefault(day, {})
    row["attacks"] = int(row.get("attacks", 0)) + int(report.get("attacks", 0) or 0)
    row["spent"] = int(row.get("spent", 0)) + int(report.get("spent", 0) or 0)
    row["found"] = max(int(row.get("found", 0)), int(report.get("found", 0) or 0))
    row["runs"] = int(row.get("runs", 0)) + 1
    return out


def day_row(days: dict, day: str | None = None) -> dict:
    """One day's row, with every field present — an empty day reads as zeros."""
    row = (days or {}).get(day or today()) or {}
    return {name: int(row.get(name, 0) or 0) for name in FIELDS}


def load(store) -> dict:
    """Read the tally out of `panel.db`. An empty one when nothing has been written."""
    data = store.blob_get(GOLDEN_BLOB) if store is not None else None
    return data if isinstance(data, dict) else {}


def save(store, days: dict) -> None:
    """Checkpoint the tally into `panel.db`. Async — see `Store.blob_set`."""
    if store is not None:
        store.blob_set(GOLDEN_BLOB, days)
