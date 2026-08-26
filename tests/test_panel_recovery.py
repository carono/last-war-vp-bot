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
    from panel.runtime import link as linkmod  # noqa: E402
    from panel.runtime import recovery as rec  # noqa: E402
except Exception as _exc:                      # noqa: BLE001
    rec, linkmod, _WHY = None, None, _exc

# THE INPUT IS ONE BOOLEAN NOW (#1911): «есть клиент и сервер молчит». The socket table
# is not evidence any more — it cannot say which conversation is the game, and for a
# night it called a healthy client dead. The four names are kept so the hundred cases
# below go on reading as prose, and three of them are the same answer because they were
# always the same answer to this decision: anything that is not «deaf» ends the run.
LOST = True
ONLINE = False
UNKNOWN = False
OFFLINE = False


class _Recovery(rec.Recovery):
    """The real decision with the panel's probe loop bolted on (#1910).

    A restart now needs TWO families of evidence: the run of `lost` readings, and server
    probes that went unanswered. The second is asked for by the decision and answered by
    the panel (`panel/__main__.py::_probe_server`), which is an exchange and not a call —
    right for the panel, tedious for a hundred cases here that are about the cooldown, the
    alternation or the kick wait and not about the probe at all.

    So this is the panel's half, in four lines: when the decision asks for confirmation,
    answer every probe it wants and put the same reading back in. `probe_answer` is what
    the SERVER said — `False` is the deaf case every case below was written for, and
    `True` is the new one: sockets that say deaf over a server that is still answering.

    The confirmation itself is pinned against the raw :class:`recovery.Recovery`, below.
    """

    probe_answer = False

    def note(self, link, now, **kw):
        kw.pop("dead", None)                        # the socket count is gone (#1911)
        said = super().note(link, now, **kw)
        if not (said and said[0] == rec.HOLD_CONFIRM):
            return said
        for _ in range(rec.PROBE_FAILS + 2):        # bounded: a pump, never a spin
            if not self.probe_due(now):
                break
            self.probe_started(now)
            self.note_probe(self.probe_answer, now)
            now += rec.PROBE_GAP_SEC
        return super().note(link, now, **kw)


def _deaf(r, n, t0=1000.0, step=8.0):
    """Feed ``n`` consecutive lost readings; return every answer that was not None.

    CONFIRMED BY DEFAULT (#1910). A restart now needs two families of evidence — the run
    of `lost` readings AND server probes that went unanswered — so a helper that fed only
    the first would be testing a decision the panel no longer makes. The probes are
    answered here the way the panel answers them, at the moment the decision asks for
    one, so every case below goes on pinning what it was written to pin.

    `confirm=False` is the other half: the sockets say deaf and the SERVER still answers,
    which must never restart anything.
    """
    out = []
    for i in range(n):
        now = t0 + i * step
        said = r.note(LOST, now)
        if said:
            out.append(said)
    return out


#: How many readings it now takes to reach a restart: the run must also SPAN
#: :data:`recovery.LOST_SPAN_SEC`, and eight seconds a look is the poll's own rate.
DEAF_READINGS = max(rec.STRIKES, int(rec.LOST_SPAN_SEC // 8) + 2)


def test_one_bad_reading_is_not_a_reason():
    """A reconnecting client has, for a moment, exactly the sockets of a dead one."""
    r = _Recovery()
    assert _deaf(r, rec.STRIKES - 1) == []
    assert r.restarts == 0


def test_a_run_of_them_is():
    r = _Recovery()
    said = _deaf(r, DEAF_READINGS)
    assert len(said) == 1 and said[0][0] == rec.ACT, said
    assert r.restarts == 1


def test_offline_is_the_watchdogs_and_not_this_ones():
    """Two things must not relaunch one client."""
    r = _Recovery()
    for i in range(rec.STRIKES * 3):
        assert r.note(OFFLINE, 1000.0 + i * 8) is None
    assert r.restarts == 0


def test_a_second_restart_waits_out_the_cooldown_and_says_so_once():
    r = _Recovery()
    assert _deaf(r, DEAF_READINGS)[0][0] == rec.ACT

    # Straight back to deaf: the run builds again, and the answer is a WAIT, once.
    said = _deaf(r, rec.STRIKES * 3, t0=1100.0)
    assert [k for k, _ in said] == [rec.HOLD], said
    assert said[0][1]["mins"] >= 1, said
    assert r.restarts == 1, "it restarted inside the cooldown"


def test_after_the_cooldown_it_restarts_again():
    r = _Recovery()
    _deaf(r, DEAF_READINGS)
    later = 1000.0 + rec.COOLDOWN_SEC + 60
    said = _deaf(r, DEAF_READINGS, t0=later)
    assert [k for k, _ in said] == [rec.ACT], said
    assert r.restarts == 2


def test_a_link_that_never_comes_back_is_retried_after_every_cooldown():
    """The latch that left a deaf client sitting for an hour (#1259, live).

    The first version said «too soon» once and then suppressed EVERYTHING, so a link
    that never recovered was restarted once and abandoned. Live: restarted 21:44:16,
    «жду 7 мин» at 21:47:53, and then nothing at all while the cooldown expired and the
    schedule failed every errand against the same dead client.
    """
    r = _Recovery()
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
    r = _Recovery()
    said = [r.note(LOST, 1000.0 + i * 8, idle_sec=10.0) for i in range(20)]
    assert r.restarts == 0, "it restarted the client under somebody's hands"
    spoken = [s for s in said if s]
    assert spoken and spoken[0][0] == rec.BUSY, spoken
    assert len(spoken) == 1, f"it said it every poll: {spoken}"


def test_an_unreadable_idle_reading_never_lets_a_restart_through():
    """«Cannot tell» must not read as «nobody is there» — the gate only ever holds back."""
    r = _Recovery()
    for i in range(DEAF_READINGS):
        r.note(LOST, 1000.0 + i * 8, idle_sec=None)
    assert r.restarts == 1, "None must behave exactly as it did before the gate existed"


def test_the_reason_a_restart_is_being_withheld_is_readable():
    """«Не перезапускается» must never be unexplained — the person asked for this."""
    r = _Recovery()
    for i in range(DEAF_READINGS):
        r.note(LOST, 1000.0 + i * 8, idle_sec=10.0)
    assert r.state(1000.0)["held_by"] == "player"

    r2 = _Recovery()
    for i in range(DEAF_READINGS):
        r2.note(LOST, 2000.0 + i * 8, idle_sec=9999.0)
    for i in range(DEAF_READINGS):
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
    r = _Recovery()
    said = [x for i in range(DEAF_READINGS)
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
    r = _Recovery()
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


def test_one_kick_reading_is_not_a_reason_either():
    """A single unlucky poll acts on nothing, exactly like a single lost reading."""
    r = _Recovery()
    assert r.note(ONLINE, 1000.0, idle_sec=9999.0, kicked=True) is None
    assert r.restarts == 0


def test_a_kick_that_clears_takes_its_run_with_it():
    """The modal going away is the account coming back — nothing is owed to it."""
    r = _Recovery()
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
    r = _Recovery()
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
    r2 = _Recovery()
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
    r = _Recovery()
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
    r = _Recovery()
    t0 = 1000.0
    for i in range(rec.KICK_STRIKES):
        r.note(ONLINE, t0 + i * 8, idle_sec=9999.0, kicked=True)
    assert r.kick_hold_left(t0 + 60) > 0
    # …the client goes away mid-wait: no process, so no evidence the account is ours.
    r.note(OFFLINE, t0 + 68, idle_sec=9999.0, kicked=False, running=False)
    assert r.kick_hold_left(t0 + 68) > 0, "a client that went away lost its own wait"
    # …and the strip goes on saying so. A blank one here reads as «ничего не
    # происходит» through the fifteen minutes when something deliberately is.
    assert r.state(t0 + 68)["held_by"] == "kick", r.state(t0 + 68)
    r.note(ONLINE, t0 + 76, idle_sec=9999.0, kicked=False, talking=True)
    assert r.kick_hold_left(t0 + 76) == 0


def test_a_second_kick_buys_its_own_wait_and_a_spent_one_does_not_repeat():
    """The wait is per EPISODE: armed once, honoured once, and re-armed for the next.

    Both halves are the bug: an expired deadline that re-arms on the next reading (the
    modal is still on screen) waits for ever and never restarts, and one that never
    re-arms lets the second kick be answered in thirty seconds — which is the fight
    this whole thing exists to stay out of.
    """
    r = _Recovery()
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
    # THE POLL IS THE RUNTIME'S SINCE #1984 — a panel with no window has to feed the
    # decision too, so the setting reaches it from `panel/runtime/status.py`.
    poll = (ROOT / "panel" / "runtime" / "status.py").read_text(encoding="utf-8")
    assert "kick_hold_sec" in poll and "kick_hold_min" in poll, \
        "the setting never reaches the decision"
    page = (ROOT / "panel" / "tabs" / "settings.py").read_text(encoding="utf-8")
    assert '"kick_hold_min"' in page, "there is no field to type it in"
    for path in sorted((ROOT / "panel" / "locales").glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in ("opt.kick_hold_min", "opt.kick_hold_min.hint")
                   if k not in locale]
        assert not missing, f"{path.name}: {missing}"

    r = _Recovery()
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

    def __init__(self, hold_left=lambda now: 0, cooldown=300.0, gate_open=True):
        # WHETHER ANYTHING MAY RUN AT ALL (#1393). The client going away is exactly what
        # «Стоп всё» arranges, and a watchdog that had never heard of the press used to
        # put it back on the next poll. Open by default: every case below is about a
        # panel that is running.
        self._gate_open = gate_open
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
               # The strike spacing reads the poll interval (#1702) — the panel's own
               # number, so a change to it changes what this stub polls at too.
               "STATUS_POLL_MS": 8000,
               "time": self}
        exec(compile("class _S:\n    " + _shell_method("_watchdog_check"),
                     "<watchdog>", "exec"), env)
        self.check = env["_S"]._watchdog_check.__get__(self)

    # the stub's own surface, standing in for the panel's
    def time(self) -> float:                       # `time.time()` inside the method
        return self.now

    def monotonic(self) -> float:                  # `time.monotonic()` — the strike clock
        # A STRIKE IS A FRESH LOOK (#1702): the method spaces its strikes by the poll
        # interval, so the stub's clock has to move the way the poll does. Same `now`
        # as `time()` — this stub has one clock and the method uses it for two things.
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

    def _probe_server(self, now) -> None:    # the confirmation's press (#1910)
        pass

    @property
    def _rt(self):                                 # `self._rt.recovery` / `_rt.play_async`
        return self

    @property
    def recovery(self):
        return self

    @property
    def gate(self):                                # `self._rt.gate.alive()`
        return self

    def alive(self) -> bool:
        return self._gate_open

    def relaunch_held(self) -> bool:               # `self._rt.gate.relaunch_held()`
        """What the watchdog asks since #1910 — the SWITCH, never the daemon.

        `gate_open=False` in the cases below always meant «somebody stopped this
        profile», which is exactly what this half answers; the daemon half never
        belonged here, because the client this would put back is what a daemon with
        nothing to attach to is missing.
        """
        return not self._gate_open

    @property
    def _dbg(self):                                # the held branch says so in debug.log
        return self

    def info(self, *args, **kw) -> None:
        pass

    def debug(self, *args, **kw) -> None:          # the spacing branch says so in debug.log
        pass

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

    # …and the retry does not make the wait new. Live on 2026-08-08 the relaunch
    # cleared the latch on its way out, so a profile whose Windows session was simply
    # not up said «поднимаю игру заново» AND «перезапуск был 0 мин назад — жду» every
    # five minutes all night. One attempt is worth a line; the wait behind it is not
    # worth repeating until something about it has changed.
    for _ in range(10):
        w.poll()
    assert [k for k, _ in w.said].count("log.game.watchdog_hold") == 1, w.said


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
    page = (ROOT / "panel" / "web" / "app" / "src" / "views" / "StateView.tsx").read_text(
        encoding="utf-8")
    assert "web.ui.recovery.kick" in page and "kick_hold_left" in page, \
        "the phone shows the old panel"


def test_a_press_that_landed_clears_the_barren_count():
    r = _Recovery()
    for _ in range(rec.BARREN - 1):
        r.note_run(1, 0)
    assert r.note_run(1, 3) is None
    assert r.state(1000.0)["barren"] == 0
    assert [x for _ in range(rec.BARREN - 1) if (x := r.note_run(1, 0))] == []


def test_an_errand_that_attempted_no_counted_press_is_no_evidence():
    """A plain `TAP x3` fires blind and learns nothing; a read-only errand presses
    nothing by design. Neither may be counted as the game refusing."""
    r = _Recovery()
    for _ in range(rec.BARREN * 2):
        assert r.note_run(0, 0) is None
    assert r.state(1000.0)["barren"] == 0


def test_a_healthy_client_is_never_touched_however_long_it_runs():
    r = _Recovery()
    for i in range(500):
        assert r.note(ONLINE, 1000.0 + i * 8) is None
    assert r.restarts == 0 and r.deaf_for == 0


def test_every_act_carries_the_words_to_explain_itself():
    """A restart with no line in the log is the fault this feature exists to fix."""
    r = _Recovery()
    for key, fmt in _deaf(r, DEAF_READINGS):
        assert isinstance(key, str) and key.startswith("log."), key
        assert isinstance(fmt, dict), fmt


def _sockets_say_deaf(r, n=None, t0=1000.0):
    """Feed the socket half only — no probes answered either way."""
    said = []
    for i in range(n or DEAF_READINGS):
        got = r.note(LOST, t0 + i * 8, idle_sec=10_000.0)
        if got:
            said.append(got)
    return said


def test_sockets_alone_never_restart_anything_any_more():
    """THE COMPLAINT, in one case: «панель перезапускает игру, а игра жива».

    Five looks over a minute of `lost` used to be the whole criterion, and the operator
    reports it firing on clients that are perfectly alive. It is now half the evidence:
    with no probe answered either way the decision waits, and says so.
    """
    r = rec.Recovery()
    said = _sockets_say_deaf(r)
    assert said and said[0][0] == rec.HOLD_CONFIRM, said
    assert r.restarts == 0, "the sockets alone restarted a client"


def test_a_server_that_still_answers_stops_the_restart_dead():
    """The false positive this whole criterion exists to remove.

    Sockets that read `lost` over a client the SERVER is still talking to. One answered
    probe is a fact that outranks any number of socket readings, so the count is wiped
    and nothing is restarted however long the sockets go on saying it.
    """
    r = rec.Recovery()
    now = 1000.0
    for i in range(DEAF_READINGS * 3):
        r.note(LOST, now + i * 8, idle_sec=10_000.0)
        while r.probe_due(now + i * 8):
            r.probe_started(now + i * 8)
            r.note_probe(True, now + i * 8)      # the server answered
    assert r.restarts == 0, "a client the server answers for was restarted"


def test_two_unanswered_probes_are_what_lets_it_through():
    """…and the other half: the same sockets, and a server that does not answer."""
    r = rec.Recovery()
    said, now = [], 1000.0
    for i in range(DEAF_READINGS):
        got = r.note(LOST, now + i * 8, idle_sec=10_000.0)
        if got:
            said.append(got)
        while r.probe_due(now + i * 8):
            r.probe_started(now + i * 8)
            r.note_probe(False, now + i * 8 + 1)
            now += rec.PROBE_GAP_SEC
    got = r.note(LOST, now + DEAF_READINGS * 8, idle_sec=10_000.0)
    if got:
        said.append(got)
    kinds = [k for k, _ in said]
    assert rec.ACT in kinds, kinds
    assert r.restarts == 1


def test_a_probe_that_never_came_back_counts_as_a_refusal():
    """A stranded client ACCEPTS the send and answers nothing — that is the whole tell.

    So «no reply within the deadline» has to count, or the one shape being detected would
    be the one shape that never accumulates.
    """
    r = rec.Recovery()
    _sockets_say_deaf(r)
    r.probe_started(2000.0)
    assert r.probe_due(2000.0 + rec.PROBE_DEADLINE_SEC / 2) is False, "asked too early"
    assert r.probe_state()["fails"] == 0, "counted before its deadline was up"
    # Past the deadline: the silence is recorded. Asking AGAIN is a separate question,
    # and it waits out `PROBE_GAP_SEC` like every other probe — two asked in one breath
    # are one ask.
    r.probe_due(2000.0 + rec.PROBE_DEADLINE_SEC + 1)
    assert r.probe_state()["fails"] == 1, r.probe_state()
    assert r.probe_due(2000.0 + rec.PROBE_GAP_SEC + 1) is True, "never asked again"


def test_an_answered_probe_is_believed_for_a_while():
    """Found LIVE, not by reading (#1910). The sockets can be wrong for hours.

    Measured the same evening: `classify` said `lost` continuously while the server
    answered every probe. The decision kept reaching the confirmation and the
    confirmation kept asking — one round trip into the game every twenty-five seconds,
    for ever, to re-establish a fact that had not changed.
    """
    r = rec.Recovery()
    _sockets_say_deaf(r)
    assert r.probe_due(2000.0) is True
    r.probe_started(2000.0)
    r.note_probe(True, 2000.5)                       # the server answered
    assert r.probe_due(2000.5 + rec.PROBE_GAP_SEC + 1) is False, "asked again at once"
    # …and the want is re-armed by THE DECISION, never by the clock: the sockets have to
    # still be saying `lost` for another probe to be worth anything.
    later = 2000.5 + rec.PROBE_OK_HOLD_SEC + 1
    r.note(LOST, later, idle_sec=10_000.0)
    assert r.probe_due(later) is True, "never asked again"


def test_the_refusal_is_said_on_the_edge_and_then_rarely():
    """The same sentence every twenty-five seconds is the noise, not the news.

    It is worth saying the moment it becomes true — «панель ничего не делает» and
    «панель держит перезапуск» must never look alike — and worth nothing at all on the
    hundredth repetition.
    """
    r = rec.Recovery()
    first = [x for x in (r.note(LOST, 1000.0 + i * 8, idle_sec=10_000.0)
                         for i in range(DEAF_READINGS)) if x]
    assert first and first[0][0] == rec.HOLD_CONFIRM, first
    again = [x for x in (r.note(LOST, 1000.0 + (DEAF_READINGS + i) * 8,
                                idle_sec=10_000.0)
                         for i in range(DEAF_READINGS)) if x]
    assert again == [], f"the refusal repeated inside its own window: {again}"
    late = r.note(LOST, 1000.0 + rec.CONFIRM_SAY_SEC + 100, idle_sec=10_000.0)
    assert late and late[0] == rec.HOLD_CONFIRM, "it never said it again at all"


def test_a_fresh_server_answer_is_what_paints_the_link_live():
    """Green comes from a FACT with a shelf life, never from an absence of bad signs.

    The sockets on this machine sit permanently in the shape they will not vouch for
    (`game_link.classify`, #1910), so a light that could only ever be amber for it would
    be amber for ever — and an amber nobody can clear is an amber nobody reads. What
    clears it is the game SERVER having answered, and only for as long as that answer is
    worth anything.
    """
    r = rec.Recovery()
    assert r.link_confirmed(1000.0) is False, "green before anything was measured"
    r.probe_started(1000.0)
    r.note_probe(True, 1000.5)
    assert r.link_confirmed(1000.5) is True
    assert r.link_confirmed(1000.5 + rec.PROBE_OK_HOLD_SEC - 1) is True
    assert r.link_confirmed(1000.5 + rec.PROBE_OK_HOLD_SEC + 1) is False, \
        "a stale answer went on painting the link live"


def test_a_refused_probe_never_paints_anything_live():
    """…and the other direction, which is the one that would be dangerous."""
    r = rec.Recovery()
    r.probe_started(1000.0)
    r.note_probe(False, 1000.5)
    assert r.link_confirmed(1000.5) is False


def test_both_front_ends_are_handed_the_confirmation():
    """One reading, two screens — the rule this repository keeps for every state."""
    r = rec.Recovery()
    r.probe_started(1000.0)
    r.note_probe(True, 1000.5)
    st = r.state(1001.0)["probe"]
    assert st["confirmed"] is True and st["for_sec"] == int(rec.PROBE_OK_HOLD_SEC), st


def test_the_decision_line_carries_the_numbers_it_was_made_on():
    """«На основании ЧЕГО» — measured, never computed (#1910).

    The old sentence said «не слышен серверу 24 с», and the 24 was `STRIKES * 8`: a
    multiplication, over a poll that jitters, presented as an observation.
    """
    r = _Recovery()
    said = _deaf(r, DEAF_READINGS)
    act = [fmt for key, fmt in said if key == rec.ACT]
    assert act, said
    fmt = act[0]
    assert set(fmt) == {"looks", "secs", "fails", "probe_secs", "idle"}, fmt
    assert fmt["looks"] >= rec.STRIKES, fmt
    assert fmt["secs"] >= rec.LOST_SPAN_SEC, fmt
    assert fmt["fails"] >= rec.PROBE_FAILS, fmt


def test_the_refusal_line_carries_the_same_numbers():
    """A restart withheld and a restart never considered must not be one silence."""
    r = rec.Recovery()
    said = _sockets_say_deaf(r)
    key, fmt = said[0]
    assert key == rec.HOLD_CONFIRM
    assert set(fmt) == {"looks", "secs", "fails", "need"}, fmt
    assert fmt["need"] == rec.PROBE_FAILS and fmt["fails"] < rec.PROBE_FAILS, fmt


def test_the_player_gate_holds_a_restart_back_but_not_for_ever():
    """A person at the machine buys the client time — not an indefinite reprieve (#1888).

    The gate exists because the restart closes the window somebody may be playing in,
    and that is worth five minutes of patience. It is not worth a night: live on
    2026-08-23 a profile sat `held_by=player` for three hours on a machine its owner was
    WORKING at, saying «не трогаю ещё 5 мин» over and over and meaning «never». The one
    restart it got that day landed while the person was away from the keyboard.

    A lost link is not a session anybody is playing — nothing typed into that window
    reaches the server — so after `PLAYER_HOLD_MAX_SEC` the client is put back anyway.
    """
    r = _Recovery()
    t = 1000.0
    # Somebody has just touched the keyboard, and goes on touching it.
    said = [r.note(LOST, t + i * 8.0, idle_sec=1.0) for i in range(DEAF_READINGS)]
    held = [x for x in said if x]
    assert held and held[-1][0] == rec.BUSY, said
    assert r.state(t)["held_by"] == "player"
    assert r.state(t)["player_hold_left"] > 0

    # …and for the whole of the patience nothing touches the client.
    inside = t + rec.PLAYER_HOLD_MAX_SEC - 30
    assert r.note(LOST, inside, idle_sec=1.0) is None
    assert r.state(inside)["player_hold_left"] > 0

    # THEN THE PATIENCE RUNS OUT and the client is restarted with the person still
    # there — in its own words, so the log can never be read as «nobody was around».
    after = t + rec.PLAYER_HOLD_MAX_SEC + 8
    act = r.note(LOST, after, idle_sec=1.0)
    assert act is not None and act[0] == rec.ACT_BUSY, act
    assert act[0] in rec.RESTARTS, act
    assert r.state(after)["restarts"] == 1


def test_the_player_hold_is_measured_from_the_link_and_not_from_the_keyboard():
    """The clock starts when the LINK went, and it is reset by the link coming back.

    Otherwise a person who steps away and returns would restart the patience, and a
    client that lost the server at three would still be deaf at midnight — the shape of
    the bug, arrived at the other way round.
    """
    r = _Recovery()
    t = 1000.0
    _deaf(r, rec.STRIKES, t0=t)              # nobody at the machine: idle unknown
    # The link comes back, so the clock is cleared and nothing is being postponed.
    assert r.note(ONLINE, t + 40) is None
    assert r.player_hold_left(t + 40) == 0

    # A fresh loss starts a fresh clock, even with the keyboard warm the whole time.
    t2 = t + 100
    for i in range(DEAF_READINGS):
        r.note(LOST, t2 + i * 8.0, idle_sec=1.0)
    left = r.player_hold_left(t2 + 16)
    assert 0 < left <= rec.PLAYER_HOLD_MAX_SEC, left


def test_a_client_nobody_is_at_is_still_restarted_at_once():
    """The bound must not become a wait of its own — the ordinary case is unchanged."""
    r = _Recovery()
    said = _deaf(r, DEAF_READINGS)             # `idle_sec=None`: cannot tell
    assert said and said[-1][0] == rec.ACT, said
    r2 = _Recovery()
    said = [x for x in (r2.note(LOST, 1000.0 + i * 8.0, idle_sec=9999.0)
                        for i in range(DEAF_READINGS)) if x]
    assert said and said[-1][0] == rec.ACT, said


def test_the_input_is_a_verdict_and_not_a_socket_reading():
    """#1911: the sockets are not evidence. What comes in is «amber, and deaf»."""
    assert LOST is True and ONLINE is False


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

    # WHO FEEDS IT is the profile's own poll (#1984): the window used to, and a panel
    # with no window then fed it nothing at all.
    poll = (ROOT / "panel" / "runtime" / "status.py").read_text(encoding="utf-8")
    assert "rt.recovery.note(" in poll, "nothing feeds the decision any more"
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "_paint_recovery" in shell, "the window never draws it"
    # Neither side may keep its own copy of the bookkeeping.
    assert "Recovery()" not in shell, "the window built a second Recovery"
    assert "Recovery()" not in poll, "the poll built a second Recovery"

    page = (ROOT / "panel" / "web" / "app" / "src" / "views" / "StateView.tsx").read_text(
        encoding="utf-8")
    assert "state.game.recovery" in page, "the page ignores what the api sends"


def _shell_method(name: str) -> str:
    """One method's source out of the shell, for the wiring assertions below."""
    shell = (ROOT / "panel" / "__main__.py").read_text(encoding="utf-8")
    at = shell.index("def %s" % name)
    return shell[at:shell.index("\n    def ", at + 10)]


def _health(deaf: bool, running: bool = True):
    """The verdict the status poll hands `_recovery_check` (#1911).

    Made by the real rule, so a change to the ladder shows up here rather than in a
    hand-written stand-in that agrees with nothing.
    """
    import profile_health as ph

    return ph.verdict(running=running,
                      plumbing=ph.LANDING,
                      server=ph.SILENT if deaf else ph.ANSWERING)


class _Press:
    """The shell, reduced to what `_recovery_check` touches. Records what it played."""

    def __init__(self, watchdog=True, gate_open=True):
        # …and whether anything may run at all (#1393). A client cure is held while this
        # profile's daemon is down — the state «Стоп всё» leaves — and the daemon cure
        # deliberately is not, or a stale daemon would hold the gate that holds its own
        # cure. Open by default: these cases are about a panel that is running.
        self._gate_open = gate_open
        self.played, self.said = [], []
        #: Daemon restarts asked for — the second cure, which has no recipe and so
        #: cannot show up in `played` (#1268).
        self.daemons = 0
        #: Daemon STARTS asked for — the third act family (#1410). Counted apart from
        #: `daemons` on purpose: a daemon that is down is started, and a restart over an
        #: empty port is the wrong act with the wrong sentence.
        self.starts = 0
        self.probes = 0
        self._watchdog = watchdog
        self._rt = self
        #: «Профиль работает». A switched-off profile's daemon is down BECAUSE it was
        #: switched off (#1882) — that reading is not a fault to cure.
        self.power = _Power()

    # -- the runtime half
    recovery = None                       # set per case, below
    def play_async(self, name, **kw):     # noqa: E301,D102 — the press being pinned
        self.played.append(name)
        return True

    # -- the window half
    def _paint_recovery(self, _state):    # noqa: D102 — drawing, not deciding
        pass

    def opt_bool(self, _key):             # noqa: D102 — the profile's «watchdog»
        return self._watchdog

    def opt_int(self, _key, low=None, high=None):
        """…and «выдержка после кика», in minutes (#1291). Zero: these cases are about
        the decision, and the wait has its own tests above."""
        return 0

    @property
    def settings(self):                   # `rt.settings.opt_bool` / `.opt_int` (#1984)
        return self

    def say(self, tag, key, **fmt):       # noqa: D102 — `rt.say`
        self.said.append(key)

    def dbg(self, _component="panel"):    # noqa: D102 — `rt.dbg(...)`, then `.info(...)`
        return self

    def _restart_daemon(self):            # noqa: D102 — the OTHER cure
        self.daemons += 1

    def _start_daemon(self) -> bool:      # noqa: D102 — the THIRD one (#1410)
        self.starts += 1
        return True

    @property
    def gate(self):                       # `self._rt.gate.alive()` inside `_act_on`
        return self

    def alive(self) -> bool:              # noqa: D102
        return self._gate_open

    def relaunch_held(self) -> bool:      # `self._rt.gate.relaunch_held()` (#1910)
        """Only the SWITCH holds a client relaunch — never the daemon it would cure."""
        return bool(self.power.off)

    @property
    def _dbg(self):                       # the held branch says so in debug.log
        return self

    def info(self, *args, **kw) -> None:  # noqa: D102
        pass

    def _probe_server(self, now) -> None:
        """The active question the poll asks the SERVER (#1911). Counted, never sent."""
        self.probes += 1

    def _act_on(self, said):              # noqa: D102 — the real one, borrowed below
        raise AssertionError("replaced by the real Panel._act_on in _drive")


class _Power:
    """`rt.power`, reduced to the one thing `_recovery_check` asks it (#1393, #1882)."""

    def __init__(self, stopped: bool = False) -> None:
        self.on = not stopped
        self.off = bool(stopped)


class _Found:
    """`game_process.Probe` as far as the wiring is concerned: is there a client."""

    def __init__(self, running=True, pid=4242):
        self.running, self.pid = bool(running), pid
        self.message = "client is running" if running else "no client"


def _health(deaf: bool, running: bool = True):
    """The verdict the status poll hands `_recovery_check` (#1911).

    Made by the real rule, so a change to the ladder shows up here rather than in a
    hand-written stand-in that agrees with nothing.
    """
    import profile_health as ph

    return ph.verdict(running=running,
                      plumbing=ph.LANDING,
                      server=ph.SILENT if deaf else ph.ANSWERING)


def _drive(link, kicked, watchdog=True, idle=10_000.0, stale=False, rounds=None,
           gate_open=True, warm=True, stopped=False):
    """Run the SHELL's own `_recovery_check` over a run of readings, unbound.

    The wiring is what is being pinned, not the decision — «`ACT_KICK` was announced and
    never played» lived entirely between the two, in a method that greps clean, and the
    same gap is where a daemon restart would go missing.
    """
    # THE READINGS AND THEIR DECISIONS ARE THE RUNTIME'S SINCE #1984, not the shell's:
    # a panel with no window has to take them too, so `_recovery_check` and `_act_on`
    # moved out of `panel/__main__.py` into `panel/runtime/status.py`. The stub below
    # stands in for the RUNTIME they are now given, which is the same surface it always
    # stood in for — the shell used to be its own.
    from panel.runtime import status as statusmod

    app = _Press(watchdog=watchdog, gate_open=gate_open)
    app.recovery = _Recovery()
    app.power = _Power(stopped)
    poll = statusmod.StatusPoll(app)
    poll._probe_server = lambda _now: setattr(app, "probes", app.probes + 1)
    real_idle = game_link.idle_sec
    game_link.idle_sec = lambda: idle      # nobody at the machine, deterministically
    # …AND THE CLOCK MOVES BETWEEN ROUNDS (#1702). A round stands for a status poll, and
    # a strike only counts when the poll has genuinely come round again: two readings
    # inside one cache window are one reading counted twice, which is what relaunched a
    # live client. Three rounds in the same microsecond are not three polls, so the
    # helper advances the clock by the interval it is pretending to be.
    import time as timemod

    clock = [timemod.time()]
    try:
        for _ in range(rounds if rounds is not None else DEAF_READINGS):
            poll._recovery_check(_Found(), _health(bool(link)), kicked, "", clock[0])
            clock[0] += 8.0
    finally:
        game_link.idle_sec = real_idle
    return app


def test_a_client_cure_is_held_while_the_panel_is_stopped():
    """«Стоп всё» is two acts, and this is what makes the second one hold (#1393).

    The press closes the client and stops this profile's daemon. A recovery that had
    never heard of it sees a client that is down — which is precisely what it is FOR —
    and puts it straight back, undoing the press within a poll. So the client cures ask
    the gate, and say nothing while it is shut: it has already said, once, that nothing
    may run.

    THE SWITCH IS WHAT SHUTS IT, not the daemon (#1910). «Профиль работает» is the
    durable record of «somebody stopped this account» (#1882), and it is the half of the
    old reading that was doing the work here all along.
    """
    app = _drive(LOST, kicked=True, gate_open=False, stopped=True)
    assert app.played == [], f"a switched-off profile put its client back: {app.played}"
    assert rec.ACT_KICK not in app.said, f"…and it was announced anyway: {app.said}"


def test_the_client_cure_is_not_held_by_the_daemon_it_would_cure():
    """THE OTHER CIRCLE, and the one that had `default` down for an afternoon (#1910).

    A daemon with no client to attach to is not alive, so the gate is shut — and this
    is the act that would give it a client. Held on `gate.alive()` it never ran: no
    client, seventeen daemon restarts, ZERO client restarts, the watchdog refused at
    every poll by the very thing it was there to fix. Same shape as
    `test_the_daemon_cure_is_not_held_by_the_gate_it_would_open` below, one act along.
    """
    app = _drive(LOST, kicked=True, gate_open=False, stopped=False)
    assert app.played, "the client was left down by the gate that was waiting for it"


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
    # THE FIRST thing said, not the only one (#1910). The run of readings a restart now
    # needs is longer than a kick's own, so the rounds that follow the kick's restart
    # rebuild an ordinary deaf run and meet the cooldown — which is a hold, correctly
    # said. What this case is about is that the kick was PLAYED and not merely announced.
    assert app.said and app.said[0] == rec.ACT_KICK, app.said
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
# #1268 — restarting the RIGHT thing, and #1911 — there is only one thing left
#
# Live on 2026-08-07 the client was relaunched six times in fifty minutes and the link
# never came back: the fault was the daemon holding a dead pid, and the answer was an
# ALTERNATION between two cures. There is no daemon any more (#1911) — the panel holds
# the client itself — so the state that alternation existed for cannot occur, and the
# whole section that pinned it went with it. What survives is the count it was built
# on: restarts that changed nothing are still counted and drawn, and they no longer
# decide anything.
# ---------------------------------------------------------------------------
def test_fruitless_restarts_are_counted_and_never_change_the_cure() -> None:
    """The evidence is still worth showing; there is nothing else to reach for."""
    r = _Recovery()
    now = 1000.0
    cures = []
    for _ in range(rec.FRUITLESS + 1):
        for i in range(DEAF_READINGS):
            said = r.note(LOST, now + i * 8, idle_sec=10_000.0)
            if said and said[0] in rec.RESTARTS:
                cures.append("client")
        now += rec.COOLDOWN_SEC + rec.PROBE_GAP_SEC * rec.PROBE_FAILS + 60
    assert cures == ["client"] * (rec.FRUITLESS + 1), cures
    assert r.state(now)["fruitless"] >= rec.FRUITLESS, r.state(now)

def _kicked_wait(r, now: float) -> int:
    """Arm a kick at `now` and return the wait it was given, in seconds.

    `KICK_STRIKES` readings, not one: a single unlucky poll may not cost a quarter of an
    hour of farming any more than it may cost a restart.
    """
    said = None
    for i in range(rec.KICK_STRIKES):
        said = r.note(LOST, now - (rec.KICK_STRIKES - 1 - i), idle_sec=None,
                      kicked=True)
    assert said is not None, "a kick must say something"
    return r.kick_hold_left(now)


def test_the_kick_wait_grows_while_the_kicks_keep_coming_back():
    """15 -> 30 -> 45 minutes. The policy was written for the `session_kick` trigger and
    never once applied — no poll trigger had ever fired (#1296) — so every kick there has
    ever been drew the same fifteen minutes however many of them there were.

    Measured from the RESTART, not from the reading: the question is «did the session
    hold», and that is time after the client was put back.
    """
    r = _Recovery()
    now = 1_000_000.0
    first = _kicked_wait(r, now)
    assert first == int(rec.KICK_HOLD_SEC), first

    r.note_kick_restart(now + 60)              # the client was put back…
    r.note(ONLINE, now + 90, talking=True)         # …came up…
    second_at = now + 120                      # …and was taken again straight away
    second = _kicked_wait(r, second_at)
    assert second == int(rec.KICK_HOLD_SEC + rec.KICK_HOLD_STEP_SEC), second

    r.note_kick_restart(second_at + 60)
    r.note(ONLINE, second_at + 90, talking=True)
    third_at = second_at + 120
    third = _kicked_wait(r, third_at)
    assert third == int(rec.KICK_HOLD_MAX_SEC), third

    #: …and it stops there rather than growing all night
    r.note_kick_restart(third_at + 60)
    r.note(ONLINE, third_at + 90)
    assert _kicked_wait(r, third_at + 120) == int(rec.KICK_HOLD_MAX_SEC)


def test_a_session_that_held_forgets_the_escalation():
    """The escalation is the memory of a FIGHT, and a fight that is over must be
    forgotten: an evening with two unrelated kicks in it is not one escalating incident."""
    r = _Recovery()
    now = 1_000_000.0
    _kicked_wait(r, now)
    r.note_kick_restart(now + 60)
    r.note(ONLINE, now + 90, talking=True)
    later = now + 60 + rec.KICK_STABILITY_SEC + 1        # the session held
    assert _kicked_wait(r, later) == int(rec.KICK_HOLD_SEC)


def test_coming_back_online_does_not_by_itself_forget_the_escalation():
    """«The client is up» is not «the session held». Clearing the escalation on the first
    online reading would reset it seconds after every relaunch, which is the same as not
    having one at all."""
    r = _Recovery()
    now = 1_000_000.0
    _kicked_wait(r, now)
    r.note_kick_restart(now + 60)
    for step in (70, 80, 90, 100):
        r.note(ONLINE, now + step)
    assert _kicked_wait(r, now + 120) == int(rec.KICK_HOLD_SEC + rec.KICK_HOLD_STEP_SEC)


def test_a_zero_hold_disarms_the_escalation_too():
    """A person who sets the hold to nothing wants the old behaviour back — no wait, and
    therefore no escalating wait either."""
    r = _Recovery()
    r.kick_hold_sec = 0.0
    now = 1_000_000.0
    r.note(LOST, now, idle_sec=None, kicked=True)
    assert r.kick_hold_left(now) == 0
    r.note_kick_restart(now + 5)
    r.note(LOST, now + 10, idle_sec=None, kicked=True)
    assert r.kick_hold_left(now + 10) == 0


def test_the_panel_stamps_the_kick_restart_with_the_clock_recovery_uses():
    """Both ends of that comparison must be in the same units. The poll hands `Recovery`
    `time.time()`; a `time.monotonic()` stamp here would be subtracted from an epoch one,
    every difference would look like hours, and every kick would read as a fresh incident
    — the escalation silently never escalating. Same shape as the two case-flipped
    comparisons this task already found, which is why it is pinned rather than trusted."""
    import re

    source = (Path(__file__).resolve().parent.parent
              / "panel" / "runtime" / "status.py").read_text(encoding="utf-8")
    stamp = re.search(r"note_kick_restart\((.*?)\)\s*$", source, re.M)
    assert stamp is not None, "the panel no longer stamps a kick restart"
    assert stamp.group(1).strip() == "time.time()", stamp.group(1)
    #: …and the act it hangs off is asked as a SET, never compared to one constant
    assert "recoverymod.KICK_ACTS" in source, "the kick act is not asked as a set"


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
