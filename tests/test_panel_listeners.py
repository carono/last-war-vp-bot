r"""Everything this profile listens to, and whether any of it is arriving (#1416).

«Пропускаются события» cannot be answered from a list of subscriptions. A listener that
has gone deaf and one sitting over a quiet map look identical from outside: both are
switched on, both say nothing, and the log is quiet either way. So «Занятость» grew a
LISTENERS section, and every row of it carries three things:

* WHAT is being listened to — the pattern, the trigger, the capture tool;
* WHETHER IT WORKS — `alive` (the process or the watch is up) AND `since` (how long ago
  something last came through). Neither alone is proof: a live capture that has heard
  nothing since it started is precisely the fault being hunted;
* WHY IT EXISTS — a locale key, so a row explains itself to whoever did not switch it on.

This pins the collector (`panel/runtime/busy.py::listeners`), which is the half that has
to be right for the drawing to mean anything. No Tk, no game, no I/O — the runtime is a
stub with the three sources on it::

    python3 tests/test_panel_listeners.py
    C:\Python312\python.exe tests\test_panel_listeners.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# `panel.runtime`'s own `__init__` pulls in the host and, with it, Tk — which this test
# has no use for and which a headless interpreter may not have at all. So the package is
# stood up as a bare namespace over the same directory and the module is imported into
# it: relative imports (`from . import claims`) resolve exactly as they do in the panel,
# and nothing that draws is executed.
import importlib                                           # noqa: E402
import types                                               # noqa: E402

_pkg = types.ModuleType("panel.runtime")
_pkg.__path__ = [str(_REPO / "panel" / "runtime")]
sys.modules.setdefault("panel", types.ModuleType("panel")).__path__ = [str(_REPO / "panel")]
sys.modules["panel.runtime"] = _pkg
busymod = importlib.import_module("panel.runtime.busy")


class _Hub:
    def __init__(self, rows) -> None:
        self._rows = rows

    def report(self):
        return list(self._rows)


class _Watcher:
    def __init__(self, rows) -> None:
        self._rows = rows

    def report(self):
        return list(self._rows)


class _Child:
    def __init__(self, tool, tag, alive=True, lines=0, last=0.0, pid=1) -> None:
        self.cmd = ["C:\\Python312\\python.exe", "-u", f"P:\\repo\\tools\\{tool}", "--json"]
        self.tag, self.alive, self.lines, self.last_line_at, self.pid = (
            tag, alive, lines, last, pid)


class _Factory:
    def __init__(self, kids) -> None:
        self.live = list(kids)


class _RT:
    def __init__(self, wire=None, triggers=None, children=None) -> None:
        self.wire, self.triggers, self.children = wire, triggers, children


def _rows(**kw):
    return busymod.listeners(_RT(**kw), now=1000.0)


def test_a_subscription_says_what_it_hears_and_when():
    rows = _rows(wire=_Hub([{"pattern": "push.alliance.march", "subscribers": 2,
                             "heard": 412, "last": 995.0,
                             "command": "push.alliance.march.refresh", "alive": True}]))
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "wire" and row["what"] == "push.alliance.march"
    assert row["alive"] and row["heard"] == 412
    assert abs(row["since"] - 5.0) < 0.001, row
    assert row["desc"], "a row with no description explains nothing to anybody"


def test_a_listener_that_has_never_heard_anything_says_so():
    """`since=None` is «ни разу», and it is NOT the same as «давно» — that difference is
    the whole point of the section."""
    rows = _rows(wire=_Hub([{"pattern": "al.help.new", "subscribers": 1, "heard": 0,
                             "last": 0.0, "command": "", "alive": True}]))
    assert rows[0]["since"] is None and rows[0]["heard"] == 0


def test_a_dead_ear_is_reported_dead_even_though_it_still_has_subscribers():
    """The capture child died; the subscriptions did not notice. That IS the fault."""
    rows = _rows(wire=_Hub([{"pattern": "al.help.new", "subscribers": 3, "heard": 9,
                             "last": 900.0, "command": "al.help.new", "alive": False}]))
    assert rows[0]["alive"] is False
    assert rows[0]["since"] == 100.0


def test_a_trigger_that_is_switched_off_is_still_listed():
    """«Этот слушатель выключен» is an answer; a missing row is not."""
    rows = _rows(triggers=_Watcher([
        {"name": "rally_auto_join", "signal": "push.alliance.march", "poll": False,
         "observe": False, "label": "triggers.item.rally_auto_join", "title": "",
         "watching": False, "fires": 0, "last": 0.0},
        {"name": "session_kick", "signal": "(function() … end)()", "poll": True,
         "observe": True, "label": "triggers.item.session_kick", "title": "",
         "watching": True, "fires": 2, "last": 940.0}]))
    off, poll = rows
    assert off["kind"] == "trigger" and off["alive"] is False
    assert off["desc"] == "triggers.item.rally_auto_join", "a trigger describes itself"
    assert poll["kind"] == "poll" and poll["alive"] and poll["since"] == 60.0


def test_a_capture_child_is_named_by_its_tool_not_by_its_slot():
    """Two very different sniffers share the tag «secret»; the tool is what differs."""
    rows = _rows(children=_Factory([
        _Child("secret_task_capture.py", "secret", lines=812, last=999.0),
        _Child("dev/secret_mission_capture.py", "secret", lines=40, last=200.0)]))
    stars, ghost = rows
    assert stars["what"] == "secret_task_capture.py"
    assert stars["desc"] == "busy.listener.secret_tasks"
    assert ghost["what"] == "secret_mission_capture.py", "a path is not a name"
    assert ghost["desc"] == "busy.listener.ghost"
    assert ghost["since"] == 800.0 >= busymod.LISTENER_QUIET_SEC


def test_an_unknown_tool_still_gets_a_row():
    """A listener nobody wrote a line for is exactly the one somebody will be hunting."""
    rows = _rows(children=_Factory([_Child("some_new_capture.py", "trigger", lines=1,
                                           last=1000.0)]))
    assert rows[0]["what"] == "some_new_capture.py" and rows[0]["desc"] == ""


def test_a_runtime_with_none_of_the_three_answers_empty_rather_than_raising():
    """A debugger that raises while explaining a jam is worse than no debugger."""
    assert busymod.listeners(_RT(), now=1.0) == []


def test_every_description_key_exists_in_every_shipped_locale():
    """A row whose description falls back to English says the wrong thing quietly."""
    keys = set(busymod.CHILD_KINDS.values()) | {
        "busy.listener.push", "busy.section.listeners",
        "busy.listen.hearing", "busy.listen.quiet", "busy.listen.never",
        "busy.listen.kind.wire", "busy.listen.kind.trigger",
        "busy.listen.kind.poll", "busy.listen.kind.capture",
        "busy.listen.line.heard", "busy.listen.line.never", "busy.listen.line.off"}
    for path in sorted((_REPO / "panel" / "locales").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(k for k in keys if k not in table)
        assert not missing, f"{path.name}: {missing}"


def test_the_snapshot_carries_the_section():
    """…and the drawing reads it off the snapshot like every other section."""
    snap = busymod.snapshot(_RT(wire=_Hub([{"pattern": "rank", "subscribers": 1,
                                            "heard": 1, "last": time.monotonic(),
                                            "command": "al.rank", "alive": True}])))
    assert [row["what"] for row in snap["listeners"]] == ["rank"]


def test_the_tile_marker_is_one_string_in_two_processes():
    """The capture and the panel agree on it and on nothing else (#1416).

    A find reaches the list as an EVENT now — the child prints the tile, the panel's hook
    parses it and hands it over. Both halves spell the marker for themselves, so a rename
    on one side would leave the other silently reading nothing: exactly the failure the
    whole task is about, and the cheapest possible test for it.
    """
    tool = (_REPO / "tools" / "secret_task_capture.py").read_text(encoding="utf-8")
    hook = (_REPO / "panel" / "tabs" / "secret_tasks" / "capture.py").read_text(
        encoding="utf-8")
    assert 'TILE_MARKER = "##TILE##"' in tool, "the capture no longer speaks tiles"
    assert 'TILE_MARKER = "##TILE##"' in hook, "the panel no longer listens for them"
    assert "TILE_MARKER + " in tool, "the marker is defined and never printed"


def test_the_tile_line_carries_no_owner():
    """A tile is a place on the map; whose base it is stays out of the stream (#1293).

    Everything this child prints lands in `panel.log`, which is a file people send each
    other when something goes wrong.
    """
    tool = (_REPO / "tools" / "secret_task_capture.py").read_text(encoding="utf-8")
    line = tool[tool.index("TILE_MARKER + "):]
    line = line[:line.index("ensure_ascii")]
    # `uuid` is the TILE's own id and is wanted; `uid` on its own is a PLAYER's, and
    # so is a name or an alliance. The keys of the object are what is checked, not the
    # prose around it.
    import re as _re
    fields = set(_re.findall(r'"(\w+)":', line))
    for banned in ("owner_uid", "alliance_id", "uid", "ownerUid", "name", "owner"):
        assert banned not in fields, f"the tile event carries {banned}: {sorted(fields)}"


def test_a_tile_is_never_dropped_because_the_tab_is_not_open():
    """The buffer is not a place an event may die (#1416).

    A tab nobody has looked at has no model to merge into. The tiles have arrived all
    the same — the capture is a standing order, not something a tab switches on — so the
    landing pass keeps them and comes back, rather than emptying the buffer into
    nothing. Read off the source, because building a tab needs Tk and this rule is one
    branch.
    """
    src = (_REPO / "panel" / "tabs" / "secret_tasks" / "tab.py").read_text(
        encoding="utf-8")
    body = src[src.index("def _tiles_land"):]
    body = body[:body.index("def _rank_of")]
    guard = body[body.index("if not self.loaded"):]
    guard = guard[:guard.index("return") + len("return")]
    assert "arm(" in guard, "an unopened tab must re-arm the pass, not swallow the tiles"
    assert body.index("if not self.loaded") < body.index("self._tiles, {}"), \
        "the buffer must not be emptied before the tab is known to be there"


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
