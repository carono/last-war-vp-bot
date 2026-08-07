r"""The panel's auto-loot watcher — what it decides to fire at, and when it does not.

The «Автолут ★» checkbox is a standing order: while it is ticked a watcher thread looks
at the tab's list and robs whatever the rule wants (task #1109). Since #1256 two things
about that sentence are load-bearing:

  * **the rule is ONE number** — «минимальный уровень», this level and everything above
    it. The range it replaces robbed its TOP and nothing else, so «от 1 до 7» left a
    raidable 6 standing there for ever;
  * **it looks at OUR LIST** (`SecretTasksTab.rob_candidates`) and at no source of its
    own. It used to re-read the live VM and the capture checkpoint through a copy of the
    rule, which meant the list on screen and the thing spending the day's five robberies
    were two different answers about the same map. What it chooses now travels to the
    child BY NAME (`--targets uuid:server,…`), so the child re-derives nothing either.

*Which* rows are in that list, and how they get there, is `test_panel_secret_tasks.py`.
What is tested here is the layer above it — the part that can quietly burn the day's
five robberies:

  * nothing in the list yet — one complaint, not one per poll;
  * nothing at or above the minimum — no robbery at all;
  * a target is sent **once**: the list keeps showing a tile the server refused, or one
    we robbed before its loot count comes back;
  * no second robbery while one is still running, and none while the budget is spent;
  * a client that is not logged in is said out loud, not robbed through.

The watcher is driven against a stub tab, so no Tk window is opened and no game is
needed. That does mean **tkinter must be importable**: under the WSL python3 it is not,
so there the test says SKIP and passes. Run it under the Windows Python to actually
exercise it::

    C:\Python312\python.exe tests\test_panel_autoloot.py
    python3 tests/test_panel_autoloot.py        # SKIP without tkinter
"""
from __future__ import annotations

import sys
import tempfile
import time
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_runtime  # noqa: E402

try:
    import tkinter  # noqa: F401
    _HAS_TK = True
except Exception:       # noqa: BLE001 — no display is fine, no module is not
    _HAS_TK = False


def _row(uuid: int, level: int, server: int = 999, starred: bool = True,
         ready: bool = True, loot_count: int = 0) -> dict:
    """One row of the tab's list, in the shape `rob_candidates` reads."""
    now_ms = int(time.time() * 1000)
    return {"uuid": uuid, "server": server, "x": 100 + uuid, "y": 200,
            "level": level, "starred": starred, "ready": ready,
            "loot_count": loot_count,
            "completed_at": now_ms - 60_000, "expires_at": now_ms + 3_600_000}


class _Tab:
    """The stub tab: OUR LIST, the rule over it, and the words the watcher says.

    `rob_candidates` mirrors the real tab's — the rule it applies is the one the watcher
    is aimed by, and a stub that chose differently would test nothing. The rows are
    plain dicts, which is what they are in the tab too.
    """

    def __init__(self, rows, level_min="", own_server=534, t=None,
                 say=None):
        self.rows = {str(r["uuid"]): r for r in rows}
        self.level_min_var = types.SimpleNamespace(get=lambda: level_min)
        self.autoloot_var = types.SimpleNamespace(get=lambda: True)
        self.capture = types.SimpleNamespace(running=False)
        self._own = own_server
        self.t = t
        self.say = say
        self.autoloot = None            # set by `_Watcher` below

    def own_server(self) -> int:
        return self._own

    def has_rows(self) -> bool:
        return bool(self.rows)

    def rob_candidates(self) -> list:
        low = self.autoloot.level_min()
        skip = self.autoloot.skip_server()
        if not skip:                      # home unknown -> nothing is a target (#1188)
            return []
        rows = [r for r in self.rows.values()
                if r.get("ready") and r.get("starred")
                and int(r.get("loot_count") or 0) < 3
                and (low is None or int(r.get("level") or 0) >= low)
                and int(r.get("server") or 0) not in (0, skip)]
        rows.sort(key=lambda r: (-int(r.get("level") or 0),
                                 int(r.get("loot_count") or 0)))
        return rows


def _Watcher(rows=(), level_min="", own_server=534, logged_in=True):
    """The «Автолут ★» standing order over a stub list, wired to nothing else.

    No Tk root, no daemon, no child ever spawned — `run` records the targets the tick
    would have handed over.
    """
    from panel import runtime as rtmod
    from panel.tabs.secret_tasks.autoloot import AutoLoot

    logs: list = []
    i18n = rtmod.Translator("ru")
    bus = fake_runtime.RecordingBus(translate=i18n.t, lines=logs)
    tmp = Path(tempfile.mkdtemp())
    # The knobs live in the binder; with no widgets attached the saved dict is the
    # answer, so an empty one means SETTINGS_DEFAULTS — the auto-loot budget, the poll
    # period and the spent-pause.
    import panel.__main__ as pm
    settings = rtmod.SettingsBinder(profiles=None, defaults=pm.SETTINGS_DEFAULTS)
    rt = types.SimpleNamespace(
        # `secret_shared_json` is where the listener records «уже поделились» (#1245).
        profiles=types.SimpleNamespace(
            tasks_json=lambda: str(tmp / "secret_tasks.json"),
            secret_shared_json=lambda: str(tmp / "secret_shared.jsonl")),
        game=types.SimpleNamespace(up=lambda: True, client=None, busy=False,
                                   evaluator=lambda: None),
        settings=settings, log=bus, put=bus.put,
        children=types.SimpleNamespace(python=lambda: "python", spawn_raw=None),
        tick=types.SimpleNamespace(arm=lambda *a, **k: None))
    tab = _Tab(rows, level_min=level_min, own_server=own_server,
               t=i18n.t, say=bus.say)
    w = AutoLoot(rt, tab)
    tab.autoloot = w
    w.logs, w.runs = logs, []
    # Everything the panel says goes through the locale files, so the watcher's own
    # lines come out of `say` — with a real translator behind it, so the assertions are
    # on the words the operator actually reads.
    w.run = lambda targets: w.runs.append([u for u, _s, _l in targets])
    # The one live question the watcher still asks the game (#1227): can this client say
    # what time it is? Answered here rather than through a daemon.
    w.session_ready = lambda: logged_in
    return w


def test_the_watcher_fires_once_per_target_out_of_the_list():
    """The whole decision, walked as one session over a changing list."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    w = _Watcher()

    # An empty list: say so once, not on every poll, and rob nothing.
    w.tick()
    w.tick()
    assert w.runs == [], w.runs
    assert sum("список пуст" in m for m in w.logs) == 1, w.logs

    # A plain (unstarred) tile is not a target, however raidable.
    w.tab.rows = {"1": _row(1, 7, starred=False)}
    w.tick()
    assert w.runs == [], w.runs

    # Two stars appear -> both are handed over at once, best first, and the same list
    # does not fire a second time.
    w.tab.rows = {"1": _row(1, 7, starred=False), "2": _row(2, 6), "3": _row(3, 7)}
    w.tick()
    assert w.runs == [[3, 2]], w.runs
    assert w._seen == {2, 3}, w._seen
    assert any("цель:" in m for m in w.logs), w.logs
    w.tick()
    w.tick()
    assert w.runs == [[3, 2]], "re-fired at an already-sent target: %r" % (w.runs,)

    # A star the list did not have before is a fresh target — and only it.
    w.tab.rows["9"] = _row(9, 7)
    w.tick()
    assert w.runs == [[3, 2], [9]], w.runs

    # A robbery still running blocks a new one; so does the spent-budget pause.
    w.tab.rows["11"] = _row(11, 7)
    w._proc = object()
    w.tick()
    assert len(w.runs) == 2, "fired while a robbery was still running"
    w._proc = None
    w._pause_until = time.time() + 60
    w.tick()
    assert len(w.runs) == 2, "fired while the day's robberies were spent"
    w._pause_until = 0.0
    w.tick()
    assert w.runs[-1] == [11], w.runs


def test_the_minimum_level_takes_everything_above_it_and_nothing_below():
    """«минимальный уровень 7» leaves a 6 alone; lowered to 6, it takes both (#1256).

    The rule this replaces would have taken the 7 and NEVER the 6, whatever the boxes
    said — its range robbed only the top. The layer above the rule is where the day's
    five are actually spent, so the number the operator typed has to survive to here.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    w = _Watcher(rows=[_row(1, 5), _row(2, 6)], level_min="7")

    # Every star in the list is below the minimum: hold fire.
    w.tick()
    w.tick()
    assert w.runs == [], "robbed below the minimum level: %r" % (w.runs,)
    assert w._seen == set(), w._seen

    # A level-7 star arrives -> it is taken, and the 6 below still is not.
    w.tab.rows["3"] = _row(3, 7)
    w.tick()
    assert w.runs == [[3]], w.runs

    # Lower the bound and the 6 becomes a target too — the whole point of a minimum.
    w.tab.level_min_var = types.SimpleNamespace(get=lambda: "6")
    w.tick()
    assert w.runs == [[3], [2]], w.runs


def test_the_own_server_is_never_a_target_and_there_is_no_box_that_can_allow_it():
    """«Грабить исключительно на чужих серверах» (#1188) — the rule, not a preference.

    It used to hang off «Не грабить на своём сервере», shipped OFF, so an untouched
    profile robbed the neighbours. The cost of that is not an error anybody sees: it is
    one of the day's five spent where it was not wanted (#1099), which is exactly the
    shape of mistake a checkbox is the wrong guard for. So the box is gone and the
    exclusion is unconditional.

    The prohibition is applied where the targets are CHOSEN, not after — so the rule
    still picks the best allowed star instead of picking a forbidden one and coming
    back with nothing.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    w = _Watcher(rows=[_row(3, 7, server=534), _row(4, 7, server=999)],
                 level_min="1", own_server=534)
    w.tick()
    assert w.runs == [[4]], w.runs
    assert w._seen == {4}, "the tile on the own server was taken as a target: %r" % (
        w._seen,)

    # A home tile ALONE is not a fallback: the watcher does nothing rather than rob it.
    home_only = _Watcher(rows=[_row(3, 7, server=534)], level_min="1", own_server=534)
    home_only.tick()
    assert home_only.runs == [], "robbed at home with nothing else on the list: %r" % (
        home_only.runs,)

    # And there is no switch left that could bring the old behaviour back.
    from panel.tabs.secret_tasks.tab import SecretTasksTab
    assert not hasattr(SecretTasksTab, "skip_own_var"), "the box came back"
    src = (_REPO_ROOT / "panel" / "tabs" / "secret_tasks" / "tab.py").read_text("utf-8")
    assert "self.skip_own_var" not in src, "the tab still carries the prohibition's box"
    cmd_src = (_REPO_ROOT / "panel" / "tabs" / "command_post" / "tab.py").read_text("utf-8")
    assert "self._skip_own_var" not in cmd_src, "«Общие» still carries it"


def test_a_row_that_cannot_say_which_server_it_is_on_is_not_robbed_either():
    """`server = 0` is «the row never carried one», not «somewhere that is not home».

    Same reasoning as the unreadable own server below: a tile that cannot place itself
    must not be robbed on the strength of failing to say «here».
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    w = _Watcher(rows=[_row(5, 7, server=0)], level_min="1", own_server=534)
    w.tick()
    assert w.runs == [], "robbed a tile with no server on it: %r" % (w.runs,)


def test_an_unreadable_own_server_stops_the_robbery_instead_of_letting_it_through():
    """A prohibition that cannot be checked must pause the watcher, not lapse quietly."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    w = _Watcher(rows=[_row(4, 7, server=999)], level_min="1",
                 own_server=0)
    w.tick()
    w.tick()
    assert w.runs == [], "robbed while the own server was unknown: %r" % (w.runs,)
    assert sum("свой сервер не прочитан" in m for m in w.logs) == 1, w.logs


def _ok_outcome():
    """The `Outcome` a played scenario returns when it went fine."""
    from panel.runtime.actions import Outcome
    return Outcome(True, "")


def test_the_rule_travels_to_the_listener_and_the_targets_to_the_recipe():
    """Two paths, two different things to be told (#1256, #1272).

    The listener chooses for itself — it fires at a tile nothing has listed yet — so it
    is handed the RULE, and it is still a child because it is a sniffer racing a person.
    The robbery chooses nothing at all, so it is handed the TARGETS: anything that
    re-derived them would be a second opinion about a map the list has already made its
    mind up about.

    What changed in #1272 is only WHO is handed them. There is no robbery child any more
    — it cost five seconds, which is the whole race — so the targets travel as the
    recipe's own `queue` argument. The rule that matters here is unchanged: what goes
    with them is WHAT, never HOW.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    w = _Watcher(rows=[_row(3, 7, server=999)], level_min="6", own_server=534)
    spawned: list = []
    w.rt.children.spawn_raw = lambda cmd, tag: spawned.append(cmd)

    w.start_push()                                  # the event-driven listener
    assert len(spawned) == 1, spawned
    listener = spawned[0]
    assert "--level-min" in listener and "6" in listener, listener
    assert "--level-max" not in listener, "the listener still carries a top bound"
    assert "--skip-own-server" in listener, listener

    # …and the poll's own robbery, which spawns nothing at all now.
    played: list = []
    w.rt.actions = types.SimpleNamespace(
        play=lambda name, args=None, **kw: (played.append((name, dict(args or {}))),
                                            _ok_outcome())[1])
    del w.run
    w.run([(3, 999, "#999")])
    for _ in range(400):
        if w._proc is None:
            break
        time.sleep(0.01)
    assert len(spawned) == 1, ("a robbery spawned a child again", spawned)
    assert played == [("steal_secret_task", {"queue": "{uuid=3,server=999}"})], played

    # The listener ALWAYS carries the prohibition now (#1188) — with no minimum typed
    # and no box to read, it is still the one flag that travels unasked.
    bare = _Watcher(rows=[_row(3, 7)], level_min="")
    quiet: list = []
    bare.rt.children.spawn_raw = lambda cmd, tag: quiet.append(cmd)
    bare.start_push()
    assert quiet and "--skip-own-server" in quiet[0], quiet
    assert "--level-min" not in quiet[0], quiet
    assert "--level-min" not in quiet[0], "an empty box became a bound"


def test_the_watcher_says_what_it_is_doing_even_when_it_does_nothing():
    """Every silent end to a tick names itself on screen (#1227).

    «Автолут не работает совершенно» was four different states wearing one face: no
    list, an unreadable own server, a spent budget, and the ordinary "there is no star
    of that level on the map right now". None of them said anything after the first
    line, so from the operator's chair they were indistinguishable from a watcher that
    had never started.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    from panel.tabs.secret_tasks import autoloot as al

    w = _Watcher()
    assert w.state()[0] == al.STATE_OFF, w.state()

    w.tick()                                       # an empty list
    assert w.state()[0] == al.STATE_NO_SOURCE, w.state()

    w.tab.rows = {"1": _row(1, 7, starred=False)}
    w.tick()                                       # rows, but nothing starred
    assert w.state()[0] == al.STATE_WATCHING, w.state()

    w.tab.rows["3"] = _row(3, 7)
    w.tick()                                       # a star at the minimum
    assert w.state() == (al.STATE_TARGETS, "1"), w.state()

    w._proc = object()                             # …a robbery in flight
    w.tick()
    assert w.state()[0] == al.STATE_ROBBING, w.state()
    w._proc = None

    w._pause_until = time.time() + 600             # …the day's five are spent
    w.tick()
    key, until = w.state()
    assert key == al.STATE_PAUSED and ":" in until, w.state()
    w._pause_until = 0.0

    # …and the own-server prohibition with nothing to compare against.
    blocked = _Watcher(rows=[_row(3, 7)], own_server=0)
    blocked.tick()
    assert blocked.state()[0] == al.STATE_NO_OWN, blocked.state()

    # Every one of them is a real key in the shipped locales, and reads as a sentence.
    assert w.state_text(), "the state came out as an empty line"


def test_a_client_that_is_not_logged_in_is_said_out_loud_not_robbed_through():
    """The second profile's whole failure, in one tick (#1227).

    A client at the login screen answers every question and every answer is a
    plausible-looking lie. The list may still be full of rows restored from the last
    session, so a watcher choosing out of it would happily fire at all of them — the
    clock is the one thing the login screen cannot fake, and it is asked at the moment
    it decides something.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    from panel.tabs.secret_tasks import autoloot as al

    w = _Watcher(rows=[_row(3, 7)], level_min="1", logged_in=False)
    w.tick()
    w.tick()
    assert w.runs == [], "robbed on the word of a client that is not logged in"
    assert w.state()[0] == al.STATE_NO_LOGIN, w.state()
    assert sum("не залогинен" in m for m in w.logs) == 1, w.logs
    assert w._seen == set(), "a target was booked while the client was not in a session"

    # It logs in: the same list is robbed on the very next look.
    w.session_ready = lambda: True
    w.tick()
    assert w.runs == [[3]], w.runs


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
