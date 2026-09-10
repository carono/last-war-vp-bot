r"""THE MONSTER FOLLOW IS AN EAR, NOT A CLOCK (#2711).

WHAT THIS FILE IS FOR. «poll_world_monsters слишком часто выполняется, и возможно
занимает панель» — and it did. `ensure_loaded` armed `secret_monster_follow` at BOOT,
every tick re-armed it in a `finally`, and the box's floor is five seconds, so a profile
with «Следить за картой» ticked asked the game about **720 times an hour, whether or not
anybody had ever opened the tab** — and on a client sitting in its base every one of
those was a round trip spent discovering that there was nothing to read.

`CLAUDE.md` has one rule about that shape («Read once, then LISTEN»), and the reason it
could be obeyed here is a measurement rather than a preference: a monster is never on the
wire, but the GROUND is, and the register is fed by the client LOADING ground. So
`world.get.block` — an answer the profile's one ear already hears — is exactly the event
the clock was guessing at.

What is pinned here, because each of these is a way the old shape could come back:

  * the box being off means NO subscription at all, and the box being on means exactly
    two: `bus.GAME_READY` and the ground on the wire;
  * a fire NEVER re-arms itself. That is the whole difference between an ear and a
    clock, and it is one `finally` away from being undone;
  * a BURST of ground answers costs one booking, not thirty;
  * a read is not taken when somebody else is holding the client — it is dropped, with
    the reason on the ledger, and it is not queued behind them;
  * and the seconds box is a FLOOR between two reads, never a period that counts down.

Needs no display: tkinter is stubbed, so this runs under a bare interpreter.

    python3 tests/test_panel_monster_follow.py
"""
from __future__ import annotations

TIER = "pure"      # tkinter is stubbed below — no display, no widgets, no game

import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src", _REPO / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from test_panel_monster_filter import _stub_tk                # noqa: E402

_stub_tk()

from panel.runtime import bus                                 # noqa: E402
from panel.tabs.secret_tasks.tab import SecretTasksTab        # noqa: E402


# ---------------------------------------------------------------------------
# the smallest thing the follow can be asked of: a `self` with the five names it
# touches. Binding the unbound methods keeps the whole tab — and a display — out of it.
# ---------------------------------------------------------------------------
class _Var:
    def __init__(self, value=False):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Ticker:
    def __init__(self):
        self.armed: dict = {}
        self.arms = 0
        self.disarmed: list = []

    def arm(self, name, ms, call):
        self.arms += 1
        self.armed[name] = (ms, call)

    def disarm(self, name):
        self.disarmed.append(name)
        self.armed.pop(name, None)


class _Ledger:
    def __init__(self):
        self.reasons: list = []

    def dropped(self, n=1, reason=""):
        self.reasons.append(reason)

    def seen(self, n=1):
        pass

    def kept(self, n=1):
        pass


class _Bus:
    def __init__(self):
        self.topics: list = []

    def subscribe(self, topic, func):
        self.topics.append(topic)

        def _off():
            self.topics.remove(topic)
        return _off


class _Wire(_Bus):
    pass


class _Game:
    def __init__(self, ready=True, holder=None):
        self._ready = ready
        self._holder = holder

    def ready(self):
        return self._ready

    def claimed_by(self):
        return self._holder


class _Follow:
    """A stand-in tab carrying only what the follow touches."""

    def __init__(self, on=False, ready=True, holder=None, secs=20):
        self.monsters = types.SimpleNamespace(follow_var=_Var(on),
                                              follow_seconds=lambda: secs)
        self.bus, self.wire, self.tick = _Bus(), _Wire(), _Ticker()
        self.rt = types.SimpleNamespace(bus=self.bus, wire=self.wire, tick=self.tick,
                                        game=_Game(ready, holder))
        self._monster_offs: list = []
        self._monster_next = 0.0
        self._monster_busy = False
        self._monster_busy_tries = 0
        self.ledger = _Ledger()
        self.posted: list = []
        self.started = 0

    # the four names the methods reach for on `self`
    def take(self, _name):
        return self.ledger

    def post(self, call):
        self.posted.append(call)

    def _monster_follow_work(self):
        self.started += 1

    # …and the methods under test, borrowed off the real class UNDER THEIR OWN NAMES —
    # they call one another, so an alias alone would leave the chain hanging.
    _monster_follow_sync = sync = SecretTasksTab._monster_follow_sync
    _monster_ground_moved = moved = SecretTasksTab._monster_ground_moved
    _monster_arm = arm = SecretTasksTab._monster_arm
    _monster_follow_fire = fire = SecretTasksTab._monster_follow_fire
    MONSTER_SETTLE_MS = SecretTasksTab.MONSTER_SETTLE_MS
    MONSTER_GROUND = SecretTasksTab.MONSTER_GROUND
    MONSTER_BUSY_RETRY_MS = SecretTasksTab.MONSTER_BUSY_RETRY_MS
    MONSTER_BUSY_TRIES = SecretTasksTab.MONSTER_BUSY_TRIES


# ---------------------------------------------------------------------------
# the switch IS the subscription
# ---------------------------------------------------------------------------
def test_the_box_off_listens_to_nothing_at_all():
    """A profile that never asked for this must cost the game and the ear NOTHING."""
    tab = _Follow(on=False)
    tab.sync()
    assert tab.bus.topics == [] and tab.wire.topics == []
    assert tab._monster_offs == []
    assert tab.tick.arms == 0, "the follow armed a clock with the box off"


def test_the_box_on_listens_to_the_ground_and_to_getting_into_the_game():
    tab = _Follow(on=True)
    tab.sync()
    assert tab.bus.topics == [bus.GAME_READY]
    assert tab.wire.topics == ["world.get.block"]
    assert tab.tick.arms == 0, "opening the ear must not arm anything by itself"


def test_unticking_the_box_shuts_the_ear_and_disarms_the_booking():
    tab = _Follow(on=True)
    tab.sync()
    tab.monsters.follow_var.set(False)
    tab.sync()
    assert tab.bus.topics == [] and tab.wire.topics == []
    assert "secret_monster_follow" in tab.tick.disarmed


def test_syncing_twice_does_not_subscribe_twice():
    tab = _Follow(on=True)
    tab.sync()
    tab.sync()
    assert len(tab.wire.topics) == 1


# ---------------------------------------------------------------------------
# a fire books nothing — the difference between an ear and a clock
# ---------------------------------------------------------------------------
def test_a_fire_never_re_arms_itself():
    """THE POINT OF #2711. The old chain re-armed in a `finally`, so nothing that
    happened — the box off, no client, a read that failed — could ever stop it."""
    tab = _Follow(on=True)
    tab.sync()
    tab.fire()
    assert tab.started == 1
    assert tab.tick.armed == {}, "the read booked another read"


def test_a_fire_that_is_refused_books_nothing_either():
    for tab in (_Follow(on=False), _Follow(on=True, ready=False)):
        tab.sync()
        tab.fire()
        assert tab.started == 0
        assert tab.tick.armed == {}


# ---------------------------------------------------------------------------
# a burst of ground is ONE read
# ---------------------------------------------------------------------------
def test_thirty_ground_answers_book_one_read():
    """A person panning the map loads dozens of blocks a second and the ear hears every
    answer. One booking, re-armed — never thirty."""
    tab = _Follow(on=True)
    tab.sync()
    for _ in range(30):
        tab.moved()
    assert len(tab.posted) == 30, "the wire callback must not touch the ticker itself"
    for call in tab.posted:
        call()
    assert list(tab.tick.armed) == ["secret_monster_follow"]
    assert tab.tick.armed["secret_monster_follow"][0] == _Follow.MONSTER_SETTLE_MS


def test_the_seconds_box_is_a_floor_between_two_reads():
    """It no longer counts anything down: it only says how close together two answers
    may be. A read just taken pushes the next booking out to it."""
    tab = _Follow(on=True, secs=30)
    tab.sync()
    tab.fire()
    tab.moved()
    tab.posted[-1]()
    waited = tab.tick.armed["secret_monster_follow"][0]
    assert waited > _Follow.MONSTER_SETTLE_MS, waited
    assert waited <= 30_000, waited


def test_a_move_with_the_box_off_books_nothing():
    tab = _Follow(on=False)
    tab.moved()
    tab.posted[-1]()
    assert tab.tick.armed == {}


# ---------------------------------------------------------------------------
# …and it steps aside for whoever is doing work
# ---------------------------------------------------------------------------
def test_the_read_yields_to_anybody_holding_the_client():
    """«Сделай этот сценарий прозрачным»: a nicety on a page nobody may be looking at
    does not queue behind a rally join. It drops, says why — and offers itself again a
    bounded number of times rather than waiting for ground that may never come (#2740)."""
    tab = _Follow(on=True, holder="default/join_rally")
    tab.sync()
    tab.fire()
    assert tab.started == 0
    assert tab.ledger.reasons == ["game_busy"]
    assert "secret_monster_follow" in tab.tick.armed, (
        "a reading stepped aside for a busy client was dropped for ever — "
        "«занята панель» then reads as «монстров нет»")


def test_a_busy_client_is_not_asked_for_ever():
    """The retry is BOUNDED: a client held all day costs a handful of claim lookups and
    no round trip at all, rather than a clock nobody asked for (#2740)."""
    tab = _Follow(on=True, holder="default/join_rally")
    tab.sync()
    for _ in range(tab.MONSTER_BUSY_TRIES + 3):
        tab.tick.armed.pop("secret_monster_follow", None)
        tab.fire()
    assert tab.started == 0
    assert tab.tick.armed == {}, "the bounded retry never stopped"


def test_fresh_ground_starts_the_count_again():
    """A walk is a new question, not the old one asked louder — so it clears the count
    and the reading gets its full allowance again (#2740)."""
    tab = _Follow(on=True, holder="default/join_rally")
    tab.sync()
    for _ in range(tab.MONSTER_BUSY_TRIES + 2):
        tab.tick.armed.pop("secret_monster_follow", None)
        tab.fire()
    assert tab.tick.armed == {}
    tab.arm()                                    # a block of ground arrived
    tab.tick.armed.pop("secret_monster_follow", None)
    tab.fire()
    assert "secret_monster_follow" in tab.tick.armed


def test_a_free_client_is_read_without_waiting():
    tab = _Follow(on=True, holder=None)
    tab.sync()
    tab.fire()
    assert tab.started == 1 and tab.ledger.reasons == []


def _run() -> int:
    bad = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
            print(f"  ok   {name}")
        except Exception as exc:                          # noqa: BLE001 — a report
            bad += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    total = sum(1 for n in globals() if n.startswith("test_"))
    print(f"\n{total - bad}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_run())
