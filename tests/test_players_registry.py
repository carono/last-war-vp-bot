r"""The register of players (#1335): what a lap may write, and what may take a row away.

Three things are worth pinning and they are all the same sentence from different sides:

* **an empty read removes nothing.** A lap that drove over nobody, a capture that was
  not running, a client that was not logged in — all of them merge zero rows and take
  zero away. `panel/kept.py` exists because three of those were once treated as «gone»;
* **a lap may not write the person's own mark**, and a tile may not erase the combat
  numbers a profile reply left behind. An unknown never overwrites a known;
* **a row leaves for one reason and it is a person asking.** Any other reason raises at
  the call site rather than shipping.

…plus the searching, which is the whole of what the page does with the list, and the
listener that fills it (`tools/lib/world_index.py`).

Every identifier here is invented — `1000000000000001`, `Player1`, `AL1` — as the
repository requires, and it reads better: a reviewer can see at a glance which value a
test is about.

    C:\Python312\python.exe tests\test_players_registry.py
    python3 tests/test_players_registry.py
"""
from __future__ import annotations

TIER = "ui"   # the tab module imports tkinter — see tools/run_tests.py

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import lastwar_proto as proto                        # noqa: E402
import world_index                                   # noqa: E402
from panel.runtime import players as playersmod      # noqa: E402
from panel.runtime.store import Store                # noqa: E402
from panel.tabs.players import registry as reg       # noqa: E402

NOW = 1_700_000_000.0


#: Every store a test opened, closed by the runner between tests. Windows will not
#: delete a directory holding an open file, and a `TemporaryDirectory` that cannot clean
#: up raises INSTEAD OF the assertion the test was about — so the cleanup is told to let
#: it go, and the handles are closed here where it is deliberate rather than incidental.
_OPENED: list = []


def _tmpdir():
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def _store(tmp, legacy: str = "") -> reg.PlayerBook:
    """A register on a database of its own — one per profile, as the panel builds it."""
    store = Store(str(Path(tmp) / "panel.db"))
    _OPENED.append(store)
    return reg.PlayerBook(store, legacy)


def _swept_into(store, records, now=None) -> int:
    """A lap of the map, through THE ONE ENTRANCE every source uses (#1371)."""
    return store.sighted(records, source=reg.SRC_MAP, now=now,
                         field_source=reg.CHECKPOINT_SOURCES)


def _swept(uid="1000000000000001", **over) -> dict:
    """One row as the capture's checkpoint spells it."""
    row = {"uid": uid, "name": "Player1", "level": 30, "server_id": 100,
           "x": 500, "y": 600, "uuid": 111, "country": "XX",
           "alliance_id": "a" * 32, "alliance_abbr": "AL1",
           "power": None, "army_power": None, "army_kill": None,
           "svip_level": None, "remark": None, "seen_at": int(NOW)}
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# the rule of the list
# ---------------------------------------------------------------------------
def test_an_empty_read_takes_nothing_away():
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept()], now=NOW)
        assert len(store) == 1
        # A lap over empty ground, a capture that was not running, a client that was
        # not logged in — three ways of saying nothing, and none of them a removal.
        assert _swept_into(store, [], now=NOW) == 0
        assert _swept_into(store, None, now=NOW) == 0
        assert len(store) == 1


def _book(path: str) -> reg.PlayerBook:
    store = Store(path)
    _OPENED.append(store)
    return reg.PlayerBook(store)


def test_the_list_survives_a_restart():
    with _tmpdir() as tmp:
        path = str(Path(tmp) / "panel.db")
        _swept_into(_book(path), [_swept()], now=NOW)
        again = _book(path)   # a fresh panel, same profile
        assert len(again) == 1
        assert again.rows()[0]["name"] == "Player1"


def test_a_row_leaves_only_when_a_person_asks():
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept()], now=NOW)
        assert store.forget("1000000000000001") is True
        assert len(store) == 0


def test_there_is_exactly_one_way_a_row_can_leave():
    """The invariant `panel/kept.py` used to give the register by construction (#1398).

    The list is a TABLE now, so «no `clear()` and one removal that names a reason» has to
    be stated where the SQL is written. It is stated as: one `DELETE`, in `forget`, and
    no statement anywhere that could empty or blank the table wholesale. The next person
    to add a «prune the stale rows» does it in a diff a reviewer can see.
    """
    source = Path(playersmod.__file__).read_text(encoding="utf-8")
    body = source[source.index("class PlayerBook"):]
    deletes = [line.strip() for line in body.splitlines()
               if "DELETE FROM" in line.upper()]
    assert len(deletes) == 1, f"more than one way a row leaves: {deletes}"
    assert "WHERE uid = ?" in deletes[0], \
        f"the one DELETE is not aimed at a single row a person named: {deletes[0]}"
    assert "forget" in body[:body.index(deletes[0].split('"')[0].strip() or "DELETE")] \
        or "def forget" in body, "the DELETE moved out of `forget`"
    for forbidden in ("clear", "wipe", "reset", "empty", "truncate", "set_rows",
                      "replace", "__setitem__", "prune", "purge"):
        assert not hasattr(reg.PlayerBook, forbidden), \
            f"PlayerBook grew a {forbidden}() — that is the hole this rule closes"


# ---------------------------------------------------------------------------
# what a lap may and may not write
# ---------------------------------------------------------------------------
def test_a_lap_never_touches_the_persons_own_mark():
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept()], now=NOW)
        store.set_note("1000000000000001", "farm")
        _swept_into(store, [_swept(level=31)], now=NOW + 60)
        row = store.get("1000000000000001")
        assert row["note"] == "farm", row
        assert row["level"] == 31, "the lap must still refresh what the game says"


def test_a_tile_does_not_erase_the_numbers_only_a_profile_carries():
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept(power=12_000_000, army_power=9_000_000)], now=NOW)
        # …and then an ordinary lap goes past, whose tile knows no power at all.
        _swept_into(store, [_swept()], now=NOW + 60)
        assert store.get("1000000000000001")["power"] == 12_000_000


def test_first_seen_is_written_once_and_last_seen_moves():
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept(seen_at=int(NOW))], now=NOW)
        _swept_into(store, [_swept(seen_at=int(NOW) + 3600)], now=NOW + 3600)
        row = store.get("1000000000000001")
        assert row["first_seen"] == int(NOW)
        assert row["last_seen"] == int(NOW) + 3600


def test_a_checkpoint_that_says_the_same_thing_twice_changes_nothing():
    """The capture re-lists a sighting every tick for as long as it is fresh.

    Live that counted as a change every twenty seconds — `Kept.merge` compares the row
    it is HANDED against the row it HOLDS, and the held one carries `first_seen` and
    the person's own mark besides, so the two are never equal. A register that rewrites
    its file and says «карта добавила или обновила 103» over an unchanged map is a
    register nobody can read the log of.
    """
    with _tmpdir() as tmp:
        store = _store(tmp)
        assert _swept_into(store, [_swept()], now=NOW) == 1
        assert _swept_into(store, [_swept()], now=NOW) == 0
        assert _swept_into(store, [_swept()], now=NOW + 300) == 0, (
            "the wall clock is not what changed — the sighting did not move")
        # …and a sighting that DID move is still news.
        assert _swept_into(store, [_swept(seen_at=int(NOW) + 300)], now=NOW + 300) == 1


def test_a_mark_on_a_player_nobody_has_seen_is_refused():
    with _tmpdir() as tmp:
        assert _store(tmp).set_note("1000000000000009", "?") is False


# ---------------------------------------------------------------------------
# searching
# ---------------------------------------------------------------------------
def _rows() -> list:
    return [
        {"uid": "1", "name": "Player1", "level": 35, "power": 50_000_000,
         "alliance_abbr": "AL1", "alliance_name": "Alliance One",
         "server_id": 100, "x": 500, "y": 600, "last_seen": NOW},
        {"uid": "2", "name": "Player2", "level": 20, "power": 1_000_000,
         "alliance_abbr": "AL2", "server_id": 200, "x": 900, "y": 100,
         "last_seen": NOW - 10 * 24 * 3600, "note": "farm"},
        {"uid": "3", "name": "Somebody", "level": 30, "server_id": 100,
         "x": 505, "y": 604, "last_seen": NOW - 7200},
    ]


def _found(f) -> set:
    return {r["uid"] for r in reg.apply_filter(_rows(), f, now=NOW)}


def test_one_box_searches_name_alliance_and_coordinate():
    assert _found({"text": "player1"}) == {"1"}
    assert _found({"text": "AL2"}) == {"2"}
    assert _found({"text": "alliance one"}) == {"1"}     # the full name, not the tag
    assert _found({"text": "500,600"}) == {"1"}
    assert _found({"text": "farm"}) == {"2"}             # the person's own mark
    assert _found({"text": "nobody at all"}) == set()


def test_the_ranges_are_inclusive_and_an_unknown_is_not_in_one():
    assert _found({"level_min": 30}) == {"1", "3"}
    assert _found({"level_min": 20, "level_max": 30}) == {"2", "3"}
    # Player3 has no power at all, which is «never looked up» and not «zero».
    assert _found({"power_min": 1}) == {"1", "2"}
    assert _found({"power_min": 10_000_000}) == {"1"}


def test_the_server_is_picked_by_number_and_never_asked_of_the_game():
    """«Свой / чужой» would have meant reading the client to find out which is «свой».

    The rows carry the server their tile was on, so the box offers those and the page
    asks the game nothing — the rule this whole tab is built on.
    """
    assert _found({"server": "100"}) == {"1", "3"}
    assert _found({"server": "200"}) == {"2"}
    assert _found({"server": ""}) == {"1", "2", "3"}
    assert _found({"server": "999"}) == set()


def test_a_rectangle_and_a_radius():
    assert _found({"rect": (490, 590, 520, 620)}) == {"1", "3"}
    assert _found({"circle": (500, 600, 10)}) == {"1", "3"}
    assert _found({"circle": (500, 600, 2)}) == {"1"}


def test_seen_recently_and_not_for_a_week():
    assert _found({"seen": "hour"}) == {"1"}
    assert _found({"seen": "day"}) == {"1", "3"}
    assert _found({"seen": "stale"}) == {"2"}
    assert _found({"seen": "any"}) == {"1", "2", "3"}


def test_only_marked_and_the_and_between_clauses():
    assert _found({"noted": True}) == {"2"}
    assert _found({"noted": True, "level_min": 30}) == set()


def test_sorting_is_stable_and_every_column_has_an_order():
    rows = _rows()
    assert [r["uid"] for r in reg.sort_rows(rows, ("level", True))] == ["1", "3", "2"]
    assert [r["uid"] for r in reg.sort_rows(rows, ("level", False))] == ["2", "3", "1"]
    # Nothing is dropped by a column half the rows have no value for.
    for column in reg.SORT_KEYS:
        assert len(reg.sort_rows(rows, (column, True))) == 3, column


def test_the_sql_filter_and_the_readable_one_never_disagree():
    """Two definitions of one filter, and this is the price of keeping them (#1398).

    `registry.matches` walks one row and is what a person argues with; `where_of` is
    what seventeen thousand rows can afford. They are run over the same rows and the
    same filters here, and the first disagreement fails — including the ones that are
    easy to get wrong in SQL: an unknown is not inside a range, a Cyrillic name has to
    match case-insensitively, and «давно не виден» is the other side of «виден за
    неделю».
    """
    filters = [
        {}, {"text": "player1"}, {"text": "AL2"}, {"text": "alliance one"},
        {"text": "500,600"}, {"text": "farm"}, {"text": "ИГРОК"}, {"text": "игрок"},
        {"level_min": 30}, {"level_min": 20, "level_max": 30}, {"power_min": 1},
        {"power_min": 10_000_000}, {"alliance": "AL1"}, {"alliance": "al1"},
        {"server": "100"}, {"server": "999"}, {"rect": (490, 590, 520, 620)},
        {"circle": (500, 600, 10)}, {"circle": (500, 600, 2)},
        {"seen": "hour"}, {"seen": "day"}, {"seen": "week"}, {"seen": "stale"},
        {"noted": True}, {"noted": True, "level_min": 30},
        {"text": "player", "server": "100", "level_min": 30},
    ]
    rows = _rows() + [{"uid": "4", "name": "Игрок", "level": 40, "server_id": 100,
                       "alliance_abbr": "АЛ1", "x": 10, "y": 20, "last_seen": NOW}]
    with _tmpdir() as tmp:
        book = _store(tmp)
        book.sighted([dict(r, seen_at=r["last_seen"]) for r in rows],
                     source=reg.SRC_MAP, now=NOW)
        # …and the notes, which no map source may write.
        for row in rows:
            if row.get("note"):
                book.set_note(row["uid"], row["note"])
        for f in filters:
            in_python = {r["uid"] for r in reg.apply_filter(rows, f, now=NOW)}
            in_sql = {r["uid"] for r in book.search(f, now=NOW)}
            assert in_python == in_sql, (
                f"filter {f}: the readable one says {sorted(in_python)}, "
                f"the SQL one says {sorted(in_sql)}")


def test_every_column_sorts_the_same_way_in_both():
    with _tmpdir() as tmp:
        rows = _rows()
        book = _store(tmp)
        book.sighted([dict(r, seen_at=r["last_seen"]) for r in rows],
                     source=reg.SRC_MAP, now=NOW)
        # The marks go in the way a PERSON writes them — no map source may (#1371), and
        # a book without them would be sorting a column it has no values in.
        for row in rows:
            if row.get("note"):
                book.set_note(row["uid"], row["note"])
        for column in reg.SORT_KEYS:
            for down in (True, False):
                in_python = [r["uid"] for r in reg.sort_rows(rows, (column, down))]
                in_sql = [r["uid"] for r in book.search({}, (column, down), now=NOW)]
                assert in_python == in_sql, f"sorting by {column} (desc={down})"


# ---------------------------------------------------------------------------
# the move out of players.json
# ---------------------------------------------------------------------------
def test_the_old_file_comes_across_whole_and_stays_on_disk():
    """The register the operator has is the reason this has to be exact (#1398).

    Every row, every field, every provenance stamp and the person's own marks — and the
    file itself still there afterwards, because an import that misread something is
    answered by opening it and a delete is answered by nothing.
    """
    with _tmpdir() as tmp:
        legacy = Path(tmp) / "players.json"
        old = [{"uid": str(1000000000000000 + i), "name": f"Player{i}",
                "level": 20 + (i % 15), "server_id": 100 + (i % 3),
                "x": 500 + i, "y": 600 - i, "alliance_abbr": "AL1",
                "power": 1_000_000 * i if i % 2 else None,
                "note": "farm" if i % 5 == 0 else None,
                "first_seen": int(NOW) - i, "last_seen": int(NOW),
                "src": {"name": ["map", int(NOW)]}}
               for i in range(1, 501)]
        legacy.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")

        book = _store(tmp, str(legacy))
        assert book.ensure_imported() == 500
        assert len(book) == 500, "the import did not bring every row"
        for want in (old[0], old[249], old[-1]):
            got = book.get(want["uid"])
            for field, value in want.items():
                assert got[field] == value, (want["uid"], field, got[field], value)
        assert not legacy.exists(), "the file was left where a re-import could find it"
        kept = Path(str(legacy) + ".imported")
        assert kept.exists(), "THE OLD FILE WAS DELETED — it is the only insurance there is"
        assert json.loads(kept.read_text(encoding="utf-8")) == old


def test_a_second_start_does_not_re_import_over_what_a_person_has_done():
    with _tmpdir() as tmp:
        legacy = Path(tmp) / "players.json"
        legacy.write_text(json.dumps([_swept(last_seen=int(NOW))]), encoding="utf-8")
        book = _store(tmp, str(legacy))
        assert book.ensure_imported() == 1
        book.set_note("1000000000000001", "farm")
        book.forget("1000000000000009")            # a row that is not there
        # The file comes back — a restored backup, or a copy somebody put next to it.
        legacy.write_text(json.dumps([_swept(last_seen=int(NOW))]), encoding="utf-8")

        again = reg.PlayerBook(book.store, str(legacy))
        assert again.ensure_imported() == 0, "the import ran a second time"
        assert again.get("1000000000000001")["note"] == "farm"


def test_a_person_forgetting_a_row_survives_the_file_being_there():
    """The one removal there is, against the one thing that could undo it."""
    with _tmpdir() as tmp:
        legacy = Path(tmp) / "players.json"
        legacy.write_text(json.dumps([_swept()]), encoding="utf-8")
        book = _store(tmp, str(legacy))
        book.ensure_imported()
        assert book.forget("1000000000000001") is True
        legacy.write_text(json.dumps([_swept()]), encoding="utf-8")
        assert reg.PlayerBook(book.store, str(legacy)).ensure_imported() == 0
        assert len(book) == 0, "a row a person forgot came back from the old file"


# ---------------------------------------------------------------------------
# the listener that fills it
# ---------------------------------------------------------------------------
def _block(*tiles) -> dict:
    return {"serverPointArr": [{"maxAreaSize": 1000, "points": list(tiles)}]}


def _base_tile(uid="1000000000000001", alliance="a" * 32) -> dict:
    return {"_protobuf": {"f1": 600 * 1000 + 500, "f2": 6, "f100": 111,
                          "f102": 100, "f103": 100,
                          "f3": {"f1": uid, "f4": 30, "f14": "Player1",
                                 "f15": "AL1", "f7": alliance, "f27": "XX"}}}


def _city_tile(alliance="a" * 32) -> dict:
    return {"_protobuf": {"f1": 700 * 1000 + 700, "f2": 25, "f100": 222,
                          "f102": 100, "f103": 100,
                          "f101": {"f5": "AL1", "f7": alliance,
                                   "f10": "Alliance One"}}}


def test_the_listener_reads_a_base_off_the_same_map_response():
    index = world_index.WorldIndex()
    index.on_blocks(_block(_base_tile()), None, time.time())
    players = index.records()["players"]
    assert len(players) == 1
    row = players[0]
    assert (row["uid"], row["name"], row["level"]) == ("1000000000000001", "Player1", 30)
    assert (row["x"], row["y"], row["server_id"]) == (500, 600, 100)
    assert row["power"] is None, "no map tile carries a combat number"


def test_the_alliances_full_name_is_joined_by_uuid_whichever_tile_lands_first():
    for tiles in ((_base_tile(), _city_tile()), (_city_tile(), _base_tile())):
        index = world_index.WorldIndex()
        for tile in tiles:
            index.on_blocks(_block(tile), None, time.time())
        row = index.records()["players"][0]
        assert row["alliance_name"] == "Alliance One", tiles


def test_a_profile_reply_folds_its_numbers_onto_the_row():
    index = world_index.WorldIndex()
    index.on_blocks(_block(_base_tile()), None, time.time())
    index.on_response(proto.PROFILE_COMMAND, {"uids": [
        {"uid": "1000000000000001", "power": 12_000_000, "armyPower": 9_000_000,
         "armyKill": 4321, "svipLevel": 3, "mainBuildingLevel": 30,
         "serverId": 100, "name": "Player1", "allianceAbbrName": "AL1"}]})
    row = index.records()["players"][0]
    assert row["power"] == 12_000_000 and row["army_kill"] == 4321
    assert row["x"] == 500, "the profile must not lose what only the tile knew"
    # …and a lap going past afterwards must not undo it.
    index.on_blocks(_block(_base_tile()), None, time.time())
    assert index.records()["players"][0]["power"] == 12_000_000


def test_a_profile_for_a_player_no_lap_has_seen_is_kept_without_coordinates():
    index = world_index.WorldIndex()
    index.on_response(proto.PROFILE_COMMAND, {"uids": [
        {"uid": "1000000000000002", "power": 1, "name": "Player2",
         "serverId": 100, "mainBuildingLevel": 25}]})
    row = index.records()["players"][0]
    assert row["x"] is None and row["power"] == 1


def test_the_accounts_own_notes_are_stamped_before_and_after_the_map():
    # They arrive at LOGIN, before any map data — so the listener has to hold them.
    index = world_index.WorldIndex()
    index.on_response(proto.REMARK_COMMAND, {"list": [
        {"targetUid": "1000000000000001", "remark": "farm"}]})
    index.on_blocks(_block(_base_tile()), None, time.time())
    assert index.records()["players"][0]["remark"] == "farm"
    # …and the other way round, for a note that lands second.
    index = world_index.WorldIndex()
    index.on_blocks(_block(_base_tile()), None, time.time())
    index.on_response(proto.REMARK_COMMAND, {"list": [
        {"targetUid": "1000000000000001", "remark": "farm"}]})
    assert index.records()["players"][0]["remark"] == "farm"


def test_a_server_change_keeps_the_players_and_drops_the_things_that_move():
    index = world_index.WorldIndex()
    index.on_blocks(_block(_base_tile()), None, time.time())
    index.on_server_left(100, 200)
    assert len(index.records()["players"]) == 1, (
        "a base does not stop being where it was because the camera left")


def test_the_checkpoint_reader_survives_anything_on_disk():
    with _tmpdir() as tmp:
        missing = str(Path(tmp) / "nope.json")
        assert reg.load_checkpoint(missing) == []
        half = Path(tmp) / "half.json"
        half.write_text('{"players": [', encoding="utf-8")   # caught mid-replace
        assert reg.load_checkpoint(str(half)) == []
        good = Path(tmp) / "good.json"
        good.write_text(json.dumps({"players": [_swept()], "mines": []}),
                        encoding="utf-8")
        assert len(reg.load_checkpoint(str(good))) == 1


# ---------------------------------------------------------------------------
# the phone's copy
# ---------------------------------------------------------------------------
class _Game:
    """The only thing this tab may do to the client: go somewhere (#1371)."""

    def __init__(self) -> None:
        self.jumps = []

    def jump(self, x, y, server=None, quiet=False) -> bool:
        self.jumps.append((x, y, server))
        return True


class _Rt:
    """Just enough runtime for `web_view`: the words, said out of the English file."""

    def __init__(self) -> None:
        self.words = json.loads((ROOT / "panel" / "locales" / "en.json")
                                .read_text(encoding="utf-8"))
        self.asked = []
        self.game = _Game()

    def t(self, key: str, **fmt) -> str:
        self.asked.append(key)
        return (self.words.get(key) or key).format(**fmt)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.asked.append(key)


def _bare_tab(tmp):
    from panel.tabs.players.tab import BLANK_FILTER as PlayersTab_BLANK, PlayersTab

    tab = PlayersTab.__new__(PlayersTab)
    tab.rt = _Rt()
    tab._registry = _store(tmp)
    tab._sort = reg.DEFAULT_SORT
    tab._home_server = None
    tab._filter = dict(PlayersTab_BLANK)
    tab._built = False
    tab._merging = False
    tab._armed_forget = (None, 0.0)
    tab._detail_uid = ""
    return tab


def test_the_phone_says_only_keys_that_exist_and_offers_only_answered_presses():
    with _tmpdir() as tmp:
        tab = _bare_tab(tmp)
        _swept_into(tab._registry, [_swept()], now=time.time())
        view = tab.web_view()
        words = tab.rt.words

        keys = []
        for card in view["cards"]:
            keys.append(card.get("title"))
            keys += [row["label"] for row in card.get("rows") or ()]
            keys += [a["label"] for a in card.get("actions") or ()]
            keys.append(card.get("empty"))
            for item in card.get("items") or ():
                for action in item.get("actions") or ():
                    keys += [action["label"], action.get("prompt")]
        keys += [a["label"] for a in view["actions"]]
        missing = [k for k in keys if k and k not in words]
        assert not missing, missing

        offered = [a["id"] for a in view["actions"]]
        for card in view["cards"]:
            offered += [a["id"] for a in card.get("actions") or ()]
            for item in card.get("items") or ():
                offered += [a["id"] for a in item.get("actions") or ()]
        for action in offered:
            answer = tab.web_press(action, {"uid": "1000000000000001", "text": "x"})
            assert answer.get("error") != "unknown", action
        assert tab.web_press("nothing-of-the-sort", {}) == {"error": "unknown"}


def test_a_press_from_the_phone_moves_the_same_filter_the_window_shows():
    with _tmpdir() as tmp:
        tab = _bare_tab(tmp)
        # The server steps come out of the register, so it needs a row to have any.
        _swept_into(tab._registry, [_swept(server_id=100)], now=time.time())
        tab.web_press("server", {})
        assert tab._filter["server"] == "100", "the register's own server, not a table"
        tab.web_press("noted", {})
        assert tab._filter["noted"] is True
        tab.web_press("level", {})
        assert tab._filter["level_min"] == 20
        tab.web_press("reset", {})
        assert tab._filter["server"] == "" and tab._filter["level_min"] is None


def test_forgetting_from_the_phone_asks_once_before_it_does_it():
    with _tmpdir() as tmp:
        tab = _bare_tab(tmp)
        _swept_into(tab._registry, [_swept()], now=time.time())
        first = tab.web_press("forget", {"uid": "1000000000000001"})
        assert first["ok"] is False and first["reason"] == "players.forget.confirm"
        assert len(tab._registry) == 1, "the first press must not remove anything"
        assert tab.web_press("forget", {"uid": "1000000000000001"})["ok"] is True
        assert len(tab._registry) == 0


def test_a_saved_filter_the_code_cannot_mean_comes_back_blank():
    """A profile written by an older build held `server = "any"`.

    Today that means «only the server literally called any», so the page opened on
    «показано 0 · скрыто 4259» — an invisible filter looks exactly like an empty
    register, and there is nothing on screen that could tell the two apart.
    """
    with _tmpdir() as tmp:
        tab = _bare_tab(tmp)
        tab.apply_config({"filter": {"server": "any", "seen": "sometimes",
                                     "level_min": 30}})
        assert tab._filter["server"] == ""
        assert tab._filter["seen"] == "any"
        assert tab._filter["level_min"] == 30, "a value that IS meant survives"
        tab.apply_config({"filter": {"server": "100"}})
        assert tab._filter["server"] == "100"


def test_nothing_on_this_tab_can_ASK_the_game_anything():
    """The rule the whole page rests on, read off its own source.

    «Собираем ровно то, что и так приходит с обхода» — so no path here may top a row
    up: not opening the tab, not a filter, not a sort, not a selected row. A field no
    source carried stays empty and SAYS so. The one read that used to be here asked
    which server this account is on, for the «свой / чужой» filter; the filter picks a
    number out of the register instead.

    THE COORDINATE PRESS IS THE ONE EXCEPTION, and it is not a read (#1371). Clicking a
    tile jumps the camera there — a person asking for something to HAPPEN, which is
    what a panel is for (`CLAUDE.md`, «A button that STARTS something is not the thing
    being forbidden»). So `rt.game.jump` is allowed and every other use of `rt.game` is
    still a failure here, by name rather than by intention.
    """
    for name in ("tab.py", "registry.py"):
        source = (ROOT / "panel" / "tabs" / "players" / name).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                          if not line.lstrip().startswith("#"))
        # `rt.game` is a whole surface — evaluator(), client, up(), claim(),
        # current_server() — and only the jump belongs on this tab.
        for use in code.split("rt.game")[1:]:
            assert use.startswith(".jump"), f"{name} asks the game something"
        assert "play_async" not in code and "rt.actions" not in code, (
            f"{name} runs a scenario — this page reads a file and nothing else")


# ---------------------------------------------------------------------------
# every source, one entrance (#1371)
# ---------------------------------------------------------------------------
def test_a_source_may_only_write_the_fields_it_can_actually_know():
    """The guard the register needs most, and it is not bookkeeping.

    The banner block reads a `power` off every squad standing in a rally, and that is
    the SQUAD's, a fraction of the player's own. Merged onto `power` it would quietly
    overwrite a real profile reading — so the rally source cannot write `power` at all,
    however its records are spelled.
    """
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept(power=12_000_000)], now=NOW)
        store.sighted([{"uid": "1000000000000001", "power": 900_000,
                        "march_power": 900_000, "name": "Player1"}],
                      source=reg.SRC_RALLY, now=NOW + 60)
        row = store.get("1000000000000001")
        assert row["power"] == 12_000_000, "a squad's power is not a player's"
        assert row["march_power"] == 900_000


def test_a_tile_may_not_move_a_player_onto_their_own_task():
    """A secret task, a ghost point, a truck — all somewhere else on the map.

    Its coordinate says where the TASK is; writing it as the player's would put every
    alliancemate on their own dispatch point.
    """
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept(x=500, y=600)], now=NOW)
        store.sighted([{"uid": "1000000000000001", "x": 12, "y": 34,
                        "name": "Player1", "alliance_abbr": "AL1"}],
                      source=reg.SRC_TILE, now=NOW + 60)
        row = store.get("1000000000000001")
        assert (row["x"], row["y"]) == (500, 600)


def test_a_source_nobody_declared_is_refused_where_it_is_written():
    with _tmpdir() as tmp:
        try:
            _store(tmp).sighted([_swept()], source="whatever", now=NOW)
        except ValueError:
            return
        raise AssertionError("an undeclared source was accepted")


def test_every_field_remembers_who_said_it_and_when():
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept(power=12_000_000, remark="theirs")], now=NOW)
        src = store.get("1000000000000001")["src"]
        assert src["name"] == [reg.SRC_MAP, int(NOW)]
        # …and the three sources folded into one checkpoint are told apart.
        assert src["power"][0] == reg.SRC_PROFILE
        assert src["remark"][0] == reg.SRC_REMARK
        # A chat line later is a different source for that one field.
        store.sighted([{"uid": "1000000000000001", "name": "Renamed"}],
                      source=reg.SRC_CHAT, now=NOW + 3600)
        src = store.get("1000000000000001")["src"]
        assert src["name"] == [reg.SRC_CHAT, int(NOW) + 3600]
        assert src["power"][0] == reg.SRC_PROFILE, "one field, not the whole row"


def test_a_field_merely_confirmed_again_is_not_restamped():
    """Otherwise a lap rewrites a multi-megabyte file every twenty seconds, for ever.

    A stamp answers «since when has it been this, and who said so»; «when was the row
    last confirmed at all» is `last_seen`, which is what the «Виден» column shows.
    """
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept()], now=NOW)
        _swept_into(store, [_swept(seen_at=int(NOW) + 3600)], now=NOW + 3600)
        row = store.get("1000000000000001")
        assert row["src"]["name"] == [reg.SRC_MAP, int(NOW)]
        assert row["last_seen"] == int(NOW) + 3600


def test_no_source_may_touch_the_persons_own_mark():
    with _tmpdir() as tmp:
        store = _store(tmp)
        _swept_into(store, [_swept()], now=NOW)
        store.set_note("1000000000000001", "farm")
        for source in (reg.SRC_CHAT, reg.SRC_RALLY, reg.SRC_ALLIANCE, reg.SRC_TILE):
            store.sighted([{"uid": "1000000000000001", "note": "wiped",
                            "name": "Player1"}], source=source, now=NOW + 60)
        row = store.get("1000000000000001")
        assert row["note"] == "farm"
        assert row["src"]["note"][0] == reg.SRC_PERSON


def test_what_the_chat_hands_over_is_the_speaker_and_never_ourselves():
    """The record shape the chat tab builds — no game asked, the message came in."""
    from panel.tabs.chat import ChatTab

    met: dict = {}
    ChatTab._met_in_chat(met, {"sender_uid": "1000000000000002", "sender_name": "P2",
                               "alliance": "AL1", "server_id": "100",
                               "head_pic": "7", "ts": NOW})
    assert met["1000000000000002"]["alliance_abbr"] == "AL1"
    assert met["1000000000000002"]["server_id"] == 100
    ChatTab._met_in_chat(met, {"sender_uid": "1000000000000001", "is_mine": True,
                               "sender_name": "Me", "ts": NOW})
    assert "1000000000000001" not in met, "the register is of other people"


# ---------------------------------------------------------------------------
# the two presses the coordinate column added (#1371)
# ---------------------------------------------------------------------------
def test_a_coordinate_press_goes_through_the_panels_one_mechanism():
    """The cell holds the canonical token, `coords.parse` reads it, `jump` does it."""
    with _tmpdir() as tmp:
        tab = _bare_tab(tmp)
        _swept_into(tab._registry, [_swept(x=500, y=600, server_id=100)], now=NOW)
        row = tab._registry.get("1000000000000001")
        assert tab.coords_of(row) == "#100 X:500 Y:600"
        assert tab._jump(tab.coords_of(row)) is True
        for _ in range(100):                      # the jump runs off the Tk thread
            if tab.rt.game.jumps:
                break
            time.sleep(0.01)
        assert tab.rt.game.jumps == [(500, 600, 100)]
        assert tab._jump("") is False, "a player with no tile has nowhere to go"


def test_a_press_from_the_phone_that_carries_no_text_does_not_wipe_a_mark():
    """THE LIVE BUG (#1371): the renderer's item buttons ignored `prompt`.

    Every «Метка» from a phone arrived with no `text`, was read as an empty note,
    cleared the mark and answered «готово» — a register of 4 259 players with not one
    mark on any of them, and nothing anywhere saying why.
    """
    with _tmpdir() as tmp:
        tab = _bare_tab(tmp)
        _swept_into(tab._registry, [_swept()], now=NOW)
        assert tab.web_press("note", {"uid": "1000000000000001",
                                      "text": "farm"})["ok"] is True
        answer = tab.web_press("note", {"uid": "1000000000000001"})
        assert answer["ok"] is False and answer["reason"] == "players.web.no_text"
        assert tab._registry.get("1000000000000001")["note"] == "farm"
        # …and an EMPTY text still clears it: that is a person saying so.
        assert tab.web_press("note", {"uid": "1000000000000001", "text": ""})["ok"]
        assert tab._registry.get("1000000000000001")["note"] is None


def test_the_phones_details_card_says_the_same_lines_as_the_windows_dialog():
    with _tmpdir() as tmp:
        tab = _bare_tab(tmp)
        _swept_into(tab._registry, [_swept(power=12_000_000)], now=time.time())
        assert tab._web_detail_card() is None, "nothing is open until it is pressed"
        assert tab.web_press("details", {"uid": "1000000000000001"})["ok"] is True
        card = tab._web_detail_card()
        lines = [row["value"] for row in card["rows"][1:]]
        assert lines == tab.details_lines("1000000000000001")
        assert any("Player1" in line for line in lines)
        assert tab.web_press("details_close", {})["ok"] is True
        assert tab._web_detail_card() is None


def test_every_field_and_every_source_has_a_word_in_every_shipped_locale():
    """«Подробно» names them by key at run time, so the i18n audit cannot see them.

    It walks the code for literal keys; these two are built as `"players.field." +
    field`, which is exactly the shape that goes missing quietly — the phone would
    show `players.field.march_power` to whoever pressed it.
    """
    wanted = ["players.field." + f for f in reg.FIELDS
              if f not in ("uid", "first_seen", "last_seen", "src")]
    wanted += ["players.src." + s for s in reg.SOURCES] + ["players.src.unknown"]
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        words = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in wanted if key not in words]
        assert not missing, f"{path.name}: {missing}"


def test_the_renderer_draws_an_items_buttons_with_the_one_press_helper():
    """Read off `app.js`: the copy that did not know about `prompt` is gone for good."""
    source = (ROOT / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    body = source.split("function renderItem")[1].split("\nfunction ")[0]
    assert "pressButton(action)" in body
    assert "/api/screen/press" not in body, (
        "renderItem posts a press of its own again — that is how the mark was lost")


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except Exception as exc:                        # noqa: BLE001
            failed += 1
            print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        finally:
            while _OPENED:
                _OPENED.pop().close()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
