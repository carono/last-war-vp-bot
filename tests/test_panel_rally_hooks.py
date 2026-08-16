r"""Two hooks on one rally event, and neither does the other's work twice (#1416).

The operator's decision, in their own words: «По ралли должно остаться два хука: один
собирает статистику по ралли, второй присоединяется. Да, возможно они слушают одно и то
же событие, но они делают разные вещи.»

So nothing here removes a consumer. What it removes is DUPLICATED WORK, measured over
5.6 live hours:

* 123 of 514 `join_rally` runs (24%) came back with a report identical to the run before
  them — two drivers of the join hearing the same push a fifth of a second apart, each
  reading the same map and sending the same nothing;
* `rally_monitor` ran 406 times (6.8% of the window) re-reading the game's own march
  table for banners the push had just described.

The rule is the banner, not the clock: a banner in a state some hook has already weighed
is a duplicate for THAT hook; a banner whose seats have moved is news and goes through —
it is exactly the `refresh` that produced 113 of 131 live sends. Each hook keeps its own
record, so neither can eat the other's turn.

No Tk, no game, no wire::

    python3 tests/test_panel_rally_hooks.py
    C:\Python312\python.exe tests\test_panel_rally_hooks.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# `panel.runtime`'s own `__init__` pulls in the host and, with it, Tk. Neither the book
# nor the gate touches a widget, so the package is stood up as a bare namespace over the
# same directory and the modules are imported into it — relative imports resolve exactly
# as they do in the panel.
import importlib                                           # noqa: E402
import types                                               # noqa: E402

sys.modules.setdefault("panel", types.ModuleType("panel")).__path__ = [str(_REPO / "panel")]
_pkg = types.ModuleType("panel.runtime")
_pkg.__path__ = [str(_REPO / "panel" / "runtime")]
sys.modules["panel.runtime"] = _pkg
BannerBook = importlib.import_module("panel.runtime.rally_wire").BannerBook


class _RT:
    def __init__(self, book) -> None:
        self.banners = book


def _gate():
    """`panel/tabs/rally/limits.py`, imported the same way and for the same reason."""
    for name, rel in (("panel.tabs", "panel/tabs"), ("panel.tabs.rally", "panel/tabs/rally")):
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [str(_REPO / rel)]
            sys.modules[name] = pkg
    return importlib.import_module("panel.tabs.rally.limits")


def _banner(book, team="1", slots="2/5"):
    book.note({"team": team, "content": "1040016", "slots": slots,
               "join": "493559/935"})


def test_a_banner_is_weighed_once_per_hook():
    book = BannerBook()
    _banner(book)
    assert book.worth_a_run("join", mark=True) is True
    assert book.worth_a_run("join", mark=True) is False, \
        "the same banner in the same state is the duplicate run"
    # …and the OTHER hook has not had its turn taken away.
    assert book.worth_a_run("stats", mark=True) is True
    assert book.worth_a_run("stats", mark=True) is False


def test_seats_moving_is_news():
    """A join left, a seat opened — that is the push that actually sends squads."""
    book = BannerBook()
    _banner(book, slots="2/5")
    assert book.worth_a_run("join", mark=True) is True
    _banner(book, slots="3/5")
    assert book.worth_a_run("join", mark=True) is True, \
        "a banner whose seats moved must reach the join"


def test_a_new_banner_is_always_news():
    book = BannerBook()
    _banner(book, team="1")
    book.worth_a_run("join", mark=True)
    _banner(book, team="2")
    assert book.worth_a_run("join", mark=True) is True


def test_a_silent_book_never_refuses():
    """The book is a FLOOR under the join, never its source: a profile whose ear is off
    still joins off the client's own march table."""
    assert BannerBook().worth_a_run("join", mark=True) is True


def test_a_banner_that_has_gone_is_forgotten():
    """…so its uuid cannot hold a record for ever, and a re-used one is not muted."""
    book = BannerBook()
    _banner(book, team="1")
    book.worth_a_run("join", mark=True)
    assert book.weighed("join") == 1
    with book._lock:                      # the banner leaves the map
        book._seen.clear()
    book.worth_a_run("join", mark=True)
    assert book.weighed("join") == 0


def test_the_join_gate_reads_the_book_and_says_why():
    limits = _gate()
    book = BannerBook()
    _banner(book)
    rt = _RT(book)
    assert limits._already_weighed(rt, "join") is None
    assert limits._already_weighed(rt, "join") == "rally.skip.same_banners"


def test_the_two_gates_do_not_share_a_record():
    limits = _gate()
    book = BannerBook()
    _banner(book)
    rt = _RT(book)
    assert limits._already_weighed(rt, "join") is None
    assert limits.monitor_precondition(rt) is None, \
        "the statistics hook must not be refused because the join has just looked"
    assert limits.monitor_precondition(rt) == "rally.skip.same_banners"


def test_a_runtime_without_a_book_passes():
    limits = _gate()

    class _Bare:
        pass

    assert limits._already_weighed(_Bare(), "join") is None


def test_the_reason_is_a_key_in_every_shipped_locale():
    import json

    for path in sorted((_REPO / "panel" / "locales").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        assert "rally.skip.same_banners" in table, path.name


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
