"""The daily budget: how many rallies a day this account spends, and on what.

A squad sent to a rally is a squad that cannot march anywhere else until it comes
back, so «сколько ралли в день» is a real budget rather than a preference. `panel/
rally_limits.py` is the arithmetic (the per-type caps, the count that resets daily);
this is where the panel asks what the DAY looks like — and nothing more than that:

* :func:`trophy_progress` — how many rally trophies the game has paid today and how
  many are left before it stops paying. Asked of the client, which keeps the number
  itself; the panel keeps none.
* :func:`soldier_pool` — how many soldiers are standing in the base, which is what the
  join's own soldier floor is judged against (#1317). Also only a reading: the press
  reads the pool itself, inside the chunk it was already making.

**NOTHING HERE GATES A JOIN** (#1281), and :func:`join_gate` keeps its name only
because the schedule asks for one — it answers «yes» to everything. The tally behind the
gate this module used to hold had drifted twelve ahead of the client's own by the time
anybody compared them, so the count stopped being ours to keep.

**The day DOES have an end again (#1317) — it is simply not enforced here.** The player
asked for it back in one sentence: «лимит Роковой Элиты стоит 20, а бот целый день
цепляется к стягам». The ceiling is one number on «Автосбор» and the door is inside the
press (`actions/join_rally.md` → `lua_actions.rally_join_all`), judged against the GAME's
own daily rally counter. That keeps both rules at once: the gate lives in the ability, and
the count belongs to whoever decides it. What is left here is the per-kind record and the
cap on the tab's own «Запустить» run — neither of which a join is ever refused on.

NO Tk HERE, on purpose. The schedule runs the «rally_auto_join» trigger off the Tk
thread and must be able to gate it whether or not the «Ралли» tab is even in this
profile's tab list (docs/research/panel-tabs-refactor.md §5) — a budget that only
holds while a tab is on screen is not a budget.

The classification is BEST-EFFORT and says so: the push carries no type, so the
rallies are read from the VM and every one of them currently counts under the fallback
type. The Lua has the one spot to refine when a reliable zombie-invasion /
alliance-drill signal is confirmed live.
"""
from __future__ import annotations

from ... import rally_limits as rallylimitsmod

# One line per rally LEADER currently out. `kind` is where a confirmed zombie/drill
# signal would classify; until then every rally is the fallback monster type.
TYPES_CHUNK = (
    'local wm=DataCenter.WorldMarchDataManager local col=wm and wm:GetAllMarches() '
    'if not col then CS.UnityEngine.Debug.LogError("RTYPE end") return end '
    'local e=col:GetEnumerator() '
    'local function g(mo,k) local ok,v=pcall(function() return mo[k] end) '
    'if ok then return v end return nil end '
    'while e:MoveNext() do local mo=e.Current.Value if mo==nil then mo=e.Current end '
    'local team=g(mo,"teamUuid") local ts=tostring(team) '
    'if team~=nil and ts~="0" and ts~="nil" then local isL=false '
    'pcall(function() isL=(tostring(g(mo,"uuid"))==tostring(team-1)) end) '
    'if isL then local kind="%s" '
    'CS.UnityEngine.Debug.LogError("RTYPE="..kind) end end end '
    'CS.UnityEngine.Debug.LogError("RTYPE end")' % rallylimitsmod.UNKNOWN_TYPE
)


def types_out(rt) -> list:
    """Best-effort monster-type key per rally currently out, read off the game.

    ``[]`` when the game or the daemon cannot answer — the caller then lets the join
    proceed uncounted rather than blocking it on a failed read.

    NOT ON THE JOIN'S PATH, AND NOT A GATE ANY MORE (#1281). A reading in front of a
    banner cost more than it could save, and then the count it fed turned out to be a
    trophy threshold rather than a door — see :func:`trophy_progress`. Kept because it
    is the one place that knows how to classify a rally off the game.
    """
    if not rt.game.ready():
        return []
    try:
        lines = rt.game.evaluator().run(TYPES_CHUNK, marker="RTYPE", settle=0.8,
                                        early=True)
    except Exception:                        # noqa: BLE001 — a bad read is not a cap
        return []
    out = []
    for line in lines or []:
        if "RTYPE=" in line:
            key = line.split("RTYPE=", 1)[1].split()[0].strip()
            if key and key != "end":
                out.append(key)
    return out


#: The squads' own states, and nothing else — the cheapest question that can answer
#: «is there anybody to send». `state == 0` with `IsFree()` is the game's own idea of a
#: squad standing at home; a squad with NO SOLDIERS is deliberately counted as FREE,
#: because an empty squad is one request away from being full (#1285) and is not a
#: reason to skip a banner.
FREE_SQUADS_CHUNK = (
    'local afd = DataCenter.ArmyFormationDataManager local free = 0 '
    'local want = {%s} '
    'for _, f in pairs(afd.ArmyFormationList) do '
    'local idx = nil pcall(function() idx = tonumber(f.index) end) '
    'local wanted = (next(want) == nil) '
    'if not wanted and idx ~= nil then wanted = (want[idx] == true) end '
    'if wanted then '
    'local st = nil pcall(function() st = tonumber(f.state) end) '
    'local idle = true local ok, v = pcall(function() return f:IsFree() end) '
    'if ok and v ~= nil then idle = (v and true or false) end '
    'if st == nil or (st == 0 and idle) then free = free + 1 end end end '
    'CS.UnityEngine.Debug.LogError("FS free="..free)'
)


def free_squads(rt, squads=None):
    """How many of ``squads`` are standing at home RIGHT NOW — ``None`` if unreadable.

    Measured on the live client at **0.06–0.10 s** a call, which is what makes it cheap
    enough to ask BEFORE a run rather than inside one: the run it saves costs a claim,
    a scenario context and several calls of its own.

    Read fresh every time and never cached. «Занят» is a state that changes in seconds —
    a squad that was marching a minute ago may well be home — so a cached answer would
    skip banners for a reason that had already stopped being true.
    """
    if not rt.game.ready():
        return None
    want = ",".join("[%d]=true" % int(s) for s in (squads or [])
                    if str(s).strip().isdigit())
    try:
        lines = rt.game.evaluator().run(FREE_SQUADS_CHUNK % want, marker="FS",
                                        settle=0.4, early=True)
    except Exception:                        # noqa: BLE001 — a gate that cannot see must not refuse
        return None
    for line in reversed(lines or []):
        if "FS free=" in line:
            try:
                return int(line.split("FS free=", 1)[1].split()[0])
            except ValueError:
                return None
    return None


def join_precondition(rt, squads=None):
    """Why the auto-join must not even START — or ``None`` to let it run (#1281).

    «Не нужно вообще запускать сценарий авторалли, если все отряды заняты — только стек
    заполнять понапрасну.» A push arrives for every banner on the map and every one of
    them used to raise a run that claimed the client, opened a scenario context and
    found what could have been known in a tenth of a second: there is nobody to send.

    A GATE THAT CANNOT SEE DOES NOT REFUSE. An unreadable answer lets the run go ahead —
    the sieve inside it says `left=[…:out]` and nothing is lost but the run itself.
    """
    free = free_squads(rt, squads)
    if free is None or free > 0:
        return _already_weighed(rt)
    return "rally.skip.squads_out"


def _already_weighed(rt, hook: str = "join"):
    """…and the OTHER reason not to start: this banner has just been weighed (#1416).

    TWO HOOKS ON ONE EVENT IS THE DESIGN — one collects the statistics, one joins, «они
    делают разные вещи». What was not the design is the same WORK twice: both drivers of
    the JOIN hear the same push and both played the recipe over it, a fifth of a second
    apart, reading the same map and reaching the same answer. 123 of 514 runs in 5.6 live
    hours came back with a report identical to the one before it.

    THE KEY IS THE BANNER, NOT THE CLOCK (the operator's own words: «дедуп по самому
    ралли, а не по времени»). A banner in a state some run has already looked at is the
    duplicate; a banner whose seats have moved is news, and it is exactly the `refresh`
    that produced 113 of 131 live sends — so it goes through untouched.

    THIS REFUSES A RUN, NOT A JOIN. Nothing here decides whether a squad may be spent:
    the sieve inside the recipe does that, on the game's own numbers, exactly as before.
    And a profile whose ear is silent — no book at all — always passes, because the book
    is a floor under the join and never its source.
    """
    book = getattr(rt, "banners", None)
    if book is None or not hasattr(book, "worth_a_run"):
        return None
    try:
        if book.worth_a_run(hook, mark=True):
            return None
    except Exception:                    # noqa: BLE001 — a gate that cannot see, passes
        return None
    return "rally.skip.same_banners"


def monitor_precondition(rt):
    """Why the STATISTICS hook need not run either — the same rule, its own book (#1416).

    The two hooks are meant to be two: «один собирает статистику, второй присоединяется…
    они делают разные вещи». What neither of them needs to do is look at a banner it has
    already looked at in the state it is in. The statistics hook reads the game's own
    march table — the leader, the target tile, every member and the squad they sent,
    which the push does not carry — and re-reading it for a banner nothing has changed
    about is the 6.8% of the window this task measured: 406 runs in 5.6 hours, most of
    them re-reading what the push had just said.

    It keeps its OWN record of what it has weighed, so the join's turn is never eaten by
    the statistics' and the other way round.
    """
    return _already_weighed(rt, "stats")


def read(rt):
    """This profile's caps and today's counts, as a pair."""
    return (rallylimitsmod.load_limits(rt.profiles.rally_limits_json()),
            rallylimitsmod.load_counts(rt.profiles.rally_counts_json()))


def trophy_progress(rt) -> dict:
    """How many rally trophies today and how many are left — ASKED OF THE GAME (#1281).

    ``{}`` when the client cannot be reached; otherwise ``{"done", "max", "left"}``
    straight out of `DataCenter.MonsterManager`, which is where the client keeps it:

        daily_kill_boss   GetKillBossNum()      how many paid out today
        kill_boss_max_num GetMaxKillBossNum()   the threshold, 20
                          GetRestKillBossNum()  what is left of it

    **IT IS A READING, NOT A GATE.** The twenty is a trophy threshold: past it the game
    stops PAYING, it does not stop joining. Refusing a banner on it — which this module
    did until the player said what it actually does — was the panel forbidding something
    nothing forbids, and it cost twelve rallies in one afternoon.

    **AND IT IS NOT OURS TO COUNT.** The tally this file used to keep in
    `rally_counts.json` read twenty at the moment the client's own read eight. Two
    counters of one thing always end like that; there is one now, and it belongs to
    whoever decides the number.
    """
    try:
        if not rt.game.ready():
            return {}
    except Exception:                        # noqa: BLE001 — a reading, never the run
        return {}
    chunk = ("local MM = DataCenter.MonsterManager local a, b, c = -1, -1, -1 "
             "pcall(function() a = MM:GetKillBossNum() b = MM:GetMaxKillBossNum() "
             "c = MM:GetRestKillBossNum() end) "
             "CS.UnityEngine.Debug.LogError('TROPHY '..tostring(a)..' '..tostring(b)"
             "..' '..tostring(c))")
    try:
        lines = rt.game.evaluator().run(chunk, marker="TROPHY", settle=0.6, early=True)
    except Exception:                        # noqa: BLE001
        return {}
    for line in lines or []:
        if "TROPHY " not in line:
            continue
        parts = line.split("TROPHY ", 1)[1].split()
        try:
            done, top, left = (int(float(p)) for p in parts[:3])
        except (ValueError, IndexError):
            return {}
        if done < 0:
            return {}
        return {"done": done, "max": top, "left": left}
    return {}


def soldier_pool(rt) -> int:
    """How many soldiers are standing in the BASE right now — `-1` if unreadable (#1317).

    `SoldierDataManager:GetPlayerSoldiersTotalNum()`, which is what is at home: the pool
    goes down when a march leaves and back up when it returns (docs/research/
    rally-join.md). It is the very number the join's own floor is judged against, read
    here only so the person can see what they are setting the floor against.

    A READING AND NEVER A GATE. Nothing on a banner's path calls this — the press reads
    the pool inside the chunk it was already making — and it is called off the Tk thread,
    from the same background read that fetches the day's count.
    """
    try:
        if not rt.game.ready():
            return -1
    except Exception:                        # noqa: BLE001 — a reading, never the run
        return -1
    chunk = ("local n = -1 pcall(function() n = tonumber("
             "DataCenter.SoldierDataManager:GetPlayerSoldiersTotalNum()) or -1 end) "
             "CS.UnityEngine.Debug.LogError('POOL '..tostring(n))")
    try:
        lines = rt.game.evaluator().run(chunk, marker="POOL", settle=0.4, early=True)
    except Exception:                        # noqa: BLE001
        return -1
    for line in reversed(lines or []):
        if "POOL " in line:
            try:
                return int(float(line.split("POOL ", 1)[1].split()[0]))
            except (ValueError, IndexError):
                return -1
    return -1


def join_gate(rt) -> list:
    """The kinds a join may be COUNTED under. It never refuses — that is the point.

    The schedule wants a gate; this one has no opinion. The daily twenty is a trophy
    threshold rather than a door (:func:`trophy_progress`), so nothing here may stop a
    banner — and a gate that always answers is what keeps :func:`record_joins` wired,
    which is how the per-kind tally survives without the refusal that used to ride with
    it (#1281).
    """
    limits, _counts = read(rt)
    return list(limits.types()) or [rallylimitsmod.UNKNOWN_TYPE]


def kind_left(rt) -> str:
    """`kind:left,…` — what each kind of banner has left today, as the recipe wants it.

    `-1` is «no ceiling», which is what a cap of `0` means in the profile's file, and a
    kind with a ceiling that is spent is `0`. The recipe parks the string and the press
    decides per banner (#1317) — the panel supplies numbers and refuses nothing itself.

    THE COUNT IS THE PANEL'S HERE, unavoidably: the client keeps one daily rally counter
    and no per-species number (docs/research/rally-join.md).

    THE STAND-DOWN IS GONE, AND IT IS THE WHOLE REASON THIS DOOR NEVER SHUT (#1322).
    Until now this function answered `""` — no per-kind budget at all — whenever the
    panel's sum for today ran ahead of the game's `daily_kill_boss`. That compared two
    different quantities and therefore stood the door down permanently:

      * the panel counts a JOIN, at the moment the game confirms one more of our squads
        standing in a rally;
      * `daily_kill_boss` counts a rally that has FINISHED and paid today.

    So the panel is ahead by every squad currently marching, all day, every day — the
    recipe's own comment measured 320 panel joins against 275 counted by the game. Live
    on 2026-08-12 the two read 52 and 30, `general_trial_elite` stood at 30 against a cap
    of 20, and the word `kind_capped=` does not appear ONCE in that day's `panel.log`.
    The only thing that ever stopped the joining was the soldier floor.

    What #1281's stand-down was protecting against was a tally that counted SENDS and had
    gone twelve ahead of anything that happened. That tally is gone: since #1281's own
    `record_run` a join is written down only from `joined`, a difference measured in the
    client, so being ahead is LAG and not invention. The drift stays visible
    (:func:`day_summary`, the «наша сумма / игра» line on the tab and on the phone), and
    an overspend now says so out loud instead of passing quietly
    (:func:`over_budget`, :func:`record_joins`).
    """
    limits, counts = read(rt)
    parts = []
    for key in limits.types():
        left = counts.left_for(key, limits)
        if left < 0:
            continue                    # unlimited: say nothing, the press treats it so
        parts.append("%s:%d" % (key, left))
    return ",".join(parts)


def ahead_of_game(rt, counts=None) -> bool:
    """Has the panel counted more joins today than the GAME has (#1317)?

    A READING, AND NEVER A GATE (#1322). It used to switch every per-kind budget off,
    which is how «Элитные инструкторы» reached 30 against a cap of 20: the panel counts
    joins and the game counts finished rallies, so «ahead» is the ordinary state of an
    account with squads on the road rather than a sign that anything has drifted. It is
    kept because the drift is worth SHOWING — :func:`day_summary` draws both numbers —
    and it costs a VM read, so nothing on a banner's path may call it.

    Unreadable game, unreadable answer: `False`.
    """
    if counts is None:
        _limits, counts = read(rt)
    progress = trophy_progress(rt)
    done = progress.get("done", -1) if progress else -1
    if done < 0:
        return False
    return sum(counts.counts.values()) > done


def day_summary(rt) -> dict:
    """Both numbers side by side, so the drift is VISIBLE rather than quiet (#1317).

    ``{"kinds": <the panel's sum for today>, "game": <daily_kill_boss>, "max": <the
    game's threshold>, "drift": kinds - game}``; `game` is `-1` when the client could not
    be asked. The person asked for this in as many words: a panel-kept tally is only
    honest while anybody can see how far it has wandered from the game's own count.
    """
    _limits, counts = read(rt)
    progress = trophy_progress(rt)
    ours = sum(counts.counts.values())
    done = progress.get("done", -1) if progress else -1
    return {"kinds": ours, "game": done,
            "max": progress.get("max", 0) if progress else 0,
            "drift": (ours - done) if done >= 0 else 0}


def kinds_of(ctx) -> list:
    """What KIND each thing the run spent was, in the order it spent them.

    The chunk classifies every banner it sends to and hands the list back as `kinds`
    (`zombie_invasion`, `monster`, …). Empty when the run reported none, and an empty
    list writes nothing: a run records only what it sent (#1281).
    """
    raw = getattr(ctx, "vars", {}).get("kinds", "")
    return [part for part in str(raw or "").split(",") if part.strip()]


def joined_of(ctx) -> int:
    """How many of our squads are standing in a rally that were not before the run.

    The recipe's own `joined`, which is the only honest count of a join (#1237). Absent
    on every path that sent nothing, and that is the right answer there: a push over a
    quiet map must not spend a day's rallies.
    """
    try:
        return max(0, int(float(getattr(ctx, "vars", {}).get("joined", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def record_run(rt, ctx) -> int:
    """THE ONE PLACE A JOIN IS WRITTEN DOWN, whichever driver played the recipe (#1281).

    Two things play `join_rally`: the schedule's «rally_auto_join» trigger and the «Ралли»
    tab's own reader, which raises a join for every banner the capture hears. Only the
    first went through the schedule's record hook, so every join the tab's driver made
    was missing from the per-kind tally — measured over one live window, 1 join of 13 was
    recorded through the trigger and `rally_counts` read 11 against 13 confirmed.

    So the counting rule lives HERE, in one function, and both drivers call it. It is one
    entry per squad this run actually sent, capped by what the run confirmed: `joined` is
    a DIFFERENCE, and a squad the OTHER driver sent that lands mid-run falls inside both
    runs' differences, so without the cap both would record it.

    Returns how many entries were written, so a caller can say so.
    """
    kinds = kinds_of(ctx)
    did = min(joined_of(ctx), len(kinds))
    record_joins(rt, kinds, did)
    return did


def record_joins(rt, kinds, did: int = 1) -> None:
    """Count what the run actually joined, EACH UNDER ITS OWN KIND, persisted for today.

    ``kinds`` is the run's own list — one entry per squad the chunk sent, in the order it
    sent them (`DataCenter.__lw_rally_kinds`), classified against the invasion event's own
    monster lists. Counting them all under one key is what made an invasion boss spend the
    ordinary monsters' budget back when the budget still refused things.

    ``did`` is how many joins the game confirmed; the ones that landed are counted from
    the front of the list, so a send that achieved nothing writes nothing.

    IT IS A RECORD, AND SINCE #1317 IT IS ALSO A RULE — the per-kind one. Nothing about
    the writing changed; what changed is that :func:`kind_left` reads it back, because the
    game keeps no per-species number to read instead. The total the day actually costs is
    still the game's own `MonsterManager` count (:func:`trophy_progress`), and that is the
    ceiling that cannot drift.

    AND IT IS WHERE A LEAKING DOOR SAYS SO (#1322). A budget that is past its cap can
    only mean the gate did not hold — the numbers were not handed to the press, or the
    press did not judge them — and the first time that happened nothing said a word: the
    count went to 30 against a cap of 20 and the only sign of it was a number on a table
    nobody was looking at. So every kind that goes over is named in the log, once per run
    that put it over, on both front-ends because the log is shared.
    """
    kinds = [str(k).strip() for k in (kinds or []) if str(k).strip()]
    if did <= 0 or not kinds:
        return
    path = rt.profiles.rally_counts_json()
    counts = rallylimitsmod.load_counts(path)
    for key in kinds[:did]:
        counts = counts.record(key)
    counts = counts.with_day_end(day_end_ms(rt))
    rallylimitsmod.save_counts(counts, path)
    limits = rallylimitsmod.load_limits(rt.profiles.rally_limits_json())
    for key, spent, cap in over_budget(rt, counts, limits):
        if key not in kinds[:did]:
            continue                    # somebody else's overspend, not this run's news
        try:                             # the kind's own words, when there is a locale
            label = rt.t("rally_limit.type." + key)
        except Exception:                # noqa: BLE001
            label = key
        try:
            rt.say("rally", "rally_kind.over_budget", kind=label, count=spent, cap=cap)
        except Exception:                # noqa: BLE001 — a complaint, never the run
            pass


def over_budget(rt, counts=None, limits=None) -> list:
    """Every kind whose day has gone PAST its cap — `[(kind, counted, cap), …]` (#1322).

    Empty is the ordinary answer and the only one a working gate can give: the press
    passes over a kind with nothing left, so a count can reach its cap and never exceed
    it. Anything in this list is the gate having failed — the budgets never reached the
    press, or reached it and were not judged — which is exactly the state #1322 was
    reported in and which nothing was saying out loud.

    Drawn by the tab and by the phone (both show «today/cap» per kind) and said in the
    log by :func:`record_joins`; it reads two files and asks the game nothing, so it is
    safe to call anywhere.
    """
    if limits is None or counts is None:
        stored_limits, stored_counts = read(rt)
        limits = limits if limits is not None else stored_limits
        counts = counts if counts is not None else stored_counts
    out = []
    for key in limits.types():
        cap = limits.limit_for(key)
        spent = counts.count_for(key)
        if cap > 0 and spent > cap:
            out.append((key, spent, cap))
    return out


def over_text(rt, over) -> str:
    """«Элитные инструкторы 30/20, …» — the overspend in the kinds' own words (#1322).

    One function because two front-ends draw it: the red line under the table in the
    window and the row on the phone. The digits are data and need no translating; the
    kind's name is `rally_limit.type.<kind>`, which is filled from the game's own tables.
    """
    parts = []
    for key, spent, cap in over or ():
        try:
            label = rt.t("rally_limit.type." + key)
        except Exception:                    # noqa: BLE001 — a line, never the run
            label = key
        parts.append("%s %d/%d" % (label, spent, cap))
    return ", ".join(parts)


def day_end_ms(rt) -> int:
    """When the SERVER's day turns, asked of the client — `0` if it cannot answer.

    Written into the counts file so the tally rolls on the game's boundary rather than on
    a date this machine works out (#1317). Asked HERE, right after a run, because that is
    the one moment a client is certainly there and nothing is waiting on the answer — a
    banner's path never touches it.
    """
    try:
        if not rt.game.ready():
            return 0
    except Exception:                        # noqa: BLE001 — a stamp, never the run
        return 0
    import lua_actions
    chunk = ("CS.UnityEngine.Debug.LogError('DAYEND '..tostring(%s))"
             % lua_actions.server_day_end())
    try:
        lines = rt.game.evaluator().run(chunk, marker="DAYEND", settle=0.4, early=True)
    except Exception:                        # noqa: BLE001
        return 0
    for line in lines or []:
        if "DAYEND " in line:
            try:
                return int(float(line.split("DAYEND ", 1)[1].split()[0]))
            except (ValueError, IndexError):
                return 0
    return 0


def record(rt, counts, type_key):
    """Count ONE rally of ``type_key`` and persist. Returns the new counts.

    The create loop holds its counts across repeats, so it hands them in rather than
    re-reading the file per rally.
    """
    counts = counts.record(type_key)
    rallylimitsmod.save_counts(counts, rt.profiles.rally_counts_json())
    return counts
