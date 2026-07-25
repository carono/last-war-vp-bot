r"""Open the city **left-panel** feature windows programmatically — no physical click.

Each button is opened either by a bare `UIManager.Instance:OpenWindow(UIWindowNames.X)`
(data-independent windows) or by a `GoToUtil.Goto*` call (the fetch+open flow, used for
the radar). All entries below were verified live: `IsWindowOpen` → true and the rendered
on-screen text matches. Full write-up: docs/research/ui-open.md § "Left panel buttons".

Driven through the warm Lua daemon (tools/lib/lua_client.get_evaluator()) — daemon-backed
when tools/lua_daemon.py is up, a fresh local LuaEval otherwise.

Left-column icons were identified by their Image sprite names on the UIMain HUD:
  city-build entrance  = sprite `zyf_chengjian_rukou_icon`   (科技/城建 queue)
  science entrance     = sprite `lyp_..._kejishu`            (tech-tree queue)
  trucks / trade       = sprite `lrb_chengjimaoyi_...`       (城际贸易 = inter-city trade)

    C:\Python312\python.exe tools\dev\ui_left_panel.py --list
    C:\Python312\python.exe tools\dev\ui_left_panel.py --open radar
    C:\Python312\python.exe tools\dev\ui_left_panel.py --open secret_missions
    C:\Python312\python.exe tools\dev\ui_left_panel.py --open trucks
    C:\Python312\python.exe tools\dev\ui_left_panel.py --open trucks --close   # …then close it
    C:\Python312\python.exe tools\dev\ui_left_panel.py --close-all             # back to city
"""
from __future__ import annotations
import argparse
import sys

sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval

# key -> (human label, Lua to run, window name to confirm via IsWindowOpen)
BUTTONS = {
    # satellite-dish icon — radar mission map (in-game "задания радара", costs stamina).
    # GoToUtil route (a bare OpenWindow of UIDetectEvent is not the reliable path).
    "radar": ("radar / recon mission map (UIDetectEvent)",
              "GoToUtil.GoRadarProbe()", "UIDetectEvent"),
    # jeep icon — Secret Command Post (in-game "Секретный командный пункт" / «Операция
    # Призрак»): ghost-recon secret missions; tabs individual / alliance / others.
    "secret_missions": ("secret missions / ghost recon (UIDispatchTaskMain)",
                        "UIManager.Instance:OpenWindow(UIWindowNames.UIDispatchTaskMain)",
                        "UIDispatchTaskMain"),
    # truck icon = sprite `lrb_chengjimaoyi` = 城际贸易 (inter-city trade): trade-post hub,
    # truck dispatch, rob/robbed log.
    "trucks": ("trucks / Trade Station hub (TradeStationCity)",
               "UIManager.Instance:OpenWindow(UIWindowNames.TradeStationCity)",
               "TradeStationCity"),
    "truck_dispatch": ("truck dispatch (UILWTruckSuperDeparture)",
                       "UIManager.Instance:OpenWindow(UIWindowNames.UILWTruckSuperDeparture)",
                       "UILWTruckSuperDeparture"),
    "truck_record": ("truck rob/robbed log (UILWTruckRecord)",
                     "UIManager.Instance:OpenWindow(UIWindowNames.UILWTruckRecord)",
                     "UILWTruckRecord"),
    # quest list — in-game "Задание": main + side quests
    "quests": ("quest list (UILWQuestList)",
               "UIManager.Instance:OpenWindow(UIWindowNames.UILWQuestList)",
               "UILWQuestList"),
}


def _grep(lines, needle):
    return " ".join(x for x in lines if needle in x)


def open_button(ev, key):
    label, lua, win = BUTTONS[key]
    ev.run('pcall(function() %s end) CS.UnityEngine.Debug.LogError("ACT ran")' % lua,
           marker="ACT", settle=2.5)
    q = ('local o=false local c=false '
         'pcall(function() o=UIManager.Instance:IsWindowOpen("%s") end) '
         'pcall(function() c=UIManager.Instance:IsPanelLoadingComplete("%s") end) '
         'CS.UnityEngine.Debug.LogError("ACT %s open="..tostring(o).." loaded="..tostring(c))'
         % (win, win, win))
    print(label)
    print("  " + _grep(ev.run(q, marker="ACT", settle=0.8), "ACT %s" % win).strip())


def close_window(ev, win):
    ev.run('local w=UIManager.Instance:GetWindow("%s") '
           'pcall(function() w.Ctrl:CloseSelf() end) '
           'CS.UnityEngine.Debug.LogError("ACT close")' % win, marker="ACT", settle=1.2)


def close_all(ev):
    ev.run('pcall(function() GoToUtil.CloseAllWindows() end) '
           'CS.UnityEngine.Debug.LogError("ACT closed cnt="..tostring(UIManager.Instance:GetStackWindowCount()))',
           marker="ACT", settle=1.2)


def main():
    ap = argparse.ArgumentParser(description="Open city left-panel feature windows.")
    ap.add_argument("--open", choices=list(BUTTONS), help="which button to open")
    ap.add_argument("--close", action="store_true", help="close the window after opening")
    ap.add_argument("--close-all", action="store_true", help="close every window (back to city)")
    ap.add_argument("--list", action="store_true", help="list known left-panel buttons")
    args = ap.parse_args()

    if args.list:
        for k, (label, lua, win) in BUTTONS.items():
            print(f"{k:16s} {label}\n{'':16s}  {lua}")
        return 0

    ev = get_evaluator()
    if args.close_all:
        close_all(ev)
        return 0
    if not args.open:
        ap.error("nothing to do: pass --open <button>, --list, or --close-all")
    open_button(ev, args.open)
    if args.close:
        close_window(ev, BUTTONS[args.open][2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
