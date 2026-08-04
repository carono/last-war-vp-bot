r"""The game's clock — the one every timestamp the game hands out is stamped on.

It is not this computer's clock, and the difference is not academic: measured live on
2026-08-04 the game ran **twelve seconds ahead** of a PC that was itself within two
seconds of real UTC, and the operator had been reading 25-30 s of that drift as a
countdown that disagreed with the one the game draws beside it (task #1227).

What is tested here is the whole of the correction:

  * a sample sets an offset, charged to the middle of the round trip;
  * `now_ms()` moves with it, and an unsynced module is exactly `time.time()`;
  * a nonsense sample is refused rather than believed — a clock moved to 1970 would
    make every tile on the map read as raidable at once;
  * `SecretTask.can_loot` / `.pending` follow it, which is the point: those two ARE
    the comparison «has this dispatch finished yet», and being seconds behind the
    game's own answer is how a robbery is aimed at a tile that is not ready — or not
    aimed at one that is;
  * the reads that already talk to the VM carry the measurement, so nothing pays for
    a round trip of its own.

    C:\Python312\python.exe tests\test_game_clock.py
    python3 tests/test_game_clock.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_clock  # noqa: E402
import lastwar_proto as proto  # noqa: E402
import lua_actions  # noqa: E402


def _task(done_offset_ms: int) -> proto.SecretTask:
    """A tile whose dispatch finishes `done_offset_ms` from now, on the LOCAL clock."""
    now = int(time.time() * 1000)
    return proto.SecretTask(
        uuid=1, server_id=534, x=1, y=2, level=7, cfg_id=60000701, family="6000",
        looted_by=(), owner_uid="u", alliance_id="a",
        expires_at=now + 3_600_000, completed_at=now + done_offset_ms)


def test_an_unmeasured_clock_is_the_local_one():
    game_clock.reset()
    assert game_clock.synced() is False
    assert game_clock.offset_ms() == 0
    assert abs(game_clock.now_ms() - int(time.time() * 1000)) < 50


def test_a_sample_is_charged_to_the_middle_of_the_round_trip():
    game_clock.reset()
    sent = time.time()
    back = sent + 2.0                       # a slow round trip: the read is at +1.0 s
    server_ms = int((sent + 1.0) * 1000) + 12_000
    offset = game_clock.note(server_ms, sent, back)
    assert 11_900 <= offset <= 12_100, offset
    assert game_clock.synced() is True
    assert game_clock.age_seconds() < 5
    game_clock.reset()


def test_a_nonsense_sample_is_refused():
    """A zero (a client that has not logged in) must not move the clock to 1970."""
    game_clock.reset()
    game_clock.note(5_000, time.time(), time.time())
    kept = game_clock.offset_ms()
    assert game_clock.note(0, time.time(), time.time()) == kept
    assert game_clock.note(-1, time.time(), time.time()) == kept
    game_clock.reset()


def test_the_raid_gate_follows_the_games_clock():
    """`can_loot` and `pending` are judged on the game's now, not the machine's."""
    game_clock.reset()
    soon = _task(20_000)                    # finishes in 20 s by this PC's reckoning
    assert soon.can_loot is False
    assert soon.pending is True             # …and is inside the ten-minute window

    try:
        # The game's clock is half a minute ahead: by ITS reckoning the dispatch is done.
        game_clock.note(int((time.time() + 30) * 1000), time.time(), time.time())
        assert soon.can_loot is True, "the local clock was still deciding the raid gate"
        assert soon.pending is False        # the two stay mutually exclusive
    finally:
        game_clock.reset()


def test_the_line_is_parsed_out_of_a_read_that_carries_it():
    """The tile reads open with `ACT NOW=<seconds>`, so a list is judged on the clock
    it was read with — no round trip of its own."""
    assert game_clock.parse(["ACT NOW=1785840599", "ACT VT uuid=1"]) == 1785840599
    assert game_clock.parse(["ACT NOW=1785840599.0"]) == 1785840599
    assert game_clock.parse(["ACT VT uuid=1"]) is None
    assert game_clock.parse([]) is None
    for chunk in (lua_actions.secret_task_all_alliance(),
                  lua_actions.secret_task_raidable_alliance(),
                  lua_actions.game_server_time()):
        assert "getServerTime" in chunk and "ACT NOW=" in chunk, chunk


def test_a_checkpoint_caught_mid_flush_is_read_again_not_raised(tmp=None):
    """The capture rewrites its checkpoint in place, so a poller sees half a file.

    That used to cost the auto-loot the whole tick — «ошибка опроса скана», and nothing
    robbed until the next poll (#1227).
    """
    import json
    import tempfile

    path = Path(tempfile.mkdtemp()) / "tasks.json"
    good = json.dumps([dict(_task(-60_000).as_dict(), seen_at=int(time.time()))])
    path.write_text('[{"uuid": 1,', encoding="utf-8")          # caught mid-write

    real_sleep, flips = time.sleep, []

    def _finish_the_write(_seconds):
        flips.append(1)
        path.write_text(good, encoding="utf-8")

    time.sleep = _finish_the_write
    try:
        tasks = proto.load_fresh_tasks(str(path))
    finally:
        time.sleep = real_sleep
    assert flips, "the broken read was not retried at all"
    assert len(tasks) == 1, tasks


if __name__ == "__main__":
    failed = 0
    for _name, _fn in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_fn):
            continue
        try:
            _fn()
            print("  ok   %s" % _name)
        except AssertionError as exc:
            failed += 1
            print("  FAIL %s: %s" % (_name, exc))
    print("\n%d passed" % (len([n for n in globals() if n.startswith("test_")]) - failed))
    raise SystemExit(1 if failed else 0)
