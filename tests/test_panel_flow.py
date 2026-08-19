r"""«ИДУТ ЛИ ДАННЫЕ, И БЕРЁМ ЛИ МЫ ИХ» — the badge every fed grid draws (#1549).

WHAT THIS FILE IS FOR. The operator's report was one sentence: «Я хожу по карте, и грид
не заполняется.» An empty table cannot answer it, because four different things draw the
same empty table — nothing is being sent, something IS being sent and we are not taking
it, it was taken and thrown away, or the source is dead. Telling those apart by hand cost
days, one at a time.

So `panel/runtime/flow.py` joins the two halves that already existed — the intake ledger
(what a receiver did with what it was handed) and `busy.listeners` (whether the source is
alive) — into ONE record per receiver, and every grid draws it above its own table.

What is pinned here is the DISTINCTION, not the wording:

  * a receiver that has taken nothing while its source HAS heard things is `starving`,
    and one whose source has heard nothing is `never`. Those two were the same blank
    page for years and they lead a person to do opposite things;
  * a receiver that has LOST something outranks everything else — there is no ordinary
    number of thrown-away events;
  * a dead source says so even when rows are still on screen, because the rows are the
    last it ever sent;
  * freshness is of an ARRIVAL and never of a refusal: a monster poll ticking every
    twenty seconds against a client in the base records a `dropped` each time, and
    reading that clock would paint «идёт прямо сейчас» over a dead page;
  * the badge is DATA — a locale key, numbers and a colour — so the window and the phone
    say it in whatever language each is showing;
  * and every receiver a grid names has a row in the table, so a page whose feed has
    never fired still gets a strip that says «ни разу».

Needs no display and no Tk:

    python3 tests/test_panel_flow.py
"""
from __future__ import annotations

TIER = "pure"      # plain data: no Tk, no display, no game

import json
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# LOADED BY PATH, not through `panel.runtime` — that package's `__init__` reaches the
# whole panel and therefore Tk, and none of the three modules under test needs a window.
# This is what makes the file `TIER = "pure"`: it runs under a bare interpreter on a
# machine with no display and no tkinter at all.
import importlib.util                                        # noqa: E402

_PKG = types.ModuleType("_flowpkg")
_PKG.__path__ = [str(_REPO / "panel" / "runtime")]
sys.modules["_flowpkg"] = _PKG


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_flowpkg.{name}", _REPO / "panel" / "runtime" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("claims")
intakemod = _load("intake")
_load("busy")
flowmod = _load("flow")


class _Child:
    """A capture child as `busy.listeners` reads one — the fields and nothing else."""

    def __init__(self, tool: str, alive: bool = True, lines: int = 0,
                 last: float = 0.0) -> None:
        self.cmd = ("python", f"tools/{tool}")
        self.alive = alive
        self.lines = lines
        self.last_line_at = last
        self.tag = ""
        self.pid = 1


class _Factory:
    def __init__(self, *kids) -> None:
        self.live = list(kids)


def _rt(*kids):
    rt = types.SimpleNamespace()
    rt.intake = intakemod.Intake()
    rt.children = _Factory(*kids)
    return rt


def _fresh(rt):
    """Forget the cached board — the tests move faster than `CACHE_SEC`."""
    rt._flow_board = None


# ---------------------------------------------------------------------------
# the distinction the module exists for
# ---------------------------------------------------------------------------
def test_a_source_that_is_heard_from_and_a_receiver_that_takes_none_is_starving():
    rt = _rt(_Child("secret_task_capture.py", alive=True, lines=25563, last=1.0))
    badge = flowmod.badge(rt, "secret.tiles")
    assert badge["state"] == flowmod.STARVING, badge
    assert badge["source"]["heard"] == 25563


def test_a_silent_source_and_a_receiver_that_took_none_is_never_not_starving():
    rt = _rt(_Child("secret_task_capture.py", alive=True, lines=0))
    assert flowmod.badge(rt, "secret.tiles")["state"] == flowmod.NEVER


def test_a_loss_outranks_every_other_state():
    rt = _rt(_Child("secret_task_capture.py", alive=True, lines=10, last=1.0))
    rt.intake.at("secret.tiles").seen(10)
    rt.intake.at("secret.tiles").lost(1, reason="torn")
    badge = flowmod.badge(rt, "secret.tiles")
    assert badge["state"] == flowmod.LOSING, badge
    assert "torn" in flowmod.why(badge)


def test_a_dead_source_says_so_even_with_rows_already_taken():
    rt = _rt(_Child("rally_monitor.py", alive=False, lines=40, last=1.0))
    rt.intake.at("rally.banners").seen(40)
    rt.intake.at("rally.banners").kept(40)
    assert flowmod.badge(rt, "rally.banners")["state"] == flowmod.DEAD


def test_something_arriving_now_is_flowing_and_long_ago_is_quiet():
    rt = _rt()
    rt.intake.at("world.monsters").seen(177)
    rt.intake.at("world.monsters").kept(177)
    assert flowmod.badge(rt, "world.monsters")["state"] == flowmod.FLOWING
    _fresh(rt)
    later = flowmod.board(rt, now=_now(rt) + flowmod.FRESH_SEC + 1)
    assert later["world.monsters"]["state"] == flowmod.QUIET


def _now(rt) -> float:
    import time

    return time.monotonic()


# ---------------------------------------------------------------------------
# the one that would have hidden the bug again
# ---------------------------------------------------------------------------
def test_a_refusal_does_not_count_as_an_arrival():
    """A poll refused every tick must not read as «данные идут прямо сейчас».

    The monster follow ticks every twenty seconds and records a `dropped` while the
    client is in the base. If freshness were read off «anything at all happened», that
    page would be painted green for ever while nothing reached it.
    """
    rt = _rt()
    take = rt.intake.at("world.monsters")
    take.seen(177)
    take.kept(177)
    now = _now(rt) + flowmod.FRESH_SEC + 5
    # …an hour of refusals later, the ARRIVAL is still the old one
    for _ in range(5):
        take.dropped(reason="not_in_world")
    _fresh(rt)
    badge = flowmod.board(rt, now=now)["world.monsters"]
    assert badge["state"] == flowmod.QUIET, badge
    assert badge["dropped"] == 5
    assert "not_in_world" in flowmod.why(badge)


# ---------------------------------------------------------------------------
# it is data, and every named receiver has a row
# ---------------------------------------------------------------------------
def test_the_badge_carries_no_words_at_all():
    rt = _rt()
    rt.intake.at("chat.messages").seen(3)
    said = flowmod.line(flowmod.badge(rt, "chat.messages"))
    assert said["key"].startswith("flow.state.")
    assert set(said["fmt"]) == {"seen", "kept", "dropped", "lost", "since",
                                "heard", "why"}
    json.dumps(said)                      # it survives the trip to a phone


def test_every_state_has_a_key_and_a_colour():
    for state in (flowmod.LOSING, flowmod.STARVING, flowmod.DEAD, flowmod.NEVER,
                  flowmod.FLOWING, flowmod.QUIET):
        assert state in flowmod.LINE_KEYS
        assert state in flowmod.COLOURS


def test_every_named_receiver_gets_a_row_even_before_it_has_fired():
    """A page whose feed has never run still gets a strip — and it says WHICH silence.

    With nothing started at all, a receiver that is ASKED (no listener behind it) has
    simply never heard anything; one that is TOLD by a capture child has a source that
    is not running, which is a different sentence and a different thing to do about it.
    """
    rt = _rt()
    board = flowmod.build(rt)
    for name in flowmod.SOURCES:
        assert name in board, name
        want = flowmod.NEVER if not flowmod.sources_of(name) else flowmod.DEAD
        assert board[name]["state"] == want, (name, board[name]["state"])


def test_a_receiver_with_no_listener_behind_it_has_no_source_rather_than_a_dead_one():
    """The monster page is ASKED, never told — inventing a source would be a lie."""
    rt = _rt()
    assert flowmod.badge(rt, "world.monsters")["source"] is None
    assert flowmod.sources_of("world.monsters") == ()


# ---------------------------------------------------------------------------
# the words exist, in all eleven
# ---------------------------------------------------------------------------
def test_every_state_key_is_in_every_shipped_locale():
    locales = sorted((_REPO / "panel" / "locales").glob("*.json"))
    assert len(locales) >= 11, [p.name for p in locales]
    for path in locales:
        words = json.loads(path.read_text(encoding="utf-8"))
        for key in flowmod.LINE_KEYS.values():
            assert key in words, (path.name, key)


def test_every_grid_that_names_an_intake_names_one_the_table_knows():
    """A page whose receiver is not in `SOURCES` would get a badge nobody feeds."""
    import re

    named = set()
    for path in (_REPO / "panel").rglob("*.py"):
        for m in re.finditer(r'^\s*INTAKE = "([^"]+)"', path.read_text(encoding="utf-8"),
                             re.M):
            named.add(m.group(1))
    assert named, "no grid names an INTAKE at all"
    for name in named:
        assert name in flowmod.SOURCES, name


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
