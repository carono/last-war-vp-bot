r"""The gate that turns one press into a spam, run in a real Lua (task #1272).

«Автолут должен начинать спамить сбор ещё за пару секунд до готовности, очень часто.»
What makes that a loop rather than a press is one expression — the button's `count_lua`,
`lua_actions.secret_task_steals_pending()` — and what it answers is «press the SAME one
again». `TAP … xall` re-reads it between rounds, so it decides three things at once:

  * **when to start** — it never asks the tile's clock, so a target parked a couple of
    seconds before it matures is pressed from the first round. Pressing early is free:
    the server answers «ещё не готово», and the daily counter is the SERVER's number,
    reaching the client only on the success branch of the reply
    (`DispatchStealMessage:HandleMessage`), so a refusal spends nothing;
  * **whether to keep going** — «not ready yet» leaves the counter where it was, the
    gate stays 1, and the next round presses again;
  * **when to stop** — the counter moving is the reply landing, and nothing else counts.
    A `steal_sent` line means a frame left the client, which is not a robbery.

Those three are what this file pins, in an actual Lua VM with a stand-in for the
dispatch manager — no game, no daemon, no panel. The panel-side halves (which rows the
standing order aims at, and that a sent frame is not counted as a success) live in
`tests/test_panel_secret_tasks.py`.

    C:\Python312\python.exe tests\test_steal_spam_gate.py
    python3 tests/test_steal_spam_gate.py            # lupa is enough
"""
from __future__ import annotations

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


#: The client's own manager, as much of it as the gate touches: the queue the recipe
#: parks, the mark stamped when a target was armed, the daily counter and its cap.
_MANAGER = """
DataCenter = { ActDispatchTaskDataManager = {
  __lw_steal_queue = {},
  __lw_steal_mark = nil,
  _today = 0,
  _cap = 5,
  GetTodayStealNum = function(self) return self._today end,
  GetDispatchSetting = function(self, key) return self._cap end,
} }
-- The arming chunk hooks this to record what a refusal said, so the stand-in VM needs
-- one exactly as the client has one.
UIUtil = { ShowTipsId = function() end }
"""


def _vm(queued: int = 1, today: int = 0, cap: int = 5, mark=None):
    """A Lua VM holding one dispatch manager in a named state."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_MANAGER)
    m = lua.eval("DataCenter.ActDispatchTaskDataManager")
    m._today, m._cap = today, cap
    lua.execute("local q = DataCenter.ActDispatchTaskDataManager.__lw_steal_queue "
                "for i = 1, %d do q[i] = {uuid = i, server = 1} end" % queued)
    m.__lw_steal_mark = today if mark is None else mark
    return lua, m


def _gate(lua) -> int:
    """What `xall` reads between rounds: 1 = press again, 0 = stop."""
    return int(lua.eval(lua_actions.secret_task_steals_pending()))


def _needs_lua(name: str) -> bool:
    if lupa is None:
        print(f"       (skipped {name}: no lupa here — pip install lupa)")
        return False
    return True


def test_a_target_that_has_not_matured_is_pressed_anyway():
    """The gate never asks the tile's clock, which is what «за пару секунд до
    готовности» needs: the recipe is played inside the window and presses from the
    first round rather than waiting for the moment."""
    if not _needs_lua("an unmatured target is pressed"):
        return
    lua, _m = _vm(queued=1, today=0)
    assert _gate(lua) == 1
    # …and there is nothing in the expression that could have consulted a clock.
    text = lua_actions.secret_task_steals_pending()
    for clock in ("completionTime", "GetServerTime", "nowms", "expires"):
        assert clock not in text, (clock, "the machine's gate grew a clock")


def test_not_ready_yet_keeps_the_loop_pressing():
    """A refusal leaves the counter where it was — «ещё не готово» is not an answer the
    loop stops on, and it costs nothing to press again."""
    if not _needs_lua("«not ready» keeps pressing"):
        return
    lua, _m = _vm(queued=1, today=0)
    for round_no in range(1, 20):               # twenty refusals in a row
        assert _gate(lua) == 1, f"the loop gave up on round {round_no}"


def test_the_counter_moving_is_what_stops_it():
    """The only honest «it worked»: the daily number comes back in the reply, so it
    moves when the server took the tile and never merely because a frame was sent."""
    if not _needs_lua("the counter stops it"):
        return
    lua, m = _vm(queued=1, today=2)
    assert _gate(lua) == 1
    m._today = 3                                 # the reply landed
    assert _gate(lua) == 0, "the spam went on after the server confirmed"


def test_a_spent_day_presses_nothing_at_all():
    """The one thing that must stop it before the server does — otherwise the spam is a
    stream of up-frames the account cannot pay for. Confirmed live: with 5/5 gone the
    gate answered 0."""
    if not _needs_lua("a spent day presses nothing"):
        return
    lua, _m = _vm(queued=1, today=5, cap=5)
    assert _gate(lua) == 0


def test_an_empty_queue_presses_nothing():
    """`xall` over a queue the recipe never filled is a round trip that finds nothing."""
    if not _needs_lua("an empty queue presses nothing"):
        return
    lua, _m = _vm(queued=0)
    assert _gate(lua) == 0


def test_the_head_survives_its_own_press_and_the_pop_re_arms():
    """The press may repeat only because the head is left where it is; `queue_pop` is
    what moves on, and it re-stamps the mark so the next target is judged by its own
    counter rather than by the last one's."""
    if not _needs_lua("the head survives its press"):
        return
    lua, m = _vm(queued=2, today=1)
    lua.execute("CS = {UnityEngine = {Debug = {LogError = function(_) end}}} "
                "SFSNetwork = {SendMessage = function() end} "
                "MsgDefines = {DispatchSteal = 'hero.dispatch.steal'}")
    lua.execute(lua_actions.steal_next_secret_task())
    assert int(lua.eval(lua_actions.secret_task_queue_len())) == 2, \
        "the press dropped its own target, so it could never be repeated"

    m._today = 2                                 # the server took it
    assert _gate(lua) == 0
    lua.execute(lua_actions.secret_task_queue_pop())
    assert int(lua.eval(lua_actions.secret_task_queue_len())) == 1
    assert _gate(lua) == 1, "the next target was judged by the last one's mark"


def test_the_server_saying_the_tile_is_gone_stops_the_spam_at_once():
    """«Сервер отвечает, что забирать уже нечего — при таком сообщении спам-клик нужно
    прекращать» (#1272).

    Live, without this, one press read `TAP Rob a secret task xall -> 60 press(es)`: the
    counter never moved, so the loop ran to the button's cap asking a server that had
    answered the first question sixty times.
    """
    if not _needs_lua("«gone» stops the spam"):
        return
    for tip in lua_actions.STEAL_GONE_TIPS:
        lua, m = _vm(queued=1, today=0)
        assert _gate(lua) == 1
        m.__lw_steal_tip = tip                   # the refusal the server sent back
        assert _gate(lua) == 0, f"{tip} did not stop the loop"


def test_a_tip_nobody_has_met_leaves_the_loop_pressing():
    """The four are NAMED rather than «any tip at all»: the dispatch family holds no
    «ещё не готово», so an early press is answered by silence — and a message we have
    not met before must not be read as «give up» (#1272)."""
    if not _needs_lua("an unknown tip keeps pressing"):
        return
    lua, m = _vm(queued=1, today=0)
    m.__lw_steal_tip = "dispatch_des999"
    assert _gate(lua) == 1


def test_the_pop_says_which_of_the_three_happened():
    """taken / gone / unanswered, per target and by uuid — what the panel steers by: a
    tile the server calls gone comes off the list, one merely unanswered stays."""
    if not _needs_lua("the pop names the outcome"):
        return
    for tip, today, expected in ((None, 0, "unanswered"),
                                 ("dispatch_des042", 0, "gone"),
                                 (None, 1, "taken")):
        lua, m = _vm(queued=1, today=0)
        lua.execute("CS = {UnityEngine = {Debug = {LogError = function(s) "
                    "SAID = (SAID or '') .. tostring(s) .. '|' end}}}")
        m.__lw_steal_tip = tip
        m._today = today
        lua.execute(lua_actions.secret_task_queue_pop())
        said = lua.eval("SAID") or ""
        assert ("how=" + expected) in said, (expected, said)
        assert "uuid=1 " in said, said


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
