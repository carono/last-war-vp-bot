"""What the two recruit banners can do right now — the parser. **No Tk.**

**Nothing here is a memory and nothing here is a tick.** Whether a free pull is waiting,
when the next one comes, how many tickets are held — every one of them is the GAME's own
answer, read fresh (`actions/read_recruit_state.md`). The panel keeps no count of its
own on purpose: a pull made on the phone, or by the person playing on the screen in
front of them, would stop being counted the moment it did, and the board would be
confidently wrong rather than merely late.

The reading is one line of records separated by « | » — see the scenario for the
shape — and this module holds what each field MEANS. The tab holds the words and the
widgets.
"""
from __future__ import annotations

#: The scenario that reads both banners, and the variable it lands in.
READ_ACTION = "read_recruit_state"
READ_VARIABLE = "recruit"

#: The scenario one press plays. `kind` and `count` are its arguments.
DRAW_ACTION = "recruit_draw"

#: The banners, in the order they are drawn. These are the words the scenario's `kind`
#: argument takes, so the tab never invents a third one.
HERO = "hero"
WORKER = "worker"
KINDS = (HERO, WORKER)

#: The sizes a pull comes in. The game's own three: one, ten and a hundred.
COUNTS = (1, 10, 100)


class Banner:
    """One recruit banner as the game last answered for it.

    ``free`` is «available this moment» — the client's own gate, not arithmetic of ours
    over ``next_at``. ``next_at`` is when it comes back, epoch seconds, ``0`` when it is
    available now or when the banner has no free pull at all.
    """

    __slots__ = ("kind", "banner_id", "support", "free", "next_at", "item",
                 "have", "costs", "total", "limit")

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.banner_id = ""
        self.support = False
        self.free = False
        self.next_at = 0
        self.item = ""
        self.have = 0
        #: `{1: n, 10: n, 100: n}` — what each size costs in that ticket. A size the
        #: banner does not offer is `0`, and a button for it is dead rather than absent:
        #: «this banner has no hundred» is information, «no button» is a mystery.
        self.costs = {size: 0 for size in COUNTS}
        self.total = 0
        self.limit = 0

    def cost(self, count: int) -> int:
        return int(self.costs.get(count, 0) or 0)

    def affordable(self, count: int) -> bool:
        """Can this pull be paid for right now — free counts as paid for.

        The same question the press asks the game before it sends anything, asked here
        so a button that cannot work is drawn dead instead of failing when pressed.
        """
        if count == 1 and self.free:
            return True
        need = self.cost(count)
        return need > 0 and self.have >= need

    def seconds_left(self, now: float) -> int:
        """Seconds until the free pull comes back; `0` when it is here or unknown."""
        if self.free or not self.next_at:
            return 0
        return max(0, int(self.next_at - now))

    def __repr__(self) -> str:
        return f"<Banner {self.kind} free={self.free} have={self.have}>"


class Reading:
    """One answer from the game: both banners, when it was taken, or why it failed."""

    __slots__ = ("banners", "now", "error", "at")

    def __init__(self, banners=None, now: float = 0.0, error: str = "",
                 at: float = 0.0) -> None:
        #: `{kind: Banner}`. A banner the client could not answer for is ABSENT rather
        #: than empty — that is how «not logged in» tells itself apart from «no free
        #: pull today».
        self.banners = dict(banners or {})
        #: The game's own clock at the moment of the reading, epoch seconds.
        self.now = now
        self.error = error
        self.at = at

    def banner(self, kind: str):
        return self.banners.get(kind)

    def __repr__(self) -> str:
        return f"<Reading {sorted(self.banners)} error={self.error!r}>"


def _int(text: str) -> int:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def parse(raw, at: float = 0.0) -> Reading:
    """Turn what `read_recruit_state.md` said into a :class:`Reading`.

    A record the reading does not carry is simply not there — no defaults are invented,
    because «the client did not answer» and «the answer is zero» are different states
    and only one of them is worth pressing a button against.
    """
    if not raw:
        return Reading(error="empty", at=at)
    now = 0.0
    banners: dict = {}
    for record in str(raw).split("|"):
        fields = record.strip().split()
        if not fields:
            continue
        head = fields[0]
        if head.startswith("now="):
            now = float(_int(head[4:]))
            continue
        if head not in KINDS:
            continue
        banner = Banner(head)
        for token in fields[1:]:
            key, _, value = token.partition("=")
            if key == "id":
                banner.banner_id = value
            elif key == "support":
                banner.support = value == "1"
            elif key == "free":
                banner.free = value == "1"
            elif key == "next":
                banner.next_at = _int(value)
            elif key == "item":
                banner.item = value
            elif key == "have":
                banner.have = _int(value)
            elif key == "total":
                banner.total = _int(value)
            elif key == "limit":
                banner.limit = _int(value)
            elif key.startswith("c") and key[1:].isdigit():
                size = int(key[1:])
                if size in banner.costs:
                    banner.costs[size] = _int(value)
        banners[head] = banner
    if not banners:
        return Reading(now=now, error="no banners", at=at)
    return Reading(banners=banners, now=now, at=at)


def hhmm(seconds: int) -> str:
    """`1:04:33` / `4:33` — a countdown, never a date. `—` when there is nothing to count."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def ago(seconds: float) -> str:
    """How old a reading is, in the shortest honest form."""
    if seconds != seconds or seconds == float("inf"):    # noqa: PLR0124 — NaN / never
        return "—"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"
