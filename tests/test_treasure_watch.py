r"""The treasure watcher's hook and ring, run in a real Lua (task #1277).

«Я хочу видеть все сообщения, которые поймает игра: что есть сокровища, что отряд был
отправлен, что сокровище было взято.» A treasure is out for minutes and the alliance
digs it together, so the messages have to be caught by something that was already
listening — `lua_actions.treasure_watch_*`, a pair of wrappers on the client's own two
network doors writing into a ring buffer that lives in the game VM.

What this file pins is everything that can be checked without a game, and the parts that
have bitten already:

  * **the wrappers pass the call through.** They are on `SFSNetwork.SendMessage` and
    `SFSNetwork.HandleMessage`, which is the client's networking — a hook that swallowed
    a message, or its return value, would break the game rather than the tool;
  * **the filter keeps the three things a person is watching for** — the chest (anything
    `detect`/`treasure`), the squad going out (`world.march.*` at target 50/182) and the
    reward — and drops the rest. **The march target is the SECOND argument**, after the
    formation uuid: the first version of the filter read the first one, so every dig
    march it was written for went unrecorded;
  * **the ring drops the OLDEST and confesses it.** `drop` is reported once and cleared,
    because a count reported twice reads as messages lost twice;
  * **the drain has two caps** — a count and a character budget — because its answer
    travels as one log line, and a line cut in half is worse than a short one;
  * **stopping puts the doors back.** A hook left on is a hook the tracer would wrap.

    C:\Python312\python.exe tests\test_treasure_watch.py
    python3 tests/test_treasure_watch.py            # lupa is enough
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_actions  # noqa: E402

try:
    import lupa                                     # noqa: E402
except ImportError:                                 # pragma: no cover - optional
    lupa = None


#: As much of the client as the hook touches: the two network doors, the SFSObject
#: reader the field extraction goes through, the server clock and the log.
_CLIENT = """
SAID = {}
CS = {UnityEngine = {Debug = {LogError = function(s) SAID[#SAID+1] = tostring(s) end}}}
DataCenter = {}
PASSED = {}
SFSNetwork = {
  SendMessage = function(cmd, ...) PASSED[#PASSED+1] = "out:" .. tostring(cmd)
    return "sent" end,
  HandleMessage = function(cmd, obj, ...) PASSED[#PASSED+1] = "in:" .. tostring(cmd)
    return "handled" end,
}
SFSObject = {
  GetKeys = function(o) return o.__keys end,
  GetData = function(o, k) return o[k] end,
}
UITimeManager = {Instance = {GetServerTime = function(self) return 1785322473766 end}}
ChatInterface = {getServerTime = function() return 1785322473 end}
"""


def _needs_lua(what: str) -> bool:
    if lupa is None:                                # pragma: no cover - optional
        print(f"  skip {what}: lupa is not installed")
        return False
    return True


def _vm(cap: int = 400, wide: bool = False):
    """A Lua VM with the client stand-in and the watcher installed."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    if wide:
        lua.execute("DataCenter.__lw_treasure_watch_wide = true")
    lua.execute(lua_actions.treasure_watch_install(cap=cap))
    return lua


def _state(lua) -> dict:
    """`on=… wide=… buf=…` parsed into a dict of ints."""
    raw = str(lua.eval(lua_actions.treasure_watch_state()))
    return {k: int(v) for k, _, v in (p.partition("=") for p in raw.split())}


def _drain(lua, limit: int = 25, budget: int = 6000) -> dict:
    return json.loads(str(lua.eval(lua_actions.treasure_watch_drain(limit, budget))))


# -- the messages of the three moments, as the 2026-08-07 session had them ----
# Invented ids of the right SHAPE — a uuid is 19 digits, a server is small — because a
# fixture that only passes against a real account is testing the account (CLAUDE.md).
_UUID = 1000000000000000001
_SERVER = 100
_FORMATION = 1000000000000000002


def _the_chest_is_shared(lua) -> None:
    """The alliance chat share that announces a chest — `world.treasure.share.chat`."""
    lua.execute(
        'SFSNetwork.HandleMessage("world.treasure.share.chat", '
        '{__keys={"uuid","x","y"}, uuid=%d, x=571, y=456})' % _UUID)


def _the_squad_goes_out(lua) -> None:
    """The dig march: target 50, and the formation uuid AHEAD of it."""
    lua.execute(
        'SFSNetwork.SendMessage("world.march.formation.new", %d, 50, %d, "1;2", 1, true)'
        % (_FORMATION, _UUID))


def _the_chest_is_taken(lua) -> None:
    """The claim going out, and the alliance broadcast coming back."""
    lua.execute('SFSNetwork.SendMessage("detect.event.claim.treasure", %d, %d)'
                % (_UUID, _SERVER))
    lua.execute('SFSNetwork.HandleMessage("push.detect.treasure.claim", '
                '{__keys={"uuid","operator"}, uuid=%d, operator={}})' % _UUID)


def _noise(lua, times: int = 1) -> None:
    """What the client says all day and nobody watching a treasure wants to see."""
    for _ in range(times):
        lua.execute('SFSNetwork.SendMessage("push.resource.info", 1)')
        lua.execute('SFSNetwork.HandleMessage("push.hero.data", {__keys={"a"}, a=1})')
        lua.execute('SFSNetwork.SendMessage("world.march.formation.new", %d, 11, 7, "1;2")'
                    % _FORMATION)


def test_the_client_still_gets_its_messages():
    """The hook is on the client's networking: every call reaches the original, with its
    return value intact. A watcher that eats a message breaks the game, not the tool."""
    if not _needs_lua("the call passes through"):
        return
    lua = _vm()
    assert str(lua.eval('SFSNetwork.SendMessage("detect.event.claim.treasure", 1, 2)')) \
        == "sent"
    assert str(lua.eval('SFSNetwork.HandleMessage("push.hero.data", '
                        '{__keys={"a"}, a=1})')) == "handled"
    passed = list(lua.eval("PASSED").values())
    assert passed == ["out:detect.event.claim.treasure", "in:push.hero.data"], passed


def test_the_three_moments_are_kept_and_the_noise_is_not():
    """The chest appearing, the squad going out, the chest being taken — and nothing
    else. The march is the one that has to be got right: its target type is the SECOND
    argument, and reading the first one silently records no dig march at all."""
    if not _needs_lua("the filter keeps the three moments"):
        return
    lua = _vm()
    _noise(lua, times=3)
    _the_chest_is_shared(lua)
    _the_squad_goes_out(lua)
    _the_chest_is_taken(lua)
    _noise(lua, times=3)
    feed = _drain(lua)
    commands = [it["c"] for it in feed["items"]]
    assert commands == ["world.treasure.share.chat", "world.march.formation.new",
                        "detect.event.claim.treasure", "push.detect.treasure.claim"], \
        commands
    assert feed["more"] == 0 and feed["drop"] == 0, feed
    assert [it["d"] for it in feed["items"]] == ["in", "out", "out", "in"]


def test_a_send_carries_its_arguments_and_a_push_its_fields():
    """Two shapes, one feed. A send has no names to read, so its arguments are numbered;
    a push is an SFSObject, so its own field names come through — which is what makes
    the line readable without the protocol note beside it."""
    if not _needs_lua("arguments and fields"):
        return
    lua = _vm()
    _the_chest_is_taken(lua)
    sent, pushed = _drain(lua)["items"]
    assert sent["f"] == "a1=%d a2=%d" % (_UUID, _SERVER), sent
    assert "uuid=%d" % _UUID in pushed["f"], pushed
    #: A nested object is named, not walked: one level is what a feed line can hold.
    assert "operator={...}" in pushed["f"], pushed


def test_wide_keeps_everything():
    """«Что я пропустил» is a different question from «что с сокровищем», and it is the
    one where a filter is the enemy. Wide records every message either way."""
    if not _needs_lua("wide keeps everything"):
        return
    lua = _vm(wide=True)
    _noise(lua)
    feed = _drain(lua)
    assert feed["wide"] == 1
    assert [it["c"] for it in feed["items"]] == [
        "push.resource.info", "push.hero.data", "world.march.formation.new"], feed


def test_wide_is_re_armed_without_a_second_layer_of_wrappers():
    """Switching wide on mid-session must not wrap the wrappers: the doors are hooked
    once and the hook reads the flag every call. Two layers would double every entry and
    leave the client's own function two frames deep."""
    if not _needs_lua("re-arming does not re-wrap"):
        return
    lua = _vm()
    lua.execute("DataCenter.__lw_treasure_watch_wide = true")
    lua.execute(lua_actions.treasure_watch_install())
    _noise(lua)
    feed = _drain(lua)
    assert feed["wide"] == 1
    assert len(feed["items"]) == 3, feed          # …and not 6
    assert list(lua.eval("PASSED").values()).count("in:push.hero.data") == 1


def test_the_ring_drops_the_oldest_and_says_so_once():
    """A buffer that overflows quietly is a buffer that lies. `drop` is the ring's own
    confession, reported once and cleared — counted twice it reads as twice the loss."""
    if not _needs_lua("the ring confesses"):
        return
    lua = _vm(cap=3)
    for _ in range(5):
        _the_chest_is_taken(lua)                  # 10 messages into a ring of 3
    assert _state(lua)["buf"] == 3
    feed = _drain(lua)
    assert feed["drop"] == 7, feed
    assert feed["seq"] == 10, feed
    assert _drain(lua)["drop"] == 0               # …and not again


def test_the_drain_is_capped_by_count_and_by_size():
    """The answer travels as ONE log line. Whichever cap is reached first stops the
    drain, and what is left is reported as `more` so a caller loops instead of losing
    the tail to a truncated line."""
    if not _needs_lua("the drain is capped"):
        return
    lua = _vm()
    for _ in range(20):
        _the_chest_is_taken(lua)                  # 40 messages
    first = _drain(lua, limit=5)
    assert first["n"] == 5 and first["more"] == 35, first
    small = _drain(lua, limit=25, budget=1)       # the budget bites on the first entry
    assert small["n"] == 1 and small["more"] == 34, small
    #: What comes out is in the order it went in, and never twice.
    assert first["items"][0]["i"] == 1 and small["items"][0]["i"] == 6


def test_the_feed_survives_a_json_hostile_payload():
    """The client says all sorts of things, and one of them will contain a quote or a
    newline. The drain escapes rather than trusting — a broken line loses the whole
    drain, not one entry."""
    if not _needs_lua("the payload is escaped"):
        return
    lua = _vm()
    lua.execute(r'SFSNetwork.HandleMessage("push.detect.event.info", '
                r'{__keys={"name"}, name = "a\"b\\c\nd"})')
    item = _drain(lua)["items"][0]                # parses at all = the escaping holds
    assert 'a"b\\c' in item["f"], item
    assert "\n" not in item["f"], item


def test_stopping_puts_the_doors_back_and_keeps_what_was_caught():
    """Stopping is not throwing away: the wrappers come off — a hook left on is one the
    tracer would wrap — and the ring keeps what it has, because the last thing recorded
    is usually the interesting one."""
    if not _needs_lua("stopping restores the doors"):
        return
    lua = _vm()
    original_send = lua.eval("SFSNetwork.SendMessage")
    _the_chest_is_taken(lua)
    lua.execute(lua_actions.treasure_watch_stop())
    state = _state(lua)
    assert state["on"] == 0 and state["buf"] == 2, state
    assert lua.eval("SFSNetwork.SendMessage") != original_send      # unwrapped
    _the_chest_is_taken(lua)                                        # …and deaf now
    assert _state(lua)["buf"] == 2


def test_a_watcher_that_was_never_installed_answers_instead_of_failing():
    """The client is restarted more often than the panel is, and a restart wipes the VM.
    Both reads answer «nothing here» rather than erroring, so a page opening onto a fresh
    client draws an empty feed instead of a stack trace."""
    if not _needs_lua("an empty VM answers"):
        return
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    assert _state(lua) == {"on": 0, "wide": 0, "buf": 0, "seq": 0, "drop": 0, "cap": 0}
    assert _drain(lua) == {"on": 0, "wide": 0, "n": 0, "more": 0, "drop": 0,
                           "seq": 0, "items": []}


def test_the_recipes_read_what_the_primitives_write():
    """The three recipes carry the expressions VERBATIM, the way read_codename_event.md
    carries the codename gates: a `READ_LUA` takes literal Lua, so the text in the `.md`
    is a copy, and a copy that drifts is two answers to one question. This is what fails
    when one of them is edited alone."""
    actions = ROOT / "src" / "lastwar_bot" / "actions" / "dev"
    state = lua_actions.treasure_watch_state()
    drain = lua_actions.treasure_watch_drain()
    for name, expected in (("watch_treasures", state),
                           ("unwatch_treasures", state),
                           ("read_treasure_watch", drain)):
        text = (actions / (name + ".md")).read_text(encoding="utf-8")
        assert expected in text, f"{name}.md no longer matches lua_actions"
    #: …and the presses are the catalogue's, not hand-written Lua in the recipe.
    watch = (actions / "watch_treasures.md").read_text(encoding="utf-8")
    assert "TAP treasure_watch_on" in watch
    assert "TAP treasure_watch_off" in (
        actions / "unwatch_treasures.md").read_text(encoding="utf-8")


def test_the_recipes_parse_and_wide_travels_as_a_lua_bool():
    """`ARGS wide = false` has to reach the game as Lua's `false`, not as `0` — which is
    TRUE in Lua and would leave the watch quietly recording every message the client
    says."""
    sys.path.insert(0, str(ROOT / "src"))
    from lastwar_bot import script_engine                       # noqa: PLC0415

    actions = ROOT / "src" / "lastwar_bot" / "actions" / "dev"
    for name in ("watch_treasures", "read_treasure_watch", "unwatch_treasures"):
        text = (actions / (name + ".md")).read_text(encoding="utf-8")
        script_engine.parse_text(script_engine.prepare_source(text, {})[0])
    text = (actions / "watch_treasures.md").read_text(encoding="utf-8")
    for value, rendered in ((True, "= true"), (False, "= false")):
        body, _ = script_engine.prepare_source(text, {"wide": value})
        chunk = [s for s in script_engine.parse_text(body)
                 if type(s).__name__ == "LuaStmt"][0].chunk
        assert chunk.endswith(rendered), chunk


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
