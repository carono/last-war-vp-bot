"""The daily budget: how many rallies a day this account spends, and on what.

A squad sent to a rally is a squad that cannot march anywhere else until it comes
back, so «сколько ралли в день» is a real budget rather than a preference. `panel/
rally_limits.py` is the arithmetic (the per-type caps, the count that resets daily);
this is where the panel asks what the DAY looks like — and nothing more than that:

* :func:`trophy_progress` — how many rally trophies the game has paid today and how
  many are left before it stops paying. Asked of the client, which keeps the number
  itself; the panel keeps none.

**NOTHING HERE GATES A JOIN** (#1281). The daily twenty is a trophy threshold, not a
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


def record(rt, counts, type_key):
    """Count ONE rally of ``type_key`` and persist. Returns the new counts.

    The create loop holds its counts across repeats, so it hands them in rather than
    re-reading the file per rally.
    """
    counts = counts.record(type_key)
    rallylimitsmod.save_counts(counts, rt.profiles.rally_counts_json())
    return counts
