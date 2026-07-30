r"""URGENT (#1116): a treasure IS on the map — find its pid/uuid via the map-tap popup.

Same shape as tools/dev/gather.py: find the tile's clone through its
TouchObjectEventTrigger, OnClick() to open UIWorldPoint, read pointId/uuid/serverId off
the popup Ctrl, close ONLY the popup (never DestroyAllWindow).
"""
from __future__ import annotations
import sys
import time

sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # noqa: E402

# What a detect-event tile looks like in the scene (seen live 2026-07-29):
#   Detect_event_icon / Detect_event_quality_icon  — the floating marker
#   WorldHelperDetectInfo(Clone)                   — the info bubble
NAMES = ("Detect", "Treasure", "detect")

TRIGGERS = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("HNT "..tostring(s)) end
local ok, err = pcall(function()
  local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
  local n = 0
  for i = 0, arr.Length - 1 do
    local mb = arr[i]
    if mb and mb:GetType().Name == 'TouchObjectEventTrigger' then
      local okgo, go = pcall(function() return mb.gameObject end)
      if okgo and go then
        -- walk up, printing the chain, so we can see what kinds of tiles are in view
        local p, path = go, go.name
        local depth = 0
        while p and p.transform.parent and depth < 6 do
          p = p.transform.parent.gameObject
          path = p.name .. "/" .. path
          depth = depth + 1
        end
        n = n + 1
        if n <= 60 then L("trig " .. path) end
      end
    end
  end
  L("trig_count=" .. n)
end)
L("done ok=" .. tostring(ok) .. " err=" .. tostring(err))
'''

CLICK = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("HNT "..tostring(s)) end
_G.TRIG = nil _G.CN = nil
local ok, err = pcall(function()
  local want = "%s"
  local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
  for i = 0, arr.Length - 1 do
    local mb = arr[i]
    if mb and mb:GetType().Name == 'TouchObjectEventTrigger' then
      local okgo, go = pcall(function() return mb.gameObject end)
      if okgo and go then
        local p, depth = go, 0
        while p and not string.find(p.name, want) and p.transform.parent and depth < 6 do
          p = p.transform.parent.gameObject; depth = depth + 1
        end
        if p and string.find(p.name, want) then _G.TRIG = mb _G.CN = p.name break end
      end
    end
  end
  if _G.TRIG then
    pcall(function() _G.TRIG:OnClick() end)
    L("clicked " .. tostring(_G.CN))
  else
    L("NO_TILE matching " .. want)
  end
end)
L("done ok=" .. tostring(ok) .. " err=" .. tostring(err))
'''

POPUP = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("HNT "..tostring(s)) end
local ok, err = pcall(function()
  local w = UIManager.Instance:GetStackTopWindow()
  local c = w and w.Ctrl
  L("top=" .. tostring(w and w.Name))
  if not c then return end
  for _, k in ipairs({"pointId", "uuid", "serverId", "pointType", "type", "data", "detail"}) do
    local v = rawget(c, k)
    if v ~= nil and type(v) ~= "table" then L("ctrl " .. k .. "=" .. tostring(v)) end
  end
  for k, v in pairs(c) do
    if type(v) ~= "function" and type(v) ~= "table" then L("all " .. tostring(k) .. "=" .. tostring(v)) end
  end
  -- one level into the data tables
  for _, k in ipairs({"data", "detail", "pointData", "treasureData"}) do
    local t = rawget(c, k)
    if type(t) == "table" then
      for kk, vv in pairs(t) do
        if type(vv) ~= "function" and type(vv) ~= "table" then
          L("data " .. k .. "." .. tostring(kk) .. "=" .. tostring(vv))
        end
      end
    end
  end
end)
L("done ok=" .. tostring(ok) .. " err=" .. tostring(err))
'''

CLOSE = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("HNT "..tostring(s)) end
local w = UIManager.Instance:GetStackTopWindow()
local c = w and w.Ctrl
if c and c.CloseSelf then pcall(function() c:CloseSelf() end) end
L("closed stack=" .. tostring(UIManager.Instance:GetStackWindowCount()))
'''


def main():
    ev = get_evaluator()
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else "trig"
        if mode == "trig":
            for line in ev.run(TRIGGERS, marker="HNT", settle=2.5):
                print(line.split("HNT ", 1)[-1], flush=True)
            return 0
        want = sys.argv[2] if len(sys.argv) > 2 else "Detect"
        for line in ev.run(CLICK % want, marker="HNT", settle=2.0):
            print(line.split("HNT ", 1)[-1], flush=True)
        time.sleep(2.0)
        for line in ev.run(POPUP, marker="HNT", settle=2.0):
            print(line.split("HNT ", 1)[-1], flush=True)
        if "--keep" not in sys.argv:
            for line in ev.run(CLOSE, marker="HNT", settle=1.5):
                print(line.split("HNT ", 1)[-1], flush=True)
    finally:
        ev.close()


if __name__ == "__main__":
    sys.exit(main())
