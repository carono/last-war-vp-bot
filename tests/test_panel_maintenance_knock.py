r"""A CLIENT THAT IS UP, CONNECTED AND NOT IN THE GAME GETS KNOCKED ON (#1549).

WHAT THIS FILE IS FOR. Server maintenance was caught live on 2026-08-19
(docs/research/server-maintenance.md) and the finding was not the maintenance — it was
that **nothing in the panel had a cure, or even a word, for it**. Every reading stayed
green for the whole window: `game=up link=online daemon=warm`. The sockets were fine, so
`Recovery.note` did nothing; there was no kick; the daemon was neither stale nor down.
Meanwhile the account sat on «Сервер находится на техническом обслуживании» and every
errand failed one at a time.

The operator's instruction was one sentence — «при техобслуживании клиент перезапускай
каждые 15 минут» — and this is the rule it turned into, plus the guards that keep it from
becoming the thing this module fears most: a restart loop that eats a healthy account.

What is pinned here:

  * a client that is PLAYING is never touched, and one that is `offline` or `lost`
    belongs to the branches that already own it — two things must not restart one client;
  * «could not ask» is treated as not-playing, deliberately: it is what maintenance looks
    like from here, and a client the panel cannot talk to for seven minutes is no more
    use than one at the login screen;
  * the first knock waits out a GRACE longer than a login takes, so an ordinary start-up
    is never interrupted;
  * after that it is one knock per cooldown — the operator's fifteen minutes;
  * a person at the machine wins, and a kick's wait is not interrupted to knock;
  * getting into the game clears everything, count included, so three separate windows in
    a day read as three;
  * and the words exist in all eleven locales, for the log line, the window strip and
    the phone.

Needs no display; tkinter is stubbed:

    python3 tests/test_panel_maintenance_knock.py
"""
from __future__ import annotations

TIER = "pure"      # tkinter is stubbed below — no display, no widgets, no game

import importlib.util
import json
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# `panel.runtime`'s own `__init__` reaches the whole panel and therefore Tk, and the
# module under test needs neither. Loaded by path under a fabricated package, the same
# way tests/test_panel_flow.py does it.
_PKG = types.ModuleType("_recpkg")
_PKG.__path__ = [str(_REPO / "panel" / "runtime")]
sys.modules["_recpkg"] = _PKG


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_recpkg.{name}", _REPO / "panel" / "runtime" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rec = _load("recovery")

ONLINE, LOST, OFFLINE, UNKNOWN = "online", "lost", "offline", "unknown"
AWAY = 10_000.0          # nobody has touched the keyboard in hours


def _r():
    return rec.Recovery()


def _grace(r) -> float:
    return r.stalled_grace_sec


# ---------------------------------------------------------------------------
# it does nothing at all to a client that is fine
# ---------------------------------------------------------------------------
def test_a_client_in_the_game_is_never_touched():
    r = _r()
    for t in range(0, 7200, 60):
        assert r.note_session(True, ONLINE, float(t), idle_sec=AWAY) is None
    assert r.state(7200.0)["stalled_for"] == 0


def test_a_client_that_is_offline_or_lost_belongs_to_the_other_branches():
    """Two things must not restart one client — the rule this module has always kept."""
    for link in (OFFLINE, LOST, UNKNOWN):
        r = _r()
        assert r.note_session(False, link, 0.0, idle_sec=AWAY) is None
        assert r.note_session(False, link, 100_000.0, idle_sec=AWAY) is None


# ---------------------------------------------------------------------------
# the knock
# ---------------------------------------------------------------------------
def test_the_first_knock_waits_out_the_grace_and_not_a_second_less():
    r = _r()
    assert r.note_session(False, ONLINE, 0.0, idle_sec=AWAY) is None
    just_early = _grace(r) - 1
    assert r.note_session(False, ONLINE, just_early, idle_sec=AWAY) is None
    said = r.note_session(False, ONLINE, _grace(r), idle_sec=AWAY)
    assert said is not None and said[0] == rec.ACT_STALLED, said


def test_an_ordinary_login_is_never_interrupted():
    """`launch_game` waits up to 300 s for the city scene; the grace is longer on purpose."""
    assert rec.STALLED_GRACE_SEC > 300.0
    r = _r()
    r.note_session(False, ONLINE, 0.0, idle_sec=AWAY)
    # …and five minutes in, the client finally lands in the game
    assert r.note_session(False, ONLINE, 300.0, idle_sec=AWAY) is None
    assert r.note_session(True, ONLINE, 301.0, idle_sec=AWAY) is None
    assert r.state(301.0)["stalled_for"] == 0


def test_after_the_first_it_is_one_knock_per_cooldown():
    """The operator's own number: «перезапускай каждые 15 минут»."""
    assert rec.STALLED_COOLDOWN_SEC == 900.0
    r = _r()
    r.note_session(False, ONLINE, 0.0, idle_sec=AWAY)
    t = _grace(r)
    assert r.note_session(False, ONLINE, t, idle_sec=AWAY)[0] == rec.ACT_STALLED
    # …nothing for the next fifteen minutes, however often it is asked
    for step in range(30, int(rec.STALLED_COOLDOWN_SEC), 30):
        assert r.note_session(False, ONLINE, t + step, idle_sec=AWAY) is None
    said = r.note_session(False, ONLINE, t + rec.STALLED_COOLDOWN_SEC, idle_sec=AWAY)
    assert said is not None and said[0] == rec.ACT_STALLED
    assert r.state(t + rec.STALLED_COOLDOWN_SEC)["stalled_restarts"] == 2


def test_could_not_ask_counts_as_not_playing():
    """`None` is what maintenance looks like from here — the VM answers nothing."""
    r = _r()
    r.note_session(None, ONLINE, 0.0, idle_sec=AWAY)
    said = r.note_session(None, ONLINE, _grace(r), idle_sec=AWAY)
    assert said is not None and said[0] == rec.ACT_STALLED


# ---------------------------------------------------------------------------
# the guards
# ---------------------------------------------------------------------------
def test_a_person_at_the_machine_wins():
    r = _r()
    r.note_session(False, ONLINE, 0.0, idle_sec=0.0)
    assert r.note_session(False, ONLINE, _grace(r), idle_sec=5.0) is None
    assert r.state(_grace(r))["held_by"] == "player"
    # …and when they leave, the knock happens
    said = r.note_session(False, ONLINE, _grace(r) + 1, idle_sec=AWAY)
    assert said is not None and said[0] == rec.ACT_STALLED


def test_a_kicks_wait_is_not_interrupted_to_knock_on_a_door():
    """A kicked client is not in a session either — and its cure has its own patience."""
    r = _r()
    r.kick_hold_sec = 900.0
    for t in (0.0, 1.0, 2.0):                    # a run of kick readings arms the wait
        r.note(ONLINE, t, idle_sec=AWAY, kicked=True)
    assert r.kick_hold_left(3.0) > 0
    r.note_session(False, ONLINE, 3.0, idle_sec=AWAY)
    assert r.note_session(False, ONLINE, _grace(r) + 3.0, idle_sec=AWAY) is None


# ---------------------------------------------------------------------------
# what it says, and to whom
# ---------------------------------------------------------------------------
def test_getting_into_the_game_clears_the_clock_and_the_count():
    r = _r()
    r.note_session(False, ONLINE, 0.0, idle_sec=AWAY)
    r.note_session(False, ONLINE, _grace(r), idle_sec=AWAY)
    assert r.state(_grace(r))["stalled_restarts"] == 1
    r.note_session(True, ONLINE, _grace(r) + 60, idle_sec=AWAY)
    st = r.state(_grace(r) + 60)
    assert st["stalled_restarts"] == 0 and st["stalled_for"] == 0
    assert st["held_by"] != "stalled"


def test_the_state_carries_the_three_numbers_both_front_ends_draw():
    r = _r()
    r.note_session(False, ONLINE, 0.0, idle_sec=AWAY)
    st = r.state(120.0)
    assert st["stalled_for"] == 120
    assert st["stalled_next"] == int(rec.STALLED_GRACE_SEC - 120)
    assert st["stalled_restarts"] == 0
    json.dumps(st)                              # it survives the trip to a phone


def test_the_act_is_a_client_restart_and_the_panel_knows_it():
    assert rec.ACT_STALLED in rec.RESTARTS
    assert rec.ACT_STALLED not in rec.DAEMON_RESTARTS
    assert rec.ACT_STALLED not in rec.KICK_ACTS      # it starts no kick stability clock


def test_every_word_of_it_is_in_every_shipped_locale():
    keys = (rec.ACT_STALLED, "status.recovery.stalled", "web.ui.recovery.stalled")
    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, [p.name for p in locales]
    for path in locales:
        words = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in words, (path.name, key)


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
