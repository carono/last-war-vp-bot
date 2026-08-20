r"""THE FIREWORK EAR: every push is counted, none is ever lost (#1677).

A firework is announced by nothing except the gift boxes falling off it
(`push.get.fireworks.gift`), so the receiver that hears that push is the whole ability's
proof of life. What is pinned here is what the receiver must not be allowed to become:

  * a push that arrives is SEEN, whether or not anything could be made of it — the shape
    #1523 named (an early `return` because nobody had opened a page) has no way in here,
    and the test says so by driving a book with no tab, no window and no game;
  * a push whose field names this build does not recognise is `dropped` WITH A REASON,
    never `lost`. `lost` is the number the whole intake ledger exists for and it stays at
    zero;
  * the day's counts belong to a DAY and to a PROFILE — a book that has been handed to
    another account starts that account's tally, rather than carrying the first one's;
  * and nothing a player is identified by ever reaches the book: the fields line the ear
    builds carries a box, a square and a kind, and the parser keeps nothing else.

Needs no display, no game and no database:

    python3 tests/test_firework_wire.py
"""
from __future__ import annotations

TIER = "unit"

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tools" / "lib", ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def _module(path: Path, name: str):
    """Load one file as a module, without importing its package.

    `panel.runtime.__init__` pulls in the whole runtime and Tk with it, and the book
    under test has neither — which is the point of it living apart from the tab.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


firework_wire = _module(ROOT / "panel" / "runtime" / "firework_wire.py", "firework_wire")
intakemod = _module(ROOT / "panel" / "runtime" / "intake.py", "panel_intake")


class _Profiles:
    def __init__(self, name: str) -> None:
        self.active = name


class _Store:
    """A blob table in a dict — the one method the book uses, and a count of writes."""

    def __init__(self) -> None:
        self.blobs: dict = {}
        self.writes = 0

    def blob_get(self, name: str):
        return self.blobs.get(name)

    def blob_set(self, name: str, value) -> None:
        self.writes += 1
        self.blobs[name] = value


class _Runtime:
    def __init__(self, profile: str = "acct1") -> None:
        self.profiles = _Profiles(profile)
        self.store = _Store()
        self.intake = intakemod.Intake()


def _book(rt=None):
    return firework_wire.FireworkBook(rt if rt is not None else _Runtime())


def _row(rt) -> dict:
    for row in rt.intake.report():
        if row["what"] == firework_wire.INTAKE:
            return row
    raise AssertionError("the firework receiver is not on the ledger at all")


# -- the fields line ---------------------------------------------------------------
def test_parse_fields_keeps_only_pairs():
    got = firework_wire.parse_fields("gift=1000000000000000001 tile=400001 type=0")
    assert got == {"gift": "1000000000000000001", "tile": "400001", "type": "0"}, got
    assert firework_wire.parse_fields("") == {}
    assert firework_wire.parse_fields("rubbish") == {}


def test_the_builder_never_names_a_player():
    """The ear's own builder, on the shape the live announcement really has (#1854).

    Measured 2026-08-20: `push.get.fireworks.gift` carries `{configId, pointId, uid,
    name, pic, picVer, headSkinId, headSkinET, isDouble}` — no box uuid, no owner, and
    the NICKNAME of whoever has just taken a box. Two fields may leave the builder; the
    player must not, in any spelling.
    """
    mon = _module(ROOT / "tools" / "wire_event_monitor.py", "wire_event_monitor")

    built = mon._firework_fields({"configId": 661502, "pointId": 400001,
                                  "uid": "1000000000000001", "name": "Player1",
                                  "pic": "", "picVer": 377, "headSkinId": 25000,
                                  "headSkinET": 0, "isDouble": False})
    assert "tile=400001" in built, built
    assert "kind=661502" in built, built
    for forbidden in ("uid", "1000000000000001", "Player1", "picVer", "headSkin"):
        assert forbidden not in built, built

    # …and the press's own spelling still answers, for a server that uses it.
    assert "kind=0" not in mon._firework_fields({"pointId": 400001, "type": 0})
    assert "kind=3" in mon._firework_fields({"pointId": 400001, "type": 3})


def test_the_builder_is_never_empty():
    """A push whose field names are not the ones known here is still one push."""
    mon = _module(ROOT / "tools" / "wire_event_monitor.py", "wire_event_monitor")

    assert mon._firework_fields({"somethingElse": 1}) == "n=1"
    assert mon._firework_fields(None) == "n=1"


# -- the receiver ------------------------------------------------------------------
def test_the_receiver_is_on_the_ledger_before_it_has_heard_anything():
    """«Ухо слушает, а салютов нет» must not read as «такого приёмника нет»."""
    rt = _Runtime()
    _book(rt)
    row = _row(rt)
    assert (row["seen"], row["kept"], row["dropped"], row["lost"]) == (0, 0, 0, 0), row


def test_a_push_is_seen_and_kept_with_no_tab_no_window_no_game():
    rt = _Runtime()
    book = _book(rt)
    assert book.note("push.get.fireworks.gift",
                     {"gift": "1", "tile": "400001", "type": "0"}) is True
    row = _row(rt)
    assert (row["seen"], row["kept"], row["lost"]) == (1, 1, 0), row


def test_an_unnamed_push_is_dropped_with_a_reason_and_never_lost():
    rt = _Runtime()
    book = _book(rt)
    assert book.note("push.get.fireworks.gift", {"n": "1"}) is False
    row = _row(rt)
    assert row["seen"] == 1, row
    assert row["dropped"] == 1, row
    assert row["lost"] == 0, row
    assert "no-tile" in (row.get("reasons") or {}), row


def test_the_day_counts_every_push_named_or_not():
    rt = _Runtime()
    book = _book(rt)
    for _ in range(3):
        book.note("push.get.fireworks.gift", {"tile": "400001"})
    book.note("push.get.fireworks.gift", {"n": "1"})
    tally = book.tally()
    assert tally["heard"] == 4, tally
    assert tally["named"] == 3, tally
    assert tally["tiles"] == 1, tally


def test_one_tile_many_boxes():
    book = _book()
    for _ in range(5):
        book.note("push.get.fireworks.gift", {"tile": "400001", "type": "0"})
    book.note("push.get.fireworks.gift", {"tile": "400002"})
    live = book.live()
    assert [(r["tile"], r["seen"]) for r in live] == [("400001", 5), ("400002", 1)], live


def test_a_tile_is_forgotten_when_its_firework_has_gone_out():
    book = _book()
    book.note("push.get.fireworks.gift", {"tile": "400001"})
    assert len(book.live()) == 1
    later = firework_wire.time.monotonic() + firework_wire.TILE_TTL_SEC + 1
    assert book.live(now=later) == []


# -- whose counts these are --------------------------------------------------------
def test_the_tally_is_checkpointed_to_the_profiles_own_database():
    rt = _Runtime()
    book = _book(rt)
    book.note("push.get.fireworks.gift", {"tile": "400001"})
    saved = rt.store.blobs.get(firework_wire.BLOB)
    assert saved and saved["heard"] == 1, saved


def test_a_saved_tally_is_picked_up_again():
    rt = _Runtime()
    rt.store.blobs[firework_wire.BLOB] = {"day": firework_wire._today(),
                                          "heard": 7, "named": 5}
    book = _book(rt)
    assert book.tally()["heard"] == 7, book.tally()


def test_another_days_tally_is_not_carried_over():
    rt = _Runtime()
    rt.store.blobs[firework_wire.BLOB] = {"day": "1999-01-01", "heard": 99, "named": 99}
    book = _book(rt)
    assert book.tally()["heard"] == 0, book.tally()


def test_another_profiles_tally_is_not_carried_over():
    """The runtime outlives a profile switch; the book must not."""
    rt = _Runtime("acct1")
    book = _book(rt)
    book.note("push.get.fireworks.gift", {"tile": "400001"})
    assert book.tally()["heard"] == 1
    rt.profiles.active = "acct2"
    rt.store = _Store()                            # …and the store follows the profile
    assert book.tally()["heard"] == 0, book.tally()
    assert book.live() == []


def test_a_store_that_raises_costs_the_checkpoint_and_never_the_push():
    class _Broken(_Store):
        def blob_set(self, name, value):
            raise RuntimeError("disk is gone")

        def blob_get(self, name):
            raise RuntimeError("disk is gone")

    rt = _Runtime()
    rt.store = _Broken()
    book = _book(rt)
    assert book.note("push.get.fireworks.gift", {"tile": "400001"}) is True
    assert _row(rt)["lost"] == 0


# -- the wiring --------------------------------------------------------------------
def test_the_ear_asks_the_child_for_the_firework_fields():
    """Read off the source: `panel/runtime/wire.py` imports its package, and this test
    runs on an interpreter with no Tk (which is the point of the book living apart)."""
    text = (ROOT / "panel" / "runtime" / "wire.py").read_text(encoding="utf-8")
    assert 'FIELDS_FIREWORK = "push.get.fireworks.gift"' in text
    assert "FIELDS_PATTERNS = (FIELDS_PATTERN, FIELDS_FIREWORK)" in text
    # …and the child is told about every one of them, not just the first.
    assert "for family in FIELDS_PATTERNS:" in text
    assert 'cmd += ["--fields", family]' in text
    # …and the fields line is routed to the book that keeps it.
    assert "self._rt.fireworks.note(command, firework_wire.parse_fields(built))" in text


def test_the_trigger_is_offered_and_runs_the_scenario():
    import panel.triggers as triggers              # noqa: PLC0415

    found = [t for t in triggers.DEFAULT_TRIGGERS if t.name == "firework_collect"]
    assert found, "the firework trigger is not in the catalogue"
    trig = found[0]
    assert trig.event_pattern == "push.get.fireworks.gift", trig.event_pattern
    assert trig.scenario == ("collect_fireworks",), trig.scenario
    assert not trig.enabled, "a trigger that acts on its own ships switched off"
    # …and it must not fire on our own answer, which is the same name without `push.`
    assert trig.event_pattern not in "get.fireworks.gift"
    # …and its label is a key, present in every locale the panel ships.
    import json                                    # noqa: PLC0415
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        words = json.loads(path.read_text(encoding="utf-8"))
        assert trig.label_key in words, f"{path.name} is missing {trig.label_key}"


def test_the_recipe_exists_and_presses_the_recorded_command():
    text = (ROOT / "src" / "lastwar_bot" / "actions" / "collect_fireworks.md").read_text(
        encoding="utf-8")
    assert "MsgDefines.GetFireworksGift" in text
    assert "IsHasAvailableBoxForMeByUid" in text        # the gate
    assert "IsThisGiftUuidGot" in text                  # …and the per-box one
    assert "# ru:" in text


def test_the_press_is_a_table_and_never_three_arguments():
    """#1854: the shape that threw inside the client must not come back.

    `SFSNetwork.SendMessage(cmd, uuid, ownerUid, type)` raises
    `GetFireworksGiftMessage.lua:13: attempt to index a number value (local 'param')` —
    measured live by sending both shapes at the same box. It threw inside the recipe's
    own `pcall`, so 553 runs reported success and collected nothing. Every send of this
    command, in every recipe, hands over ONE TABLE.
    """
    actions = ROOT / "src" / "lastwar_bot" / "actions"
    for name in ("collect_fireworks.md", "watch_fireworks.md"):
        text = (actions / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "SendMessage(MsgDefines.GetFireworksGift" in line and not line.startswith("#"):
                for call in line.split("SendMessage(MsgDefines.GetFireworksGift")[1:]:
                    assert call.lstrip().startswith(", {"), f"{name}: {call[:60]}"
                    assert "uuid =" in call[:120], f"{name}: no uuid field"
                    assert "ownerUid =" in call[:200], f"{name}: no ownerUid field"


def test_the_watcher_presses_inside_the_game_and_can_be_read_and_stopped():
    """The three halves of the in-VM watch, and the number it exists to report."""
    actions = ROOT / "src" / "lastwar_bot" / "actions"
    arm = (actions / "watch_fireworks.md").read_text(encoding="utf-8")
    read = (actions / "read_fireworks_watch.md").read_text(encoding="utf-8")
    stop = (actions / "unwatch_fireworks.md").read_text(encoding="utf-8")

    # it presses where the announcement arrives, not on a poll
    assert "SFSNetwork.HandleMessage" in arm
    assert "push.get.fireworks.gift" in arm
    # …re-arming is free, and stopping is a flag the wrapper itself checks
    assert "already on" in arm
    assert "B.on and (" in arm, "the hook must obey the off switch"
    assert "B.on = false" in stop
    # …and the reading carries the milliseconds from push to press
    assert "lastMs" in arm and "lastMs" in read
    assert "giftUuid2TimeTable" in read, "the count is the client's, never the panel's"
    for text in (arm, read, stop):
        assert "# ru:" in text


def test_the_watch_trigger_re_arms_the_hook():
    import panel.triggers as triggers              # noqa: PLC0415

    found = [t for t in triggers.DEFAULT_TRIGGERS if t.name == "firework_watch"]
    assert found, "the firework watch is not in the catalogue"
    trig = found[0]
    assert trig.scenario == ("watch_fireworks",), trig.scenario
    assert not trig.enabled, "a trigger that acts on its own ships switched off"
    assert trig.interval_sec >= 60, "re-arming is bookkeeping, not a poll for fireworks"
    import json                                    # noqa: PLC0415
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        words = json.loads(path.read_text(encoding="utf-8"))
        assert trig.label_key in words, f"{path.name} is missing {trig.label_key}"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    bad = 0
    for t in tests:
        try:
            t()
            print("  ok  ", t.__name__)
        except Exception as exc:                  # noqa: BLE001 — a test runner
            bad += 1
            print("  FAIL", t.__name__, "->", exc)
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
