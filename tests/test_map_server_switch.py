r"""One jump costs ONE server switch, however many times the client announces it (#1416).

A capture drops everything it has indexed for the server being left
(`MapIndex.on_server_left`), because a secret task's dispatch timer keeps ticking and a
tile nobody is looking at any more would go on reading as raidable. That is right once
the map really has moved, and it is what made two of this task's four symptoms:

    12:54:51 [coord] переход в #902 X:500 Y:500
    12:54:52 [secret] server 901 -> 902 — dropped everything indexed for 901
    12:54:52 [secret] server 902 -> 903 — dropped everything indexed for 902
    12:54:52 [secret] server 903 -> 904 — dropped everything indexed for 903
    12:54:52 [secret] server 904 -> 902 — dropped everything indexed for 904
    12:54:52 [secret]   …running — server 902, … 0 task(s), 0 star(s)

One jump, four announcements, four evictions — and the 1565 tasks / 101 stars a lap of
the map had just paid for were gone. The operator sees «обход карты не сработал с
первого раза» and «секретки не обновляются».

So `meteorite.enter.world` is INTENT now: remembered, and applied when the map confirms
it with a block of its own, or when its grace window runs out (the minimap click, which
lands on cached ground and asks the server for nothing). Either way, one switch.

No wire, no npcap, no game — the index is fed decoded payloads directly::

    python3 tests/test_map_server_switch.py
    C:\Python312\python.exe tests\test_map_server_switch.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import map_capture                                        # noqa: E402


class _Index(map_capture.MapIndex):
    """A MapIndex that only remembers what it was told to forget."""

    def __init__(self) -> None:
        super().__init__()
        self.left: list = []

    def on_server_left(self, server: int) -> None:
        self.left.append(server)


def _jump(index, server: int) -> None:
    """What the client sends BEFORE it moves — the announcement, not the move."""
    index._note_jump({"targetServerId": server})


def _blocks(index, server: int, points: int = 1) -> None:
    """A map response for `server`, straight into the index's own hook."""
    blocks = [{"serverId": server,
               "points": [{"_protobuf": {"f2": 17}} for _ in range(points)]}]
    servers = map_capture.block_servers(blocks)
    with index._index_lock:
        now = time.time()
        index._confirm_declared(servers, now)
        if now < index._jump_grace_until:
            servers = [s for s in servers if s == index.current_server]
        index._votes.extend((now, s) for s in servers)
        viewing = index._elect(now)
        if viewing is not None:
            index._switch_to(viewing)
        index.on_blocks({}, blocks, now)


def test_a_burst_of_announcements_costs_one_switch():
    """The live case, to the number: 901 → (902, 903, 904, 902) → one eviction."""
    index = _Index()
    index.current_server = 901
    for server in (902, 903, 904, 902):
        _jump(index, server)
    assert index.current_server == 901, \
        "an announcement nothing has confirmed must not move the screen yet"
    assert index.left == [], f"nothing was confirmed, so nothing may be evicted: {index.left}"

    _blocks(index, 902)                      # the map arrives on the server it went to
    assert index.current_server == 902, "the confirming response must apply the jump"
    assert index.left == [901], \
        f"one jump is one eviction, of the server actually left: {index.left}"
    assert index.drain_server_changes() == [(901, 902)], "one switch, said once"


def test_a_confirmed_jump_keeps_the_new_server():
    """The stragglers the old server was still sending must not take the screen back."""
    index = _Index()
    index.current_server = 901
    _jump(index, 902)
    _blocks(index, 902)
    for _ in range(map_capture.SERVER_VOTE_MIN + 2):
        _blocks(index, 901)                  # in-flight responses from the map we left
    assert index.current_server == 902, "a settled jump must survive the old map's tail"
    assert index.left == [901], f"and cost no further eviction: {index.left}"


def test_an_unconfirmed_jump_is_honoured_when_its_grace_runs_out():
    """The minimap click: it asks for no block, so the clock is the only witness."""
    index = _Index()
    index.current_server = 901
    _jump(index, 903)
    with index._index_lock:                  # the grace window, expired
        index._jump_grace_until = time.time() - 1.0
        index._confirm_declared((), time.time())
    assert index.current_server == 903, "an unconfirmed announcement is still the truth"
    assert index.left == [901], f"and it evicts exactly once: {index.left}"


def test_an_announcement_of_where_we_already_are_cancels_a_pending_one():
    """A burst that ends where it started must not move anything at all."""
    index = _Index()
    index.current_server = 901
    _jump(index, 902)
    _jump(index, 901)                        # the client changed its mind mid-burst
    _blocks(index, 901)
    assert index.current_server == 901, "no move was made, so none may be reported"
    assert index.left == [], f"and nothing may be evicted: {index.left}"


def test_the_election_still_follows_a_dragged_map():
    """Nothing above touches the ordinary path: weight of traffic still decides."""
    index = _Index()
    index.current_server = 901
    for _ in range(map_capture.SERVER_VOTE_MIN + 1):
        _blocks(index, 905)
    assert index.current_server == 905, "a dragged map must still take the screen"
    assert index.left == [901]


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
