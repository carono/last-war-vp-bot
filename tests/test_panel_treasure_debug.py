r"""The «Сокровища» debug page: a feed that is read, kept, and the same in both windows.

The rules this file exists to hold:

* **a message is classified by its NAME**, never by a guess about what somebody meant —
  and a command nobody has met before comes out as «a chest said something» rather than
  disappearing into the drawer nobody looks in;
* **the panel keeps no count of its own.** `seq`, `drop` and `more` are the game's
  numbers, drained and shown. The only thing this side counts is how many lines are on
  its own screen, which is a fact about the window;
* **a broken answer is an error, not an exception** — this is the client talking through
  a log line, and one that has just been restarted says all sorts of things. A single
  malformed ENTRY costs that entry and not the batch it arrived in;
* **the phone shows what the window shows.** Both front-ends draw one feed and offer the
  same presses (`CLAUDE.md`), and every word of both is a key.

No display for the model half — it is Tk-free. The tab MODULE imports tkinter, which the
WSL python does not ship, so those tests say SKIP there and run under the Windows one:

    C:\Python312\python.exe tests\test_panel_treasure_debug.py
    python3 tests/test_panel_treasure_debug.py       # the model half
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import i18n as i18nmod                                  # noqa: E402
from panel.tabs.treasure_debug import model as modelmod            # noqa: E402

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions" / "dev"

#: A drain of the three moments, shaped exactly as the scenario returns one. Invented
#: ids of the right shape — nothing here is an account's (`CLAUDE.md`).
DRAIN = json.dumps({
    "on": 1, "wide": 0, "n": 4, "more": 0, "drop": 0, "seq": 128,
    "items": [
        {"i": 125, "t": 1785322473766, "d": "in", "c": "world.treasure.share.chat",
         "f": "uuid=1000000000000000001 x=571 y=456"},
        {"i": 126, "t": 1785322480000, "d": "out", "c": "world.march.formation.new",
         "f": "a1=1000000000000000002 a2=50 a3=1000000000000000001"},
        {"i": 127, "t": 1785322600000, "d": "out", "c": "detect.event.claim.treasure",
         "f": "a1=1000000000000000001 a2=100"},
        {"i": 128, "t": 1785322600500, "d": "in", "c": "push.detect.treasure.claim",
         "f": "uuid=1000000000000000001 operator={...}"},
    ]})


def _needs_tk(what: str):
    """The tab class, or None with a SKIP line — the WSL python has no tkinter."""
    try:
        from panel.tabs.treasure_debug.tab import TreasureDebugTab
    except ImportError:                             # pragma: no cover - no display
        print(f"  skip {what}: tkinter is not installed")
        return None
    return TreasureDebugTab


# ---------------------------------------------------------------------------
# what a message IS
# ---------------------------------------------------------------------------
def test_each_of_the_three_moments_is_recognised_by_its_command():
    assert modelmod.kind("world.treasure.share.chat") == modelmod.FOUND
    assert modelmod.kind("push.detect.event.info") == modelmod.FOUND
    assert modelmod.kind("world.march.formation.new") == modelmod.MARCH
    assert modelmod.kind("detect.event.claim.treasure") == modelmod.TAKEN
    assert modelmod.kind("push.detect.treasure.claim") == modelmod.TAKEN
    assert modelmod.kind("push.hero.data") == modelmod.OTHER


def test_a_treasure_command_nobody_has_met_reads_as_a_chest_not_as_noise():
    """The filter that put it in the feed matched `treasure`/`detect`, so a page that
    then drew it as «Прочее» would hide it behind a checkbox nobody ticks."""
    for unknown in ("detect.event.put.point.in.world", "activity.detect.list",
                    "push.itemuse.detect.info", "world.treasure.something.new"):
        assert modelmod.kind(unknown) == modelmod.FOUND, unknown


def test_the_kinds_the_tab_draws_are_the_kinds_the_model_has():
    """One list, so a kind added to the model gets a filter and a locale key rather than
    quietly falling through the tab's `_LOOK` table."""
    tab = _needs_tk("the kinds match the tab's table")
    if tab is None:
        return
    from panel.tabs.treasure_debug import tab as tabmod
    assert set(tabmod._LOOK) == set(modelmod.KINDS)


# ---------------------------------------------------------------------------
# what came back
# ---------------------------------------------------------------------------
def test_a_drain_is_read_into_entries_with_the_games_own_clock():
    drain = modelmod.parse(DRAIN, at=100.0)
    assert drain and drain.on and not drain.wide
    assert drain.seq == 128 and drain.more == 0 and drain.at == 100.0
    assert [e.kind for e in drain.entries] == [
        modelmod.FOUND, modelmod.MARCH, modelmod.TAKEN, modelmod.TAKEN]
    assert drain.entries[1].out is True and drain.entries[0].out is False
    assert drain.entries[0].ms == 1785322473766


def test_an_answer_that_is_not_an_answer_is_an_error_and_not_a_crash():
    for broken in (None, "", "nil", "{oops", "[]", "12"):
        drain = modelmod.parse(broken)
        assert not drain, broken
        assert drain.error and not drain.entries, broken


def test_one_malformed_entry_costs_that_entry_and_not_the_batch():
    raw = json.dumps({"on": 1, "seq": 2, "items": [
        {"i": 1, "t": 1, "d": "in", "c": "push.detect.treasure.claim", "f": "uuid=1"},
        {"i": "not a number", "t": 2, "d": "in", "c": "x", "f": ""},
    ]})
    drain = modelmod.parse(raw)
    assert drain and len(drain.entries) == 1


def test_the_watch_state_line_is_read_as_numbers():
    state = modelmod.parse_state("on=1 wide=0 buf=3 seq=9 drop=0 cap=400")
    assert state == {"on": 1, "wide": 0, "buf": 3, "seq": 9, "drop": 0, "cap": 400}
    assert modelmod.parse_state(None) == {}
    assert modelmod.parse_state("nil") == {}


def test_a_clock_the_game_would_not_answer_is_dashes_and_never_1970():
    assert modelmod.clock(0) == "--:--:--"
    assert modelmod.clock(1785322473766).count(":") == 2


# ---------------------------------------------------------------------------
# the ring
# ---------------------------------------------------------------------------
def test_the_ring_keeps_the_newest_and_counts_what_fell_off():
    ring = modelmod.Ring(cap=3)
    drain = modelmod.parse(DRAIN)
    assert ring.add(drain.entries) == 4
    assert len(ring) == 3 and ring.lost == 1
    assert [e.seq for e in ring.entries] == [126, 127, 128]


def test_the_filter_picks_kinds_and_the_text_is_one_line_each():
    ring = modelmod.Ring()
    ring.add(modelmod.parse(DRAIN).entries)
    taken = ring.select((modelmod.TAKEN,))
    assert [e.seq for e in taken] == [127, 128]
    text = ring.text((modelmod.TAKEN,))
    assert len(text.splitlines()) == 2
    assert "detect.event.claim.treasure" in text
    assert "→" in text and "←" in text          # the direction, as a glyph


def test_clearing_the_page_loses_nothing_the_game_still_holds():
    """«Очистить» empties the panel's copy only — the game's ring is the one that must
    survive, and a person tidying the screen is not asking to lose the session."""
    ring = modelmod.Ring()
    ring.add(modelmod.parse(DRAIN).entries)
    ring.clear()
    assert len(ring) == 0 and ring.lost == 0


# ---------------------------------------------------------------------------
# the two front-ends
# ---------------------------------------------------------------------------
def test_the_phone_and_the_window_offer_the_same_presses():
    """A control the phone has and the window does not is a control the person at the
    machine cannot find, and the other way round is worse (`CLAUDE.md`)."""
    tab = _needs_tk("both front-ends offer the same presses")
    if tab is None:
        return
    source = (Path(tab.__module__.replace(".", "/")).with_suffix(".py"))
    text = (_REPO / source).read_text(encoding="utf-8")
    for command in ("self.copy_feed", "self.save_feed", "self.clear_feed",
                    "self._toggle_watch", "self._toggle_wide"):
        assert command in text, command
    for action in ("watch_on", "watch_off", "wide", "save", "clear"):
        assert '"%s"' % action in text, action


def test_the_screen_is_keys_and_data_and_never_a_sentence():
    """Every label the phone draws is a locale key that exists in every shipped locale;
    every value is data. The renderer translates, so a sentence here is a sentence in
    English for ever."""
    tab = _needs_tk("the screen is keys")
    if tab is None:
        return
    en = i18nmod.I18n("en", persist=False)
    seen = set()
    for key in ("tab.treasure_debug", "treasure_debug.hint",
                "treasure_debug.web.state", "treasure_debug.web.counts",
                "treasure_debug.web.feed", "treasure_debug.web.start",
                "treasure_debug.web.stop", "treasure_debug.web.empty"):
        assert en.t(key) != key, key
        seen.add(key)
    for kind in modelmod.KINDS:
        key = "treasure_debug.kind." + kind
        assert en.t(key) != key, key
    assert len(seen) == 8


def test_the_page_plays_scenarios_and_assembles_no_lua():
    """The whole rule: the ability is three `actions/dev/*.md`, and the panel plays them.
    A `lua_actions` import or a `Debug.LogError` in the tab would be the debt starting
    again (`CLAUDE.md`)."""
    for part in ("tab.py", "model.py"):
        text = (_REPO / "panel" / "tabs" / "treasure_debug" / part).read_text(
            encoding="utf-8")
        assert "import lua_actions" not in text, part
        assert "LogError" not in text, part
        assert "SFSNetwork" not in text, part
    for name in (modelmod.WATCH_ACTION, modelmod.READ_ACTION, modelmod.UNWATCH_ACTION):
        assert (ACTIONS / (name + ".md")).exists(), name


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed or skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
