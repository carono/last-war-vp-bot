"""What the wire has said about the fireworks going off over the map, per profile (#1677).

WHAT A FIREWORK IS. A player lights one over their own base and, while it burns, it
drops gift boxes anybody who is near may take. The game announces every box that is
taken — ours and everyone else's — as `push.get.fireworks.gift`, and that push is the
ONLY thing that says a firework exists at all: there is no periodic list to sweep, and
the ask-able `get.fireworks.info.list` answers about what is burning *now*, which is
already too late for a firework that started while nobody asked. So the stream is the
ability, and this is the book it fills.

WHY A BOOK AND NOT A TAB'S DICT. The same reason `panel/runtime/rally_wire.py` exists:
a receiver that lives on a tab is absent in every profile whose window does not draw
that tab, and a profile with the collect trigger switched on but no page open would then
hear the pushes and write down nothing. This hangs off `PanelRuntime`, so it is there
whether or not anybody is looking — and it is a PROFILE'S OWN, like the log and the
schedule (`CLAUDE.md`, «A profile is a whole panel of its own»).

IT IS A RECEIVER, AND IT SAYS SO. Every push it is handed is counted on the profile's
intake ledger (`panel/runtime/intake.py`, #1523) under :data:`INTAKE`, as seen / kept /
dropped-with-a-reason. **`lost` stays at zero by construction**: the work this receiver
does is four integer adds and a dict write, there is nothing here that can decline to
run, and nothing is deferred to a thread that might not exist. A push it cannot make
sense of is `dropped` with the reason that says so — never silently swallowed.

NOTHING HERE IS A PERSON. The fields line the ear hands over carries `gift`, `tile` and
`type` — the id of a box, the square it fell on and which firework it was — because
`tools/wire_event_monitor.py` builds it from an allow-list and never from the payload
(#1293). The push itself also carries `ownerUid`, the account the firework belongs to,
and it does not cross the pipe: the collector reads the owner out of the client's own
`LWFireworkGiftManager` at the moment it presses, where it never leaves the game VM.

WHAT IS KEPT AND WHERE. The count of what was heard today, by tile, in the profile's own
database (`store.blob_get`/`blob_set` under :data:`BLOB`) — game data, so a row and not a
file (`CLAUDE.md`, «Game data lives only in the database»). What was actually COLLECTED
is not written down here and must not be: the client keeps that itself, in
`LWFireworkGiftManager.giftUuid2TimeTable`, and a second copy the panel maintains is the
one that is wrong the first time the two disagree.

Read with no window and no game at all:

    python3 tests/test_firework_wire.py
"""
from __future__ import annotations

import datetime
import threading
import time

#: This receiver's row on «Занятость». One name, because there is one ear and one book.
INTAKE = "fireworks.push"

#: Where the day's tally lives in the profile's database.
BLOB = "firework_state"

#: How long a heard tile is remembered for. A firework burns for minutes and the boxes
#: with it; a tile older than this stands for one that has gone out, and the only thing
#: keeping it would do is make the count of «what is up now» wrong.
TILE_TTL_SEC = 900.0

#: How often the tally is written to the database. The pushes arrive in bursts — 109 in
#: one recorded session — and a checkpoint per push would be a transaction per push for a
#: number nobody reads oftener than a tab repaint.
SAVE_EVERY_SEC = 20.0


def parse_fields(raw: str) -> dict:
    """`"gift=1 tile=2 type=0"` -> `{"gift": "1", "tile": "2", "type": "0"}`.

    Anything unreadable is left out rather than guessed at; an empty dict is a perfectly
    good answer and is counted as a push that could not be named.
    """
    out: dict = {}
    for part in str(raw or "").split():
        key, sep, value = part.partition("=")
        if sep and key and value:
            out[key] = value
    return out


def _today() -> str:
    """The day this tally belongs to — the GAME's day whenever the game has said so.

    The same rule, and the same fallback, as `panel/rally_limits.py::_today`: a daily
    count resets when the SERVER's day turns, and the PC clock is not even reliably in
    the same minute as the game's (`tools/lib/game_clock.py`).
    """
    try:
        import game_clock                      # lazy: tools/lib is on the panel's path
        import game_day
        stamp = game_clock.now_ms()
    except Exception:                          # noqa: BLE001 — no tools path, no game
        stamp = None
    if not stamp:
        return datetime.date.today().isoformat()
    return game_day.day_key(stamp)


class FireworkBook:
    """The fireworks this profile's ear has heard about, and how many boxes fell.

    Fed off the capture's reader thread and read from Tk and from the schedule's worker,
    so every touch is under one lock. Nothing here asks the game anything: it is a memory
    of what arrived, and an empty book is a perfectly good answer.
    """

    def __init__(self, rt=None) -> None:
        self._rt = rt
        self._lock = threading.Lock()
        # tile -> {"seen": n, "heard": monotonic, "type": str}. A firework is identified
        # by the square it is standing over: the gift ids differ per box, the owner does
        # not cross the pipe, and the tile is what both the panel and the map call it.
        self._tiles: dict = {}
        # The day's counts, loaded from the store on the first touch.
        self._day = ""
        self._heard = 0
        self._named = 0                        # …of which carried a tile
        self._saved = 0.0                      # monotonic of the last checkpoint
        # WHOSE counts these are. The runtime outlives a profile switch (`store` re-checks
        # the path on every ask for the same reason), so a book that only ever loaded once
        # would carry one account's tally into the next — the failure
        # `docs/research/profile-isolation.md` is a list of.
        self._loaded = ""
        # ON THE LEDGER BEFORE THE FIRST PUSH (#1523's other half). A row made on first
        # arrival cannot tell «the ear is listening and the sky is empty» from «there is
        # no such receiver», and the first of those is the ordinary state of this one:
        # fireworks come in bursts and are absent for hours in between.
        led = self._intake()
        if led is not None:
            led.declare(INTAKE)

    # -- the ledger ----------------------------------------------------------
    def _intake(self):
        rt = self._rt
        return getattr(rt, "intake", None) if rt is not None else None

    def _seen(self) -> None:
        led = self._intake()
        if led is not None:
            led.seen(INTAKE)

    def _kept(self) -> None:
        led = self._intake()
        if led is not None:
            led.kept(INTAKE)

    def _dropped(self, reason: str) -> None:
        led = self._intake()
        if led is not None:
            led.dropped(INTAKE, reason=reason)

    # -- receiving -----------------------------------------------------------
    def note(self, command: str, fields: dict) -> bool:
        """One firework push, counted. Returns whether it advanced the tally.

        **This is the receiver, and it never declines to do its work.** It has no tab to
        be shut, no queue to be full and no game to be down — the hole #1523 named (a
        receiver that returns early because nobody has opened its page) cannot happen
        here, because there is no page. A push that arrives unnamed is still counted;
        what it is not is credited to a tile.
        """
        self._seen()
        self._roll()
        with self._lock:
            self._heard += 1
            tile = str((fields or {}).get("tile") or "")
            if not tile:
                # Heard, counted, and honestly not understood: the push's own field names
                # are the server's and this build knows three spellings of «where». The
                # day's total is still right; only the per-tile breakdown misses it.
                self._dropped("no-tile")
                self._save_maybe()
                return False
            self._named += 1
            row = self._tiles.setdefault(tile, {"seen": 0, "heard": 0.0, "type": ""})
            row["seen"] += 1
            row["heard"] = time.monotonic()
            kind = str((fields or {}).get("type") or "")
            if kind:
                row["type"] = kind
            self._save_maybe()
        self._kept()
        return True

    # -- reading -------------------------------------------------------------
    def live(self, now: "float | None" = None) -> list:
        """The tiles heard from inside :data:`TILE_TTL_SEC`, busiest first.

        A list of `{"tile", "seen", "ago", "type"}` and nothing else — no owner, no name.
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            rows = [{"tile": tile, "seen": int(row["seen"]),
                     "ago": max(0.0, now - float(row["heard"])),
                     "type": str(row.get("type") or "")}
                    for tile, row in self._tiles.items()
                    if now - float(row["heard"]) <= TILE_TTL_SEC]
        rows.sort(key=lambda r: (-r["seen"], r["tile"]))
        return rows

    def tally(self) -> dict:
        """`{"day", "heard", "named", "tiles"}` — the day's numbers, for a report."""
        self._roll()
        with self._lock:
            return {"day": self._day, "heard": self._heard, "named": self._named,
                    "tiles": len(self._tiles)}

    # -- the day, and the database -------------------------------------------
    def _profile(self) -> str:
        rt = self._rt
        try:
            return str(rt.profiles.active) if rt is not None else ""
        except Exception:                      # noqa: BLE001 — a reading, never the ear
            return ""

    def _roll(self) -> None:
        """Load the day's counts on the first touch, and reset them when the day — or
        the profile under this runtime — turns."""
        today = _today()
        who = self._profile() or "?"
        with self._lock:
            if self._loaded != who:
                self._loaded = who
                self._tiles.clear()
                self._saved = 0.0
                saved = self._read_blob()
                if isinstance(saved, dict) and str(saved.get("day") or "") == today:
                    self._day = today
                    self._heard = int(saved.get("heard") or 0)
                    self._named = int(saved.get("named") or 0)
                else:
                    self._day, self._heard, self._named = today, 0, 0
                return
            if self._day != today:
                self._day, self._heard, self._named = today, 0, 0
                self._tiles.clear()
                self._saved = 0.0

    def _read_blob(self):
        rt = self._rt
        if rt is None:
            return None
        try:
            return rt.store.blob_get(BLOB)
        except Exception:                      # noqa: BLE001 — a reading, never the ear
            return None

    def _save_maybe(self) -> None:
        """Checkpoint the day's counts, at most every :data:`SAVE_EVERY_SEC`.

        Called with `_lock` held, so it must not raise and must not be slow — a failed
        write costs the checkpoint and never the push that was being counted.
        """
        now = time.monotonic()
        if now - self._saved < SAVE_EVERY_SEC:
            return
        self._saved = now
        rt = self._rt
        if rt is None:
            return
        try:
            rt.store.blob_set(BLOB, {"day": self._day, "heard": self._heard,
                                     "named": self._named})
        except Exception:                      # noqa: BLE001 — a checkpoint, never the ear
            pass
