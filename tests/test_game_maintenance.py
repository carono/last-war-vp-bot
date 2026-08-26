r"""«Сервер на техобслуживании» read as a state of its own (task #1982).

THE INCIDENT. Maintenance was caught live on 2026-08-19
(`docs/research/server-maintenance.md`) and every indicator the panel had stayed GREEN
for the whole window: the client was up, chunks landed, the daemon was warm. The account
sat on a closed door and the panel said «не удалось спросить клиент», which is the
sentence that invites somebody to go and restart things that are not broken.

The one thing that knew was the sentence on the client's own screen, and the client
renders it from a KEY of its own language tables — so it is recognisable in whatever
language the game is played in, the same technique the session kick uses
(`tools/lib/game_kick.py`).

What is pinned here:

  * the game's own maintenance sentence is recognised in ANY language it ships;
  * the shutdown COUNTDOWN («in {0}-min», «in {0}s») is a different state and it hands
    back the seconds — the only time the game names at all, and it is the time until the
    door shuts, never the time it opens;
  * a template that is mostly a placeholder never matches an ordinary dialog;
  * ANOTHER warzone being closed (a refused cross-server jump, a refused duel) is not
    this account's server being closed and must never park a working account;
  * every way of NOT KNOWING is `None` — never `""` and never a verdict.

No game, no daemon, no Windows: the tables are stubbed, the client is a fake evaluator.

    C:\Python312\python.exe tests\test_game_maintenance.py
    python3 tests/test_game_maintenance.py
"""
from __future__ import annotations

TIER = "pure"

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import game_maintenance as gm  # noqa: E402

#: Made-up sentences of the same SHAPE as the game's, in three scripts. The real ones
#: are the game's own text and are read off the install at run time; a test that only
#: passed against the shipped tables would be testing the install rather than the code.
CLOSED_EN = "The server is under maintenance. Please wait a moment, we will be back!"
CLOSED_RU = "Сервер находится на техническом обслуживании. Подождите немного!"
CLOSED_TH = ("เซิร์ฟเวอร์\u200bอยู่\u200bระหว่าง\u200bการ\u200bบำรุงรักษา "
             "โปรด\u200bรอ\u200bสัก\u200bครู่!")
CODED_EN = "({0}) The server is under maintenance."
SOON_MIN = "The server will shut down for maintenance in {0}-min"
SOON_SEC = "The server will shut down for maintenance in {0}s"


def _with(**keys) -> None:
    """Stub the language tables — the seam every judgement below stands on."""
    gm.forget()
    gm._phrases = {key: set(value if isinstance(value, (list, tuple, set)) else [value])
                   for key, value in keys.items()}
    gm._looked = True


def teardown() -> None:
    gm.forget()


class _Ev:
    """A fake VM: answers one line, or raises, exactly as the client's would."""

    def __init__(self, text=None, boom=False):
        self.text, self.boom, self.calls = text, boom, 0

    def run(self, chunk, marker="", settle=0.0, **_kw):
        self.calls += 1
        if self.boom:
            raise RuntimeError("nothing is attached")
        return [f"{gm.MARKER} tip={self.text}"]


# --- the closed door --------------------------------------------------------
def test_the_games_own_sentence_is_maintenance_in_every_language_it_ships():
    _with(login_err_tips_maintenance_new=[CLOSED_EN, CLOSED_RU, CLOSED_TH])
    for said in (CLOSED_EN, CLOSED_RU, CLOSED_TH):
        assert gm.judge(said) == (gm.CLOSED, None), said


def test_the_zero_width_spaces_and_the_dialogs_padding_do_not_matter():
    _with(login_err_tips_maintenance_new=[CLOSED_TH])
    padded = "  " + CLOSED_TH.replace("\u200b", "") + "  "
    assert gm.judge(padded)[0] == gm.CLOSED


def test_an_error_code_in_the_sentence_is_still_the_same_state():
    """`login_err_tips_maintenance` carries the server's code in a slot."""
    _with(login_err_tips_maintenance=CODED_EN)
    assert gm.judge("(129012) The server is under maintenance.") == (gm.CLOSED, None)


def test_an_ordinary_dialog_is_not_maintenance():
    _with(login_err_tips_maintenance_new=[CLOSED_EN, CLOSED_RU])
    assert gm.judge("Not enough diamonds") == ("", None)
    assert gm.judge("Your account is signed in on another device!") == ("", None)


# --- the door closing -------------------------------------------------------
def test_the_countdown_is_its_own_state_and_it_hands_back_the_seconds():
    _with(**{"120036": SOON_MIN, "120037": SOON_SEC})
    assert gm.judge("The server will shut down for maintenance in 15-min") == \
        (gm.CLOSING, 900.0)
    assert gm.judge("The server will shut down for maintenance in 45s") == \
        (gm.CLOSING, 45.0)


def test_the_countdown_outranks_the_closed_door_because_it_carries_the_time():
    _with(login_err_tips_maintenance_new=CLOSED_EN, **{"120036": SOON_MIN})
    state, secs = gm.judge("The server will shut down for maintenance in 5-min")
    assert (state, secs) == (gm.CLOSING, 300.0)


# --- what must never be judged ---------------------------------------------
def test_a_template_that_is_mostly_a_placeholder_matches_nothing():
    """Otherwise `({0})` would make every dialog in the game a maintenance notice."""
    _with(login_err_tips_maintenance="({0})")
    assert gm.judge("(602026) Not enough diamonds") == ("", None)


def test_somebody_elses_warzone_being_closed_is_not_ours():
    """`server_open_tips001` / `server_maintenance_001` are a refused jump and a duel.

    They are not among the keys read at all, which is the point: parking a working
    account because a cross-server jump was refused would be the expensive mistake.
    """
    assert "server_open_tips001" not in gm.CLOSED_KEYS
    assert "server_maintenance_001" not in gm.CLOSED_KEYS


# --- every way of not knowing ----------------------------------------------
def test_no_language_tables_means_cannot_judge_and_never_a_verdict():
    _with()
    assert gm.judge(CLOSED_EN) == (None, None)
    assert gm.read(_Ev(CLOSED_EN)) == (None, None)


def test_a_client_that_will_not_answer_is_cannot_tell():
    _with(login_err_tips_maintenance_new=CLOSED_EN)
    assert gm.read(_Ev(boom=True)) == (None, None)


def test_no_dialog_on_screen_is_a_real_answer_and_not_a_shrug():
    _with(login_err_tips_maintenance_new=CLOSED_EN)
    assert gm.read(_Ev("")) == ("", None)


def test_the_reading_is_one_round_trip():
    _with(login_err_tips_maintenance_new=CLOSED_EN)
    ev = _Ev(CLOSED_EN)
    assert gm.read(ev) == (gm.CLOSED, None)
    assert ev.calls == 1


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
        finally:
            teardown()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
