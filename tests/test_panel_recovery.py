r"""A deaf client gets restarted — and a healthy one never does (task #1259).

The state is the one `docs/research/server-link-status.md` describes: the process is
there, the window draws, every getter answers with yesterday's numbers, every send
returns `true`, and the server has not been on the other end since some hour of the
night. Two ways in — the server hangs up on an idle client, or the account is logged in
on another device and this session is kicked — and one cure, a restart.

On 2026-08-06 nothing did it: the client lost the server at 18:58, died at 20:02 and was
still dead two hours later. The watchdog only reacts to the PROCESS going away.

What is pinned here is the decision, because **a false positive costs a live client** and
that is the expensive direction to be wrong in:

  * a run of readings, not one — a reconnecting client briefly has the sockets of a dead
    one;
  * `unknown` is never a reason, and neither is `offline` (that is the watchdog's, and
    two things must not relaunch one client);
  * a cooldown, said out loud, so «waiting» never looks like «nothing is happening»;
  * and every act comes back with the words to say it, so a caller cannot restart a
    client without the log line explaining why.

No Tk, no game, no clock of its own — the time is passed in.

    C:\Python312\python.exe tests\test_panel_recovery.py
    python3 tests/test_panel_recovery.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import game_link  # noqa: E402

try:
    from panel.runtime import recovery as rec  # noqa: E402
except Exception as _exc:                      # noqa: BLE001
    rec, _WHY = None, _exc

LOST = "lost"
ONLINE = "online"
UNKNOWN = "unknown"
OFFLINE = "offline"


def _deaf(r, n, t0=1000.0, step=8.0):
    """Feed ``n`` consecutive lost readings; return every answer that was not None."""
    out = []
    for i in range(n):
        said = r.note(LOST, t0 + i * step)
        if said:
            out.append(said)
    return out


def test_one_bad_reading_is_not_a_reason():
    """A reconnecting client has, for a moment, exactly the sockets of a dead one."""
    r = rec.Recovery()
    assert _deaf(r, rec.STRIKES - 1) == []
    assert r.restarts == 0


def test_a_run_of_them_is():
    r = rec.Recovery()
    said = _deaf(r, rec.STRIKES)
    assert len(said) == 1 and said[0][0] == rec.ACT, said
    assert r.restarts == 1


def test_the_run_is_broken_by_any_other_answer():
    """Including `unknown` — «I cannot tell» must never accumulate into a restart."""
    for other in (ONLINE, UNKNOWN, OFFLINE):
        r = rec.Recovery()
        for i in range(rec.STRIKES - 1):
            r.note(LOST, 1000.0 + i)
        assert r.note(other, 1100.0) is None
        assert r.deaf_for == 0, other
        # …and the count has to start again from nothing.
        assert _deaf(r, rec.STRIKES - 1, t0=1200.0) == [], other
        assert r.restarts == 0, other


def test_offline_is_the_watchdogs_and_not_this_ones():
    """Two things must not relaunch one client."""
    r = rec.Recovery()
    for i in range(rec.STRIKES * 3):
        assert r.note(OFFLINE, 1000.0 + i * 8) is None
    assert r.restarts == 0


def test_a_second_restart_waits_out_the_cooldown_and_says_so_once():
    r = rec.Recovery()
    assert _deaf(r, rec.STRIKES)[0][0] == rec.ACT

    # Straight back to deaf: the run builds again, and the answer is a WAIT, once.
    said = _deaf(r, rec.STRIKES * 3, t0=1100.0)
    assert [k for k, _ in said] == [rec.HOLD], said
    assert said[0][1]["mins"] >= 1, said
    assert r.restarts == 1, "it restarted inside the cooldown"


def test_after_the_cooldown_it_restarts_again():
    r = rec.Recovery()
    _deaf(r, rec.STRIKES)
    later = 1000.0 + rec.COOLDOWN_SEC + 60
    said = _deaf(r, rec.STRIKES, t0=later)
    assert [k for k, _ in said] == [rec.ACT], said
    assert r.restarts == 2


def test_a_link_that_never_comes_back_is_retried_after_every_cooldown():
    """The latch that left a deaf client sitting for an hour (#1259, live).

    The first version said «too soon» once and then suppressed EVERYTHING, so a link
    that never recovered was restarted once and abandoned. Live: restarted 21:44:16,
    «жду 7 мин» at 21:47:53, and then nothing at all while the cooldown expired and the
    schedule failed every errand against the same dead client.
    """
    r = rec.Recovery()
    acts = [i for i in range(400)
            if (said := r.note(LOST, 1000.0 + i * 8, idle_sec=9999.0))
            and said[0] == rec.ACT]
    hours = 400 * 8 / 3600.0
    assert r.restarts >= int(hours * 3600 / rec.COOLDOWN_SEC) - 1, (
        f"{r.restarts} restarts in {hours:.1f} h at a {rec.COOLDOWN_SEC / 60:.0f} min "
        f"cooldown — it gave up")
    assert len(acts) == r.restarts


def test_nobody_is_thrown_out_of_a_game_they_are_playing():
    """The restart CLOSES the window. On 2026-08-06 at 21:44:16 it closed a live one.

    A person had logged in, the link dropped a couple of minutes later, and the panel
    «fixed» it by ending their session. An account being played is not an account in
    trouble.
    """
    r = rec.Recovery()
    said = [r.note(LOST, 1000.0 + i * 8, idle_sec=10.0) for i in range(20)]
    assert r.restarts == 0, "it restarted the client under somebody's hands"
    spoken = [s for s in said if s]
    assert spoken and spoken[0][0] == rec.BUSY, spoken
    assert len(spoken) == 1, f"it said it every poll: {spoken}"


def test_an_unreadable_idle_reading_never_lets_a_restart_through():
    """«Cannot tell» must not read as «nobody is there» — the gate only ever holds back."""
    r = rec.Recovery()
    for i in range(rec.STRIKES):
        r.note(LOST, 1000.0 + i * 8, idle_sec=None)
    assert r.restarts == 1, "None must behave exactly as it did before the gate existed"


def test_the_reason_a_restart_is_being_withheld_is_readable():
    """«Не перезапускается» must never be unexplained — the person asked for this."""
    r = rec.Recovery()
    for i in range(rec.STRIKES):
        r.note(LOST, 1000.0 + i * 8, idle_sec=10.0)
    assert r.state(1000.0)["held_by"] == "player"

    r2 = rec.Recovery()
    for i in range(rec.STRIKES):
        r2.note(LOST, 2000.0 + i * 8, idle_sec=9999.0)
    for i in range(rec.STRIKES):
        r2.note(LOST, 2100.0 + i * 8, idle_sec=9999.0)
    st = r2.state(2100.0)
    assert st["held_by"] == "cooldown" and st["cooldown_left"] > 0, st


def test_a_kick_is_the_same_act_but_not_the_same_sentence():
    """«Связь пропала» and «у вас забрали аккаунт» want different things done (#1259).

    The player saw the game's own «В ваш аккаунт был выполнен вход с другого
    устройства» — key `E100083` — which is what disproved the earlier conclusion that
    a kick leaves no trace in the client. The flag is the disconnect window
    (`lua_actions.kicked_out()`), and it earns its own line in the log.
    """
    r = rec.Recovery()
    said = [x for i in range(rec.STRIKES)
            if (x := r.note(LOST, 1000.0 + i * 8, idle_sec=9999.0, kicked=True))]
    assert [k for k, _ in said] == [rec.ACT_KICK], said
    assert r.restarts == 1 and r.state(1000.0)["kicks"] == 1


def test_a_kick_does_not_override_the_person_at_the_machine():
    """The gate is the same one: being kicked is not a licence to close a live window."""
    r = rec.Recovery()
    said = [x for i in range(rec.STRIKES * 2)
            if (x := r.note(LOST, 1000.0 + i * 8, idle_sec=10.0, kicked=True))]
    assert r.restarts == 0, "a kick walked straight through the player gate"
    assert [k for k, _ in said] == [rec.BUSY], said


def test_the_kick_flag_reads_a_window_and_fails_closed():
    """It may only ever ADD a reason — anything unreadable answers «no kick»."""
    import lua_actions

    expr = lua_actions.kicked_out()
    assert "UIDisconnect" in expr and "UICrossDisconnect" in expr, expr
    assert "pcall" in expr and "return 0" in expr, "it must not raise into the caller"


def test_a_healthy_client_is_never_touched_however_long_it_runs():
    r = rec.Recovery()
    for i in range(500):
        assert r.note(ONLINE, 1000.0 + i * 8) is None
    assert r.restarts == 0 and r.deaf_for == 0


def test_every_act_carries_the_words_to_explain_itself():
    """A restart with no line in the log is the fault this feature exists to fix."""
    r = rec.Recovery()
    for key, fmt in _deaf(r, rec.STRIKES):
        assert isinstance(key, str) and key.startswith("log."), key
        assert isinstance(fmt, dict), fmt


def test_the_state_both_front_ends_draw_is_numbers_and_not_words():
    r = rec.Recovery()
    _deaf(r, rec.STRIKES)
    st = r.state(1000.0 + 60)
    assert set(st) == {"deaf_for", "strikes", "restarts", "kicks", "cooldown_left",
                       "held_by"}, st
    assert st["restarts"] == 1 and st["strikes"] == rec.STRIKES
    assert 0 < st["cooldown_left"] <= rec.COOLDOWN_SEC
    for key, value in st.items():
        # Numbers, and one id — never a sentence. `held_by` names WHY a restart is
        # being withheld so each front-end can word it itself; it is "", "cooldown"
        # or "player", which is a key and not a language.
        assert isinstance(value, int if key != "held_by" else str), (key, value)
    assert st["held_by"] in ("", "cooldown", "player"), st


def test_the_lost_it_watches_for_is_the_shared_one():
    """Not a string of its own: the rule and the watcher must mean the same state."""
    assert LOST == game_link.LOST


def test_it_travels_to_BOTH_front_ends_out_of_ONE_object():
    """`CLAUDE.md`: an edit travels between the window and the web, in both directions.

    And here it must come from the SAME object, not two: a client being restarted round
    and round must not look like one that is simply working, and it must not look one
    way in the window and another on the phone.
    """
    host = (ROOT / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
    assert "self.recovery" in host, "the runtime does not hold it, so only one side can"

    api = (ROOT / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert "rt.recovery.state(" in api, "the phone is not sent the recovery state"

    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "self._rt.recovery.note(" in shell, "the window never feeds the decision"
    assert "_paint_recovery" in shell, "the window never draws it"
    # Neither side may keep its own copy of the bookkeeping.
    assert "Recovery()" not in shell, "the window built a second Recovery"

    page = (ROOT / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "state.game.recovery" in page, "the page ignores what the api sends"


def test_the_restart_it_asks_for_is_the_lifecycle_recipe():
    """Not a hand-rolled kill-and-launch: the panel presses scenarios (`CLAUDE.md`)."""
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    at = shell.index("def _recovery_check")
    body = shell[at:shell.index("\n    def ", at + 10)]
    assert 'play_async("restart_game")' in body, body[-400:]
    # …and only when the decision said ACT, never on the «too soon» answer.
    assert "recovery.ACT" in body


def test_both_its_sentences_are_in_every_shipped_locale():
    import json

    keys = (rec.ACT, rec.HOLD)
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in locale]
        assert not missing, f"{path.name}: {missing}"


def _main() -> int:
    if rec is None:
        print(f"  SKIP the runtime package will not import here: {_WHY}")
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
