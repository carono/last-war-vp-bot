r"""The alliance duel read: both sides, every day, and which side is ours (#1304).

`tools/lib/vs_duel.py` turns what the client emits — a head line, a line per side, a
line per batch of ranking rows — into rows the ranking history can store. What is pinned
here is the part that is a JUDGEMENT rather than a copy:

  * **which side is «ours»** is derived from the opponent the duel names, and is left
    EMPTY when it cannot be told. A guessed side is worse than none: it looks answered.
  * **a day is its own board**, so a finished day dedups against itself instead of being
    rewritten every time the running day moves.
  * **the running day is not in `scoreHistory`** — it is only in `alScore` — so the side
    rows are filed under today rather than under «no day».
  * a line the reader does not understand is kept as `unread`, never dropped.

Every value below is invented and looks it. No wire, no game::

    python3 tests/test_vs_duel.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import vs_duel  # noqa: E402

M = vs_duel.MARKER

#: Two invented alliances. Thirty-two hex characters is the shape the game uses; these
#: are plainly not real ones, which is the point.
OURS = "a" * 32
THEIRS = "b" * 32

HEAD = (f'{M} head {{"target_alliance_id":"{THEIRS}","target_server_id":902,'
        f'"weekday_index":3,"min_day_score":200000,"min_week_score":600000,'
        f'"my_alliance_score":500,"enemy_alliance_score":400}}')

SIDES = [
    f'{M} rows side {OURS} [{{"allianceId":"{OURS}","alName":"Alliance One",'
    f'"abbr":"AL1","serverId":901,"alScore":500,"win":2,"power":1000,'
    f'"mvp_uid":"1000000000000001","mvp_name":"Player1"}}]',
    f'{M} rows sideday {OURS} [{{"day":1,"score":110}},{{"day":2,"score":120}}]',
    f'{M} rows side {THEIRS} [{{"allianceId":"{THEIRS}","alName":"Alliance Two",'
    f'"abbr":"AL2","serverId":902,"alScore":400,"win":0,"power":900}}]',
    f'{M} rows sideday {THEIRS} [{{"day":1,"score":100}},{{"day":2,"score":90}}]',
]

PLAYERS = [
    f'{M} rows day 1 [{{"uid":1000000000000001,"name":"Player1","aid":"{OURS}",'
    f'"abbr":"AL1","serverId":901,"score":60,"position":1,"day":1}},'
    f'{{"uid":1000000000000002,"name":"Player2","aid":"{THEIRS}","abbr":"AL2",'
    f'"serverId":902,"score":50,"position":2,"day":1}}]',
    f'{M} rows day 2 [{{"uid":1000000000000001,"name":"Player1","aid":"{OURS}",'
    f'"abbr":"AL1","serverId":901,"score":70,"position":1,"day":2}}]',
    f'{M} rows rank 1 [{{"uid":1000000000000001,"name":"Player1","aid":"{OURS}",'
    f'"abbr":"AL1","serverId":901,"score":130,"position":1}}]',
]

LINES = [HEAD] + SIDES + PLAYERS + [f"{M} done"]


def _state():
    return vs_duel.parse(LINES)


def test_the_read_comes_apart_into_head_sides_and_players():
    state = _state()
    assert state["head"]["target_server_id"] == 902
    assert len(state["sides"]) == 2
    assert len(state["side_days"]) == 4            # two days, two sides
    assert len(state["players"]) == 4              # 2 + 1 daily, 1 standing
    assert state["unread"] == []


def test_our_side_is_the_one_the_duel_does_not_name_as_the_opponent():
    state = _state()
    assert vs_duel.own_alliance_id(state) == OURS
    assert vs_duel.side_of(state, OURS) == "own"
    assert vs_duel.side_of(state, THEIRS) == "enemy"


def test_with_no_opponent_named_no_row_is_given_a_side():
    """A bye week, or a head that never arrived — an empty column, never a guess."""
    state = vs_duel.parse([line for line in LINES if not line.startswith(f"{M} head")])
    assert vs_duel.own_alliance_id(state) is None
    assert vs_duel.side_of(state, OURS) is None
    rows = vs_duel.store_records(state, seen_at=1)
    assert all(row["side"] is None for row in rows)


def test_both_sides_are_in_the_one_ranking_and_come_out_marked():
    rows = vs_duel.store_records(_state(), seen_at=1)
    day_one = [r for r in rows if r["day"] == 1 and r["scope"] == "player"]
    assert sorted(r["side"] for r in day_one) == ["enemy", "own"]
    assert {r["alliance"] for r in day_one} == {"AL1", "AL2"}


def test_a_day_is_its_own_board_and_the_standing_week_is_another():
    rows = vs_duel.store_records(_state(), seen_at=1)
    boards = {r["leaderboard"] for r in rows}
    assert "al.battle.rank.info/type=0/day=1" in boards
    assert "al.battle.rank.info/type=0/day=2" in boards
    assert "al.battle.rank.info/type=1" in boards


def test_the_running_day_is_filed_under_today_not_under_no_day():
    """`alScore` is TODAY's — `scoreHistory` only holds the days that have finished."""
    rows = vs_duel.store_records(_state(), seen_at=1)
    sides = [r for r in rows if r["scope"] == "alliance"]
    today = [r for r in sides if r["score_field"] == "alScore"]
    assert len(today) == 2                          # one per side
    assert {r["day"] for r in today} == {3}         # the head's weekday_index
    assert all(r["day"] is not None for r in sides)


def test_the_original_row_travels_with_every_record():
    rows = vs_duel.store_records(_state(), seen_at=1)
    player = next(r for r in rows if r["scope"] == "player")
    assert player["raw"]["uid"] == 1000000000000001
    assert player["source"] == "game"


def test_a_line_nobody_understands_is_kept_rather_than_dropped():
    state = vs_duel.parse(LINES + [f"{M} something-new 42"])
    assert state["unread"] and "something-new" in state["unread"][0]


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
