r"""Nothing is driven into a client that has lost the server (task #1259).

The state this guards is the one `docs/research/server-link-status.md` describes and
nothing could act on: a client holding a socket the far end closed. It draws its window,
answers every Lua getter with the numbers it last received, and returns `true` from
every send while nothing arrives — so a recipe run against one presses all the way to
the end and fails on whatever it proves itself by. That failure reads as «the game
refused», and it is nothing of the kind.

#1259 spent a day on exactly that: five variants of a march message tried against a
server that was never asked, over a client the panel had already declared dead in its
own log two hours earlier. The rule that came out of it is that the link is READ before
anything is driven, and it is read from the same place the panel reads it —
`tools/lib/game_link.py`, which exists so that the layer which SENDS can ask the rule and
not only the layer which DRAWS it.

Two halves are pinned here:

  * the rule itself, on a stubbed socket table — a half-closed game socket is a loss, a
    live one beside it is not, the web ports are not the game, and loopback is not the
    server;
  * the gate, which must refuse a run ONLY on `lost`. `unknown` is a client 45 seconds
    into starting up, or a machine that will not attribute a foreign process's sockets;
    blocking on that would strand a healthy account behind a guess. The gate FAILS OPEN
    by construction — no psutil, no socket table, no client found all land in
    «cannot tell» — because a gate that is itself the fault is worse than no gate.

No Tk, no game, no Windows.

    C:\Python312\python.exe tests\test_engine_link_gate.py
    python3 tests/test_engine_link_gate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "src"))

import game_link  # noqa: E402

try:
    from lastwar_bot import script_engine  # noqa: E402
except Exception as _exc:                  # noqa: BLE001
    script_engine, _WHY = None, _exc


class _Addr:
    def __init__(self, ip, port):
        self.ip, self.port = ip, port


class _Conn:
    """One row of the socket table, as psutil hands it over."""

    def __init__(self, status, ip="203.0.113.7", port=10012, pid=1):
        self.status = status
        self.raddr = _Addr(ip, port) if ip else None
        self.pid = pid


# --- the rule ---------------------------------------------------------------
def test_a_half_closed_game_socket_and_nothing_else_is_a_loss():
    state, conn, dead = game_link.classify([_Conn("CLOSE_WAIT")])
    assert state == game_link.LOST and conn is None and dead == 1


def test_a_live_socket_beside_the_dead_ones_wins():
    """A healthy client keeps the losers of its gateway race half-closed all session."""
    state, conn, _ = game_link.classify(
        [_Conn("CLOSE_WAIT"), _Conn("CLOSE_WAIT"), _Conn("ESTABLISHED", "203.0.113.9")])
    assert state == game_link.ONLINE and conn == "203.0.113.9:10012"


def test_a_live_socket_of_another_service_does_not_win():
    """…and it stops winning at the point it stops being the SAME conversation (#1266).

    The gate in this file is the second thing the night of 2026-08-06 defeated: every
    `LUA` / `TAP` / `GAME` / `JUMP` was let through against a client whose game sockets
    were all half-closed, because the chat channel's one live socket answered for them
    (docs/research/server-link-status.md §2.2). The rule above is unchanged and still
    right — a live socket beats the dead ones BESIDE it. A live socket of somebody
    else's port is not beside them.
    """
    dead_game = [_Conn("CLOSE_WAIT", f"203.0.113.{n}", 10012) for n in range(1, 7)]
    state, conn, dead = game_link.classify(
        dead_game + [_Conn("ESTABLISHED", "198.51.100.4", 17935)])
    assert state == game_link.LOST, f"the control channel vouched for the game: {state}"
    assert dead == 6 and conn is None, (dead, conn)


def test_the_clients_loopback_pair_is_not_the_server():
    """It survives the server hanging up — counting it is the lie this rule stops."""
    state, _, _ = game_link.classify([_Conn("ESTABLISHED", "127.0.0.1", 63204)])
    assert state == game_link.UNKNOWN


def test_the_web_ports_are_not_the_game():
    for port in (80, 443):
        state, _, _ = game_link.classify([_Conn("ESTABLISHED", "203.0.113.7", port)])
        assert state == game_link.UNKNOWN, port


def test_time_wait_is_a_clean_reconnect_and_not_a_loss():
    state, _, dead = game_link.classify([_Conn("TIME_WAIT")])
    assert state == game_link.UNKNOWN and dead == 0


def test_saying_nothing_is_unknown_and_no_client_is_offline():
    assert game_link.classify([])[0] == game_link.UNKNOWN
    assert game_link.state_of([]) == game_link.OFFLINE


# --- the gate ---------------------------------------------------------------
#: Socket tables that classify into each verdict — fed to the gate instead of a stubbed
#: answer, so the REAL `classify` runs and the test cannot drift away from it (#1269
#: moved the gate's seam from `state_of` to the sockets themselves, because the gate now
#: has a second question to ask of them: is the live conversation the GAME's?).
def _sockets_for(state, confirmed=True):
    if state == game_link.LOST:
        return [_Conn("CLOSE_WAIT"), _Conn("CLOSE_WAIT")]
    if state == game_link.UNKNOWN:
        return []
    if confirmed:
        # the game's own conversation: the winner of the gateway race, losers behind it
        return [_Conn("ESTABLISHED"), _Conn("CLOSE_WAIT")]
    # one established conversation and no race — «на связи» that may not be the game
    return [_Conn("ESTABLISHED")]


def _gate(state, pid=4242, confirmed=True, session=True):
    """`Interpreter._link_lost()` with the socket table and the client's pid stubbed.

    ``confirmed`` is whether the live conversation carries the gateway race behind it;
    ``session`` is what the client itself would answer about being logged in — the two
    inputs #1269 added, because `online` alone stopped being enough.
    """
    interp = script_engine.Interpreter(script_engine.new_context(0, lambda _e: None))
    interp._tools_lib_on_path()
    real_sockets, real_port = game_link.sockets_of, interp._game_port
    real_confirm = script_engine.Interpreter._session_confirmed
    fake_client = type(sys)("game_client")
    fake_client.target_pid = lambda **kw: pid
    saved = sys.modules.get("game_client")
    sys.modules["game_client"] = fake_client
    game_link.sockets_of = lambda _pids: _sockets_for(state, confirmed)
    script_engine.Interpreter._session_confirmed = lambda _self: session
    interp._game_port = lambda: 47654
    try:
        return interp._link_lost()
    finally:
        game_link.sockets_of, interp._game_port = real_sockets, real_port
        script_engine.Interpreter._session_confirmed = real_confirm
        if saved is None:
            sys.modules.pop("game_client", None)
        else:
            sys.modules["game_client"] = saved


def test_the_cure_is_not_blocked_by_the_symptom():
    """`restart_game.md` must run ON a lost link — it is what FIXES one.

    The first version of this gate stood at the top of `run_action`, which refused every
    recipe including that one: `QUIT_GAME` / `CALL launch_game` / `ATTACH_GAME` send
    nothing to the server, they repair the client. The six-hourly restart timer would
    have stopped working in exactly the case it exists for. So the gate stands on the
    four primitives that reach the game, and the lifecycle ones are free by construction
    — this test reads the recipe rather than a list, so a step added to it is covered
    whether or not anybody remembers this file.
    """
    text = (ROOT / "src" / "lastwar_bot" / "actions" / "restart_game.md").read_text(
        encoding="utf-8")
    gated = (script_engine.GameSceneStmt, script_engine.JumpStmt,
             script_engine.TapStmt, script_engine.LuaStmt)
    statements = script_engine.parse_text(script_engine.prepare_source(text, {})[0])
    assert statements, "restart_game.md is empty"

    def walk(block):
        for stmt in block:
            yield stmt
            for attr in ("body", "then_body", "else_body", "steps"):
                inner = getattr(stmt, attr, None)
                if isinstance(inner, list):
                    yield from walk(inner)

    for stmt in walk(statements):
        assert not isinstance(stmt, gated), (
            f"restart_game.md now drives the game ({type(stmt).__name__}) — it would be "
            f"gated, and the cure would be blocked by the symptom")


def test_the_cure_runs_with_a_lost_link_and_with_no_client_at_all():
    """The two states it exists to get out of, asserted against the gate itself.

    Both are the same question from opposite ends: a client that answers but is not
    heard, and no client to answer at all. The recipe has to be runnable in each.
    """
    for state in (game_link.LOST, game_link.OFFLINE):
        assert _gate(state, pid=None) is None, f"blocked with no client, link={state}"
    # …and with a client that IS there and IS deaf, the gate speaks — but only for the
    # primitives that send, which `restart_game.md` (above) has none of.
    assert _gate(game_link.LOST, pid=4242) is not None


def test_the_gate_stands_on_the_driving_primitives_and_not_on_the_run():
    src = (ROOT / "src" / "lastwar_bot" / "script_engine.py").read_text(encoding="utf-8")
    where = src.index("def run_action")
    assert "_require_link" not in src[where:src.index("def ", where + 10)], (
        "the gate is back at the top of run_action — see the test above")
    for stmt in ("GameSceneStmt", "JumpStmt", "TapStmt", "LuaStmt"):
        at = src.index(f"case {stmt}():")
        assert "_require_link" in src[at:at + 200], f"{stmt} is not gated"
    # …and a READ is not a send: blinding the diagnosis is not the answer to a lie.
    at = src.index("case ReadLuaStmt():")
    assert "_require_link" not in src[at:at + 200], "reads must not be gated"


def test_the_link_is_read_once_per_run_not_once_per_press():
    interp = script_engine.Interpreter(script_engine.new_context(0, lambda _e: None))
    calls = []
    interp._link_lost = lambda: calls.append(1) or None
    for _ in range(5):
        interp._require_link(type("S", (), {"line_no": 1})())
    assert len(calls) == 1, f"the socket table was walked {len(calls)} times"


def test_a_lost_link_stops_the_run_and_says_why():
    said = _gate(game_link.LOST)
    assert said and "no longer talking to the game server" in said
    assert "server-link-status" in said, "the failure has to point at the write-up"


def test_online_and_unknown_both_let_the_run_through():
    """`unknown` is a starting client or an unreadable socket table — never a fault."""
    assert _gate(game_link.ONLINE) is None
    assert _gate(game_link.UNKNOWN) is None
    assert _gate(game_link.OFFLINE) is None


def test_no_client_at_all_is_not_the_gates_business():
    """«The game is not running» is the run's own error, in its own words."""
    assert _gate(game_link.LOST, pid=None) is None


def test_the_gate_never_becomes_the_fault():
    """Anything that raises inside it reads as «cannot tell», not as a loss."""
    interp = script_engine.Interpreter(script_engine.new_context(0, lambda _e: None))
    real = interp._game_port
    interp._game_port = lambda: (_ for _ in ()).throw(RuntimeError("no port"))
    try:
        assert interp._link_lost() is None
    finally:
        interp._game_port = real


# ---------------------------------------------------------------------------
# #1269 — «на связи» arrives before «готов играть»
#
# Live on 2026-08-07 the strip read `онлайн → …:17935` for three minutes while the
# game's own conversation did not exist yet: a starting client opens its control
# channel first. `classify` calls that ONLINE honestly, by its own definition, and the
# gate used to let everything through on it — errands into a client that is not in the
# game, reporting success for doing nothing. The fourth instance of one reading
# answering a different question (docs/research/server-link-status.md §5).
# ---------------------------------------------------------------------------
def test_the_gateway_race_is_what_confirms_a_link_is_the_games():
    """The one thing sockets CAN say: the winner of the race is the game's own talk."""
    raced = [_Conn("ESTABLISHED"), _Conn("CLOSE_WAIT")]
    assert game_link.online_is_confirmed(raced) is True
    # …one established conversation and nothing behind it: could be the game, could be
    # the control channel. Sockets cannot tell, and must not pretend to.
    assert game_link.online_is_confirmed([_Conn("ESTABLISHED")]) is False
    assert game_link.online_is_confirmed([]) is False


def test_a_confirmed_link_costs_no_round_trip():
    """The healthy path stays free — the client is not asked anything at all."""
    asked = []

    real = script_engine.Interpreter._session_confirmed
    script_engine.Interpreter._session_confirmed = lambda _s: asked.append(1) or True
    try:
        assert _gate(game_link.ONLINE, confirmed=True) is None
    finally:
        script_engine.Interpreter._session_confirmed = real
    assert asked == [], "a client with the race behind it was interrogated for nothing"


def test_an_unconfirmed_link_is_refused_when_the_client_says_it_is_not_playing():
    """THE BUG. `online` on the control channel, client still at the login screen."""
    said = _gate(game_link.ONLINE, confirmed=False, session=False)
    assert said, "an errand was let through into a client that is not in the game"
    assert "not in the game yet" in said, said


def test_an_unconfirmed_link_passes_once_the_client_confirms_the_session():
    """…and the same reading with the client answering is a pass, so the window is
    as short as the login is and never longer."""
    assert _gate(game_link.ONLINE, confirmed=False, session=True) is None


def test_unknown_still_fails_open_because_the_recovery_stands_on_it():
    """THE THING THAT MUST NOT BREAK (#1268, and the reason `unknown` exists).

    A client 45 seconds into starting up, and a machine that will not attribute a
    foreign process's sockets, both read `unknown`. Blocking on it would strand a
    healthy second account for ever, and counting it as a loss would restart a client
    that is merely young.
    """
    assert _gate(game_link.UNKNOWN, confirmed=False, session=False) is None
    assert _gate(game_link.UNKNOWN, confirmed=True, session=True) is None


def test_lost_is_still_lost_whatever_the_client_says_about_itself():
    """The confirmation may only ever ADD a refusal, never take one away: a stranded
    client answers every question with yesterday's numbers, including that one."""
    said = _gate(game_link.LOST, confirmed=False, session=True)
    assert said and "half-closed" in said, said


def test_the_confirmation_fails_open_on_every_way_of_not_knowing():
    """No daemon, no evaluator, a read that raised — all «could not tell», all a pass.

    Asserted against the real method rather than the stub, because this is the half
    that decides whether a gate can strand a healthy account.
    """
    interp = script_engine.Interpreter(script_engine.new_context(0, lambda _e: None))
    interp._tools_lib_on_path()
    import lua_client

    real_running = lua_client.is_running
    lua_client.is_running = lambda **kw: False          # nothing warm on the port
    try:
        assert interp._session_confirmed() is True
    finally:
        lua_client.is_running = real_running

    class _Boom:
        def run(self, *a, **kw):
            raise RuntimeError("daemon said no")

    interp.ctx.evaluator = _Boom()
    assert interp._session_confirmed() is True


def test_the_confirmation_never_builds_a_local_evaluator():
    """A gate may not be the most expensive thing in a run.

    `_evaluator()` would spin up a local `LuaEval` — seconds, plus an attach — for every
    scenario passing this gate, including the vision-only ones that are documented never
    to touch the daemon. So a cold port is a pass, without one being built.
    """
    interp = script_engine.Interpreter(script_engine.new_context(0, lambda _e: None))
    interp._tools_lib_on_path()
    import lua_client

    real_running, built = lua_client.is_running, []
    real_eval = script_engine.Interpreter._evaluator
    lua_client.is_running = lambda **kw: False
    script_engine.Interpreter._evaluator = lambda _s: built.append(1)
    try:
        assert interp._session_confirmed() is True
    finally:
        lua_client.is_running = real_running
        script_engine.Interpreter._evaluator = real_eval
    assert built == [], "the gate built an evaluator against a daemon that is not there"


def _main() -> int:
    if script_engine is None:
        print(f"  SKIP the engine will not import here: {_WHY}")
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

