"""The rally auto-join's four standing rules, wired for WHICHEVER front-end is running.

WHY IT EXISTS (#2051). «rally_auto_join» is a trigger of the schedule's, and the
schedule runs in every open profile whether or not anybody has a window. Four things it
needs are NOT the schedule's own — they belong to the rally code — so they are handed to
it at start-up:

  * :func:`join_args` — the arguments the recipe is played with: the squads, the three
    maps the wire keeps (what each banner is going FOR, how many seats it has, where a
    joiner is sent), the day's ceiling, the kind filter, the per-kind budget and the
    soldier floor;
  * the gate — what a run may be COUNTED under, and the hook that writes the count down
    (`limits.record_run`), which is the ONLY thing that moves `rally_counts`;
  * the join's precondition — do not even start when every squad is out, or when this
    banner has just been weighed;
  * the statistics hook's own precondition, for the same reason and its own book.

ALL FOUR USED TO BE REGISTERED BY THE WINDOW ALONE, inside `Panel._open_session_page`,
and that is the whole of the bug this module exists to end. A panel with no window
(`panel/headless.py`) registered none of them, so on the front-end that actually farms
the accounts:

  * `targets` arrived EMPTY, so every banner was classified as the fallback `monster`
    and no per-kind ceiling could bite — exactly the failure #1323 fixed for the tab and
    that came straight back through the other door;
  * `kind_left` arrived empty, so the press was handed no per-kind budget AT ALL;
  * `max_joins` and `min_soldiers` fell back to their defaults, so the day's ceiling and
    the soldier floor the person had typed were both ignored;
  * nothing called `record_run`, so the tally never moved — which is why the counter on
    the screen read almost zero while the log showed hundreds of joins;
  * and no precondition ran, so a push raised a run even with every squad on the road.

Measured on the live `default` profile over one day: 544 runs of `join_rally`, 537 of
them reporting «no banner targets were parked at all» and «the panel handed no per-kind
budget at all», and the word `kind_capped=` not once in the file.

NO Tk HERE, on purpose — the same rule `panel/tabs/rally/limits.py` keeps. Everything
takes the profile's runtime and reads it; the tab modules answer in a profile whose
«Ралли» tab was never built.
"""
from __future__ import annotations


def _tab():
    """`panel/tabs/rally`, imported at CALL time and never at wiring time.

    The wiring runs while a profile is starting up, on both front-ends; the rally tab
    package pulls Tk in behind it. Nothing here needs a widget, so the import waits until
    a rule is actually asked — which also keeps :func:`wire` testable with no display.
    """
    from ..tabs import rally as rallytab
    return rallytab


def _gate():
    """…and `panel/tabs/rally/limits.py`, the Tk-free half, for the same reason."""
    from ..tabs.rally import limits as rallygate
    return rallygate


def join_args(rt) -> dict:
    """Which squads the rally auto-join spends, and on what terms — read LIVE.

    Registered with the schedule rather than known to it: the rule belongs to the rally
    code, which answers in a profile that does not show that tab either.

    `targets` is what each banner we have HEARD of is going for, so the chunk can name
    the kind before a squad leaves (#1281). The wire is the only place it exists — the
    field is on the push and in nothing the client keeps.

    `slots` is how many seats each has, for the same reason and from the same line: a
    banner that has not left yet can still be shut, and the join must not spend a squad
    on one it cannot enter.

    `points` is WHERE a joiner is sent for each of them, which is what lets the run act
    on a banner the client's own march table has not heard of yet (#1301). That table is
    a median of 10 s behind the push; the push has the address from the first byte.

    `max_joins` is HOW MANY RALLIES THIS DAY IS WORTH (#1317). The ceiling is the
    person's number and the count behind it is the game's own — the recipe reads it
    inside the press it was already making, so the door costs no call and the panel keeps
    no tally.

    THE WIRE'S OWN BOOK UNDER ALL THREE MAPS (#1323). `rallytab.*_map` answers off the
    «Ралли» tab, and a window that does not SHOW that tab has no such tab and no such
    capture — while this trigger is a standing order of the schedule's and fires all the
    same. Every banner then arrived with no target, was classified as the fallback
    `monster`, and each of the person's per-kind caps stayed at zero while one bucket
    took the whole day. So the profile's own ear keeps the same three maps
    (`panel/runtime/rally_wire.py`) and they are the floor under the tab's: where both
    know a banner, the tab's entry wins.
    """
    from . import rally_wire as rallywire
    rallytab, rallygate = _tab(), _gate()

    squads = rallytab.join_squads(rt)
    if not squads:
        rt.say("trigger", "triggers.log.no_squads")
    book = rt.banners
    return {"squads": squads,
            "targets": rallywire.merge(rallytab.target_map(rt), book.targets()),
            "slots": rallywire.merge(rallytab.slot_map(rt), book.slots()),
            "points": rallywire.merge(rallytab.point_map(rt), book.points()),
            "max_joins": rallytab.daily_max(rt),
            # …which KINDS of banner to leave alone, and how many of each are left today
            # (#1317). The filter counts nothing and is exact; the budget is the panel's
            # own tally, chosen by the person with the drift explained. It is handed over
            # on EVERY run since #1322 — it used to be withheld whenever the tally ran
            # ahead of the game's own count, which is the ordinary state of an account
            # with squads on the road, so the door never once shut.
            "kind_skip": rallytab.kind_skip(rt),
            "kind_left": rallygate.kind_left(rt),
            # …and HOW MANY SOLDIERS MUST BE HOME for a banner to be worth a squad
            # (#1317). Soldiers are one pool: a squad is only «full» at the expense of
            # the next one, so the question «хватает ли на все три» is about the base and
            # the answer is one door over the whole run, judged in the press against the
            # pool it already reads.
            "min_soldiers": rallytab.min_soldiers(rt)}


def wire(rt, bind=None) -> None:
    """Give this profile's schedule the four rules above. Called by BOTH front-ends.

    ``bind`` is the window's `Panel._bound` — it re-enters the session a callable was
    made in, because the shell's own state follows whichever page is showing. A headless
    panel has no such state and passes nothing; every callable below closes over `rt`
    explicitly either way, so the binding is a belt over braces rather than the thing
    that makes it right.

    THE RALLY JOIN IS COUNTED, NEVER REFUSED BY THE GATE (#1281). The daily twenty is a
    TROPHY THRESHOLD rather than a door — past it the game stops paying, not joining — so
    :func:`limits.join_gate` answers «yes» to everything and exists only to keep the
    record wired: what each join actually went to, kind by kind, which the game does not
    keep for us. What the day costs is the client's own count (`limits.trophy_progress`).
    """
    schedule = getattr(rt, "schedule", None)
    if schedule is None or not hasattr(schedule, "register_args"):
        return
    hold = bind if callable(bind) else (lambda func: func)

    schedule.register_gate(
        "rally_auto_join",
        hold(lambda: _gate().join_gate(rt)),
        hold(lambda ctx: _gate().record_run(rt, ctx)))
    schedule.register_args("rally_auto_join", hold(lambda: join_args(rt)))
    # …and it does not START at all when every squad it may spend is out (#1281). A push
    # lands for every banner on the map; a run that can only discover there is nobody to
    # send still costs a claim, a context and the queue slot behind it. The reading is
    # 0.06–0.10 s on the live client and is taken fresh at the moment of the decision —
    # «занят» stops being true in seconds, so nothing is cached.
    schedule.register_precondition(
        "rally_auto_join",
        hold(lambda: _gate().join_precondition(rt, _tab().join_squads(rt))))
    # …AND THE STATISTICS HOOK GETS THE SAME COURTESY (#1416). Two hooks on one event is
    # the design — one records the banners, one joins them — and what they must not do is
    # each re-do work the other's push already covered. This one reads the game's own
    # march table, which carries what the push does not (the leader, the target tile,
    # every member and the squad they sent); it simply stops doing it again for a banner
    # nothing has changed about. Its own record, so neither hook can eat the other's turn.
    schedule.register_precondition(
        "rally_monitor", hold(lambda: _gate().monitor_precondition(rt)))
