r"""Named game "buttons" — the friendly vocabulary the DSL `TAP` primitive speaks.

This is where the ugly engine names live so the recipes don't have to. A recipe says
`TAP alliance` / `TAP donate_1000 x30`; the real `UIManager.Instance:OpenWindow(...)`
and `OnResDonateClick(...)` calls are hidden here, one entry per button. Adding a new
button for a recipe author = add one entry below (name -> the Lua it fires).

Each button is a `Button`:
  * ``lua``   — the raw Lua chunk that "presses" it (runs in the game VM, verbatim).
  * ``wait``  — seconds to pause AFTER pressing, so the next step sees the result.
                Crucial for anything that waits on the server (a donation only lowers
                its counter after the reply) — the pause is baked in here, not in the
                recipe, which is why `TAP donate_1000 x30` is safe and never freezes.
  * ``label`` — a human phrase for the log.
  * ``batch_lua`` — optional: the same press as an `n`-times loop, run in ONE call
                into the game VM. Where it exists, a repeat costs one round trip
                instead of one per press (see the field's comment below).
  * ``verify_lua`` — optional: an expression whose CHANGE after the press proves the
                game did something. Without it a `TAP` reports success from «the Lua
                did not raise»; with it, `wait` becomes a deadline on the re-read
                instead of a sleep, and a press that changed nothing fails (#1282).

The catalogue is deliberately small and readable. See docs/dsl.md ("TAP") and, for the
alliance-science calls, docs/research/alliance-tech-donate.md.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lua_actions as _lua_actions  # noqa: E402


@dataclass(frozen=True)
class Button:
    lua: str
    wait: float
    label: str
    # Optional: a Lua expression returning "how many times this button can still do
    # something right now" (e.g. remaining donations). Given, the recipe can say
    # `TAP <button> xall` to press exactly that many times instead of a fixed count —
    # the real count is substituted at run time, and the loop re-reads it so throttled
    # / dropped presses are retried until the count actually reaches zero.
    count_lua: str | None = None
    # Safety cap on `xall` iterations, so a miscounting expression can't spin forever.
    max_taps: int = 60
    # Optional: the same press written to fire `n` times inside ONE game-VM call, where
    # `n` is a Lua local the caller prepends. A call into the VM costs ~0.15 s and the
    # loop inside it is free, so a button with a batch form empties a 30-press quota in
    # one call instead of thirty — the difference between half a minute and a second.
    # The chunk must report how many presses it really fired as `ACT fired=<k>`.
    #
    # Only for a press that is a plain fire-and-forget send: nothing inside the batch
    # can wait for the server, because the counters it would wait on cannot change
    # before the frame ends (that is the client freeze in
    # docs/research/alliance-tech-donate.md). The caller still reads `count_lua` before
    # the batch and again after it, so the real count remains the stop condition.
    batch_lua: str | None = None
    # Optional: a Lua *expression* whose CHANGE after the press is the proof that the
    # game did something (#1282). Without one, a plain `TAP` reports success from «the
    # Lua did not raise» — which says the call ran, not that anything happened, and is
    # the mechanism behind every «the panel confidently reported the wrong thing»: the
    # client told it was being restarted and was not (#1259), «развести клиенты» that
    # changed nothing (#1263), a live socket vouching for a dead game link (#1266).
    #
    # With one, the press is followed by a poll of this expression until its value
    # MOVES, and `wait` stops being a sleep and becomes the DEADLINE on that poll — so
    # a verified button is usually faster as well as honest (a `TAP` whose whole cost
    # was the button's own 1.0 s pause, #1230). A press whose value has not moved by
    # the deadline FAILS the recipe rather than logging `tap=ok`.
    #
    # It must be an expression, cheap, and stable between presses: a clock or a frame
    # counter «moves» every time and proves nothing. The obvious one for a button that
    # has it is `count_lua` — the number the press is supposed to spend.
    verify_lua: str | None = None
    # Optional: the marker lines this button's Lua prints that the RUN is entitled to
    # hear — «what the server answered», as opposed to the interpreter's own telemetry
    # (#1416). Named as prefixes of the text after `ACT `, e.g. `("steal_done",)`.
    #
    # WHY IT HAS TO BE DECLARED. Everything a chunk logs comes back to `_run_lua`, and
    # the interpreter reads out the two or three fields it needs (`tap=`, `fired=`,
    # `gate left=`) and DROPS the rest — so a verdict a button was written to report
    # reached nobody. The robbery is the case that proves it: `secret_task_queue_pop`
    # has printed `ACT steal_done uuid=<u> how=<taken|gone|unanswered>` since #1272, and
    # both readers of it — the «Автолут ★» watcher and the tab's own press — match that
    # line in the event stream, which never carried it. So a tile the server called
    # «задание уже взято» was never taken off the list and was chosen again on the next
    # tick, for as long as it stayed on the map.
    #
    # A LIST RATHER THAN «RELAY EVERYTHING»: `steal_secret_task` prints `steal_sent` on
    # every one of up to sixty presses in a spam, and a run that repeated all of them
    # would bury its own verdict. What is relayed is what the button DECLARES worth
    # hearing.
    relay: tuple = ()


# The recommended-science object is fetched fresh inside each press (it is cheap and
# avoids stashing engine objects across daemon calls).
_REC = "DataCenter.AllianceScienceDataManager:GetCurRecommendScience()"

BUTTONS: dict[str, Button] = {
    # --- Alliance -> Alliance Tech -> donate to the priority tech -------------
    "alliance": Button(
        lua="UIManager.Instance:OpenWindow(UIWindowNames.UILWAlMain)",
        wait=1.2, label="Alliance panel",
    ),
    "alliance_tech": Button(
        lua="UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)",
        wait=1.5, label="Alliance Tech",
    ),
    "recommended_tech": Button(
        # Open the server-recommended (priority) tech's detail = the donate panel.
        lua=("local rec = %s "
             "UIManager.Instance:GetStackTopWindow().Ctrl:OnScienceInfoClick(rec, nil)"
             % _REC),
        wait=1.5, label="recommended tech",
    ),
    "donate_1000": Button(
        # One "Donate 1000" press — headless: the controller's donate method touches no
        # `self`, so it is called on the module with no window open (proven live, see
        # lua_actions.alliance_donate_batch). `batch_lua` is the same press written as
        # an n-times loop, which is what makes a whole quota one call: the in-game
        # long-press repeats the click, and this repeats it inside a single frame.
        lua=_lua_actions.alliance_donate_press(),
        batch_lua=_lua_actions.alliance_donate_batch(),
        # Long enough for the server's replies to land, so the confirming re-read after
        # a batch sees the new count rather than the one it started from.
        wait=0.5, label="Donate 1000",
        count_lua=_lua_actions.alliance_donate_rest(),
        max_taps=40,
    ),
    # --- Alliance -> help every member with an open help request -------------
    "help_ally_all": Button(
        # The in-game "Помочь всем" (Help All) button — one al.help.all message answers
        # every pending request at once, and no UI window has to be open. The engine
        # side, and why `AllianceHelpDataManager:OnHelpAll` is NOT it, is written up in
        # lua_actions.alliance_help_all(). Helping is unlimited; only the daily HELP
        # POINTS are capped (GetAllianceHelpSliderData -> {todayHelpPoint,
        # maxHelpCount=1000}), and hitting that cap does NOT stop you from helping.
        lua=_lua_actions.alliance_help_all(),
        wait=1.0, label="Help All (alliance)",
        # How many alliancemates are still waiting — the same gate the press applies, so
        # `xall` presses once, re-reads to confirm the server cleared the list, and mops
        # up anything that arrived in the gap instead of guessing a fixed count.
        # It is the LARGER of the client's two readings (the help list and the red-point
        # count): a request that arrived while the bot was running is only ever in the
        # second one, so the list alone made this recipe press zero times — see the note
        # above alliance_help_pending() and docs/research/alliance-help.md.
        count_lua=_lua_actions.alliance_help_waiting(),
        max_taps=10,
    ),
    # --- Base -> recruit a waiting survivor ("Собрать выжившего") -------------
    "recruit_survivor": Button(
        # A survivor knocking at the base is a CityVisitorManager queue entry with
        # eventType == VisitorType.RECRUITMENT (3); accepting sends one
        # visitor.operate {uid, operate=1} — the agree button of UIWorkerDetailRecruit,
        # captured whole in trace 20260729_145441. No window need be open: the send
        # reads the uid straight off the queued visitor. The engine side and why the
        # queue wrapper is {data, model} is written up in lua_actions.visitor_recruit_*
        # and docs/research/city-visitor-recruit.md.
        lua=_lua_actions.visitor_recruit_survivor(),
        wait=1.0, label="Recruit survivor",
        # How many recruitable survivors are still queued — the same gate the send
        # applies, so `xall` recruits them one message at a time and re-reads to let
        # the server's push.user.visitor.change drain the queue instead of guessing.
        count_lua=_lua_actions.visitor_recruit_pending(),
        max_taps=10,
    ),
    # --- Base -> collect a gift-bearing survivor ("Собрать подарки выжившего") -
    "collect_visitor_gifts": Button(
        # A survivor bringing gifts is a CityVisitorManager queue entry with
        # eventType == VisitorType.GIFT (2); collecting sends the same one-shot
        # visitor.operate {uid, operate=1} as a recruit — captured whole in trace
        # 20260729_151712, after which the client flew a coin-box reward and closed
        # UICityVisitor. Only the visitor kind differs from recruit_survivor; the
        # engine side is written up in lua_actions.visitor_gift_* and
        # docs/research/city-visitor-recruit.md.
        lua=_lua_actions.visitor_gift_collect(),
        wait=1.0, label="Collect visitor gifts",
        # How many gift-bearing survivors are still queued — the same gate the send
        # applies, so `xall` collects them one message at a time and re-reads to let
        # the server's push.user.visitor.change drain the queue instead of guessing.
        count_lua=_lua_actions.visitor_gift_pending(),
        max_taps=10,
    ),
    # --- Alliance -> gifts: open the section, then claim each tab -------------
    # The "Подарки альянса" window has two "collect all" buttons — ordinary gifts
    # (type 1) and premium/privilege gifts (type 2) — handled by the same click
    # handler UILWAllianceGiftCtrl:OnGetAllBtnClick(type) (nparams=2 = self+type).
    # On the wire each press is alliance.reward.allreceive {type}; opening the
    # window sends alliance.reward.list. Unlike a headless data call these are the
    # real button clicks, so the window has to be open first (they read the loaded
    # list). Live-confirmed: opening the window and firing OnGetAllBtnClick(2)
    # collected the premium gifts in-game. See docs/research/alliance-gift-collection.md.
    "alliance_gifts": Button(
        lua="UIManager.Instance:OpenWindow(UIWindowNames.UILWAllianceGift)",
        wait=1.3, label="Alliance gifts panel",
    ),
    "collect_gifts_ordinary": Button(
        # "Забрать всё" on the ordinary-gifts tab (type 1). No-op if that tab is
        # already empty. Guarded so it only fires with the gift window on top.
        lua=("local w=UIManager.Instance:GetStackTopWindow() "
             "if w and tostring(w.Name)=='UILWAllianceGift' then w.Ctrl:OnGetAllBtnClick(1) end"),
        wait=0.8, label="Collect ordinary gifts",
    ),
    "collect_gifts_premium": Button(
        # "Забрать всё" on the premium/privilege tab (type 2). Same guard.
        lua=("local w=UIManager.Instance:GetStackTopWindow() "
             "if w and tostring(w.Name)=='UILWAllianceGift' then w.Ctrl:OnGetAllBtnClick(2) end"),
        wait=0.8, label="Collect premium gifts",
    ),
    "dismiss_reward_popup": Button(
        # After a collect the game raises a "you received …" reward-list modal
        # (UIGiftPackageRewardGet, confirmed live). It sits on a SEPARATE UI layer,
        # NOT on the main window stack — GetStackTopWindow() still returns the gift
        # window, which is why a top-of-stack close never sees it. So scan every
        # window name, and for each reward-show popup that is currently open
        # (name carries 'Reward' or 'GetGift') close it via GetWindow -> CloseSelf.
        # Safe: the gift window ('UILWAllianceGift') and the HUD ('UIMain') match
        # neither token, so they are never touched; a no-op when no popup is up.
        lua=("local mgr=UIManager.Instance "
             "for _,name in pairs(UIWindowNames) do local s=tostring(name) "
             "if s:find('Reward') or s:find('GetGift') then "
             "local ok,open=pcall(function() return mgr:IsWindowOpen(name) end) "
             "if ok and open then local w=mgr:GetWindow(name) "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end "
             "end end end"),
        wait=0.5, label="dismiss reward popup",
    ),
    # --- base -> collect every ready resource building -----------------------
    "collect_base_resources": Button(
        # "Собрать все ресурсы с базы" — the base's own "Collect All" in one press.
        # The base's resource generators are production lines tracked by
        # DataCenter.ProductLineManager; harvesting one is SendCollect(uuid), and
        # the game's Collect-All button simply fires that for every ready building.
        # So this loops GetAllBuildUuids() and calls SendCollect on the ready ones.
        # READINESS IS MANDATORY: SendCollect on a building with nothing banked is
        # NOT a no-op — the server answers `building.production.collect` with
        # errorCode 602026 "In production, please be patient." and the client pops
        # that toast, one per building (confirmed on the wire, task #1087).
        # GetBuildingCurrStorage(uuid) is the banked amount and the server bills
        # exactly floor() of it (stor 30155.12 -> resNum 30155, stor 210.87 ->
        # resNum 210, both captured live), so `>= 1` is precisely the server's own
        # accept condition — and it also skips the sub-unit window right after a
        # collect, where storage is positive but floors to 0.
        # Verified live through the warm daemon: sweeping all 38 production
        # buildings dropped their pending storage from ~29k to ~6k (16 ready -> 0).
        # No world positions, itemId grouping or 205-building scan — the earlier
        # BuildingUtils.CityCollectionByItemId approach is retired.
        # See docs/research/resource-collection.md.
        lua=(
            "local plm=DataCenter.ProductLineManager "
            "for _,u in pairs(plm:GetAllBuildUuids() or {}) do "
            "local ok,stor=pcall(function() return plm:GetBuildingCurrStorage(u) end) "
            "if ok and (stor or 0)>=1 then pcall(function() plm:SendCollect(u) end) end end"
        ),
        wait=1.5, label="Collect base resources",
    ),
    # --- base -> collect every supply truck that has arrived ------------------
    "collect_trucks": Button(
        # "Собрать грузовики". A supply truck surfaces on the base as a build bubble:
        # BuildBubbleType.TruckTravelling while en route, TruckReward / TruckReady
        # once it has arrived. Tapping the ready bubble collects its goods, so this
        # fires OnClick on every TruckReward/TruckReady bubble — the literal
        # reproduction of the "Сбор грузовика ресурсов" trace. Like help_ally_all it
        # clears all pending ones in a single press (no window needs to be open).
        # See docs/research/resource-collection.md.
        lua=(
            "local m=DataCenter.BuildBubbleManager local BT=_G.BuildBubbleType "
            "for _,v in pairs(m.allBuildBubble or {}) do local ty=v.param and v.param.buildBubbleType "
            "if ty==BT.TruckReward or ty==BT.TruckReady then pcall(function() v:OnClick() end) end end"
        ),
        wait=1.2, label="Collect ready trucks",
    ),
    # --- base -> the resource truck's own "collect" press ----------------------
    # «Сбор ресурсов с грузовика». Recording 20260730_130004 caught the wire: the
    # tap, the collect and the modal-close are all one command with a different
    # `action` int, so the press needs no window and no bubble lookup.
    "truck_reward_refresh": Button(
        lua=_lua_actions.truck_reward_refresh(),
        wait=0.6, label="Read the truck's load",
    ),
    "collect_truck_reward": Button(
        # One press takes the whole banked pile, so never `xall` this one.
        lua=_lua_actions.truck_reward_collect(),
        wait=1.0, label="Collect the resource truck",
    ),
    "dismiss_truck_menu": Button(
        # After the collect, the truck's own menu is left open on the window stack,
        # with the congratulation reward modal (closed by `dismiss_reward_popup`) on a
        # layer above it. Close the top-of-stack window unless it is the HUD (`UIMain`):
        # once the modal is gone that is the truck menu. Same guarded GetStackTopWindow
        # -> CloseSelf shape as `collect_premium_gifts`, so it is a no-op with nothing
        # open and never touches the HUD. The base truck's menu window name was not in
        # the (SFS-only) trace behind this feature, which is why this is a top-of-stack
        # close rather than a by-name one — tighten it to the name once it is read live.
        lua=("local w=UIManager.Instance:GetStackTopWindow() "
             "if w and tostring(w.Name)~='UIMain' and w.Ctrl and w.Ctrl.CloseSelf then "
             "pcall(function() w.Ctrl:CloseSelf() end) end"),
        wait=0.5, label="Close the truck menu",
    ),
    # --- profession ("mastery") skills: fire the ones that need no target -----
    # «Навыки профессии» — the active skills of the profession the account picked.
    # Each is a once-a-day-ish charge (cooldown 1410-4290 min) that hands over
    # resources, speed-ups, a survivor or an instant build/research step, so leaving
    # them unpressed is pure lost income.
    #
    # One press = one skill, always the first one that is off cooldown; `xall` walks
    # the whole ready set. The skill is chosen inside the press rather than named
    # here, because which skills exist depends on the profession (Инженер / Военный
    # лидер) and on how far its tree is levelled — a button per id would only fit one
    # account. For pinning a routine to a single named skill there is
    # lua_actions.apply_occupation_skill(id).
    #
    # Only skills whose use-position is `SkillView` are fired: those need no target.
    # The `Building` / `Field` ones (Совместное исследование, Осадное знамя …) want a
    # world point and are deliberately left alone. See
    # docs/research/occupation-skills.md.
    "use_profession_skill": Button(
        lua=_lua_actions.apply_next_occupation_skill(),
        # Generous on purpose. The cooldown is set by the SERVER's reply, and the
        # observed round trip for use.desert.talent.skill ran up to ~8 s (the reply
        # carries the whole reward list). Pressing again before it lands would fire
        # the same skill twice — the re-fire guard in apply_next_occupation_skill() is the
        # real safety net, this pause is what keeps `xall` from leaning on it.
        wait=4.0, label="Use profession skill",
        count_lua=_lua_actions.occupation_skills_ready_count(),
        # Thirteen active nodes on a maxed tree, and only about half are no-target.
        max_taps=10,
    ),
    "profession_skills_panel": Button(
        # The «Профессия» window itself. Not needed to fire anything — the press is
        # headless — but it is how a human checks what the bot just did.
        lua="UIManager.Instance:OpenWindow(UIWindowNames.LWUIMastery)",
        wait=1.5, label="Profession panel",
    ),
    "dismiss_skill_result": Button(
        # A successful use raises its own result modal — UIMasterySkillUseResultShow
        # for most skills, UIBuyOneGetOneFree for the resource ones (seen live in
        # trace 20260729_010052), UIGetVirus for Cultivate Virus. They are separate
        # windows from the generic reward popup, so `dismiss_reward_popup` does not
        # match them. No-op when nothing is up.
        lua=("local mgr=UIManager.Instance "
             "for _,n in ipairs({UIWindowNames.UIMasterySkillUseResultShow, "
             "UIWindowNames.UIBuyOneGetOneFree, UIWindowNames.UIGetVirus}) do "
             "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
             "if ok and open then local w=mgr:GetWindow(n) "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end "
             "end end"),
        wait=0.5, label="dismiss skill-result popup",
    ),
    # --- world -> rob another player's secret task ---------------------------
    # «Кража секретки». A finished hero-dispatch task on someone else's tile can
    # be robbed three times before its loot slots fill up; the account gets five
    # robberies a day (`GetDispatchSetting("steal_count")`), and an unspent one is
    # simply lost at the daily reset. One press is one `hero.dispatch.steal
    # {uuid, targetServer}` — no marker tap, no popup, no camera move.
    #
    # `TAP` takes no arguments, so the targets are parked in the game VM first
    # (`tools/steal_secret_task.py` fills the queue from a map scan, from
    # coordinates or from bare uuids) and this button robs them one per press.
    # See lua_actions.steal_next_secret_task() and docs/research/secret-task-steal.md.
    "steal_secret_task": Button(
        lua=_lua_actions.steal_next_secret_task(),
        # AS FAST AS THE CHANNEL ALLOWS (#1272). A raidable star is taken in the first
        # instant it exists, so this is a spam loop rather than a press: `xall` re-reads
        # `count_lua` and presses again while the SERVER has not confirmed, and the pause
        # is what keeps a round from starting before the last one is off the wire.
        #
        # 0.05 s and not 0: one round trip through the warm daemon is ~80-135 ms (#1232),
        # so the loop is paced by the call itself and this is a floor, not a throttle —
        # about seven or eight presses a second. It used to be 2.0 s, which is a whole
        # race lost between two presses.
        wait=0.05, label="Rob a secret task",
        # 1 while the head is worth pressing again — see `secret_task_steals_pending`.
        count_lua=_lua_actions.secret_task_steals_pending(),
        # The cap is the width of the spam, not a number of targets: at ~0.15 s a round
        # that is about nine seconds of pressing at one tile, which covers the couple of
        # seconds before it matures and a good spell after.
        max_taps=60,
    ),
    "drop_steal_target": Button(
        # Move on: drop the head of the queue and re-arm the confirmation mark on the
        # next one. Between targets, never before a send — the head has to survive its
        # own press so the press can be repeated (`secret_task_queue_pop`).
        lua=_lua_actions.secret_task_queue_pop(),
        wait=0.05, label="Drop the current steal target",
        # THE VERDICT, OUT LOUD (#1416). This is where the server's answer about the
        # target being dropped is decided — taken, gone, or unanswered — and both
        # readers of it live outside the game: `panel/tabs/secret_tasks/autoloot.py`
        # takes a «gone» tile off the list, and the tab's own press does the same.
        # Until the line was declared here it was printed into the daemon's log and
        # dropped by the interpreter, so neither ever saw one.
        relay=("steal_done",),
    ),
    "dismiss_steal_reward": Button(
        # A successful robbery raises `UIDispatchTaskReward` — the loot list plus the
        # emoji strip for leaving the victim a message. Its own window, so neither
        # `dismiss_reward_popup` nor a top-of-stack close reliably matches it. No-op
        # when nothing is up.
        lua=("local mgr=UIManager.Instance local n=UIWindowNames.UIDispatchTaskReward "
             "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
             "if ok and open then local w=mgr:GetWindow(n) "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end end"),
        wait=0.5, label="dismiss steal-reward popup",
    ),
    # --- alliance -> help a mate's finished secret task -----------------------
    # A THIRD daily budget on this tab and a THIRD command (#1272): `help_ally_all`
    # answers building requests and is unlimited, `steal_secret_task` robs strangers,
    # and this HELPS an alliancemate's finished hero dispatch — `hero.dispatch.assist`,
    # five a day, and what the daily plan calls «помочь выполнить 5 секретных заданий
    # ранга UR или Звезда». No queue to fill: the targets are the client's own
    # `allianceTask` table, so the press chooses for itself out of the rule parked
    # beside it. See docs/research/secret-task-assist.md.
    "assist_secret_task": Button(
        lua=_lua_actions.assist_next_secret_task(),
        # The counter only moves when the reply lands, and a press that helped nothing
        # (the list had gone stale) is answered with a tip rather than a budget change.
        wait=2.0, label="Help a secret task (alliance)",
        # min(tasks the rule matches, helps left today).
        count_lua=_lua_actions.secret_task_assists_pending(),
        max_taps=10,
    ),
    "scan_secret_task_stars": Button(
        # One walk over the alliance list, parked where the recipe's `READ_LUA`s can
        # read it (#1292). Not a press at all — it changes nothing in the game and
        # sends nothing — but the recipe needs six answers to ONE walk, and a `TAP` is
        # how the DSL runs a chunk it then asks questions of.
        lua=_lua_actions.secret_task_assist_scan(),
        wait=0.4, label="Scan the alliance list for stars",
    ),
    "refresh_alliance_secret_tasks": Button(
        # `hero.dispatch.alliance.list`, fire and forget. NOT optional before a help:
        # the local copy keeps tasks somebody else has already helped with, and every
        # one of those costs a refusal instead of a help (docs/research/…-assist.md).
        lua=_lua_actions.secret_task_assist_refresh(),
        wait=2.0, label="Re-read the alliance's secret tasks",
    ),
    # --- the star sprint: the last seconds of a star's countdown (#1294) ------
    # A ripe star lives under two minutes — live, the day's only one was gone before a
    # five-minute poll ever saw it ready. The three buttons below are the robbery's
    # answer to the same race, aimed at a MOMENT rather than at a tile: the client
    # already knows the star's `completionTime`, so the panel schedules a wake-up for it
    # and these press through the instant it arrives.
    "arm_assist_sprint": Button(
        lua=_lua_actions.secret_task_assist_sprint_arm(),
        wait=0.2, label="Arm the star sprint",
    ),
    "assist_secret_task_sprint": Button(
        lua=_lua_actions.secret_task_assist_sprint_press(),
        # AS FAST AS THE CHANNEL ALLOWS, exactly like `steal_secret_task` — one round
        # trip through the warm daemon is 80-135 ms, so this floor is the call's own
        # pace and not a throttle. Pressing before the star matures costs nothing: the
        # reply's error branch raises a tip and never touches `todayAssistNum`.
        wait=0.05, label="Help the armed star (sprint)",
        count_lua=_lua_actions.secret_task_assist_sprint_pending(),
        # The cap is the WIDTH of the spam. At ~0.15 s a round this is about eighteen
        # seconds of pressing, which covers a lead of a few seconds and a good spell
        # after — and the armed window stops it sooner whenever the recipe says so.
        max_taps=120,
    ),
    "finish_assist_sprint": Button(
        lua=_lua_actions.secret_task_assist_sprint_verdict(),
        wait=0.1, label="Close the star sprint",
    ),
    # --- world -> rob a ghost-recon squad («Операция Призрак») ----------------
    # A DIFFERENT feature from `steal_secret_task` above: that one robs a hero
    # dispatch («секретка», `hero.dispatch.steal`), this one robs the weekly
    # co-op event's squads (`ghost.recon.steal`). Separate commands, separate
    # daily budgets (5 each), separate queues — mixing them up would send the
    # wrong command at the right uuid. See docs/research/ghost-recon-steal.md.
    #
    # Targets are parked in the VM first (tools/ghost_recon_steal.py), because
    # `TAP` takes no arguments; one press robs one squad and drops it.
    "steal_ghost_recon": Button(
        lua=_lua_actions.steal_next_ghost_recon(),
        # The budget only moves when the reply lands, and that reply carries the
        # whole reward list. The queue pop is the safety net; this pause is what
        # keeps `xall` from leaning on it.
        wait=2.0, label="Rob a ghost-recon squad",
        # min(queued, robberies left today), and 0 while the event is closed — so
        # `xall` is a no-op six days a week instead of an error.
        count_lua=_lua_actions.ghost_recon_steals_pending(),
        max_taps=10,
    ),
    "dismiss_ghost_recon_reward": Button(
        # A successful robbery raises the event's own loot window
        # (UIGhostreconReward; the box variant is UIGhostreconGetBoxReward).
        # Separate windows from the dispatch one, so `dismiss_steal_reward` does
        # not match them. No-op when nothing is up.
        lua=("local mgr=UIManager.Instance "
             "for _,n in ipairs({UIWindowNames.UIGhostreconReward, "
             "UIWindowNames.UIGhostreconGetBoxReward}) do "
             "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
             "if ok and open then local w=mgr:GetWindow(n) "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end "
             "end end"),
        wait=0.5, label="dismiss ghost-recon reward popup",
    ),
    # --- world -> a map treasure («сокровище на карте») -----------------------
    # Two one-thing buttons over the SAME parked queue (DataCenter.__lw_treasure_queue):
    #   dig_treasure   — pop the head and send a squad to dig it (still being dug)
    #                    MarchTargetType.DETECT_TREASURE / CROSS_DETECT_TREASURE
    #   claim_treasure — pop the head and claim the reward (already dug)
    #                    detect.event.claim.treasure {uuid, targetServer}
    # The recipe (work_treasure.md) reads the head's state and presses the right one; the
    # dig-vs-dug split is the point's operator-uid field (docs/research/world-treasures.md).
    #
    # Targets are parked by a finder — the chat "new treasure" detector (coming later) or a
    # map scan — because `TAP` takes no arguments, the same hand-off as ghost recon.
    # UNPROVEN: no treasure was live during the RE, so neither send has been fired
    # end-to-end. `count_lua` is the queue length so each is `xall`-able and a clean no-op
    # when the queue is empty (both pop, so xall drains it).
    "dig_treasure": Button(
        lua=_lua_actions.dig_head_treasure(),
        wait=2.0, label="Send a squad to dig a treasure",
        count_lua=_lua_actions.treasure_queue_len(),
        max_taps=10,
    ),
    "claim_treasure": Button(
        lua=_lua_actions.claim_head_treasure(),
        wait=2.0, label="Claim a dug treasure",
        count_lua=_lua_actions.treasure_queue_len(),
        max_taps=10,
    ),
    "dismiss_treasure_reward": Button(
        # A successful claim raises UIGiftPackageRewardGet (captured in the trace). Its own
        # window, so the generic closers do not match it. No-op when nothing is up.
        lua=("local mgr=UIManager.Instance local n=UIWindowNames.UIGiftPackageRewardGet "
             "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
             "if ok and open then local w=mgr:GetWindow(n) "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end end"),
        wait=0.5, label="dismiss treasure-reward popup",
    ),
    # --- world -> the treasure watcher (the debug feed, #1277) ---------------
    # Two presses that record nothing in the game and send nothing to the server: they
    # hook (and unhook) the client's own two network doors so every treasure message it
    # sends or receives is kept in a ring buffer until somebody drains it. The whole
    # reasoning is in lua_actions («The watcher»); the short version is that a chest is
    # out for minutes and nobody can start a sniffer in time.
    #
    # `treasure_watch_on` reads DataCenter.__lw_treasure_watch_wide, which the recipe
    # parks first — a `TAP` takes no arguments, the same hand-off the steal queue uses.
    # Pressing it again re-arms with the new flag and does NOT wrap the wrappers.
    #
    # NOT AT THE SAME TIME AS THE TRACER: `lua_trace` wraps these two doors as well, and
    # whichever restores last wins. Record with one of them.
    "treasure_watch_on": Button(
        lua=_lua_actions.treasure_watch_install(),
        wait=0.3, label="Start watching treasure messages",
    ),
    "treasure_watch_off": Button(
        lua=_lua_actions.treasure_watch_stop(),
        wait=0.3, label="Stop watching treasure messages",
    ),
    # --- world -> the treasure errand that runs itself (#1296) ----------------
    # The same hook, used to ACT rather than to record. `treasure_auto_arm` switches the
    # harvest on — every chest announced in alliance chat becomes a target in a queue that
    # lives in the game VM — and `treasure_auto_step` works the whole queue one step: the
    # nearest free squad marches onto the nearest chest, and a chest the alliance has
    # already dug is claimed. One press, because a chest is a race (the reasoning is in
    # lua_actions, «The auto errand»).
    #
    # The squads the arm is allowed to spend are parked by the recipe first —
    # `DataCenter.__lw_treasure_auto.squads`, the same hand-off the rally's join uses,
    # because a `TAP` takes no arguments.
    #
    # AND THE ARM NOW STARTS A CLOCK AS WELL AS AN EAR (#1318). Hearing a chest early is
    # worth nothing if the gift is taken ten seconds after the dig ends, and ten seconds is
    # what a panel poll costs at best. So the arm also parks the claim half in the game
    # (`A.tick`) and starts the game's own timer over it: the dig's deadline is read off our
    # own march and the claim leaves in the frame it passes. The panel's press still runs
    # the same function, so nothing depends on the timer being alive.
    "treasure_auto_arm": Button(
        lua=(_lua_actions.treasure_watch_install() + " "
             + _lua_actions.treasure_auto_arm_parked() + " "
             + _lua_actions.treasure_reaper_start()),
        wait=0.3, label="Listen for treasures and work them",
    ),
    "treasure_auto_off": Button(
        lua=(_lua_actions.treasure_auto_disarm() + " "
             + _lua_actions.treasure_reaper_stop()),
        wait=0.3, label="Stop working treasures by itself",
    ),
    # What the watch is doing, and the number the acceptance criterion is read off: how
    # long the last chest waited between becoming takeable and its first claim leaving.
    # ONE named chest into the same queue — what a row of «Командный пункт» parks before it
    # plays `actions/take_treasure.md`. Its uuid and tile travel on the VM
    # (`DataCenter.__lw_treasure_one`), because a `TAP` carries no arguments.
    "treasure_queue_one": Button(
        lua=_lua_actions.treasure_queue_one_parked(),
        wait=0.2, label="Queue one named treasure",
    ),
    "treasure_reaper_state": Button(
        lua=('CS.UnityEngine.Debug.LogError("ACT treasure_reaper " .. (%s))'
             % _lua_actions.treasure_reaper_state()),
        wait=0.2, label="What the treasure watch is doing",
    ),
    "treasure_auto_step": Button(
        lua=_lua_actions.treasure_auto_step(),
        wait=0.6, label="March on / claim every queued treasure",
    ),
    # --- world -> the SECOND door: reading what is already on screen (#1296) ---
    # «Убирай обход, он не нужен, нужно просто слушать всегда окружение, т.к. 99% кладов
    # находятся в улье, а не на карте.» The lap that used to live here was measured and
    # was not worth its camera: two full laps found 19 and 21 chests and OURS WAS ZERO
    # both times — a chest of one's own alliance is placed in the hive, not out on the
    # open map. What was worth keeping is the reading, which was never the expensive half.
    #
    #   treasure_look        — the chests in the box the camera is ALREADY sitting in.
    #                          No jump, no zoom change, nothing sent. Rides an ordinary
    #                          tick of the errand and is silent in the city.
    #   treasure_scan_harvest — what was seen becomes targets of the errand above
    #
    # The three below it are the LAP, kept for a census somebody asks for by hand
    # (`actions/scan_treasures.md`) and pressed by nothing on a schedule.
    "treasure_look": Button(
        lua=_lua_actions.treasure_look_around(),
        wait=0.3, label="Read the treasures already in view",
    ),
    "treasure_scan_due": Button(
        lua=_lua_actions.treasure_scan_ask(),
        wait=0.2, label="Is a treasure lap of the map due?",
    ),
    "treasure_scan_start": Button(
        lua=_lua_actions.treasure_scan_sweep(),
        # The lap is walked by the GAME's own timer, so this press returns as soon as the
        # waypoints are handed over. What it takes to finish is `span` in the reading —
        # the recipe waits that out itself.
        wait=0.4, label="Sweep the map for treasures",
    ),
    "treasure_scan_harvest": Button(
        lua=_lua_actions.treasure_scan_harvest(),
        wait=0.3, label="Queue the treasures the map sweep found",
    ),
    # --- Hospital: heal wounded soldiers ("Лечение юнитов") ------------------
    # Two presses, the two halves of the in-game routine (docs/research/hospital-heal.md):
    #   heal_all       — send every wounded soldier type for treatment in one
    #                    `hospital.cure`, built from DataCenter.HospitalManager
    #   collect_healed — take the healed ones back when the timer ends, which is the
    #                    manager's own CheckSendFinish -> `queue.finish`
    # Both run headless: the wounded list and the queue state are read off the game
    # state, no hospital window is opened. Asking the alliance to speed the heal up is
    # NOT a third press — starting a heal registers it for help by itself.
    #
    # `count_lua` makes each one `xall`-able and a clean no-op: 0 when nothing is hurt,
    # 0 while the heal is still running. One heal press already covers every type, so a
    # plain `TAP heal_all` is the usual call.
    #
    # PROVEN LIVE (2026-07-29): heal_all sent 681 wounded for treatment in one press, and
    # collect_healed brought a finished batch back. A heal is refused (errorCode 130069)
    # while the hospital queue is busy — including when finished soldiers are still waiting
    # to be collected — so run collect_healed first, which is the order the recipe uses.
    "heal_all": Button(
        lua=_lua_actions.hospital_heal_all(),
        wait=1.2, label="Heal all wounded soldiers",
        count_lua=_lua_actions.hospital_wounded_count(),
        max_taps=1,
    ),
    # Ask the alliance to speed up whatever is working — the third press of the healing
    # routine, and useful on its own for builds and research. `count_lua` counts queues
    # with no request standing, so `TAP call_help xall` is a clean no-op when every one
    # has already been asked for.
    "call_help": Button(
        lua=_lua_actions.alliance_call_help_all(),
        wait=1.0, label="Ask the alliance to speed up the queues",
        count_lua=_lua_actions.queues_needing_help(),
        max_taps=1,
    ),
    "collect_healed": Button(
        lua=_lua_actions.hospital_collect(),
        wait=1.0, label="Collect the healed soldiers",
        count_lua=_lua_actions.hospital_healed_ready(),
        max_taps=1,
    ),
    # --- alliance rally: join the live ones, one squad each -------------------
    # «Присоединиться к ралли». One press sends the next parked squad to the next
    # rally the player is not already in, so `TAP join_rally xall` spends the
    # squads one per rally — squads 2 and 3 land on two DIFFERENT rallies.
    #
    # Which squads may be spent is parked first (`DataCenter.__lw_rally_squads`,
    # see lua_actions.rally_squads_set) because `TAP` takes no arguments; with
    # nothing parked the press falls back to squads 1/2/3. The recipe that reads
    # the `squads` argument and parks it is actions/join_rally.md.
    #
    # Headless whenever any squad is already loaded. If every formation is cold
    # (soldiers=0) the send would silently no-op, so the press warms them the way
    # the game does — which opens the dispatch panel — and closes it again with
    # GoToUtil.CloseAllWindows(). See docs/research/rally-join.md.
    "join_rally": Button(
        lua=_lua_actions.join_next_rally(),
        # The joining march only appears once the server answers (the send itself
        # is scheduled 0.5 s out), and `rally_join.py` waits ~3 s before it can
        # confirm one. The press marks the rally as taken by itself, so this pause
        # is not what keeps two squads apart — it is what lets the count re-read
        # see reality.
        wait=3.0, label="Join a rally",
        count_lua=_lua_actions.rally_joins_pending(),
        # Three squads is the whole army; the cap is only a backstop.
        max_taps=5,
    ),
    # --- alliance rally: JOIN one --------------------------------------------
    # THE WHOLE JOIN IN ONE PRESS (#1281): sieve the squads, pair each with a different
    # banner and send them all, with no reading in front of it and no window behind it.
    # What it left behind and why is `DataCenter.__lw_rally_report`, which the recipe
    # reads back and logs. It is what `actions/join_rally.md` plays; everything below it
    # is the older, step-at-a-time shape, kept for the one thing a headless send cannot
    # do (see `fill_empty_squads`).
    "rally_join_all": Button(
        lua=_lua_actions.rally_join_all(),
        # The marches appear when the SERVER answers and the recipe polls for that.
        # Sleeping here holds the game's lease in front of the next banner for nothing.
        wait=0.1, label="join every rally that can be joined",
    ),
    # `rally_join_send` is the join for ONE armed rally, and it opens nothing: the squad
    # screen adds nothing to the message that the squad does not already carry
    # (docs/research/rally-join.md).
    #
    # THE SCREEN IS GONE (#1285). Three presses used to sit here — open the squad screen,
    # pick the squad, launch — as the one thing a headless send could not do: fill a
    # squad standing empty. It never worked: the game's own launch threw from inside its
    # own code (`SceneUtils.lua:258`), so the case had no route at all. It does not need
    # one. A squad reading `totalSoldierNum = 0` is a squad the client has not ASKED
    # about, and one message (`fill_empty_squads` below) fetches the army the server
    # already had — in 0.37 s, with nothing on screen.
    "rally_join_arm": Button(
        # Not a press in the game: pick the rally and the squad and park them, so every
        # step below reads one answer rather than racing the map for its own.
        lua=_lua_actions.rally_join_arm(),
        wait=0.05, label="arm the join (rally + squad)",
    ),
    "rally_join_send": Button(
        # The join with no screen at all: the same message the screen's launch ends up
        # sending, aimed at the tile the joiners gather on. Tried first; the screens
        # below are the fallback when the map does not move (actions/join_rally.md).
        lua=_lua_actions.rally_join_send(),
        # The march appears when the server answers and the recipe POLLS for that.
        # Sleeping here only holds the lease — and the next rally behind it.
        wait=0.1, label="join the rally with no screen",
    ),
    # --- the squads themselves: fetch the army the client has not asked about ---
    "fill_empty_squads": Button(
        lua=_lua_actions.squads_fill_empty(),
        # The soldiers appear when the SERVER answers, and `actions/fill_empty_squads.md`
        # polls for that in quarter seconds. Just long enough for the request to leave.
        wait=0.1, label="ask the game for the army of every empty squad",
    ),
    # --- alliance rally: RAISE one («Стягивание») -----------------------------
    # The create side, four presses in the order the game itself walks them:
    #
    #     rally_search_window -> rally_search -> rally_banner -> rally_squad -> rally_launch
    #
    # Each press needs the window the previous one opened to be there, so the polls
    # between them live in the recipe (actions/create_rally.md), not in the Lua —
    # a chunk that waited for the server would freeze the client.
    #
    # WHAT is rallied (squad, level, elite-or-monster) is parked in
    # `DataCenter.__lw_rally_create` first, because `TAP` carries no arguments; the
    # recipe that reads the scenario's arguments and parks them is
    # actions/create_rally.md. Engine side: lua_actions + docs/research/rally-create.md.
    "rally_arm": Button(
        # Not a press in the game — the run's setup step, and it comes first because
        # both of its readings have to be taken before any window is opened: the
        # squad's formation (a slot that does not exist must stop the recipe, not
        # leave a target popup open on the map) and the rally count the raise is
        # measured against.
        lua=_lua_actions.rally_create_arm(),
        wait=0.2, label="arm the rally run (squad + starting count)",
    ),
    "rally_search_window": Button(
        lua=_lua_actions.rally_search_open(),
        wait=1.6, label="the map search («лупа»)",
    ),
    "rally_search": Button(
        # Type the parked level into the parked tab and press the magnifier. The
        # server answers by flying the camera to a target and opening its popup, so
        # the pause here is just the send — the recipe polls for the popup.
        lua=_lua_actions.rally_search_fire(),
        wait=1.8, label="search for a target of that level",
    ),
    "rally_banner": Button(
        lua=_lua_actions.rally_banner_press(),
        wait=1.8, label="«Стягивание» on the target",
    ),
    "rally_squad": Button(
        lua=_lua_actions.rally_squad_pick(),
        wait=1.0, label="pick the squad on the rally screen",
    ),
    "rally_launch": Button(
        # The launch runs the game's own pre-checks and sends; the screen closes
        # itself. The banner only shows up as an own march once the server answers,
        # which the recipe waits for by re-reading the rally count.
        lua=_lua_actions.rally_launch(),
        wait=2.0, label="launch the rally",
    ),
    # --- «Кодовое имя»: attack the event's world boss -------------------------
    # Three, and none of them opens a window:
    #
    #     codename_fetch -> codename_arm -> codename_send
    #
    # A person walks five screens for this — the event window, its «Атака» (which only
    # flies the camera), the boss on the map, the popup's «Атака», the squad screen —
    # and every one of those ends at a single send. #1259 recorded that send while the
    # player made one attack by hand, and it needs none of the walk: the boss is
    # addressed by uuid, so there is no tile to wait for and no camera to move.
    #
    # WHICH boss and WHICH squad are parked in `DataCenter.__lw_codename` by the arm,
    # because `TAP` carries no arguments. The recipe is actions/attack_codename_boss.md
    # and the reverse-engineering is docs/research/codename-event.md.
    "codename_fetch": Button(
        # Not a press either: the ASK. Every reading of this event is worthless until
        # the server's reply has landed, because the manager starts empty and the
        # client only fills it when it opens the event's own screen. Both the reading
        # and the attack send this first (#1259).
        lua=_lua_actions.codename_fetch(),
        wait=1.2, label="ask the server for the event's boss and stage",
    ),
    "codename_arm": Button(
        # Not a press in the game: the run's setup. It picks the boss out of the
        # event's list, picks the first squad standing in the base, and notes how many
        # attacks have gone out already so the last step can measure rather than assume.
        lua=_lua_actions.codename_arm(),
        wait=0.2, label="arm the boss attack (target + free squad)",
    ),
    "codename_send": Button(
        # The attack itself, in ONE call and with no window: the very send the squad
        # screen makes when a person taps «Марш», with the arguments read off the wire
        # while the player made one attack by hand (#1259).
        lua=_lua_actions.codename_send(),
        # The server answers with the refreshed count a beat later, which is what the
        # recipe then measures — so the pause is part of the proof, not politeness.
        wait=2.0, label="send the squad at the boss",
    ),
    # --- base decorations: the handbook's upgrade press -----------------------
    # One press upgrades the first decoration that is ready: the button finds the
    # group itself, so nothing has to be picked or parked beforehand. Headless — no
    # building tapped, no handbook opened.
    #
    # `count_lua` counts STEPS, not decorations: the spare duplicates banked across
    # every group that has an upgrade step, so `TAP upgrade_decoration xall` spends
    # all of them and does nothing at all when there are none — which is the normal
    # state, since a spare copy of a decoration is a rare thing to be holding. One
    # press = one step, so each press re-reads what the last reply left behind.
    "upgrade_decoration": Button(
        lua=_lua_actions.upgrade_next_decoration(),
        # The reply carries the group's refreshed info; the pause lets the next
        # count re-read see it.
        wait=1.2, label="Upgrade a decoration",
        count_lua=_lua_actions.decoration_upgrade_ready_count(),
        max_taps=25,
    ),
    "dump_decorations": Button(
        # The "why is nothing happening?" reading: every decoration that has an
        # upgrade step, with its star score, the threshold it climbs to and how many
        # steps its spares would buy. Reads only, sends nothing.
        lua=_lua_actions.decoration_state_dump(),
        wait=0.4, label="decoration state",
    ),
    "decorations": Button(
        lua=_lua_actions.decorations_window(),
        wait=1.5, label="Decorations",
    ),
    # --- the account's characters, and switching to one of them --------------
    # `list_characters` is the game's «Персонажи» screen doing its one send, without
    # the screen: the reply is asynchronous, so the pause after it is what the recipe
    # reads across, and it re-reads rather than trusting a single wait.
    "list_characters": Button(
        lua=_lua_actions.account_roles_request(),
        wait=2.0, label="ask for this account's characters",
    ),
    # The «войти» press of the character screen's login window, run headless: it saves
    # the picked character's credentials and drops the session, and the client
    # reconnects as that character. Which character is parked in a variable first
    # (`LUA DataCenter.__lw_switch_account = <server>`), because TAP takes no
    # arguments. One press — never repeat it: the second would fire mid-reconnect.
    "switch_account": Button(
        lua=_lua_actions.account_switch_press(),
        # The client tears the session down inside this pause; the recipe then polls
        # for the new character rather than assuming this was long enough.
        wait=3.0, label="switch to another character",
    ),
    # --- general navigation --------------------------------------------------
    "close": Button(
        # Close the top window by state (pop one off the UI stack). Repeat with xN.
        lua=("local w = UIManager.Instance:GetStackTopWindow() "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() end"),
        wait=0.4, label="close window",
    ),
    # --- the keyboard macros: send the squad at whatever the person chose ---
    # ONE press behind each recipe (#1283, made one call each in #1290):
    #
    #     macro_send                     keys 1..4 — the CLICKED target, or the open
    #                                    squad screen when there is one (#1328)
    #     macro_repeat                   CapsLock, with no screen at all
    #
    # WHICH squad is parked in `DataCenter.__lw_macro` by the recipe, because `TAP`
    # carries no arguments; the target is not parked by anybody — it is the point the
    # person's own map click pinned, or the one on the screen their click opened.
    # docs/research/march-hotkeys.md.
    #
    # NEITHER OF THEM PAUSES AFTERWARDS, and that is the point of #1290. A `wait` is a
    # plain sleep with the game claim held, and both recipes then measure the march
    # count themselves — which is a wait for the thing rather than a wait for a number
    # somebody guessed. The two seconds each of these used to sit out were two seconds
    # of «занят» for the next key press.
    "macro_send": Button(
        # Arm the click watcher, then take the first target there is: the open squad
        # screen's, pressed the way #1283 pressed it, or — with no screen at all — the
        # one the person's map click pinned, marched on directly with no window. One
        # chunk, one frame. What it decided is parked in `result`.
        lua=_lua_actions.macro_send(),
        wait=0.0, label="send the chosen squad at the chosen target",
    ),
    "macro_repeat": Button(
        # CapsLock: the same send the last launch made, made directly. No window is
        # opened, no camera moved, no target clicked — the uuid is the address. It
        # refuses a rally itself and parks that in `result`.
        lua=_lua_actions.macro_repeat(),
        wait=0.0, label="repeat the last macro march",
    ),
}


# --- Government -> ministry: apply for one of the server's eight posts --------
# One button per post ("apply_minister_science", "apply_vice_president", …) rather
# than one parameterised button, because `TAP` takes no arguments and a recipe that
# names the post it wants reads like the in-game click it replaces. Every entry is
# the same gated one-liner from lua_actions.ministry_apply(); the ids, the names and
# the gate are documented in docs/research/ministry.md.
#
# `max_taps=1` on purpose: an application is a single press. `xall` then means "press
# only if the post can actually be applied for right now" — which is what makes
# submit_ministry.md able to walk a preference list and stop at the first post that
# takes it. (Without the cap, a server that queues applicants instead of granting them
# instantly would leave CheckCanApply true and the loop would re-apply in a spin.)
for _pid, (_slug, _en, _ru) in _lua_actions.MINISTRY_POSTS.items():
    BUTTONS["apply_%s" % _slug] = Button(
        lua=_lua_actions.ministry_apply(_pid),
        wait=1.2, label="Apply: %s (%s)" % (_en, _ru),
        count_lua=_lua_actions.ministry_can_apply(_pid),
        max_taps=1,
    )


# --- «Найм» -> one pull on a recruit banner, heroes or survivors -----------
# The size and the banner are PARKED by the recipe before this fires
# (`DataCenter.__lw_recruit_*`), exactly as `rally_join_all` takes its squads: a `TAP`
# carries no arguments of its own, and a recipe that names its own banner is what
# `ARGS` is for. The wire is one message either way — `lottery.hero.card` /
# `lottery.worker.card`, both read off run 20260813_103441 and confirmed in the VM —
# so nothing is opened and nothing is clicked.
BUTTONS["recruit_draw"] = Button(
    lua=_lua_actions.recruit_draw(),
    wait=0.4, label="Recruit: one pull on the parked banner",
    # NO `verify_lua` HERE, on purpose. The press may decide to send nothing — no free
    # pull with «only free» asked for, not enough tickets — and a button-level check
    # would report that as «pressed and nothing moved», burying a refusal the press has
    # already explained in words. The proof lives in `recruit_draw.md` instead: it reads
    # `recruit_sent` first, and only a pull that really left is waited on
    # (`recruit_moved`).
    max_taps=1,
)


# --- «Радар» -> read the board, claim what is finished, run the ally errands ---
# The whole board is four messages and no window (#1414, #1470); which errand is which
# and why the ceiling matters is in docs/research/radar.md.
BUTTONS["radar_read_board"] = Button(
    # The refresh the board itself sends. It asks the server; the reply is what fills
    # the client's list, so everything below has to come after it and after its settle.
    lua=_lua_actions.radar_fetch_board(),
    wait=1.0, label="Radar: refresh the board",
)
BUTTONS["radar_claim"] = Button(
    # «Получить» on one card. `xall` is «Получить все», because the in-game button is a
    # client-side loop over the same message and nothing more.
    lua=_lua_actions.radar_claim_press(),
    batch_lua=_lua_actions.radar_claim_batch(),
    # Long enough for the server's replies to land, so the confirming re-read after a
    # batch sees the new badge rather than the one it started from.
    wait=0.8, label="Radar: claim one finished errand",
    count_lua=_lua_actions.radar_finished_count(),
    max_taps=60,
)
BUTTONS["radar_help_start"] = Button(
    # «Быстро выполнить»: every eligible ally errand set running in one call. NO
    # `count_lua` — this is not one press repeated, it is one press that covers the
    # whole eligible set, exactly like `collect_base_resources`.
    lua=_lua_actions.radar_help_start_all(),
    wait=0.6, label="Radar: start every ally errand",
)
BUTTONS["radar_help_end"] = Button(
    # The finish the client only sends while its own window is open. The three seconds
    # it needs are the recipe's `WAIT`, not this button's pause: a sleep here would be
    # spent even when nothing was started.
    lua=_lua_actions.radar_help_end_all(),
    wait=0.8, label="Radar: report the ally errands finished",
)


# `heal_units` is an alias of `heal_all` — the task tracker refers to the ability by
# that name, so both resolve to the one hospital.cure press.
BUTTONS["heal_units"] = BUTTONS["heal_all"]


def get(name: str) -> Button | None:
    return BUTTONS.get(name)


def names() -> list[str]:
    return sorted(BUTTONS)
