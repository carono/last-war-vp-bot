r"""Unit tests for the player-sweep filters — `--level/--alliance/--name/--uid`.

Nothing here touches the network: the tiles and profiles are the shapes the
decoders already produce, so the filters can be pinned down without a game and
without a capture.

    python3 tests/test_player_filters.py        # standalone, prints PASS/FAIL
    pytest tests/test_player_filters.py         # or under pytest

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lastwar_proto as proto  # noqa: E402
from scan_players import PlayerIndex, uid_set  # noqa: E402


def _base(uid, name, level=30, alliance_abbr="VP", server_id=1234):
    return proto.PlayerBase(
        uid=str(uid), server_id=server_id, x=10, y=20, name=name, level=level,
        alliance_id="77", alliance_abbr=alliance_abbr, country="ru", uuid=5,
    )


def _tile(uid, name, level=30, alliance_abbr="VP", server_id=1234):
    """One `f2 = 6` point, as `player_bases()` reads it off the wire."""
    return {"_protobuf": {"f2": 6, "f1": 20 * 1000 + 10, "f100": 5,
                          "f102": server_id,
                          "f3": {"f1": uid, "f14": name, "f4": level,
                                 "f7": 77, "f15": alliance_abbr,
                                 "f27": "ru"}}}


def _blocks(*tiles):
    return {"serverPointArr": [{"maxAreaSize": 1000, "points": list(tiles)}]}


def _profile(uid, name, level=30, alliance_abbr="VP", server_id=1234):
    """One `get.user.info.multi` entry — what a click on a base answers with."""
    return {"uid": uid, "serverId": server_id, "name": name, "power": 5_000_000,
            "armyPower": 1, "armyKill": 2, "svipLevel": 3,
            "mainBuildingLevel": level, "allianceId": 77,
            "allianceAbbrName": alliance_abbr, "country": "ru"}


def _uids(players) -> set:
    return {p.uid for p in players}


# --------------------------------------------------------------------------
# proto.filter_players
# --------------------------------------------------------------------------

def test_name_is_a_case_insensitive_substring():
    players = [_base(1, "KotoPes"), _base(2, "Doggo"), _base(3, "кот")]
    assert _uids(proto.filter_players(players, name="kot")) == {"1"}
    assert _uids(proto.filter_players(players, name="KOTO")) == {"1"}
    # Cyrillic folds too — casefold(), not an ASCII-only lower().
    assert _uids(proto.filter_players(players, name="Кот")) == {"3"}
    # Surrounding whitespace is the shell's, not the player's, so it is
    # stripped off the needle before the match.
    assert _uids(proto.filter_players(players, name="  ogg ")) == {"2"}
    # Latin "kot" and Cyrillic "кот" are different text and must not cross.
    assert _uids(proto.filter_players(players, name="кот")) == {"3"}
    assert proto.filter_players(players, name="nobody") == []


def test_name_skips_a_base_that_carries_none():
    """`f14` is optional on the tile; a nameless base can match no name."""
    players = [_base(1, None), _base(2, "Doggo")]
    assert _uids(proto.filter_players(players, name="o")) == {"2"}
    # ...but it is still collected when no name filter was asked for.
    assert _uids(proto.filter_players(players)) == {"1", "2"}


def test_uid_is_exact_and_takes_a_list():
    players = [_base(1, "a"), _base(2, "b"), _base(12, "c")]
    assert _uids(proto.filter_players(players, uid="1")) == {"1"}
    assert _uids(proto.filter_players(players, uid={"1", "12"})) == {"1", "12"}
    # A number is accepted and compared as text — uid is an id, not a quantity.
    assert _uids(proto.filter_players(players, uid=2)) == {"2"}
    assert proto.filter_players(players, uid="999") == []


def test_filters_combine_as_and():
    players = [_base(1, "KotoPes", level=30), _base(2, "Kotik", level=25),
               _base(3, "Doggo", level=30, alliance_abbr="XX")]
    assert _uids(proto.filter_players(players, name="kot", level=30)) == {"1"}
    assert _uids(proto.filter_players(players, name="kot",
                                      uid={"2", "3"})) == {"2"}
    assert proto.filter_players(players, name="kot", alliance="XX") == []


def test_no_filter_keeps_everything():
    players = [_base(1, "a"), _base(2, "b")]
    assert _uids(proto.filter_players(players)) == {"1", "2"}


# --------------------------------------------------------------------------
# the CLI parser for --uid
# --------------------------------------------------------------------------

def test_uid_set_parses_a_list_and_refuses_an_empty_one():
    assert uid_set("123456") == {"123456"}
    assert uid_set(" 1 , 2 ,") == {"1", "2"}
    try:
        uid_set(" , ")
    except Exception as exc:                      # argparse.ArgumentTypeError
        assert "no uid" in str(exc), exc
    else:
        raise AssertionError("an empty --uid should be refused, not accepted")


# --------------------------------------------------------------------------
# PlayerIndex — the filters narrow what is *collected*, tiles and clicks alike
# --------------------------------------------------------------------------

def test_index_narrows_tiles_and_counts_the_rest_as_rejected():
    index = PlayerIndex(name="kot")
    index.on_blocks(_blocks(_tile(1, "KotoPes"), _tile(2, "Doggo"),
                            _tile(3, "Kotik")), None, time.time())
    assert _uids(index.bases) == {"1", "3"}
    assert index.rejected == 1


def test_index_narrows_clicked_profiles_the_same_way():
    """A click on someone outside the filter is dropped, not smuggled in."""
    index = PlayerIndex(uid={"8"})
    index.on_response(proto.PROFILE_COMMAND,
                      {"uids": [_profile(8, "KotoPes"), _profile(9, "Doggo")]})
    assert _uids(index.bases) == {"8"}
    assert (index.profiles_added, index.rejected) == (1, 1)


def test_index_merges_a_profile_onto_a_base_that_passed_the_filter():
    """Merging re-runs no filter: the record was already collected."""
    index = PlayerIndex(name="kot")
    index.on_blocks(_blocks(_tile(8, "KotoPes")), None, time.time())
    index.on_response(proto.PROFILE_COMMAND, {"uids": [_profile(8, "KotoPes")]})
    base, = index.bases
    assert (base.uid, base.x, base.y) == ("8", 10, 20)   # tile kept its ground
    assert base.power == 5_000_000                       # profile added its own
    assert index.profiles_merged == 1


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
