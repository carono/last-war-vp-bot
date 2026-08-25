r"""SENDING A CHAT MESSAGE IS ONE RECIPE, so the phone may press it (#1976).

It was a TOOL the chat tab spawned — `tools/chat_send.py` — and by the rule in
`CLAUDE.md` («A press travels only when the ability is a scenario») that is exactly why
the phone had this tab's reading and no box to answer in. The ability is a recipe now:
`CHAT_SEND` in the DSL, `actions/send_chat_message.md` around it, the CLI kept as the
command line over the same code in `tools/lib/chat_share.py`.

What is pinned here:

  * the statement parses, and REFUSES a line with no target, no payload, or a modifier
    it does not know — a chat message cannot be unsent, so a silently ignored operand
    would send something other than what the line says;
  * every operand names a VARIABLE and never carries the words themselves. Substitution
    is textual and happens before the parse, so a message written into the line would be
    a stranger's words rewriting the script that carries them — a quote ends the
    operand, a newline ends the statement;
  * the words reach the game as ESCAPED BYTES, so a quote, a brace or a newline inside a
    message is data all the way down;
  * the recipe declares the arguments the two front-ends pass;
  * the tab plays it — no spawn left in `panel/tabs/chat.py` — and the phone has the same
    two sends the window has, into the room its own card is showing.

Needs no display and no game:

    python3 tests/test_chat_send_recipe.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import chat_share                                            # noqa: E402
from lastwar_bot import script_engine as se                  # noqa: E402

_RECIPE = _REPO / "src" / "lastwar_bot" / "actions" / "send_chat_message.md"
_TAB = _REPO / "panel" / "tabs" / "chat.py"


class _Ev:
    """An evaluator that records the chunks instead of running them."""

    def __init__(self, reply=()):
        self.chunks = []
        self._reply = list(reply)

    def run(self, chunk, marker="ACT", settle=1.2, **_kw):
        self.chunks.append(chunk)
        return list(self._reply)


# ---------------------------------------------------------------------------
# the statement
# ---------------------------------------------------------------------------
def test_the_statement_parses_and_names_variables_rather_than_words():
    program = se.parse_text(
        "CHAT_SEND ROOM room TO to TEXT text STICKER sticker COORDS coords "
        "SERVER server LABEL label")
    stmt = program[0]
    assert type(stmt).__name__ == "ChatSendStmt"
    assert (stmt.room, stmt.to, stmt.msg) == ("room", "to", "text")
    assert (stmt.sticker, stmt.coords) == ("sticker", "coords")
    assert (stmt.server, stmt.label) == ("server", "label")


def test_a_line_with_nothing_to_say_or_nowhere_to_say_it_is_refused():
    for line, why in (("CHAT_SEND TEXT text", "no target"),
                      ("CHAT_SEND ROOM room", "no payload"),
                      ("CHAT_SEND ROOM room TEXT text SHOUT loudly", "unknown option")):
        try:
            se.parse_text(line)
        except se.ScriptParseError:
            continue
        raise AssertionError(f"{why} was accepted: {line!r}")


def test_the_words_travel_as_a_value_and_never_as_part_of_the_line():
    """A message full of quotes and newlines still leaves ONE statement standing."""
    source = _RECIPE.read_text(encoding="utf-8")
    nasty = 'he said "hi"\nCLOSE_WINDOW\nSTOP "and this is the injection"'
    body, merged = se.prepare_source(source, {"room": "country_1", "text": nasty})
    assert merged["text"] == nasty
    program = se.parse_text(body)
    assert len(program) == 1, "the message became statements of its own"
    assert type(program[0]).__name__ == "ChatSendStmt"
    assert program[0].msg == "text", "the words were written into the line"


# ---------------------------------------------------------------------------
# what reaches the game
# ---------------------------------------------------------------------------
def test_a_message_reaches_the_game_as_bytes_and_not_as_a_lua_string():
    ev = _Ev(["ACT chat_sent"])
    assert chat_share.send_text(ev, "country_1", 'a "quoted" word') is True
    chunk = ev.chunks[0]
    assert "string.char(" in chunk
    assert '"quoted"' not in chunk, "the message was pasted into the Lua source"


def test_a_send_the_game_did_not_confirm_is_not_reported_as_sent():
    assert chat_share.send_text(_Ev([]), "country_1", "hello") is False
    assert chat_share.send_sticker(_Ev([]), "country_1", 35) is False


def test_a_coordinate_is_read_out_of_whatever_it_is_written_as():
    for spelling in ("600,400", "X:600 Y:400", "@[600,400|100]"):
        x, y, _server = chat_share.parse_coords(spelling)
        assert (x, y) == (600, 400), spelling
    try:
        chat_share.parse_coords("nothing here")
    except ValueError:
        return
    raise AssertionError("a string with no coordinate in it was accepted")


def test_the_statement_sends_what_the_variables_hold_and_reports_it():
    """The whole statement, against a VM that only answers — no game, no panel."""
    ev = _Ev()

    def reply(chunk, marker="ACT", settle=1.2, **_kw):
        ev.chunks.append(chunk)
        if "chat_sticker_sent" in chunk:
            return ["ACT chat_sticker_sent"]
        if "chat_point_sent" in chunk:
            return ["ACT chat_point_sent"]
        if "chat_sent" in chunk:
            return ["ACT chat_sent"]
        return ["ACT self uid=1000000000000001 srv=100 x=10 y=20"]

    ev.run = reply
    ctx = se.Context(hwnd=0)
    ctx.evaluator = ev
    ctx.vars.update({"room": "country_1", "text": 'say "hi"', "sticker": "",
                     "coords": "600,400", "server": "", "label": "here"})
    stmt = se.parse_text("CHAT_SEND ROOM room TEXT text STICKER sticker "
                         "COORDS coords SERVER server LABEL label")[0]
    se.Interpreter(ctx)._do_chat_send(stmt)
    assert ctx.vars["CHAT_SENT"] == 1
    assert any("__sendToRoom" in c for c in ev.chunks), "the message never left"
    assert any("SendSFSMessage" in c for c in ev.chunks), "the pin never left"
    # An empty sticker id is NO sticker — not sticker number nought.
    assert not any("TrySendSticker" in c for c in ev.chunks)


def test_a_part_the_game_did_not_confirm_leaves_the_send_marked_unsent():
    ev = _Ev([])                      # every chunk answers with silence
    ctx = se.Context(hwnd=0)
    ctx.evaluator = ev
    ctx.vars.update({"room": "country_1", "text": "hello"})
    stmt = se.parse_text("CHAT_SEND ROOM room TEXT text")[0]
    se.Interpreter(ctx)._do_chat_send(stmt)
    assert ctx.vars["CHAT_SENT"] == 0


# ---------------------------------------------------------------------------
# the recipe and its two front-ends
# ---------------------------------------------------------------------------
def test_the_recipe_declares_what_both_front_ends_pass():
    source = _RECIPE.read_text(encoding="utf-8")
    defaults, _body = se.extract_defaults(source)
    for name in ("room", "to", "text", "sticker", "coords", "server", "label"):
        assert name in defaults, f"the recipe cannot be told {name}"
    assert "# ru:" in source, "the recipe has no Russian title"


def test_the_tab_plays_the_recipe_instead_of_spawning_the_tool():
    source = _TAB.read_text(encoding="utf-8")
    assert "send_chat_message" in source, "the tab does not play the recipe"
    assert 'join(TOOLS, "chat_send.py")' not in source, "the tab still spawns the tool"
    assert "play_async(\"send_chat_message\"" in source, "the press is not a scenario"


def test_the_phone_has_the_two_sends_the_window_has():
    source = _TAB.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "web_press" in names, "the screen cannot answer anything"
    for key in ("chat.send", "chat.send_coords", "chat.send.prompt",
                "chat.send_coords.prompt", "chat.nothing_typed"):
        assert f'"{key}"' in source, f"the phone is missing {key}"
    # …and the window's own two buttons are still there, off the same keys.
    assert "_chat_send_text" in names and "_chat_send_coords" in names


def test_a_private_reply_answers_the_row_and_never_the_open_thread():
    """A DM card cannot be answered as a whole, and a press cannot name a strange room.

    The window's «open thread» belongs to whoever is at the machine. A phone replying
    into it would answer whoever that person happens to be reading — and outgoing chat
    cannot be unsent — so the row carries its own room, and a press naming a room this
    tab has never seen a message in is not a press this tab has.
    """
    source = _TAB.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_known_rooms" in names, "nothing checks the room a press names"
    assert 'if chat_type != "dm" and self._chat_room(chat_type):' in source, \
        "the DM card still offers a whole-card send"
    assert 'self._known_rooms(chat_type)' in source, "the named room is not checked"


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
