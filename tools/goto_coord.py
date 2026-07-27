r"""Go to world coordinates (X, Y) [on SERVER] — the real in-engine navigation, no pixel tap.

Entry points:

  * default  -> `GoToUtil.GotoWorldPos(Vector3(X*2+1,0,Y*2+1), 105, nil, nil, serverId)` :
                the game's OWN "go to coordinate on server" jump (`lua_actions.jump_to_coord`),
                captured live from the in-game magnifier flow. ONE call for same- and
                cross-server: a foreign SERVER loads and enters that world, the home SERVER
                centres on it. No `UIMoveCity` teleport window, so map input stays alive.
                SERVER defaults to the home server when omitted.
  * --click  -> `GoToUtil.OnClickWorldPoint(pid, type, uuid)` : exactly what a real tap on
                the map does — navigate AND select, opening the tile's UIWorldPoint popup
                with its detail loaded. The "click" happens inside the game, so there is no
                pydirectinput pixel tap to miss and nothing under-sent. Same-server only.

    C:\Python312\python.exe tools\goto_coord.py <X> <Y> [SERVER]        # jump (real, GotoWorldPos)
    C:\Python312\python.exe tools\goto_coord.py 650 480                 # -> home server (650,480)
    C:\Python312\python.exe tools\goto_coord.py 499 499 972             # -> server 972 (499,499)
    C:\Python312\python.exe tools\goto_coord.py 576 492 --click 2 <uuid>   # navigate + select
"""
import sys
sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval
import lua_actions as A


def one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def cur(run):
    return one(run(
        'local WS=_G.WS if not WS or not WS.CurTilePos then '
        'local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) '
        'for i=0,arr.Length-1 do if arr[i] and arr[i]:GetType().Name=="WorldScene" then WS=arr[i] break end end _G.WS=WS end '
        'CS.UnityEngine.Debug.LogError("CUR=("..tostring(WS.CurTilePos.x)..","..tostring(WS.CurTilePos.y)..")")',
        "CUR", 1.0), "CUR=")


def main():
    argv = sys.argv[1:]
    if len(argv) < 2:
        print(__doc__); return
    x, y = int(argv[0]), int(argv[1])
    rest = argv[2:]

    ev = get_evaluator()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    print("before:", cur(run), flush=True)

    if rest and rest[0] == "--click":
        ptype = int(rest[1]) if len(rest) > 1 else 0
        uuid = int(rest[2]) if len(rest) > 2 else 0
        chunk = A.click_world_point(x, y, ptype, uuid)
        marker, tag = "ACT", "click"
    else:
        srv = int(rest[0]) if rest and rest[0].lstrip("-").isdigit() else A.HOME_SERVER
        chunk = A.jump_to_coord(x, y, srv)
        marker, tag = "ACT", "jump srv=%d" % srv

    print(one(run(chunk, marker, 2.0), "ACT "), flush=True)
    print("after:", cur(run), flush=True)
    print("target: (%d,%d) via %s" % (x, y, tag), flush=True)
    ev.close()


if __name__ == "__main__":
    main()
