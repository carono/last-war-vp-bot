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

import rally_report as rr            # noqa: E402 — reachable only once the path is set

UID_A = "1000000000000001"
UID_B = "1000000000000002"


def _line(stamp, uid, name, power, hp, slot, heroes, team="2000000000000001",
          formation=60001):
    """One archived participant, in the shape `tools/rally_monitor.py` writes."""
    rows = [{"f1": hero, "f2": 175, "f3": 5, "f4": index + 1, "f15": 30}
            for index, hero in enumerate(heroes)]
    rows.append({"f1": rr.DRONE_ID, "f4": len(heroes) + 1, "f16": {"f1": rr.DRONE_ID,
                                                                  "f2": 40}})
    return json.dumps({
        "timestamp": stamp, "teamUuid": team, "ownerUid": uid, "ownerName": name,
        "power": power, "curHp": hp, "x": None, "y": None, "targetServer": None,
        "heroes": [{"heroId": h, "tier": 5, "level": 175, "skills": []} for h in heroes],
        "formation": formation,
        "armyInfoRaw": {"f1": {"f1": hp, "f2": hp, "f3": 900 + int(stamp), "f4": uid},
                        "f2": {"f2": rows, "f13": formation},
                        "f4": slot},
    }, ensure_ascii=False)


def _archive(tmp, name, lines):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def test_slot_splits_squads_and_survives_a_hero_swap():
    """Two slots are two squads; one slot stays one squad when a hero is replaced."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5]),
            _line(2000, UID_A, "Player1", 51_000_000, 3000, 1, [1, 2, 3, 4, 5]),
            # the same slot, one hero replaced — a composition key would call this a
            # third squad; the slot does not.
            _line(3000, UID_A, "Player1", 52_000_000, 3000, 1, [1, 2, 3, 4, 9]),
            _line(1500, UID_A, "Player1", 30_000_000, 2500, 2, [6, 7, 8, 10, 11]),
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
    assert squads[0]["rallies"] == 4


def test_two_profiles_of_one_alliance_are_not_two_readings():
    """The same rally reaches every watching profile — it must be counted once."""
    shared = [
        _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5]),
        _line(1000, UID_B, "Player2", 40_000_000, 2800, 1, [6, 7, 8, 10, 11]),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        one = _archive(tmp, "one.jsonl", shared)
        two = _archive(tmp, "two.jsonl", shared + [
            _line(2000, UID_B, "Player2", 41_000_000, 2800, 1, [6, 7, 8, 10, 11]),
        ])
        data = rr.load([one, two])

    kept = {os.path.basename(s["path"]): s["kept"] for s in data["sources"]}
    assert kept == {"one.jsonl": 2, "two.jsonl": 1}, kept
    for player in data["players"]:
        squad = player["squads"][0]
        assert squad["seen"] == len(squad["series"]) or squad["seen"] == 2, squad["seen"]
    by_uid = {p["uid"]: p for p in data["players"]}
    assert by_uid[UID_A]["seen"] == 1
    assert by_uid[UID_B]["seen"] == 2


def test_a_flat_run_collapses_to_one_point():
    """A refresh re-broadcasts the same march; forty identical readings are one point."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000 + step * 10, UID_A, "Player1", 50_000_000, 3000, 1,
                  [1, 2, 3, 4, 5], team=str(3000000000000000 + step))
            for step in range(40)
        ] + [_line(9000, UID_A, "Player1", 51_000_000, 3000, 1, [1, 2, 3, 4, 5])])
        data = rr.load([path])
    series = data["players"][0]["squads"][0]["series"]
    assert [point[1] for point in series] == [50_000_000, 51_000_000], series


def test_a_wounded_march_is_kept_but_marked_by_its_soldier_count():
    """Power follows the soldiers that marched — the page needs the pair, not one half."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5]),
            _line(2000, UID_A, "Player1", 20_000_000, 1200, 1, [1, 2, 3, 4, 5]),
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


def test_a_page_is_one_file_and_reaches_nothing():
    """No fetched script, no fetched font, no network — it opens on a phone offline."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _archive(tmp, "rally_log.jsonl", [
            _line(1000, UID_A, "Player1", 50_000_000, 3000, 1, [1, 2, 3, 4, 5]),
            _line(2000, UID_A, "Player1", 51_000_000, 3000, 1, [1, 2, 3, 4, 5]),
        ])
        page = rr.render(rr.load([path]))
    for reach in ("http://", "https://", "src=", "@import", "<link"):
        assert reach not in page, reach
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
