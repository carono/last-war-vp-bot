"""The treasure feed: what a drained message MEANS, and the ring that keeps it. **No Tk.**

The tab draws; this decides. Three questions live here and nowhere else:

* **what came back** — `parse` turns the one JSON line `read_treasure_watch.md` leaves in
  `feed` into :class:`Drain`, and says «the watcher is not installed» rather than raising
  when the client has been restarted under it;
* **which of the three moments a message is** — :func:`kind`. The person asked to see
  «что есть сокровища, что отряд был отправлен, что сокровище было взято», and that is a
  reading of the command name, not a guess about intent;
* **what it reads as on one line** — :func:`line`, used by the window, by the phone and
  by the saved file, so a line copied out of any of them is the same line.

**The ring is the panel's second copy, not its only one.** The first lives in the game
VM and survives a panel restart (`lua_actions`, «The watcher»); this one survives a
`GAME` restart, which wipes that. Between them there is no moment where a message is
kept in exactly one place — which is the whole point of «не терять сообщения, если
человек не смотрит».

**Nothing here is a count the panel keeps.** `seq`, `drop` and `more` are the game's own
numbers, drained and shown; the ring's own length is the only thing this module counts,
and it is a fact about the window rather than about the game.
"""
from __future__ import annotations

import json
import time

#: The scenarios. The panel plays these and assembles no Lua of its own (`CLAUDE.md`).
#: Named by their bare stem: the interpreter looks in `actions/` first and `actions/dev/`
#: after, and all three of these live in `dev/` because they modify the client.
WATCH_ACTION = "watch_treasures"
READ_ACTION = "read_treasure_watch"
UNWATCH_ACTION = "unwatch_treasures"

#: Where each scenario leaves its answer.
FEED_VARIABLE = "feed"
STATE_VARIABLE = "watch"

# -- the three moments, plus the one that is none of them --------------------
#: A chest exists: the alliance share, the detect-event pushes, the list replies.
FOUND = "found"
#: A squad is on its way to dig one: a `world.march.*` send at a treasure target type.
MARCH = "march"
#: A chest was taken: the claim going out, its reply, the alliance broadcast.
TAKEN = "taken"
#: Everything else — only ever present when the watch is running wide.
OTHER = "other"

#: In the order the tab draws its filter, which is the order of the ability itself.
KINDS = (FOUND, MARCH, TAKEN, OTHER)

#: The commands that are unambiguously the taking. Everything else `detect`/`treasure`
#: is the chest being announced, listed or updated — which is `FOUND` by elimination,
#: deliberately: a message we have never seen before is better drawn as «a chest said
#: something» than silently dropped into `OTHER` where nobody looks.
_TAKEN_COMMANDS = frozenset({
    "detect.event.claim.treasure",
    "push.detect.treasure.claim",
    "receive.detect.event.reward",
})


def kind(command: str) -> str:
    """Which of the three moments this command is — by name, never by guess."""
    name = (command or "").strip().lower()
    if name in _TAKEN_COMMANDS:
        return TAKEN
    if name.startswith("world.march."):
        return MARCH
    if "treasure" in name or "detect" in name:
        return FOUND
    return OTHER


class Entry:
    """One message the watcher kept.

    ``ms`` is the GAME's clock in milliseconds (`docs/research/game-clock.md` — the PC's
    lies, and a feed timestamped by the wrong clock is worse than one with no timestamp,
    because it looks right). ``fields`` is the flattened `k=v` text the drain built:
    numbered arguments for a send, the server's own field names for a push.
    """

    __slots__ = ("seq", "ms", "out", "command", "fields", "kind")

    def __init__(self, seq: int, ms: int, out: bool, command: str, fields: str) -> None:
        self.seq = seq
        self.ms = ms
        #: Did the CLIENT send it? The other direction is the server talking.
        self.out = out
        self.command = command
        self.fields = fields
        self.kind = kind(command)

    def __repr__(self) -> str:
        return f"<Entry {self.seq} {'->' if self.out else '<-'} {self.command}>"


class Drain:
    """One answer from `read_treasure_watch.md`.

    ``error`` is set when the run itself failed, and then `on` is False and the numbers
    are zero — a scenario that did not run has not said the watch is off, so the tab
    shows the failure rather than redrawing the page as «not listening».
    """

    __slots__ = ("on", "wide", "more", "drop", "seq", "entries", "error", "at")

    def __init__(self, on=False, wide=False, more=0, drop=0, seq=0,
                 entries=None, error: str = "", at: float = 0.0) -> None:
        self.on = bool(on)
        self.wide = bool(wide)
        #: Still queued in the game. Not zero means drain again, at once.
        self.more = int(more)
        #: Dropped by the ring since the last drain — reported once, then cleared.
        self.drop = int(drop)
        #: How many messages the watcher has kept in total, ever.
        self.seq = int(seq)
        self.entries = list(entries or ())
        self.error = error
        self.at = at

    def __bool__(self) -> bool:
        return not self.error


def parse(raw, at: float = 0.0) -> "Drain":
    """Turn the scenario's one JSON line into a :class:`Drain`.

    Anything unparseable is an `error` rather than an exception: this is the client
    talking through a log line, and a client that has just been restarted says all
    sorts of things. A single malformed ENTRY is dropped and the rest of the drain is
    kept — losing one message beats losing the batch it arrived in.
    """
    if raw is None:
        return Drain(error="no answer", at=at)
    try:
        data = json.loads(str(raw))
    except (ValueError, TypeError):
        return Drain(error="unreadable", at=at)
    if not isinstance(data, dict):
        return Drain(error="unreadable", at=at)
    entries = []
    for item in data.get("items") or ():
        try:
            entries.append(Entry(int(item.get("i") or 0), int(item.get("t") or 0),
                                 str(item.get("d") or "") == "out",
                                 str(item.get("c") or ""), str(item.get("f") or "")))
        except (TypeError, ValueError, AttributeError):
            continue
    return Drain(on=data.get("on"), wide=data.get("wide"), more=data.get("more") or 0,
                 drop=data.get("drop") or 0, seq=data.get("seq") or 0,
                 entries=entries, at=at)


def parse_state(raw) -> dict:
    """`on=1 wide=0 buf=3 seq=9 drop=0 cap=400` -> a dict of ints, `{}` if it is not that.

    What `watch_treasures.md` and `unwatch_treasures.md` leave in `watch`: the press is
    not trusted to have worked, the reading beside it is what says so.
    """
    out: dict = {}
    for piece in str(raw or "").split():
        key, sep, value = piece.partition("=")
        if not sep:
            continue
        try:
            out[key] = int(value)
        except ValueError:
            continue
    return out


def clock(ms: int) -> str:
    """The game's millisecond stamp as `HH:MM:SS`, or `--:--:--` when there is none.

    Local time, because the person reading the feed is watching the same screen the game
    is on. A zero is drawn as dashes rather than as 1970: the clock was unreadable, and
    saying so is the honest answer.
    """
    if not ms:
        return "--:--:--"
    try:
        return time.strftime("%H:%M:%S", time.localtime(ms / 1000.0))
    except (ValueError, OSError, OverflowError):
        return "--:--:--"


def line(entry: "Entry") -> str:
    """The one line a message reads as — in the window, on the phone and in the file.

    `HH:MM:SS → command  fields`. The arrow is the direction (`→` the client sent it,
    `←` the server said it), and it is a glyph rather than a word for the reason the
    events tab's are: it needs no translating and reads the same in all eleven.
    """
    return "%s %s %s  %s" % (clock(entry.ms), "→" if entry.out else "←",
                             entry.command, entry.fields)


class Ring:
    """The panel's copy of the feed: the last `cap` entries, oldest first.

    A ring rather than a list because the wide watch is genuinely unbounded — this page
    is opened precisely for the sessions where nobody knows what is coming. What falls
    off is counted, and the tab says so, for the same reason the game-side ring confesses
    its own drops: a feed that silently forgets reads as a quiet client.
    """

    __slots__ = ("cap", "entries", "lost")

    def __init__(self, cap: int = 2000) -> None:
        self.cap = int(cap)
        self.entries: list = []
        #: How many entries this ring has dropped to stay within `cap`.
        self.lost = 0

    def add(self, entries) -> int:
        """Append what a drain brought back; returns how many were added."""
        added = 0
        for entry in entries:
            self.entries.append(entry)
            added += 1
        overflow = len(self.entries) - self.cap
        if overflow > 0:
            del self.entries[:overflow]
            self.lost += overflow
        return added

    def clear(self) -> None:
        self.entries = []
        self.lost = 0

    def select(self, kinds=None) -> list:
        """The entries of the given kinds, oldest first. `None` means all of them."""
        if not kinds:
            return list(self.entries)
        wanted = set(kinds)
        return [e for e in self.entries if e.kind in wanted]

    def text(self, kinds=None) -> str:
        """The visible feed as plain text — what «Копировать» and «Сохранить» hand over."""
        return "\n".join(line(e) for e in self.select(kinds))

    def __len__(self) -> int:
        return len(self.entries)
