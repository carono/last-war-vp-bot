r"""World-map treasures ("сокровища на карте") — dig march + claim, no-click.

Two primitives for the treasure an alliance's Detect Event drops on the world map
(task #1107, docs/research/world-treasures.md). A treasure is a `world.get.block`
tile (`WorldPointType.TREASURE == 21`); members march onto it to dig, and the
finisher claims the gift.

    march  — send a squad to dig it   (MarchUtil.SendCreateMarchMessage,
                                        MarchTargetType.DETECT_TREASURE / CROSS_DETECT_TREASURE)
    claim  — take the dug treasure    (SFSNetwork.SendMessage detect.event.claim.treasure)

Both are the exact calls captured from a live session; the march is the same launch
primitive as attack.py/scout, only the MarchTargetType differs. Same-server vs
cross-server is auto-picked from the viewed server unless forced with --cross/--same.

Usage (run under the Windows Python so it reaches the warm Lua daemon)::

    C:\Python312\python.exe tools\dig_treasure.py march <pid> <uuid> [serverId] [formation]
    C:\Python312\python.exe tools\dig_treasure.py march --xy <x> <y> <uuid> [serverId] [formation]
    C:\Python312\python.exe tools\dig_treasure.py claim <uuid> [serverId]

`pid` is the treasure tile index (its point's pointId, e.g. 500553 -> (552,500)); the
`--xy` form computes it from tile coordinates instead. `uuid` is the treasure UUID and
`serverId` its targetServer, both from the point data (push.world.point.update field
f11.1 / the id suffix) — the same pair the `claim` needs. serverId / formation default
to env LW_DEFAULT_SERVER / LW_DEFAULT_FORMATION.

NOT PROVEN LIVE YET: no treasure was on the map during the RE (treasures_num == 0), so
neither send has been fired end-to-end. Shapes are verbatim from the capture and from
the working attack / ghost-recon primitives. The server gates both on the per-day limit.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "tools/lib")
import lua_actions as A  # noqa: E402
from lua_client import get_evaluator  # noqa: E402  daemon-backed when running
from tool_config import default_formation, default_server  # noqa: E402

DEFAULT_FORMATION = default_formation()
DEFAULT_SERVER = default_server()


def _one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def _viewed_server(ev):
    """The world server currently on screen (for same/cross auto-pick); 0 if unknown."""
    line = _one(ev.run(A.current_server(), marker="ACT", settle=1.0), "curserver=")
    try:
        return int(line.split("curserver=", 1)[1].split()[0])
    except (IndexError, ValueError):
        return 0


def _pid_from_xy(ev, x, y):
    """Resolve a tile index from (x, y) via the game's SceneUtils.TilePosToIndex."""
    line = _one(ev.run(
        'CS.UnityEngine.Debug.LogError("ACT pid="..tostring('
        'SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(%d,%d))))' % (int(x), int(y)),
        marker="ACT", settle=1.0), "ACT pid=")
    return line.split("pid=", 1)[1].split()[0]


def _march_state(ev):
    """(IsHaveMarchInWorld, owner-march count) — the reliable launch signal (attack.py)."""
    return _one(ev.run(
        'local wm=DataCenter.WorldMarchDataManager local o=wm:GetOwnerMarches() local n=0 '
        'if o then pcall(function() n=o.Count end) if n==nil then n=0 for _ in pairs(o) do n=n+1 end end end '
        'CS.UnityEngine.Debug.LogError("HV="..tostring(wm:IsHaveMarchInWorld()).." om="..tostring(n))',
        marker="HV", settle=1.0), "HV=")


def march(pid, uuid, srv, formation, cross):
    ev = get_evaluator()
    if cross is None:
        viewed = _viewed_server(ev)
        cross = bool(viewed and int(srv) and viewed != int(srv))
    kind = "CROSS_DETECT_TREASURE (182)" if cross else "DETECT_TREASURE (50)"
    print("dig march: pid=%s uuid=%s serverId=%s formation=%s -> %s"
          % (pid, uuid, srv, formation, kind), flush=True)
    print("BEFORE:", _march_state(ev), flush=True)

    ev.run(A.dig_treasure_march(pid, uuid, srv, formation, cross=cross),
           marker="ACT", settle=1.5)

    time.sleep(3.0)
    res = _march_state(ev)
    print("AFTER:", res, flush=True)
    print("MARCH LAUNCHED" if "HV=true" in res
          else "NO MARCH (uuid stale / treasure gone / no free squad / daily limit)", flush=True)
    ev.close()


def claim(uuid, srv):
    ev = get_evaluator()
    print("claim: uuid=%s serverId=%s (detect.event.claim.treasure)" % (uuid, srv), flush=True)
    line = _one(ev.run(A.claim_treasure(uuid, srv), marker="ACT", settle=1.5),
                "claim_treasure_sent")
    print("sent:", line or "(no ack line — check Player.log)", flush=True)
    print("Reward lands as UIGiftPackageRewardGet + push.detect.treasure.claim if accepted.",
          flush=True)
    ev.close()


def _force_cross(argv):
    """Pop --cross/--same from argv; return True/False/None (auto)."""
    if "--cross" in argv:
        argv.remove("--cross")
        return True
    if "--same" in argv:
        argv.remove("--same")
        return False
    return None


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = a[0]
    rest = a[1:]
    cross = _force_cross(rest)

    if cmd == "march":
        ev_needed_xy = rest and rest[0] == "--xy"
        if ev_needed_xy:
            if len(rest) < 4:
                print("usage: dig_treasure.py march --xy <x> <y> <uuid> [serverId] [formation]")
                sys.exit(2)
            x, y, uuid = rest[1], rest[2], rest[3]
            srv = rest[4] if len(rest) > 4 else DEFAULT_SERVER
            formation = rest[5] if len(rest) > 5 else DEFAULT_FORMATION
            ev = get_evaluator()
            pid = _pid_from_xy(ev, x, y)
            ev.close()
        else:
            if len(rest) < 2:
                print("usage: dig_treasure.py march <pid> <uuid> [serverId] [formation]")
                sys.exit(2)
            pid, uuid = rest[0], rest[1]
            srv = rest[2] if len(rest) > 2 else DEFAULT_SERVER
            formation = rest[3] if len(rest) > 3 else DEFAULT_FORMATION
        if not srv:
            print("no serverId: pass it or set LW_DEFAULT_SERVER (.env)")
            sys.exit(2)
        if not formation:
            print("no formationUuid: pass it or set LW_DEFAULT_FORMATION (.env)")
            sys.exit(2)
        march(pid, uuid, srv, formation, cross)
        return

    if cmd == "claim":
        if len(rest) < 1:
            print("usage: dig_treasure.py claim <uuid> [serverId]")
            sys.exit(2)
        uuid = rest[0]
        srv = rest[1] if len(rest) > 1 else DEFAULT_SERVER
        if not srv:
            print("no serverId: pass it or set LW_DEFAULT_SERVER (.env)")
            sys.exit(2)
        claim(uuid, srv)
        return

    print("unknown command %r (march | claim)" % cmd)
    sys.exit(2)


if __name__ == "__main__":
    main()
