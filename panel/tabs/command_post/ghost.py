"""«Операция Призрак» as a standing order: five robberies a day, unattended.

Secret tasks needed a pcap because their tiles only arrive while the map moves. Ghost
recon does not: the client keeps the whole squad list and its own verdict on each, so
this watcher polls the GAME rather than a checkpoint.

WHAT IT ROBS IS CHOSEN OUT OF THE PAGE'S OWN LIST (#1256). A look fills that list
(`GhostReconPane.reload`) from the two sources it has — the client's `taskList` and
whatever a map scan wrote down, which is the only one that ever sees another alliance's
tiles — and then asks the list which of them the rule wants
(`GhostReconPane.rob_candidates`: robbable, not mine, at or above «минимальный уровень»).
The chosen ones travel to the recipe BY NAME, as its `queue`. The robbery used to hand a
child `--all` and let it re-derive the set from its own reading of `taskList`, which meant
the page could be showing one thing and the robbery spending the budget on another — and
there was nowhere to put a level rule at all.

AND THE ROBBERY IS ONE SCENARIO, IN ONE STEP (#1188, then #1976). It used to be two:
spawn the standalone tool under its parking flag to leave the chosen squads in the game VM,
then play `actions/steal_ghost_recon.md` to press them. The reason for the spawn was that
`TAP` takes no arguments, so a robbery could not name its victim — true of `TAP`, and not
true of the recipe, which takes `ARGS`. What settled it is the same measurement that
settled the secret-task one: **the parking child costs five seconds**, and the whole of
what it did here was park a list THIS PAGE had already chosen
(`GhostReconPane.rob_candidates`). So the queue travels as an argument and the recipe
parks it in the call it was going to make anyway.

The tool keeps its own life at the command line, for `--list`, `--status` and `--all` —
none of which is in anybody's hot path.

The two gates that stay the GAME's stay the game's: whether today is the event's day and
how many of the five are left are read here, before anything is chosen, and read again by
the recipe's own `xall` before every press.

The event runs ONE DAY A WEEK. Six days out of seven `IsOpenDay()` says so in one cheap
read and the answer is "look again in an hour" — a minute-by-minute poll of a shut event
is a log nobody wants and a round trip nobody needs. That is also why the switch is
EAGER on the tab: an order that only runs while somebody has the tab open would miss
the one day it matters.

It was `Panel._ghost_loop` / `_ghost_tick` / `_ghost_run`, with its checkbox drawn on a
different tab again. All three are here now, beside the page that shows the squads.
"""
from __future__ import annotations

import threading

# The runtime FIRST: importing `panel.runtime` is what puts the repo's tools/lib on
# sys.path, and `lua_actions` is one of the bare-name modules that live there.
from ...runtime import game_process

import lua_actions                                   # noqa: E402  (see above)

#: How often the watcher looks while the event is open.
POLL = 60.0
#: …and while it is shut. Six days a week that is the whole of it.
CLOSED_PAUSE = 3600.0

#: What the recipe says when the SERVER confirmed a robbery, and when the day's five are
#: gone. Both are read off its own events — `stealTimes` only moves on the reply, so a
#: «ghost_steal_sent» line proves a frame left the client and nothing more. Reword them in
#: `actions/steal_ghost_recon.md` and this order stops noticing its own successes.
TAKEN_MARK = "ghost_taken"
SPENT_MARK = "ghost_steals_spent"


class GhostOrder:
    """The watcher, the read that gates it, and the child that does the robbing."""

    def __init__(self, rt, pane) -> None:
        self.rt = rt
        self.pane = pane          # the page whose list this chooses out of
        self._stop = None         # threading.Event while watching, else None
        self._proc = None         # one robbery in flight at a time
        # uuids handed to a child this session. A squad the server refused stays in the
        # client's list wearing the same «можно грабить» verdict, so without this the
        # next look would spend another attempt on it, and the one after that too.
        self._seen: set = set()

    @property
    def running(self) -> bool:
        return self._stop is not None

    def limit(self) -> int:
        return self.rt.settings.opt_int("autoloot_limit", low=1, high=50)

    # -- start / stop --------------------------------------------------------
    def toggle(self) -> None:
        if self.pane.autoloot_var.get():
            self.start()
        else:
            self.stop()

    def ensure_started(self) -> None:
        """Start it if this profile had it ticked. Idempotent."""
        if self.pane.autoloot_var.get():
            self.start()

    def start(self) -> None:
        if self._stop is not None:
            return
        self._stop = threading.Event()
        self._seen.clear()
        self.rt.say("ghost", "ghost.on")
        self.rt.say("ghost", "ghost.rule", rule=self.pane.rule_text())
        threading.Thread(target=self._loop, args=(self._stop,), daemon=True).start()

    def stop(self) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            stop.set()
            self.rt.say("ghost", "ghost.off")

    # -- the watch -----------------------------------------------------------
    def _loop(self, stop: threading.Event) -> None:
        """Poll the event's budget; rob when it is open and something is robbable."""
        last_err = ""
        while not stop.is_set():
            wait = POLL
            try:
                wait = self.tick()
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — one tick, not the loop
                err = f"{type(exc).__name__}: {exc}"
                if err != last_err:
                    last_err = err
                    self.rt.say("ghost", "log.ghost.error", error=err)
            if stop.wait(wait):
                return

    def tick(self) -> float:
        """One look. Returns how long to wait before the next one."""
        if self._proc is not None:            # a robbery is still running
            return POLL
        if self.rt.game.busy or not self.rt.game.ready():
            return POLL
        running, _text = game_process.profile_status(self.rt.settings)
        if not running:
            return POLL
        chunk = ('CS.UnityEngine.Debug.LogError("GHOST open=" .. tostring(%s) '
                 '.. " left=" .. tostring(%s))'
                 % (lua_actions.ghost_recon_is_open(),
                    lua_actions.ghost_recon_steals_left()))
        text = " ".join(self.rt.game.client.run(chunk, marker="GHOST", settle=0.6,
                                                early=True))
        if "open=1" not in text:
            return CLOSED_PAUSE
        left = 0
        if "left=" in text:
            try:
                left = int(float(text.split("left=")[1].split()[0]))
            except (ValueError, IndexError):
                left = 0
        if left <= 0:
            # Open, but today's five are spent. The reset is at the server's day
            # boundary, so the same pause the secret-task watcher uses fits.
            return self.rt.settings.opt_int("autoloot_pause_min",
                                            low=1, high=1440) * 60.0
        # The event is open and there is budget: fill the page's list, then ask the list
        # what the rule wants (#1256). Both halves are the page's — this only decides
        # WHEN to look, which is the one thing a watcher is for.
        self.pane.reload()
        picks = [t for t in self.pane.rob_candidates()
                 if str(t.get("uuid")) not in self._seen]
        if not picks:
            return POLL
        self.rob(picks[:left])
        return POLL

    # -- one press, from away --------------------------------------------------
    def run_once(self) -> bool:
        """«Ограбить всех» from the phone: re-read the list, then rob what the rule wants.

        The window's button robs what is ON SCREEN, because somebody is looking at it.
        Nobody is looking at the phone's copy — its card is drawn from the map scan's
        file, not from this page's list — so the reading is done first, exactly as the
        watcher's own look does it (`tick`), and the choice is still the page's.

        Returns False when a robbery is already in flight; the caller says so rather than
        parking a second set of squads on top of the queue this one is pressing.
        """
        if self._proc is not None:
            return False
        self._proc = object()          # claim it before the read, so two presses cannot
        threading.Thread(target=self._look_and_rob, daemon=True).start()
        return True

    def _look_and_rob(self) -> None:
        """The read, then the robbery — with the in-flight flag held across BOTH.

        Never cleared between them: a look that took a second and then handed over would
        leave a gap the watcher's own tick could walk into, and two runs parking two sets
        of squads on one queue is exactly what the flag is for. `rob` clears it on an
        empty pick and `_spend` clears it when the recipe is done.
        """
        picks = []
        try:
            self.pane.reload()
            picks = self.pane.rob_candidates()
        except Exception as exc:       # noqa: BLE001 — a failed read is a log line
            self.rt.say("ghost", "log.ghost.error", error=f"{type(exc).__name__}: {exc}")
        if not picks:
            self._proc = None
            return
        self.rob(picks)

    # -- the robbery ---------------------------------------------------------
    def rob(self, targets) -> None:
        """Play `actions/steal_ghost_recon.md` over the squads this look chose.

        Also what «ограбить всё» presses. By name, never «--all» (#1256): the choice was
        made against the page's own list, under the page's own «минимальный уровень», and
        a second opinion derived from a second reading of `taskList` is how the page and
        the robbery come to disagree.

        ONE STEP (#1976). The queue is an argument now — `ARGS queue` — and the recipe
        parks it in the call it was going to make anyway, so nothing is spawned and
        nothing is waited for before the first press. The level rule and «not mine» were
        applied where the targets were CHOSEN; the recipe re-derives neither, and the
        event day and the daily budget stay the game's, read by its own `xall`.
        """
        pairs = [(int(t["uuid"]), int(t.get("srv") or 0))
                 for t in (targets or ()) if t.get("uuid")]
        pairs = pairs[:self.limit()]
        if not pairs:
            # Whoever set the flag — `run_once` does, before the read — gets it back.
            self._proc = None
            return
        self._seen.update(str(uuid) for uuid, _srv in pairs)
        queue = ",".join("{uuid=%d,server=%d}" % pair for pair in pairs)
        self.rt.say("ghost", "ghost.robbing", n=len(pairs))
        self._proc = object()      # «a robbery is in flight» — `tick` reads this
        threading.Thread(target=self._spend, args=(queue,), daemon=True).start()

    def _spend(self, queue: str) -> None:
        """The press itself, on this worker thread.

        Straight through `rt.actions`, deliberately NOT `rt.play_async`: the interlock
        this order has is «one run at a time» (`_proc`), and a claim wrapped round the
        press would invent a refusal («занят») in the middle of a robbery whose squads
        were chosen a moment ago and are already in `_seen` — with nothing left to retry
        it, because the next look skips them.

        The recipe is safe over a queue that emptied under it: its `xall` re-reads
        min(queued, robberies left) before every press, and reads 0 outright once the
        event shuts.
        """
        taken = spent = False

        def put(msg) -> None:
            nonlocal taken, spent
            line = str(msg)
            self.rt.put(f"[ghost] {line}")
            if TAKEN_MARK in line:
                taken = True
            if SPENT_MARK in line:
                spent = True

        try:
            outcome = self.rt.actions.play("steal_ghost_recon", {"queue": queue},
                                           human=True, on_event=put)
        except Exception as exc:       # noqa: BLE001 — a failed press, never the watcher
            self.rt.say("ghost", "log.ghost.spend_failed",
                        reason=f"{type(exc).__name__}: {exc}")
            return
        finally:
            self._proc = None
        if not outcome:
            # The scenario's own reason, verbatim — it is the authority on why it
            # stopped and the panel's job is to repeat it, not to re-diagnose it.
            self.rt.say("ghost", "log.ghost.spend_failed", reason=outcome.reason or "?")
        elif spent and not taken:
            # Open, budget gone, nothing taken this run: say it once rather than letting
            # the next look find the same squads and spend another round trip on them.
            self.rt.say("ghost", "log.ghost.spent")
