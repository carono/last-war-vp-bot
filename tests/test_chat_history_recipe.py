r"""READING THE CHAT HISTORY IS ONE RECIPE, and it asks the SERVER nothing (#2064).

The chat tab only ever LISTENED: a reader child hears what arrives, so a freshly
switched-on tab was empty until somebody spoke and everything said before the panel
started existed only in the client. The client keeps its own per-room copy
(`Chat.ChatInterface.getRoomMgr().roomDatas[<room>].msgs`, filled by the very parse the
listener hooks), and `READ_CHAT` reads THAT — once, on a press.

What is pinned here:

  * the statement parses, with and without `LIMIT`, and refuses a line that names no
    variable to answer into;
  * the seeding Lua reads the client's held messages and never asks the server —
    `ChatRoomRequestHistoryMsg` is the deeper fetch and it must stay out of this path;
  * the backlog fills a buffer of ITS OWN, not the listener's `__CR_BUF`: the reader
    child drains that one on its own clock, so a backlog seeded there would go to
    whichever of the two asked first and the other would see nothing;
  * one decoder, shared — the listener's records and the backlog's land in the same
    store under the same identity, and a field spelled differently in one of them is a
    duplicate nobody can see is a duplicate;
  * an un-confirmed echo (no `seqId`) is dropped and a timestamp is the message's own
    `serverTime`, never the parse time;
  * the recipe exists and declares its argument;
  * BOTH front-ends press it — a button in `build()` and an action in `web_view()` —
    and neither of them spawns anything.

Needs no display and no game:

    python3 tests/test_chat_history_recipe.py
"""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import chat_records                                          # noqa: E402
from lastwar_bot import script_engine as se                  # noqa: E402

_RECIPE = _REPO / "src" / "lastwar_bot" / "actions" / "read_chat_history.md"
_TAB = _REPO / "panel" / "tabs" / "chat.py"
_DSL = _REPO / "docs" / "dsl.md"


# ---------------------------------------------------------------------------
# the statement
# ---------------------------------------------------------------------------
def test_parses_with_and_without_limit():
    prog = se.parse_text("READ_CHAT INTO chat\nREAD_CHAT LIMIT 7 INTO other\n")
    stmts = [s for s in prog if isinstance(s, se.ReadChatStmt)]
    assert len(stmts) == 2, f"parsed {len(stmts)} READ_CHAT statements"
    assert (stmts[0].var, stmts[0].limit) == ("chat", 40), "the default limit moved"
    assert (stmts[1].var, stmts[1].limit) == ("other", 7)


def test_refuses_a_line_with_no_variable():
    """`READ_CHAT` alone answers nowhere — a read whose answer is dropped is not a read."""
    for bad in ("READ_CHAT", "READ_CHAT LIMIT 5", "READ_CHAT INTO"):
        try:
            prog = se.parse_text(bad + "\n")
        except se.ScriptParseError:
            continue                      # refused outright: the strongest answer
        assert not any(isinstance(s, se.ReadChatStmt) for s in prog), \
            f"{bad!r} parsed as a READ_CHAT"


# ---------------------------------------------------------------------------
# the Lua: what it reads, and what it must never ask
# ---------------------------------------------------------------------------
def test_backlog_reads_what_the_client_holds():
    lua = chat_records.backlog_lua(12)
    assert "Chat.ChatInterface" in lua, "the room manager is not reached"
    assert "roomDatas" in lua and ".msgs" in lua, "the held messages are not read"
    assert "12" in lua, "the per-room limit was not filled in"


def test_backlog_never_asks_the_server():
    """The deeper fetch is a question to the server, and it is deliberately not made."""
    lua = chat_records.backlog_lua()
    for forbidden in ("ChatRoomRequestHistoryMsg", "RequestHistory", "historyState"):
        assert forbidden not in lua, f"the backlog read asks the server ({forbidden})"


def test_backlog_has_a_buffer_of_its_own():
    """Never the listener's `__CR_BUF`: the reader child empties that on its own clock."""
    assert chat_records.HISTORY_SINK != "__CR_BUF"
    lua = chat_records.backlog_lua()
    assert chat_records.HISTORY_SINK in lua
    assert "_G.__CR_BUF = {}" not in lua, "the backlog empties the listener's buffer"


def test_the_recorder_is_the_same_one():
    """One recorder, so the two readers cannot record a field differently."""
    lua = chat_records.backlog_lua()
    assert "_G.__CR_REC" in lua, "the backlog does not use the shared recorder"
    assert "__CR_REC" in chat_records.record_lua()


# ---------------------------------------------------------------------------
# the decoding: one parser for both readers
# ---------------------------------------------------------------------------
def _line(**over) -> str:
    fields = {"roomId": "country_100", "seqId": "8123", "st": "1756412345000",
              "post": "1", "type": "0", "uid": "1000000000000001", "lang": "en",
              "gm": "0", "srv": "100", "hp": "0", "hpv": "0", "ismy": "false",
              "alliance": "414c31", "sender": "506c6179657231",
              "msg": "68656c6c6f", "we": ""}
    fields.update(over)
    return "ACT R " + " ".join(f"{k}={v}" for k, v in fields.items())


def test_one_decoder_for_both_readers():
    rec = chat_records.parse_record_line(_line())
    assert rec is not None
    assert rec["room_id"] == "country_100" and rec["chat_type"] == "world"
    assert rec["sender_name"] == "Player1" and rec["alliance"] == "AL1"
    assert rec["msg"] == "hello"
    assert chat_records.usable(rec)


def test_the_stamp_is_the_message_s_own_server_time():
    """History is parsed «now»; a parse-time stamp sorts every old message to the bottom."""
    rec = chat_records.parse_record_line(_line(st="1756412345000"))
    assert abs(rec["ts"] - 1756412345.0) < 0.001, rec["ts"]
    assert rec["ts"] < time.time(), "the record was stamped with the parse time"


def test_an_unconfirmed_echo_is_dropped():
    """An outgoing message is parsed twice; only the server-confirmed copy is kept."""
    assert not chat_records.usable(chat_records.parse_record_line(_line(seqId="0")))
    assert not chat_records.usable(chat_records.parse_record_line(_line(seqId="nil")))
    assert not chat_records.usable(chat_records.parse_record_line(_line(roomId="nil")))


def test_identity_is_shared():
    """Both readers store under one identity, or the same message lands twice."""
    a = chat_records.parse_record_line(_line())
    b = chat_records.parse_record_line(_line(hp="7", ismy="true"))
    assert chat_records.identity(a) == chat_records.identity(b), \
        "a field neither reader stores changes the identity"


# ---------------------------------------------------------------------------
# the ability, and the two front-ends that press it
# ---------------------------------------------------------------------------
def test_the_recipe_is_one_file():
    text = _RECIPE.read_text(encoding="utf-8")
    assert "# ru:" in text, "the title has no Russian line"
    body = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert any(ln.startswith("ARGS limit") for ln in body), "no `limit` argument"
    assert any(ln.upper().startswith("READ_CHAT") for ln in body), "nothing is read"


def test_the_recipe_parses():
    body, _merged = se.prepare_source(_RECIPE.read_text(encoding="utf-8"), {})
    prog = se.parse_text(body)
    assert any(isinstance(s, se.ReadChatStmt) for s in prog)


def test_both_front_ends_press_it():
    """A control that exists on one side and not the other is one nobody can find."""
    source = _TAB.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_load_backlog" in names, "the tab cannot read the history at all"
    assert '"read_chat_history"' in source, "the tab does not play the recipe"
    assert '"chat.history.load"' in source, "no label for the press"
    assert 'action == "history"' in source, "the phone cannot press it"
    assert source.count('"chat.history.load"') >= 2, \
        "the press is on one front-end only (window button + web action expected)"


def test_the_press_spawns_nothing():
    """A press travels only when the ability is a scenario — the read is one."""
    source = _TAB.read_text(encoding="utf-8")
    start = source.index("def _load_backlog")
    end = source.index("def _dm_append")
    body = source[start:end]
    for forbidden in ("children.spawn", "subprocess", "Popen"):
        assert forbidden not in body, f"the backlog read spawns something ({forbidden})"


def test_history_is_not_news():
    """A press that seeds three hundred old messages must not paint the flow strip
    green over a reader that has been dead for an hour, nor ring as unread."""
    source = _TAB.read_text(encoding="utf-8")
    assert 'record.pop("_backlog"' in source, "backlog records are not marked"
    assert "if not backlog:\n                    self.take(INTAKE_CHAT).kept()" in source, \
        "a backlog record still counts as the reader talking"
    assert source.count("not backlog and not record.get(\"is_mine\")") >= 2, \
        "history still counts as unread"


def test_the_statement_is_documented():
    doc = _DSL.read_text(encoding="utf-8")
    assert "### `READ_CHAT" in doc, "READ_CHAT is not in docs/dsl.md"
    assert "ChatRoomRequestHistoryMsg" in doc, \
        "the doc does not say what the statement refuses to ask"


def test_every_locale_has_the_keys():
    wanted = ("chat.history.load", "log.chat.backlog", "log.chat.backlog_none",
              "log.chat.backlog_reading")
    for path in sorted((_REPO / "panel" / "locales").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in wanted if k not in table]
        assert not missing, f"{path.name} is missing {missing}"


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
