# Keep the ear on the reward popups, and bring back what it heard.
# ru: Держать слушатель наградных окон и забрать, что он услышал.
#
# WHAT IT IS FOR (#2027). Half the abilities of this bot end in a modal: a help given to
# an alliancemate's secret task, a gift collected, a truck brought home. The panel presses
# headless, so nobody asked for that window — it lands on top of the client anyway and
# stays there. The old answer was a press of its own after each collect
# (`TAP dismiss_reward_popup`): a sweep of every open window whose name carries
# `Reward`/`GetGift`. It works, and it is a PRESS — it happens only where a recipe
# remembered to put it, it says nothing about what was IN the window, and a popup raised
# by something the panel did not start sits there until the next recipe runs.
#
# So this is an EAR instead, which is what «читаем один раз, дальше слушаем» asks for
# (CLAUDE.md). `TAP watch_reward_popups` wraps two of the client's own Lua methods, once
# per client: the reward manager's show-methods (which carry the reward list — that is
# WHAT was given) and `UIManager:OpenWindow` (where the popup arrives). From then on the
# client closes its own reward popups and writes down what it was given, with NO question
# asked of the game by anybody: the wrappers run inside calls the game was making anyway.
#
# ONLY A REWARD WINDOW IS EVER CLOSED, and it takes two conditions at once: the game must
# have called a reward show in the last three seconds AND the window's name must carry
# `Reward` or `GetGift`. A mini-game, a squad screen, a purchase the panel itself opened
# can therefore never be shut by this — which is the one class of breakage a blind
# «close whatever popped up» would buy.
#
# WHAT COMES BACK. One line per drain, `reward_popups: <row> ;; <row> ;; …`, each row
# `<game clock ms>|<kind>|<what>`:
#
#     1756402331000|reward|ShowCommonReward|101x2,102x1     what the game said was given
#     1756402331080|closed|UIGiftPackageRewardGet           …and the window it shut
#     1756402340000|popup|UIDispatchTaskReward              a reward window it could NOT shut
#     0|lost|4                                              rows the ring dropped, uncounted
#
# The panel books those rows against whatever it was playing at the time
# (`panel/runtime/rewards.py`) — the «за что» half of «что дали и за что». Nothing in the
# client knows why a reward arrived, and the panel does: it started the recipe.
#
# CALL THIS AT THE END OF ANY RECIPE THAT EARNS SOMETHING. It costs one round trip when
# there is nothing to bring back and two when there is, and it puts the ear back into a
# client that has restarted since the last one.

# 1. Put the ear in. Idempotent: a client that already has it pays nothing at all.
TAP watch_reward_popups

# 2. How much is waiting. Asked before the drain so that a run with nothing to say does
#    not write an empty line into every log the panel keeps.
READ_LUA (function() local B=DataCenter.__lw_rewards if B==nil then return 0 end return #(B.rows or {})+((B.lost or 0)>0 and 1 or 0) end)() INTO reward_rows

# 3. …and take it, clearing the ring as we go. The rows are the panel's from here on.
IF reward_rows > 0
    READ_LUA (function() local B=DataCenter.__lw_rewards if B==nil then return '' end local r=B.rows or {} B.rows={} if (B.lost or 0)>0 then r[#r+1]='0|lost|'..tostring(B.lost) B.lost=0 end return table.concat(r,' ;; ') end)() INTO reward_popups
    LOG "reward_popups: {reward_popups}"
