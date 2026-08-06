"""«Автолут ★» — the standing order that spends the day's five robberies.

THIS IS A BUDGET, and that is what makes it the delicate part of the tab. Five raids a
day is the whole allowance, so a rule that is off by one level does not fail loudly —
it quietly spends a robbery on a level-6 star that a 7 could have had, and nobody finds
out until the reset (#1099). Everything here follows from that:

* **the rule is ONE number: the minimum level** (#1256). «Уровень от / до» was a range
  whose TOP was the level actually robbed, so «от 1 до 7» left every 6 alone however
  long it sat there — a rule two boxes wide that only one of the boxes decided. It is
  «минимальный уровень» now: this level and everything above it, best first;
* **the rule is read live, every tick**, so raising it takes effect at once;
* **a half-typed box is "no bound"**, never "level 0";
* **the event-driven listener is RESTARTED when the rule changes**, since it is a
  subprocess started with a fixed one — that is the exact trap #1099 closed for the
  poll and would have left open here;
* **a uuid already fired at is never fired at again this session**, so a poll on a
  spent budget does not burn the allowance on a target that cannot pay;
* **«не грабить на своём сервере» travels the same way** — it takes the tiles at home
  out of the choice here, and is handed to the listener, which chooses for itself.

THE WATCHER PICKS OUT OF THE TAB'S OWN LIST (#1256), through
:meth:`~panel.tabs.secret_tasks.tab.SecretTasksTab.rob_candidates`. It used to re-read
the sources for itself — the live VM and the capture checkpoint, filtered by a copy of
the rule — which meant the panel's list and the thing spending the panel's robberies
were two different answers to the same question: a tile the list had dropped as expired
could still be a target here, and a tile the list was drawing as ready might not be one.
The list is the model every source fills (the capture, the client's own tables, the
alliance pushes) and the one every actuality check already runs against, so it is the
only sensible thing to choose out of. What is CHOSEN then travels to the child by name
(`steal_secret_task.py --targets uuid:server,…`): the child re-derives nothing, which is
the same disagreement one step further down.

Two paths on purpose. The listener robs a *shared* secret task the instant its push
crosses the wire (< 1 s), which is the case a human used to win; the poll is the slower
safety net over the whole list. The listener is a sniffer of its own by necessity — it
is racing a person who is watching the same broadcast — and it is told the same rule in
words rather than handed a list, because the tile it robs is one nothing has listed yet.
"""
from __future__ import annotations

import os
import threading
import time

from ...runtime.paths import TOOLS

#: How long after the last keystroke the listener is re-spawned with the new rule.
#: Debounced so typing "1" then "7" restarts once, not per keystroke — spawning a
#: capture is not free.
RESTART_MS = 1500

# The states the standing order reports on screen. They are the reasons a tick can end
# without a robbery — every one of which used to look identical from outside: nothing in
# the log, nothing on the tab, and no way to tell a watcher waiting for a star from one
# that was never started (#1227).
STATE_OFF = "secret.autoloot.state.off"            # not watching at all
STATE_WATCHING = "secret.autoloot.state.watching"  # watching; the rule matches nothing
STATE_TARGETS = "secret.autoloot.state.targets"    # …matches this many tiles
STATE_ROBBING = "secret.autoloot.state.robbing"    # a robbery is in flight
STATE_PAUSED = "secret.autoloot.state.paused"      # the day's budget is spent, until…
STATE_NO_SOURCE = "secret.autoloot.state.no_source"  # the list has nothing in it yet
STATE_NO_OWN = "secret.autoloot.state.no_own"      # own server unknown, box ticked
STATE_NO_LOGIN = "secret.autoloot.state.no_login"  # the client is not in a session
STATE_ERROR = "secret.autoloot.state.error"        # the last tick raised


class AutoLoot:
    """The watcher, the listener, and the rule both of them obey."""

    def __init__(self, rt, tab) -> None:
        self.rt = rt
        self.tab = tab
        self._stop = None            # threading.Event of the poll loop, while running
        self._proc = None            # one robbery child at a time
        self._push_proc = None       # the event-driven listener, when running
        self._seen: set = set()      # uuids sent this session (no re-tries)
        self._pause_until = 0.0      # wall clock the watcher may fire again at
        self._warned = False         # "the list is empty" is said once per run
        self._warned_own = False     # so is "the own server cannot be read"
        self._warned_login = False   # …and "this client is not logged in"
        # What the standing order is doing right now, as (locale key, datum beside it).
        # A watcher that finds nothing to rob says nothing — which is indistinguishable
        # from one that is not running at all, and is exactly what «автолут не работает
        # совершенно» turned out to be (#1227). Every early return below writes here, and
        # the tab draws it under the checkbox, so silence has a reason on screen.
        self._state = (STATE_OFF, "")

    @property
    def running(self) -> bool:
        return self._stop is not None

    # -- start / stop --------------------------------------------------------
    def toggle(self) -> None:
        if self.tab.autoloot_var.get():
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        if self._stop is not None:               # already watching
            return
        self._stop = threading.Event()
        self._seen.clear()
        self._pause_until = 0.0
        self._warned = self._warned_own = self._warned_login = False
        self._state = (STATE_WATCHING, "")
        self.tab.say("autoloot", "log.autoloot.on", rule=self.rule_text())
        if not self.tab.capture.running:
            self.tab.say("autoloot", "log.autoloot.no_monitor")
        self.start_push()
        threading.Thread(target=self._loop, args=(self._stop,), daemon=True).start()

    def stop(self) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            stop.set()
            self.tab.say("autoloot", "log.autoloot.off")
        self._state = (STATE_OFF, "")
        self.stop_push()

    # -- the event-driven listener -------------------------------------------
    def start_push(self) -> None:
        """Spawn the listener that robs a shared secret task on its push (#1124).

        It sniffs the game stream itself (no dependence on the «Мониторинг» capture) and
        acts through this profile's daemon, so it is given the same rule the poll obeys —
        otherwise it would rob below «минимальный уровень». It is the ONE thing here that
        does not choose out of the tab's list, and it cannot: the tile it fires at is one
        the push has only just announced, and waiting for it to reach a table is losing
        the race the listener exists to win.
        """
        if self._push_proc is not None:
            return
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "secret_share_autoloot.py"),
               # `--star-max` with no `--level-max` is "starred, at this level or above"
               # — the single-bound rule, in the listener's own words.
               "--star-max", "--limit", str(self.limit()),
               # Every share it decodes is marked as shared, whether or not the rule
               # takes it (#1245): «worth one of my five robberies» and «the alliance
               # has already been shown this» are different questions, and the tab
               # draws the second on both of its tables.
               "--shared-json", self.rt.profiles.secret_shared_json()]
        low = self.level_min()
        if low is not None:
            cmd += ["--level-min", str(low)]
        # The listener resolves the own server itself (it is spawned at boot, when the
        # client may not be logged in yet), so the box travels as a flag, not a number.
        if self.tab.skip_own_var.get():
            cmd.append("--skip-own-server")
        proc = self.rt.children.spawn_raw(cmd, "autoloot")
        if proc is None:
            return
        self._push_proc = proc
        threading.Thread(target=self._push_reader, args=(proc,), daemon=True).start()

    def stop_push(self) -> None:
        proc, self._push_proc = self._push_proc, None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:                    # noqa: BLE001 — already gone is fine
                pass

    def restart_push(self) -> None:
        """Re-spawn the listener so a changed «минимальный уровень» takes effect."""
        if self._stop is None:                   # auto-loot was unticked meanwhile
            return
        self.stop_push()
        self.start_push()

    def range_changed(self) -> None:
        """The rule was changed (the level, or «не грабить на своём сервере»). Bounce
        the listener onto it, debounced.

        The poll re-reads the rule live every tick, but the listener is a subprocess
        started with a fixed one — a level typed while auto-loot is on would otherwise
        keep robbing to the OLD minimum, and a box ticked after it started would not
        reach it at all.
        """
        if self._stop is None:
            return
        self.rt.tick.arm("autoloot_push_restart", RESTART_MS, self.restart_push)

    def _push_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if line:
                    self.rt.put(f"[autoloot] {line}")
        except Exception:                        # noqa: BLE001 — the pipe closed
            pass
        if self._push_proc is proc:
            self._push_proc = None

    # -- the poll ------------------------------------------------------------
    def _loop(self, stop: threading.Event) -> None:
        """Poll the list until the checkbox is cleared.

        A whole tick is wrapped: the watcher is a background loop the operator cannot
        see, so one bad tick must cost a log line and not the auto-loot for the session.
        The same complaint is printed once and not on every poll after it.
        """
        last_err = ""
        while True:
            try:
                self.tick()
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — never let one tick kill the loop
                err = f"{type(exc).__name__}: {exc}"
                self._state = (STATE_ERROR, type(exc).__name__)
                if err != last_err:
                    last_err = err
                    self.tab.say("autoloot", "log.autoloot.poll_error", error=err)
            if stop.wait(self.rt.settings.opt_float("autoloot_poll", low=1.0, high=600.0)):
                return

    def tick(self) -> None:
        """One look at OUR LIST: fire when the rule has a target we have not sent yet.

        The list is the tab's own model (`SecretTasksTab.rob_candidates`) — the one the
        capture fills off the wire, the one the client's own tables seed and the alliance
        pushes update, and the one the ready-row poll re-verifies against the game every
        thirty seconds, dropping whatever it can no longer confirm. So the tiles this
        weighs are exactly the tiles the person is looking at, which is the whole point
        of #1256: before it, the watcher re-read the sources for itself and the two could
        disagree about what was even on the map.

        A row the list is wrong about costs a REFUSED send, not a robbery: the budget is
        spent server-side and an errorCode leaves `todayStealNum` where it was.
        """
        if self._proc is not None:                    # a robbery is still running
            self._state = (STATE_ROBBING, "")
            return
        if time.time() < self._pause_until:           # the day's budget is spent
            self._state = (STATE_PAUSED, _hhmm(self._pause_until))
            return
        # «Не грабить на своём сервере» is a prohibition, so an unknown own server stops
        # the tick rather than letting it through: robbing a neighbour the operator asked
        # to be left alone cannot be taken back, and a paused watcher says so in the log.
        if self.tab.skip_own_var.get() and not self.tab.own_server():
            self._state = (STATE_NO_OWN, "")
            if not self._warned_own:
                self._warned_own = True
                self.tab.say("autoloot", "log.autoloot.no_own_server")
            return
        self._warned_own = False
        if not self.tab.has_rows():
            # Nothing has reached the list yet — no capture has flushed, no read has
            # landed, no push has come. Say so once, not on every poll.
            self._state = (STATE_NO_SOURCE, "")
            if not self._warned:
                self._warned = True
                self.tab.say("autoloot", "log.autoloot.no_scan")
            return
        self._warned = False
        targets = self.targets()
        # What the rule matched THIS tick, whether or not any of it is new. A watcher
        # that keeps finding nothing is the ordinary case — there is no star of that
        # level on the map most of the time — and it is the case that read as broken.
        self._state = ((STATE_TARGETS, str(len(targets))) if targets
                       else (STATE_WATCHING, ""))
        # Already-sent uuids are skipped: the list keeps showing a tile the server
        # refused (or one we robbed whose loot count has not come back yet), and
        # re-firing at it would burn the day's budget on a target that cannot pay. A
        # fresh session forgets them again.
        fresh = [t for t in targets if t[0] not in self._seen]
        if not fresh:
            return
        # The client's own word on whether it is even in a session, asked once, here —
        # where it decides something. A client at the login screen answers everything
        # and every answer is a plausible-looking lie (#1227); the list may still be
        # full of rows restored from the last session, and firing at them would spend
        # nothing and explain nothing.
        if not self.session_ready():
            self._state = (STATE_NO_LOGIN, "")
            if not self._warned_login:
                self._warned_login = True
                self.tab.say("autoloot", "log.autoloot.no_login")
            return
        self._warned_login = False
        for _uuid, _srv, label in fresh:
            self.tab.say("autoloot", "log.autoloot.target", label=label)
        self._seen.update(uuid for uuid, _srv, _label in fresh)
        self.run(fresh)

    def session_ready(self) -> bool:
        """Whether the client is far enough into a session to be robbed through.

        The clock is the one question a login screen cannot fake (`game_clock`), and it
        is asked only when there is something to fire at — a watcher with no target has
        no business waking the daemon every two seconds.
        """
        import game_clock             # lazy: keeps panel start-up free of it
        try:
            return game_clock.session_ready(self.rt.game.evaluator())
        except Exception:             # noqa: BLE001 — no daemon, no game, no session
            return False

    def targets(self) -> list:
        """What the rule would rob right now, as (uuid, server, label) — from OUR list.

        The selection is the tab's (`rob_candidates`), because the list is the tab's; all
        this adds is the shape the child is named in.
        """
        import coords as coords_fmt   # lazy: tools/lib is on the path by now
        out = []
        for row in self.tab.rob_candidates():
            out.append((int(row["uuid"]), int(row["server"] or 0),
                        coords_fmt.fmt(row.get("x"), row.get("y"), row.get("server"))))
        return out

    def run(self, targets) -> None:
        """Hand the chosen targets to the robbery tool, by name.

        `--targets` and nothing else: the level rule, the star and the own-server
        prohibition were all applied where the targets were chosen, and a child that
        re-derived them would be re-reading a map the list has already made its mind up
        about (#1256). The budget and the queue stay the tool's, which is where they
        belong — the recipe only SPENDS a queue this tool fills (#1188).
        """
        if not targets:
            return
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "steal_secret_task.py"),
               "--limit", str(self.limit()),
               "--targets", ",".join("%d:%d" % (uuid, srv)
                                     for uuid, srv, _label in targets)]
        self.rt.put(f"[autoloot] {self.rule_text()} …")
        proc = self.rt.children.spawn_raw(cmd, "autoloot")
        if proc is None:
            return
        self._proc = proc
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()

    def _reader(self, proc) -> None:
        spent = False
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                self.rt.put(f"[autoloot] {line}")
                # The child says so in words when there is nothing left to spend.
                if "robberies are spent" in line or "robberies left today: 0" in line:
                    spent = True
        except Exception:                        # noqa: BLE001 — the pipe closed
            pass
        if spent:
            pause = self.rt.settings.opt_int("autoloot_pause_min", low=1, high=1440) * 60
            self._pause_until = time.time() + pause
            self._state = (STATE_PAUSED, _hhmm(self._pause_until))
            self.tab.say("autoloot", "log.autoloot.spent", mins=int(pause // 60))
        if self._proc is proc:
            self._proc = None

    # -- the rule ------------------------------------------------------------
    def limit(self) -> int:
        return self.rt.settings.opt_int("autoloot_limit", low=1, high=50)

    def level_min(self) -> "int | None":
        """«Минимальный уровень» as an int, or None when the box is empty (#1256).

        Read live on every tick, like the display filters, so raising it takes effect on
        the next tick instead of at the next tick of the checkbox. Anything that is not a
        number reads as "no bound" — a half-typed entry must not silently become level 0,
        which is every level there is.
        """
        raw = str(self.tab.level_min_var.get()).strip()
        return int(raw) if raw.isdigit() else None

    def skip_server(self) -> "int | None":
        """The server the standing order must not rob on — the player's own, or None.

        None means "no prohibition": either the box is clear, or the own server could not
        be read. The unreadable case is NOT silently permissive — `tick` refuses to fire
        at all while the box is ticked and the answer is unknown; this only reports what
        the filter can be given.
        """
        if not self.tab.skip_own_var.get():
            return None
        return self.tab.own_server()

    def rule_text(self) -> str:
        """The standing order in one phrase — what it will rob, in the log's words.

        The rule is invisible otherwise, and an invisible rule is how a robbery got spent
        on a level-6 star: the operator must be able to read what the checkbox is about
        to do without opening the source.
        """
        low = self.level_min()
        text = (self.tab.t("secret.autoloot.rule_min", lvl=low) if low is not None
                else self.tab.t("secret.autoloot.rule_any"))
        if self.tab.skip_own_var.get():
            text += " " + self.tab.t("secret.autoloot.rule_skip_own")
        return text

    # -- what it is doing right now --------------------------------------------
    def state(self) -> tuple:
        """(locale key, the datum that goes beside it) — the live state of the order.

        The rule says what it WOULD rob; this says what is happening. They are different
        questions, and only the first one was ever answered on screen: a watcher with no
        star in range is silent, and so is one whose budget is spent, one that cannot
        read the own server, and one that was never started. From the operator's chair
        all four are «автолут не работает совершенно» (#1227).
        """
        return self._state

    def state_text(self) -> str:
        """The same thing as one phrase, in the panel's language."""
        key, datum = self._state
        text = self.tab.t(key)
        return f"{text} {datum}" if datum else text


def _hhmm(when: float) -> str:
    """A wall-clock stamp as HH:MM — how long a pause lasts, in the operator's terms.

    A number of minutes tells somebody who has just walked up nothing; a time they can
    compare with the clock on their own screen tells them whether to wait.
    """
    return time.strftime("%H:%M", time.localtime(when))
