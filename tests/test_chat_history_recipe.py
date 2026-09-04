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
import re
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
_DEEP = _REPO / "src" / "lastwar_bot" / "actions" / "fetch_chat_history.md"
_VIEW = _REPO / "panel" / "web" / "app" / "src" / "views" / "ChatView.tsx"
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


def test_an_interactive_post_is_drawn_the_way_the_game_draws_it():
    """#2418, the person's report: «в чате альянса я вижу сообщения от игроков "msg", а в
    игре там нормальные сообщения».

    `getMsg()` answers the bare word `msg` for the interactive posts, and the rendered
    text is on `getMessageWithExtra()`. Measured live: of 328 messages the client held,
    189 render identically both ways and every one of the 139 that differ carries a
    non-zero `post`. So the POST decides, not a list of placeholder words.
    """
    rendered = "506c6179657231206a6f696e6564"          # invented, «Player1 joined»
    rec = chat_records.parse_record_line(
        _line(post="608", msg="6d7367", we=rendered))
    assert rec["msg"] == "Player1 joined", rec["msg"]


def test_a_plain_message_keeps_its_own_words():
    """The other half: a plain post (`post = 0`) is never replaced by the renderer's
    version, whatever that would have been — no measured plain message's rendering even
    extends its base, and a message rewritten by a renderer is a message nobody wrote."""
    rec = chat_records.parse_record_line(
        _line(post="0", msg="68656c6c6f", we="736f6d657468696e6720656c7365"))
    assert rec["msg"] == "hello", rec["msg"]


def test_the_placeholder_rule_still_holds_for_a_plain_post():
    """A `?` is a placeholder whatever the post says — that is what it was before."""
    rec = chat_records.parse_record_line(
        _line(post="0", msg="3f", we="61207368617265"))
    assert rec["msg"] == "a share", rec["msg"]


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


def test_the_store_is_written_even_with_nobody_looking():
    """The first live run read 278 messages and stored NOUGHT of them (#2064).

    A press off a phone reaches this tab before anybody has opened it: no `build()`,
    therefore no views and no pump, so records handed to the queue waited in it for
    ever. The store needs neither, and it is the durable half — so it is written first
    and the queue is fed only when there is something to draw into.
    """
    source = _TAB.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_file_backlog" in names, "nothing writes the backlog to the store"
    start = source.index("def _file_backlog")
    end = source.index("def _dm_append")
    body = source[start:end]
    assert "self._chat_store.append(record)" in body, "the backlog is not persisted"
    assert "if self._chat_trees:" in body, \
        "records are queued for a pump that may not be running"
    # …and a backlog that arrives before the store is open is HELD, never dropped:
    # a press that says 278 and keeps none of them looks exactly like one that worked.
    assert "_backlog_pending" in source, "an early backlog is dropped"
    assert '"log.chat.backlog_held"' in source, "an early backlog says nothing"


def test_the_phone_draws_the_conversation_and_skips_the_listing():
    """The chat screen is DRAWN, and the front-end that knows it drops the cards.

    A conversation is not a card of rows (#2064). The tab says `map: {kind: "chat"}`
    and marks the channel cards `drawn`, so the renderer that understands the kind
    paints the pane and skips them — and one that does not still shows the newest
    messages as a list rather than nothing at all.
    """
    tab = _TAB.read_text(encoding="utf-8")
    assert '"map": {"kind": "chat"}' in tab, "the chat screen is not drawn"
    assert '"drawn": True' in tab, "the channel cards are not marked as already drawn"
    view = (_REPO / "panel" / "web" / "app" / "src" / "views" / "ChatView.tsx")
    assert view.exists(), "the phone has no chat view"
    screen = (_REPO / "panel" / "web" / "app" / "src" / "views"
              / "ScreenView.tsx").read_text(encoding="utf-8")
    assert "view?.map?.kind === 'chat'" in screen, "the chat kind is not dispatched"
    assert "!(view?.map && c.drawn)" in screen, "a drawn card is still listed below"


def test_scrolling_up_reads_the_store_and_never_the_game():
    """Paging upwards is `web_data`, and nothing on that path may ask the game.

    This is the «read once, then LISTEN» rule as it applies to a gesture: a thumb
    flicking up a chat must not be able to turn itself into a stream of questions to
    the server. The page comes off this profile's own SQLite history, and going deeper
    than the store would mean `ChatRoomRequestHistoryMsg` — which is not sent.
    """
    view = (_REPO / "panel" / "web" / "app" / "src" / "views"
            / "ChatView.tsx").read_text(encoding="utf-8")
    assert "kind=page" in view, "the phone does not page the store"
    assert "ChatRoomRequestHistoryMsg" not in view, "the phone asks the server"
    # …and the scroll does not jump when the page lands above what is being read.
    assert "useLayoutEffect" in view and "held.current" in view,         "the pane does not hold the reader's place when older messages arrive"
    assert "el.scrollTop += el.scrollHeight - held.current" in view,         "the prepend is not compensated"


def test_a_lone_history_on_disk_names_its_own_character():
    """A phone opening the chat on a freshly started panel showed NOTHING (#2064).

    Paging needs to know whose history it is, and the tab learns that from the game the
    first time somebody opens it — which on a fresh panel nobody has. A profile that has
    ever collected chat holds one `chat_history_<uid>.db`, and where there is exactly one
    the character is not a guess. Two or more is left unanswered on purpose: a chat drawn
    under the wrong character's name is worse than an empty page.
    """
    source = _TAB.read_text(encoding="utf-8")
    assert "def _only_history_on_disk" in source, "a lone history does not name itself"
    start = source.index("def _only_history_on_disk")
    body = source[start:source.index("def _web_when")]
    assert "len(found) != 1" in body, "several characters are answered by a guess"
    assert 'self._chat_uid or "") or self._only_history_on_disk()' in source, \
        "the read store does not fall back to the history on disk"


def test_a_coordinate_in_a_message_is_a_link_on_the_phone_too():
    """Chat is where places arrive, and the window has made them clickable for years."""
    tab = _TAB.read_text(encoding="utf-8")
    assert "def _coord_parts" in tab, "chat prose is not marked for coordinates"
    assert "coordlinks.parts(text)" in tab,         "the marking does not go through the panel's one parser"


def test_a_profile_switch_closes_the_store_it_was_reading():
    """The tail of `on_profile_switch` had drifted below a `return` (#1221, fixed #2064).

    Everything after it was unreachable, so switching accounts stopped the reader and
    cleared the widgets and then went on paging the PREVIOUS character's history out of
    a store nobody had closed.
    """
    tree = ast.parse(_TAB.read_text(encoding="utf-8"))
    body = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "on_profile_switch":
            body = node
    assert body is not None, "the tab does not answer a profile switch"
    said = ast.dump(body)
    assert "_chat_store" in said and "_read_store" in said,         "a profile switch leaves the old character's store open"
    # …and nothing unreachable is left behind a `return` anywhere in the tab.
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for i, stmt in enumerate(node.body[:-1]):
            assert not isinstance(stmt, ast.Return),                 f"{node.name} has statements after its return"


def test_the_statement_is_documented():
    doc = _DSL.read_text(encoding="utf-8")
    assert "### `READ_CHAT" in doc, "READ_CHAT is not in docs/dsl.md"
    assert "ChatRoomRequestHistoryMsg" in doc, \
        "the doc does not say what the statement refuses to ask"


# ---------------------------------------------------------------------------
# the deeper read — the one place the chat talks to the SERVER (#2064)
# ---------------------------------------------------------------------------
def test_the_deep_read_is_a_recipe_of_its_own():
    text = _DEEP.read_text(encoding="utf-8")
    assert "ARGS room" in text, "the deep read does not declare the room it names"
    assert "ChatRoomRequestHistoryMsg" in text, "it does not make the request"
    assert "READ_CHAT" in text, "it asks and then never reads what arrived"
    body, _merged = se.prepare_source(text, {"room": "country_1", "limit": 40})
    prog = se.parse_text(body)
    assert prog, "the recipe does not parse"


def test_the_deep_read_asks_backwards_only():
    """`sort = 1` brought nothing live; asking with it would be a round trip for none."""
    text = _DEEP.read_text(encoding="utf-8")
    call = [ln for ln in text.splitlines() if "ChatRoomRequestHistoryMsg" in ln
            and not ln.lstrip().startswith("#")]
    assert call, "nothing in the body makes the request"
    for line in call:
        assert '", 0)' in line.replace(" ,", ","), \
            f"the request is not the backwards one: {line.strip()[:90]}"


def test_the_deep_read_is_gated_on_the_end_the_game_remembers():
    text = _DEEP.read_text(encoding="utf-8")
    assert "GetIsChatHistoryEnd" in text, \
        "nothing reads the game's own «that is all there was»"
    assert "history_end" in text, "the recipe answers with no end flag"


def test_the_panel_keeps_the_person_s_rules_for_the_ask():
    """Store first, a person's scroll, one at a time, and the end remembered."""
    text = _TAB.read_text(encoding="utf-8")
    assert "_ask_server_for_older" in text, "the press has nowhere to land"
    assert "_deep_busy" in text, "nothing stops one scroll making several requests"
    assert "_history_end" in text, "«there is nothing earlier» is not remembered"
    tree = ast.parse(text)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "_ask_server_for_older"]
    assert fn, "the method is gone"
    body = ast.dump(fn[0])
    assert "fetch_chat_history" in body, "the ask does not play the recipe"
    assert "arm(" not in body and "after(" not in body, \
        "the ask is on a clock — it must ride a person's scroll and nothing else"


def test_a_silent_answer_ends_the_room_only_the_second_time():
    """The game does not always set its own end flag — measured live on the world room.

    So silence is read as the end too, and the reason it takes TWO of them is that one
    empty answer is also what a reply slower than the recipe's wait looks like.
    """
    text = _TAB.read_text(encoding="utf-8")
    assert "_deep_empty" in text, "an empty answer is not counted at all"
    assert 'self._as_int(got.get("held_after"))' in text, \
        "«did the server send anything» is measured by the store rather than by THIS "\
        "room's own list — a word in another channel then reads as history arriving"
    assert 'self._deep_empty.get(room, 0) >= 2' in text, \
        "one slow reply can close a room's history for the rest of the session"


def test_the_read_grows_with_the_room_it_is_reading():
    """`READ_CHAT` brings home the NEWEST `limit` of a room and the fetched messages
    arrive at the OLD end — so a fixed limit stops carrying them across the moment the
    client holds more than that. Measured live: `got: 100, filed: 0`, three in a row."""
    text = _TAB.read_text(encoding="utf-8")
    assert "_deep_hold" in text, "the limit does not follow the room's own list"
    assert "DEEP_CEILING" in text, "the growing limit has no ceiling"


def test_the_page_says_whether_the_server_is_worth_asking():
    text = _TAB.read_text(encoding="utf-8")
    assert '"server": bool(asked)' in text, \
        "the page does not tell the front-end whether an ask is still worth making"


def test_the_phone_reads_the_store_before_it_reaches_the_game():
    """The scroll handler must exhaust `more` before it can call the deep read."""
    text = _VIEW.read_text(encoding="utf-8")
    assert "deeper()" in text, "the phone cannot ask at all"
    assert "if (more && !busy) void older()" in text, "the store is no longer read first"
    assert "else if (!more && server && !deep && !busy) void deeper()" in text, \
        "the game is asked without the store having run out"
    assert "chat.history_end" in text, "nothing tells the reader the history has ended"


def test_what_arrives_while_reading_history_is_counted_not_thrown_at_the_reader():
    """Both halves of the person's second rule, and they are opposite behaviours.

    At the bottom: a new message appends and the view follows it. Up in the history:
    the message still goes in — scrolling down must find it in place — but the view
    stays put and a counter says how many are below.
    """
    text = _VIEW.read_text(encoding="utf-8")
    assert "if (!glued.current) setUnseen((n) => n + added.length)" in text, \
        "nothing counts what arrived while the reader was up in the history"
    assert "chat.new_below" in text, "the reader is never told there is anything below"
    assert "if (glued.current) el.scrollTop = el.scrollHeight" in text, \
        "a new message no longer follows the reader who IS at the bottom"


def test_a_busy_game_does_not_end_the_recording():
    """The ear died on a busy VM, and dying is what made it invisible (#2064).

    The panel holds the client's Lua VM and hands it out one caller at a time, so a
    scenario in the middle of a run makes the reader's drain fail. That call was
    unguarded, so the failure ended the PROCESS: the panel wrote «монитор завершён»,
    the tick went off and nothing was recorded until somebody noticed — and a gap in a
    chat history looks exactly like a quiet hour. A missed drain must cost seconds.
    """
    src = (_REPO / "tools" / "chat_reader.py").read_text(encoding="utf-8")
    assert "def _install()" in src, "the hook cannot be put back after a client went away"
    assert "installed = _install()" in src, "the hook is never installed"
    assert "except Exception as exc:        # noqa: BLE001 -- a busy VM, not a bug" in src, \
        "a drain that fails still ends the recording"
    assert "installed = False\n                continue" in src, \
        "a failed drain neither re-installs the hook nor waits for the next round"


def test_the_ear_is_a_switch_the_phone_can_reach():
    """A history that has stopped growing looks exactly like a quiet chat (#2064).

    Nothing is filed while the reader child is stopped, and its only switch was the
    window's tick — so a phone could read a chat that had stopped recording hours before
    and see nothing saying so. The switch travels, and it is ONE state with two views:
    both move `_chat_var` through the same `_toggle_chat`, so neither front-end can start
    a second reader or show the opposite of what is running.
    """
    tab = _TAB.read_text(encoding="utf-8")
    assert '"listening": bool(self._chat_var.get())' in tab, \
        "the phone is not told whether the monitor is running"
    assert 'if action == "listen":' in tab, "the phone has no way to start the monitor"
    assert "def _set_listening(self" in tab, \
        "the two front-ends do not move one state"
    assert "self._chat_var.set(on)" in tab and "self._toggle_chat()" in tab, \
        "the switch moves the tick without doing what moving it does"
    # …and the window keeps its own tick over the same variable.
    assert "variable=self._chat_var, command=self._toggle_chat" in tab, \
        "the window lost the checkbox the phone now mirrors"

    view = _VIEW.read_text(encoding="utf-8")
    assert "action: 'listen'" in view, "the phone's chip presses nothing"
    assert "chat.monitor" in view, "the chip has no word on it"
    assert "useEffect(() => setEar(listening), [listening])" in view, \
        "the chip never catches up with what the panel really did"


# ---------------------------------------------------------------------------
# a drawn screen draws ITSELF and never its neighbour
# ---------------------------------------------------------------------------
def _drawn_kinds() -> dict:
    """Every `map: {"kind": ...}` a tab hands the phone, by the file that sends it."""
    found = {}
    for path in sorted((_REPO / "panel" / "tabs").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for kind in re.findall(r'"map":\s*\{"kind":\s*"([a-z_]+)"', text):
            found.setdefault(kind, set()).add(path.name)
    return found


def test_two_screens_never_claim_one_drawing():
    """A kind belongs to ONE tab. Two tabs on one kind is two pages drawn as one."""
    kinds = _drawn_kinds()
    assert "chat" in kinds and "world" in kinds, f"the drawn screens moved: {kinds}"
    doubled = {k: sorted(v) for k, v in kinds.items() if len(v) > 1}
    assert not doubled, f"one drawing claimed by several tabs: {doubled}"
    assert kinds["chat"] == {"chat.py"}, f"the chat drawing moved: {kinds['chat']}"
    assert kinds["world"] == {"worldview.py"}, f"the map drawing moved: {kinds['world']}"


def test_the_renderer_matches_every_drawing_by_name():
    """No «there is a map, so paint the world» fallback.

    That default is what makes two different screens one: any screen sending a kind
    the front-end does not know would be painted as the world map, and the next drawn
    screen anybody adds would silently become the map as well.
    """
    text = (_REPO / "panel" / "web" / "app" / "src" / "views" / "ScreenView.tsx").read_text(
        encoding="utf-8")
    assert "view?.map?.kind === 'chat' ? (" in text, "the chat is not matched by name"
    assert "view?.map?.kind === 'world' ? (" in text, \
        "the world map is drawn for ANY map kind — that is the two-screens-in-one bug"
    assert ") : view?.map ? (" not in text, "the catch-all fallback is back"


# ---------------------------------------------------------------------------
# the send box a thumb can actually reach (#2064)
# ---------------------------------------------------------------------------
def test_no_large_viewport_units_are_left_in_the_layout():
    """`vh` on a phone is the viewport WITHOUT the browser's furniture.

    Anything measured in it is taller than the screen really is, and whatever follows
    it goes under the bottom bar. It cost the modal once (#2061) and the chat once
    (#2064, «футер налезает на окно чата»); the units are `dvh` everywhere now.
    """
    css = (_REPO / "panel" / "web" / "app" / "src" / "app.css").read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)          # prose may name the trap
    bad = re.findall(r":[^;{}]*?\b\d+(?:\.\d+)?vh\b", body)
    assert not bad, f"large-viewport units left in the layout: {bad}"


def test_the_send_box_stands_above_the_bottom_bar():
    css = (_REPO / "panel" / "web" / "app" / "src" / "app.css").read_text(encoding="utf-8")
    assert "--navh:" in css, "the bar's height is not named anywhere"
    assert "padding-bottom: var(--navh)" in css, \
        "the page's clearance for the bar is a number of its own again"
    box = css[css.index(".chatbox {"):css.index(".chatbox {") + 260]
    assert "position: sticky" in box and "bottom: calc(var(--navh)" in box, \
        "the send box does not stand above the bar"


def test_the_pane_is_measured_and_not_guessed():
    view = _VIEW.read_text(encoding="utf-8")
    assert "visualViewport" in view, \
        "nothing follows the viewport the keyboard leaves behind"
    assert "el.style.height" in view, "the pane's height is still a share of something"


def test_every_locale_has_the_keys():
    wanted = ("chat.history.load", "log.chat.backlog", "log.chat.backlog_none",
              "log.chat.backlog_reading", "log.chat.backlog_held",
              "chat.older_from_game", "chat.history_end", "chat.deep_busy",
              "chat.deep_failed", "log.chat.deep_asking", "log.chat.deep_done",
              "chat.new_below")
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
