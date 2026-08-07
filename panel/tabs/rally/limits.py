"""The daily budget: how many rallies a day this account spends, and on what.

A squad sent to a rally is a squad that cannot march anywhere else until it comes
back, so «сколько ралли в день» is a real budget rather than a preference. `panel/
rally_limits.py` is the arithmetic (the per-type caps, the count that resets daily);
this is where the panel asks what the DAY looks like — and nothing more than that:

* :func:`trophy_progress` — how many rally trophies the game has paid today and how
  many are left before it stops paying. Asked of the client, which keeps the number
  itself; the panel keeps none.

**NOTHING HERE GATES A JOIN** (#1281), and :func:`join_gate` keeps its name only
because the schedule asks for one — it answers «yes» to everything. The daily twenty is a trophy threshold, not a
door: past it the game stops paying and the joining goes on. A gate on it was the panel
forbidding what nothing forbids, and the tally behind that gate had drifted twelve ahead
of the client's own by the time anybody compared them.

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
        return None
    return "rally.skip.squads_out"


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


def record_joins(rt, kinds, did: int = 1) -> None:
    """Count what the run actually joined, EACH UNDER ITS OWN KIND, persisted for today.

    ``kinds`` is the run's own list — one entry per squad the chunk sent, in the order it
    sent them (`DataCenter.__lw_rally_kinds`), classified against the invasion event's own
    monster lists. Counting them all under one key is what made an invasion boss spend the
    ordinary monsters' budget back when the budget still refused things.

    ``did`` is how many joins the game confirmed; the ones that landed are counted from
    the front of the list, so a send that achieved nothing writes nothing.

    IT IS A RECORD, NOT A RULE. Nothing reads this back to refuse a join. What the day
    actually costs is the game's own `MonsterManager` count (:func:`trophy_progress`);
    this is the panel's own note of WHAT it went to, which the game does not keep.
    """
    kinds = [str(k).strip() for k in (kinds or []) if str(k).strip()]
    if did <= 0 or not kinds:
        return
    path = rt.profiles.rally_counts_json()
    counts = rallylimitsmod.load_counts(path)
    for key in kinds[:did]:
        counts = counts.record(key)
    rallylimitsmod.save_counts(counts, path)


def record(rt, counts, type_key):
    """Count ONE rally of ``type_key`` and persist. Returns the new counts.

    The create loop holds its counts across repeats, so it hands them in rather than
    re-reading the file per rally.
    """
    counts = counts.record(type_key)
    rallylimitsmod.save_counts(counts, rt.profiles.rally_counts_json())
    return counts
