r"""Create (raise) an alliance rally on a world monster of a chosen level — no-click.

Two kinds of target are searchable, and they differ only in which «лупа» tab is pressed: a
«Роковая Элита» (the `boss` tab, `find.monster.boss`) and an ordinary world monster (the
`monster` tab, `find.monster`). Both take levels 1–200 — seasonal events put very high-level
monsters on the map. Everything after the search — the monster's popup, its rally button and
the squad screen behind it — is the same for both.

This is the CREATE side of a rally; the JOIN side (walking a squad onto a rally that is
already out) is tools/rally_join.py. Creating one means getting a rally target of the wanted
level onto the map and raising the banner («Стягивание») on it.

Four steps, all driven through xLua SafeDoString (docs/research/xlua-state.md) — and each one
waits for the game to actually be in the next state instead of sleeping a guessed amount:

  FIND    — use the game's own world-map search («лупа», the `UISearch` window), not a scan of
            whatever clones happen to be loaded on screen. Open `UISearch`, set the search level
            for the wanted kind (`Ctrl:SetCurNumBySearchType(type, level, 0)`), then press the
            magnifier (`Ctrl:OnSearchClick(type, 0)`). That sends the server the "find a monster
            of this level near me" request; when the server answers, the game flies the camera to
            the monster it produced and opens its `UIWorldPoint` popup by itself
            (`OnSearchEnd` → `GoToUtil.MoveToWorldMarchAndOpen`). We poll until that popup is up
            AND its monster data has arrived, then read `pointId/uuid/serverId`, the level, and
            the popup's single action button — `Ctrl:GetPointBtnEnumName(View.btnList[1])`.
            `RallyBoss` is the «Стягивание» button; anything else (e.g. `AttackMonster`) means
            the search returned a soloable monster, which cannot be rallied.

  PRESS   — press that button: `MarchUtil.OnClickStartMarch(MarchTargetType.RALLY_FOR_BOSS,
            pointId, uuid)`, exactly the two arguments the button's own handler passes. The
            popup stays OPEN for this — closing it first is what made the monster "hide" without
            anything being pressed.

  SQUAD   — the press opens the squad screen (`UIFormationSelectListV2`, or
            `UIFormationSelectListNew` when the game's `formation_v2_switch` is off), already
            carrying the target: `targetType = 7`, `targetPoint`, `targetUuid`, `targetServerId`
            and the rally wait `timeIndex`. Wait for that window, then pick the squad —
            `View:OnSelectClick(uuid)` (the tap, so the screen shows it) plus
            `Ctrl:SetSelectFormationUuid(uuid)` — and read `Ctrl.selectFormationUuid` back to
            confirm the pick landed before anything is sent.

  LAUNCH  — press the screen's launch button: `Ctrl:OnCheckTime(formationUuid, nil)`, the same
            entry its View uses, which runs the game's own pre-checks and then
            `OnCreateClick` → `MarchUtil.SendCreateMarchMessage(formationUuid, targetType,
            targetPoint, targetUuid, timeIndex, autoBackHome, NeedTakeArmy(), targetServerId,
            nil)`. The screen closes itself. The rally is confirmed the only way that counts: a
            new own march appears whose `teamUuid` is non-zero — i.e. a стяг led by us.

Proven live: a rally on a level-35 «Роковая Элита» went out this way (own rally marches 0 → 1,
the new march carrying `teamUuid == uuid + 1`, the leader's numbering) —
docs/research/rally-create.md.

Usage::

    python tools/rally_create.py --find --level N [--type monster|boss]   # search + report only
    python tools/rally_create.py --level N --squad M [--type monster|boss] [--server S]

`--squad` picks which squad raises the banner (its formation uuid, read live off the game, same
resolver as rally_join.py). `--type` picks the «лупа» tab the target is searched under (defaults
to the module constant). `--server` is only a fallback for the report; the target carries its own
server and the squad screen takes it from there.
"""
import argparse
import sys
import time

sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval
from tool_config import default_server
# The squad -> formation-uuid resolver is shared with the JOIN side; no second copy.
from rally_join import formation_by_squad

# The popup button that raises a rally. `UIWorldPointCtrl:GetPointBtnEnumName(btn)` names the
# popup's action button; a rally target shows exactly this one. A soloable monster shows
# `AttackMonster` instead, and no amount of pressing turns that into a rally.
RALLY_BTN = "RallyBoss"

# The squad screen the rally button opens. Which of the two the game uses is a config switch
# (`formation_v2_switch`, read in `UIUtil.OpenFormationSelectUI`), so both are accepted.
FORMATION_WINDOWS = ("UIFormationSelectListV2", "UIFormationSelectListNew")

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
# (`EL popup waiting`); once it flips to `UIWorldPoint` we read point/uuid/server, the monster's
# level and canAttack (the uuid arg is REQUIRED — docs/research/world-monsters.md Finding 8), and
# the name of the popup's action button, which is what decides whether this can be rallied at all.
_READ_POPUP = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  if not w then L("popup none") return end
  if w.Name ~= "UIWorldPoint" then L("popup waiting win=" .. tostring(w.Name)) return end
  local c = w.Ctrl
  local lvl, ca, btn = "?", "?", "?"
  pcall(function() local md = c:GetMonsterData(c.uuid) lvl = tostring(md.level) ca = tostring(md.canAttack) end)
  pcall(function() btn = tostring(c:GetPointBtnEnumName(w.View.btnList[1])) end)
  L("popup pid=" .. tostring(c.pointId) .. " uuid=" .. tostring(c.uuid)
    .. " server=" .. tostring(c.serverId) .. " level=" .. lvl .. " canAttack=" .. ca
    .. " btn=" .. btn)
end)
'''

# Press the popup's «Стягивание» button. Its own handler passes exactly these two arguments —
# `MarchUtil.OnClickStartMarch(MarchTargetType.RALLY_FOR_BOSS, point, uuid)` — and the game fills
# the rest (server, wait time, auto-return) on the squad screen it opens. The popup must still be
# the top window: pressing after it was closed is the bug this replaced.
_PRESS_RALLY = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  if not w or w.Name ~= "UIWorldPoint" then L("press-nopopup win=" .. tostring(w and w.Name)) return end
  local c = w.Ctrl
  local ok, err = pcall(function()
    MarchUtil.OnClickStartMarch(MarchTargetType.RALLY_FOR_BOSS, c.pointId, c.uuid)
  end)
  L("press ok=" .. tostring(ok) .. " err=" .. tostring(err))
end)
'''

# Is the squad screen up yet? Reports the target it carries, so a wrong one shows up in the log
# rather than being silently rallied.
_READ_PANEL = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  if not w then L("panel none") return end
  if w.Name ~= "UIFormationSelectListV2" and w.Name ~= "UIFormationSelectListNew" then
    L("panel waiting win=" .. tostring(w.Name)) return end
  local c = w.Ctrl
  L("panel win=" .. w.Name .. " targetType=" .. tostring(c.targetType)
    .. " point=" .. tostring(c.targetPoint) .. " uuid=" .. tostring(c.targetUuid)
    .. " server=" .. tostring(c.targetServerId) .. " timeIndex=" .. tostring(c.timeIndex)
    .. " sel=" .. tostring(c.selectFormationUuid))
end)
'''

# Pick the squad on the open screen and read the pick back. `View:OnSelectClick` is the tap (it
# repaints the cells and the cost), `Ctrl:SetSelectFormationUuid` is what the tap ultimately
# records; both are done so the screen and the send agree. Nothing is sent here — the launch is a
# separate step that only runs once `squad sel=` shows the wanted uuid.
_PICK_SQUAD = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  if not w or (w.Name ~= "UIFormationSelectListV2" and w.Name ~= "UIFormationSelectListNew") then
    L("squad nopanel win=" .. tostring(w and w.Name)) return end
  local c = w.Ctrl
  pcall(function() w.View:OnSelectClick(%(formation)s) end)
  pcall(function() c:SetSelectFormationUuid(%(formation)s) end)
  L("squad sel=" .. tostring(c.selectFormationUuid))
end)
'''

# Press the screen's launch button. `Ctrl:OnCheckTime(formationUuid, destroyTimeIndex)` is what
# its View calls: the game's own pre-checks (rally cap, wait-time warnings) and then
# `OnCreateClick` → `SendCreateMarchMessage`. The screen closes itself on success.
_LAUNCH = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  if not w or (w.Name ~= "UIFormationSelectListV2" and w.Name ~= "UIFormationSelectListNew") then
    L("launch nopanel win=" .. tostring(w and w.Name)) return end
  local c = w.Ctrl
  local ok, err = pcall(function() c:OnCheckTime(%(formation)s, nil) end)
  L("launch ok=" .. tostring(ok) .. " err=" .. tostring(err))
end)
'''

# How many of the player's own world marches are part of a rally (teamUuid ~= 0). A raised banner
# adds one; that increase is the confirmation, since a plain march count also moves for unrelated
# reasons and `IsHaveMarchInWorld` is already true whenever anything is out.
_OWN_RALLIES = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("EL "..tostring(s)) end
pcall(function()
  local wm = DataCenter.WorldMarchDataManager
  local om = wm:GetOwnerMarches()
  local n = 0
  if om then
    local e = om:GetEnumerator()
    while e:MoveNext() do
      local mo = e.Current.Value if mo == nil then mo = e.Current end
      local ok, team = pcall(function() return mo.teamUuid end)
      if ok and team ~= nil and tostring(team) ~= "0" and tostring(team) ~= "nil" then n = n + 1 end
    end
  end
  L("rallies n=" .. n)
end)
'''

# Close whatever is on top, keeping the HUD: the game's own CloseSelf, never DestroyAllWindow.
_CLOSE_TOP = (
    'pcall(function() local w = UIManager.Instance:GetStackTopWindow() '
    'if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() end end) '
    'CS.UnityEngine.Debug.LogError("EL closed")'
)


def _runner(ev):
    """A `run(chunk, marker, settle)` bound to this evaluator — the shape rally_join expects."""

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    return run


def own_rallies(run):
    """How many rallies the player currently has a march in (own marches with a teamUuid)."""
    line = _one(run(_OWN_RALLIES, "EL rallies", 1.0), "rallies n=")
    try:
        return int(line.split("n=")[1].split()[0])
    except (IndexError, ValueError):
        return -1


def _parse_popup(line):
    """Parse an `EL popup pid=.. uuid=.. server=.. level=.. canAttack=.. btn=..` line to a dict."""
    out = {}
    for key in ("pid", "uuid", "server", "level", "canAttack", "btn"):
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
            "btn": out.get("btn"),
        }
    except (TypeError, ValueError):
        return None


def find_target(ev, level, search_type=None, wait_s=12.0, keep_open=False):
    """Search the «лупа» for a monster of ``level`` and return its popup (dict), or ``None``.

    Drives the real world-map search: open `UISearch`, set the level, press the magnifier, then
    wait for the game to fly to the monster the server produced and open its `UIWorldPoint`
    popup. Returns ``{pid, uuid, server, level, canAttack, btn}`` for whatever came back, or
    ``None`` when the search fired and no monster of that level was returned within ``wait_s``
    seconds (or the search could not be fired at all).

    ``btn`` is the name of the popup's action button — ``RALLY_BTN`` means this target can be
    rallied. The caller decides; nothing is pressed here.

    With ``keep_open`` the popup is LEFT OPEN when a target was found, because the rally button
    lives on it — that is the whole point of the flow. On a miss (and always without
    ``keep_open``) whatever the search left on top is closed again, so the map is left as found.

    ``search_type`` picks the «лупа» tab (`boss` for the Fatal Elite, `monster` for ordinary
    field monsters); ``level`` is clamped into that tab's range (SEARCH_LEVEL_RANGE).
    """
    kind = search_kind(search_type)
    st = UISEARCH_TYPE[kind]
    level = clamp_level(level, kind)
    run = _runner(ev)

    run(_OPEN_SEARCH, "EL search-open", 1.6)
    fired = _one(run(_FIRE_SEARCH % {"type": st, "level": int(level)}, "EL", 1.8), "EL ")
    if "search-fired" not in fired:
        run(_CLOSE_TOP, "EL closed", 0.8)
        return None

    # The popup arrives after a server round-trip, and its monster data one beat after the window
    # itself — poll for BOTH (a `level=?` read means the window is up but still empty) rather than
    # sleeping a guessed amount and reading once.
    popup = ""
    for _ in range(max(1, int(wait_s))):
        popup = _one(run(_READ_POPUP, "EL", 1.0), "popup ")
        if ("pid=" in popup and "pid=nil" not in popup
                and "waiting" not in popup and "popup none" not in popup
                and "level=?" not in popup and "canAttack=?" not in popup):
            break
        time.sleep(0.9)

    if ("pid=" not in popup or "pid=nil" in popup
            or "waiting" in popup or "popup none" in popup):
        run(_CLOSE_TOP, "EL closed", 0.8)
        return None
    target = _parse_popup(popup)
    if target is None or not keep_open:
        run(_CLOSE_TOP, "EL closed", 0.8)
    return target


def raise_rally(ev, formation, wait_s=8.0):
    """With a rally target's popup open, press «Стягивание» and launch ``formation`` at it.

    Presses the popup's rally button, waits for the squad screen it opens, picks the squad and
    reads the pick back, then presses the screen's launch button. Returns ``(ok, reason)`` where
    ``reason`` is one of ``launched`` / ``no_panel`` (the button did not bring up the squad
    screen — a confirm dialog in the way, or the target went stale) / ``no_squad`` (the screen
    would not take that squad) / ``not_raised`` (everything was pressed and no rally came out).

    ``ok`` is decided by the game, not by the presses: the count of own rally marches must go up.
    """
    run = _runner(ev)
    before = own_rallies(run)

    run(_PRESS_RALLY, "EL press", 1.8)

    # The squad screen replaces the popup after the press — wait for it instead of assuming it.
    panel = ""
    for _ in range(max(1, int(wait_s))):
        panel = _one(run(_READ_PANEL, "EL", 1.0), "panel ")
        if "panel win=" in panel:
            break
        time.sleep(0.8)
    if "panel win=" not in panel:
        return False, "no_panel"

    picked = _one(run(_PICK_SQUAD % {"formation": formation}, "EL", 1.4), "squad ")
    if ("sel=" not in picked) or (str(formation) not in picked):
        run(_CLOSE_TOP, "EL closed", 0.8)
        return False, "no_squad"

    run(_LAUNCH % {"formation": formation}, "EL launch", 2.0)

    # The banner shows up as a new own march carrying a teamUuid; give the server a moment.
    for _ in range(4):
        time.sleep(1.2)
        after = own_rallies(run)
        if before >= 0 and after > before:
            return True, "launched"
    return False, "not_raised"


def create_on_level(ev, level, squad, server=None, search_type=None):
    """Search a rally target of ``level`` («лупа») and raise a rally on it with ``squad``.

    Returns a result dict ``{ok, reason, pid, uuid, server, level, formation}``. ``ok`` is True
    only when the game shows a new rally of ours afterwards. ``reason`` names the miss so a
    caller (the panel loop) can report it:

    * ``no_formation`` — the squad is not loaded (checked first, before anything is opened)
    * ``no_elite``     — the search returned nothing, or something without a «Стягивание» button
    * ``no_panel``     — the rally button did not bring up the squad screen
    * ``no_squad``     — the squad screen would not take that squad
    * ``not_raised``   — everything was pressed and no rally appeared

    ``search_type`` picks the «лупа» tab and with it the level range the search accepts
    (1–200 for both kinds); ``level`` is clamped into it.
    """
    run = _runner(ev)
    level = clamp_level(level, search_type)

    # Resolve the squad BEFORE searching: a squad that cannot be sent must not leave a monster
    # popup hanging open on the map.
    formation = formation_by_squad(run, squad)
    if not formation:
        return {"ok": False, "reason": "no_formation", "squad": squad, "level": level}

    target = find_target(ev, level, search_type, keep_open=True)
    if target is None:
        return {"ok": False, "reason": "no_elite", "level": level, "squad": squad}
    srv = target["server"] or (str(server) if server is not None else DEFAULT_SERVER)
    if target.get("btn") != RALLY_BTN:
        # A soloable monster (or whatever else the «лупа» happened to return) — not ralliable.
        run(_CLOSE_TOP, "EL closed", 0.8)
        return {"ok": False, "reason": "no_elite", "squad": squad, **target, "server": srv}

    ok, reason = raise_rally(ev, formation)
    return {"ok": ok, "reason": reason, "formation": formation, "squad": squad,
            **target, "server": srv}


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
            target = find_target(ev, level, args.type)
            if target is None:
                print("no %s of level %s returned by the search" % (args.type, level), flush=True)
            elif target.get("btn") != RALLY_BTN:
                print("found level=%s pid=%s uuid=%s server=%s with a «%s» button — it cannot be "
                      "rallied" % (target["level"], target["pid"], target["uuid"],
                                   target["server"], target.get("btn")), flush=True)
            else:
                print("rally target (%s) level=%s pid=%s uuid=%s server=%s"
                      % (args.type, target["level"], target["pid"], target["uuid"],
                         target["server"]), flush=True)
            return

        if args.level is None or args.squad is None:
            ap.error("--level and --squad are required (or use --find --level N)")
        res = create_on_level(ev, args.level, args.squad, args.server, args.type)
        if res["ok"]:
            print("RALLY RAISED level=%s squad=%s pid=%s server=%s"
                  % (res.get("level"), args.squad, res.get("pid"), res.get("server")), flush=True)
        elif res["reason"] == "no_elite":
            print("no ralliable %s of level %s found by the search"
                  % (args.type, clamp_level(args.level, args.type)), flush=True)
        elif res["reason"] == "no_formation":
            print("no squad %s found (nothing raised)" % args.squad, flush=True)
        elif res["reason"] == "no_panel":
            print("the «Стягивание» button did not open the squad screen (nothing raised)",
                  flush=True)
        elif res["reason"] == "no_squad":
            print("the squad screen would not take squad %s (nothing raised)" % args.squad,
                  flush=True)
        else:
            print("pressed, but no rally came out (see EL lines above)", flush=True)
    finally:
        ev.close()


if __name__ == "__main__":
    main()
