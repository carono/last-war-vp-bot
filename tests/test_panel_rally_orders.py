r"""The rally auto-join's standing rules reach the schedule on BOTH front-ends (#2051).

THE BUG THIS PINS. «rally_auto_join» is a trigger of the schedule's and fires in every
open profile. Four things it needs belong to the rally code rather than to the schedule —
the arguments it is played with, the hook that writes the count down, and two
preconditions — and all four were registered inside `Panel._open_session_page`, which
only a WINDOW ever reaches. A headless panel therefore joined banners all day with:

  * no `targets`, so every banner fell back to the `monster` kind;
  * no `kind_left`, so the press was handed no per-kind budget at all;
  * `max_joins` and `min_soldiers` at their defaults, so the day's ceiling and the
    soldier floor the person had typed were ignored;
  * nothing calling `record_run`, so `rally_counts` never moved and the counter on the
    screen stood still while the log showed hundreds of joins.

Measured on one live day: 544 runs, 537 of them reporting «no banner targets were parked
at all» and «the panel handed no per-kind budget at all», `kind_capped=` not once.

So the wiring is one module both front-ends call, and this test fails if either of them
stops calling it — or if `wire` starts needing a display to run.

No Tk, no game, no wire::

    python3 tests/test_panel_rally_orders.py
    C:\Python312\python.exe tests\test_panel_rally_orders.py
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# `panel.runtime`'s own `__init__` pulls in the host and, with it, Tk. The wiring touches
# no widget, so the package is stood up as a bare namespace over the same directory and
# the module is imported into it — relative imports resolve exactly as they do in the
# panel. That this WORKS is half of what is being pinned: `wire` must not import the
# rally tab (and Tk behind it) merely to register four callables.
sys.modules.setdefault("panel", types.ModuleType("panel")).__path__ = [str(_REPO / "panel")]
_pkg = types.ModuleType("panel.runtime")
_pkg.__path__ = [str(_REPO / "panel" / "runtime")]
sys.modules["panel.runtime"] = _pkg
orders = importlib.import_module("panel.runtime.rally_orders")

#: The four rules, as `(register method, errand name)`. A fifth would be a new rule and
#: is meant to break this list rather than slip in on one front-end only.
EXPECTED = (("gate", "rally_auto_join"),
            ("args", "rally_auto_join"),
            ("precondition", "rally_auto_join"),
            ("precondition", "rally_monitor"))


class _Schedule:
    def __init__(self) -> None:
        self.calls: list = []

    def register_gate(self, name, gate, record=None) -> None:
        self.calls.append(("gate", name))
        self.gate, self.record = gate, record

    def register_args(self, name, source) -> None:
        self.calls.append(("args", name))
        self.args = source

    def register_precondition(self, name, check) -> None:
        self.calls.append(("precondition", name))


class _RT:
    def __init__(self, schedule=None) -> None:
        self.schedule = schedule


def test_wire_registers_all_four_rules() -> None:
    schedule = _Schedule()
    orders.wire(_RT(schedule))
    assert schedule.calls == list(EXPECTED), schedule.calls


def test_wire_survives_a_runtime_with_no_schedule() -> None:
    """A profile still coming up must not take the panel down with it."""
    orders.wire(_RT(None))
    orders.wire(_RT(object()))


def test_the_bind_is_used_when_one_is_given() -> None:
    """The window hands its `_bound`; every callable registered goes through it."""
    seen = []

    def bind(func):
        seen.append(func)
        return func

    schedule = _Schedule()
    orders.wire(_RT(schedule), bind)
    # Five callables: the gate and its record, the arguments, and the two preconditions.
    assert len(seen) == 5, seen


def _source(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8")


def test_both_front_ends_call_the_wiring() -> None:
    """The whole of #2051: the window is not the only thing that starts a profile."""
    for rel in ("panel/__main__.py", "panel/headless.py"):
        text = _source(rel)
        assert "rally_orders" in text, rel
        assert "rallyorders.wire(" in text, rel


def test_the_rules_are_registered_nowhere_else() -> None:
    """One home, so a third front-end cannot half-inherit them.

    `panel/runtime/rally_orders.py` is the only place that may name these four
    registrations; anything else naming them is a second copy about to drift.
    """
    for path in sorted((_REPO / "panel").rglob("*.py")):
        if path.name == "rally_orders.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "rally_auto_join" not in text:
            continue
        # A tab or a catalogue may MENTION the errand; what it may not do is register a
        # gate or the arguments for it.
        for forbidden in ("register_gate", "register_args"):
            spot = text.find(forbidden)
            while spot >= 0:
                window = text[spot:spot + 200]
                assert "rally_auto_join" not in window, f"{path}: {forbidden}"
                spot = text.find(forbidden, spot + 1)


def _main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    bad = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except Exception as exc:                  # noqa: BLE001 — a report, not a run
            bad += 1
            print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
