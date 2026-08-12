r"""The live block of standing banners (task #1324) — the model behind it.

The «Ралли» tab now draws what is on the map RIGHT NOW: which banners are up, what each
is going for, who is standing in it and how much room is left. What makes it worth
pinning is that it is built out of two sources that disagree on purpose, and every way
of getting that wrong looks like an ordinary quiet evening:

* **the wire is first and the client is authoritative.** A push announces a banner a
  median of 10 s before the client's own march table has it (#1301), so a banner is
  shown the moment it is heard — and its COMPOSITION is only ever the game's reading,
  because a membership list assembled from log lines would be the panel keeping a second
  version of the truth (CLAUDE.md).
* **only the wire can say how a banner ENDED.** `push.alliance.march.remove` carries
  `{teamUuid, isCancel}` — launched or cancelled — and the client's march table loses
  the banner either way, so a reader of the table alone can never tell the two apart.
  That line must also never be mistaken for a banner to go and JOIN.
* **an empty reading and an unreadable one are not the same thing.** «The game says
  there are no banners» retires them; «the client could not answer» must leave the
  screen exactly as it was.
* **a face is a file in a shared folder, reached by name** — and the name a phone sends
  is checked rather than trusted.

The tab-level half (the `gone=` line stopping short of the bell and the join) is pinned
in tests/test_panel_rally_tab.py, which needs Tk. This file needs nothing.

    python3 tests/test_rally_roster.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "tools", ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.tabs.rally import roster as rostermod          # noqa: E402


class _Game:
    """A stand-in game link: hands back whatever lines the test wrote for it."""

    def __init__(self, lines=None, ready=True) -> None:
        self.lines = lines
        self.up = ready
        self.chunks: list = []

    def ready(self, fresh: bool = False) -> bool:
        return self.up

    def evaluator(self):
        return self

    def run(self, chunk, marker=None, settle=0.0, early=False, **kw):
        self.chunks.append(chunk)
        if self.lines is None:
            raise RuntimeError("the client did not answer")
        return list(self.lines)


class _Rt:
    def __init__(self, game) -> None:
        self.game = game


def _line(team, members, point="377512", server="1832", name="", level=""):
    """One `RLYR` row as the read writes it."""
    return (f"[log] {rostermod.MARKER} {team}|{point}|{server}|{name}|{level}|"
            + ",".join(members))


def _member(uid, name, head="20002", power="1000000", leader="0", mine="0"):
    return f"{uid}~{name}~{head}~{power}~{leader}~{mine}"


def _roster(lines=None, events=None):
    """A roster wired to a stand-in game, reading synchronously."""
    game = _Game(lines)
    said = events if events is not None else []
    model = rostermod.RallyRoster(
        _Rt(game), on_event=lambda key, fmt: said.append((key, fmt)))
    return model, game, said


def _read(model) -> None:
    """The read, on this thread — the worker is what the tab starts, not the model."""
    model._apply(model._read())


# --- what the wire says, before the client knows anything -------------------------
def test_a_banner_is_on_screen_the_moment_the_wire_announces_it():
    model, game, said = _roster(lines=[])
    model.heard("100000000000000001", content="300602", seats="1/5",
                point=(377512, 1832), count=1)
    banner = model.banners()[0]
    assert banner.state == "wire", "a banner the client has not caught up with is lost"
    assert banner.seats_cap == 5 and banner.taken == 1, vars(banner)
    assert banner.free == 4
    assert ("rally_roster.event.up", {"team": "100000000000000001"}) in said


def test_a_banner_the_client_never_confirms_is_dropped_and_not_called_closed():
    """It was over before the client caught up: nothing to say about it."""
    model, _game, said = _roster(lines=[])
    model.heard("100000000000000002", seats="2/5")
    banner = model.banners()[0]
    banner.heard_at = time.time() - rostermod.WIRE_GRACE_SEC - 1
    assert model.banners() == [], "a banner nobody ever saw the inside of lingers"
    assert not [k for k, _ in said if k.endswith(".closed")], said


# --- what the game holds ----------------------------------------------------------
def test_the_composition_and_the_target_come_off_the_game_read():
    model, game, _said = _roster(lines=[
        _line("100000000000000003",
              [_member("1000000000000001", "Player1", leader="1"),
               _member("1000000000000002", "Player2", mine="1")],
              name="season_monster_name001", level="35"),
        f"[log] {rostermod.MARKER} .",
    ])
    model.heard("100000000000000003", content="300602", seats="1/5")
    _read(model)
    banner = model.banners()[0]
    assert banner.state == "open"
    assert [m.name for m in banner.members] == ["Player1", "Player2"]
    assert banner.members[0].leader and not banner.members[1].leader
    assert banner.mine, "our own squad standing in it is not noticed"
    assert banner.target == (512, 377), banner.target
    assert banner.level == 35
    # The kind is the ONE table the per-kind budget is keyed by — not a second
    # classifier of this block's own.
    import rally_kinds
    assert banner.kind == rally_kinds.KIND_OF_NAME["season_monster_name001"]


def test_the_seat_count_takes_the_larger_of_the_two_and_never_the_newer():
    """Both counts are floors of the truth and the client's is the one that lags."""
    model, _game, _said = _roster(lines=[
        _line("100000000000000004", [_member("1000000000000001", "Player1")]),
        f"[log] {rostermod.MARKER} .",
    ])
    model.heard("100000000000000004", seats="4/5")
    _read(model)
    banner = model.banners()[0]
    assert banner.taken == 4, "the wire's fuller count was thrown away"
    assert banner.free == 1


def test_a_joiner_and_a_leaver_are_told_by_uid_and_not_by_the_count():
    """One in and one out between two reads leaves the count unchanged."""
    events: list = []
    model, game, _said = _roster(lines=[
        _line("100000000000000005", [_member("1000000000000001", "Player1")]),
        f"[log] {rostermod.MARKER} .",
    ], events=events)
    _read(model)
    game.lines = [
        _line("100000000000000005", [_member("1000000000000002", "Player2")]),
        f"[log] {rostermod.MARKER} .",
    ]
    _read(model)
    kinds = [(k, f.get("who")) for k, f in events]
    assert ("rally_roster.event.joined", "Player2") in kinds, kinds
    assert ("rally_roster.event.left", "Player1") in kinds, kinds


def test_a_banner_that_leaves_the_march_table_is_over():
    model, game, events = _roster(lines=[
        _line("100000000000000006", [_member("1000000000000001", "Player1")]),
        f"[log] {rostermod.MARKER} .",
    ])
    _read(model)
    game.lines = [f"[log] {rostermod.MARKER} ."]
    _read(model)
    banner = model.banners()[0]
    assert banner.state == "gone" and banner.ending == "closed"
    assert ("rally_roster.event.closed", {"team": "100000000000000006"}) in events
    # …and it is kept on screen for a while: «what happened to that one» is asked
    # after the fact.
    banner.gone_at = time.time() - rostermod.GONE_KEEP_SEC - 1
    assert model.banners() == []


def test_a_client_that_cannot_answer_leaves_the_screen_alone():
    """«Nothing is out» and «nothing could be read» must never look the same."""
    model, game, _said = _roster(lines=[
        _line("100000000000000007", [_member("1000000000000001", "Player1")]),
        f"[log] {rostermod.MARKER} .",
    ])
    _read(model)
    game.lines = None                       # the run raises: no client
    _read(model)
    assert model.banners()[0].state == "open", "an unreadable client emptied the block"
    game.lines = []                         # answered, but nothing came back
    game.up = False
    _read(model)
    assert model.banners()[0].state == "open", "a game that is not ready emptied it"


# --- only the wire can say HOW it ended -------------------------------------------
def test_the_wire_says_which_way_a_banner_ended():
    for word in ("launched", "cancelled"):
        model, _game, events = _roster(lines=[])
        model.heard("100000000000000008", seats="5/5")
        model.ended("100000000000000008", word)
        banner = model.banners()[0]
        assert banner.ending == word and banner.state == "gone"
        assert (f"rally_roster.event.{word}", {"team": "100000000000000008"}) in events


def test_the_monitor_prints_the_end_of_a_banner_and_archives_nothing():
    import rally_monitor

    monitor = rally_monitor.RallyMonitor(None)
    lines: list = []
    printed = __builtins__["print"] if isinstance(__builtins__, dict) else print
    import builtins
    builtins.print = lambda *a, **kw: lines.append(" ".join(str(x) for x in a))
    try:
        monitor._ended("push.alliance.march.remove",
                       {"teamUuid": 100000000000000009, "isCancel": False})
        monitor._ended("push.alliance.march.remove",
                       {"teamUuid": 100000000000000010, "isCancel": True})
        monitor._ended("push.alliance.march.remove", {})       # no banner: no line
    finally:
        builtins.print = printed
    assert len(lines) == 2, lines
    assert "team=100000000000000009" in lines[0] and "gone=launched" in lines[0]
    assert "gone=cancelled" in lines[1]
    assert monitor.participant_rows == 0, "an ending was written into the archive"


# --- the read itself ---------------------------------------------------------------
def test_the_read_asks_the_game_for_what_the_wire_cannot_carry():
    model, game, _said = _roster(lines=[f"[log] {rostermod.MARKER} ."])
    model.heard("100000000000000011", content="300602")
    _read(model)
    chunk = game.chunks[-1]
    assert "GetAllMarches" in chunk, "the composition is not read from the game"
    # The client's march record has no `targetContentId`, so what the banner is going
    # for can only be resolved by handing the id the push carried to the game's config.
    assert "lw_world_monster" in chunk
    assert "100000000000000011:300602" in chunk, "the wire's target never reached it"
    assert "allianceMembers" in chunk, "nothing would have an avatar to draw"


def test_the_chunk_runs_against_a_stand_in_client_and_writes_what_it_should():
    """The Lua itself, in a real interpreter with a stand-in game around it.

    A chunk that is only ever pasted into a live VM is a chunk nobody can be wrong about
    cheaply: this one groups marches by banner, picks the leader out by
    `uuid == teamUuid - 1`, falls back to the alliance roster for an avatar the march
    does not repeat, and resolves the species out of the config with the id the WIRE
    carried. All of that is testable without a game (`docs/research/…`, lupa).
    """
    try:
        import lupa
    except Exception as exc:                            # noqa: BLE001
        print(f"  SKIP no lupa: {exc}")
        return
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        LINES = {}
        CS = {UnityEngine = {Debug = {LogError = function(s) LINES[#LINES+1] = s end}}}
        LuaEntry = {Player = {uid = "1000000000000002"}}
        local marches = {
          {teamUuid = 5000, uuid = 4999, ownerUid = "1000000000000001",
           ownerName = "Play|er1", headSkinId = 20002, power = 1234567,
           targetPos = 377512, serverId = 1832},
          {teamUuid = 5000, uuid = 5001, ownerUid = "1000000000000002",
           ownerName = "Player2", power = 7654321},
        }
        local at = 0
        local col = {GetEnumerator = function()
          return {Current = nil, MoveNext = function(self)
            at = at + 1
            if marches[at] == nil then return false end
            self.Current = {Value = marches[at]}
            return true
          end}
        end}
        DataCenter = {
          WorldMarchDataManager = {GetAllMarches = function() return col end},
          AllianceMemberDataManager = {allianceMembers = {
            {uid = "1000000000000002", headSkinId = 25000}}},
        }
        LocalController = {instance = function() return {getValue =
          function(self, table_, cid, field)
            if table_ ~= "lw_world_monster" then return nil end
            if field == "name" then return "season_monster_name001" end
            if field == "level" then return 35 end
            return nil
          end} end}
    """)
    lua.execute(rostermod._chunk("5000:300602"))
    lines = list(lua.eval("LINES").values())
    assert len(lines) == 2 and lines[-1].endswith(" ."), lines
    row = rostermod._parse_row(lines[0].split(rostermod.MARKER, 1)[1].strip())
    assert row["team"] == "5000"
    assert row["target"] == (512, 377) and row["server"] == 1832
    assert row["name_key"] == "season_monster_name001" and row["level"] == 35
    first, second = row["members"]
    assert first.leader and not second.leader, "the leader is not the one it names"
    # A name carrying one of the separators would otherwise split the row in half.
    assert first.name == "Play er1", first.name
    assert first.head == "20002", "the march's own avatar was dropped"
    # …and the roster answers for the member whose march does not repeat it.
    assert second.head == "25000", "the alliance roster was never asked"
    assert second.mine and not first.mine, "our own squad is not marked"


def test_a_row_survives_a_name_with_nothing_in_it():
    row = rostermod._parse_row("100000000000000012|0|0|||"
                               + _member("1000000000000001", "?"))
    assert row["team"] == "100000000000000012"
    assert row["target"] is None and row["level"] == 0
    assert row["members"][0].name == "?"
    assert rostermod._parse_row("not a row at all") is None
    assert rostermod._parse_row("100|0|0") is None


# --- the faces ---------------------------------------------------------------------
def test_a_face_travels_as_a_name_and_the_name_is_checked(tmp=None):
    import tempfile

    import game_paths
    import player_faces

    folder = tempfile.mkdtemp(prefix="faces-")
    original = game_paths.avatar_cache
    game_paths.avatar_cache = lambda: folder
    try:
        good = os.path.join(folder, "1000000000000001.jpg")
        with open(good, "wb") as fh:
            fh.write(b"not really a jpeg, and it does not have to be")
        assert player_faces.file_named("1000000000000001.jpg") == good
        # …and everything else is refused, whatever it looks like.
        for bad in ("", ".", "..", "../../etc/passwd", "sub/1000000000000001.jpg",
                    "1000000000000001.txt", "nobody.jpg",
                    "..\\..\\windows\\win.ini"):
            assert player_faces.file_named(bad) is None, bad
        assert rostermod.face_url(good) == "/api/avatar?face=1000000000000001.jpg"
    finally:
        game_paths.avatar_cache = original


def test_the_faces_folder_is_the_machines_and_not_a_profiles():
    """A face is the same picture whichever account met the player first (#1306)."""
    import inspect

    import game_paths
    import player_faces

    source = inspect.getsource(player_faces)
    assert "avatar_cache" in source
    # The shared folder and nothing else: a profile's own directory, or a runtime to
    # ask which profile is open, would put the same face on disk four times over.
    for filed_per_account in ("profiles/", "profiles\\", "rt.profiles", "profile_dir"):
        assert filed_per_account not in source, filed_per_account
    assert callable(game_paths.avatar_cache)


# --- the block is one profile's ----------------------------------------------------
def test_a_profile_switch_empties_it():
    model, _game, _said = _roster(lines=[])
    model.heard("100000000000000013", seats="1/5")
    model.reset()
    assert model.banners() == [], "another account was shown this alliance's banners"


def test_nothing_about_the_model_is_module_state():
    """Two rosters in one window must not see each other's banners."""
    first, _g1, _s1 = _roster(lines=[])
    second, _g2, _s2 = _roster(lines=[])
    first.heard("100000000000000014", seats="1/5")
    assert len(first.banners()) == 1 and second.banners() == []


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
    raise SystemExit(_main())
