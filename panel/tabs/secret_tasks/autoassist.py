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
task has just finished», the tasks finish in their own time all day, and the race the
auto-loot listener exists to win — a human reading the same broadcast — is not a race
that exists here: helping pays the helper and the owner both, so nobody is competing
for a tile. A quiet look every few minutes is the whole requirement.

The rule is the same shape as the auto-loot one and read the same way — live, on every
tick, so raising the minimum takes effect at once and a half-typed box is «no bound»
rather than «level 0». The RANK half is not a setting: only UR and starred tasks are
helped, because that is what the daily plan pays for, and a star-only rule would fire
roughly never (live, one alliance task in two hundred carried a star while thirty-four
finished URs sat there waiting).
"""
from __future__ import annotations

import threading
import time

#: What the scenario says when the day's five are gone. Reword it there and this order
#: stops pausing and starts polling a spent budget every few minutes — the scenario says
#: so beside the line.
SPENT_MARK = "no assists left today"

#: …and what one landed help looks like in its output (`ACT assist_sent uuid=…`).
SENT_MARK = "assist_sent"

# The states the standing order reports on screen — the reasons a tick can end without a
# help. Every one of them used to look identical from outside, which is what «автолут не
# работает совершенно» turned out to be (#1227); this order is born with the answer.
STATE_OFF = "autoassist.state.off"            # not watching at all
STATE_WATCHING = "autoassist.state.watching"  # watching; nothing matched last look
STATE_HELPING = "autoassist.state.helping"    # a run is in flight
STATE_HELPED = "autoassist.state.helped"      # …and it helped this many
STATE_PAUSED = "autoassist.state.paused"      # the day's five are spent, until…
STATE_NO_LOGIN = "autoassist.state.no_login"  # the client is not in a session
STATE_ERROR = "autoassist.state.error"        # the last tick raised


class AutoAssist:
    """The watcher, and the rule the scenario is played with."""

    def __init__(self, rt, tab) -> None:
        self.rt = rt
        self.tab = tab
        self._stop = None            # threading.Event of the poll loop, while running
        self._running = False        # a scenario is in flight
        self._pause_until = 0.0      # wall clock the watcher may play again at
        self._warned_login = False   # "this client is not logged in" is said once
        self._state = (STATE_OFF, "")

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
        self._state = (STATE_WATCHING, "")
        self.tab.say("autoassist", "log.autoassist.on", rule=self.rule_text())
        threading.Thread(target=self._loop, args=(self._stop,), daemon=True).start()

    def stop(self) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            stop.set()
            self.tab.say("autoassist", "log.autoassist.off")
        self._state = (STATE_OFF, "")

    # -- the poll ------------------------------------------------------------
    def _loop(self, stop: threading.Event) -> None:
        """Look every few minutes until the checkbox is cleared.

        One bad tick costs a log line and not the order for the session, and the same
        complaint is printed once rather than on every poll — the auto-loot watcher's
        shape, for the same reason: nobody is watching this loop.
        """
        last_err = ""
        while True:
            try:
                self.tick()
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — one tick, never the loop
                err = f"{type(exc).__name__}: {exc}"
                self._state = (STATE_ERROR, type(exc).__name__)
                if err != last_err:
                    last_err = err
                    self.tab.say("autoassist", "log.autoassist.poll_error", error=err)
            if stop.wait(self.rt.settings.opt_float("autoassist_poll",
                                                    low=30.0, high=3600.0)):
                return

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
        helped, spent = 0, False

        def put(msg) -> None:
            nonlocal helped, spent
            line = str(msg)
            self.rt.put(f"[autoassist] {line}")
            if SENT_MARK in line:
                helped += 1
            if SPENT_MARK in line:
                spent = True

        try:
            outcome = self.rt.actions.play(
                "assist_secret_task", {"level": self.level_min() or 0}, on_event=put)
        except Exception as exc:      # noqa: BLE001 — a failed press, never the watcher
            self._state = (STATE_ERROR, type(exc).__name__)
            self.tab.say("autoassist", "log.autoassist.failed",
                         reason=f"{type(exc).__name__}: {exc}")
            self._running = False
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
        elif helped:
            self._state = (STATE_HELPED, str(helped))
            self.tab.say("autoassist", "log.autoassist.helped", n=helped)
        else:
            self._state = (STATE_WATCHING, "")
        self._running = False

    # -- the rule ------------------------------------------------------------
    def level_min(self) -> "int | None":
        """«Минимальный уровень» as an int, or None when the box is empty.

        Read live on every run, so raising it takes effect on the next one. Anything that
        is not a number reads as «no bound» — a half-typed entry must not silently become
        level 0, which is every level there is.
        """
        raw = str(self.tab.assist_level_var.get()).strip()
        return int(raw) if raw.isdigit() else None

    def rule_text(self) -> str:
        """The standing order in one phrase — what it will help with, in the log's words.

        The rank half is said every time and not only when it happens to bite: «UR или
        ★» is what the order IS, and a rule the log stops mentioning is a rule the next
        person has to read the source to find.
        """
        low = self.level_min()
        return (self.tab.t("autoassist.rule_min", lvl=low) if low is not None
                else self.tab.t("autoassist.rule_any"))

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
