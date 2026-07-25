r"""Jump the world-map camera to arbitrary game coordinates (X, Y) — no UI, no magnifier window.

The in-game magnifier ("лупа" → enter X/Y → jump) is `UISearchCtrl:OnJumpClick(server, x, y)`, which
internally calls **`GoToUtil.GotoPos(worldPos, zoom, time, onComplete, serverId, worldId)`**. Captured
the exact worldPos it passes: for tile (X, Y) it is `Vector3(X*2+1, 0, Y*2+1)` (TileSize=2, +1 = tile
centre) with `zoom=105`. So the coordinate jump can be done directly, with no window opened at all:

  GoToUtil.GotoPos(CS.UnityEngine.Vector3(X*2+1, 0, Y*2+1), 105, nil, nil, serverId, nil)

Verified live: WorldScene.CurTilePos moved exactly to (X, Y), UIManager stack stayed empty (top=nil).
(`GoToUtil.MoveToWorldPoint(SceneUtils.TilePosToIndex(Vector2Int(X,Y)))` is an equivalent pid-based
jump; GotoPos is the one the magnifier's coordinate search actually uses.)

    C:\Python312\python.exe tools\goto_coord.py <X> <Y> [serverId]
    C:\Python312\python.exe tools\goto_coord.py 650 480 935
"""
import sys, time
sys.path.insert(0, "tools")
from lua_eval import LuaEval


def one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def main():
    if len(sys.argv) < 3:
        print(__doc__); return
    x = int(sys.argv[1])
    y = int(sys.argv[2])
    srv = sys.argv[3] if len(sys.argv) > 3 else "935"

    ev = LuaEval()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    def cur():
        return one(run(
            'local WS=_G.WS if not WS then local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) '
            'for i=0,arr.Length-1 do if arr[i] and arr[i]:GetType().Name=="WorldScene" then WS=arr[i] break end end _G.WS=WS end '
            'CS.UnityEngine.Debug.LogError("CUR=("..tostring(WS.CurTilePos.x)..","..tostring(WS.CurTilePos.y)..")")',
            "CUR", 1.0), "CUR=")

    print("before:", cur(), flush=True)
    r = one(run(
        'local ok,err=pcall(function() GoToUtil.GotoPos(CS.UnityEngine.Vector3(%d*2+1, 0, %d*2+1), 105, nil, nil, %s, nil) end) '
        'CS.UnityEngine.Debug.LogError("J ok="..tostring(ok).." err="..tostring(err))' % (x, y, srv),
        "J", 1.6), "J ")
    print(r, flush=True)
    time.sleep(1.5)
    print("after:", cur(), flush=True)
    print("target: (%d,%d)" % (x, y), flush=True)
    ev.close()


if __name__ == "__main__":
    main()
