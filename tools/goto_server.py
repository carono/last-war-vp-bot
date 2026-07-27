r"""Switch to another server's world the way the in-game UI does — clean, no teleport window.

This replays the exact sequence the engine runs on a MANUAL server switch, reverse-engineered
with `tools/lua_trace.py --dedup` while the player switched servers by hand (two switches, to
8131 and 1040). The trace showed the switch is just:

    CrossServerUtil.OnCrossServer(serverId)     -- enter the cross-server context
    GoToUtil.GotoServerZone(serverId, false)    -- navigate to that server's zone

and, crucially, it used NEITHER `JumpToServerByServerId` NOR `SetCrossEnableList` — those are
the move-city bulk-load hack (`tools/dev/cross_server.py`) that also pops the `UIMoveCity`
teleport UI. `GotoServerZone` is the clean entry point: no teleport window, no authorize-list
dance. It loads the target for servers the client is already authorized to view — i.e. servers
in an active cross-server event group (the traced switch belonged to the yuntie/meteorite battle
group). For an arbitrary out-of-event server, use `tools/dev/cross_server.py` instead.

Return home:  CrossServerUtil.OnBackSelfServer() + SceneUtils.ChangeToCity()  (also from the trace)

    C:\Python312\python.exe tools\goto_server.py <serverId>
    C:\Python312\python.exe tools\goto_server.py 1040
    C:\Python312\python.exe tools\goto_server.py --home        # return to the home server
"""
import sys
import time

sys.path.insert(0, "tools/lib")

import lua_actions as LA
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval


def _one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    ev = get_evaluator()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    if sys.argv[1] == "--home":
        run('pcall(function() CrossServerUtil.OnBackSelfServer() end) '
            'pcall(function() SceneUtils.ChangeToCity() end) '
            'CS.UnityEngine.Debug.LogError("H back home")', "H", 1.2)
        time.sleep(3)
        st = _one(run('CS.UnityEngine.Debug.LogError("HS IsInOther="..'
                      'tostring(select(2,pcall(function() return CrossServerUtil.IsInOtherServer() end))))',
                      "HS", 1.0), "HS ")
        print("returned home:", st, flush=True)
        ev.close()
        return

    srv = int(sys.argv[1])

    # Clean in-game switch: OnCrossServer(srv) + GotoServerZone(srv, false).
    r = _one(run(LA.goto_server(srv), "ACT", 1.8), "ACT ")
    print("switch:", r, flush=True)

    # Give the world a moment to stream in, then report the cross-server state.
    time.sleep(3)
    v = _one(run(
        'CS.UnityEngine.Debug.LogError("V IsInOther="..'
        'tostring(select(2,pcall(function() return CrossServerUtil.IsInOtherServer() end)))..'
        '" reason="..tostring(select(2,pcall(function() return CrossServerUtil.GetCrossEnableReason(%d) end))))'
        % srv, "V", 1.4), "V ")
    print("result:", v, flush=True)
    print("target server: %d" % srv, flush=True)
    ev.close()


if __name__ == "__main__":
    main()
