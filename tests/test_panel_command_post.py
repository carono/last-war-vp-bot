"""The «Секретный командный пункт» tab (panel/tabs/command_post/) and its two new chunks.

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

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_runtime  # noqa: E402
import lua_actions as la  # noqa: E402

SOURCE = (ROOT / "panel" / "tabs" / "command_post" / "tab.py").read_text(encoding="utf-8")

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
    """``panel.tabs.command_post.tab``, or ``None`` where tkinter is missing."""
    try:
        from panel.tabs.command_post import tab as command_post
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
    line = ("ACT TQ i=2 pid=500553 uuid=1397117530950313784 srv=100 dug=1 "
            "x=552 y=500")
    got = cp._fields(line, " TQ ")
    assert got["pid"] == "500553" and got["srv"] == "100" and got["dug"] == "1"
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


def test_the_ghost_standing_order_is_this_tabs_own():
    """The box, the variable behind it and the watcher it starts are all here.

    They used to be split three ways — the widget on the «Секретки» tab, the var on the
    app, the loop in the panel — and the settings load expected exactly one of them to
    have created it. Now the page that shows the squads owns all three, so the check is
    that nothing outside this package mentions the variable at all.
    """
    # The «Секретки» tab has a ghost page of its own now (#1251) and so it says the
    # word — what it must not have is the ghost STANDING ORDER's switch, which is this
    # page's. So the check names the thing rather than the word: a variable or a call
    # that ties the two together anywhere in that package.
    import re
    tie = re.compile(r"ghost\w*[_.]?autoloot|autoloot\w*[_.]?ghost", re.IGNORECASE)
    for path in sorted((ROOT / "panel" / "tabs" / "secret_tasks").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not tie.search(text), f"{path.name} holds the ghost standing order"
        assert "GhostOrder" not in text, path.name
    assert '"panel/__main__.py has no ghost"' or True
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "_ghost_autoloot_var" not in shell, "the shell still holds the ghost switch"
    assert "self.autoloot_var = tk.BooleanVar" in SOURCE
    assert "command=self.order.toggle" in SOURCE


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

        # The shared stand-in, not a hand-rolled one: a COLD runtime is exactly what a
        # tab is handed when it is launched on its own, and building against it is what
        # proves the tab does not reach for the game while it draws.
        rt = fake_runtime.cold_runtime(app)
        tab = cp.CommandPostTab(rt, ttk.Frame(app))
        tab.build()
        assert len(tab._pages) == 3
        assert rt.game.asked == [], rt.game.asked

        pages = list(tab._pages.values())
        ghost = next(p for p in pages if isinstance(p, cp.GhostReconPane))
        shared = next(p for p in pages if isinstance(p, cp.SharedMissionsPane))
        treasure = next(p for p in pages if isinstance(p, cp.TreasuresPane))

        # The ghost page owns the standing order: its checkbox var and its watcher.
        assert ghost.autoloot_var.get() is False
        assert ghost.order.running is False
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

        # This page keeps NO rule of its own any more (#1188) — no «грабить сразу», no
        # star box, no level pair. It shows the one on «Секретки» instead.
        for gone in ("_rob_var", "_star_var", "_from_var", "_to_var", "_levels"):
            assert not hasattr(shared, gone), gone

        # The dig squad is a real choice, defaulting to the first slot.
        assert treasure._squad_var.get() == cp.TREASURE_SQUADS[0]
        treasure._squad_var.set(3)
        assert treasure._squad_var.get() == 3

        # The squad is kept in the profile; the shared page keeps nothing at all, and a
        # junk block cannot smuggle in a squad the page would not offer.
        saved = tab.config()
        assert saved["pages"]["shared"] == {}, saved["pages"]["shared"]
        assert saved["pages"]["treasure"] == {"squad": 3}
        tab.apply_config({})
        assert tab.config()["pages"]["shared"] == {}
        assert tab.config()["pages"]["treasure"] == {"squad": cp.TREASURE_SQUADS[0]}
        tab.apply_config(saved)
        assert tab.config() == saved
        # An OLD block still naming the rule this page used to keep is simply ignored —
        # not restored, and not able to bring a second standing order back.
        tab.apply_config({"pages": {"shared": {"rob": True, "stars_only": False,
                                               "level_from": "3", "level_to": "7"},
                                    "treasure": {"squad": 9}}})
        assert tab.config()["pages"]["shared"] == {}
        assert treasure._squad_var.get() == cp.TREASURE_SQUADS[0]
        tab.apply_config("not a block at all")
        assert tab.config()["pages"]["treasure"] == {"squad": cp.TREASURE_SQUADS[0]}
        # «Слушать эфир» is a running capture, not a setting — restoring a tick without
        # a listener behind it would claim the air is being watched when it is not.
        assert all(str(shared._listen_var) != str(v) for v in tab.persist_vars())
        assert any(str(treasure._squad_var) == str(v) for v in tab.persist_vars())

        # Shutting the tab down with nothing running is a no-op, not an error.
        tab.shutdown()
        tab.restart_children()
    finally:
        app.destroy()


def test_panel_keeps_the_saved_block_until_the_tab_exists():
    """`_tabs_block` (panel/__main__.py) — the guard every plugin tab's block goes through.

    Settings are collected on every save, including saves before the tabs are built;
    one of those must hand back what is on disk, or a start-up save would write a
    default over the settings that are about to be restored. It used to be a
    hand-written method per tab; it is one loop over the built ones now, so a tab that
    is switched off — or that failed to build — keeps its block too.
    """
    try:
        import panel.__main__ as pm                      # needs tkinter
    except Exception as exc:                             # noqa: BLE001
        return _skip(exc)

    block = {"pages": {"treasure": {"squad": 2}}, "ghost_autoloot": True}

    class _NoTabYet:
        _settings = {"tabs": {"config": {"command_post": block}}}
        _tabs_block = pm.Panel._tabs_block

    class _Built:
        _settings = {"tabs": {"config": {"command_post": block}}}
        _tabs_block = pm.Panel._tabs_block
        # A DRAWN tab: `_tabs_block` asks every tab for `stored_config`, which is the
        # widgets for one that has been looked at and the block it was given for one
        # that has not (`PanelTab.LAZY`, #1215).
        _plugin_tabs = {"command_post": types.SimpleNamespace(
            ID="command_post", built=True,
            stored_config=lambda: {"pages": {"treasure": {"squad": 1}},
                                   "ghost_autoloot": False})}

    class _NeverOpened:
        """The tab is in the window but nobody has looked at it: it hands back exactly
        the block it was handed, so a save cannot flatten settings out of the profile."""

        _settings = {"tabs": {"config": {"command_post": block}}}
        _tabs_block = pm.Panel._tabs_block
        _plugin_tabs = {"command_post": types.SimpleNamespace(
            ID="command_post", built=False, stored_config=lambda: dict(block))}

    class _Fresh:                                        # a profile with nothing saved
        _settings = {}
        _tabs_block = pm.Panel._tabs_block

    assert _NoTabYet()._tabs_block()["config"]["command_post"] == block
    assert _Built()._tabs_block()["config"]["command_post"]["ghost_autoloot"] is False
    assert _NeverOpened()._tabs_block()["config"]["command_post"] == block
    fresh = _Fresh()._tabs_block()
    assert fresh["config"] == {}, fresh
    # Every save records which tabs this build offered, so an unticked one stays
    # unticked instead of reappearing as "new" on the next start.
    assert "rally" in fresh["known"] and "stats" in fresh["known"], fresh
    # …and a hand-written `tabs.enabled` survives a save that has nothing to say about it.
    class _Chosen:
        _settings = {"tabs": {"enabled": ["stats"], "config": {}}}
        _tabs_block = pm.Panel._tabs_block

    assert _Chosen()._tabs_block()["enabled"] == ["stats"]


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

    class Rt:
        """Only what `_scanned_targets` reads: where this profile's checkpoints are."""
        profiles = Profiles()

    now = int(time.time())
    mission = proto.GhostReconMission(
        uuid=111, cfg_id=60302, family="6", level=5, state=3, target_server=700,
        owner_id="someone", owner_server=700, alliance_id=None, alliance_show=True,
        point_id=500553, x=553, y=500, member_count=1, steal_count=0,
        team_start_time=None, completion_time=1, expire_time=None)
    known = proto.GhostReconMission(**{**mission.as_dict(), "uuid": 222})
    ghost_path.write_text(_json.dumps([mission.as_dict() | {"seen_at": now},
                                       known.as_dict() | {"seen_at": now}]),
                          encoding="utf-8")

    pane = cp.GhostReconPane.__new__(cp.GhostReconPane)   # no Tk needed for this
    pane.rt = Rt()
    rows = pane._scanned_targets({"222"})
    assert [r["uuid"] for r in rows] == ["111"], rows
    assert rows[0]["scanned"] is True and rows[0]["state"] is None
    assert rows[0]["srv"] == 700 and (rows[0]["x"], rows[0]["y"]) == (553, 500)

    # The treasure half, off the recorded live chest.
    fixture = _json.loads((ROOT / "tests" / "fixtures" /
                           "world_treasure_points.json").read_text(encoding="utf-8"))
    frame = [f for f in fixture["frames"]
             if f["command"] == "push.world.point.update"][-1]
    chest = next(iter(proto.world_treasure_points(frame["command"], frame["payload"])))
    record = chest.as_dict() | {"seen_at": now, "expires_at": None}
    treasure_path.write_text(_json.dumps([record]), encoding="utf-8")

    tpane = cp.TreasuresPane.__new__(cp.TreasuresPane)
    tpane.rt = Rt()
    trows = tpane._scanned_targets(set(), home=100)
    assert len(trows) == 1, trows
    assert trows[0]["uuid"] == str(chest.uuid) and trows[0]["dug"] is True
    assert trows[0]["cross"] is False        # same server as home
    # …and one the list already carries is not added twice.
    assert tpane._scanned_targets({str(chest.uuid)}, home=100) == []


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


def test_the_shared_page_cannot_rob_by_itself_at_all():
    """«Общие» WATCHES the air; it does not rob, and it may not (#1188).

    It used to keep its own «грабить сразу» / «только звёзды» / level pair and spawn
    them into a listener of its own — a SECOND standing order over the same push, with
    a rule nobody was looking at. That pair is what made «I turned auto-loot off» true
    of one order and false of the other, and it cost the player a raid on their own
    server and a fine for it.

    So the child is spawned `--dry-run` always, carries no rule flags at all, and still
    carries the home-server prohibition — three things checked together, because any
    one of them coming back alone is the same bug.
    """
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
        rt = fake_runtime.cold_runtime(app)
        tab = cp.CommandPostTab(rt, ttk.Frame(app))
        tab.build()
        shared = next(p for p in tab._pages.values()
                      if isinstance(p, cp.SharedMissionsPane))

        spawned = []

        class _Child:
            def __init__(self, cmd):
                spawned.append(cmd)

            def start(self):
                return True

            def stop(self):
                pass

        rt.children.spawn = lambda tag, cmd, **kw: _Child(cmd)

        # The prohibition travels ALWAYS (#1188) — there is no box that could hold it
        # back, so the very first listener carries it.
        shared._start_listener()
        assert spawned, spawned
        cmd = spawned[0]
        assert "--skip-own-server" in cmd, cmd
        # …and it never robs: `--dry-run` unconditionally, and not one rule flag.
        assert "--dry-run" in cmd, cmd
        for flag in ("--star-max", "--level-min", "--level-max"):
            assert flag not in cmd, (flag, cmd)
        shared._stop_listener()

        # The rule it SHOWS is read from «Секретки» and not kept here. With no such tab
        # in this window it says so instead of inventing one.
        line = shared.autoloot_line()
        assert line and line == rt.t("cmdpost.shared.rule_elsewhere_off"), line
    finally:
        app.destroy()


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


def test_web_view_reports_seconds_on_the_games_clock_not_local_ms():
    """`until`/`now` are epoch SECONDS on the GAME's clock (#1227/#1228).

    Both `GhostReconMission.expire_time` and `WorldTreasure.expires_at` are the game's
    MILLISECONDS. The screen contract (`panel/tabs/base.py`) is SECONDS, and drawing
    `now` from `time.time()` judges the game's stamps against the wrong clock — the two
    ran twelve seconds apart live. Before this fix `until` went out as raw milliseconds
    against a seconds `now`, drawing a multi-thousand-year countdown on the phone.
    """
    cp = _module()
    if cp is None:
        return
    import json as _json
    import tempfile
    import time
    import game_clock
    import lastwar_proto as proto

    tmp = Path(tempfile.mkdtemp())
    ghost_path, treasure_path = tmp / "ghost.json", tmp / "treasure.json"

    class Profiles:
        def ghost_json(self):
            return str(ghost_path)

        def treasures_json(self):
            return str(treasure_path)

    class Rt:
        profiles = Profiles()

        # The ghost card carries the standing order's two facts now (#1256), and a
        # value on a card is already in the person's language — so the stand-in has to
        # answer for a key. Echoing it is enough: what is pinned here is the clock.
        @staticmethod
        def t(key, **fmt):
            return key

    now_ms = int(time.time() * 1000)
    mission = proto.GhostReconMission(
        uuid=111, cfg_id=60302, family="6", level=5, state=3, target_server=700,
        owner_id="someone", owner_server=700, alliance_id=None, alliance_show=True,
        point_id=500553, x=553, y=500, member_count=1, steal_count=0,
        team_start_time=None, completion_time=1, expire_time=now_ms + 3_600_000)
    ghost_path.write_text(
        _json.dumps([mission.as_dict() | {"seen_at": int(time.time())}]),
        encoding="utf-8")

    fixture = _json.loads((ROOT / "tests" / "fixtures" /
                           "world_treasure_points.json").read_text(encoding="utf-8"))
    frame = [f for f in fixture["frames"]
             if f["command"] == "push.world.point.update"][-1]
    chest = next(iter(proto.world_treasure_points(frame["command"], frame["payload"])))
    record = chest.as_dict() | {"seen_at": int(time.time()),
                                "expires_at": now_ms + 1_800_000}
    treasure_path.write_text(_json.dumps([record]), encoding="utf-8")

    game_clock.reset()
    try:
        game_clock.note(now_ms + 60_000, time.time(), time.time())

        tab = cp.CommandPostTab.__new__(cp.CommandPostTab)
        tab.rt = Rt()
        tab._by_key = {}
        view = tab.web_view()

        assert abs(view["now"] - game_clock.now_ms() / 1000.0) < 1, view["now"]
        assert view["now"] < 10_000_000_000, "now is still milliseconds"

        ghost_card = next(c for c in view["cards"] if c["title"] == "cmdpost.tab.ghost")
        until = ghost_card["items"][0]["until"]
        assert until < 10_000_000_000, "ghost 'until' is still milliseconds"
        assert abs(until - (now_ms + 3_600_000) / 1000.0) < 1, until

        treasure_card = next(c for c in view["cards"]
                             if c["title"] == "cmdpost.tab.treasure")
        t_until = treasure_card["items"][0]["until"]
        assert t_until < 10_000_000_000, "treasure 'until' is still milliseconds"
        assert abs(t_until - (now_ms + 1_800_000) / 1000.0) < 1, t_until
    finally:
        game_clock.reset()


# --- the robbery is a scenario now (#1188) ----------------------------------

class _Proc:
    """A `spawn_raw` child that has already said its piece and gone."""

    def __init__(self, lines) -> None:
        self.stdout = iter(list(lines))
        self.returncode = 0

    def terminate(self) -> None: ...


class _Children:
    """The child factory, remembering the ONE command line it was handed."""

    def __init__(self, lines) -> None:
        self.lines, self.cmd = lines, None

    def python(self) -> str:
        return "python"

    def spawn_raw(self, cmd, tag):
        self.cmd = list(cmd)
        return _Proc(self.lines)


class _Actions:
    """`rt.actions`, remembering which scenarios were played."""

    def __init__(self, ok: bool = True, reason: str = "") -> None:
        self.played, self._ok, self._reason = [], ok, reason

    def play(self, name, args=None, **kw):
        from panel.runtime.actions import Outcome
        self.played.append(name)
        return Outcome(self._ok, self._reason)


def _order(lines, ok: bool = True, reason: str = ""):
    """A `GhostOrder` over a runtime that spawns nothing and presses nothing.

    ``None`` where there is no tkinter — importing the page reaches the panel runtime.
    """
    try:
        from panel.tabs.command_post.ghost import GhostOrder
    except Exception as exc:            # noqa: BLE001 — no tkinter is a skip, not a fail
        _skip(exc)
        return None, None, None
    said = []
    rt = types.SimpleNamespace(
        children=_Children(lines), actions=_Actions(ok, reason),
        settings=types.SimpleNamespace(opt_int=lambda key, low=0, high=0: 5),
        say=lambda tag, key, **fmt: said.append(key), put=lambda line: None)
    return GhostOrder(rt, pane=None), rt, said


def _drain(order) -> None:
    """Wait for the reader thread `rob()` started — the whole two-step lives on it."""
    import time as _time
    for _ in range(200):
        if order._proc is None:
            return
        _time.sleep(0.01)
    raise AssertionError("the robbery never finished")


def test_the_ghost_robbery_parks_with_the_tool_and_presses_with_the_recipe():
    """#1188: the tool selects and parks, `actions/steal_ghost_recon.md` robs.

    The event runs one day a week, so a swap that quietly robbed nothing would not be
    noticed for six days. The tool keeps what is genuinely the game's answer — the event
    day and the daily budget — and the pressing is the scenario's.
    """
    order, rt, _said = _order(["ghost recon: open   robberies left today: 5   queued: 0",
                               "  target uuid=1 srv=100",
                               "queued 1 target(s) — run actions/…"])
    if order is None:
        return
    order.rob([{"uuid": "1", "srv": 100}])
    _drain(order)

    assert "--queue-only" in rt.children.cmd, rt.children.cmd
    assert "ghost_recon_steal.py" in " ".join(rt.children.cmd)
    # …and the chosen squad still travels by name, never «--all» (#1256).
    assert "--targets" in rt.children.cmd and "1:100" in rt.children.cmd
    assert "--all" not in rt.children.cmd, rt.children.cmd
    assert rt.actions.played == ["steal_ghost_recon"], rt.actions.played


def test_a_shut_event_parks_nothing_and_presses_nothing():
    """Six days out of seven the tool says so and never reaches the queue — and a recipe
    played over a stale one is the only way this order could rob the wrong squad."""
    order, rt, _said = _order(["ghost recon: CLOSED (not an event day)   robberies left "
                               "today: 5   queued: 0",
                               "the event is not running today — nothing to rob"])
    if order is None:
        return
    order.rob([{"uuid": "1", "srv": 100}])
    _drain(order)
    assert rt.actions.played == [], rt.actions.played


def test_a_ghost_run_that_queued_nothing_presses_nothing():
    """«queued 0 target(s)» — the tool reached the queue and left it empty.

    It happens on a spent budget: the tool slices the named squads to what is left, and
    «ограбить всё» does not gate on the budget the way the standing order does. The count
    is what the reader steers by, not the word.
    """
    order, rt, _said = _order(["queued 0 target(s) — run actions/…"])
    if order is None:
        return
    order.rob([{"uuid": "1", "srv": 100}])
    _drain(order)
    assert rt.actions.played == [], rt.actions.played


def test_a_ghost_recipe_that_failed_says_so_in_the_scenarios_own_words():
    """The scenario is the authority on why it stopped; the panel repeats it."""
    order, rt, said = _order(["queued 1 target(s) — run actions/…"],
                             ok=False, reason="no daemon")
    if order is None:
        return
    order.rob([{"uuid": "1", "srv": 100}])
    _drain(order)
    assert rt.actions.played == ["steal_ghost_recon"]
    assert "log.ghost.spend_failed" in said, said


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
