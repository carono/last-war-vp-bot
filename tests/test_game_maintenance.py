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
SEASON_EN = ("The season has ended, and the server is currently under maintenance.\n"
             "(Estimated time: 10-30 minutes)")


def _with(**keys) -> None:
    """Stub the language tables — the seam every judgement below stands on."""
    gm.forget()
    gm._phrases = {key: set(value if isinstance(value, (list, tuple, set)) else [value])
                   for key, value in keys.items()}
    gm._looked = True


def teardown() -> None:
    gm.forget()


class _Ev:
    """A fake VM: answers one line, or raises, exactly as the client's would.

    The line is what `lua_actions.maintenance_look` builds — the four window flags and
    the message dialog's text, the text last because it is the only field that can
    contain spaces.
    """

    def __init__(self, text="", boom=False, window=False, login=False,
                 disconnect=False, cross=False, raw=None):
        self.text, self.boom, self.calls = text, boom, 0
        self.window, self.login, self.disconnect, self.cross = (
            window, login, disconnect, cross)
        self.raw = raw

    def run(self, chunk, marker="", settle=0.0, **_kw):
        self.calls += 1
        if self.boom:
            raise RuntimeError("nothing is attached")
        if self.raw is not None:
            return [f"{gm.MARKER} look={self.raw}"]
        said = ("maint=%s login=%s disc=%s cross=%s tip=%s"
                % (int(self.window), int(self.login), int(self.disconnect),
                   int(self.cross), self.text))
        return [f"{gm.MARKER} look={said}"]


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


# --- the game's own name for the state --------------------------------------
def test_the_games_own_window_decides_with_no_tables_at_all():
    """`UIServerMaintenanceTip` is the same in every language and needs no sentence.

    Confirmed to EXIST on a live client (2026-08-26); not yet seen open, which is why
    the sentences below are still read as a second rung.
    """
    _with()                                   # no locale tables on this machine at all
    assert gm.read(_Ev(window=True)) == (gm.CLOSED, None)


def test_the_window_outranks_a_dialog_that_says_something_else():
    _with(login_err_tips_maintenance_new=CLOSED_EN)
    assert gm.read(_Ev(text="Not enough diamonds", window=True)) == (gm.CLOSED, None)


def test_the_context_flags_come_back_for_the_recording():
    """Where the client is SITTING is what a sample is worth reading for."""
    seen = gm.look(_Ev(text=CLOSED_EN, window=True, login=True))
    assert seen["window"] is True and seen["login"] is True
    assert seen["disconnect"] is False and seen["cross"] is False
    assert seen["tip"] == CLOSED_EN
    assert seen["raw"].startswith("maint=1 login=1")


def test_a_tip_with_spaces_survives_the_one_line_it_travels_in():
    seen = gm.look(_Ev(text="The server is under maintenance. Please wait."))
    assert seen["tip"] == "The server is under maintenance. Please wait."


def test_a_client_that_answers_nothing_at_all_is_cannot_tell():
    assert gm.look(_Ev(raw="")) is None


# --- the one length the game names ------------------------------------------
def test_the_season_close_is_maintenance_and_it_says_how_long():
    """The only sentence in the game that estimates the LENGTH of the outage."""
    _with(season_close_tips01=SEASON_EN)
    assert gm.judge(SEASON_EN) == (gm.CLOSED, None)
    assert gm.estimate(SEASON_EN) == (10 * 60.0, 30 * 60.0)


def test_no_length_is_read_out_of_any_other_sentence():
    """Two numbers in an ordinary message are a level or a reward, never a deadline."""
    _with(login_err_tips_maintenance_new=CLOSED_EN, season_close_tips01=SEASON_EN)
    assert gm.estimate(CLOSED_EN) is None
    assert gm.estimate("Base 10-30 upgraded") is None


def test_no_dialog_on_screen_is_a_real_answer_and_not_a_shrug():
    _with(login_err_tips_maintenance_new=CLOSED_EN)
    assert gm.read(_Ev("")) == ("", None)


def test_the_reading_is_one_round_trip():
    """Both questions — the kick and the closed door — come out of this one line."""
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
