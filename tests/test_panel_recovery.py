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

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import game_link  # noqa: E402

try:
    from panel.runtime import daemon as daemonmod  # noqa: E402
    from panel.runtime import recovery as rec  # noqa: E402
except Exception as _exc:                      # noqa: BLE001
    rec, daemonmod, _WHY = None, None, _exc

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


def test_a_kick_cannot_override_offline_either():
    """No process, nothing on screen — so nothing can be showing a modal (#1270).

    The kick is deaf on its own whatever the SOCKETS say; `offline` is not a socket
    reading, it is «there is no client», and that one stays the watchdog's.
    """
    r = rec.Recovery()
    for i in range(rec.KICK_STRIKES * 3):
        assert r.note(OFFLINE, 1000.0 + i * 8, idle_sec=9999.0, kicked=True) is None
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
    (`lua_actions.kick_tip()`, judged by `game_kick`), and it earns its own line.
    """
    r = rec.Recovery()
    said = [x for i in range(rec.STRIKES)
            if (x := r.note(LOST, 1000.0 + i * 8, idle_sec=9999.0, kicked=True))]
    assert [k for k, _ in said] == [rec.HOLD_KICK], said
    # …and the same distinction on the far side of the kick's own wait (#1291): a
    # hang-up and a stolen account are one act and two events, and the log has to say
    # which it was.
    later = 1000.0 + rec.KICK_HOLD_SEC + 8
    assert r.note(LOST, later, idle_sec=9999.0, kicked=True) == (rec.ACT_KICK, {})
    assert r.restarts == 1 and r.state(later)["kicks"] == 1


def test_a_kick_does_not_override_the_person_at_the_machine():
    """The gate is the same one: being kicked is not a licence to close a live window."""
    r = rec.Recovery()
    said = [x for i in range(rec.STRIKES * 2)
            if (x := r.note(LOST, 1000.0 + i * 8, idle_sec=10.0, kicked=True))]
    assert r.restarts == 0, "a kick walked straight through the player gate"
    assert [k for k, _ in said] == [rec.BUSY], said


def test_the_kick_flag_reads_a_window_and_fails_closed():
    """It may only ever ADD a reason — anything unreadable answers «no dialog»."""
    import lua_actions

    expr = lua_actions.kick_tip()
    # The window it asks for, by name — watched live, neither of the two disconnect
    # windows this once named ever opens, and the stack cannot see the one that does
    # (`DontPushWindowStack`). Only `IsWindowOpen` on the generic tip finds it.
    assert "UICommonMessageTip" in expr and "IsWindowOpen" in expr, expr
    assert "pcall" in expr and "return ''" in expr, "it must not raise into the caller"
    # …and the OPEN check must come before the text is fetched: `GetWindow` hands back
    # a closed window with its last message still on it (#1270).
    assert expr.index("IsWindowOpen") < expr.index("GetWindow"), expr


def test_a_kick_is_deaf_even_while_the_sockets_read_online():
    """THE FIFTH FORM (#1270), as a decision.

    On 2026-08-07 the account was taken by another device and the client kept ONE
    established conversation of the six it had — so `classify` answered `online,
    dead=0`, honestly. The kick flag was only ever consulted while the link already read
    `lost`, so nothing asked it, and the panel played timers into a client that could
    not send from 05:13 to 07:27.

    A live socket and the kick modal together mean the client cannot be played. The
    patience is the kick's own and shorter than the link's: this is the game's own
    sentence, not an inference off a socket table.

    The ACT is now on the far side of the wait (#1291) — what is pinned here is that the
    state is REACHED at all through a link that reads perfectly online.
    """
    r = rec.Recovery()
    said = [x for i in range(rec.KICK_STRIKES)
            if (x := r.note(ONLINE, 1000.0 + i * 8, idle_sec=9999.0, kicked=True))]
    assert [k for k, _ in said] == [rec.HOLD_KICK], said
    later = 1000.0 + rec.KICK_HOLD_SEC + 8
    assert r.note(ONLINE, later, idle_sec=9999.0, kicked=True) == (rec.ACT_KICK, {})
    assert r.restarts == 1 and r.state(later)["kicks"] == 1
    assert rec.ACT_KICK in rec.RESTARTS, "announced and never performed — the #1259 bug"


def test_one_kick_reading_is_not_a_reason_either():
    """A single unlucky poll acts on nothing, exactly like a single lost reading."""
    r = rec.Recovery()
    assert r.note(ONLINE, 1000.0, idle_sec=9999.0, kicked=True) is None
    assert r.restarts == 0


def test_a_kick_that_clears_takes_its_run_with_it():
    """The modal going away is the account coming back — nothing is owed to it."""
    r = rec.Recovery()
    r.note(ONLINE, 1000.0, idle_sec=9999.0, kicked=True)
    r.note(ONLINE, 1008.0, idle_sec=9999.0, kicked=False)
    assert r.note(ONLINE, 1016.0, idle_sec=9999.0, kicked=True) is None
    assert r.restarts == 0


def test_a_kick_is_left_alone_for_a_quarter_of_an_hour():
    """THE CURE FOR A KICK IS NOT THE CURE FOR A HANG-UP (#1291): wait first.

    Naming the state was only half of it. A kick has an AUTHOR — somebody logged the
    account in on a phone or another machine — and taking it back thirty seconds later
    throws them out, whereupon their client throws this one out again. Live on
    2026-08-08 that was three restarts in a row, `launch_game` timing out on each, and
    the daemon dying with every client, while the person was simply trying to play.

    So the kick is SAID at once (with the minutes left) and ACTED ON at the far end of
    the wait, whereupon the ordinary scheme resumes untouched.
    """
    r = rec.Recovery()
    t0 = 1000.0
    # The status poll's own eight seconds, right through the wait and out the far side:
    # the hold is armed on the second of them, so the run has to outlast t0 + 8 + hold.
    said = [x for i in range(8 + int(rec.KICK_HOLD_SEC // 8))
            if (x := r.note(ONLINE, t0 + i * 8, idle_sec=9999.0, kicked=True))]
    keys = [k for k, _ in said]
    at = keys.index(rec.ACT_KICK)
    # One sentence when the wait starts, nothing at all for a quarter of an hour, and
    # then the restart. (Past it the modal is still up, so a second episode arms — which
    # is the next test's business.)
    assert keys[:at + 1] == [rec.HOLD_KICK, rec.ACT_KICK], said
    assert said[0][1]["mins"] == int(rec.KICK_HOLD_SEC // 60), said[0]
    assert r.restarts == 1, "the client was touched inside its own wait"
    # …and while it lasts the strip has a countdown to draw rather than silence.
    r2 = rec.Recovery()
    for i in range(rec.KICK_STRIKES):
        r2.note(ONLINE, t0 + i * 8, idle_sec=9999.0, kicked=True)
    st = r2.state(t0 + 60)
    assert st["held_by"] == "kick" and 0 < st["kick_hold_left"] <= rec.KICK_HOLD_SEC, st


def test_the_wait_holds_even_when_the_link_goes_with_it():
    """A kick usually takes the sockets too, and then it looks like an ordinary loss.

    The wait is a DEADLINE, not a streak of readings: once a kick has been seen, three
    `lost` readings behind it must not be the thing that restarts the client anyway.
    That is the hole a hold hung off `kicked` would have left, and it is the ordinary
    shape of a kick rather than an exotic one.
    """
    r = rec.Recovery()
    t0 = 1000.0
    for i in range(rec.KICK_STRIKES):
        r.note(ONLINE, t0 + i * 8, idle_sec=9999.0, kicked=True)
    said = [x for i in range(20)
            if (x := r.note(LOST, t0 + 100 + i * 8, idle_sec=9999.0, kicked=False))]
    assert [k for k, _ in said if k in rec.RESTARTS] == [], said
    assert r.restarts == 0


def test_the_account_coming_back_ends_the_wait():
    """ONLINE **and** no modal is the account being ours again — nothing is owed then.

    Deliberately not «the modal went away»: a client that merely went offline mid-wait
    proves nothing, and clearing on that would hand it straight to the watchdog.
    """
    r = rec.Recovery()
    t0 = 1000.0
    for i in range(rec.KICK_STRIKES):
        r.note(ONLINE, t0 + i * 8, idle_sec=9999.0, kicked=True)
    assert r.kick_hold_left(t0 + 60) > 0
    r.note(OFFLINE, t0 + 68, idle_sec=9999.0, kicked=False)
    assert r.kick_hold_left(t0 + 68) > 0, "a client that went away lost its own wait"
    # …and the strip goes on saying so. A blank one here reads as «ничего не
    # происходит» through the fifteen minutes when something deliberately is.
    assert r.state(t0 + 68)["held_by"] == "kick", r.state(t0 + 68)
    r.note(ONLINE, t0 + 76, idle_sec=9999.0, kicked=False)
    assert r.kick_hold_left(t0 + 76) == 0


def test_a_second_kick_buys_its_own_wait_and_a_spent_one_does_not_repeat():
    """The wait is per EPISODE: armed once, honoured once, and re-armed for the next.

    Both halves are the bug: an expired deadline that re-arms on the next reading (the
    modal is still on screen) waits for ever and never restarts, and one that never
    re-arms lets the second kick be answered in thirty seconds — which is the fight
    this whole thing exists to stay out of.
    """
    r = rec.Recovery()
    t0 = 1000.0
    for i in range(rec.KICK_STRIKES):
        r.note(ONLINE, t0 + i * 8, idle_sec=9999.0, kicked=True)
    first = t0 + rec.KICK_HOLD_SEC + 8
    assert r.note(ONLINE, first, idle_sec=9999.0, kicked=True)[0] == rec.ACT_KICK
    # Still taken: a fresh episode, which earns a fresh run of readings and then a
    # fresh wait — never a second restart on the strength of the first one's.
    said = [x for i in range(1, rec.KICK_STRIKES + 1)
            if (x := r.note(ONLINE, first + i * 8, idle_sec=9999.0, kicked=True))]
    assert [k for k, _ in said] == [rec.HOLD_KICK], said
    at = first + rec.KICK_STRIKES * 8
    assert r.kick_hold_left(at) > 0, "the second kick was not given its own wait"
    assert r.restarts == 1


def test_how_long_to_wait_is_a_setting_and_zero_is_the_old_behaviour():
    """The threshold is a person's decision about another person, not a constant.

    Fifteen minutes is only the default: the panel writes `kick_hold_min` into it on
    every status poll, and 0 restores «restart at once» for whoever wants it back.
    """
    assert rec.KICK_HOLD_SEC == 900.0, "the default is fifteen minutes"
    import json

    defaults = (ROOT / "panel" / "runtime" / "settings.py").read_text(encoding="utf-8")
    assert '"kick_hold_min": 15' in defaults, "the wait is not a profile setting"
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "kick_hold_sec" in shell and "kick_hold_min" in shell, \
        "the setting never reaches the decision"
    page = (ROOT / "panel" / "tabs" / "settings.py").read_text(encoding="utf-8")
    assert '"kick_hold_min"' in page, "there is no field to type it in"
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in ("opt.kick_hold_min", "opt.kick_hold_min.hint")
                   if k not in locale]
        assert not missing, f"{path.name}: {missing}"

    r = rec.Recovery()
    r.kick_hold_sec = 0.0
    said = [x for i in range(rec.KICK_STRIKES)
            if (x := r.note(ONLINE, 1000.0 + i * 8, idle_sec=9999.0, kicked=True))]
    assert [k for k, _ in said] == [rec.ACT_KICK], said


def test_every_thing_that_can_put_a_client_back_asks_the_wait():
    """A wait one of the three honours is not a wait at all (#1291).

    Three of them can relaunch: this decision, the process watchdog, and the
    `restart_game` errand — which `Schedule.gate` deliberately lets through precisely
    when the game looks down, i.e. exactly the state a kicked client ends up in. The
    user's report was the watchdog and the recovery each doing their own thing a minute
    apart.
    """
    watchdog = _shell_method("_watchdog_check")
    assert "kick_hold_left" in watchdog, "the watchdog relaunches inside the wait"
    assert "log.game.kick_hold" in watchdog, "…and would do it silently"
    gate = (ROOT / "panel" / "runtime" / "schedule.py").read_text(encoding="utf-8")
    assert "kick_hold_left" in gate, "the restart_game errand ignores the wait"
    assert "timers.log.skip_kick" in gate, "…and would be dropped without a word"


class _Watchdog:
    """The shell's `_watchdog_check`, run against a stub — no Tk, no game, no clock.

    The method is compiled out of `panel/__main__.py` rather than copied, so a change
    to the real one is what this exercises.
    """

    STRIKES = 2

    def __init__(self, hold_left=lambda now: 0, cooldown=300.0):
        self._game_gone = 0
        self._game_was_up = True
        self._watchdog_last = 0.0
        self._wd_held = ""
        self.said: list[tuple[str, dict]] = []
        self.launched: list[float] = []
        self.now = 1000.0
        self._hold_left = hold_left
        env = {"WATCHDOG_STRIKES": self.STRIKES,
               "WATCHDOG_COOLDOWN_SEC": cooldown,
               "time": self}
        exec(compile("class _S:\n    " + _shell_method("_watchdog_check"),
                     "<watchdog>", "exec"), env)
        self.check = env["_S"]._watchdog_check.__get__(self)

    # the stub's own surface, standing in for the panel's
    def time(self) -> float:                       # `time.time()` inside the method
        return self.now

    def _say(self, _tag, key, **fmt) -> None:
        self.said.append((key, fmt))

    def _opt_bool(self, _name) -> bool:
        return True

    def play_async(self, name) -> None:
        assert name == "launch_game", name
        self.launched.append(self.now)

    def kick_hold_left(self, now) -> int:
        return self._hold_left(now)

    @property
    def _rt(self):                                 # `self._rt.recovery` / `_rt.play_async`
        return self

    @property
    def recovery(self):
        return self

    def poll(self, running: bool = False, step: float = 8.0) -> None:
        self.check(running)
        self.now += step


def test_the_watchdog_comes_back_after_the_wait_it_honoured():
    """A hold must suppress the ACT while it lasts, and nothing after it (#1291).

    Live on 2026-08-08 it suppressed the watchdog for good. The method acted on the
    EXACT strike (`self._game_gone != WATCHDOG_STRIKES`), so the poll on which a hold
    spoke was the only poll that ever looked: the wait was armed at 07:55:06, the
    process went away at 08:07:42 and said «жду 3 мин», the wait ran out at 08:10:06 —
    and nothing put the client back until a person pressed «Запустить» at 08:38:25.

    Half an hour of a farming account sitting closed, out of a fix whose entire subject
    is a client that must come back BY ITSELF once the other device is done with it.
    """
    until = 1000.0 + 900.0
    w = _Watchdog(hold_left=lambda now: max(0, int(until - now)))
    for _ in range(4):                             # the process goes, the wait holds
        w.poll()
    assert not w.launched, "the wait was walked straight through"
    assert [k for k, _ in w.said] == ["log.game.gone", "log.game.kick_hold"], w.said

    while w.now < until:                           # …quietly, for the whole quarter hour
        w.poll()
    assert not w.launched, "the wait was walked through later on"
    assert len(w.said) == 2, "a wait said once a poll is a log nobody can read"

    w.poll()                                       # and the poll after it is over
    assert w.launched, "the wait spent the watchdog's only attempt"
    assert w.said[-1][0] == "log.game.watchdog_relaunch", w.said


def test_the_watchdog_retries_on_its_cooldown_rather_than_once():
    """«перезапуск был N мин назад — жду» has to be a promise, not a farewell.

    The same `!=` made the cooldown branch unreachable inside one death: it could only
    be reached on the exact strike, and a relaunch had already been spent by then. So a
    client that died while starting up was told it would be retried and never was.
    """
    w = _Watchdog(cooldown=300.0)
    w.poll(); w.poll()
    assert len(w.launched) == 1, w.launched
    for _ in range(20):                            # 160 s of it — inside the cooldown
        w.poll()
    assert len(w.launched) == 1, "the cooldown between relaunches is not kept"
    assert [k for k, _ in w.said].count("log.game.watchdog_hold") == 1, w.said

    while len(w.launched) < 2 and w.now < 1000.0 + 900.0:
        w.poll()
    assert len(w.launched) == 2, "the retry the cooldown promises never comes"
    assert w.launched[1] - w.launched[0] >= 300.0, w.launched


def test_a_client_that_comes_back_forgets_what_was_being_waited_for():
    """Otherwise the next death inherits the last one's silence."""
    w = _Watchdog(hold_left=lambda now: 900)
    w.poll(); w.poll()
    assert w._wd_held == "kick", w._wd_held
    w.poll(running=True)
    assert w._wd_held == "" and w._game_gone == 0, (w._wd_held, w._game_gone)
    assert w.said[-1][0] == "log.game.back", w.said


def test_the_wait_is_drawn_on_both_front_ends():
    """`CLAUDE.md`: an edit travels between the window and the web, in both directions.

    And this one has to: the person reading the phone is very often the person who took
    the account. «Жду 14 мин» is the answer to both «why did my client stop» and «when
    does the bot come back».
    """
    paint = _shell_method("_paint_recovery")
    assert '"status.recovery.kick"' in paint, "the window draws no countdown"
    page = (ROOT / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "web.ui.recovery.kick" in page and "kick_hold_left" in page, \
        "the phone shows the old panel"


def test_a_kick_never_blames_the_daemon():
    """The alternation of #1268 exists for a diagnosis nobody has. Here there is one.

    Two client restarts with the link never back move the blame to the daemon — right,
    while the fault is unknown. An account on another device is not something a daemon
    on this machine can be restarted out of, and reaching for it would be the #1268
    mistake made deliberately.
    """
    r = rec.Recovery()
    now = 1000.0
    # Far enough apart that neither wait is what is being measured: the cooldown
    # between two restarts, and the fifteen minutes a kick is left alone (#1291).
    step = max(rec.COOLDOWN_SEC, rec.KICK_HOLD_SEC) + 60
    # Twice as many rounds as restarts wanted: a restart clears the kick's run, so the
    # next episode spends one round earning its readings and the round after that acts.
    for _ in range((rec.FRUITLESS + 2) * 2):
        for i in range(rec.KICK_STRIKES):
            r.note(ONLINE, now + i * 8, idle_sec=9999.0, kicked=True)
        now += step
    assert r.state(now)["daemon_restarts"] == 0, "a kick was blamed on the daemon"
    assert r.restarts >= rec.FRUITLESS + 1, r.restarts


def test_errands_that_press_nothing_are_counted_and_said_once():
    """«Успешно ничего» — the only true line in the log that morning (#1270).

    Evidence, never a cure: it is said and drawn, and it restarts nothing, because a
    spent account genuinely presses nothing all evening.
    """
    r = rec.Recovery()
    said = [x for _ in range(rec.BARREN * 2) if (x := r.note_run(1, 0))]
    assert [k for k, _ in said] == [rec.SAY_BARREN], said
    assert said[0][1]["n"] == rec.BARREN, said
    assert rec.SAY_BARREN not in rec.RESTARTS | rec.DAEMON_RESTARTS
    assert rec.SAY_BARREN in rec.SAYINGS
    assert r.restarts == 0, "a reading became a cure"


def test_a_press_that_landed_clears_the_barren_count():
    r = rec.Recovery()
    for _ in range(rec.BARREN - 1):
        r.note_run(1, 0)
    assert r.note_run(1, 3) is None
    assert r.state(1000.0)["barren"] == 0
    assert [x for _ in range(rec.BARREN - 1) if (x := r.note_run(1, 0))] == []


def test_an_errand_that_attempted_no_counted_press_is_no_evidence():
    """A plain `TAP x3` fires blind and learns nothing; a read-only errand presses
    nothing by design. Neither may be counted as the game refusing."""
    r = rec.Recovery()
    for _ in range(rec.BARREN * 2):
        assert r.note_run(0, 0) is None
    assert r.state(1000.0)["barren"] == 0


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
                       "held_by", "blame", "daemon_stale", "daemon_strikes",
                       "daemon_restarts", "daemon_cooldown_left", "fruitless",
                       "barren", "barren_of", "kick_hold_left", "kick_hold_of"}, st
    assert st["restarts"] == 1 and st["strikes"] == rec.STRIKES
    assert 0 < st["cooldown_left"] <= rec.COOLDOWN_SEC
    words = ("held_by", "blame")
    for key, value in st.items():
        # Numbers, and two ids — never a sentence. `held_by` names WHY a restart is
        # being withheld and `blame` names WHAT is thought to be broken, so each
        # front-end can word both itself; each is a key and not a language.
        assert isinstance(value, int if key not in words else str), (key, value)
    assert st["held_by"] in ("", "cooldown", "player", "daemon_cooldown", "kick"), st
    assert st["blame"] in ("", "client", "daemon"), st


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


def _shell_method(name: str) -> str:
    """One method's source out of the shell, for the wiring assertions below."""
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    at = shell.index("def %s" % name)
    return shell[at:shell.index("\n    def ", at + 10)]


def test_the_restart_it_asks_for_is_the_lifecycle_recipe():
    """Not a hand-rolled kill-and-launch: the panel presses scenarios (`CLAUDE.md`).

    Both decisions go through ONE door now (`_act_on`), which is the point: there are
    two cures and four acts, and a second place that turned keys into presses would be
    a second place to forget one.
    """
    check = _shell_method("_recovery_check")
    assert "_act_on(" in check, "the decision never reaches the door that acts on it"
    body = _shell_method("_act_on")
    assert 'play_async("restart_game")' in body, body[-400:]
    # …and on EVERY act that means it, never on the «too soon» answer. The sets, not one
    # constant: `key == recovery.ACT` is what left a kicked client announced and never
    # restarted, and this assertion used to pass over that bug because `recovery.ACT`
    # is a substring of the very line that was missing it.
    assert "recovery.RESTARTS" in body, body[-400:]
    assert "recovery.DAEMON_RESTARTS" in body, "the daemon's cure is never wired"
    assert "== runtime.recovery.ACT" not in body, "one act is wired, the others are not"


def test_the_daemons_cure_is_the_daemons_own_restart():
    """…and it is `DaemonLink.restart`, not a kill: the daemon is asked to go and a
    fresh one is started, which is what re-attaches it to the client that is running.

    It is also the SAME method the «⭮» button beside the daemon indicator presses. The
    cure already existed and only the decision to reach for it was missing, so the count
    of definitions is pinned: the first draft of #1268 added a second `_restart_daemon`
    that silently overrode the button's, which is the failure mode `docs/panel-tabs.md`
    calls «a control drawn twice, never copied».
    """
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert shell.count("def _restart_daemon") == 1, "two daemon restarts, one wins"
    body = _shell_method("_restart_daemon")
    assert "_game.restart" in body, body
    assert "taskkill" not in body and "terminate" not in body, body
    daemon = (ROOT / "panel" / "runtime" / "daemon.py").read_text(encoding="utf-8")
    assert "def attached_pid" in daemon, "nothing can tell which client the daemon holds"
    # …and the reading that turns that pid into a verdict, which `ensure` asks before it
    # may call a daemon warm (#1286). Without it «already warm» is a port check again.
    assert "def health" in daemon, "nothing can tell a live daemon from a corpse"


def test_every_act_that_means_a_restart_is_in_the_set():
    """A new `ACT_*` is a new press. A set is how a caller finds out about it.

    There are two sets now — one cure per thing that can be broken (#1268) — and the
    check is that every act belongs to EXACTLY one. An act in neither is announced and
    never done, which is the 2026-08-06 bug; an act in both is a client and a daemon
    restarted for one reading, which is the same carelessness pointing the other way.
    """
    acts = {name for name in vars(rec)
            if name == "ACT" or name.startswith("ACT_")}
    for name in sorted(acts):
        key = getattr(rec, name)
        homes = [s for s in ("RESTARTS", "DAEMON_RESTARTS") if key in getattr(rec, s)]
        assert len(homes) == 1, f"{name} is in {homes or 'no set'}, expected exactly one"


class _Press:
    """The shell, reduced to what `_recovery_check` touches. Records what it played."""

    def __init__(self, watchdog=True):
        self.played, self.said = [], []
        #: Daemon restarts asked for — the second cure, which has no recipe and so
        #: cannot show up in `played` (#1268).
        self.daemons = 0
        self._watchdog = watchdog
        self._rt = self

    # -- the runtime half
    recovery = None                       # set per case, below
    def play_async(self, name, **kw):     # noqa: E301,D102 — the press being pinned
        self.played.append(name)
        return True

    # -- the window half
    def _paint_recovery(self, _state):    # noqa: D102 — drawing, not deciding
        pass

    def _opt_bool(self, _key):            # noqa: D102 — the profile's «watchdog»
        return self._watchdog

    def _opt_int(self, _key, low=None, high=None):
        """…and «выдержка после кика», in minutes (#1291). Zero: these cases are about
        the decision, and the wait has its own tests above."""
        return 0

    def _say(self, tag, key, **fmt):      # noqa: D102
        self.said.append(key)

    def _restart_daemon(self):            # noqa: D102 — the OTHER cure
        self.daemons += 1

    def _act_on(self, said):              # noqa: D102 — the real one, borrowed below
        raise AssertionError("replaced by the real Panel._act_on in _drive")


class _Found:
    def __init__(self, link, pid=4242):
        self.link, self.running, self.pid = link, True, pid


def _drive(link, kicked, watchdog=True, idle=10_000.0, stale=False, rounds=None):
    """Run the SHELL's own `_recovery_check` over a run of readings, unbound.

    The wiring is what is being pinned, not the decision — «`ACT_KICK` was announced and
    never played» lived entirely between the two, in a method that greps clean, and the
    same gap is where a daemon restart would go missing.
    """
    import panel.__main__ as pm            # by name: safe, and what the other tests do

    app = _Press(watchdog=watchdog)
    app.recovery = rec.Recovery()
    app._act_on = lambda said: pm.Panel._act_on(app, said)
    real_idle = pm.game_link.idle_sec
    pm.game_link.idle_sec = lambda: idle   # nobody at the machine, deterministically
    try:
        for _ in range(rounds if rounds is not None else rec.STRIKES):
            pm.Panel._recovery_check(app, _Found(link), kicked, stale)
    finally:
        pm.game_link.idle_sec = real_idle
    return app


def test_a_kick_is_actually_restarted_and_not_only_announced():
    """THE BUG THIS FILE MISSED, in the only terms that could have caught it.

    Live on 2026-08-06 the panel said «выкинуло: вход с другого устройства —
    перезапускаю» at 22:49:02 and at 22:59:05 and played nothing either time: the
    caller tested `key == recovery.ACT`, and a kick answers `ACT_KICK`. Nineteen
    minutes of a deaf client, rescued in the end by the process watchdog when it died
    on its own. Every assertion in this file passed throughout — they all stopped at
    the decision, and the decision was right.
    """
    app = _drive(LOST, kicked=True)
    assert app.said == [rec.ACT_KICK], app.said
    assert app.played == ["restart_game"], f"announced and not played: {app.played}"


def test_an_ordinary_hang_up_is_restarted_too():
    """The path that always worked — pinned beside the one that did not, so a fix to
    either cannot quietly cost the other."""
    app = _drive(LOST, kicked=False)
    assert app.said == [rec.ACT] and app.played == ["restart_game"], (app.said, app.played)


def test_nothing_is_played_while_the_watchdog_switch_is_off():
    """One promise, one switch: «поднимать игру при падении» governs both halves."""
    app = _drive(LOST, kicked=True, watchdog=False)
    assert app.played == [], app.played


def test_a_healthy_client_is_neither_announced_nor_played():
    app = _drive(ONLINE, kicked=False)
    assert (app.said, app.played) == ([], []), (app.said, app.played)


# ---------------------------------------------------------------------------
# #1268 — restarting the RIGHT thing
#
# Live on 2026-08-07 the client was relaunched six times in fifty minutes and the link
# never came back: the fault was the daemon holding a dead pid. Two readings now tell
# that apart from a broken client, and each gets both halves pinned — the decision, and
# the wiring that turns it into a press.
# ---------------------------------------------------------------------------
def test_one_stale_reading_is_not_a_reason_either():
    """The same patience as a link reading, and for a narrower reason: a daemon is
    legitimately a step behind a client that has just been replaced."""
    r = rec.Recovery()
    assert r.note_daemon(True, 1000.0) is None
    assert r.state(1000.0)["daemon_restarts"] == 0


def test_a_run_of_stale_readings_restarts_the_daemon_and_not_the_client():
    r = rec.Recovery()
    said = [r.note_daemon(True, 1000.0 + i * 8) for i in range(rec.DAEMON_STRIKES)]
    key, _fmt = said[-1]
    assert key == rec.ACT_DAEMON
    assert key in rec.DAEMON_RESTARTS and key not in rec.RESTARTS, \
        "the daemon's fault must never be answered with a client restart"


def test_the_daemon_is_judged_while_the_link_is_perfectly_online():
    """THE SHAPE THAT WAS MISSED. Six sockets established, the strip saying «онлайн»,
    and every errand failing — a decision hung off `link == lost` is never even asked."""
    app = _drive(ONLINE, kicked=False, stale=True, rounds=rec.DAEMON_STRIKES)
    assert app.daemons == 1, f"daemon never restarted: {app.daemons}"
    assert app.played == [], f"the client must not be touched: {app.played}"
    assert rec.ACT_DAEMON in app.said


def test_a_matching_pid_says_nothing_and_clears_the_run():
    r = rec.Recovery()
    r.note_daemon(True, 1000.0)
    assert r.note_daemon(False, 1008.0) is None
    assert r.state(1008.0)["daemon_stale"] == 0
    assert r.state(1008.0)["blame"] == ""


def test_a_second_daemon_restart_waits_out_its_own_cooldown_and_says_so_once():
    r = rec.Recovery()
    for i in range(rec.DAEMON_STRIKES):
        r.note_daemon(True, 1000.0 + i * 8)
    said = [r.note_daemon(True, 1100.0 + i * 8) for i in range(rec.DAEMON_STRIKES + 2)]
    holds = [s for s in said if s and s[0] == rec.HOLD_DAEMON]
    assert len(holds) == 1, f"the wait must be said once, not per reading: {said}"
    assert r.state(1100.0)["daemon_restarts"] == 1


def test_a_daemon_that_stays_stale_is_restarted_again_after_the_cooldown():
    """The 2026-08-06 bug, guarded against in the new half before it can happen: a hold
    that suppressed the ACT as well left a broken thing broken for ever."""
    r = rec.Recovery()
    now = 1000.0
    acts = 0
    for _ in range(6):
        for i in range(rec.DAEMON_STRIKES):
            said = r.note_daemon(True, now + i * 8)
            if said and said[0] == rec.ACT_DAEMON:
                acts += 1
        now += rec.DAEMON_COOLDOWN_SEC + 1
    assert acts >= 5, f"a permanently stale daemon was restarted {acts}× in six rounds"


def _cures(r, rounds, t0=1000.0):
    """Which cure each restart round reached for: "client" or "daemon", in order."""
    out, now = [], t0
    for _ in range(rounds):
        for i in range(rec.STRIKES):
            said = r.note(LOST, now + i * 8, idle_sec=10_000.0)
            if said and said[0] in rec.RESTARTS:
                out.append("client")
            elif said and said[0] in rec.DAEMON_RESTARTS:
                out.append("daemon")
        now += rec.COOLDOWN_SEC + 1
    return out


def test_client_restarts_that_change_nothing_move_the_blame_to_the_daemon():
    """THE ANTI-LOOP. Not «restart harder» — a different diagnosis.

    The link never returns, so every strike run ends in a restart. The first
    :data:`FRUITLESS` are the client's; then something else is tried.
    """
    cures = _cures(rec.Recovery(), rec.FRUITLESS + 1)
    assert cures[:rec.FRUITLESS] == ["client"] * rec.FRUITLESS, cures
    assert cures[rec.FRUITLESS] == "daemon", f"the blame never moved: {cures}"


def test_neither_cure_is_ever_abandoned_for_the_other():
    """ALTERNATION, not replacement — the regression the first draft of this shipped.

    Booking the daemon and leaving the count where it was meant the client was never
    restarted again: one stuck loop swapped for another, and the worse one, because a
    client restart is the cure that works most of the time. So the pattern repeats —
    client, client, daemon, client, client, daemon — and a permanently deaf client goes
    on being retried for ever, which is what `test_a_link_that_never_comes_back…`
    already promised and what caught this.
    """
    cures = _cures(rec.Recovery(), rec.FRUITLESS * 3 + 3)
    assert cures.count("client") >= rec.FRUITLESS * 2, f"client abandoned: {cures}"
    assert cures.count("daemon") >= 2, f"daemon abandoned: {cures}"
    # …and no cure is ever repeated more than FRUITLESS times without the other
    # being tried in between.
    run, last = 0, None
    for cure in cures:
        run = run + 1 if cure == last else 1
        last = cure
        assert run <= rec.FRUITLESS, f"{cure} repeated {run}× in a row: {cures}"


def test_the_blame_moves_back_the_moment_the_link_returns():
    """A cure that WORKED is the only thing that clears the evidence — and it has to be
    ONLINE, not merely «not lost»: a relaunching client is `offline` then `unknown` for
    most of a minute, and counting those would reset the count every single restart."""
    r = rec.Recovery()
    for i in range(rec.STRIKES):
        r.note(LOST, 1000.0 + i * 8, idle_sec=10_000.0)
    assert r.state(1000.0)["fruitless"] == 1
    r.note(OFFLINE, 1040.0)                     # …still on its way back
    assert r.state(1040.0)["fruitless"] == 1, "a relaunching client is not a success"
    r.note(UNKNOWN, 1048.0)
    assert r.state(1048.0)["fruitless"] == 1
    r.note(ONLINE, 1056.0)                      # …and now it is
    assert r.state(1056.0)["fruitless"] == 0
    assert r.state(1056.0)["blame"] == ""


def test_the_anti_loop_is_wired_all_the_way_to_the_press():
    """The decision reaching the shell, which is where the last one was lost."""
    import panel.__main__ as pm

    app = _Press()
    app.recovery = rec.Recovery()
    app._act_on = lambda said: pm.Panel._act_on(app, said)
    real_idle = pm.game_link.idle_sec
    pm.game_link.idle_sec = lambda: 10_000.0
    try:
        now = 1000.0
        for _ in range(rec.FRUITLESS + 1):
            for _ in range(rec.STRIKES):
                pm.Panel._recovery_check(app, _Found(LOST), False, False)
            # let the client cooldown expire so the run is decided on the blame and
            # not on the wait
            app.recovery._last -= rec.COOLDOWN_SEC + 1
            now += 1
    finally:
        pm.game_link.idle_sec = real_idle
    assert len(app.played) == rec.FRUITLESS, f"client restarts: {app.played}"
    assert app.daemons >= 1, "the seventh client restart happened instead"


def test_nothing_at_all_happens_while_the_watchdog_switch_is_off():
    """One promise, one switch — and the daemon half obeys it too."""
    app = _drive(ONLINE, kicked=False, stale=True, watchdog=False,
                 rounds=rec.DAEMON_STRIKES)
    assert (app.daemons, app.played) == (0, []), (app.daemons, app.played)


def test_the_state_says_what_is_being_blamed_and_how_hard_it_has_tried():
    """Both front-ends draw out of this one dict, and «что чинится» is half the answer."""
    r = rec.Recovery()
    st = r.state(1000.0)
    for field in ("blame", "daemon_stale", "daemon_strikes", "daemon_restarts",
                  "daemon_cooldown_left", "fruitless"):
        assert field in st, f"the front-ends cannot draw {field}"
    for i in range(rec.DAEMON_STRIKES):
        r.note_daemon(True, 1000.0 + i * 8)
    st = r.state(1008.0)
    assert st["blame"] == "daemon" and st["daemon_restarts"] == 1
    assert st["daemon_cooldown_left"] > 0
    assert all(not isinstance(v, str) or k in ("blame", "held_by")
               for k, v in st.items()), "the state is numbers, the words are the locales'"


def _held(pid):
    """A game link whose daemon answers a ping naming ``pid`` — the real comparison.

    A `GameLink` with nothing built but its answer to the wire, so the two-pid reading
    under test is `GameLink.health`'s own and not a restatement of it here. Since #1286
    that is where «stale» is defined, because `ensure` has to ask the same question
    before it can say «already warm» over a daemon holding a client that has gone.
    """
    link = daemonmod.GameLink.__new__(daemonmod.GameLink)
    link.ping = lambda: {"ok": True, "warm": pid is not None, "pid": pid}
    return link


def test_a_daemon_that_will_not_say_which_client_is_never_a_reason():
    """`unknown` is never a reason — the rule the link half already keeps.

    `_daemon_stale` answers False for every «could not tell»: no daemon, no client,
    no pid. A restart loop built on an unanswered question has no bottom.
    """
    import panel.__main__ as pm

    app = _Press()
    app._rt = app
    app.game = _held(None)
    assert pm.Panel._daemon_stale(app, _Found(ONLINE), False) is False, "no daemon"
    assert pm.Panel._daemon_stale(app, _Found(ONLINE, pid=0), True) is False, "no client"
    dead = type("F", (), {"link": ONLINE, "running": False, "pid": 7})()
    assert pm.Panel._daemon_stale(app, dead, True) is False, "client not running"


def test_the_pids_are_compared_and_nothing_else_is():
    """The positive reading: two integers. Equal is healthy, different is the fault."""
    import panel.__main__ as pm

    app = _Press()
    app._rt = app
    app.game = _held(4242)
    assert pm.Panel._daemon_stale(app, _Found(ONLINE, pid=4242), True) is False
    assert pm.Panel._daemon_stale(app, _Found(ONLINE, pid=9999), True) is True
    # …and a daemon that answers for NO client while one is running is the same fault
    # wearing another answer: it never attached, or it let go (#1286).
    app.game = _held(None)
    assert pm.Panel._daemon_stale(app, _Found(ONLINE, pid=9999), True) is True


def test_both_its_sentences_are_in_every_shipped_locale():
    import json

    keys = (rec.ACT, rec.HOLD, rec.BUSY, rec.ACT_KICK, rec.HOLD_KICK,
            rec.ACT_DAEMON, rec.ACT_DAEMON_STUCK, rec.HOLD_DAEMON, rec.SAY_BARREN,
            "status.recovery.kick", "web.ui.recovery.kick", "timers.log.skip_kick")
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
