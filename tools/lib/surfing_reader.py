r"""Street Run («Уличный забег» / Surfing) obstacle reader — the state layer read from
**Lua/Unity scene**, replacing the vision detector (tools/street_run_bot.py).

During a run the game holds every obstacle as a monster object in
``SurfingMonsterManager.showList`` and the avatar as ``SurfingLogic.player``. Each
monster object exposes, as plain Lua fields (dumped live, server 935, 2026-07-29):

    .x        lane centre — one of {32, 36, 40} (centre lane = 36, lanes 4 units apart)
    .dataZ    world Z (distance along the track; grows forward)
    .bornId   obstacle template id (e.g. 203001 = barrel «mutong»)
    .unitType 4 = solid collider obstacle (dodge) · 1 = score/coin · 3 = energy · 2 = box
    .gameObject.name  the prefab, e.g. "A_Monster_surfing_mutong(Clone)" (definitive type)

The player advances at a constant ``SurfingLogic:GetMoveSpeed()`` = 30 units/s, so
distance-ahead ``dz = obstacle.dataZ - player.z`` converts to time-to-impact ``dz/30``.
This gives the dodger perfect, deterministic look-ahead (obstacles are readable ~150
units / ~5 s ahead) instead of a 15 fps pixel guess.

The manager/logic instances are captured by wrapping ``SurfingLogic.OnStart`` and
``SurfingMonsterManager.Init`` (they stash ``self`` into ``_G.__SR_LOGIC`` / ``__SR_MM``);
so ``install()`` must run BEFORE the run starts. A scene-enumeration fallback (walk
Transforms by prefab name) keeps ``read()`` working even without the capture.

Lane numbering used everywhere here: **0 = left (x≈32), 1 = centre (x≈36), 2 = right
(x≈40)**.
"""
from __future__ import annotations

# Lane geometry (live-measured). Centre lane x=36, neighbours ±4.
LANE_X = (32.0, 36.0, 40.0)
MOVE_SPEED = 30.0  # units/s forward (SurfingLogic:GetMoveSpeed()); refreshed live in read()


def lane_of(x: float) -> int:
    """Map a world x to lane 0/1/2 (nearest of 32/36/40)."""
    return min(range(3), key=lambda i: abs(x - LANE_X[i]))


# --- obstacle classification by prefab name (definitive) --------------------
# jumpable=True → a low ground obstacle the avatar can hop (↑); tall barriers/containers
# are fatal to jump into (proven live) and must be dodged by a lane change.
def classify(name: str, unit_type: int, height: float = 0.0) -> dict:
    n = (name or "").lower()
    # collectibles / buffs — not collision hazards
    if unit_type == 1 or "score" in n or "_gold" in n:
        return {"kind": "coin", "obstacle": False, "jumpable": False}
    if unit_type == 3 or "energy" in n:
        return {"kind": "energy", "obstacle": False, "jumpable": False}
    if unit_type == 2 or "box" in n:
        return {"kind": "box", "obstacle": False, "jumpable": False}
    if "buff" in n or "magnet" in n or "jetpack" in n or "shield" in n or "morph" in n:
        return {"kind": "buff", "obstacle": False, "jumpable": False}
    # solid obstacles (unit_type == 4)
    if "mutong" in n or "barrel" in n:
        return {"kind": "barrel", "obstacle": True, "jumpable": True}
    if "dizhalan" in n or "low_zhalan" in n or "low_object" in n:
        return {"kind": "low_fence", "obstacle": True, "jumpable": True}
    if "high_zhalan" in n or "gaozhalan" in n or "zhalan" in n:
        return {"kind": "fence", "obstacle": True, "jumpable": False}
    if "chexiang" in n or "truck" in n or "vehicle" in n or "che" in n:
        return {"kind": "truck", "obstacle": True, "jumpable": False}
    if "pitfall" in n or "saw" in n or "trap" in n:
        return {"kind": "trap", "obstacle": True, "jumpable": False}
    # unknown solid: treat as a tall obstacle (safe default — dodge, don't jump)
    return {"kind": "unknown", "obstacle": unit_type == 4, "jumpable": height and height < 1.2}


# --- Lua chunks -------------------------------------------------------------
_INSTALL = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRD "..tostring(s)) end
local okL,SL=pcall(require,"DataCenter.LWBattle.Logic.Surfing.SurfingLogic")
if okL and type(SL)=="table" and not SL.__srd_hooked then
  local o=SL.OnStart SL.OnStart=function(s,...) _G.__SR_LOGIC=s return o(s,...) end
  SL.__srd_hooked=true
end
local okM,MM=pcall(require,"Scene.LWBattle.Surfing.Monster.SurfingMonsterManager")
if okM and type(MM)=="table" and not MM.__srd_hooked then
  local o=MM.Init MM.Init=function(s,...) _G.__SR_MM=s return o(s,...) end
  MM.__srd_hooked=true
end
L("install ok")
"""

# One-round-trip read: player pos + speed, then one M-line per monster in showList.
_READ = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRD "..tostring(s)) end
local lg,mm=_G.__SR_LOGIC,_G.__SR_MM
if not (lg and mm) then L("noinst") return end
local ok,p=pcall(function() return lg.player:GetPosition() end)
if not ok or not p then L("noplayer") return end
local sp=30 pcall(function() sp=lg:GetMoveSpeed() end)
L(string.format("P %.3f %.3f %.3f", p.x, p.z, sp))
local n=0
for k,mon in pairs(mm.showList) do
  if type(mon)=="table" then
    local x=mon.x or 0
    local z=mon.dataZ or (mon.curWorldPos and mon.curWorldPos[3]) or 0
    local u=mon.unitType or 4
    local nm="?" pcall(function() nm=mon.gameObject.name end)
    L(string.format("M %s %s %s %s", tostring(u), tostring(x), tostring(z), tostring(nm)))
    n=n+1
    if n>=60 then break end
  end
end
L("END "..n)
"""


class SurfReader:
    """Wraps a warm Lua evaluator; ``install()`` once, then ``read()`` each tick."""

    def __init__(self, ev):
        self.ev = ev

    def install(self):
        self.ev.run(_INSTALL, marker="SRD ", settle=0.6)

    def read(self) -> dict:
        """Return {'ok':bool,'player':(x,z),'lane':int,'speed':float,
        'obstacles':[{lane,x,z,dz,tti,unit_type,name,kind,obstacle,jumpable}],'reason':str}.

        ``obstacles`` holds ALL showList entries ahead-or-near; filter by ``obstacle``
        for collision hazards and by ``dz`` for look-ahead depth.
        """
        lines = self.ev.run(_READ, marker="SRD ", settle=0.06)
        px = pz = None
        speed = MOVE_SPEED
        obst = []
        for ln in lines:
            body = ln.split("SRD ", 1)[-1].strip() if "SRD " in ln else ""
            if body.startswith("noinst"):
                return {"ok": False, "reason": "no-instance", "obstacles": []}
            if body.startswith("noplayer"):
                return {"ok": False, "reason": "no-player", "obstacles": []}
            if body.startswith("P "):
                parts = body.split()
                px, pz, speed = float(parts[1]), float(parts[2]), float(parts[3])
            elif body.startswith("M "):
                parts = body.split(None, 4)
                if len(parts) < 5:
                    continue
                u = int(float(parts[1])); x = float(parts[2]); z = float(parts[3]); name = parts[4]
                obst.append({"unit_type": u, "x": x, "z": z, "name": name})
        if px is None:
            return {"ok": False, "reason": "no-read", "obstacles": []}
        out = []
        for o in obst:
            cls = classify(o["name"], o["unit_type"])
            dz = o["z"] - pz
            out.append({
                "lane": lane_of(o["x"]), "x": o["x"], "z": o["z"], "dz": dz,
                "tti": (dz / speed) if speed else None,
                "unit_type": o["unit_type"], "name": o["name"], **cls,
            })
        out.sort(key=lambda o: o["dz"])
        return {"ok": True, "player": (px, pz), "lane": lane_of(px),
                "speed": speed, "obstacles": out, "reason": "ok"}


# --- decision layer (replaces vision decide()) ------------------------------
# Look-ahead window: only obstacles within this many Z-units ahead threaten soon.
LOOKAHEAD_Z = 60.0
# Danger window: an obstacle nearer than this (in Z) in the player's lane forces action.
DANGER_Z = 46.0
# Jump window: hop a low/barrel obstacle only once it is this close (else the arc lands
# before it). ~20 units ≈ 0.66 s at speed 30.
JUMP_Z = 22.0
# A lane is "blocked" if any obstacle sits in it within [ -CLEAR_BACK , LOOKAHEAD_Z ].
CLEAR_BACK = 6.0


def lane_threats(state: dict):
    """Return (per_lane_nearest_dz, per_lane_jumpable_only). per_lane_nearest_dz[i] is the
    smallest forward dz of a solid obstacle in lane i within the look-ahead window (or None
    if the lane is clear). per_lane_jumpable_only[i] is True when that nearest threat is a
    low/hoppable obstacle (a barrel), so a jump clears it."""
    near = [None, None, None]
    jumpable = [True, True, True]
    for o in state.get("obstacles", []):
        if not o["obstacle"]:
            continue
        if -CLEAR_BACK <= o["dz"] <= LOOKAHEAD_Z:
            i = o["lane"]
            if near[i] is None or o["dz"] < near[i]:
                near[i] = o["dz"]
                jumpable[i] = o["jumpable"]
    return near, jumpable


def decide(state: dict) -> str | None:
    """Deterministic dodge from exact obstacle geometry. Returns 'left'|'right'|'up'|None.

    Priority (the staggered opening — barrel dead-ahead with a truck in the only side
    lane — punishes a naive "switch to the farthest-threat lane"):
      1. Nothing imminent in the player's lane → hold.
      2. A genuinely CLEAR adjacent lane (no obstacle in the look-ahead) → step into it.
      3. Dead-ahead obstacle is a LOW/hoppable barrel and close enough → jump it (a jump
         into a tall barrier/truck is fatal, so this is height-gated by ``jumpable``).
      4. Otherwise pick the least-bad reachable lane (farthest nearest-threat), if it beats
         staying; else hold and (if the near obstacle is hoppable) jump as a last resort.
    """
    if not state.get("ok"):
        return None
    pl = state["lane"]
    near, jumpable = lane_threats(state)
    own = near[pl]
    if own is None or own > DANGER_Z:
        return None  # nothing imminent in this lane

    cand = [(0, "left"), (2, "right")] if pl == 1 else ([(1, "right")] if pl == 0 else [(1, "left")])

    def safety(i):
        return float("inf") if near[i] is None else near[i]

    # 2. a truly clear side lane wins outright (choose the one with the most room behind it)
    clear = [(i, k) for (i, k) in cand if near[i] is None]
    if clear:
        return clear[0][1]

    # 3. own obstacle is a LOW/hoppable barrel: never trade it for a non-clear lane (that
    #    lane may hold a tall truck/fence — fatal). Wait and hop it inside the jump window.
    if jumpable[pl]:
        return "up" if own <= JUMP_Z else None

    # 4. own obstacle is TALL (truck/fence) and no clear lane: a lane change is forced —
    #    take the least-bad reachable lane (farthest nearest-threat). Staying is certain death.
    best = max(cand, key=lambda c: safety(c[0]))
    return best[1]
