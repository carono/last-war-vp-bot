r"""«Вход с другого устройства» read as a state of its own (task #1270).

THE INCIDENT. On 2026-08-07 the account was taken by another device at ~04:38. The
client kept ONE established conversation on the game's own port with five half-closed
beside it — which is also what a perfectly healthy client looks like — so the link read
`online, dead=0`, the clock still answered (the offset is set at login and kept locally),
and every errand was let through and pressed nothing. The one reading that knew was the
kick modal, and it was asked ONLY while the link already said `lost`.

Making it askable at any moment meant making it conclusive on its own first. The window
is `UICommonMessageTip`, the client's GENERIC dialog: on a lost link «a dialog is open»
was proof enough, on a healthy one it is a false kick — and the cure for a kick is a
restart, which closes the window somebody may be playing in.

So the TEXT is compared with the game's own wording for key `E100083`, read out of the
client's own language tables. What is pinned here:

  * the sentence is judged in ANY of the languages the game ships, not the panel's;
  * an ordinary dialog is not a kick;
  * a closed dialog is not a kick — `GetWindow` hands back the last text of a window
    that has been shut, so the open check has to come first;
  * every way of NOT KNOWING is `None`, never `False` and never `True`;
  * and with no language tables at all the reading falls back to exactly what shipped
    before this task, so a machine that cannot find its install is no worse off.

No game, no daemon, no Windows: the tables are stubbed, the client is a fake evaluator.

    C:\Python312\python.exe tests\test_game_kick.py
    python3 tests/test_game_kick.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import game_kick  # noqa: E402

#: Made-up sentences of the same SHAPE as the game's, in three scripts. The real ones
#: are the game's own text and are read off the install at run time; nothing here needs
#: them, and a test that only passes against the shipped tables would be testing the
#: install rather than the code.
KICK_EN = "Your account is signed in on another device!"
KICK_RU = "В этот аккаунт выполнен вход с другого устройства"
KICK_TH = "บัญชี\u200bของ\u200bคุณ\u200bเข้า\u200bสู่\u200bระบบ\u200bบน\u200bอุปกรณ์\u200bอื่น!"


class _Ev:
    """A fake VM: answers one line, or raises, exactly as the daemon client would."""

    def __init__(self, text=None, boom=False, lines=None):
        self.text, self.boom, self.lines, self.calls = text, boom, lines, 0

    def run(self, chunk, marker="", settle=0.0, **_kw):
        # `**_kw` because the reading's WAITING is the caller's business, not the fake's:
        # `early` arrived in #1290 and the next deadline knob will arrive the same way.
        self.calls += 1
        if self.boom:
            raise RuntimeError("the daemon is not there")
        if self.lines is not None:
            return self.lines
        return [f"{game_kick.MARKER} tip={self.text}"]


def _with_phrases(phrases):
    """Stub the language tables — the seam every judgement below stands on."""
    game_kick.forget()
    game_kick._phrases = tuple(phrases)
    game_kick._looked = True


def teardown():
    game_kick.forget()


# --- judging the words ------------------------------------------------------
def test_the_games_own_sentence_is_a_kick_in_every_language_it_ships():
    _with_phrases([KICK_EN, KICK_RU, KICK_TH])
    for said in (KICK_EN, KICK_RU, KICK_TH):
        assert game_kick.judge(said) is True, said


def test_the_zero_width_spaces_and_the_dialogs_padding_do_not_matter():
    """Thai breaks its words with U+200B and the dialog may hand back its own layout.

    The same sentence written twice must compare equal; two DIFFERENT sentences must not.
    """
    _with_phrases([KICK_EN, KICK_TH])
    assert game_kick.judge("  " + KICK_EN.upper() + "\n") is True
    assert game_kick.judge(KICK_TH.replace("\u200b", "")) is True
    assert game_kick.judge("Внимание\n" + KICK_EN) is True, "a title prefix is not a no"


def test_an_ordinary_dialog_is_not_a_kick():
    """The window is the client's generic message tip — it is used for anything."""
    _with_phrases([KICK_EN, KICK_RU])
    for said in ("Not enough resources", "Отряд уже в пути", "Server maintenance"):
        assert game_kick.judge(said) is False, said


def test_with_no_tables_it_declines_to_judge_rather_than_guessing():
    """`None` is «cannot judge», and it is what makes the fallback below possible."""
    _with_phrases([])
    assert game_kick.judge(KICK_EN) is None
    assert game_kick.judge("anything at all") is None


# --- the reading ------------------------------------------------------------
def test_a_kick_is_read_whatever_the_link_says():
    """THE FIX. No `link_lost`, and the account is still positively gone."""
    _with_phrases([KICK_RU])
    assert game_kick.read(_Ev(KICK_RU)) is True


def test_a_client_with_no_dialog_on_screen_is_not_kicked():
    _with_phrases([KICK_RU])
    assert game_kick.read(_Ev("")) is False
    assert game_kick.read(_Ev("   ")) is False


def test_an_ordinary_dialog_on_a_healthy_client_is_not_a_kick():
    """The false positive the narrowing exists to prevent: its cure is a restart."""
    _with_phrases([KICK_RU])
    assert game_kick.read(_Ev("Недостаточно ресурсов")) is False


def test_every_way_of_not_knowing_is_none_and_not_a_verdict():
    _with_phrases([KICK_RU])
    assert game_kick.read(_Ev(boom=True)) is None, "a dead daemon is not a kick"
    assert game_kick.read(_Ev(lines=[])) is None, "an unanswered read is not a kick"
    assert game_kick.read(_Ev(lines=["ACT something else"])) is None


def test_without_tables_it_keeps_exactly_the_rule_that_shipped_before():
    """A machine that cannot find its install loses nothing and gains no guess.

    Before #1270 the pair was «a lost link AND a dialog with text». That is what a
    reading with nothing to compare against falls back to — never more.
    """
    _with_phrases([])
    assert game_kick.read(_Ev("some dialog"), link_lost=True) is True
    assert game_kick.read(_Ev("some dialog"), link_lost=False) is False
    assert game_kick.read(_Ev(""), link_lost=True) is False


def test_the_client_is_asked_once_per_reading():
    """A gate and a status poll both pay for this; it may not become two round trips."""
    _with_phrases([KICK_RU])
    ev = _Ev(KICK_RU)
    game_kick.read(ev)
    assert ev.calls == 1, ev.calls


# --- the chunk it reads through ---------------------------------------------
def test_the_open_check_comes_before_the_text():
    """`GetWindow` answers with a CLOSED window's last message still on it.

    Without the order, a kick that was dismissed minutes ago would still read as one —
    and would be restarted for.
    """
    import lua_actions

    expr = lua_actions.kick_tip()
    assert "IsWindowOpen" in expr and "UICommonMessageTip" in expr, expr
    assert expr.index("IsWindowOpen") < expr.index("GetWindow"), expr
    assert "pcall" in expr, "a reading may never raise into the caller"


def test_the_tables_are_found_without_anything_naming_this_machine():
    """The install is asked for, never written down (`CLAUDE.md`).

    `game_paths.locale_tables()` comes back empty where there is nothing to read, rather
    than raising or guessing — which is what lets :func:`game_kick.phrases` be empty
    instead of being wrong.
    """
    import game_paths

    src = (ROOT / "tools" / "lib" / "game_kick.py").read_text(encoding="utf-8")
    assert "game_paths.locale_tables()" in src, "the tables are located somewhere else"
    assert "LOCALAPPDATA" not in src, "an account's own folder is spelled out here"
    assert "C:\\" not in src, "a drive letter is spelled out here"
    import os

    old = os.environ.get("LW_LOCALE_DIR")
    os.environ["LW_LOCALE_DIR"] = str(ROOT / "does-not-exist")
    try:
        assert game_paths.locale_dir() is None
        game_kick.forget()
        assert game_kick.phrases() == ()
    finally:
        if old is None:
            os.environ.pop("LW_LOCALE_DIR", None)
        else:
            os.environ["LW_LOCALE_DIR"] = old
        game_kick.forget()


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
