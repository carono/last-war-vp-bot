# VIP rewards: the daily chest, the daily gift, and the one-off ladder

*#2091. Measured on a live client on 2026-09-01, VIP level 14, through the panel's own
scenario runner. Nothing here needed a capture: the whole thing is readable and pressable
from the game's Lua VM.*

The player's own profile card carries a VIP badge, and behind it two rewards come back
every day the subscription is alive — a **chest** of VIP points and a **daily gift** of
items. `actions/collect_vip_gifts.md` takes both.

## 1. Where it lives

`DataCenter.VIPManager` is the manager, and the character's own record hangs off it as
`VIPManager.vipinfo` — an instance of the client's `VIPDataInfo` class. The record is
filled at login and refreshed by the server's own `vip.info`, so **every reading below is
LOCAL**: not one question goes on the wire for it.

The record's own fields, as one live account had them:

```
level=14  score=2310870  loginDays=237  endTime=<epoch s>  lastUpdateTime=<epoch ms>
everyDayReward=0  loginScoreState=0  addScore=0  nextDayScore=0
privilegeReward="1;2;3;4;6;8;9;"     -- parsed into _privilegeRewardCanGet
boxRewardArr=<level -> the chest's contents, 1..18>
```

Four other managers carry «VIP» in their name and none of them is this one:
`VIPTemplateManager` (the level table, `maxLevel`), `VipExtendManager` (the VIP-18 city
skin), `LWVipPayDataManager` and `VipGiftActDataManager` (shop and gift-pack offers).

## 2. The gates — ask the game, never the clock

| Question | Call | Answers |
|---|---|---|
| Is the subscription running at all | `vipinfo:IsVIPActive()` | boolean |
| Is TODAY's gift still on offer | `vipinfo:CanGetDailyFreeReward()` | boolean |
| Is TODAY's points chest still on offer | `vipinfo:CanGetDailyPoint()` | boolean |
| Would the game draw a badge | `VIPManager:GetRedNum()` | number |
| The one-off ladder, per level | `vipinfo:GetPrivilegeRewardState(level)` | `1` / `0` / `-1` |

**The day boundary is the server's, and nothing computes it.** Both daily gates are the
server's own answer about today, so the recipe never reads a clock, never consults
`day_reset` and keeps no «last taken» of its own. There is nothing to drift.

`VIPManager:GetDailyPointNum()` is NOT a gate: it throws
(`VIPManager.lua:130: attempt to compare number with nil`) because `_dailyPointConfig` is
empty until the VIP shop's own config is loaded, and `OnEnterVipPanel()` does not fill it.
Nothing needs it — `CanGetDailyPoint()` answers the only question the recipe asks.

## 3. The presses, and what they put on the wire

Measured by wrapping `SFSNetwork.SendMessage` for the length of one call each and
restoring it immediately:

| Call | Wire |
|---|---|
| `VIPManager:ReceiveFreeReward()` | `vip.get.every.day.reward`, no payload |
| `VIPManager:RequestVipGetDailyPoint()` | `vip.add.login.score`, no payload |
| `VIPManager:ReceivePrivilegeReward(level)` | `vip.add.login.score` with the level as a bare number |
| `VIPManager:RequestLatestVipInfo()` | `vip.info`, no payload |
| `VIPManager:RequestRewardInfo()` | nothing — it is guarded by `_requestRewardInfo` |

The message names are the client's own constants and two of them are misleading: the
privilege chest travels on the message named for the login score, and `MsgDefines`'
`VipExtendCitySkinGet` is spelled `vip.privilege.receive` while belonging to the VIP-18
city skin. Go by the CALL, never by the name.

## 4. How a refusal announces itself: it does not

A claim the server accepts is answered by pushing the record back, which the client
applies through `VIPManager:UpdateVipInfo(record, false)` — confirmed by wrapping that very
handler and watching one `vip.info` round trip arrive with

```
UpdateVipInfo({endTime=…,everyDayReward=0,level=14,loginDays=237,loginScoreState=0,
               privilegeReward=1;2;3;4;6;8;9;,score=2310870}, false)
```

A claim it refuses is answered with **silence** — no reply, no error, no toast. So a press
proves nothing on its own, and the recipe reports what MOVED rather than what it sent: it
presses, asks for the record again with `RequestLatestVipInfo()`, and names a gate that is
still open afterwards as refused.

## 5. The one-off ladder, and the question that is still open

Beside the two daily rewards the record carries a chest per VIP level ever reached:
`boxRewardArr[level]` is its contents (a bundle of speed-ups and resource crates that grows
with the level) and `GetPrivilegeRewardState(level)` its state — `1`, `0`, or `-1` for a
level not reached yet.

**Which of `1` and `0` means «still on offer» is not settled.** The client's own parsed
field is called `_privilegeRewardCanGet` and holds exactly the levels that answer `1`,
which reads as «can get»; but on the live account `GetRedNum()` was `0` (the game would
draw no badge), and `ReceivePrivilegeReward` was refused in silence for levels of BOTH
states — `1`, `2`, `5`, `7` — leaving the ladder untouched. So on that account there was
simply nothing left to claim, and the two states could not be told apart.

`collect_vip_gifts.md` therefore **reads the ladder into its log and presses nothing on
it**. A press nobody can gate is seven refused messages a run; a log line costs nothing and
is what will settle the question the first time a level is genuinely unclaimed.

## 6. What was probed and found not to matter

* `OnEnterVipPanel()` / `CheckOpen()` fill nothing and change no gate — the manager needs
  no «panel opened» ceremony before a claim.
* `string.dump` is refused (`lua_dump is disabled`), so the manager's source cannot be read
  back; every conclusion above is from behaviour and from `debug.getinfo`.
* `GetPointGoodList()` (6 shop goods) and `GetRenewGoodList()` (3) are the VIP SHOP, not a
  reward.
* `FreeGoodCanGet(x)` answered `false` for every level and every pack id tried; it belongs
  to the paid packs (`GetAllVipPacks()` -> level -> packId), not to the daily gift.
