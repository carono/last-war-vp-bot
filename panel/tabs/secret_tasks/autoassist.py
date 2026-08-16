"""«Автопомощь» — the standing order that spends the day's five helps (#1272).

A SECOND budget on this tab and a different one from «Автолут ★». Robbing spends
`hero.dispatch.steal` on strangers' tiles; helping spends `hero.dispatch.assist` on the
alliance's OWN finished tasks, has a cap of its own (`GetDispatchSetting("aid_count")`,
five live) and is what the daily plan calls «помочь выполнить 5 секретных заданий ранга
UR или Звезда». Spending one does not touch the other.

THE WHOLE ABILITY IS THE SCENARIO. `actions/assist_secret_task.md` re-reads the
alliance's list, parks the rule, gates on the budget and presses; this class is a clock
and a checkbox. There is nothing to park from the panel first — unlike the robbery
(#1188), whose targets have to be resolved off a map scan before a recipe can spend
them, the tasks worth helping are already in the client's own table, so the recipe can
choose for itself and the panel has no queue to fill.

Which is why this is a poll rather than a listener. There is no push saying «a mate's
task has just finished» — forty-five minutes of the live wire carried some three
thousand messages and not one of the `push.hero.dispatch.task.*` family, which the client
keeps for its OWN tasks (#1294) — and the tasks finish in their own time all day.

BUT A POLL ALONE IS NOT ENOUGH FOR THE STAR, and that is the one thing this class does
beyond keeping time (#1294). A ripe star is taken by alliancemates in under two minutes;
live, the day's only one came and went between two five-minute looks and `star_ready`
never read non-zero. Helping is not competitive in general — it pays the helper and the
owner both — but the STARS are, because everybody's daily plan wants the same rare thing.

The answer costs nothing extra all day, because the client already knows the moment. A
task carries its own `completionTime`, so the ordinary poll reads the star's maturity
hours ahead (live: 78, 79 and 233 minutes) and this class simply SLEEPS UNTIL IT.
A few seconds before, it plays `actions/assist_star_sprint.md`, which presses as fast as
the channel allows until the server answers. The period is unchanged, no reading happens
while the star ripens, and the fast pressing lasts seconds — «жать часто, но только там,
где секунды решают».

The rule is the same shape as the auto-loot one and read the same way — live, on every
tick, so raising the minimum takes effect at once and a half-typed box is «no bound»
rather than «level 0». The RANK half is not a setting: only UR and starred tasks are
helped, because that is what the daily plan pays for.

WHICH OF THE TWO GOES FIRST IS THE ORDER'S WHOLE POINT (#1292). A star outranks every UR
whatever their levels, and a star still counting down RESERVES one of the day's five
rather than letting a UR spend it — the scenario decides all of that and this class only
repeats it. It needs saying because a star is rare: live, one alliance task in two
hundred carried one while thirty-four finished URs sat there waiting, so a budget that
takes whatever is ready is empty by the time the day's star matures. The same rarity is
why the waiting has a floor — `autoassist_star_wait_min`, plus the task's own expiry and
the daily reset — because thirty-four unspent URs is the other way to throw five helps
away.
"""
from __future__ import annotations

import re
import threading
import time

#: What the scenario says when the day's five are gone. Reword it there and this order
#: stops pausing and starts polling a spent budget every few minutes — the scenario says
#: so beside the line.
SPENT_MARK = "no assists left today"

#: …and what one landed help looks like in its output (`ACT assist_sent uuid=…`).
SENT_MARK = "assist_sent"

#: …and the line that says the budget is being HELD rather than spent (#1292). The
#: scenario decides that — a star still counting down outranks every ready UR, so it
#: reserves one of the day's five — and this is the panel repeating the decision, with
#: the star's level and its countdown in whole minutes exactly as the game gave them.
#: Reword the `LOG` line in `actions/assist_secret_task.md` and this order goes back to
#: saying «наблюдаю» about a tick that deliberately did nothing.
WAIT_LINE = re.compile(
    r"waiting for star (\d+) \(ready in (-?\d+) min\) — holding (\d+) of (\d+)")

#: …and the other way the priority can fall: nothing starred is coming, so the URs get
#: the budget. Said in the operator's own language below, and only when helps were
#: actually made — a poll every five minutes announcing «звёзд нет» about a day with
#: nothing to help at all would bury the lines that matter.
NO_STAR_LINE = re.compile(r"no star ripening today — taking UR")

#: The countdown in SECONDS, which is what the sprint is scheduled off (#1294). The
#: scenario says it whenever a star is on its way; the minutes line beside it is for the
#: person, this one is for the clock. A star matures at a moment the client knows to the
#: millisecond, so this is read once every ordinary poll and nothing has to poll faster
#: to find it.
COUNTDOWN_LINE = re.compile(r"star countdown: (-?\d+) s")

#: What `actions/assist_star_sprint.md` says when a sprint ends. Three outcomes, and they
#: must stay distinguishable: «took it», «somebody else did» and «the server never
#: answered» are three different days.
TAKEN_LINE = re.compile(r"assist_star_taken — ★(\d+) helped after (\d+) press")
MISSED_LINE = re.compile(r"assist_star_missed — ★(\d+) not taken after (\d+) press")

# The states the standing order reports on screen — the reasons a tick can end without a
# help. Every one of them used to look identical from outside, which is what «автолут не
# работает совершенно» turned out to be (#1227); this order is born with the answer.
STATE_OFF = "autoassist.state.off"            # not watching at all
STATE_WATCHING = "autoassist.state.watching"  # watching; nothing matched last look
STATE_HELPING = "autoassist.state.helping"    # a run is in flight
STATE_HELPED = "autoassist.state.helped"      # …and it helped this many
STATE_PAUSED = "autoassist.state.paused"      # the day's five are spent, until…
STATE_WAITING = "autoassist.state.waiting"    # holding a help for a star, until…
STATE_NO_LOGIN = "autoassist.state.no_login"  # the client is not in a session
STATE_ERROR = "autoassist.state.error"        # the last tick raised
STATE_SPRINT = "autoassist.state.sprint"      # pressing through a star's last seconds


class AutoAssist:
    """The watcher, and the rule the scenario is played with."""

    def __init__(self, rt, tab) -> None:
        self.rt = rt
        self.tab = tab
        self._stop = None            # threading.Event of the poll loop, while running
        # …and what interrupts its sleep: a run that has just learned when the next star
        # is due, or the checkbox being cleared. A tick returns before its run finishes,
        # so without this the appointment would be five minutes late every time (#1294).
        self._wake = threading.Event()
        self._running = False        # a scenario is in flight
        self._pause_until = 0.0      # wall clock the watcher may play again at
        self._warned_login = False   # "this client is not logged in" is said once
        self._said_wait = None       # the last «жду звезду» announced, so it is said once
        self._state = (STATE_OFF, "")
        # When the nearest ripening star is due, as a wall clock, or 0 for «none known».
        # Read off the ordinary poll's own countdown line and nothing else: the game
        # already knows the moment to the millisecond, so this is the whole of the
        # scheduling (#1294).
        self._star_at = 0.0
        # The tally the order shows and the log repeats — what the sprint actually cost
        # and bought. Kept for the session rather than for the day: it is a measurement
        # of the mechanism, and a counter that survives a restart would quietly mix two.
        self._sprints = 0            # sprints played
        self._presses = 0            # presses they made, all told
        self._taken = 0              # stars the SERVER confirmed
        self._missed = 0             # …and stars that went to somebody else

    @property
    def running(self) -> bool:
        return self._stop is not None

    # -- start / stop --------------------------------------------------------
    def toggle(self) -> None:
        if self.tab.autoassist_var.get():
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        if self._stop is not None:               # already watching
            return
        self._stop = threading.Event()
        self._pause_until = 0.0
        self._warned_login = False
        self._said_wait = None
        self._star_at = 0.0
        self._state = (STATE_WATCHING, "")
        self.tab.say("autoassist", "log.autoassist.on", rule=self.rule_text())
        threading.Thread(target=self._loop, args=(self._stop,), daemon=True).start()

    def stop(self) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            stop.set()
            self._wake.set()                  # …and do not sit out the rest of a sleep
            self.tab.say("autoassist", "log.autoassist.off")
        self._state = (STATE_OFF, "")

    # -- the poll ------------------------------------------------------------
    def _loop(self, stop: threading.Event) -> None:
        """Look every few minutes — and be awake for the second a star matures.

        One bad tick costs a log line and not the order for the session, and the same
        complaint is printed once rather than on every poll — the auto-loot watcher's
        shape, for the same reason: nobody is watching this loop.

        THE PERIOD NEVER CHANGES; THE SLEEP DOES (#1294). A ripe star is gone in under
        two minutes and a five-minute look cannot land inside that window — but nothing
        has to look faster to find one, because the task carries its own
        `completionTime` and the ordinary poll reads it hours ahead. So the wait is cut
        short exactly once per star: the loop wakes a few seconds before it is due, plays
        the sprint, and goes back to the ordinary pace. No extra game read happens while
        the star ripens, which is the whole difference between this and a shorter poll.

        WHICH IS WHY THE SLEEP IS INTERRUPTIBLE AND THE POLL HAS ITS OWN DEADLINE. A tick
        hands the run to a worker and returns at once, so the countdown the run reads
        arrives AFTER the sleep has already been sized: without a wake-up the appointment
        would first be honoured on the next ordinary look, five minutes late, which is
        precisely the failure this exists to fix. `_wake` is set when a run learns
        something and by `stop()`, and `next_poll` keeps the ordinary look on its own
        schedule so an extra wake-up costs a recalculation and never a second run.
        """
        last_err = ""
        next_poll = 0.0                  # the first look is immediate
        while True:
            self._wake.clear()
            try:
                if self._sprint_due():
                    self.sprint()
                elif time.time() >= next_poll:
                    next_poll = time.time() + self.rt.settings.opt_float(
                        "autoassist_poll", low=30.0, high=3600.0)
                    self.tick()
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — one tick, never the loop
                err = f"{type(exc).__name__}: {exc}"
                self._state = (STATE_ERROR, type(exc).__name__)
                if err != last_err:
                    last_err = err
                    self.tab.say("autoassist", "log.autoassist.poll_error", error=err)
            self._wake.wait(self._sleep_for(next_poll))
            if stop.is_set():
                return

    def _sleep_for(self, next_poll: float = 0.0) -> float:
        """How long to sleep next: until the next ordinary look, unless a star is sooner.

        Never below half a second — a schedule that lands a shade early is the point, and
        one that lands a shade early over and over is a spin loop.
        """
        poll = self.rt.settings.opt_float("autoassist_poll", low=30.0, high=3600.0)
        wait = poll if next_poll <= 0 else next_poll - time.time()
        due = self._sprint_at()
        if due > 0:
            wait = min(wait, due - time.time())
        return max(0.5, min(poll, wait))

    def _sprint_at(self) -> float:
        """The wall clock the sprint should START at, or 0 when there is nothing to run.

        The star's own moment, minus the operator's lead. A lead of 0 turns the sprint
        off outright — the ordinary poll then takes whatever it happens to find ready,
        which is the behaviour there was before this existed.
        """
        lead = self.sprint_lead_sec()
        if not lead or self._star_at <= 0:
            return 0.0
        return self._star_at - lead

    def _sprint_due(self) -> bool:
        """Whether this wake-up is the scheduled one. Half a second of slack, because
        `Event.wait` is not a real-time clock and arriving 20 ms early must not count as
        «not yet» and cost another whole period."""
        due = self._sprint_at()
        return bool(due) and time.time() >= due - 0.5

    def tick(self) -> None:
        """One look: play the scenario unless something says not to.

        Nothing is read out of the game here — the recipe re-reads the alliance list
        itself and gates on its own budget, which is the only reading that can be trusted
        anyway (the panel's roster is a snapshot from whenever the tab was last
        refreshed). All this decides is WHEN.
        """
        if self._running:                             # a run is still going
            self._state = (STATE_HELPING, "")
            return
        if time.time() < self._pause_until:           # the day's five are spent
            self._state = (STATE_PAUSED, _hhmm(self._pause_until))
            return
        # A client at the login screen answers everything and every answer is a
        # plausible-looking lie (#1227): its alliance list is empty and its budget reads
        # full, so a run there would report «нечего помочь» for ever without saying why.
        if not self.session_ready():
            self._state = (STATE_NO_LOGIN, "")
            if not self._warned_login:
                self._warned_login = True
                self.tab.say("autoassist", "log.autoassist.no_login")
            return
        self._warned_login = False
        self._running = True
        threading.Thread(target=self._play, daemon=True).start()

    def session_ready(self) -> bool:
        """Whether the client is far enough into a session to be helped through.

        The clock is the one question a login screen cannot fake (`game_clock`).
        """
        import game_clock             # lazy: keeps panel start-up free of it
        try:
            return game_clock.session_ready(self.rt.game.evaluator())
        except Exception:             # noqa: BLE001 — no daemon, no game, no session
            return False

    def _play(self) -> None:
        """Play `actions/assist_secret_task.md` with the rule the boxes hold.

        Straight through `rt.actions`, on this worker, for the reason the auto-loot
        watcher's `_spend` gives: the interlock this order has is «one run at a time»,
        and wrapping it in a second claim would invent a refusal in the middle of it.
        """
        helped, spent, waiting, no_star = 0, False, None, False
        # «No star coming» until the scenario says otherwise. Cleared here rather than
        # left standing, or a star that has since been helped by somebody else keeps its
        # appointment for ever and the sprint fires at nothing every five minutes.
        self._star_at = 0.0

        def put(msg) -> None:
            nonlocal helped, spent, waiting, no_star
            line = str(msg)
            self.rt.put(f"[autoassist] {line}")
            if SENT_MARK in line:
                helped += 1
            if SPENT_MARK in line:
                spent = True
            if NO_STAR_LINE.search(line):
                no_star = True
            due = COUNTDOWN_LINE.search(line)
            if due is not None:
                # The scenario's own arithmetic on the GAME's clock, turned into a wall
                # clock here and nowhere else. A negative countdown means the star is
                # already ripe — the appointment is now, not in the past.
                secs = int(due.group(1))
                self._star_at = time.time() + max(secs, 0)
            held = WAIT_LINE.search(line)
            if held is not None:
                waiting = tuple(int(g) for g in held.groups())

        try:
            outcome = self.rt.actions.play(
                "assist_secret_task",
                {"level": self.level_min() or 0,
                 "star_wait_min": self.star_wait_min()}, on_event=put)
        except Exception as exc:      # noqa: BLE001 — a failed press, never the watcher
            self._state = (STATE_ERROR, type(exc).__name__)
            self.tab.say("autoassist", "log.autoassist.failed",
                         reason=f"{type(exc).__name__}: {exc}")
            self._done()
            return
        if not outcome:
            # The scenario's own reason, verbatim — it is the authority on why it
            # stopped and the panel's job is to repeat it, not to re-diagnose it.
            self._state = (STATE_ERROR, "")
            self.tab.say("autoassist", "log.autoassist.failed",
                         reason=outcome.reason or "?")
        elif spent:
            pause = self.rt.settings.opt_int("autoassist_pause_min",
                                             low=1, high=1440) * 60
            self._pause_until = time.time() + pause
            self._state = (STATE_PAUSED, _hhmm(self._pause_until))
            self.tab.say("autoassist", "log.autoassist.spent", mins=int(pause // 60))
        elif waiting is not None:
            # BEFORE «помог N», deliberately (#1292). Both can be true in one tick — a
            # star ripens while the URs beneath it spend what the reserve does not need
            # — and of the two it is the holding that has to be on screen: «помог 3»
            # about a budget that is deliberately keeping its last two back reads as a
            # standing order that has stopped, which is the complaint #1227 was.
            lvl, mins, held, left = waiting
            self._state = (STATE_WAITING,
                           "%s (★%d)" % (_hhmm(time.time() + max(mins, 0) * 60), lvl))
            # …and in the log, in the operator's own language — but only when the fact
            # has moved. The scenario says it on every poll by design (it is a branch,
            # not a report), and a line every five minutes about the same star waiting
            # the same wait is how the lines that matter get buried.
            if waiting != self._said_wait:
                self._said_wait = waiting
                self.tab.say("autoassist", "log.autoassist.waiting",
                             lvl=lvl, mins=mins, held=held, left=left)
            if helped:
                self.tab.say("autoassist", "log.autoassist.helped", n=helped)
        elif helped:
            self._said_wait = None
            self._state = (STATE_HELPED, str(helped))
            # «Звёзд нет — беру UR» carries its reason when that is what happened, so a
            # spent help can always be told from the rule that spent it.
            self.tab.say("autoassist",
                         "log.autoassist.no_star" if no_star
                         else "log.autoassist.helped", n=helped)
        else:
            self._said_wait = None
            self._state = (STATE_WATCHING, "")
        self._done()

    # -- the sprint ------------------------------------------------------------
    def sprint(self) -> None:
        """The scheduled wake-up: the star is about to mature, so go and press.

        Same three gates as an ordinary tick — one run at a time, a spent day, a client
        that is not in a session — because every one of them is as true here as there.
        A missed appointment is dropped rather than retried: the next ordinary poll
        re-reads the countdown, and a star we were too busy for at the moment it matured
        is not a star a minute of catching up will win.
        """
        if self._running:
            self._state = (STATE_HELPING, "")
            self._star_at = 0.0
            return
        if time.time() < self._pause_until:
            self._state = (STATE_PAUSED, _hhmm(self._pause_until))
            self._star_at = 0.0
            return
        if not self.session_ready():
            self._state = (STATE_NO_LOGIN, "")
            if not self._warned_login:
                self._warned_login = True
                self.tab.say("autoassist", "log.autoassist.no_login")
            self._star_at = 0.0
            return
        self._warned_login = False
        # The appointment is spent whatever happens next: kept here rather than after the
        # run, so a sprint that raises still cannot be scheduled twice for one star.
        self._star_at = 0.0
        self._running = True
        threading.Thread(target=self._play_sprint, daemon=True).start()

    def _play_sprint(self) -> None:
        """Play `actions/assist_star_sprint.md` and count what it cost and bought.

        The recipe is the authority on everything below it: it re-reads the list, arms
        one star, presses until the SERVER answers and says which of the three things
        happened. This adds the tally — presses, stars taken, stars lost — because
        «жать чаще» is a claim that has to be measurable, and a sprint that presses forty
        times to lose every race is a different answer from one that presses three to
        win.
        """
        self._state = (STATE_SPRINT, "")
        self._sprints += 1
        taken = missed = None
        started = time.time()

        def put(msg) -> None:
            nonlocal taken, missed
            line = str(msg)
            self.rt.put(f"[autoassist] {line}")
            hit = TAKEN_LINE.search(line)
            if hit is not None:
                taken = (int(hit.group(1)), int(hit.group(2)))
            lost = MISSED_LINE.search(line)
            if lost is not None:
                missed = (int(lost.group(1)), int(lost.group(2)))

        try:
            outcome = self.rt.actions.play(
                "assist_star_sprint",
                {"level": self.level_min() or 0,
                 "window_sec": self.sprint_window_sec()}, on_event=put)
        except Exception as exc:      # noqa: BLE001 — a failed press, never the watcher
            self._state = (STATE_ERROR, type(exc).__name__)
            self.tab.say("autoassist", "log.autoassist.failed",
                         reason=f"{type(exc).__name__}: {exc}")
            self._done()
            return
        secs = round(time.time() - started, 1)
        if not outcome:
            self._state = (STATE_ERROR, "")
            self.tab.say("autoassist", "log.autoassist.failed",
                         reason=outcome.reason or "?")
        elif taken is not None:
            lvl, presses = taken
            self._taken += 1
            self._presses += presses
            self._state = (STATE_HELPED, "★%d" % lvl)
            self.tab.say("autoassist", "log.autoassist.sprint_taken",
                         lvl=lvl, presses=presses, secs=secs)
        elif missed is not None:
            lvl, presses = missed
            self._missed += 1
            self._presses += presses
            self._state = (STATE_WATCHING, "")
            self.tab.say("autoassist", "log.autoassist.sprint_missed",
                         lvl=lvl, presses=presses, secs=secs)
        else:
            # The recipe found nothing starred to press — the star was helped, cancelled
            # or expired between the poll that scheduled this and the moment it arrived.
            self._state = (STATE_WATCHING, "")
        self._done()
        # Whatever happened, the list has moved: a star was taken out of it, or somebody
        # else took it. The next ordinary tick re-reads the countdown and re-schedules.
        self._said_wait = None

    def _done(self) -> None:
        """A run has finished: let the loop re-size its sleep around what it learned.

        The tick that started it returned long ago, so the countdown it read arrived
        after the sleep was already chosen. Without this the appointment would be kept
        on the NEXT ordinary look — five minutes after the star, which is the failure
        this whole thing exists to fix (#1294).
        """
        self._running = False
        self._wake.set()

    def sprint_lead_sec(self) -> int:
        """How many seconds BEFORE the star matures the pressing starts.

        A setting rather than a box, like the poll and the pause beside it. `0` switches
        the sprint off altogether and leaves the ordinary poll to take whatever it finds
        ready — which is the behaviour that lost the star in the first place, so it is
        not the default.
        """
        return self.rt.settings.opt_int("autoassist_sprint_lead_sec", low=0, high=120)

    def sprint_window_sec(self) -> int:
        """How long the pressing may last, from the moment the target is armed."""
        return self.rt.settings.opt_int("autoassist_sprint_window_sec", low=1, high=300)

    def tally_text(self) -> str:
        """The sprint's measurement in one phrase, or empty until one has run.

        On the tab and on the phone both. It answers the question the change was made
        to answer — how many presses a star costs and how many of them are won — and it
        is empty rather than «0/0» before there is anything to report.
        """
        if not self._sprints:
            return ""
        return self.tab.t("autoassist.tally", taken=self._taken, missed=self._missed,
                          presses=self._presses)

    # -- the rule ------------------------------------------------------------
    def level_min(self) -> "int | None":
        """«Минимальный уровень» as an int, or None when the box is empty.

        Read live on every run, so raising it takes effect on the next one. Anything that
        is not a number reads as «no bound» — a half-typed entry must not silently become
        level 0, which is every level there is.
        """
        # Through the tab's mirror, never the Tk variable: this runs on the
        # watcher's own worker, and reading a variable off the event loop's
        # thread threw away the first look of every session (#1416).
        raw = self.tab.rule("assist_level_var").strip()
        return int(raw) if raw.isdigit() else None

    def star_wait_min(self) -> int:
        """How long a ripening star may hold one of the day's five back, in minutes.

        A setting rather than a box on the page: it is a pace, like the poll and the
        pause beside it in «Настройки», and it is read live on every run so shortening
        it late in the day takes effect on the next look. `0` means «as long as the
        task's own expiry and the daily reset allow» — the scenario's own floor.
        """
        return self.rt.settings.opt_int("autoassist_star_wait_min", low=0, high=1440)

    def rule_text(self) -> str:
        """The standing order in one phrase — what it will help with, in the log's words.

        The rank half is said every time and not only when it happens to bite: «сначала
        звезда, UR только если звёзд нет» is what the order IS, and a rule the log stops
        mentioning is a rule the next person has to read the source to find. The wait
        bound rides with it for the same reason — it is the one number that decides
        whether a held help is ever spent.
        """
        low, wait = self.level_min(), self.star_wait_min()
        rank = (self.tab.t("autoassist.rule_min", lvl=low) if low is not None
                else self.tab.t("autoassist.rule_any"))
        # Two phrases rather than one key with a number in it: «0» is not a duration but
        # a different rule («as long as the day allows»), and a sentence built to hold a
        # number cannot say that without reading as «не дольше сколько угодно минут».
        held = (self.tab.t("autoassist.rule_wait", wait=wait) if wait
                else self.tab.t("autoassist.rule_wait_any"))
        return f"{rank} · {held}"

    # -- what it is doing right now --------------------------------------------
    def state(self) -> tuple:
        """(locale key, the datum that goes beside it) — the live state of the order."""
        return self._state

    def state_text(self) -> str:
        """The same thing as one phrase, in the panel's language."""
        key, datum = self._state
        text = self.tab.t(key)
        return f"{text} {datum}" if datum else text


def _hhmm(when: float) -> str:
    """A wall-clock stamp as HH:MM — a time to compare with the clock on screen."""
    return time.strftime("%H:%M", time.localtime(when))
