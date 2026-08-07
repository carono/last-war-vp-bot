r"""How long the rally auto-join takes to reach its send, step by step (task #1281).

The complaint is «стяги пропускаются»: a banner goes up, the panel says it heard the
push, and the squad never leaves. A rally lives for tens of seconds during an event, so
the only question worth asking is **how many seconds pass between the push and the
message going out**, and where they go.

This probe walks the same readings `actions/join_rally.md` walks, in the same order,
against the live client, and prints a millisecond figure per step. It sends NOTHING —
the join itself (`rally_join_send`) is deliberately not here, so the probe can be run
during an event without spending a squad.

    C:\Python312\python.exe tools\dev\rally_latency.py                 # default daemon
    C:\Python312\python.exe tools\dev\rally_latency.py --port 47655    # the other client
    C:\Python312\python.exe tools\dev\rally_latency.py --rounds 3

Read it beside `call_latency.py`, which times ONE call end to end and answers "was it us
or the client". This one answers "how many calls does the ability make, and what does
the queue in front of them cost" — the two numbers multiply, and that product is what
decides whether a banner is caught or missed.

Background and the numbers this produced: docs/research/rally-join.md.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import lua_client  # noqa: E402

# The readings the recipe takes before it can send, in its own order. Each is an
# expression, run the way `READ_LUA` runs one, so the timing includes everything a step
# of the recipe pays: the daemon queue, the hijack, the answer.
STEPS = (
    ("rally_monitor read", "(function() local wm=DataCenter.WorldMarchDataManager "
     "local col=wm and wm:GetAllMarches() if not col then return 0 end "
     "local e=col:GetEnumerator() local n=0 while e:MoveNext() do n=n+1 end return n end)()"),
    ("squads sieve (LUA)", "(function() local afd = DataCenter.ArmyFormationDataManager "
     "local n = 0 for _, v in pairs(afd.ArmyFormationList) do n = n + 1 end return n end)()"),
    ("free_squads", "#(DataCenter.__lw_rally_squads or {})"),
    ("rallies_out", "(function() local wm=DataCenter.WorldMarchDataManager "
     "local col=wm and wm:GetAllMarches() if not col then return 0 end local n=0 "
     "local e=col:GetEnumerator() while e:MoveNext() do local mo=e.Current.Value "
     "if mo==nil then mo=e.Current end local ok,t=pcall(function() return mo.teamUuid end) "
     "if ok and t~=nil and tostring(t)~='0' then n=n+1 end end return n end)()"),
    ("before-count", "(function() local P=LuaEntry.Player "
     "local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager "
     "local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() "
     "local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) "
     "if m~=nil and tostring(m.teamUuid)~='0' then n=n+1 end end) end return n end)()"),
    ("armed?", "(function() local p = DataCenter.__lw_rally_join "
     "if p == nil or p.formation == nil then return 0 end return 1 end)()"),
    ("soldiers", "(function() local afd = DataCenter.ArmyFormationDataManager local n = 0 "
     "for _, f in pairs(afd.ArmyFormationList) do pcall(function() "
     "n = n + (tonumber(f.totalSoldierNum) or 0) end) end return n end)()"),
)


def read(client, expr: str) -> tuple[float, str]:
    """One `READ_LUA`, timed. Returns ``(seconds, value)``."""
    chunk = ("local ok,v=pcall(function() return %s end) "
             'CS.UnityEngine.Debug.LogError("RLUA "..(ok and tostring(v) '
             'or ("ERR:"..tostring(v))))' % expr)
    started = time.monotonic()
    lines = client.run(chunk, marker="RLUA", settle=0.35, early=True)
    took = time.monotonic() - started
    value = ""
    for line in lines or []:
        if "RLUA " in line:
            value = line.split("RLUA ", 1)[1].strip()
    return took, value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=lua_client.PORT)
    ap.add_argument("--rounds", type=int, default=1)
    args = ap.parse_args()

    # Unleased on purpose: the probe must not take the game away from the panel, and an
    # unleased read is exactly what a background tab does. It still queues on the
    # daemon's per-call lock, which is the cost being measured.
    client = lua_client.DaemonClient(port=args.port, token="")
    state = client._rpc({"op": "ping"})
    print(f"daemon :{args.port}  warm={state.get('warm')}  pid={state.get('pid')}  "
          f"lease={state.get('lease')}")

    for round_no in range(1, args.rounds + 1):
        total = 0.0
        print(f"\n-- round {round_no} " + "-" * 40)
        for label, expr in STEPS:
            took, value = read(client, expr)
            total += took
            print(f"{label:22s} {took * 1000:8.0f} ms   {value}")
        print(f"{'TOTAL before the send':22s} {total * 1000:8.0f} ms "
              f"({len(STEPS)} calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
