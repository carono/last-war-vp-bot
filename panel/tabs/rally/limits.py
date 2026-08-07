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

    NOT ON THE JOIN'S PATH ANY MORE (#1281): see :func:`join_gate` for why a reading in
    front of a banner costs more than it can save. Kept because it is the one place that
    knows how to classify a rally off the game, and the shape a real zombie/drill signal
    would slot into.
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


def join_gate(rt):
    """The rally types still under their daily cap — answered from the FILE, not the game.

    ``[]`` when EVERY type is at its cap (the caller skips the join entirely); otherwise
    the keys still allowed, which is what the recipe is handed so it can skip the banners
    whose kind is spent and send to the rest.

    **IT USED TO COST A GAME CALL, AND IT STOOD IN FRONT OF THE JOIN** (#1281). The gate
    read the whole march table before the recipe was allowed to start, at 1.3–19 s a
    call, to be told a constant. It answers from the counts file now.

    **AND IT USED TO ASK ABOUT ONE KEY ONLY.** `zombie_invasion` is configured uncapped
    because the event does not ration those rallies — and the gate asked whether
    `monster` was spent, so once the ordinary twenty were gone the auto-join refused
    invasion bosses too. Every key is asked now, and a kind with no cap keeps the door
    open for itself alone.
    """
    limits, counts = read(rt)
    allowed = [key for key in limits.types() if counts.allowed(key, limits)]
    if not allowed:
        rt.say("trigger", "triggers.log.rally_capped")
    return allowed


def blocked_types(rt) -> list:
    """The keys that ARE at their cap — what the recipe parks so the chunk can skip them.

    The mirror of :func:`join_gate`, and it is the half that stops a squad: the gate only
    says whether the run may start at all, and a run allowed because invasion bosses are
    uncapped must still not spend an ordinary monster's twenty-first.
    """
    limits, counts = read(rt)
    return [key for key in limits.types() if not counts.allowed(key, limits)]


def record_joins(rt, kinds, did: int = 1) -> None:
    """Count what the run actually joined, EACH UNDER ITS OWN KEY, persisted for today.

    ``kinds`` is the run's own list — one entry per squad the chunk sent, in the order it
    sent them (`DataCenter.__lw_rally_kinds`). It used to be the gate's answer and every
    join was written under `types[0]`, so an invasion boss — which the event does not
    ration and which this file is configured never to cap — spent the ordinary monsters'
    budget. A key whose cap is 0 is unlimited and recording under it costs nothing, which
    is exactly what «uncapped» has to mean.

    ``did`` is how many joins the game confirmed. Fewer than the sends means some did not
    land, and the ones that did are counted from the front of the list rather than all of
    them: a send that achieved nothing must not spend a day's budget (#1281).
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
