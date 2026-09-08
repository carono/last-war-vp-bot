r"""A NAME THE GAME WROTE, SAID IN THE PANEL'S LANGUAGE (#2645).

The person's report was «вещи не переведены на языки», and asked where: «Названия из
игры (здания, чипы, фазы)». Those words are not the panel's — the CLIENT resolved them,
in the language that client is playing in — so `panel/runtime/game_words.py` turns them
round through the GAME's own tables, never through a translation of ours.

What is pinned here is the behaviour that decides whether that is safe to leave running
on somebody's live panel:

  * a name in the client's language comes back in the panel's;
  * a name ALREADY in the panel's language is handed back untouched, and that does NOT
    pin the client's language — a word can stand in two tables, and pinning on one of
    those would leave every later name untranslated;
  * a name in neither is handed back exactly as the game said it, never blanked and
    never replaced by something that looks close;
  * a machine with no game (this one, a test, a checkout) is answered the same way,
    without raising;
  * and the language a profile's client turned out to be in is remembered PER PROFILE,
    because two accounts on one machine may run two clients in two languages
    (`CLAUDE.md`, «A profile is a whole panel of its own»).

Needs no display and no game: the tables are stubbed.

    python3 tests/test_panel_game_words.py
"""
from __future__ import annotations

TIER = "pure"      # no game, no display — the tables are stubbed below

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import game_words          # noqa: E402 — path wired up above

#: TABLES OF THE RIGHT SHAPE, WITH INVENTED CONTENT. The game's own are `{key: text}`
#: with the SAME keys in every language, and that is the whole of what matters here.
#: Nothing in this file is a value read off anybody's account (`CLAUDE.md`).
_TABLES = {
    "en": {"800351": "Squad 1", "800352": "Steel Mill", "900001": "OK"},
    "ru": {"800351": "1-й отряд", "800352": "Металлургический завод", "900001": "OK"},
    "de": {"800351": "Trupp 1", "800352": "Stahlwerk", "900001": "OK"},
}


def _fake_tables(langs=("en", "ru", "de")) -> None:
    """Hand the module the tables above instead of the ones on this machine's disk."""
    game_words._TABLES.clear()               # noqa: SLF001 — the module under test
    game_words._INDEX.clear()                # noqa: SLF001
    game_words._CLIENT.clear()               # noqa: SLF001
    game_words._table = lambda lang: dict(_TABLES.get(lang, {}))     # noqa: SLF001
    game_words._index = lambda lang: {t: k for k, t in                # noqa: SLF001
                                      reversed(list(_TABLES.get(lang, {}).items()))}
    game_words._candidates = lambda want: [l for l in ((want,) + tuple(langs))  # noqa: SLF001, E501
                                           if l in _TABLES][:4]


# ---------------------------------------------------------------------------
# turning a name round
# ---------------------------------------------------------------------------
def test_a_name_in_the_clients_language_comes_back_in_the_panels():
    _fake_tables()
    assert game_words.say("Металлургический завод", "de", scope="a") == "Stahlwerk"
    # …and the client's language is remembered, so the next name goes straight to it
    assert game_words._CLIENT["a"] == "ru"                            # noqa: SLF001
    assert game_words.say("1-й отряд", "de", scope="a") == "Trupp 1"


def test_a_name_already_in_the_panels_language_is_left_alone():
    _fake_tables()
    assert game_words.say("Stahlwerk", "de", scope="b") == "Stahlwerk"
    # AND IT IS NOT TAKEN AS PROOF of what the client is in: a word can stand in two
    # tables, and pinning on one of those is how every later name stops translating.
    assert "b" not in game_words._CLIENT                              # noqa: SLF001
    assert game_words.say("Металлургический завод", "de", scope="b") == "Stahlwerk"


def test_a_name_the_tables_do_not_know_is_handed_straight_back():
    _fake_tables()
    assert game_words.say("Fábrica de nada", "de", scope="c") == "Fábrica de nada"
    assert game_words.say("", "de", scope="c") == ""
    assert game_words.say(None, "de", scope="c") == ""


def test_a_machine_with_no_game_answers_the_same_way_and_never_raises():
    _fake_tables(langs=())
    game_words._candidates = lambda want: []                          # noqa: SLF001
    assert game_words.say("Металлургический завод", "de", scope="d") \
        == "Металлургический завод"


def test_the_clients_language_is_remembered_per_profile():
    _fake_tables()
    assert game_words.say("Steel Mill", "ru", scope="one") == "Металлургический завод"
    assert game_words.say("Stahlwerk", "ru", scope="two") == "Металлургический завод"
    assert game_words._CLIENT == {"one": "en", "two": "de"}           # noqa: SLF001


def test_the_scan_is_capped_so_an_unknown_name_costs_four_tables_at_most():
    """The real `_candidates` never hands back more than four languages.

    Without the cap a name nobody can place would read every table the game ships off
    the disk — nineteen of them — for every name on the page.
    """
    game_words._TABLES.clear()               # noqa: SLF001
    game_words._INDEX.clear()                # noqa: SLF001
    import importlib
    importlib.reload(game_words)
    assert len(game_words._candidates("ru")) <= 4                     # noqa: SLF001


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    bad = 0
    for t in tests:
        try:
            t()
            print("  ok  ", t.__name__)
        except Exception as exc:                  # noqa: BLE001 — a test runner
            bad += 1
            print("  FAIL", t.__name__, "->", exc)
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
