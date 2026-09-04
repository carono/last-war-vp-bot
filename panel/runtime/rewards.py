"""The book of reward popups: what the game gave, and what the panel was doing (#2027).

THE EAR IS IN THE CLIENT, not here. `tools/lib/lua_actions.py::reward_watch_install`
wraps two of the client's own Lua methods once per client — the reward manager's
show-methods and `UIManager:OpenWindow` — so a reward modal is closed by the client
itself, inside a call it was making anyway. Nothing on this side asks the game anything,
and there is no clock: this is the «слушаем» half of «читаем один раз, дальше слушаем»
(`CLAUDE.md`).

WHAT THIS CLASS IS. The ear writes into a ring inside the client; the recipe
`actions/collect_reward_popups.md` empties that ring whenever the panel is talking to the
VM anyway and says the rows out loud as one log line. This class listens to the LOG — the
one place every scenario's output already passes through, whoever started it — parses
that line and books the rows into this profile's own table (`store.rewards_add`).

WHY THE LOG AND NOT A RETURN VALUE. The drain happens inside whatever recipe earned
something: the assist, a collect, a robbery. Those are played by the schedule, by a
trigger, by a button on the phone and by a person at the window, and the only thing all
four share is that their scenario's lines reach `rt.log`. A hook per caller would be four
places to forget; a tap is one.

«ЗА ЧТО» IS THE PANEL'S ANSWER, AND «НЕ ЗНАЮ» IS AN ALLOWED ONE. Nothing in the client
knows why a reward arrived — the reply that carried it is long gone by the time the
window opens. What IS known is what the panel was playing at that moment
(`rt.activity`), and that is what is written down. When the panel was playing nothing —
a reward that arrived from a push, an alliancemate's gift, something the person did by
hand — the field stays EMPTY and the page says «не знаю». A guess there would be
indistinguishable from a fact, which is worse than a gap.
"""
from __future__ import annotations

import re
import threading
import time

#: The marker the recipe prints. Kept here because this is the side that reads it; the
#: recipe says the same word and `tests/test_panel_rewards.py` pins the two together.
MARK = "reward_popups:"

#: How the drain packs its rows: `<game ms>|<kind>|<what>`, rows separated by « ;; ».
ROW_SEP = " ;; "

#: The kinds the ear can write. Anything else is a row from a newer client than this
#: panel — booked as it is rather than dropped, so nothing is lost while the two are out
#: of step.
KINDS = ("reward", "closed", "popup", "unknown", "held", "lost")

#: How long a row is kept. Ninety days is longer than any question anybody has asked of
#: this book and small enough that it never becomes the biggest table in the file.
KEEP_SEC = 90 * 24 * 3600

#: The step key `ActionRunner` puts on the activity while a scenario plays, and the field
#: in it that names the scenario. Read rather than re-spelled: this is the only honest
#: source for «за что» there is.
PLAY_KEY = "activity.action"

#: The tail of a log line the scenario's `LOG` writes, so the blob can be lifted out of
#: it whatever the tag and stamp in front are.
_LINE = re.compile(re.escape(MARK) + r"\s*(?P<blob>.*?)\s*\"?\s*$")


class RewardBook:
    """One profile's record of the reward popups its client raised."""

    def __init__(self, log, store=None, activity=None, say=None) -> None:
        self._log = log
        self._store = store
        self._activity = activity
        #: `say(tag, key, **fmt)` — used for exactly one thing: an UNKNOWN reward window.
        #: That row is the only one a person has to act on (it is how the whitelist
        #: grows, `lua_actions.REWARD_WINDOWS`), and a row nobody sees is a whitelist
        #: that never grows.
        self._say = say
        self._lock = threading.Lock()
        self._off = None
        self._pruned = False
        #: The last rows booked, newest first — what a page draws without touching the
        #: database on every poll.
        self._recent: list = []
        #: WHOEVER ELSE WANTS TO KNOW A DRAIN HAPPENED (#2408). One callback list, told
        #: the rows that were just booked. The standing order uses it to put a switched
        #: OFF wish back into a client that has restarted since it was made — the ear is
        #: in the client, so a drain is the only proof there is that it is listening
        #: again, and it is an EVENT rather than a clock (`CLAUDE.md`).
        self._watchers: list = []

    # -- listening ----------------------------------------------------------
    def listen(self) -> None:
        """Start hearing the drains. Idempotent."""
        if self._off is not None or self._log is None:
            return
        self._off = self._log.tap(self._heard)

    def stop(self) -> None:
        off, self._off = self._off, None
        if off is not None:
            off()

    def watch(self, on_rows) -> None:
        """Be told the rows of every drain. Never raises out of the book."""
        self._watchers.append(on_rows)

    def _heard(self, line: str) -> None:
        """One log line. Cheap and total: everything the panel says passes through here."""
        if MARK not in (line or ""):
            return
        try:
            self.take(line)
        except Exception:                 # noqa: BLE001 — a book, never the panel
            pass

    # -- booking ------------------------------------------------------------
    def take(self, line: str) -> list:
        """Book the rows in one drain line. Returns what was booked."""
        found = _LINE.search(line or "")
        if found is None:
            return []
        rows = self.parse(found.group("blob"), why=self.playing())
        if not rows:
            return []
        with self._lock:
            self._recent = (rows + self._recent)[:200]
        store = self._store() if callable(self._store) else self._store
        if store is not None:
            store.rewards_add(rows)
            if not self._pruned:
                self._pruned = True
                store.rewards_prune(time.time() - KEEP_SEC)
        self._announce(rows)
        for watcher in tuple(self._watchers):
            try:
                watcher(rows)
            except Exception:             # noqa: BLE001 — a listener, never the book
                pass
        return rows

    @staticmethod
    def parse(blob: str, why: str = "") -> list:
        """The drain's own text as rows. Malformed pieces are skipped, never guessed at."""
        seen = int(time.time())
        out = []
        for piece in (blob or "").split(ROW_SEP):
            piece = piece.strip()
            if not piece:
                continue
            bits = piece.split("|", 2)
            if len(bits) < 2:
                continue
            try:
                at = int(bits[0])
            except ValueError:
                continue
            kind = bits[1].strip()
            rest = bits[2] if len(bits) > 2 else ""
            source, items = rest, ""
            if kind == "reward" and "|" in rest:
                source, items = rest.split("|", 1)
            out.append({"at": at, "seen_at": seen, "kind": kind,
                        "source": source.strip(), "items": items.strip(), "why": why})
        return out

    def playing(self) -> str:
        """WHAT THE PANEL IS PLAYING right now, or `""` for «не знаю».

        The OLDEST live play, not the newest step: a scenario that calls another shares
        one step, and anything else in flight (a read, a poll) is not what earned this.
        """
        activity = self._activity
        if activity is None:
            return ""
        try:
            for step in activity.live():
                if getattr(step, "key", "") == PLAY_KEY:
                    return str((getattr(step, "fmt", None) or {}).get("name") or "")
        except Exception:                 # noqa: BLE001 — a reading, never the run
            return ""
        return ""

    def _announce(self, rows) -> None:
        """Say the one thing a person has to act on: a reward window nobody vouched for.

        Everything else is a row on a page. An `unknown` is a name that BELONGS in
        `lua_actions.REWARD_WINDOWS` and is not there yet — until somebody adds it, that
        popup stays on the client's screen — so it is said once per name, out loud.
        """
        if self._say is None:
            return
        said = getattr(self, "_said", None)
        if said is None:
            said = self._said = set()
        for row in rows:
            if row.get("kind") != "unknown":
                continue
            name = row.get("source") or ""
            if name in said:
                continue
            said.add(name)
            self._say("rewards", "rewards.unknown", window=name)

    # -- reading ------------------------------------------------------------
    def recent(self, limit: int = 50, *, kind: str = "") -> list:
        """The newest rows, from the database when there is one and memory otherwise."""
        store = self._store() if callable(self._store) else self._store
        if store is not None:
            try:
                return store.rewards_recent(limit, kind=kind)
            except Exception:             # noqa: BLE001 — a page, never a crash
                pass
        with self._lock:
            rows = [r for r in self._recent if not kind or r.get("kind") == kind]
        return rows[:limit]

    def unknown(self, limit: int = 20) -> list:
        """The reward windows the ear saw and would not close — the whitelist's queue."""
        return self.recent(limit, kind="unknown")

    def tally(self, rows=None) -> dict:
        """How many of each kind are in these rows (or in the newest hundred)."""
        rows = self.recent(100) if rows is None else rows
        out = {kind: 0 for kind in KINDS}
        for row in rows:
            kind = str(row.get("kind") or "")
            out[kind] = out.get(kind, 0) + 1
        return out
