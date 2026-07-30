r"""URGENT (#1116): name the object that carries the visible treasure marker."""
from __future__ import annotations
import sys

sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # noqa: E402

CHAIN = r'''
local L = function(s) CS.UnityEngine.Debug.LogError("HNT "..tostring(s)) end
local ok, err = pcall(function()
  local objs = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.GameObject))
  local seen = {}
  for i = 0, objs.Length - 1 do
    local go = objs[i]
    local nm = go.name
    if nm == "Detect_event_icon" or nm == "Detect_event_quality_icon"
       or string.find(nm, "WorldPointObject_") or string.find(nm, "detectObj") then
      local p, path, depth = go, nm, 0
      while p and p.transform.parent and depth < 8 do
        p = p.transform.parent.gameObject
        path = p.name .. "/" .. path
        depth = depth + 1
      end
      if not seen[path] then
        seen[path] = true
        local pos = go.transform.position
        L("chain " .. path .. " @" .. string.format("%.0f,%.0f", pos.x, pos.z))
      end
    end
  end
end)
L("done ok=" .. tostring(ok) .. " err=" .. tostring(err))
'''


def main():
    ev = get_evaluator()
    try:
        for line in ev.run(CHAIN, marker="HNT", settle=2.5):
            print(line.split("HNT ", 1)[-1], flush=True)
    finally:
        ev.close()


if __name__ == "__main__":
    sys.exit(main())
