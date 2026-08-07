r"""What the auto-join actually did, counted off the panel's own log (task #1281).

The acceptance criterion for the rally auto-join is not a feeling — it is «not one
banner missed without a named reason» — so it needs counting over hours rather than a
glance at the last few lines. This reads a profile's `debug.log` (millisecond stamps,
one file per profile) and prints the tally:

  * how many pushes fired the trigger, and what became of each — run, re-armed mid-run,
    or coalesced onto a run that had not looked at anything yet;
  * how many runs of `join_rally` there were, how many squads were SENT, and how many
    joins the GAME confirmed (a send returns cleanly whether the server took it or
    dropped it — only a squad standing in a rally proves anything, #1237);
  * why every run that sent nothing sent nothing, in buckets, out of the chunk's own
    report — no banner out, every squad already marching, every squad empty, more
    banners than squads, the link gone, the day's cap spent;
  * **the empty-squad case on a line of its own**, because it has no working route at
    all right now (the game's own screen launch throws, #1285) and mixing it into the
    ordinary skips would hide a real gap behind a plausible word;
  * and the delay from the push landing to the send going out — min, median, max.

    C:\Python312\python.exe tools\dev\rally_stats.py                  # this profile
    C:\Python312\python.exe tools\dev\rally_stats.py --profile main
    C:\Python312\python.exe tools\dev\rally_stats.py --since 16:40    # from a time
    C:\Python312\python.exe tools\dev\rally_stats.py --watch 300      # every 5 min

A SKIP WITH NO REASON IS THE BUG THIS LOOKS FOR. The last section counts runs that sent
nothing and said nothing; it must stay at zero, and if it does not, the run's own lines
are printed so the hole can be found.

Background and the numbers this produced: docs/research/rally-join.md.
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
import time
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The lines this reads, by the substring that identifies each. All of them are English
#: on purpose — the technical logger writes in English whatever language the panel is
#: showing, so a tally does not break when somebody switches locale.
FIRE = "fire rally_auto_join on"
RUN = "rally_auto_join: > action: join_rally"
SEND = "rally_auto_join:   TAP join every rally"
REPORT = "rally_auto_join:   READ_LUA report = "
JOINED = "rally_auto_join:   READ_LUA joined = "
SCREEN = "CALL join_rally_via_screen"
FAILED = "run of rally_auto_join failed"
SKIPPED = "skipped rally_auto_join"
#: A run that ended in a FAIL says why in its own words. Bucketed alongside the reports
#: so that EVERY run is accounted for: a run that neither sent nor explained itself is
#: the bug this file exists to catch, and it can only be spotted by adding up.
FAILTEXT = "rally_auto_join: < action: join_rally FAILED"

#: The report's own trailing sentence -> the bucket it is counted in. The words come from
#: `lua_actions.rally_join_all`; anything unrecognised lands in «other» and is printed,
#: which is how a new ending announces itself instead of being silently averaged away.
BUCKETS = (
    ("no rally of this alliance is out", "no banner of ours was out"),
    ("more rallies than squads", "more banners than squads to spend"),
)

STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\.(\d{3})\]")

#: A FAIL's own sentence -> the short bucket it is counted under. Long enough to be
#: recognisable, short enough to line up in a column.
FAIL_WORDS = (
    ("no longer talking to the game server", "the link to the server was gone"),
    ("came down before the squad", "the banner came down first"),
    ("empty squad was filled and launched", "the screen path launched and nothing joined"),
    ("did not bring up the squad screen", "the squad screen never opened"),
    ("would not take the chosen squad", "the screen refused the squad"),
    ("no squad appeared in a rally", "the send went out and no squad appeared"),
    ("could not be paired up", "no formation for the chosen squad"),
)


def _fail_bucket(text: str) -> str:
    for needle, bucket in FAIL_WORDS:
        if needle in text:
            return bucket
    return "other: " + text[:60]


def stamp(line: str) -> float | None:
    """The line's time as seconds within its day, or ``None`` for a continuation line."""
    m = STAMP.match(line)
    if not m:
        return None
    h, mnt, s = (int(x) for x in m.group(2).split(":"))
    return h * 3600 + mnt * 60 + s + int(m.group(3)) / 1000.0


def read(path: str, since: str | None) -> list:
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    if not since:
        return lines
    out, on = [], False
    for line in lines:
        m = STAMP.match(line)
        if m and m.group(2) >= since:
            on = True
        if on:
            out.append(line)
    return out


def tally(lines: list) -> dict:
    """Every number, counted ONE RUN AT A TIME.

    The first version of this added up line kinds and came out with «33 runs accounted
    for out of 30»: a run can both report a reason and then fail — the empty-squad case
    reports `not one of the chosen squads`, calls the screen path and fails there — so
    counting lines double-counts runs. The accounting line is the whole point of the
    file, and an accounting line that can exceed its own total is worth nothing. So the
    log is cut into runs at `> action: join_rally`, and each run is put in exactly one
    bucket, by its LAST word about itself.
    """
    fires, again, waiting = [], 0, 0
    pending_fire: float | None = None
    latencies: list = []
    first = last = None
    runs: list = []                       # one dict per run, in order
    cur: dict | None = None

    for line in lines:
        at = stamp(line)
        if at is not None:
            first = first if first is not None else at
            last = at
        if FIRE in line:
            fires.append(at)
            pending_fire = at
            continue
        if "rally_auto_join" in line and "на ходу" in line:
            again += 1
            continue
        if "rally_auto_join" in line and "очереди" in line:
            waiting += 1
            continue
        if SKIPPED in line:
            runs.append({"skipped": True})
            continue
        if RUN in line:
            cur = {"report": None, "sent": 0, "joined": 0, "screen": False,
                   "fail": None}
            runs.append(cur)
            continue
        if cur is None:
            continue
        if SEND in line:
            if pending_fire is not None and at is not None and at >= pending_fire:
                latencies.append(at - pending_fire)
                pending_fire = None
        elif REPORT in line:
            cur["report"] = line.split(REPORT, 1)[1].strip().strip("'")
            m = re.search(r"sent=(\d+)", cur["report"] or "")
            cur["sent"] = int(m.group(1)) if m else 0
        elif JOINED in line:
            try:
                cur["joined"] = max(cur["joined"],
                                    int(line.split(JOINED, 1)[1].split()[0]))
            except (ValueError, IndexError):
                pass
        elif SCREEN in line:
            cur["screen"] = True
        elif FAILTEXT in line:
            cur["fail"] = line.split("FAILED", 1)[1].lstrip(" —-").strip()

    reasons, fails, squads_left = Counter(), Counter(), Counter()
    empty_only = joined_runs = sent_total = joins = screens = 0
    # A CROSS-CUT, not a bucket: how many runs found a banner out and every squad they
    # were allowed to spend standing EMPTY, however the run then ended. Most of them end
    # in the screen path's failure and are bucketed there, so the exclusive count says 0
    # and the gap disappears — which is exactly what must not happen while that case has
    # no working route (#1285).
    empty_seen = 0
    unexplained: list = []

    for run in runs:
        if run.get("skipped"):
            fails["the schedule refused the run before it started"] += 1
            continue
        rep = run["report"] or ""
        screens += 1 if run["screen"] else 0
        sent_total += run["sent"]
        joins += run["joined"]
        left = re.search(r"left=\[(.*?)\]", rep)
        words = [w.split(":")[1] for w in left.group(1).split()] if left else []
        for w in words:
            squads_left[w] += 1
        # ONE bucket per run, decided by the last thing it said about itself.
        tail0 = re.search(r"-- (.*)$", rep)
        if (tail0 and "not one of the chosen squads" in tail0.group(1)
                and words and all(w == "empty" for w in words)):
            empty_seen += 1
        if run["fail"]:
            fails[_fail_bucket(run["fail"])] += 1
            continue
        if run["sent"] > 0:
            joined_runs += 1
            continue
        tail = re.search(r"-- (.*)$", rep)
        if not tail:
            unexplained.append(rep or "(the run said nothing at all)")
            continue
        text = tail.group(1)
        if "not one of the chosen squads" in text:
            if words and all(w == "empty" for w in words):
                empty_only += 1          # its own line: no working route yet (#1285)
            else:
                reasons["every squad was already out"] += 1
            continue
        for needle, bucket in BUCKETS:
            if needle in text:
                reasons[bucket] += 1
                break
        else:
            reasons["other: " + text[:60]] += 1

    return {
        "span": (first, last),
        "fires": len(fires), "again": again, "waiting": waiting,
        "runs": len(runs), "sends": len(latencies), "sent": sent_total, "joins": joins,
        "screens": screens, "failures": sum(fails.values()),
        "reasons": reasons, "empty_only": empty_only, "left": squads_left,
        "fails": fails, "latencies": latencies, "unexplained": unexplained,
        "empty_seen": empty_seen,
        "with_send": joined_runs,
    }


def show(t: dict) -> None:
    first, last = t["span"]
    if first is not None and last is not None:
        mins = max(0.0, (last - first)) / 60.0
        print(f"window: {mins:.0f} min")
    print(f"pushes that fired           : {t['fires']}"
          f"   (re-armed mid-run {t['again']}, coalesced {t['waiting']})")
    print(f"runs of join_rally          : {t['runs']}")
    print(f"presses that went out       : {t['sends']}")
    print(f"squads SENT                 : {t['sent']}")
    print(f"joins CONFIRMED by the game : {t['joins']}")
    print(f"runs that failed            : {t['failures']}")
    if t["latencies"]:
        lat = sorted(t["latencies"])
        print(f"push -> send, seconds       : min {lat[0]:.2f}"
              f"  median {statistics.median(lat):.2f}  max {lat[-1]:.2f}"
              f"   (n={len(lat)})")
    else:
        print("push -> send, seconds       : nothing was sent in this window")

    print("\nwhy a run sent nothing:")
    for name, n in t["reasons"].most_common():
        print(f"  {n:5d}  {name}")
    for name, n in t["fails"].most_common():
        print(f"  {n:5d}  {name}")
    print(f"\nof those, a banner was out and EVERY squad it could spend stood empty:"
          f" {t['empty_seen']}"
          f"\n   (counted across the buckets above, not beside them — that case has no"
          f"\n    working route yet: the game's own screen launch throws, #1285)")

    if t["left"]:
        print("\nsquads passed over, by word:")
        for name, n in t["left"].most_common():
            print(f"  {n:5d}  {name}")
    # THE ACCOUNTING LINE. Every run either sent something, explained itself in the
    # chunk's report, or failed saying why. Anything left over is a run that went by in
    # silence — the one thing this ability is not allowed to do (#1281).
    explained = (sum(t["reasons"].values()) + t["empty_only"]
                 + sum(t["fails"].values()) + t["with_send"])
    print(f"\nruns accounted for          : {explained} of {t['runs']}")
    print(f"runs that sent nothing and said nothing: "
          f"{max(0, t['runs'] - explained) + len(t['unexplained'])}")
    for rep in t["unexplained"][:5]:
        print("   !", rep)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default=None,
                    help="profile directory name (default: the active one)")
    ap.add_argument("--since", default=None, help="HH:MM:SS to start counting from")
    ap.add_argument("--watch", type=float, default=0,
                    help="re-print every N seconds instead of once")
    args = ap.parse_args()

    name = args.profile
    if not name:
        import json
        with open(os.path.join(REPO, "profiles", "settings.json"), encoding="utf-8") as fh:
            name = json.load(fh).get("active_profile") or "default"
    path = os.path.join(REPO, "profiles", name, "debug.log")
    if not os.path.exists(path):
        print(f"no debug.log for profile {name!r}", file=sys.stderr)
        return 2

    while True:
        print(f"=== {name}  {time.strftime('%H:%M:%S')} " + "=" * 30)
        show(tally(read(path, args.since)))
        if not args.watch:
            return 0
        print()
        time.sleep(args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
