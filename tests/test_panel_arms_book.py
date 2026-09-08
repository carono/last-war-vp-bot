r"""The day of «Гонка вооружений», phase by phase — and not one question to the game (#2579).

The person asked the card for two things: «в карточке гонки вооружений, сколько сундуков
собрано за день, а при нажатии на i, выводим иконками каждый час события за сегодня и
сколько там собрано сундуков в каждом часе».

WHY THERE IS A BOOK AT ALL, and why this file pins it: the game keeps no history. Probed
live for #2579 — `dataDict` carries the CURRENT phase's three boxes, the day's three, and
a `claimStatus` keyed `<day>_<stage>` whose value is a FLAG (`1` once the phase counts as
finished), never a count. A phase that ended an hour ago is gone from the client. So the
panel writes down what the GAME said while each phase was the one running, and that is
free: the answer had already arrived.

    C:\Python312\python.exe tests\test_panel_arms_book.py
"""
from __future__ import annotations

TIER = "offline"        # no game, no Tk — a dict and a JSON file

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools" / "lib"))

from panel.runtime import arms_book                      # noqa: E402
from panel.runtime import errand_stats as statsmod       # noqa: E402


class _Store:
    """One profile's `blobs` table, as far as the book is concerned."""

    def __init__(self) -> None:
        self.rows: dict = {}

    def blob_get(self, name: str):
        return self.rows.get(name)

    def blob_set(self, name: str, value) -> None:
        self.rows[name] = value


class _Rt:
    def __init__(self) -> None:
        self.store = _Store()
        self.tabs = None

    def play_async(self, *a, **k):
        raise AssertionError("the book must never play a scenario")


# ---------------------------------------------------------------------------
# the book
# ---------------------------------------------------------------------------
def test_a_phase_is_written_down_and_only_ever_grows():
    """A reading that caught the phase early must not overwrite a later one."""
    rt = _Rt()
    arms_book.record(rt, 2, 120002, 1, ladder=0)
    arms_book.record(rt, 2, 120002, 3, ladder=1)
    arms_book.record(rt, 2, 120002, 2, ladder=0)     # a re-read of a finished phase
    book = arms_book.read(rt)
    assert book["stages"]["2"]["chests"] == 3, "a later reading may not lose chests"
    assert book["ladder"] == 1, "…and neither may the day's own ladder"


def test_the_day_total_counts_the_phases_and_the_ladder():
    rt = _Rt()
    arms_book.record(rt, 0, 120004, 3)
    arms_book.record(rt, 1, 120000, 2)
    arms_book.record(rt, 2, 120001, 3, ladder=3)
    chests, seen, age = arms_book.total(rt)
    assert (chests, seen) == (11, 3), "3 + 2 + 3 phases and the day's three"
    assert age is not None and age < 60


def test_a_book_from_yesterday_is_not_todays_answer():
    """The day is the SERVER's, and a stale book answers «ничего», never yesterday."""
    rt = _Rt()
    arms_book.record(rt, 0, 120004, 3, ladder=3)
    rt.store.rows[arms_book.BLOB]["day"] = "1999-01-01"
    assert arms_book.total(rt) == (0, 0, None)
    assert arms_book.read(rt)["stages"] == {}


def test_a_phase_nobody_read_is_a_dash_and_not_a_zero():
    """The calendar names six windows; the book fills in the ones it saw."""
    rt = _Rt()
    arms_book.record(rt, 1, 120000, 2)
    calendar = ((0, 120004, 100, 200), (1, 120000, 200, 300), (2, 120001, 300, 400))
    rows = arms_book.phases(rt, calendar)
    assert [r["stage"] for r in rows] == [0, 1, 2], "the calendar decides the order"
    assert rows[0]["chests"] is None, "nobody looked while it ran — that is not «0»"
    assert rows[1]["chests"] == 2
    assert rows[1]["all"] == arms_book.PHASE_CHESTS


def test_with_no_calendar_the_book_still_lists_what_it_worked():
    """A profile whose «События» page was never opened still gets its own phases."""
    rt = _Rt()
    arms_book.record(rt, 3, 120003, 1)
    rows = arms_book.phases(rt, ())
    assert len(rows) == 1 and rows[0]["kind"] == 120003 and rows[0]["chests"] == 1


def test_nothing_in_the_book_reaches_for_the_game():
    source = (_REPO / "panel" / "runtime" / "arms_book.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]
    for forbidden in ("play_async", "run_action", "READ_LUA", "Thread(", ".after("):
        assert forbidden not in code, f"the book must not {forbidden}"


# ---------------------------------------------------------------------------
# the line on the card
# ---------------------------------------------------------------------------
def test_the_card_says_the_day_and_an_empty_book_says_nothing_of_its_own():
    rt = _Rt()
    # An empty book is «мы не смотрели», so the row falls through to the panel's own
    # count of today's runs rather than claiming zero chests.
    assert statsmod.of(rt, "perform_arms_race")["key"] != "timers.stat.arms"
    arms_book.record(rt, 0, 120001, 3, ladder=1)
    stat = statsmod.of(rt, "perform_arms_race")
    assert stat["key"] == "timers.stat.arms"
    assert stat["fmt"] == {"n": 4, "phases": 1}


# ---------------------------------------------------------------------------
# the pictures
# ---------------------------------------------------------------------------
def test_the_map_names_only_phases_it_is_sure_of():
    """Four certain pictures, and the drone's is deliberately absent.

    The client's own art folder holds six pictures and only four say plainly which phase
    they belong to. A fifth that «looks close enough» is exactly what the errand covers
    were forbidden from having, and for the same reason.
    """
    data = json.loads((_REPO / "tools" / "data"
                       / "arms_icons.json").read_text(encoding="utf-8"))
    icons = data["icons"]
    assert set(icons) == {"120000", "120001", "120002", "120003"}, icons
    assert "120004" not in icons, "the drone must not borrow another phase's picture"
    assert len(set(icons.values())) == len(icons), "one picture may not stand for two"


def test_a_machine_with_no_art_draws_no_picture_and_no_broken_link():
    import arms_icons

    arms_icons.forget()
    old, arms_icons.ICON_ROOT = arms_icons.ICON_ROOT, os.path.join(
        str(_REPO), "results", "no-such-folder-2579")
    try:
        assert arms_icons.name_for("120001") == ""
        assert arms_icons.file_named("lrb_gerenjunbei_jianzhu.png") is None
    finally:
        arms_icons.ICON_ROOT = old
        arms_icons.forget()


def test_a_name_off_the_wire_cannot_walk_out_of_the_icon_folder():
    import arms_icons

    for evil in ("../secrets.png", "/etc/passwd", ".hidden.png", "x.py", ""):
        assert arms_icons.file_named(evil) is None, evil


def test_the_route_is_the_sixth_of_the_same_shape():
    server = (_REPO / "panel" / "web" / "server.py").read_text(encoding="utf-8")
    assert '/api/armsicon' in server and "def _armsicon" in server
    route = server.split("def _armsicon", 1)[1]
    assert "self._picture(query, resolve)" in route, (
        "a picture goes through the one helper that authorises, resolves and caches")
    # …and it did not land inside the errand route, whose own test reads the slice
    # between it and the next one (`tests/test_panel_web_cards.py`).
    assert server.index("def _errandicon") < server.index("def _monstericon") \
        < server.index("def _armsicon")


def test_the_phones_sheet_gets_the_rows_and_the_window_is_left_alone():
    """The web is the front-end being built on (`CLAUDE.md`), and the «i» is the one sheet."""
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert "def _arms_card" in api and "self._arms_card(rt, timer.name)" in api
    card = (_REPO / "panel" / "web" / "app" / "src" / "ui"
            / "ErrandCard.tsx").read_text(encoding="utf-8")
    assert "function Phases(" in card, "the sheet must draw the day"
    assert card.count("<Modal") == 1, "one modal, and no second one is written"
    view = (_REPO / "panel" / "web" / "app" / "src" / "views"
            / "TimersView.tsx").read_text(encoding="utf-8")
    assert "phases={row.phases}" in view


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
        except Exception as exc:      # noqa: BLE001 — a raise is a failure too
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
