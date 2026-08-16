r"""Per-monster-type daily caps on rally auto-join — the limits and the day's count.

The «rally_auto_join» trigger (panel/triggers.py) joins every banner that goes out.
Some rallies are worth a squad and some are not, and a squad spent is a squad that
cannot go elsewhere for the march's length — so this puts a **daily cap per monster
type** in front of it: join at most N of that type today, and 0 means "no cap".

Two small stores, both per profile, and only one of them a file (#1465):

  * ``rally_limits.json`` — ``{monster_type_key: max_count}``. ``0`` = unlimited. Seeded
    from :data:`DEFAULT_RALLY_LIMITS` on first run, and edited from the «Авторалли»
    settings page. **Stays a file** — a person edits it by hand, and «copy the folder and
    your panel comes with you» has to keep meaning something.
  * `rally_counts` — how many of each type were joined *today*; it resets itself the
    first time it is read on a new day, so a cap is a per-day budget, not a running
    total. **The day is the SERVER's** (#1317): `day_end_ms` is the client's own
    `GetTomorrowZero()`, written by whoever last recorded a join, and the roll prefers it
    over any date this machine can work out for itself. This one IS game data — a count,
    not a setting — so it lives in this profile's `panel.db` (`panel/runtime/store.py`,
    the `blobs` table under the name `rally_counts`), not `rally_counts.json` any more.
    `load_counts`/`save_counts` still take a bare path and are kept for the pre-#1465
    file shape and for tests; every call site in the panel goes through
    :func:`load_counts_from_store` / :func:`save_counts_to_store` instead.

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

# …and the one place the SERVER's day boundary is worked out (#1333). Shared with the
# daily timers and the checklist's «до сброса», so the three cannot drift apart.
import game_day                                                       # noqa: E402

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

#: The kinds that ship UNCAPPED — «на золотых оставляем без лимита», and «золотые» is
#: exactly the four the game calls Golden: Golden Defender, Golden Striker, Golden
#: Annihilator and the Desert Boss, whose Russian name is «Золотой вожак»
#: (`tools/game_locale.py`).
#:
#: THE WANDERING MUMMY WARLORD WAS IN THIS LIST AND IS NOT ANY MORE — «мумию не
#: учитываем», said after a day of watching it («Золотой» is not in its name, in any of
#: the eleven locales). It goes back to the ordinary twenty, and a profile seeded while
#: it was uncapped is carried across by :data:`RESEEDED_KINDS`: the zero in those files
#: was never anybody's choice, it was this list's.
UNCAPPED_KINDS = ("desert_boss", "golden_defender", "golden_striker",
                  "golden_annihilator")

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

#: What a kind's SEED changed to, and what it was: `{kind: (the old seed, the new one)}`.
#:
#: A profile's file wins over the built-ins, which is right for a number somebody typed
#: and wrong for one this module put there. The Wandering Mummy Warlord shipped uncapped
#: for a day and every profile opened in that day has a `0` nobody chose; «мумию не
#: учитываем» has to reach those files or it only holds for installs made after it.
#:
#: So the value MOVES ONLY IF IT IS STILL THE OLD SEED — a profile where somebody typed
#: their own number keeps it, whatever it is. Applied once, at the file version below.
RESEEDED_KINDS: dict[str, tuple] = {"wandering_mummy_warlord": (0, DEFAULT_CAP)}

#: The file format's own version. `2` said whether a stored `doom_elite` was the old
#: meaning (both keys are legitimate now, so a file has to say which it means); `3` says
#: whether :data:`RESEEDED_KINDS` has been applied. Each migration runs exactly once,
#: and a file is rewritten at the new version the moment one does.
FILE_VERSION = 3

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
    return game_day.day_key(stamp)


#: When the server's day turns, in hours UTC. Measured on the live warzone for #1188 —
#: `GetTomorrowZero()` answered 02:00 UTC and 597 of 636 tile expiries shared `01:59:59`.
#: It is a FALLBACK: a counts file that carries the client's own `day_end_ms` is rolled
#: on that instead, because the client is the authority and this number is one warzone's.
#:
#: RE-EXPORTED, NOT RE-SPELT (#1333). The same number decides when a daily TIMER is next
#: due and how long the checklist says is left before the reset, so it lives in exactly
#: one place — `tools/lib/game_day.py` — and everything that needs it asks there. It was
#: written out three times before that, in three different units, and one of the three
#: had it at midnight UTC.
SERVER_DAY_HOUR_UTC = game_day.DEFAULT_RESET_HOUR_UTC


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
    try:
        version = int(data.get("v") or 0)
    except (TypeError, ValueError):
        version = 0
    if version < 1:                      # the `doom_elite` rename, once
        stored = migrate_kinds(stored)
    if version < 3:                      # a seed of ours that changed, once
        stored = reseed_kinds(stored)
    merged = dict(DEFAULT_RALLY_LIMITS)
    merged.update(stored)
    limits = RallyLimits(merged, path)
    # …and the file is rewritten AT THE NEW VERSION, so a migration runs once rather
    # than on every read. Without it a person who sets a reseeded kind back by hand in
    # the JSON would have this module quietly undo them at the next start-up.
    if version < FILE_VERSION:
        save_limits(limits, path)
    return limits


def reseed_kinds(stored: dict) -> dict:
    """Move a kind whose DEFAULT changed, and only if the file still holds the old one.

    «Мумию не учитываем» (#1317): the Wandering Mummy Warlord was seeded uncapped for a
    day, so profiles opened in that day carry a `0` that is this module's opinion rather
    than the person's. A number somebody typed themselves is never touched — the value
    has to be exactly the old seed to move.
    """
    out = dict(stored)
    for key, (was, now) in RESEEDED_KINDS.items():
        if key not in stored:
            continue
        try:
            if int(stored[key]) == int(was):
                out[key] = now
        except (TypeError, ValueError):
            continue
    return out


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


#: The name this store's row lives under in `panel.db`'s `blobs` table.
COUNTS_BLOB = "rally_counts"


def load_counts_from_store(store, path: str, today: str | None = None) -> RallyCounts:
    """Read today's counts out of `panel.db`, importing `path` the first time.

    `path` is only ever touched here to bring an older profile's `rally_counts.json`
    across, once (`panel.runtime.store.blob_import_once`); every read after that is the
    database. `store` is `rt.store` — always the CALLING profile's, never a module-level
    one (`CLAUDE.md`: a profile is a whole panel of its own).
    """
    from .runtime.store import blob_import_once
    today = today or _today()
    data = store.blob_get(COUNTS_BLOB)
    if data is None:
        blob_import_once(store, COUNTS_BLOB, path)
        data = store.blob_get(COUNTS_BLOB)
    if not isinstance(data, dict):
        return RallyCounts(today, {}, path)
    raw = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    kept = {str(k): v for k, v in raw.items()}
    counts = RallyCounts(str(data.get("date") or today),
                         kept if data.get("v") else migrate_kinds(kept, tally=True),
                         path, data.get("day_end_ms"))
    return counts.rolled(today)


def save_counts_to_store(store, counts: RallyCounts) -> None:
    """Checkpoint `counts` into `panel.db`. Async — see `Store.blob_set`."""
    store.blob_set(COUNTS_BLOB,
                   {"v": FILE_VERSION, "date": counts.date,
                    "day_end_ms": counts.day_end_ms, "counts": dict(counts.counts)})
