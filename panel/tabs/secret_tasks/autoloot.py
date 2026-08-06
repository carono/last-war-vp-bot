"""«Автолут ★» — the standing order that spends the day's five robberies.

THIS IS A BUDGET, and that is what makes it the delicate part of the tab. Five raids a
day is the whole allowance, so a rule that is off by one level does not fail loudly —
it quietly spends a robbery on a level-6 star that a 7 could have had, and nobody finds
out until the reset (#1099). Everything here follows from that:

* **the range is read live, every tick**, so narrowing it takes effect at once;
* **a half-typed box is "no bound"**, never "any level";
* **the range travels to every child**, because each of them re-applies the rule and
  would otherwise rob outside it;
* **the event-driven listener is RESTARTED when the range changes**, since it is a
  subprocess started with a fixed one — that is the exact trap #1099 closed for the
  poll and would have left open here;
* **a uuid already fired at is never fired at again this session**, so a poll on a
  spent budget does not burn the allowance on a target that cannot pay;
* **«не грабить на своём сервере» travels the same way the range does** — it filters
  the targets here AND is handed to both children, because each of them re-reads the
  sources and would otherwise rob the neighbours the box says to leave alone.

Two paths on purpose. The listener robs a *shared* secret task the instant its push
crosses the wire (< 1 s), which is the case a human used to win; the poll is the slower
safety net that still catches enemy tiles the sweep panned over, and tasks that were
already there before the listener started.
"""
from __future__ import annotations

import os
import threading
import time

from ...runtime.paths import TOOLS

#: How long after the last keystroke the listener is re-spawned with the new range.
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
STATE_NO_SOURCE = "secret.autoloot.state.no_source"  # no live game and no checkpoint
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
        self._warned = False         # "no checkpoint yet" is said once per run
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
        acts through this profile's daemon, so it is given the same level range the
        poll's child gets — otherwise it would rob outside «уровень от / до».
        """
        if self._push_proc is not None:
            return
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "secret_share_autoloot.py"),
               "--star-max", "--limit", str(self.limit()),
               # Every share it decodes is marked as shared, whether or not the rule
               # takes it (#1245): «worth one of my five robberies» and «the alliance
               # has already been shown this» are different questions, and the tab
               # draws the second on both of its tables.
               "--shared-json", self.rt.profiles.secret_shared_json()]
        lo, hi = self.levels()
        if lo is not None:
            cmd += ["--level-min", str(lo)]
        if hi is not None:
            cmd += ["--level-max", str(hi)]
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
        """Re-spawn the listener so a changed «уровень от / до» takes effect."""
        if self._stop is None:                   # auto-loot was unticked meanwhile
            return
        self.stop_push()
        self.start_push()

    def range_changed(self) -> None:
        """The rule was changed (the range, or «не грабить на своём сервере»). Bounce
        the listener onto it, debounced.

        The poll re-reads the rule live every tick, but the listener is a subprocess
        started with a fixed one — a range typed while auto-loot is on would otherwise
        keep robbing to the OLD «уровень до», and a box ticked after it started would
        not reach it at all.
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
        """Poll the sources until the checkbox is cleared.

        A whole tick is wrapped: the watcher is a background loop the operator cannot
        see, so one unreadable checkpoint (caught half-written by the capture, say) must
        cost a log line and not the auto-loot for the session. The same complaint is
        printed once and not on every poll after it.
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
        """One look at the sources: fire when the rule has a target we have not sent yet.

        The primary source is the live game VM (`ActDispatchTaskDataManager.allianceTask`,
        read through the warm daemon): a member's shared secret task is in it the moment
        the push lands, so a raidable star is knowable in the second it appears rather
        than whenever the map sweep next pans over it — which is what let a human beat the
        bot to the tile (#1124). The capture checkpoint is kept as a SECOND source, so
        enemy tiles the sweep panned over are still robbed when the monitor is on; when it
        is off, the VM alone carries the feature.
        """
        if self._proc is not None:                    # a robbery is still running
            self._state = (STATE_ROBBING, "")
            return
        if time.time() < self._pause_until:           # the day's budget is spent
            self._state = (STATE_PAUSED, _hhmm(self._pause_until))
            return
        checkpoint = self.rt.profiles.tasks_json()
        have_scan = os.path.exists(checkpoint)
        vm_ready = self.rt.game.up() and not self.rt.game.busy
        if not vm_ready and not have_scan:
            # No live VM to read and no checkpoint to fall back on — there is simply no
            # source yet. Say so once, not on every poll.
            self._state = (STATE_NO_SOURCE, "")
            if not self._warned:
                self._warned = True
                self.tab.say("autoloot", "log.autoloot.no_scan")
            return
        self._warned = False
        # «Не грабить на своём сервере» is a prohibition, so an unknown own server stops
        # the tick rather than letting it through: robbing a neighbour the operator asked
        # to be left alone cannot be taken back, and a paused watcher says so in the log.
        # The read needs the live VM, so a checkpoint alone is not enough to fire on.
        if self.tab.skip_own_var.get():
            if not (vm_ready and self.tab.own_server()):
                self._state = (STATE_NO_OWN, "")
                if not self._warned_own:
                    self._warned_own = True
                    self.tab.say("autoloot", "log.autoloot.no_own_server")
                return
            self._warned_own = False
        import steal_secret_task              # lazy: keeps panel start-up free of it

        try:
            targets = self.all_targets(checkpoint if have_scan else None, vm_ready)
        except steal_secret_task.NotLoggedIn:
            # The client answered and said nothing useful: no alliance task, own server
            # -1, the whole day's robberies apparently unspent. That is a session that
            # has not started, not a quiet map, and until #1227 the two looked the same
            # from here — the watcher simply never found a target and never said why.
            self._state = (STATE_NO_LOGIN, "")
            if not self._warned_login:
                self._warned_login = True
                self.tab.say("autoloot", "log.autoloot.no_login")
            return
        self._warned_login = False
        # What the rule matched THIS tick, whether or not any of it is new. A watcher
        # that keeps finding nothing is the ordinary case — there is no star of that
        # level on the map most of the time — and it is the case that read as broken.
        self._state = ((STATE_TARGETS, str(len(targets))) if targets
                       else (STATE_WATCHING, ""))
        # Already-sent uuids are skipped: a source keeps showing a tile the server refused
        # (or that we robbed but whose loot count has not come back yet), and re-firing at
        # it would burn the day's budget on a target that cannot pay. A fresh session
        # forgets them again.
        fresh = [t for t in targets if t[0] not in self._seen]
        if not fresh:
            return
        for _uuid, _srv, label in fresh:
            self.tab.say("autoloot", "log.autoloot.target", label=label)
        # Mark EVERY target of the rule, not just the fresh ones: the child re-reads the
        # same sources and will attempt the whole list, so the panel must not treat the
        # rest as new the next time round.
        self._seen.update(uuid for uuid, _srv, _label in targets)
        self.run(checkpoint if have_scan else None, vm_ready)

    def all_targets(self, checkpoint, vm_ready: bool) -> list:
        """Union of the VM's raidable alliance tasks and the checkpoint's, VM first.

        A target in both sources under the same `(uuid, server)` is kept once — the VM
        copy, the fresher of the two. A source raising propagates up to `_loop`, which
        logs it once and tries again next poll; that is fine, because a robbery needs the
        daemon anyway, so a dead VM is a tick with nothing to rob rather than a target
        quietly dropped.
        """
        seen: set = set()
        out: list = []

        def _merge(rows):
            for uuid, srv, label in rows:
                if (uuid, srv) in seen:
                    continue
                seen.add((uuid, srv))
                out.append((uuid, srv, label))

        if vm_ready:
            _merge(self.vm_targets())
        if checkpoint is not None:
            _merge(self.scan_targets(checkpoint))
        return out

    def vm_targets(self) -> list:
        """Star-max raidable alliance tasks read live from the VM, as (uuid, server, label).

        The same rule `scan_targets` applies to a checkpoint, applied to the tasks the
        game already holds — no capture, no map panning.
        """
        import steal_secret_task     # lazy: keeps panel start-up free of it
        lo, hi = self.levels()
        return steal_secret_task.targets_from_vm(
            self.rt.game.client, limit=self.limit(), star_max=True,
            level_min=lo, level_max=hi, skip_server=self.skip_server(),
            say=lambda _m: None)

    def scan_targets(self, checkpoint: str) -> list:
        """Star-max targets in the checkpoint right now, as (uuid, server, label).

        Pure file work — it does not touch the game or the daemon, so it is safe to call
        from the watcher thread on every poll.
        """
        import steal_secret_task     # lazy: keeps panel start-up free of it
        lo, hi = self.levels()
        return steal_secret_task.targets_from_scan(
            checkpoint, limit=self.limit(), star_max=True,
            level_min=lo, level_max=hi, skip_server=self.skip_server(),
            say=lambda _m: None)

    def run(self, checkpoint, vm_ready: bool) -> None:
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "steal_secret_task.py"),
               "--star-max", "--limit", str(self.limit())]
        # The child re-reads the same sources and re-applies the rule, so it has to be
        # told which ones the tick used: the live VM (fast path) and/or the capture
        # checkpoint (enemy tiles the sweep saw). Passing neither would leave it with
        # nothing to rob.
        if vm_ready:
            cmd.append("--from-vm")
        if checkpoint is not None:
            cmd += ["--from-scan", checkpoint]
        # The range has to travel with it: without these the watcher would agree to a
        # target inside the range and the child would then rob outside it. The
        # own-server prohibition travels for exactly the same reason.
        lo, hi = self.levels()
        if lo is not None:
            cmd += ["--level-min", str(lo)]
        if hi is not None:
            cmd += ["--level-max", str(hi)]
        if self.tab.skip_own_var.get():
            cmd.append("--skip-own-server")
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

    def levels(self) -> tuple:
        """The «уровень от / до» range as (min, max) ints, either end None if unset.

        Read live on every poll, like the display filters, so narrowing the range takes
        effect on the next tick instead of at the next tick of the checkbox. Anything
        that is not a number reads as "no bound" — a half-typed entry must not silently
        widen the gate to everything.
        """
        def bound(var) -> "int | None":
            raw = var.get().strip()
            return int(raw) if raw.isdigit() else None
        return bound(self.tab.level_from_var), bound(self.tab.level_to_var)

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
        lo, hi = self.levels()
        if hi is not None:
            text = self.tab.t("secret.autoloot.rule_top", lvl=hi,
                              lo=lo if lo is not None else "—")
        else:
            text = self.tab.t("secret.autoloot.rule_found",
                              lo=lo if lo is not None else "—")
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
