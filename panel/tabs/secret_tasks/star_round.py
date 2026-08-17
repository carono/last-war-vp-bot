"""«Обход зон ★» — the panel's half of the star-secret-task round (#1479).

THE ROUND ITSELF IS A SCENARIO (`actions/sweep_star_servers.md`), and everything about
the ability is in it: the day's-quota gate, which warzones are having their star day,
which of them this account may rob on, which ones today has already walked, and the laps.
`CLAUDE.md` is binding about that and this module does not bend it — what is here is the
two things the RECIPE cannot know, because they are the panel's own and not the game's:

* **whether anything is listening.** A lap produces traffic and decodes nothing: the ★
  page's sniffer is what turns it into rows. With the capture down the errand would walk
  five warzones, report a cheerful success and fill nothing — which is the exact shape of
  the fault that hid #1476 for hours. So the round does not START while the monitor is
  down, and the skip says which of the two it is: a sniffer somebody switched off, or one
  that died and is being brought back.
* **what reached the list.** The recipe can say how many warzones it walked and what the
  day's robbery budget stands at — those are the game's own numbers. How many rows the
  list gained and how many of them are ripe enough for «Автолут ★» to take is the
  PANEL's answer, and a report that stops before it is one a person has to finish by
  hand every four hours.

Neither of those is a gate on the ability: the first is «is there a point», asked in
front of the run (`Schedule.register_precondition`), and the second is a sentence about a
run that is over (`Schedule.register_report`).

**No widgets, and that is deliberate.** The errand is a row on the «Таймеры» tab like
every other timer — it is switched on, given its period and pressed «Запустить» there —
so there is nothing here for either front-end to draw and nothing to mirror onto the
phone. (The «Таймеры» tab declares no web screen at all; that hole is #1297 and is not
this task's to close.)
"""
from __future__ import annotations

#: The errand this hooks onto — the name of the timer AND of the scenario it plays.
ERRAND = "sweep_star_servers"


class StarRound:
    """The precondition in front of the round, and the report after it."""

    def __init__(self, rt, tab) -> None:
        self.rt = rt
        self.tab = tab
        #: Registered once per tab, whatever asks (`ensure_loaded` is idempotent).
        self._registered = False
        #: How many rows the list held when the round was let through, so the report can
        #: say what the lap ADDED rather than only what the list happens to hold. `None`
        #: means «no round has started since the panel came up».
        self._rows_before = None

    # -- wiring ---------------------------------------------------------------
    def register(self) -> None:
        """Hook this profile's schedule up to the round. Idempotent, called at boot."""
        if self._registered:
            return
        schedule = getattr(self.rt, "schedule", None)
        if schedule is None:                     # a tab opened on its own, no schedule
            return
        schedule.register_precondition(ERRAND, self.precondition)
        schedule.register_report(ERRAND, self.report)
        self._registered = True

    # -- before the run --------------------------------------------------------
    def precondition(self) -> "str | None":
        """Why a round would be pointless right now — or `None` to let it run.

        Called on the scheduler's own thread at the moment of the decision, with the
        client already known to be up (`Schedule.gate`). It reads two cheap things: is
        the ★ sniffer alive, and how big the list is — no game round trip, no widget.

        A sniffer that is WANTED but not up is nudged rather than merely reported: the
        capture brings itself back from a crash (#1476), and a round four hours from now
        is worth one `start()` today. The nudge goes through the tab's own `after`,
        because starting a capture reads the tab's boxes and those belong to Tk.
        """
        capture = getattr(self.tab, "capture", None)
        if capture is None:                      # a tab that has not made one yet
            return "secret.round.skip_monitor"
        if not capture.running:
            if capture.wanted:
                self.tab.after(capture.start)
                return "secret.round.skip_monitor_wait"
            return "secret.round.skip_monitor"
        self._rows_before = self._rows()
        return None

    # -- after it ---------------------------------------------------------------
    def report(self, ctx) -> None:
        """What only the panel can say about the lap that has just finished.

        Handed the finished run, so the warzones and the day's budget come out of the
        recipe's own variables — the same numbers it logged — and the two list counts
        come from the tab. A round that never reached the picking stage (the quota was
        spent, nothing was having its star day) says nothing here: the scenario has
        already said why, and a row of zeroes underneath it reads like a failure.
        """
        walked = int(_number(ctx, "STAR_PICKED"))
        if walked <= 0:
            return
        rows = self._rows()
        before = self._rows_before
        self._rows_before = None
        self.tab.say("secret", "log.round.report",
                     n=walked,
                     servers=str(ctx.vars.get("STAR_CHOSEN") or "—"),
                     added=(rows - before) if before is not None else 0,
                     rows=rows,
                     ready=len(self.tab.rob_candidates()),
                     done=int(_number(ctx, "steals_done")),
                     left=int(_number(ctx, "steals_left")))

    # -- readings ---------------------------------------------------------------
    def _rows(self) -> int:
        """How many tiles the ★ list holds, counted off a SNAPSHOT.

        The scheduler's thread is not Tk's and the list is added to from the capture
        reader, the merges and the ticks — walking the live mapping raises «dictionary
        changed size during iteration», which is what cost «Автолут ★» 77 ticks in one
        live day (#1416). A copy of the keys is a list of references and costs nothing.
        """
        try:
            return len(list(getattr(self.tab, "_rows", {})))
        except Exception:                        # noqa: BLE001 — a count, never the run
            return 0


def _number(ctx, name, default=0) -> float:
    """One of the run's variables as a number — anything else is `default`.

    A recipe that STOPped early never set some of them, and a report is not the place to
    discover that: the ones it is about are read leniently and the sentence says zero.
    """
    try:
        return float(getattr(ctx, "vars", {}).get(name, default))
    except (TypeError, ValueError):
        return default
