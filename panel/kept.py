r"""A list the panel keeps, whose removals have to name a reason (#1282).

## What this is for

Three data losses in one day, all the same shape: an EMPTY or FAILED read was treated as
authoritative and used to delete rows a person had paid for with laps of the map
(`7885032`, `a1bf34b`, `1511c48`). #1272 answered it properly for ONE list — the ★ tiles
— as a prose rule (`THE_LIST_RULE`), every removal site naming the clause it is
executing, and an audit test that walks every door.

The rule is right. What it is not is checkable anywhere else, and the panel keeps a dozen
other lists that have no guard at all: `ghost_map_state.json`, `rally_limits.json` /
`rally_counts.json`, `resource_stats.json`, `secret_shared.jsonl`, `timers_last_run.json`
(`docs/panel-storage.md` lists them). Three fixes would leave a fourth waiting, which is
exactly what #1272 said in so many words.

So the invariant goes into a TYPE. A `Kept` list has:

* **no `clear()`, and no way to assign its contents.** Not «a discouraged one» — there is
  no method, so a wipe fails where it is written instead of shipping and being found by
  the person who lost the data;
* **one removal API, and it takes a reason** — :data:`EXPIRED`, :data:`GAME_SAID_GONE`,
  :data:`PERSON_ASKED` — and each store declares which of the three it will accept, so a
  list that may only shed expired rows refuses the other two by construction;
* **a merge that only ever adds**, so the ordinary failure — a read that came back empty
  because the client was busy, or not logged in, or answering something else — cannot
  take anything away. An empty read merges nothing and removes nothing.

## What it is NOT

It is not a database and not a cache. It holds one JSON list of dicts keyed by one field,
because that is what every one of these stores actually is. Anything bigger belongs
somewhere else.

## Using it

    tiles = Kept(profiles.ghost_map_state_json(), key="uuid",
                 accepts=(EXPIRED, GAME_SAID_GONE))

    tiles.merge(rows_just_read)              # adds and updates; never removes
    tiles.drop(uuid, GAME_SAID_GONE)         # the server said this tile is gone
    tiles.drop_where(lambda r: r["expires_at"] <= now, EXPIRED)
    tiles.drop(uuid, PERSON_ASKED)           # ValueError: this store does not accept it

The file is written on every change, atomically (write beside, then replace), so a panel
killed mid-write reads back the previous whole list rather than half of one.
"""
from __future__ import annotations

import json
import os
import tempfile

#: The row's own countdown ran out. The only removal that needs nobody's word for it.
EXPIRED = "EXPIRED"
#: The GAME answered about this row and said it is not there — taken, gone, expired at
#: its end. Never «the read came back empty»: an empty answer is «cannot say» and this
#: constant is not for it.
GAME_SAID_GONE = "GAME_SAID_GONE"
#: A person pressed something that means «forget this». The only clause that may empty a
#: list, and only ever through :meth:`Kept.drop_where` with a predicate the press wrote.
PERSON_ASKED = "PERSON_ASKED"

#: All three, for a store that accepts all three.
ALL_REASONS = (EXPIRED, GAME_SAID_GONE, PERSON_ASKED)


class Kept:
    """A list of rows on disk, which grows freely and shrinks only for a named reason."""

    def __init__(self, path: str, *, key: str = "uuid",
                 accepts: tuple = ALL_REASONS, fields: tuple | None = None) -> None:
        bad = [r for r in accepts if r not in ALL_REASONS]
        if bad:
            raise ValueError(f"not a removal reason: {bad}")
        self.path = path
        self.key = key
        self.accepts = tuple(accepts)
        #: Which fields are checkpointed. `None` keeps the whole row — a store that
        #: holds live objects should name its fields so a restart cannot resurrect one.
        self.fields = tuple(fields) if fields else None
        self._rows: dict = {}
        self._loaded = False

    # -- reading ---------------------------------------------------------------------
    def load(self) -> "Kept":
        """Read the file. A missing or broken one is an EMPTY list, never an error.

        And an empty list here is the honest answer: there is nothing on disk. That is
        the one case where «I have nothing» is a fact rather than a failed read.
        """
        self._loaded = True
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return self
        if not isinstance(data, list):
            return self
        for row in data:
            if isinstance(row, dict) and row.get(self.key) is not None:
                self._rows[str(row[self.key])] = self._slice(row)
        return self

    def _slice(self, row: dict) -> dict:
        if self.fields is None:
            return dict(row)
        return {f: row.get(f) for f in self.fields}

    def rows(self) -> list:
        """Every row, in insertion order. A copy — mutating it changes nothing here."""
        self._ensure()
        return [dict(r) for r in self._rows.values()]

    def get(self, key) -> dict | None:
        self._ensure()
        row = self._rows.get(str(key))
        return dict(row) if row is not None else None

    def __len__(self) -> int:
        self._ensure()
        return len(self._rows)

    def __contains__(self, key) -> bool:
        self._ensure()
        return str(key) in self._rows

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    # -- adding ----------------------------------------------------------------------
    def merge(self, records) -> int:
        """Add or update rows. **Never removes one**, whatever `records` is missing.

        This is the whole point of the type. A read that came back empty — a busy
        client, a session that is not logged in, an answer that went to somebody else —
        merges nothing, and every row that was here is still here. The three losses this
        type exists for were all this call written as an assignment.

        Returns how many rows were added or changed.
        """
        self._ensure()
        changed = 0
        for record in records or ():
            if not isinstance(record, dict) or record.get(self.key) is None:
                continue
            key = str(record[self.key])
            row = self._slice(record)
            if self._rows.get(key) != row:
                merged = dict(self._rows.get(key) or {})
                merged.update(row)
                self._rows[key] = merged
                changed += 1
        if changed:
            self.save()
        return changed

    # -- removing --------------------------------------------------------------------
    def drop(self, key, reason: str) -> bool:
        """Remove one row, for one of the reasons this store accepts.

        A reason the store does not accept raises — at the call site, in the diff,
        rather than as a list somebody notices is short a week later.
        """
        self._check(reason)
        self._ensure()
        if self._rows.pop(str(key), None) is None:
            return False
        self.save()
        return True

    def drop_where(self, predicate, reason: str) -> int:
        """Remove every row the predicate names, for one accepted reason.

        The predicate is written at the press or the tick that has the right to remove
        them; this only enforces that a reason was named and that this store takes it.
        """
        self._check(reason)
        self._ensure()
        doomed = [k for k, row in self._rows.items() if predicate(dict(row))]
        for k in doomed:
            del self._rows[k]
        if doomed:
            self.save()
        return len(doomed)

    def _check(self, reason: str) -> None:
        if reason not in ALL_REASONS:
            raise ValueError(
                f"{reason!r} is not a removal reason. The three are {ALL_REASONS} — "
                f"and «the read came back empty» is not among them on purpose.")
        if reason not in self.accepts:
            raise ValueError(
                f"this list does not remove rows for {reason}; it accepts "
                f"{self.accepts}. If that is wrong, say so where the list is made — "
                f"never here.")

    # -- writing ---------------------------------------------------------------------
    def save(self) -> None:
        """Write the whole list, atomically. A half-written checkpoint is not a thing."""
        rows = list(self._rows.values())
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
