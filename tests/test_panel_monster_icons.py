r"""The banner's own picture, and the cap that can be TYPED from a phone (#2055).

Two halves of the same task, neither of which needs the game:

* `tools/lib/monster_icons.py` + `/api/monstericon` — the fifth picture route of the
  shape `/api/errandicon` opened (#2019). A machine that has not run an extractor
  answers «no picture» to everything, which is the contract every one of them keeps.
* the daily cap per kind is a FIELD on the phone rather than a reading — «в веб панели
  нельзя настроить лимиты автостягов», in the person's own words.

WHICH COLUMN OF `lw_world_monster` NAMES THE SPRITE IS STILL OPEN, and nothing here
depends on the answer: the map is `tools/data/monster_icons.json`, kind -> sprite stem,
and whichever column settles it fills that file. `pic_name` — the column #2018 pointed
at — is a PREFAB rather than an icon (`docs/research/golden-zombies.md`: config 1030000
reads `world_monster_general_invasion`, the world model); the same census names a
`worldmap_icon` column beside it, which is the likelier one.

No Tk, no game, no wire::

    python3 tests/test_panel_monster_icons.py
    C:\Python312\python.exe tests\test_panel_monster_icons.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import monster_icons                                       # noqa: E402


def test_a_machine_with_no_pictures_answers_nothing_and_never_raises() -> None:
    """The contract every picture route in this panel keeps."""
    monster_icons.forget()
    assert monster_icons.name_for("doom_elite") == ""
    assert monster_icons.name_for("") == ""
    assert monster_icons.stem_for("nothing at all") == ""


def test_the_name_is_checked_against_the_folder_and_not_trusted() -> None:
    """The route is reachable from a phone, so a name is a plain name or it is nothing."""
    for bad in ("", "   ", ".hidden.png", "../secrets.png", "sub/dir.png",
                "notapicture.txt", "doom_elite.PNG.exe"):
        assert monster_icons.file_named(bad) is None, bad


def test_the_map_file_exists_and_is_shaped_like_the_errands_one() -> None:
    """`{"icons": {kind: stem}}` — the shape `tools/data/errand_icons.json` set."""
    data = json.loads((_REPO / "tools" / "data" / "monster_icons.json")
                      .read_text(encoding="utf-8"))
    assert isinstance(data.get("icons"), dict), data


def test_the_route_is_registered_and_goes_through_the_shared_picture_door() -> None:
    text = (_REPO / "panel" / "web" / "server.py").read_text(encoding="utf-8")
    assert '"/api/monstericon"' in text
    assert "def _monstericon" in text
    # …and it authorises, resolves and caches exactly as its four siblings do, rather
    # than opening a file of its own.
    spot = text.index("def _monstericon")
    assert "self._picture(query, resolve)" in text[spot:spot + 900]


def test_the_runtime_door_hands_back_a_link_and_never_an_exception() -> None:
    """The panel asks `panel/runtime/`, never `tools/lib`, and gets `""` on any trouble."""
    text = (_REPO / "panel" / "runtime" / "monster_art.py").read_text(encoding="utf-8")
    assert "/api/monstericon?icon=" in text
    assert "except Exception" in text


def test_the_cap_is_a_field_on_the_phone_and_the_press_routes_it() -> None:
    """Half the task: «в веб панели нельзя настроить лимиты автостягов» (#2055)."""
    text = (_REPO / "panel" / "tabs" / "rally" / "tab.py").read_text(encoding="utf-8")
    assert "def _web_limit_card" in text
    assert '"key": "limit_" + key' in text
    # …and the press that comes back is routed to the ONE setter, never to a second copy
    # of the write.
    assert 'key.startswith("limit_")' in text
    assert "self.autorally.set_cap(" in text


def test_the_setter_gives_way_to_a_drawn_window() -> None:
    """A write behind a live field is undone by that field's own trace on the next tick.

    The same rule `panel/web/api.py::set_timer` follows for the Timers tab's boxes.
    """
    text = (_REPO / "panel" / "tabs" / "rally" / "autorally.py").read_text(encoding="utf-8")
    spot = text.index("def set_cap")
    body = text[spot:spot + 2600]
    assert "self._limit_vars.get(key)" in body
    assert "rallylimitsmod.save_limits" in body


def test_the_new_label_is_a_key_in_every_shipped_locale() -> None:
    """Eleven files, one commit — and the placeholders have to survive translation."""
    for path in sorted((_REPO / "panel" / "locales").glob("*.json")):
        words = json.loads(path.read_text(encoding="utf-8"))
        value = words.get("rally_limit.field")
        assert value, path.name
        assert "{name}" in value and "{count}" in value, (path.name, value)


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
