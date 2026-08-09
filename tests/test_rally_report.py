r"""What `tools/rally_report.py` folds a rally archive into — task #1305.

The one thing worth pinning here is the squad key. The report claims a march's
`armyInfo.f4` is the squad slot it was sent from, and everything downstream — the growth
chart, the per-squad statistics, the composition shown — is wrong the moment that is
wrong: key on the march uuid instead and every rally becomes a brand-new "squad", key on
the hero composition and one hero swap splits a squad in two.

**Every value in this file is invented.** The uids are `1000000000000001`-shaped, the
players are `Player1`/`Player2`, the heroes are the numeric ids the wire ships anyway.
That is deliberate — see CLAUDE.md, «Not one identifier of a real account is written
down». A fixture that only passes against a live capture is testing the account.

Run:
    C:\Python312\python.exe tests\test_rally_report.py
    python3 tests/test_rally_report.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools"))
sys.path.insert(0, str(_REPO / "tools" / "lib"))

import head_icons_map as head_map    # noqa: E402 — reachable only once the path is set
import rally_report as rr            # noqa: E402

UID_A = "1000000000000001"
UID_B = "1000000000000002"


def _line(stamp, uid, name, power, hp, slot, heroes, team="2000000000000001",
          formation=60001, alliance=None, head=None):
    """One archived participant, in the shape `tools/rally_monitor.py` writes."""
    rows = [{"f1": hero, "f2": 175, "f3": 5, "f4": index + 1, "f15": 30}
            for index, hero in enumerate(heroes)]
    rows.append({"f1": rr.DRONE_ID, "f4": len(heroes) + 1, "f16": {"f1": rr.DRONE_ID,
                                                                  "f2": 40}})
    record = {
        "timestamp": stamp, "teamUuid": team, "ownerUid": uid, "ownerName": name,
        "power": power, "curHp": hp, "x": None, "y": None, "targetServer": None,
        "heroes": [{"heroId": h, "tier": 5, "level": 175, "skills": []} for h in heroes],
        "formation": formation,
        "armyInfoRaw": {"f1": {"f1": hp, "f2": hp, "f3": 900 + int(stamp), "f4": uid},
                        "f2": {"f2": rows, "f13": formation},
                        "f4": slot},
    }
    if alliance is not None:
        record.update({"allianceAbbr": alliance, "allianceName": f"Alliance {alliance}",
                       "allianceId": f"{alliance}-0000"})
    if head is not None:
        record["headSkinId"] = head
    return json.dumps(record, ensure_ascii=False)


def _archive(tmp, name, lines):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def test_slot_splits_squads_and_survives_a_hero_swap():
    """Two slots are two squads; one slot stays one squad when a hero is replaced."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="2000000000000001"),
            _line(2000, UID_A, "Player1", 51_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="2000000000000002"),
            # the same slot, one hero replaced — a composition key would call this a
            # third squad; the slot does not.
            _line(3000, UID_A, "Player1", 52_000_000, 3000, 1, [1, 2, 3, 4, 9],
                  team="2000000000000003"),
            _line(1500, UID_A, "Player1", 30_000_000, 2500, 2, [6, 7, 8, 10, 11],
                  team="2000000000000002"),
        ])
        data = rr.load([path])

    assert len(data["players"]) == 1, data["players"]
    player = data["players"][0]
    assert [s["slot"] for s in player["squads"]] == [1, 2]
    first = player["squads"][0]
    assert len(first["series"]) == 3, first["series"]
    assert first["peak"] == 52_000_000
    assert first["power"] == 52_000_000           # the latest reading
    assert [h["id"] for h in first["heroes"]] == [1, 2, 3, 4, 9]   # the latest, too
    assert first["drone"] == {"grade": 40}
    assert first["formation"] == 60001


def test_the_march_uuid_is_not_the_squad():
    """Every line carries its own `f1.f3`; keying on it would make four squads."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000 + step, UID_A, "Player1", 50_000_000 + step, 3000, 1,
                  [1, 2, 3, 4, 5], team=str(3000000000000000 + step))
            for step in range(4)
        ])
        data = rr.load([path])
    squads = data["players"][0]["squads"]
    assert len(squads) == 1, [s["slot"] for s in squads]
    assert squads[0]["moments"] == 4


def test_two_profiles_of_one_alliance_are_not_two_readings():
    """The same rally reaches every watching profile — it must be counted once."""
    shared = [
        _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5]),
        _line(1000, UID_B, "Player2", 40_000_000, 2800, 1, [6, 7, 8, 10, 11]),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        one = _archive(tmp, "one.jsonl", shared)
        two = _archive(tmp, "two.jsonl", shared + [
            _line(2000, UID_B, "Player2", 41_000_000, 2800, 1, [6, 7, 8, 10, 11],
                  team="2000000000000002"),
        ])
        data = rr.load([one, two])

    kept = {os.path.basename(s["path"]): s["kept"] for s in data["sources"]}
    assert kept == {"one.jsonl": 2, "two.jsonl": 1}, kept
    by_uid = {p["uid"]: p for p in data["players"]}
    assert by_uid[UID_A]["moments"] == 1
    assert by_uid[UID_B]["moments"] == 2


def test_one_rally_is_one_moment_however_many_lines_it_left():
    """A rally is re-broadcast on every refresh; that is one sighting, not forty."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            # forty lines of ONE rally: same team, same reading, forty timestamps
            _line(1000 + step * 10, UID_A, "Player1", 50_000_000, 3000, 1,
                  [1, 2, 3, 4, 5], team="4000000000000001")
            for step in range(40)
        ] + [_line(9000, UID_A, "Player1", 51_000_000, 3000, 1, [1, 2, 3, 4, 5],
                   team="4000000000000002")])
        data = rr.load([path])
    squad = data["players"][0]["squads"][0]
    assert squad["moments"] == 2, squad["moments"]
    # …and the moment is stamped when the squad was FIRST seen, not on the last refresh.
    assert [(p[0], p[1]) for p in squad["series"]] == [(1000, 50_000_000),
                                                       (9000, 51_000_000)]


def test_an_unchanging_squad_still_has_a_point_on_every_day_it_was_seen():
    """The page buckets by day, so a day whose only reading was thinned out reads as
    «not seen» — a break in the line. A squad that never changes is exactly the one
    that would have had every middle day deleted, and it is the one whose flat line
    means the most.
    """
    import datetime
    noon = datetime.datetime(2026, 3, 2, 12, 0).timestamp()
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            # five days running, three sightings a day, the same reading every time
            _line(noon + day * 86400 + hour * 3600, UID_A, "Player1",
                  50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team=str(4000000000000000 + day * 10 + hour))
            for day in range(5) for hour in range(3)
        ])
        data = rr.load([path])
    squad = data["players"][0]["squads"][0]
    assert squad["moments"] == 15, squad["moments"]
    days = {datetime.datetime.fromtimestamp(p[0]).date() for p in squad["series"]}
    assert len(days) == 5, sorted(days)          # not one of them may go missing


def test_a_create_before_the_team_id_is_not_a_second_moment():
    """`teamUuid` is "0" until the team exists; that line is the same sighting."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="0"),
            _line(1060, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="0"),
        ])
        data = rr.load([path])
    assert data["players"][0]["squads"][0]["moments"] == 1


def test_a_wounded_march_is_kept_but_marked_by_its_soldier_count():
    """Power follows the soldiers that marched — the page needs the pair, not one half."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="2000000000000001"),
            _line(2000, UID_A, "Player1", 20_000_000, 1200, 1, [1, 2, 3, 4, 5],
                  team="2000000000000002"),
        ])
        data = rr.load([path])
    squad = data["players"][0]["squads"][0]
    assert [(p[1], p[2]) for p in squad["series"]] == [(50_000_000, 3000),
                                                       (20_000_000, 1200)]
    assert squad["fullHp"] == 3000
    assert squad["peak"] == 50_000_000


def test_the_fullest_reading_names_the_squad():
    """A squad that marched wiped is archived with the survivor — not what it is."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5]),
            _line(2000, UID_A, "Player1", 900_000, 40, 1, [1]),
        ])
        data = rr.load([path])
    squad = data["players"][0]["squads"][0]
    assert [h["id"] for h in squad["heroes"]] == [1, 2, 3, 4, 5], squad["heroes"]


def test_the_alliance_is_the_last_one_the_player_was_seen_in():
    """A player who moved during the window belongs to the alliance they are in now."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="2000000000000001", alliance="AL1"),
            _line(5000, UID_A, "Player1", 51_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="2000000000000002", alliance="AL2"),
        ])
        data = rr.load([path])
        groups = rr.group_by_alliance(data, [path])
    assert data["players"][0]["alliance"]["tag"] == "AL2"
    assert [g["tag"] for g in groups] == ["AL2"]
    assert groups[0]["how"] == "archive"


def test_riding_together_spreads_one_known_tag_over_the_group():
    """Archives written before #1305 carry no tag; a rally is still an alliance affair."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            # one rally, two players — only the first line says which alliance
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="2000000000000001", alliance="AL1"),
            _line(1000, UID_B, "Player2", 40_000_000, 2800, 1, [6, 7, 8, 10, 11],
                  team="2000000000000001"),
            # …and somebody who never rode with either of them
            _line(2000, "1000000000000003", "Player3", 30_000_000, 2000, 1, [1, 2, 3],
                  team="2000000000000009"),
        ])
        data = rr.load([path])
        groups = rr.group_by_alliance(data, [path])

    named = [g for g in groups if g["tag"] == "AL1"]
    assert len(named) == 1, [g["tag"] for g in groups]
    assert {p["uid"] for p in named[0]["players"]} == {UID_A, UID_B}
    assert named[0]["how"] == "partial"          # the reader is told it was spread
    # the stranger is a group of their own and is NOT thrown away
    other = [g for g in groups if g["tag"] == ""]
    assert len(other) == 1 and other[0]["how"] == "unknown"
    assert [p["uid"] for p in other[0]["players"]] == ["1000000000000003"]
    assert sum(len(g["players"]) for g in groups) == 3


def _fake_cache(root: str, uid: str, pic_ver: int) -> str:
    """One JPEG in the client's cache layout: bucket by uid tail, name by md5."""
    import hashlib
    bucket = os.path.join(root, uid[-6:])
    os.makedirs(bucket, exist_ok=True)
    digest = hashlib.md5(f"{uid}_{pic_ver}".encode()).hexdigest()
    path = os.path.join(bucket, f"{digest}.jpg")
    try:
        from PIL import Image
        Image.new("RGB", (256, 256), (30, 90, 150)).save(path, "JPEG")
    except ImportError:
        # No image library here — the bytes only have to exist for the lookup, and
        # `_shrink` hands an unreadable file over whole rather than dropping it.
        with open(path, "wb") as fh:
            fh.write(b"not a picture")
    return path


def test_the_newest_cached_photo_wins():
    """A player who changed their picture leaves the old file behind — take the new."""
    import player_photos
    with tempfile.TemporaryDirectory() as tmp:
        _fake_cache(tmp, UID_A, 3)
        newest = _fake_cache(tmp, UID_A, 41)
        player_photos.reset_cache()
        found = player_photos.newest_for(UID_A, root=tmp)
        assert found == (newest, 41), found
        assert player_photos.newest_for(UID_B, root=tmp) is None      # never downloaded
        assert player_photos.newest_for("", root=tmp) is None


def test_the_photo_cache_beats_the_built_in_avatar():
    """A player's own picture is the picture; the built-in one is what is left."""
    with tempfile.TemporaryDirectory() as tmp:
        cache = os.path.join(tmp, "cache")
        _fake_cache(cache, UID_A, 7)
        path = _archive(tmp, "rally_log.jsonl", [
            # A wears a built-in avatar AND has a photo cached — the photo wins
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  head=head_map.PICKABLE_BASE + 1),
            # B only has the built-in one
            _line(1000, UID_B, "Player2", 40_000_000, 2800, 1, [6, 7, 8, 10, 11],
                  team="2000000000000001", head=head_map.PICKABLE_BASE + 1),
            # C's id is outside the pickable range and has no photo — placeholder
            _line(2000, "1000000000000003", "Player3", 30_000_000, 2000, 1, [1, 2],
                  team="2000000000000002", head=99999),
        ])
        import player_photos
        player_photos.reset_cache()
        data = rr.load([path])
        out = os.path.join(tmp, "report.html")
        hrefs, stats = rr.copy_avatars(data["players"], out, root=cache)

        assert stats["photos"] == 1, stats
        assert hrefs[UID_A] == f"report_avatars/{UID_A}.jpg"   # relative, beside the page
        assert os.path.exists(os.path.join(tmp, "report_avatars", f"{UID_A}.jpg"))
        # only the players the cache could not answer for cost a sprite
        assert stats["ids"] == 2, stats
        assert stats["unmapped"] == [99999], stats
        if head_map.available():                     # skipped where nothing is extracted
            key = str(head_map.PICKABLE_BASE + 1)
            assert hrefs[key] == f"report_avatars/{key}.png"
            assert stats["sprites"] == 1, stats
        assert "1000000000000003" not in hrefs


def test_only_the_pickable_avatar_range_is_mapped():
    """The id -> sprite table is encrypted; the numbering rule covers one family only."""
    assert head_map.resname_for(head_map.PICKABLE_BASE + 1) == "player_head_1"
    assert head_map.resname_for(head_map.PICKABLE_BASE + head_map.PICKABLE_MAX) == \
        f"player_head_{head_map.PICKABLE_MAX}"
    for outside in (head_map.PICKABLE_BASE,                       # the base itself
                    head_map.PICKABLE_BASE + head_map.PICKABLE_MAX + 1,
                    25000, 25015, 21016, None, "x"):
        assert head_map.resname_for(outside) is None, outside


def test_a_page_reaches_nothing_off_the_disk():
    """No fetched script, no fetched font, no network — it opens on a phone offline.

    The avatars ARE files now, so `src=` is allowed — but only ever as a relative path
    next to the page. A scheme, a protocol-relative `//host`, or an absolute path would
    each be a link out of the folder the reader was handed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  head=head_map.PICKABLE_BASE + 1),
            _line(2000, UID_A, "Player1", 51_000_000, 3000, 1, [1, 2, 3, 4, 5],
                  team="2000000000000002", head=head_map.PICKABLE_BASE + 1),
        ])
        cache = os.path.join(tmp, "cache")
        _fake_cache(cache, UID_A, 7)
        import player_photos
        player_photos.reset_cache()
        data = rr.load([path])
        hrefs, _stats = rr.copy_avatars(data["players"],
                                        os.path.join(tmp, "report.html"), root=cache)
        page = rr.render(data, rr.group_by_alliance(data, [path]), hrefs)
    for reach in ("http://", "https://", "@import", "<link", 'src="/', 'src="//'):
        assert reach not in page, reach
    for href in hrefs.values():
        assert not href.startswith(("/", "http", "..")), href
    assert "Player1" in page and UID_A in page          # the data really is embedded


def test_a_nickname_cannot_end_the_payload():
    """Players choose their own names, and one of them will contain a closing tag."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player</script><b>1", 50_000_000, 3000, 1,
                  [1, 2, 3, 4, 5]),
        ])
        page = rr.render(rr.load([path]))
    assert page.count("</script>") == 1, "the payload closed the script block early"
    assert "<\\/script>" in page


def test_writing_outside_a_git_ignored_tree_is_refused():
    """The page is other people's nicknames and uids; a tracked destination is a leak."""
    argv, cwd = sys.argv[:], os.getcwd()
    try:
        os.chdir(_REPO)
        sys.argv = ["rally_report.py", "--out", "docs/rally.html"]
        assert rr.main() == 1
        assert not os.path.exists(os.path.join(_REPO, "docs", "rally.html"))
    finally:
        sys.argv, _ = argv, os.chdir(cwd)


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
