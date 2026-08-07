"""«Операция Призрак» as a standing order: five robberies a day, unattended.

Secret tasks needed a pcap because their tiles only arrive while the map moves. Ghost
recon does not: the client keeps the whole squad list and its own verdict on each, so
this watcher polls the GAME rather than a checkpoint.

WHAT IT ROBS IS CHOSEN OUT OF THE PAGE'S OWN LIST (#1256). A look fills that list
(`GhostReconPane.reload`) from the two sources it has — the client's `taskList` and
whatever a map scan wrote down, which is the only one that ever sees another alliance's
tiles — and then asks the list which of them the rule wants
(`GhostReconPane.rob_candidates`: robbable, not mine, at or above «минимальный уровень»).
The chosen ones travel to `tools/ghost_recon_steal.py --targets uuid:server,…` by name.
It used to hand the tool `--all` and let it re-derive the set from its own reading of
`taskList`, which meant the page could be showing one thing and the robbery spending the
budget on another — and there was nowhere to put a level rule at all.

AND THE ROBBERY ITSELF IS A SCENARIO (#1188). The tool is run with `--queue-only`: it
parks the chosen squads in the game VM and stops, and `actions/steal_ghost_recon.md`
does the pressing. Two steps rather than one because the recipe SPENDS a queue and does
not fill one — `TAP` takes no arguments, so a robbery cannot name its victim in the DSL —
and one step rather than none because `CLAUDE.md` is binding: the ability lives in the
scenario, and the panel plays it.

The two gates that stay the GAME's stay the game's: whether today is the event's day and
how many of the five are left are read here, before anything is chosen, and read again by
the tool before every send.

The event runs ONE DAY A WEEK. Six days out of seven `IsOpenDay()` says so in one cheap
read and the answer is "look again in an hour" — a minute-by-minute poll of a shut event
is a log nobody wants and a round trip nobody needs. That is also why the switch is
EAGER on the tab: an order that only runs while somebody has the tab open would miss
the one day it matters.

It was `Panel._ghost_loop` / `_ghost_tick` / `_ghost_run`, with its checkbox drawn on a
different tab again. All three are here now, beside the page that shows the squads.
"""
from __future__ import annotations

import os
import threading

# The runtime FIRST: importing `panel.runtime` is what puts the repo's tools/lib on
# sys.path, and `lua_actions` is one of the bare-name modules that live there.
from ...runtime import game_process
from ...runtime.paths import TOOLS

import lua_actions                                   # noqa: E402  (see above)

#: How often the watcher looks while the event is open.
POLL = 60.0
#: …and while it is shut. Six days a week that is the whole of it.
CLOSED_PAUSE = 3600.0

#: What the parking run says when it has left something in the game VM for the recipe to
#: spend — `tools/ghost_recon_steal.py`, under `--queue-only`. It is the one line that
#: tells «the targets are parked» from the two ways the tool declines (the event is shut,
#: nothing was named), neither of which touches the queue. Reword it there and this order
#: stops robbing, quietly — the tool says so beside it.
QUEUED_MARK = "queued "


def _parked(line: str) -> bool:
    """Did the parking run leave targets in the game VM? Read off its own words.

    «queued N target(s)» with N above zero, and nothing else. The count matters: the tool
    prints the line whether or not anything survived its own gates, and a recipe played
    over an empty queue is a round trip that presses nothing and reports success.
    """
    if not line.startswith(QUEUED_MARK):
        return False
    head = line[len(QUEUED_MARK):].split(" ", 1)[0]
    return head.isdigit() and int(head) > 0


class GhostOrder:
    """The watcher, the read that gates it, and the child that does the robbing."""

    def __init__(self, rt, pane) -> None:
        self.rt = rt
        self.pane = pane          # the page whose list this chooses out of
        self._stop = None         # threading.Event while watching, else None
        self._proc = None         # one robbery child at a time
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

    # -- the robbery ---------------------------------------------------------
    def rob(self, targets) -> None:
        """PARK the chosen squads with the tool, then PLAY the recipe that spends them.

        Also what «ограбить всё» presses. By name, never «--all» (#1256): the choice was
        made against the page's own list, under the page's own «минимальный уровень», and
        a child that re-derived it from its own reading of `taskList` would be a second
        opinion nobody asked for.

        `--queue-only` is what this task is (#1188). The tool keeps what is genuinely
        the game's answer — the event day, the daily budget — and the queue in the game
        VM that a target is named through; what it no longer keeps is the pressing. It
        selects, parks and stops, and `actions/steal_ghost_recon.md` robs, in
        :meth:`_spend`. Swapping the spawn outright for `run_action` — which the refactor
        plan called a one-line change — would have played a recipe that OPENS by reading
        that queue and logging «run tools/ghost_recon_steal.py first»: nothing robbed, on
        the one day a week there is anything to rob.
        """
        pairs = [(int(t["uuid"]), int(t.get("srv") or 0))
                 for t in (targets or ()) if t.get("uuid")]
        if not pairs:
            return
        self._seen.update(str(uuid) for uuid, _srv in pairs)
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "ghost_recon_steal.py"),
               # Select and park; the robbery itself is the recipe's, below.
               "--queue-only",
               "--limit", str(self.limit()),
               "--targets", ",".join("%d:%d" % pair for pair in pairs)]
        self.rt.say("ghost", "ghost.robbing", n=len(pairs))
        proc = self.rt.children.spawn_raw(cmd, "ghost")
        if proc is None:
            return
        self._proc = proc
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()

    def _reader(self, proc) -> None:
        """Stream the parking run, then spend what it parked.

        `self._proc` stays set while :meth:`_spend` runs: `tick` reads it as «a robbery
        is in flight», and clearing it between the two halves would let the next look
        park a second set of squads on top of the queue this one is pressing.
        """
        queued = False
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                self.rt.put(f"[ghost] {line}")
                if _parked(line):
                    queued = True
        except Exception:                     # noqa: BLE001 — the pipe closed
            pass
        if queued:
            self._spend()
        if self._proc is proc:
            self._proc = None

    def _spend(self) -> None:
        """Play `actions/steal_ghost_recon.md` over the queue the tool just parked.

        Straight through `rt.actions`, on this reader thread, and deliberately NOT
        `rt.play_async`. The tool that ran a moment ago drove the game without the
        panel's claim — like every child, it takes the daemon's lease for itself — so
        claiming for the second half alone would invent a refusal («занят») in the middle
        of a robbery whose squads are already parked, with nothing left to retry it: the
        uuids are in `_seen` and the next look would skip them. The interlock stays the
        one this order has always had — one child at a time, and the daemon's lease under
        both halves.

        The recipe is safe over a queue that emptied under it: its `xall` re-reads
        min(queued, robberies left) before every press, and reads 0 outright once the
        event shuts.
        """
        put = lambda msg: self.rt.put(f"[ghost] {msg}")        # noqa: E731
        try:
            outcome = self.rt.actions.play("steal_ghost_recon", on_event=put)
        except Exception as exc:       # noqa: BLE001 — a failed press, never the watcher
            self.rt.say("ghost", "log.ghost.spend_failed",
                        reason=f"{type(exc).__name__}: {exc}")
            return
        if not outcome:
            # The scenario's own reason, verbatim — it is the authority on why it
            # stopped and the panel's job is to repeat it, not to re-diagnose it.
            self.rt.say("ghost", "log.ghost.spend_failed", reason=outcome.reason or "?")
