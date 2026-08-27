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
    # …AND IT MOVED AGAIN (#2010), for the same kind of reason it was gathered up in the
    # first place: this tab is dev-only and the live profile had it switched OFF, so an
    # order that spends five robberies a day did not exist there at all. It is on
    # «Секретки» → «Призрак: карта» now — the page holding the list it chooses out of,
    # which is where «Автолут ★» has been since #1271. So the check is the other way
    # round: nothing of it may be left HERE, and the shell must still not hold it.
    for path in sorted((ROOT / "panel" / "tabs" / "command_post").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "GhostOrder" not in text, path.name
        assert "autoloot_var" not in text, f"{path.name} still holds the ghost switch"
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "_ghost_autoloot_var" not in shell, "the shell still holds the ghost switch"
    ghost = (ROOT / "panel" / "tabs" / "secret_tasks" / "ghost.py").read_text(
        encoding="utf-8")
    # `statevar.boolean` rather than `tk.BooleanVar` since #1976 (P3): the switch is the
    # window's own variable while there is a window and a plain one when there is not.
    assert "self.autoloot_var = statevar.boolean" in ghost
    assert "command=self.order.toggle" in ghost


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
        # FOUR pages since #1903: the player's own tasks joined the three that read
        # somebody else's — the only one of them that spends a currency.
        assert len(tab._pages) == 4, sorted(tab._by_key)
        assert set(tab._by_key) == {"ghost", "shared", "treasure", "tasks"}
        assert rt.game.asked == [], rt.game.asked

        pages = list(tab._pages.values())
        ghost = next(p for p in pages if isinstance(p, cp.GhostReconPane))
        shared = next(p for p in pages if isinstance(p, cp.SharedMissionsPane))
        treasure = next(p for p in pages if isinstance(p, cp.TreasuresPane))

        # The ghost page does NOT own the standing order any more (#2010): it moved to
        # «Секретки» → «Призрак: карта», the page holding the list it spends, because
        # this tab is dev-only and a profile with it switched off had no order at all.
        assert not hasattr(ghost, "autoloot_var") and not hasattr(ghost, "order")
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
    # unticked instead of reappearing as "new" on the next start. WHICH tabs those are
    # is asked of the registry rather than named here: this used to name «stats», #1273
    # marked it `in_development`, and a tab that is not offered must NOT be recorded as
    # offered — recording it would read, the day the mark comes off, as a tab this
    # profile had already said no to.
    from panel import tabs as tabsreg
    assert set(fresh["known"]) == {spec.id for spec in tabsreg.listed()}, fresh
    assert not [i for i in fresh["known"] if tabsreg.BY_ID[i].in_development], fresh
    # …and a tab somebody UNTICKED stays unticked, which is what `enabled` is for.
    #
    # It used to say «a hand-written `tabs.enabled` survives untouched», and #1327 ended
    # that: a tab the profile has never heard of is appended and BUILT, so a save that
    # left `enabled` alone wrote it into `known` and nowhere else — and «in known, not in
    # enabled» is exactly how this file spells «declined». The tab then appeared once and
    # was gone for ever. So `enabled` is rewritten from what the window actually built,
    # and the guarantee to pin is the one that survived: known-and-not-enabled stays off.
    class _Chosen:
        _settings = {"tabs": {"enabled": ["rally"], "known": ["rally", "chat"],
                              "config": {}}}
        _tabs_block = pm.Panel._tabs_block

    chosen = _Chosen()._tabs_block()
    assert "rally" in chosen["enabled"], chosen
    assert "chat" not in chosen["enabled"], "an unticked tab came back on"
    assert "chat" in chosen["known"], chosen


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


def test_the_ghost_page_reads_the_panels_own_kept_list():
    """This page's rows come out of what «Призрак: карта» has KEPT (#2010).

    It used to read the capture's live checkpoint through the freshness window, and that
    file is rewritten every tick out of an index holding only the warzone on screen — a
    lap walks eighteen of them in seconds, so the standing order had nothing to rob while
    the sniffer was decoding thousands of tiles. The kept list is the panel's own, it
    survives a restart, and it is the list the person is looking at.
    """
    cp = _module()
    if cp is None:
        return
    import game_clock

    now = game_clock.now_ms()
    kept = [
        # Back and still running: a target.
        {"uuid": "1000000000000001", "owner_server": 700, "x": 10, "y": 20,
         "cfg_id": 60050101, "level": 5, "loot_max": 3, "loot_count": 1,
         "completed_at": now - 1000, "expires_at": now + 3_600_000},
        # Still out — listed, but not robbable yet.
        {"uuid": "1000000000000002", "owner_server": 700, "cfg_id": 60050101,
         "level": 5, "completed_at": now + 3_600_000, "expires_at": now + 7_200_000},
        # Its own clock ran out: gone, clause 1 of THE_LIST_RULE.
        {"uuid": "1000000000000003", "owner_server": 700, "cfg_id": 60050101,
         "level": 5, "completed_at": now - 5000, "expires_at": now - 1000},
        # Robbed out: the server would only refuse, and one of the five would pay for it.
        {"uuid": "1000000000000004", "owner_server": 700, "cfg_id": 60050101,
         "level": 5, "loot_max": 3, "loot_count": 3,
         "completed_at": now - 5000, "expires_at": now + 3_600_000},
    ]

    class Rt:
        store = types.SimpleNamespace(blob_get=lambda _name: list(kept))
        profiles = types.SimpleNamespace(
            ghost_json=lambda: "/nonexistent/ghost.json")

    pane = cp.GhostReconPane.__new__(cp.GhostReconPane)
    pane.rt = Rt()
    rows = pane._scanned_targets(set())
    assert [r["uuid"] for r in rows] == ["1000000000000001",
                                         "1000000000000002"], rows
    assert rows[0]["can"] is True and rows[1]["can"] is False, rows
    assert rows[0]["srv"] == 700 and rows[0]["level"] == 5, rows[0]
    # …and one the client's own list already carries is not added a second time.
    assert [r["uuid"] for r in pane._scanned_targets({"1000000000000001"})] == \
        ["1000000000000002"]

    # …and the LEVEL the game gave is not overwritten by the cfgId's digits on the way in
    # (`absorb`). The RULE that spends the day's five is not this page's any more — it is
    # «Секретки» → «Призрак: карта»'s since #2010, and it is pinned there.
    pane.status, pane.targets = {}, []
    pane.absorb({"open": True, "left": 5}, rows)
    assert pane.targets[0]["level"] == 5, pane.targets[0]


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
    """`rt.actions`, remembering which scenarios were played AND with what.

    The arguments matter now (#1976): the queue used to be parked by a spawned tool and
    is a `variables` entry of the recipe, so a robbery that presses the right scenario
    over an empty queue is exactly the failure this file has to be able to see.
    """

    def __init__(self, ok: bool = True, reason: str = "") -> None:
        self.played, self.args, self._ok, self._reason = [], [], ok, reason

    def play(self, name, args=None, **kw):
        from panel.runtime.actions import Outcome
        self.played.append(name)
        self.args.append(dict(args or kw.get("variables") or {}))
        return Outcome(self._ok, self._reason)


def _order(lines, ok: bool = True, reason: str = ""):
    """A `GhostOrder` over a runtime that spawns nothing and presses nothing.

    ``None`` where there is no tkinter — importing the page reaches the panel runtime.
    """
    try:
        from panel.tabs.secret_tasks.ghost_order import GhostOrder
    except Exception as exc:            # noqa: BLE001 — no tkinter is a skip, not a fail
        _skip(exc)
        return None, None, None
    said = []
    rt = types.SimpleNamespace(
        children=_Children(lines), actions=_Actions(ok, reason),
        settings=types.SimpleNamespace(opt_int=lambda key, low=0, high=0: 5),
        say=lambda tag, key, **fmt: said.append(key), put=lambda line: None)
    return GhostOrder(rt, page=None), rt, said


def _drain(order) -> None:
    """Wait for the reader thread `rob()` started — the whole two-step lives on it."""
    import time as _time
    for _ in range(200):
        if order._proc is None:
            return
        _time.sleep(0.01)
    raise AssertionError("the robbery never finished")


def test_the_ghost_robbery_travels_as_a_queue_and_spawns_nothing():
    """#1188, then #1976: ONE step — the recipe takes the squads as an argument.

    It used to be two: spawn `tools/ghost_recon_steal.py --queue-only` to park the chosen
    squads in the game VM, then play the recipe to press them. The parking child cost five
    seconds before the first press, in a race that is decided in fractions of one, and all
    it parked was a list this page had already chosen. So the queue is `ARGS queue` now,
    and what this pins is the pair of facts that make the swap correct: NOTHING is spawned,
    and the squads reach the recipe BY NAME rather than being re-derived from a second
    reading of `taskList` (#1256).
    """
    order, rt, _said = _order([])
    if order is None:
        return
    order.rob([{"uuid": "1", "srv": 100}, {"uuid": "2", "srv": 101}])
    _drain(order)

    assert rt.children.cmd is None, f"a child was spawned: {rt.children.cmd}"
    assert rt.actions.played == ["steal_ghost_recon"], rt.actions.played
    queue = rt.actions.args[0].get("queue", "")
    assert queue == "{uuid=1,server=100},{uuid=2,server=101}", queue


def test_a_robbery_with_nothing_chosen_presses_nothing() -> None:
    """An empty pick is the one case that must NOT reach the recipe.

    The recipe's own `xall` re-reads min(queued, robberies left) before every press and
    reads 0 once the event shuts — but a press over a queue somebody else parked is the
    way this order could rob a squad the page never chose, so the empty pick stops here.
    """
    order, rt, _said = _order([])
    if order is None:
        return
    order.rob([])
    assert rt.actions.played == [], rt.actions.played
    assert order._proc is None, "the in-flight flag was left set on an empty pick"


def test_the_queue_is_cut_to_what_the_day_has_left() -> None:
    """Five a day is the game's number, and the order slices its own pick by it.

    The recipe re-reads the budget too — this is the cheaper half of the same gate, and
    the half that keeps the log honest: «граблю N» must not name more squads than the
    day can pay for.
    """
    order, rt, said = _order([])
    if order is None:
        return
    rt.settings.opt_int = lambda key, low=0, high=0: 2
    order.rob([{"uuid": str(n), "srv": 100} for n in range(1, 6)])
    _drain(order)
    queue = rt.actions.args[0].get("queue", "")
    assert queue.count("uuid=") == 2, queue
    assert "ghost.robbing" in said, said


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


def test_a_ghost_row_carries_its_own_press_where_the_game_allows_one():
    """Per-row «Ограбить» on the phone — the last thing this card was missing (#1976).

    It waited on the rows, not on the rule: the card used to be drawn from the map-scan
    FILE, whose records carry no uuid and no verdict, so a row could be shown and never
    pressed. The card is drawn from the PAGE'S OWN LIST when it has one — what a look
    left behind, the client's `taskList` merged with the scan — and those rows carry
    both. The file is still the fallback for a page nobody has looked at.

    The press is offered exactly where the window offers it: the game says the tile may
    be robbed, and it is not our own squad. Never on a row excluded only by «минимальный
    уровень» — that is the standing order's rule for spending the day's five unattended,
    not a ban on a squad somebody chose by hand.
    """
    cp = _module()
    if cp is None:
        return
    import coords

    class Rt:
        @staticmethod
        def t(key, **fmt):
            return key

    tab = cp.CommandPostTab.__new__(cp.CommandPostTab)
    tab.rt = Rt()
    pane = types.SimpleNamespace(
        targets=[{"uuid": "11", "srv": 700, "x": 1, "y": 2, "level": 30, "can": True,
                  "mine": False, "looted": 0, "scanned": True},
                 {"uuid": "12", "srv": 700, "x": 3, "y": 4, "level": 5, "can": True,
                  "mine": True, "looted": 1, "scanned": True},
                 {"uuid": "13", "srv": 700, "x": 5, "y": 6, "level": 9, "can": False,
                  "mine": False, "looted": 0, "scanned": True}],
        level_min=lambda: 20,
        autoloot_var=types.SimpleNamespace(get=lambda: False))
    tab._by_key = {"ghost": pane}

    card = tab._web_ghost(coords, 0.0)
    items = card["items"]
    assert len(items) == 3, items
    pressable = [i for i in items if i.get("actions")]
    assert len(pressable) == 1, pressable
    action = pressable[0]["actions"][0]
    assert action["id"] == "ghost_rob_one", action
    # The window's own row label, not a second word for the same press.
    assert action["label"] == "cmdpost.steal", action
    assert action["args"] == {"uuid": "11", "srv": 700}, action
    # …and the row that is ours says so instead of offering a press the game refuses.
    assert items[1]["pill"] == "cmdpost.ghost.own", items[1]


def test_a_row_press_robs_that_row_and_a_second_one_is_refused():
    """One squad, the same recipe «Ограбить всех» plays — with a queue of one.

    And the in-flight flag covers it exactly as it covers the whole-list press: five a
    day are not refundable, so a second tap while the first is being pressed is answered
    rather than parking another squad on the queue underneath it.
    """
    order, rt, _said = _order([])
    if order is None:
        return
    cp = _module()
    if cp is None:
        return
    tab = cp.CommandPostTab.__new__(cp.CommandPostTab)
    tab.rt = rt
    tab._by_key = {"ghost": types.SimpleNamespace()}
    # The order is «Секретки»'s since #2010, and this tab asks the runtime's own tab
    # register for it rather than importing it (`docs/panel-tabs.md`).
    rt.tabs = {"secret_tasks": types.SimpleNamespace(
        ghost_map=types.SimpleNamespace(order=order))}

    assert tab.web_press("ghost_rob_one", {"uuid": "11", "srv": 700}) == {"ok": True}
    _drain(order)
    assert rt.actions.played == ["steal_ghost_recon"], rt.actions.played
    assert rt.actions.args[0]["queue"] == "{uuid=11,server=700}", rt.actions.args
    assert rt.children.cmd is None, "a per-row robbery spawned something"

    # …and a press with no row named is not a press.
    assert tab.web_press("ghost_rob_one", {}) == {"error": "unknown"}

    order._proc = object()                       # a robbery in flight
    assert tab.web_press("ghost_rob_one", {"uuid": "12", "srv": 700}) == {
        "ok": False, "reason": "cmdpost.ghost.busy"}

    # …and a profile with «Секретки» switched off has no order at all: said, not pressed
    # by hand — a second way to spend a ghost robbery is what one-ability-one-place
    # exists to stop.
    rt.tabs = {}
    assert tab.web_press("ghost_rob_one", {"uuid": "13", "srv": 700}) == {
        "ok": False, "reason": "cmdpost.ghost.busy"}


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
