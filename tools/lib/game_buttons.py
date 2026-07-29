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
        # visitorId == VisitorType.RECRUITMENT (3); accepting sends one
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
        # visitorId == VisitorType.GIFT (2); collecting sends the same one-shot
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
        # The daily counter only moves when the server's reply lands, and that reply
        # carries the whole reward list. Pressing again before it arrives would rob
        # against a stale budget — the queue pop is the safety net, this pause is what
        # keeps `xall` from leaning on it.
        wait=2.0, label="Rob a secret task",
        # min(targets queued, robberies left today) — so `xall` stops both when the
        # queue runs dry and when the daily cap is spent.
        count_lua=_lua_actions.secret_task_steals_pending(),
        max_taps=10,
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
    # --- Hospital: heal wounded soldiers ("Лечение юнитов") ------------------
    # One press heals EVERY wounded soldier type in a single `hospital.cure`
    # {armyArray = [{armyId, healNum}, ...]} — the message shape proven in traces
    # 20260729_152749 / 152841 (docs/research/hospital-heal.md). The soldier list is
    # read headlessly from `T11Util.GetSelfCurSoldierData()`, so no window is opened.
    # `count_lua` is the number of wounded soldier types, so `TAP heal_all xall` is a
    # clean no-op when nothing is hurt; one press already covers all types, so a plain
    # `TAP heal_all` is the usual call. UNPROVEN LIVE: the per-entry field names on
    # GetSelfCurSoldierData are still guessed (safe: a wrong guess heals nothing rather
    # than the wrong thing) — pin them down with tools/scratch/_hospital_probe.lua.
    "heal_all": Button(
        lua=_lua_actions.hospital_heal_all(),
        wait=1.2, label="Heal all wounded soldiers",
        count_lua=_lua_actions.hospital_wounded_count(),
        max_taps=1,
    ),
    # --- general navigation --------------------------------------------------
    "close": Button(
        # Close the top window by state (pop one off the UI stack). Repeat with xN.
        lua=("local w = UIManager.Instance:GetStackTopWindow() "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() end"),
        wait=0.4, label="close window",
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


# `heal_units` is an alias of `heal_all` — the task tracker refers to the ability by
# that name, so both resolve to the one hospital.cure press.
BUTTONS["heal_units"] = BUTTONS["heal_all"]


def get(name: str) -> Button | None:
    return BUTTONS.get(name)


def names() -> list[str]:
    return sorted(BUTTONS)
