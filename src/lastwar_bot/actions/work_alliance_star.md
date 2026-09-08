# Alliance Star: like every star of the week, then take the two chests it pays.
# ru: Звезда альянса: поставить лайки всем звёздам недели и забрать два сундука.
#
# WHAT THE EVENT IS. Once a week the alliance's duel is totted up and the game holds a
# ceremony: fourteen categories, three nominees in each, one of them the STAR. A member
# may give each star a like, and the likes pay two chests — one for having liked at all
# (its tiers are `GetRewardSetting()`), one for taking part. Both are free: no diamonds,
# no quota anybody else is spending, nothing that expires unclaimed inside the week.
#
# NOTHING HERE OPENS A WINDOW. The whole ability is four commands on the wire, read off
# the client's own message classes (docs/research/alliance-star.md):
#
#   alliance.star.gain.activity.info.new           -- is there a ceremony at all
#   alliance.star.gain.ceremony.info.new           -- the ceremony, its stage, its board
#   alliance.star.gain.thumbs.up   (edition, "")   -- the board of likes, with mine on it
#   alliance.star.thumbs.up.new    (configId, targetUid, thumbsIndexId, type)   -- A LIKE
#   alliance.star.ceremony.quest.emoji.reward.new  -- the chest the likes earned
#   alliance.star.ceremony.quest.reward.new        -- the chest for taking part
#
# THE GATES ARE THE SERVER'S OWN FLAGS, never a count this recipe keeps: a star already
# liked carries `selfThumbs`, the like chest carries `canReward`, the participation chest
# carries `participateReceive`. So a second run on the same Sunday sends nothing and says
# so, and a run on any other day stops at the first question.

# Which of the five ceremony emoji the like is given with. They are interchangeable —
# the chest counts LIKES, not faces — so the default is simply the first.
ARGS emoji = 1

# 1. Is there a ceremony this week at all? The one question that is asked whatever the
#    day is, and the one that costs nothing when the answer is «no».
LUA pcall(function() DataCenter.AllianceStarManager:RequestActivityInfo() end)
WAIT 2
READ_LUA (function() local M=DataCenter.AllianceStarManager if M==nil then return 0 end return (M.hasCeremony and 1 or 0) end)() INTO ceremony

IF ceremony == 0
    LOG "alliance star: no ceremony right now — nothing to like"
    STOP "no ceremony"

# 2. The board. Two asks: the ceremony itself (who is nominated, who is the star) and the
#    likes standing on it, which is where OUR own like shows up as `selfThumbs`.
LUA pcall(function() SFSNetwork.SendMessage('alliance.star.gain.ceremony.info.new') end)
WAIT 2
LUA pcall(function() SFSNetwork.SendMessage('alliance.star.gain.thumbs.up', DataCenter.AllianceStarManager.ceremonyEdition or 0, '') end)
WAIT 3

READ_LUA (function() local M=DataCenter.AllianceStarManager local n=0 for _,l in pairs(M.ceremonyThumbs or {}) do for _,v in pairs(l or {}) do if v.isStar then n=n+1 end end end return n end)(), (function() local M=DataCenter.AllianceStarManager local n=0 for _,l in pairs(M.ceremonyThumbs or {}) do for _,v in pairs(l or {}) do if v.isStar and type(v.selfThumbs)=='table' and next(v.selfThumbs)~=nil then n=n+1 end end end return n end)() INTO stars, liked

IF stars == 0
    LOG "alliance star: the board came back empty — nobody to like"
    STOP "empty board"

# 3. THE LIKES, all of them in ONE call. A round trip costs the trip and not the work
#    inside it, and thirteen sends inside one chunk all landed live (#2584) — so the
#    loop is in the game rather than in the recipe. A star that already carries a like
#    of ours is skipped, which is what makes a second run free.
READ_LUA (function() local M=DataCenter.AllianceStarManager local sent=0 for _,l in pairs(M.ceremonyThumbs or {}) do for _,v in pairs(l or {}) do if v.isStar then local mine=(type(v.selfThumbs)=='table' and next(v.selfThumbs)~=nil) if not mine then local ok=pcall(function() SFSNetwork.SendMessage('alliance.star.thumbs.up.new', v.configId, tostring(v.uid), {emoji}, 1) end) if ok then sent=sent+1 end end end end end return sent end)() INTO sent

IF sent == 0
    LOG "alliance star: every star already has our like ({liked} of {stars})"
ELSE
    LOG "alliance star: {sent} like(s) sent"

# 4. Re-read the board, so what is reported is what the SERVER now holds rather than what
#    was sent at it.
WAIT 3
LUA pcall(function() SFSNetwork.SendMessage('alliance.star.gain.thumbs.up', DataCenter.AllianceStarManager.ceremonyEdition or 0, '') end)
WAIT 3
READ_LUA (function() local M=DataCenter.AllianceStarManager local n=0 for _,l in pairs(M.ceremonyThumbs or {}) do for _,v in pairs(l or {}) do if v.isStar and type(v.selfThumbs)=='table' and next(v.selfThumbs)~=nil then n=n+1 end end end return n end)() INTO liked

# 5. THE FIRST CHEST — what the likes earned. Its tiers are claimed one at a time and the
#    server says when there is nothing left: `canReward` goes false and the block itself
#    goes away, so a nil reads exactly like a «no» and the loop ends either way.
READ_LUA (function() local M=DataCenter.AllianceStarManager local ok,e=pcall(function() return M:GetEmojiThumbsRewardInfo() end) if not ok or type(e)~='table' then return 0 end return (e.canReward and 1 or 0) end)() INTO chest_likes

WHILE chest_likes == 1 LIMIT 4
    LUA pcall(function() SFSNetwork.SendMessage('alliance.star.ceremony.quest.emoji.reward.new') end)
    WAIT 3
    READ_LUA (function() local M=DataCenter.AllianceStarManager local ok,e=pcall(function() return M:GetEmojiThumbsRewardInfo() end) if not ok or type(e)~='table' then return 0 end return (e.canReward and 1 or 0) end)() INTO chest_likes

# 6. THE SECOND CHEST — for taking part. One flag, one send, and the flag is read back
#    rather than assumed: the reply carries it.
READ_LUA (function() local M=DataCenter.AllianceStarManager local fd=M.ceremonyFullData if type(fd)~='table' then return 0 end return (fd.participateReceive and 1 or 0) end)() INTO taken_part

IF taken_part == 1
    LOG "alliance star: the taking-part chest was already claimed"
ELSE
    LUA pcall(function() SFSNetwork.SendMessage('alliance.star.ceremony.quest.reward.new') end)
    WAIT 3
    READ_LUA (function() local M=DataCenter.AllianceStarManager local fd=M.ceremonyFullData if type(fd)~='table' then return 0 end return (fd.participateReceive and 1 or 0) end)() INTO taken_part

# 7. What the run did, in the two numbers the card draws.
# `liked` was read by this run, so it is PARKED rather than interpolated: a `{name}` is
# filled when the file is parsed, and `{liked}>0` reached the game as a table constructor
# compared with a number — an error in the one branch that used it (#2649).
PARK liked INTO DataCenter.__lw_star_liked

READ_LUA (function() local M=DataCenter.AllianceStarManager local n=0 local ok,e=pcall(function() return M:GetEmojiThumbsRewardInfo() end) local claimed=0 if ok and type(e)=='table' then claimed=tonumber(e.claimedIndex) or 0 end if claimed>0 then n=n+1 elseif (not ok or type(e)~='table') and (tonumber(DataCenter.__lw_star_liked) or 0)>0 then n=n+1 end local fd=M.ceremonyFullData if type(fd)=='table' and fd.participateReceive then n=n+1 end return n end)() INTO chests

LOG "alliance_star_done — likes {liked}/{stars}, chests {chests}/2"
