r"""Create (raise) an alliance rally on a world monster of a chosen level — no-click.

Two kinds of target are searchable, and they differ only in which «лупа» tab is pressed: a
«Роковая Элита» (the `boss` tab, `find.monster.boss`) and an ordinary world monster (the
`monster` tab, `find.monster`). Both take levels 1–200 — seasonal events put very high-level
monsters on the map. Everything after the search — reading the popup the game opens and
raising the banner — is the same for both.

This is the CREATE side of a rally; the JOIN side (walking a squad onto a rally that is
already out) is tools/rally_join.py. Creating one means getting a rally-elite of the wanted
level onto the map and raising the banner («Стягивание») on it.

Two steps, both driven through xLua SafeDoString (docs/research/xlua-state.md):

  SPAWN  — use the game's own world-map search («лупа», the `UISearch` window), not a scan of
           whatever clones happen to be loaded on screen. Open `UISearch`, set the search level
           for the wanted kind (`Ctrl:SetCurNumBySearchType(type, level, 0)`), then press the
           magnifier (`Ctrl:OnSearchClick(type, 0)`). That sends the server the "find a monster
           of this level near me" request; when the server answers, the game flies the camera to
           the monster it produced and opens its `UIWorldPoint` popup by itself
           (`OnSearchEnd` → `GoToUtil.MoveToWorldMarchAndOpen`). We then read the popup's
           `pointId/uuid/serverId` and `GetMonsterData(uuid).level/.canAttack` and close it with
           `Ctrl:CloseSelf()` (NEVER DestroyAllWindow — it kills the HUD). A rally elite reads
           `canAttack == 0` (a soloable monster reads `1`); a soloable result is treated as
           "no rally elite of that level".

  CREATE — raise the banner: schedule `MarchUtil.SendCreateMarchMessage(...)` on the game's own
          main thread (a cold send from the hijack thread is created but dropped by the server —
          docs/research/world-monsters.md Finding 17), warming the formation first the way the
          join does (`OnClickStartMarch` + `GoToUtil.CloseAllWindows()`).

⚠ UNPROVEN. The SPAWN path drives the real «лупа» (its `OnSearchClick` was seen to fire the
server request live); whether a monster of the asked level comes back depends on one being
available in the game, and the CREATE wire itself was never captured (the solo launch is target
type 1, the JOIN is type 6 — docs/research/rally-join.md — but the «Стягивание» *create* send has
no live capture). RALLY_CREATE_TARGET below is the best hypothesis and is a single constant to
flip once a real create is sniffed. Do not mark this ability ✅ until then.

Usage::

    python tools/rally_create.py --find --level N [--type monster|boss]   # search + report only
    python tools/rally_create.py --level N --squad M [--type monster|boss] [--server S]

`--squad` picks which squad raises the banner (its formation uuid, read live off the game, same
resolver as rally_join.py). `--type` picks the «лупа» tab the elite is searched under (defaults
to the module constant). `--server` defaults to LW_DEFAULT_SERVER; the elite carries its own
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

# «лупа» search tabs (UISearchType enum, read live). A live search for a level-35 Fatal Elite
# was captured going out under the `Boss` tab — `find.monster.boss` with the level as its whole
# payload — and the server answered with the elite's popup (`MoveToWorldMarchAndOpen` →
# `UIWorldPoint`). The `Monster` tab («лупа» for ordinary field monsters) sends `find.monster`,
# which never carries the elite — searching a level-35 elite there returned nothing («нет
# подходящих монстров»). So the elite is searched under `Boss`, and `--type monster` searches
# the ordinary field monsters instead.
UISEARCH_TYPE = {"monster": 1, "boss": 5}
RALLY_ELITE_SEARCH = "boss"

# How high the level may go per tab — the same 1–200 for both. A season puts levels far above
# the old elite ceiling on the map, and each tab's own ceiling follows the account/season (the
# Monster tab read 30 here once, the Boss tab 35 — docs/research/rally-elite-search.md), so this
# is the range the tool is willing to ask for, not a promise the server has one: a level it has
# nothing for comes back empty like any other miss. Kept per-kind so a range can be tightened
# alone if a live capture ever shows a tab refusing what was asked. A level outside its tab's
# range is clamped into it rather than sent.
SEARCH_LEVEL_RANGE = {"monster": (1, 200), "boss": (1, 200)}

DEFAULT_SERVER = default_server()


def _one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def search_kind(search_type=None):
    """Normalise a requested search kind to one the «лупа» knows (`boss` / `monster`)."""
    kind = search_type or RALLY_ELITE_SEARCH
    return kind if kind in UISEARCH_TYPE else "monster"


def level_range(search_type=None):
    """The ``(min, max)`` level the given search kind accepts — see SEARCH_LEVEL_RANGE."""
    return SEARCH_LEVEL_RANGE[search_kind(search_type)]


def clamp_level(level, search_type=None):
    """The level as an int, pulled into the kind's range (unparseable reads as the minimum)."""
    low, high = level_range(search_type)
    try:
        return max(low, min(high, int(level)))
    except (TypeError, ValueError):
        return low


# Open the world-map search window («лупа»).
_OPEN_SEARCH = (
    'pcall(function() UIManager.Instance:OpenWindow(UIWindowNames.UISearch) end) '
    'CS.UnityEngine.Debug.LogError("EL search-open")'
)

# Set the search level for the wanted kind and press the magnifier. `OnSearchClick(type, subType)`
# reads the level back via `GetCurNumBySearchType` and fires the server request; the subType 0 is
# the default sub-tab (a nil subType trips the recorder — SearchPanelDataManager). Emits
# `EL search-fired` when the request went out, or `EL search-err <e>` / `EL search-notopen`.
_FIRE_SEARCH = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
local ok, err = pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  if not w or w.Name ~= "UISearch" then L("search-notopen win=" .. tostring(w and w.Name)) return end
  local c = w.Ctrl
  c:SetCurNumBySearchType(%(type)d, %(level)d, 0)
  c:OnSearchClick(%(type)d, 0)
  L("search-fired level=%(level)d type=%(type)d")
end)
if err then L("search-err " .. tostring(err)) end
'''

# Read the popup the search opened on its own (`OnSearchEnd` → `MoveToWorldMarchAndOpen` opens
# `UIWorldPoint`). While the server has not answered yet the top window is still `UISearch`
# (`EL popup waiting`); once it flips to `UIWorldPoint` we read point/uuid/server + the monster's
# level and canAttack (the uuid arg is REQUIRED — docs/research/world-monsters.md Finding 8).
_READ_POPUP = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  if not w then L("popup none") return end
  if w.Name ~= "UIWorldPoint" then L("popup waiting win=" .. tostring(w.Name)) return end
  local c = w.Ctrl
  local lvl, ca = "?", "?"
  pcall(function() local md = c:GetMonsterData(c.uuid) lvl = tostring(md.level) ca = tostring(md.canAttack) end)
  L("popup pid=" .. tostring(c.pointId) .. " uuid=" .. tostring(c.uuid)
    .. " server=" .. tostring(c.serverId) .. " level=" .. lvl .. " canAttack=" .. ca)
end)
'''

# Close whatever the search left on top (the monster popup, or UISearch if nothing was found),
# keeping the HUD: the game's own CloseSelf, never DestroyAllWindow.
_CLOSE_TOP = (
    'pcall(function() local w = UIManager.Instance:GetStackTopWindow() '
    'if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() end end) '
    'CS.UnityEngine.Debug.LogError("EL closed")'
)


def spawn_elite(ev, level, search_type=None, wait_s=10.0):
    """Search the «лупа» for a monster of ``level`` and return its popup (dict), or ``None``.

    Drives the real world-map search: open `UISearch`, set the level, press the magnifier, then
    wait for the game to fly to the monster the server produced and open its `UIWorldPoint`
    popup. Returns a dict ``{pid, uuid, server, level, canAttack}`` for whatever came back, or
    ``None`` when the search fired but no monster of that level was returned in ``wait_s`` seconds
    (or the search could not be fired). The caller decides whether the result is a rally elite
    (``canAttack == 0``). The popup is closed again before returning, so the map is left as found.

    ``search_type`` picks the «лупа» tab (`boss` for the Fatal Elite, `monster` for ordinary
    field monsters); ``level`` is clamped into that tab's range (SEARCH_LEVEL_RANGE).
    """
    kind = search_kind(search_type)
    st = UISEARCH_TYPE[kind]
    level = clamp_level(level, kind)

    def run(chunk, marker, settle=1.4):
        return ev.run(chunk, marker=marker, settle=settle)

    run(_OPEN_SEARCH, "EL search-open", 1.6)
    fired = _one(run(_FIRE_SEARCH % {"type": st, "level": int(level)}, "EL", 1.8), "EL ")
    if "search-fired" not in fired:
        run(_CLOSE_TOP, "EL closed", 0.8)
        return None

    # The popup arrives after a server round-trip — poll until it opens or the wait runs out.
    popup = ""
    for _ in range(max(1, int(wait_s))):
        popup = _one(run(_READ_POPUP, "EL", 1.0), "popup ")
        if ("pid=" in popup and "pid=nil" not in popup
                and "waiting" not in popup and "popup none" not in popup
                and "level=?" not in popup and "canAttack=?" not in popup):
            break
        time.sleep(0.9)

    run(_CLOSE_TOP, "EL closed", 0.8)
    if "pid=" not in popup or "pid=nil" in popup or "waiting" in popup or "popup none" in popup:
        return None
    return _parse_popup(popup)


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


def create_on_level(ev, level, squad, server=None, search_type=None):
    """Search a rally elite of ``level`` («лупа») and raise a rally on it with ``squad``.

    Returns a result dict ``{ok, reason, pid, uuid, server, level, formation}``. ``ok`` is True
    only when a rally elite was found AND the create send was armed. ``reason`` names the miss
    (``no_elite`` when the search returned nothing or a soloable monster, ``no_formation`` when
    the squad is not loaded) so a caller (the panel loop) can report it.

    ``search_type`` picks the «лупа» tab and with it the level range the search accepts
    (1–200 for both kinds); ``level`` is clamped into it.
    """

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    level = clamp_level(level, search_type)
    elite = spawn_elite(ev, level, search_type)
    # A search miss, or a soloable monster (canAttack != 0) is not a rally elite.
    if elite is None or elite.get("canAttack") != 0:
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
        description="Create (raise) an alliance rally on a world monster of a chosen level.")
    ap.add_argument("--find", action="store_true",
                    help="only search the «лупа» for the level and report, do not raise anything")
    ap.add_argument("--level", type=int,
                    help="target level (required); clamped to the tab's range — %s"
                         % ", ".join("%s %d-%d" % (k, *SEARCH_LEVEL_RANGE[k])
                                     for k in sorted(SEARCH_LEVEL_RANGE)))
    ap.add_argument("--squad", type=int, choices=(1, 2, 3, 4),
                    help="which squad raises the banner (1/2/3/4)")
    ap.add_argument("--type", choices=sorted(UISEARCH_TYPE), default=RALLY_ELITE_SEARCH,
                    help="which «лупа» tab to search under — `boss` is the Fatal Elite, "
                         "`monster` the ordinary field monsters (default %(default)s)")
    ap.add_argument("--server", type=int, help="target server (defaults to LW_DEFAULT_SERVER)")
    args = ap.parse_args()

    ev = get_evaluator()
    try:
        if args.find:
            if args.level is None:
                ap.error("--find needs --level N")
            level = clamp_level(args.level, args.type)
            elite = spawn_elite(ev, level, args.type)
            if elite is None:
                print("no %s of level %s returned by the search" % (args.type, level), flush=True)
            elif elite.get("canAttack") != 0:
                print("found a SOLOABLE monster level=%s pid=%s uuid=%s server=%s (cannot be "
                      "rallied)" % (elite["level"], elite["pid"], elite["uuid"], elite["server"]),
                      flush=True)
            else:
                print("rally target (%s) level=%s pid=%s uuid=%s server=%s"
                      % (args.type, elite["level"], elite["pid"], elite["uuid"], elite["server"]),
                      flush=True)
            return

        if args.level is None or args.squad is None:
            ap.error("--level and --squad are required (or use --find --level N)")
        res = create_on_level(ev, args.level, args.squad, args.server, args.type)
        if res["ok"]:
            print("RALLY ARMED level=%s squad=%s pid=%s server=%s (create wire UNPROVEN — "
                  "confirm a march/banner appears)" % (res.get("level"), args.squad,
                                                       res.get("pid"), res.get("server")), flush=True)
        elif res["reason"] == "no_elite":
            print("no ralliable %s of level %s found by the search"
                  % (args.type, clamp_level(args.level, args.type)), flush=True)
        elif res["reason"] == "no_formation":
            print("no squad %s found (nothing raised)" % args.squad, flush=True)
        else:
            print("send not armed (see RC lines above)", flush=True)
    finally:
        ev.close()


if __name__ == "__main__":
    main()
