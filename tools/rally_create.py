r"""Create (raise) an alliance rally on a «Роковая Элита» of a chosen level — no-click.

This is the CREATE side of a rally; the JOIN side (walking a squad onto a rally that is
already out) is tools/rally_join.py. Creating one means finding a live rally-elite of the
wanted level on the world map and raising the banner («Стягивание») on it.

Two steps, both driven through xLua SafeDoString (docs/research/xlua-state.md):

  FIND  — a «Роковая Элита» is a rally-only world monster: its popup reads
          `GetMonsterData(uuid).canAttack == 0` (a soloable monster reads `1`). Monsters are
          not carried in any data manager (docs/research/world-monsters.md Findings 1-10), so
          the only way to read a monster's level + uuid is the clone-hunt: scan the
          `WorldMonster*(Clone)` objects through their `TouchObjectEventTrigger`, `:OnClick()`
          one to open its `UIWorldPoint` popup, read `Ctrl.pointId/uuid/serverId` and
          `Ctrl:GetMonsterData(uuid).level/.canAttack`, then `Ctrl:CloseSelf()` (NEVER
          DestroyAllWindow — it kills the HUD). Keep the first whose `canAttack==0` and whose
          level is the wanted one. The already-clicked clones are remembered on the VM
          (`DataCenter.__lw_elite_seen`) so repeated calls walk fresh ones.

  CREATE — raise the banner: schedule `MarchUtil.SendCreateMarchMessage(...)` on the game's own
          main thread (a cold send from the hijack thread is created but dropped by the server —
          docs/research/world-monsters.md Finding 17), warming the formation first the way the
          join does (`OnClickStartMarch` + `GoToUtil.CloseAllWindows()`).

⚠ UNPROVEN. The FIND read path (clone-hunt + `GetMonsterData(uuid)`) is the same one the solo
attack proved live. The CREATE wire, however, was never captured: the solo launch is target
type 1, the JOIN is type 6 (docs/research/rally-join.md), but the exact «Стягивание» *create*
send has no live capture. RALLY_CREATE_TARGET below is the best hypothesis and is a single
constant to flip once a real create is sniffed. Do not mark this ability ✅ until then.

Usage::

    python tools/rally_create.py --find [--level N]        # just report the elites in view
    python tools/rally_create.py --level N --squad M [--server S]

`--squad` picks which squad raises the banner (its formation uuid, read live off the game, same
resolver as rally_join.py). `--server` defaults to LW_DEFAULT_SERVER; the elite carries its own
server, which wins when found.
"""
import argparse
import sys
import time

sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval
from tool_config import default_server
# The squad -> formation-uuid resolver is shared with the JOIN side; no second copy.
from rally_join import formation_by_squad, pick_formation

# MarchTargetType for a rally. Joining an existing team is 6 (docs/research/rally-join.md); the
# CREATE of a fresh rally on a monster is UNPROVEN (never sniffed). 6 is the hypothesis — flip to
# 7 (MarchTargetType.RALLY_FOR_BOSS) here if a live «Стягивание» capture shows that instead.
RALLY_CREATE_TARGET = 6
# rallyType passed to OnClickStartMarch when it warms the formation (RALLY_FOR_BOSS), same value
# the join's warm step uses.
RALLY_FOR_BOSS = 7

DEFAULT_SERVER = default_server()


def _one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def _reset_seen(run):
    """Forget the clones a previous scan already opened (start a fresh hunt)."""
    run('DataCenter.__lw_elite_seen = {} CS.UnityEngine.Debug.LogError("EL reset")',
        "EL reset", 0.6)


# Open the NEXT not-yet-seen WorldMonster clone's popup (its TouchObjectEventTrigger:OnClick),
# remembering it on the VM so the next call takes a different one. Boss clones are skipped — the
# rally elite is a WorldMonster clone, and a Boss clone is the alliance world-boss, a different
# thing. Emits `EL clicked <name>` or `EL none` when every clone in view has been seen.
_CLICK_NEXT = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
DataCenter.__lw_elite_seen = DataCenter.__lw_elite_seen or {}
local seen = DataCenter.__lw_elite_seen
local ok, err = pcall(function()
  local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
  for i = 0, arr.Length - 1 do
    local mb = arr[i]
    if mb and mb:GetType().Name == 'TouchObjectEventTrigger' then
      local okgo, go = pcall(function() return mb.gameObject end)
      if okgo and go then
        local p, depth = go, 0
        while p and not string.find(p.name, 'WorldMonster') and p.transform.parent and depth < 6 do
          p = p.transform.parent.gameObject; depth = depth + 1
        end
        if p and string.find(p.name, 'WorldMonster') and not string.find(p.name, 'Boss') then
          local id = p:GetInstanceID()
          if not seen[id] then
            seen[id] = true
            pcall(function() mb:OnClick() end)
            L("clicked " .. tostring(p.name))
            return
          end
        end
      end
    end
  end
  L("none")
end)
if err then L("error " .. tostring(err)) end
'''

# Read the open UIWorldPoint popup: point/uuid/server and the monster's level + canAttack (the
# uuid arg is REQUIRED for the full detail — docs/research/world-monsters.md Finding 8).
_READ_POPUP = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
local ok, err = pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  local c = w and w.Ctrl
  if not c then L("popup none") return end
  local lvl, ca = "?", "?"
  pcall(function() local md = c:GetMonsterData(c.uuid) lvl = tostring(md.level) ca = tostring(md.canAttack) end)
  L("popup pid=" .. tostring(c.pointId) .. " uuid=" .. tostring(c.uuid)
    .. " server=" .. tostring(c.serverId) .. " level=" .. lvl .. " canAttack=" .. ca)
end)
if err then L("popup err " .. tostring(err)) end
'''

# Close ONLY the monster popup (keep the HUD): the game's own CloseSelf, never DestroyAllWindow.
_CLOSE_POPUP = (
    'pcall(function() UIManager.Instance:GetStackTopWindow().Ctrl:CloseSelf() end) '
    'CS.UnityEngine.Debug.LogError("EL closed")'
)


def find_elite(ev, level=None, max_scan=15):
    """Return the first rally elite in view (dict pid/uuid/server/level), or ``None``.

    ``level`` filters to that exact level; ``None`` returns the first rally elite of any level.
    A "rally elite" is a monster whose popup reads ``canAttack == 0`` (soloable monsters, which
    have their own solo attack, are skipped). Opens each candidate's popup, reads it, and closes
    it again — so the map is left as it was found.
    """

    def run(chunk, marker, settle=1.4):
        return ev.run(chunk, marker=marker, settle=settle)

    _reset_seen(run)
    for _ in range(max_scan):
        clicked = _one(run(_CLICK_NEXT, "EL", 2.0), "EL ")
        if "none" in clicked or "clicked" not in clicked:
            break
        # The popup detail arrives after a server round-trip — retry the read a few times.
        popup = ""
        for _ in range(4):
            popup = _one(run(_READ_POPUP, "EL", 1.0), "popup ")
            if "pid=nil" not in popup and "canAttack=?" not in popup and "level=?" not in popup:
                break
            time.sleep(0.8)
        run(_CLOSE_POPUP, "EL closed", 0.8)
        if "pid=nil" in popup or "popup none" in popup:
            continue
        info = _parse_popup(popup)
        if info is None or info["canAttack"] != 0:
            continue                     # not a rally elite (soloable / unreadable)
        if level is not None and info["level"] != int(level):
            continue                     # wrong level
        return info
    return None


def _parse_popup(line):
    """Parse an `EL popup pid=.. uuid=.. server=.. level=.. canAttack=..` line to a dict."""
    out = {}
    for key in ("pid", "uuid", "server", "level", "canAttack"):
        if key + "=" in line:
            out[key] = line.split(key + "=")[1].split()[0]
    if "pid" not in out or "uuid" not in out:
        return None
    try:
        return {
            "pid": out["pid"],
            "uuid": out["uuid"],
            "server": out.get("server") if out.get("server") not in (None, "nil", "") else None,
            "level": int(out["level"]) if out.get("level") not in (None, "nil", "?") else None,
            "canAttack": int(out["canAttack"]) if out.get("canAttack") not in (None, "nil", "?") else -1,
        }
    except (TypeError, ValueError):
        return None


def create_rally(ev, pid, uuid, server, formation):
    """Raise a rally on the elite at ``pid`` (uuid/server from its popup) with ``formation``.

    Warms the squad the way the join does (a cold formation makes the send a silent no-op), then
    schedules the create send on the main thread. Returns whether the send was ARMED (not whether
    the server honoured it — the CREATE wire is unproven, see the module docstring).
    """

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    # Warm only if every formation is cold — the same rule the join follows.
    if pick_formation(run) is None:
        run('pcall(function() MarchUtil.OnClickStartMarch(%d,%s,%s,-1,1,%d,%s,0,0) end) '
            'CS.UnityEngine.Debug.LogError("RC warm")'
            % (RALLY_CREATE_TARGET, pid, uuid, RALLY_FOR_BOSS, server), "RC warm", 1.5)
        run('pcall(function() GoToUtil.CloseAllWindows() end) '
            'CS.UnityEngine.Debug.LogError("RC closed")', "RC closed", 0.8)

    out = run(
        'TimerManager:GetInstance():DelayInvoke(function() '
        'local ok,err=pcall(function() '
        'MarchUtil.SendCreateMarchMessage(%s, %d, %s, %s, 1, 1, false, %s, nil) end) '
        'CS.UnityEngine.Debug.LogError("RC sent ok="..tostring(ok).." err="..tostring(err)) '
        'end, 0.5) '
        'CS.UnityEngine.Debug.LogError("RC armed")'
        % (formation, RALLY_CREATE_TARGET, pid, uuid, server), "RC", 1.8)
    return any("RC armed" in ln for ln in out)


def create_on_level(ev, level, squad, server=None):
    """Find a rally elite of ``level`` and raise a rally on it with ``squad``.

    Returns a result dict ``{ok, reason, pid, uuid, server, level, formation}``. ``ok`` is True
    only when an elite was found AND the create send was armed. ``reason`` names the miss
    (``no_elite`` / ``no_formation``) so a caller (the panel loop) can report it.
    """

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    elite = find_elite(ev, level)
    if elite is None:
        return {"ok": False, "reason": "no_elite", "level": level}
    srv = elite["server"] or (str(server) if server is not None else DEFAULT_SERVER)
    formation = formation_by_squad(run, squad)
    if not formation:
        return {"ok": False, "reason": "no_formation", "squad": squad, **elite, "server": srv}
    armed = create_rally(ev, elite["pid"], elite["uuid"], srv, formation)
    return {"ok": bool(armed), "reason": "armed" if armed else "not_armed",
            "formation": formation, "server": srv, **elite}


def main():
    ap = argparse.ArgumentParser(
        description="Create (raise) an alliance rally on a «Роковая Элита» of a chosen level.")
    ap.add_argument("--find", action="store_true",
                    help="only report the rally elites in view, do not raise anything")
    ap.add_argument("--level", type=int,
                    help="target elite level (required unless --find with no level)")
    ap.add_argument("--squad", type=int, choices=(1, 2, 3, 4),
                    help="which squad raises the banner (1/2/3/4)")
    ap.add_argument("--server", type=int, help="target server (defaults to LW_DEFAULT_SERVER)")
    args = ap.parse_args()

    ev = get_evaluator()
    try:
        if args.find:
            # Walk every clone in view once and print each rally elite found.
            def run(chunk, marker, settle=1.4):
                return ev.run(chunk, marker=marker, settle=settle)
            _reset_seen(run)
            seen_any = False
            for _ in range(15):
                clicked = _one(run(_CLICK_NEXT, "EL", 2.0), "EL ")
                if "none" in clicked or "clicked" not in clicked:
                    break
                popup = ""
                for _ in range(4):
                    popup = _one(run(_READ_POPUP, "EL", 1.0), "popup ")
                    if "pid=nil" not in popup and "level=?" not in popup:
                        break
                    time.sleep(0.8)
                run(_CLOSE_POPUP, "EL closed", 0.8)
                info = _parse_popup(popup)
                if info and info["canAttack"] == 0:
                    seen_any = True
                    print("elite level=%s pid=%s uuid=%s server=%s"
                          % (info["level"], info["pid"], info["uuid"], info["server"]), flush=True)
            if not seen_any:
                print("no rally elite in view", flush=True)
            return

        if args.level is None or args.squad is None:
            ap.error("--level and --squad are required (or use --find)")
        res = create_on_level(ev, args.level, args.squad, args.server)
        if res["ok"]:
            print("RALLY ARMED level=%s squad=%s pid=%s server=%s (create wire UNPROVEN — "
                  "confirm a march/banner appears)" % (res.get("level"), args.squad,
                                                       res.get("pid"), res.get("server")), flush=True)
        elif res["reason"] == "no_elite":
            print("no rally elite of level %s in view" % args.level, flush=True)
        elif res["reason"] == "no_formation":
            print("no squad %s found (nothing raised)" % args.squad, flush=True)
        else:
            print("send not armed (see RC lines above)", flush=True)
    finally:
        ev.close()


if __name__ == "__main__":
    main()
