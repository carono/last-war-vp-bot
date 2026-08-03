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


def _role(serverid, uid, level, nick, power=0, alliance="", picver=0, uuid=""):
    """One `rolesList` entry, as the roles reader prints it."""
    return (f"ACT R serverid={serverid} gameUid={uid} level={level} power={power} "
            f"picVer={picver} nick={_hex(nick)} zone={_hex(f'APS{serverid}')} "
            f"alliance={_hex(alliance)} uuid={_hex(uuid)}")


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
    "ACT cur=100",
    _role(100, "1000000000000935", 35, "Player2", 241514404, "ALLY",
          273, "00000000-0000-4000-8000-000000000000_n0000000000000000"),
    _role(200, "1000000000013509", 21, "Игрок 00000509", 4185296, "<ALLY3>"),
]

# What the client had cached at the same moment: six logins for those two.
_CACHE = [
    "ACT cur=100",
    _cached(1, 600, "1000000000016105", 0, "Игрок 00002105", "Online: 0"),
    _cached(2, 400, "1000000000000935", 35, "Player2"),
    _cached(3, 300, "1000000000000935", 35, "Player2"),
    _cached(4, 500, "1000000000000935", 35, "Player2"),
    _cached(5, 200, "1000000000013509", 21, "Игрок 00000509"),
    _cached(6, 100, "1000000000000935", 35, "Player2"),
]


def _servers(rows):
    return [r["serverid"] for r in rows]


# --------------------------------------------------------------------------
# read_accounts — the server's list
# --------------------------------------------------------------------------

def test_the_characters_are_the_two_the_server_names():
    rows = account_switch.read_accounts(_FakeEval(_ROLES))
    assert _servers(rows) == [100, 200]


def test_the_character_in_play_is_flagged_and_comes_first():
    rows = account_switch.read_accounts(_FakeEval(_ROLES))
    assert rows[0]["is_current"] and not rows[1]["is_current"]


def test_every_field_the_tab_draws_survives_the_read():
    rows = account_switch.read_accounts(_FakeEval(_ROLES))
    by_server = {r["serverid"]: r for r in rows}
    assert by_server[100]["nickname"] == "Player2"
    assert by_server[100]["level"] == 35
    assert by_server[100]["zone"] == "APS100"
    assert by_server[100]["gameUid"] == "1000000000000935"
    assert by_server[100]["power"] == 241514404
    assert by_server[100]["alliance"] == "ALLY"
    assert by_server[100]["picVer"] == 273
    assert by_server[100]["uuid"].endswith("_n0000000000000000")
    assert by_server[200]["nickname"] == "Игрок 00000509"


def test_an_empty_roles_list_asks_the_server_then_reads_again():
    """First read is empty → send account.login.new → the retry finds them."""
    ev = _FakeEval([], ["ACT ASK sent"], _ROLES)
    rows = account_switch.read_accounts(ev, timeout=3.0)
    assert _servers(rows) == [100, 200]
    assert "AccountLoginNew" in ev.ran[1]      # the ask went out between the reads


def test_a_silent_server_yields_no_characters_not_stale_rows():
    """Nothing came back inside the timeout — an empty tab is the honest answer."""
    ev = _FakeEval([], ["ACT ASK sent"])
    assert account_switch.read_accounts(ev, timeout=1.0) == []


def test_the_placeholder_row_is_not_a_character():
    """The screen's «add a character» slot carries no id and must not be listed."""
    lines = ["ACT cur=100", _role(100, "1000000000000935", 35, "Player2")]
    rows = account_switch.read_accounts(_FakeEval(lines))
    assert len(rows) == 1 and rows[0]["serverid"] == 100


# --------------------------------------------------------------------------
# read_login_cache — what the tab used to draw, kept for --cache
# --------------------------------------------------------------------------

def test_the_login_cache_still_holds_six_rows_for_two_characters():
    """The bug itself, pinned: this is what the tab drew before #1190."""
    rows = account_switch.read_login_cache(_FakeEval(_CACHE))
    assert len(rows) == 6
    assert sorted(_servers(rows)) == [100, 200, 300, 400, 500, 600]


def test_the_cache_repeats_one_character_across_four_servers():
    rows = account_switch.read_login_cache(_FakeEval(_CACHE))
    player2 = [r for r in rows if r["gameUid"] == "1000000000000935"]
    assert sorted(r["serverid"] for r in player2) == [100, 300, 400, 500]


def test_the_cache_reader_flags_the_character_in_play():
    rows = account_switch.read_login_cache(_FakeEval(_CACHE))
    assert rows[0]["serverid"] == 100 and rows[0]["is_current"]


def test_no_game_reads_as_no_characters():
    assert account_switch.read_login_cache(_FakeEval([])) == []


# --------------------------------------------------------------------------
# switch_account — the character screen's own login press, gated
# --------------------------------------------------------------------------
# The press writes the picked character's credentials over the saved ones and drops
# the session, so the two ways it would be a no-op are refused BEFORE it fires: no
# character on that server, and the character already in play. `target` is the Lua
# reading that tells them apart (1 / 0 / -1).

def _target(value):
    return [f"ACT target={value}"]


def test_a_switch_with_no_character_list_never_presses():
    """The server said nothing — refuse rather than press blind."""
    ev = _FakeEval([], ["ACT ASK sent"])
    assert account_switch.switch_account(ev, 200, timeout=1.0) == "no-characters"
    assert not any("AccountCredentialManager" in c for c in ev.ran)


def test_a_switch_to_a_server_without_a_character_is_refused():
    ev = _FakeEval(_ROLES, [], _target(0))
    assert account_switch.switch_account(ev, 4242) == "no-such-account"
    assert not any("AccountCredentialManager" in c for c in ev.ran)


def test_a_switch_to_the_character_in_play_is_refused():
    ev = _FakeEval(_ROLES, [], _target(-1))
    assert account_switch.switch_account(ev, 100) == "already-current"
    assert not any("AccountCredentialManager" in c for c in ev.ran)


def test_a_switch_to_another_character_parks_it_and_presses():
    ev = _FakeEval(_ROLES, [], _target(1), ["ACT account_switch sent server=200"])
    assert account_switch.switch_account(ev, 200) == "sent"
    assert "DataCenter.__lw_switch_account = 200" in ev.ran[1]
    # The press is the character screen's login, not the login screen's cell handler
    # that #1190 caught sending an empty user name.
    assert "AccountCredentialManager" in ev.ran[-1]
    assert "OnBtnSelectClick" not in ev.ran[-1]


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
