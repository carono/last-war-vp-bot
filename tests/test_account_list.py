r"""Unit tests for the account list — the characters, as the server reports them.

The tab asks the server (`account.login.new`) and draws what comes back in
`rolesList`; it does NOT draw the client's cache of logins, which holds one row per
server a character has ever connected to and was the whole of #1190. These tests
pin down both readers on the shapes a live client actually produced — six cache
rows for the two characters the server names — and need no game: the reader is fed
the log lines its Lua prints.

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


def _hex(s: str) -> str:
    return s.encode("utf-8").hex()


def _role(serverid, uid, level, nick, power=0, alliance=""):
    """One `rolesList` entry, as the roles reader prints it."""
    return (f"ACT R serverid={serverid} gameUid={uid} level={level} power={power} "
            f"nick={_hex(nick)} zone={_hex(f'APS{serverid}')} "
            f"alliance={_hex(alliance)}")


def _cached(seq, serverid, uid, level, nick, env="Online"):
    """One login-cache row, as the cache reader prints it."""
    return (f"ACT R seq={seq} serverid={serverid} gameUid={uid} level={level} "
            f"nick={_hex(nick)} zone={_hex(f'APS{serverid}')} env={_hex(env)}")


class _FakeEval:
    """Replays canned lines; records each chunk it was asked to run."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.ran: list[str] = []

    def run(self, lua, marker, settle):        # noqa: ARG002 — signature only
        self.ran.append(lua)
        return list(self._replies.pop(0)) if self._replies else []


# What the server answered on 2026-08-02: two characters, and nothing else.
_ROLES = [
    "ACT cur=935",
    _role(935, "1522777203000972", 35, "Carono", 241514404, "TLou"),
    _role(509, "2146058428000509", 21, "Игрок 3464d509", 4185296, "RBs"),
]

# What the client had cached at the same moment: six logins for those two.
_CACHE = [
    "ACT cur=935",
    _cached(1, 2105, "1092741133002105", 0, "Игрок 1aada2105", "Online: 0"),
    _cached(2, 1012, "1522777203000972", 35, "Carono"),
    _cached(3, 972, "1522777203000972", 35, "Carono"),
    _cached(4, 8118, "1522777203000972", 35, "Carono"),
    _cached(5, 509, "2146058428000509", 21, "Игрок 3464d509"),
    _cached(6, 935, "1522777203000972", 35, "Carono"),
]


def _servers(rows):
    return [r["serverid"] for r in rows]


# --------------------------------------------------------------------------
# read_accounts — the server's list
# --------------------------------------------------------------------------

def test_the_characters_are_the_two_the_server_names():
    rows = account_switch.read_accounts(_FakeEval(_ROLES))
    assert _servers(rows) == [935, 509]


def test_the_character_in_play_is_flagged_and_comes_first():
    rows = account_switch.read_accounts(_FakeEval(_ROLES))
    assert rows[0]["is_current"] and not rows[1]["is_current"]


def test_every_field_the_tab_draws_survives_the_read():
    rows = account_switch.read_accounts(_FakeEval(_ROLES))
    by_server = {r["serverid"]: r for r in rows}
    assert by_server[935]["nickname"] == "Carono"
    assert by_server[935]["level"] == 35
    assert by_server[935]["zone"] == "APS935"
    assert by_server[935]["gameUid"] == "1522777203000972"
    assert by_server[935]["power"] == 241514404
    assert by_server[935]["alliance"] == "TLou"
    assert by_server[509]["nickname"] == "Игрок 3464d509"


def test_an_empty_roles_list_asks_the_server_then_reads_again():
    """First read is empty → send account.login.new → the retry finds them."""
    ev = _FakeEval([], ["ACT ASK sent"], _ROLES)
    rows = account_switch.read_accounts(ev, timeout=3.0)
    assert _servers(rows) == [935, 509]
    assert "AccountLoginNew" in ev.ran[1]      # the ask went out between the reads


def test_a_silent_server_yields_no_characters_not_stale_rows():
    """Nothing came back inside the timeout — an empty tab is the honest answer."""
    ev = _FakeEval([], ["ACT ASK sent"])
    assert account_switch.read_accounts(ev, timeout=1.0) == []


def test_the_placeholder_row_is_not_a_character():
    """The screen's «add a character» slot carries no id and must not be listed."""
    lines = ["ACT cur=935", _role(935, "1522777203000972", 35, "Carono")]
    rows = account_switch.read_accounts(_FakeEval(lines))
    assert len(rows) == 1 and rows[0]["serverid"] == 935


# --------------------------------------------------------------------------
# read_login_cache — what the tab used to draw, kept for --cache
# --------------------------------------------------------------------------

def test_the_login_cache_still_holds_six_rows_for_two_characters():
    """The bug itself, pinned: this is what the tab drew before #1190."""
    rows = account_switch.read_login_cache(_FakeEval(_CACHE))
    assert len(rows) == 6
    assert sorted(_servers(rows)) == [509, 935, 972, 1012, 2105, 8118]


def test_the_cache_repeats_one_character_across_four_servers():
    rows = account_switch.read_login_cache(_FakeEval(_CACHE))
    carono = [r for r in rows if r["gameUid"] == "1522777203000972"]
    assert sorted(r["serverid"] for r in carono) == [935, 972, 1012, 8118]


def test_the_cache_reader_flags_the_character_in_play():
    rows = account_switch.read_login_cache(_FakeEval(_CACHE))
    assert rows[0]["serverid"] == 935 and rows[0]["is_current"]


def test_no_game_reads_as_no_characters():
    assert account_switch.read_login_cache(_FakeEval([])) == []


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
