r"""Unit tests for the account list — the cache trimmed down to the characters.

The game hands over a cache of every login it has ever made, so one character sits
in there once per server it has ever been on, and a character made and abandoned
sits there for good (see `docs/research/account-list.md`). These tests pin down the
rule that turns that into the list of characters, on the six rows a live client
actually held, and they need no game: the reader is fed the log lines the Lua side
prints.

    python3 tests/test_account_list.py         # standalone, prints PASS/FAIL
    pytest tests/test_account_list.py          # or under pytest

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import account_switch  # noqa: E402


def _row(seq, serverid, uid, level, current=False, nickname="n"):
    """One cache row in the shape `read_accounts()` produces."""
    return {"seq": seq, "serverid": serverid, "gameUid": uid, "level": level,
            "nickname": nickname, "zone": f"APS{serverid}", "env": "Online",
            "is_current": current}


def _servers(rows):
    return [r["serverid"] for r in rows]


# The cache of a live client on 2026-08-02: two characters, six rows. `Carono`
# (uid ends in 972, the server it was made on) has since moved to 935 and been
# pulled through 1012 and the 8118 event server; 2105 was made and never played.
_LIVE = [
    _row(1, 2105, "1092741133002105", 0, nickname="Игрок 1aada2105"),
    _row(2, 1012, "1522777203000972", 35, nickname="Carono"),
    _row(3, 972, "1522777203000972", 35, nickname="Carono"),
    _row(4, 8118, "1522777203000972", 35, nickname="Carono"),
    _row(5, 509, "2146058428000509", 21, nickname="Игрок 3464d509"),
    _row(6, 935, "1522777203000972", 35, current=True, nickname="Carono"),
]


# --------------------------------------------------------------------------
# playable_accounts
# --------------------------------------------------------------------------

def test_the_live_cache_comes_down_to_the_two_characters_it_holds():
    """Six rows, two characters: the one in play on 935 and the one on 509."""
    assert _servers(account_switch.playable_accounts(_LIVE)) == [509, 935]


def test_one_character_keeps_the_server_it_is_on_now():
    """Same gameUid on four servers is one character, listed where it is today."""
    kept = account_switch.playable_accounts(_LIVE)
    carono = [r for r in kept if r["gameUid"] == "1522777203000972"]
    assert len(carono) == 1 and carono[0]["serverid"] == 935


def test_a_character_that_never_reached_level_one_is_left_out():
    """HQ 0 means made and abandoned, or since deleted — nothing to switch to."""
    assert 2105 not in _servers(account_switch.playable_accounts(_LIVE))


def test_without_a_current_row_the_freshest_login_wins():
    """Read before curServerId is known: position in the cache is the recency."""
    rows = [_row(1, 972, "u1", 35), _row(2, 935, "u1", 35), _row(3, 509, "u2", 21)]
    assert _servers(account_switch.playable_accounts(rows)) == [935, 509]


def test_the_character_in_play_outranks_a_staler_row_of_a_higher_level():
    """A stale row may carry a level read long ago; being in play settles it."""
    rows = [_row(1, 972, "u1", 35), _row(2, 935, "u1", 30, current=True)]
    assert _servers(account_switch.playable_accounts(rows)) == [935]


def test_a_level_zero_character_that_is_being_played_stays():
    """A brand-new character is level 0 until its HQ level is read — keep it."""
    rows = [_row(1, 700, "u9", 0, current=True)]
    assert _servers(account_switch.playable_accounts(rows)) == [700]


def test_two_characters_are_never_merged():
    """Different gameUid is a different character, whatever the servers are."""
    rows = [_row(1, 935, "u1", 35, current=True), _row(2, 935, "u2", 21)]
    assert len(account_switch.playable_accounts(rows)) == 2


def test_an_empty_cache_stays_empty():
    assert account_switch.playable_accounts([]) == []


# --------------------------------------------------------------------------
# read_accounts — the parse, and where the trim sits
# --------------------------------------------------------------------------

class _FakeEval:
    """Replays the lines the reader's Lua prints, in the game's own format."""

    def __init__(self, lines):
        self._lines = lines

    def run(self, lua, marker, settle):        # noqa: ARG002 — signature only
        return list(self._lines)


def _hex(s: str) -> str:
    return s.encode("utf-8").hex()


def _line(seq, serverid, uid, level, nick="Carono", zone="", env="Online"):
    return (f"ACT A seq={seq} serverid={serverid} gameUid={uid} level={level} "
            f"nick={_hex(nick)} zone={_hex(zone or f'APS{serverid}')} env={_hex(env)}")


_LIVE_LINES = [
    "ACT cur=935",
    _line(1, 2105, "1092741133002105", 0, nick="Игрок 1aada2105", env="Online: 0"),
    _line(2, 1012, "1522777203000972", 35),
    _line(3, 972, "1522777203000972", 35),
    _line(4, 8118, "1522777203000972", 35),
    _line(5, 509, "2146058428000509", 21, nick="Игрок 3464d509"),
    _line(6, 935, "1522777203000972", 35),
]


def test_read_accounts_trims_by_default():
    """What the panel draws is the characters, current one first."""
    rows = account_switch.read_accounts(_FakeEval(_LIVE_LINES))
    assert _servers(rows) == [935, 509]
    assert rows[0]["is_current"] and not rows[1]["is_current"]


def test_read_accounts_keeps_the_whole_cache_when_asked():
    """`--all` is what the cache was read with to work the rule out."""
    rows = account_switch.read_accounts(_FakeEval(_LIVE_LINES), keep_stale=True)
    assert len(rows) == 6
    assert _servers(rows)[0] == 935          # current first, then level, then server


def test_read_accounts_decodes_the_names_and_the_cache_position():
    rows = account_switch.read_accounts(_FakeEval(_LIVE_LINES))
    by_server = {r["serverid"]: r for r in rows}
    assert by_server[935]["nickname"] == "Carono"
    assert by_server[935]["seq"] == 6        # the freshest login of that character
    assert by_server[509]["nickname"] == "Игрок 3464d509"
    assert by_server[509]["zone"] == "APS509"


def test_a_silent_game_reads_as_no_accounts():
    """No daemon, no game, or the manager not loaded yet — an empty tab, no crash."""
    assert account_switch.read_accounts(_FakeEval([])) == []


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
