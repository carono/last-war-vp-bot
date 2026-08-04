r"""The game's clock — the one every timestamp the game hands out is stamped on.

It is not this computer's clock, and the difference is not academic: measured live on
2026-08-04 the two were **eleven seconds apart**, with the PC the slow one, and the
operator had been reading 25-30 s of that drift as a countdown that disagreed with
the one the game draws beside it (task #1227).

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
    """The tile reads open with the game's clock, so a list is judged on the clock it
    was read with — and no read pays a round trip of its own."""
    assert game_clock.parse_ms(["ACT NOWMS=1785840599123", "ACT VT uuid=1"]) \
        == 1785840599123
    assert game_clock.parse_ms(["ACT NOWMS=1785840599123.0"]) == 1785840599123
    # The whole-second fallback, for a chunk written before the millisecond one.
    assert game_clock.parse_ms(["ACT NOW=1785840599"]) == 1785840599000
    assert game_clock.parse_ms(["ACT VT uuid=1"]) is None
    assert game_clock.parse_ms([]) is None
    # Every read that talks to the VM carries it, and asks the manager the client's own
    # countdown uses — with `ChatInterface` kept as the fallback behind it.
    for chunk in (lua_actions.secret_task_all_alliance(),
                  lua_actions.secret_task_raidable_alliance(),
                  lua_actions.game_server_time()):
        assert "UITimeManager" in chunk and "ACT NOWMS=" in chunk, chunk
        assert "getServerTime" in chunk, chunk


def test_a_client_at_the_login_screen_is_not_believed():
    """A game that has not logged in answers with its own uptime, and cheerfully.

    Measured on the second client (#1227): `UITimeManager:GetServerTime()` = 6 280 648
    — an hour and three quarters of process uptime, not a clock — with
    `serverDeltaTime` still 0. Believing it would put the game's clock in 1970 and make
    every tile on the map read as expired since the Carter administration. And it is
    the same read that answers "no alliance tasks, own server -1, all five robberies
    still yours", every one of them a plausible-looking lie.
    """
    class _LoginScreen:
        def run(self, _chunk, _marker=None, _settle=1.0):
            return ["ACT NOWMS=6280648"]           # uptime, not a clock

    class _Session:
        def run(self, _chunk, _marker=None, _settle=1.0):
            return ["ACT NOWMS=%d" % int(time.time() * 1000)]

    assert game_clock.plausible(6_280_648) is False
    assert game_clock.plausible(0) is False
    assert game_clock.plausible(int((time.time() + 9 * 3600) * 1000)) is False
    assert game_clock.plausible(int(time.time() * 1000)) is True

    game_clock.reset()
    try:
        assert game_clock.read(_LoginScreen()) is None
        assert game_clock.session_ready(_LoginScreen()) is False
        assert game_clock.offset_ms() == 0, "an uptime moved the clock"
        assert game_clock.session_ready(_Session()) is True
    finally:
        game_clock.reset()


def test_a_read_with_no_clock_in_it_is_a_client_that_cannot_answer():
    """The VM reads raise rather than return an empty list — the two mean different
    things, and telling them apart is the whole point (#1227)."""
    import steal_secret_task as steal

    class _LoginScreen:
        def run(self, _chunk, _marker=None, _settle=1.0):
            return []                              # no clock, no tasks, no error

    try:
        steal._vm_all_alliance_tasks(_LoginScreen())
    except steal.NotLoggedIn:
        pass
    else:
        raise AssertionError("an empty read passed for a logged-in client")


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
