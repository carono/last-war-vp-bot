"""The «Секретный командный пункт» tab (panel/command_post.py) and its two new chunks.

Three halves, in the order they can be checked without a game:

* the **wire parsing** — one line of ``tools/secret_share_autoloot.py`` output becomes one
  shared-mission row. That decode is the only place this tab reads something it did not
  ask for, so it is pinned against the exact strings the tool prints (a match, a mission
  left alone, a robbery), including the ``lvl ?`` an unsplittable cfgId produces;
* the **Lua chunks** the treasure page added to ``tools/lib/lua_actions.py`` — the queue
  dump and the shared dig squad. They are strings, so what can be checked is that they
  read the queue the recipe layer writes and never write it back;
* the **locale keys**: every key the tab asks for must exist in both locale files, or a
  button ships with its own key printed on it.

The tab widget itself needs Tk, so it is built on a tkinter root and only checked to
construct and drive its controls without raising; it skips where there is no display.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import lua_actions as la  # noqa: E402

SOURCE = (ROOT / "panel" / "command_post.py").read_text(encoding="utf-8")

# The three lines tools/secret_share_autoloot.py prints about a mission, verbatim in
# shape (the ANSI colours it wraps them in are stripped before the parse).
LINE_MATCH = "12:00:00 SHARE MATCH  * lvl 7  #946  cfg 60000701  uuid 1394584906709054020"
LINE_SKIP = ("12:00:00 share:   lvl 5  #946  cfg 40000501  uuid 1394584906709054021 "
             "— outside the rule, left alone")
LINE_ROBBED = ("12:00:00 robbed * lvl 7  #946  cfg 60000701  uuid 1394584906709054020  "
               "(budget 5 -> 4)")
LINE_UNKNOWN = "12:00:00 share:   lvl ?  #946  cfg 5000302  uuid 1394584906709054022"


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else "  SKIP no tkinter")


def _module():
    """``panel.command_post``, or ``None`` where tkinter is missing."""
    try:
        from panel import command_post
    except Exception as exc:            # noqa: BLE001 — no tkinter is a skip, not a fail
        _skip(exc)
        return None
    return command_post


# --- the wire: a listener line becomes a row --------------------------------

def test_share_line_reads_a_match():
    cp = _module()
    if cp is None:
        return
    got = cp.SHARE_LINE.search(LINE_MATCH).groupdict()
    assert got == {"lvl": "7", "srv": "946", "cfg": "60000701",
                   "uuid": "1394584906709054020"}, got


def test_share_line_reads_the_other_two_verdicts():
    """A mission left alone and a robbed one carry the same label — only the prefix differs."""
    cp = _module()
    if cp is None:
        return
    skipped = cp.SHARE_LINE.search(LINE_SKIP)
    robbed = cp.SHARE_LINE.search(LINE_ROBBED)
    assert skipped is not None and robbed is not None
    assert skipped.group("uuid") == "1394584906709054021"
    assert robbed.group("uuid") == "1394584906709054020"
    # A cfgId that did not split prints «lvl ?»; it must still yield a row (level 0),
    # never a crash — a share with an unknown level is exactly what wants looking at.
    unknown = cp.SHARE_LINE.search(LINE_UNKNOWN)
    assert unknown is not None and unknown.group("lvl") == "?"
    assert cp._int(unknown.group("lvl"), 0) == 0


def test_a_line_that_names_no_mission_is_not_a_row():
    cp = _module()
    if cp is None:
        return
    for line in ("Shared-secret-task auto-loot — scapy/npcap, no dumpcap",
                 "12:00:00 the day's robberies are spent — listening on",
                 "1 shared mission(s) matched, 0 robbery/robberies sent"):
        assert cp.SHARE_LINE.search(line) is None, line


def test_marker_fields_are_read_off_a_log_line():
    cp = _module()
    if cp is None:
        return
    line = ("ACT TQ i=2 pid=500553 uuid=1397117530950313784 srv=935 dug=1 "
            "x=552 y=500")
    got = cp._fields(line, " TQ ")
    assert got["pid"] == "500553" and got["srv"] == "935" and got["dug"] == "1"
    assert got["x"] == "552" and got["y"] == "500"
    assert cp._fields(line, " NOPE ") == {}


# --- the two new Lua chunks -------------------------------------------------

def test_treasure_queue_dump_reads_the_queue_and_never_writes_it():
    """The dump is a READER: it must not assign the queue the finder parks."""
    chunk = la.treasure_queue_dump()
    assert "__lw_treasure_queue" in chunk
    assert "DataCenter.__lw_treasure_queue=" not in chunk
    assert "table.remove" not in chunk          # reading must not spend a target
    # Every field a row needs, including the tile position the pid stands for.
    for field in ("i=", "pid=", "uuid=", "srv=", "dug=", "x=", "y="):
        assert field in chunk, field
    assert "SceneUtils.IndexToTilePos" in chunk


def test_treasure_formation_is_parked_as_a_bare_number():
    """A formation uuid is a 19-digit number — it goes in as a Lua literal, not a string."""
    chunk = la.treasure_formation_set(1397117530950313784)
    assert "DataCenter.__lw_treasure_formation=1397117530950313784" in chunk
    assert '"1397117530950313784"' not in chunk
    # Anything that is not a number is refused rather than injected into the chunk.
    for bad in ("'; os.exit()", "nil", ""):
        try:
            la.treasure_formation_set(bad)
        except (TypeError, ValueError):
            continue
        raise AssertionError(f"accepted {bad!r}")


# --- the locale contract ----------------------------------------------------

def _keys_used() -> set:
    """Every locale key the tab asks for — the literals, plus the three built by hand."""
    keys = set(re.findall(r'"((?:cmdpost|tabx|ghost)\.[a-z_.]+)"', SOURCE))
    keys |= {"cmdpost.tab." + page for page in ("ghost", "shared", "treasure")}
    # The label on the outer tab is added by the panel, not by this module.
    keys.add("tab.command_post")
    # `"cmdpost.tab." + key` and the like are prefixes, not keys.
    return {k for k in keys if not k.endswith(".")}


def test_every_key_exists_in_both_locales():
    used = _keys_used()
    assert "cmdpost.ghost.title" in used and "tab.command_post" in used, used
    for lang in ("en", "ru"):
        table = json.loads((ROOT / "panel" / "locales" / f"{lang}.json")
                           .read_text(encoding="utf-8"))
        missing = sorted(k for k in used if k not in table)
        assert not missing, f"{lang}.json misses {missing}"


def test_the_two_locales_carry_the_same_command_post_keys():
    tables = {}
    for lang in ("en", "ru"):
        table = json.loads((ROOT / "panel" / "locales" / f"{lang}.json")
                           .read_text(encoding="utf-8"))
        tables[lang] = {k for k in table if k.startswith("cmdpost.")}
    assert tables["en"] == tables["ru"], tables["en"] ^ tables["ru"]


def test_the_ghost_checkbox_moved_off_the_secret_tasks_tab():
    """Its widget lives here now; its var and its method still live on the app.

    The move is the point: `_ghost_autoloot_var` is created by whichever tab draws the
    box, and the settings load expects exactly one of them to have done it.
    """
    secret = (ROOT / "panel" / "secret_tasks.py").read_text(encoding="utf-8")
    assert "_ghost_autoloot_var" not in secret
    assert "app._ghost_autoloot_var = tk.BooleanVar" in SOURCE
    assert "app._toggle_ghost_autoloot" in SOURCE


# --- the widget (needs Tk) --------------------------------------------------

def test_tab_builds_and_drives_its_controls():
    cp = _module()
    if cp is None:
        return
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:            # noqa: BLE001
        return _skip(exc)
    try:
        app = tk.Tk()
    except Exception as exc:            # noqa: BLE001 — headless box
        return _skip(exc)
    try:
        app.withdraw()

        class FakeApp:
            """The handful of panel methods the tab touches while it is being built."""

            def __init__(self, root):
                # NOT `_root`: tkinter calls `master._root()` on a var's master, and an
                # attribute of that name would shadow the Tk method it needs.
                self._tk = root
                self._tr_hooks = []
                self.logged = []

            def _t(self, key, **fmt):
                return key

            def _tr(self, widget, key, option="text", **fmt):
                widget.configure(**{option: key})
                return widget

            def _say(self, tag, key, **fmt):
                self.logged.append((tag, key))

            def _toggle_ghost_autoloot(self):
                pass

            def _autoloot_limit(self):
                return 5

            def _python(self):
                return sys.executable

            def _daemon_port(self):
                return 47654

            def after(self, ms, func=None, *a):
                return self._tk.after(ms, func, *a) if func else None

            def __getattr__(self, name):
                return getattr(self.__dict__["_tk"], name)

        fake = FakeApp(app)
        frame = ttk.Frame(app)
        tab = cp.CommandPostTab(fake, frame)
        assert len(tab._pages) == 3

        pages = list(tab._pages.values())
        ghost = next(p for p in pages if isinstance(p, cp.GhostReconPane))
        shared = next(p for p in pages if isinstance(p, cp.SharedMissionsPane))
        treasure = next(p for p in pages if isinstance(p, cp.TreasuresPane))

        # The ghost page owns the standing-order checkbox's var, on the app.
        assert hasattr(fake, "_ghost_autoloot_var")
        assert ghost.LOG_TAG == "ghost"

        # Building the tab must not read the game: Tk selects the first inner page by
        # itself, and a panel nobody opened this tab on would otherwise poll the client
        # at start-up. Only the panel actually showing the tab arms the page loads.
        assert tab._shown is False
        tab._on_page_changed()
        assert not any(p._loaded for p in pages)

        # A decoded line lands as a row, and a repeat of it does not double the list.
        shared._on_line(LINE_MATCH)
        shared._add({"uuid": "1394584906709054020", "server": 946, "cfg": "60000701",
                     "level": 7, "star": True, "matched": True, "robbed": True})
        assert len(shared._rows) == 1
        assert shared._rows["1394584906709054020"]["robbed"] is True
        shared._clear()
        assert not shared._rows

        # The level range reads as a pair, blank ends meaning "no bound".
        assert shared._levels() == (None, None)
        shared._from_var.set("3")
        shared._to_var.set("7")
        assert shared._levels() == (3, 7)

        # The dig squad is a real choice, defaulting to the first slot.
        assert treasure._squad_var.get() == cp.TREASURE_SQUADS[0]
        treasure._squad_var.set(3)
        assert treasure._squad_var.get() == 3

        # Shutting the tab down with nothing running is a no-op, not an error.
        tab.shutdown()
        tab.restart_children()
    finally:
        app.destroy()


def test_a_scanned_row_is_never_labelled_with_a_verdict_the_game_did_not_give():
    """The state column: the client's own verdict, or the clock — never mixed.

    A tile off the map has no `GhostreconPointStealType` (the gate only answers for
    squads in the client's list) and its own `f9` is a different enum that reads 3
    whether the squad is back or not. Borrowing either would print a confident word
    the game never said.
    """
    cp = _module()
    if cp is None:
        return
    key = cp.GhostReconPane._state_key
    assert key({"state": 2}) == "cmdpost.ghost.state.can"
    assert key({"state": 1}) == "cmdpost.ghost.state.preview"
    assert key({"state": None}) == "cmdpost.ghost.state.not_shown"
    assert key({"scanned": True, "can": True}) == "cmdpost.ghost.state.map_ready"
    assert key({"scanned": True, "can": False}) == "cmdpost.ghost.state.map_running"
    # A scanned row keeps its own label even when a stale `state` rides along.
    assert key({"scanned": True, "can": True, "state": 4}) == \
        "cmdpost.ghost.state.map_ready"


def test_the_scan_checkpoints_feed_the_two_lists():
    """A scan's checkpoint becomes rows, minus what the client already knows."""
    cp = _module()
    if cp is None:
        return
    import json as _json
    import tempfile
    import time
    import lastwar_proto as proto

    tmp = Path(tempfile.mkdtemp())
    ghost_path, treasure_path = tmp / "ghost.json", tmp / "treasure.json"

    class Profiles:
        def ghost_json(self):
            return str(ghost_path)

        def treasures_json(self):
            return str(treasure_path)

    class App:
        _profiles = Profiles()

    now = int(time.time())
    mission = proto.GhostReconMission(
        uuid=111, cfg_id=60302, family="6", level=5, state=3, target_server=1006,
        owner_id="someone", owner_server=1006, alliance_id=None, alliance_show=True,
        point_id=500553, x=553, y=500, member_count=1, steal_count=0,
        team_start_time=None, completion_time=1, expire_time=None)
    known = proto.GhostReconMission(**{**mission.as_dict(), "uuid": 222})
    ghost_path.write_text(_json.dumps([mission.as_dict() | {"seen_at": now},
                                       known.as_dict() | {"seen_at": now}]),
                          encoding="utf-8")

    pane = cp.GhostReconPane.__new__(cp.GhostReconPane)   # no Tk needed for this
    pane.app = App()
    rows = pane._scanned_targets({"222"})
    assert [r["uuid"] for r in rows] == ["111"], rows
    assert rows[0]["scanned"] is True and rows[0]["state"] is None
    assert rows[0]["srv"] == 1006 and (rows[0]["x"], rows[0]["y"]) == (553, 500)

    # The treasure half, off the recorded live chest.
    fixture = _json.loads((ROOT / "tests" / "fixtures" /
                           "world_treasure_points.json").read_text(encoding="utf-8"))
    frame = [f for f in fixture["frames"]
             if f["command"] == "push.world.point.update"][-1]
    chest = next(iter(proto.world_treasure_points(frame["command"], frame["payload"])))
    record = chest.as_dict() | {"seen_at": now, "expires_at": None}
    treasure_path.write_text(_json.dumps([record]), encoding="utf-8")

    tpane = cp.TreasuresPane.__new__(cp.TreasuresPane)
    tpane.app = App()
    trows = tpane._scanned_targets(set(), home=935)
    assert len(trows) == 1, trows
    assert trows[0]["uuid"] == str(chest.uuid) and trows[0]["dug"] is True
    assert trows[0]["cross"] is False        # same server as home
    # …and one the list already carries is not added twice.
    assert tpane._scanned_targets({str(chest.uuid)}, home=935) == []


def test_a_missing_checkpoint_is_no_rows_not_a_crash():
    cp = _module()
    if cp is None:
        return

    class Profiles:
        def ghost_json(self):
            return "/nonexistent/ghost.json"

        def treasures_json(self):
            return "/nonexistent/treasure.json"

    class App:
        _profiles = Profiles()

    pane = cp.GhostReconPane.__new__(cp.GhostReconPane)
    pane.app = App()
    assert pane._scanned_targets(set()) == []
    tpane = cp.TreasuresPane.__new__(cp.TreasuresPane)
    tpane.app = App()
    assert tpane._scanned_targets(set(), home=0) == []


def test_the_scan_children_are_the_two_map_scanners():
    cp = _module()
    if cp is None:
        return
    assert cp.GHOST_SCAN_SCRIPT.endswith("secret_mission_capture.py")
    assert cp.TREASURE_SCAN_SCRIPT.endswith("treasure_capture.py")
    for script in (cp.GHOST_SCAN_SCRIPT, cp.TREASURE_SCAN_SCRIPT):
        assert (ROOT / "tools" / script).exists(), script
    # A scan is a window, not a standing capture — a button that never ends is a leak.
    assert 30 <= cp.SCAN_SECONDS <= 900


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
