# Mail gifts — the badge on a tab, and the «collect all» behind it (#2090)

How the panel takes the attachments waiting in the game's Mail: what the client already
knows (so nothing has to be asked on a clock), which call is the tab's own «собрать всё»,
and what the server confirms afterwards.

- The recipe: `src/lastwar_bot/actions/collect_mail_gifts.md`.
- The errand: `mail_gifts` in `panel/triggers.py` — a wire trigger on `push.mail`, off by
  default.
- Related: `docs/research/reward-popups.md` (the modal a collect raises is closed and
  written down by the ear, #2027).

Every id and figure below is of the shape a live client answered with; the account's own
values are replaced (`CLAUDE.md`, «Not one identifier of a real account is written down»).

---

## 1. The tabs are «groups», and each keeps its own badge

`DataCenter.MailDataManager.group` is a table keyed by the tab id, and every entry carries
the three numbers the tab draws — measured live on 2026-09-01, nine tabs:

```
group[<tab>] = { groupId = <tab>, total = 1566, unreadCount = 22, unrewardCount = 11, hide = 0 }
```

* **`unrewardCount` is the gift badge** — letters on that tab whose attachment nobody has
  taken. It is the one number this ability gates on.
* `unreadCount` / `total` are the tab's other two figures and are not acted on.

The same figures are readable by method — `GetMailUnRewardCountByGroup(<tab>)`,
`GetMailUnReadCountByGroup(<tab>)`, and `GetMainUIUnRewardCount()` for the badge on the
main screen's mail icon. All LOCAL: no request leaves the machine.

Nine tabs were present on the account measured, with `unrewardCount`
`0,0,3,11,0,0,0,0,1` — fourteen gifts, on three tabs.

## 2. A letter says the same thing itself

A mail object (`MailDataManager:GetGroupMailList(<tab>)`) carries, among its fields:

```
uid           <a 32-char hex string>     -- the letter
groupId       4                          -- the tab it sits on
mailId        60102                      -- what KIND of letter it is
type          106
rewardStatus  0                          -- 0 = the gift is still there, 1 = taken
createTime / expireTime                  -- ms; a letter lives for weeks
```

and the methods `CanClaimReward()`, `GetMailReward()`, `GetRewardData()`, `SetMailRead()`.
`CanClaimReward()` agreed with `rewardStatus == 0` on every letter measured, and the count
of those agreed with the tab's `unrewardCount`.

**The lists are PAGED**, though — a tab of 1 566 letters hands out twenty at a time
(`GetMoreGroupUIMailList`, `ReqMore`) — so a sweep over the loaded page is a sample, not
the list. That is why the recipe gates on the tab's count and not on the letters.

## 3. The press

`MailDataManager:ReadAndRewardGroupMail(<tab>)` — the manager's own «collect all», the
call behind the button on the tab. It goes out as `mail.reward.batch`
(`MsgDefines.MailRewardBatch`) and the reply is handled by `HandleMailRewardBatchMessage`.

**It needs no window open.** Measured headless on the tab that had one gift left: the call
returned at once, and within two seconds the badge went `1 -> 0` and the letter's
`rewardStatus` `0 -> 1`. Then over the two tabs holding the other fourteen: `[3:3, 4:11]`
pressed, `still waiting = 0`.

As the name says it also marks that tab's letters READ — exactly what pressing the button
in the game does.

The neighbouring wire names, for whoever needs them next: `mail.read` (`MailGet`),
`mail.read.status` / `mail.read.status.betch`, `mail.reward` (one letter),
`mail.delete` / `mail.delete.batch`, `mail.save` / `mail.cancel.save` (favourites),
`get.fight.report.detail`, and the pushes `push.mail`, `push.mail.read`,
`push.mail.reward.batch`, `push.battle.report`, `push.mail.delete.batch`.

## 4. Why there is no clock

A letter arriving is announced: `push.mail` (`MsgDefines.PushMail`,
`HandlePushMailMessage`). So the ability is an ear — the trigger `mail_gifts` — and
nothing in the panel asks the mail anything on a beat (`CLAUDE.md`, «читаем один раз,
дальше слушаем»).

The push fires for every letter, gift or not, and that is affordable because the gate is
local: a fire whose badges are all zero is one VM round trip that presses nothing and
sends no request. Nothing here is a race — a gift sits in its letter until the letter
expires, weeks away — so the errand is deliberately NOT «сразу, без очереди» and takes its
turn behind work that is timed.

## 5. What a run says

```
Mail gifts: tabs=9 gifts=14 pressed=2 failed=0 [3:3,4:11] ms=0
Mail gifts: still waiting=0
```

The first line is what the client knew and what was pressed; the second is what the SERVER
made of it, read 1.5 s later off the same badges — a tab still standing above zero there
is a press the server refused, and it is never counted as a success. A run that pressed
nothing skips the second reading and the wait entirely.
