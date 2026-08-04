"""The daily budget: how many rallies a day this account spends, and on what.

A squad sent to a rally is a squad that cannot march anywhere else until it comes
back, so «сколько ралли в день» is a real budget rather than a preference. `panel/
rally_limits.py` is the arithmetic (the per-type caps, the count that resets daily);
this is where the panel asks it the two questions it has:

* **before a join** — which of the rallies currently out are still under their cap;
* **after one** — count what was let through.

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
    """
    if not rt.game.up():
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


def join_gate(rt):
    """The rally types out that are still under their daily cap.

    ``None`` when the types could not be read (the join then proceeds uncounted);
    ``[]`` when every type out is at its cap (the caller skips the join); otherwise the
    eligible types, which are counted after a clean join.
    """
    types = types_out(rt)
    if not types:
        return None
    limits, counts = read(rt)
    eligible = [t for t in types if counts.allowed(t, limits)]
    if not eligible:
        rt.say("trigger", "triggers.log.rally_capped")
    return eligible


def record_joins(rt, types) -> None:
    """Count one join per eligible rally type, persisted for today."""
    path = rt.profiles.rally_counts_json()
    counts = rallylimitsmod.load_counts(path)
    for key in types:
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
