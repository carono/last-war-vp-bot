r"""Open the in-game Shop (UICommonShop), switch tabs, and close it — no physical click.

The generic Shop («Магазин») is `UIWindowNames.UICommonShop`. It opens cold via
`UIManager.Instance:OpenWindow`, carries the full tab bar, and closes via `Ctrl:CloseSelf`.
Tabs are keyed by a *shop-type* number (NOT an index); switching is done by driving the
real Unity toggle (`togglesTb[type].unity_uitoggle.isOn = true`), which fires the registered
onValueChanged and updates `curShopType` synchronously. Full write-up: docs/research/ui-open.md.

Observed types: 1=diamonds, 2=VIP, 7=alliance(honor), 8, 10, 100(star), 150, 200.

    C:\Python312\python.exe tools\dev\ui_shop.py                 # open, show tab list, curShopType
    C:\Python312\python.exe tools\dev\ui_shop.py --tab 7         # open + switch to alliance shop
    C:\Python312\python.exe tools\dev\ui_shop.py --tab 7 --tab 100
    C:\Python312\python.exe tools\dev\ui_shop.py --tab 7 --close # …then close
    C:\Python312\python.exe tools\dev\ui_shop.py --close-only    # just close it
"""
from __future__ import annotations
import argparse
import sys
sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval

WIN = "UICommonShop"


def _grep(lines, needle):
    return " ".join(x for x in lines if needle in x)


def open_shop(ev):
    ev.run(
        'pcall(function() UIManager.Instance:OpenWindow(UIWindowNames.%s) end) '
        'CS.UnityEngine.Debug.LogError("ACT opened")' % WIN,
        marker="ACT", settle=2.5)
    q = ('local o=false local c=false pcall(function() o=UIManager.Instance:IsWindowOpen("%s") end) '
         'pcall(function() c=UIManager.Instance:IsPanelLoadingComplete("%s") end) '
         'local w=UIManager.Instance:GetWindow("%s") local tabs="" '
         'pcall(function() for i,t in pairs(w.View.shopTabTypeList) do tabs=tabs..tostring(t).." " end end) '
         'CS.UnityEngine.Debug.LogError("ACT shop open="..tostring(o).." loaded="..tostring(c)'
         '.." cur="..tostring(w and w.View and w.View.curShopType).." tabs="..tabs)'
         % (WIN, WIN, WIN))
    print(_grep(ev.run(q, marker="ACT shop", settle=0.8), "ACT shop"))


def switch_tab(ev, tab):
    # Setting isOn fires onValueChanged, which updates curShopType on the NEXT frame —
    # so read it in a follow-up call, not the same chunk.
    ev.run('local w=UIManager.Instance:GetWindow("%s") local v=w and w.View '
           'local ok=pcall(function() v.togglesTb[%d].unity_uitoggle.isOn=true end) '
           'CS.UnityEngine.Debug.LogError("ACT set tab=%d ok="..tostring(ok))'
           % (WIN, tab, tab), marker="ACT set", settle=1.6)
    q = ('local w=UIManager.Instance:GetWindow("%s") local v=w and w.View '
         'CS.UnityEngine.Debug.LogError("ACT tab=%d cur="..tostring(v and v.curShopType))' % (WIN, tab))
    print(_grep(ev.run(q, marker="ACT tab", settle=0.6), "ACT tab"))


def close_shop(ev):
    ev.run('local w=UIManager.Instance:GetWindow("%s") '
           'pcall(function() w.Ctrl:CloseSelf() end) '
           'CS.UnityEngine.Debug.LogError("ACT close")' % WIN, marker="ACT", settle=1.2)
    q = ('local o=false pcall(function() o=UIManager.Instance:IsWindowOpen("%s") end) '
         'CS.UnityEngine.Debug.LogError("ACT closed open="..tostring(o))' % WIN)
    print(_grep(ev.run(q, marker="ACT closed", settle=0.6), "ACT closed"))


def main():
    ap = argparse.ArgumentParser(description="Open/switch/close the in-game Shop (UICommonShop).")
    ap.add_argument("--tab", type=int, action="append", default=[],
                    help="shop-type to switch to (repeatable): 1 2 7 8 10 100 150 200")
    ap.add_argument("--close", action="store_true", help="close the shop after switching")
    ap.add_argument("--close-only", action="store_true", help="only close an already-open shop")
    args = ap.parse_args()

    ev = get_evaluator()
    if args.close_only:
        close_shop(ev)
        return 0
    open_shop(ev)
    for t in args.tab:
        switch_tab(ev, t)
    if args.close:
        close_shop(ev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
