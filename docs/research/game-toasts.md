# Where the game's floating toast comes from, and how to ask it (#2677)

The operator saw «Недостаточно предметов» in the middle of the screen, repeatedly, and
there is nothing on screen that says which part of the game raised it: the toast has no
title, no window and no button. Nothing in this repository prints that sentence either —
it is the CLIENT's own text — so «who raised it» is a question only the client can
answer.

This is what it takes to ask it, end to end, and it is a recipe for the next such hunt
rather than a note about one toast.

## 1. The wording is a key in the game's own tables

`tools/game_locale.py` reads the tables the client ships. The lookup by an English term
only searches `en`, so a Russian sentence is found by loading that language and matching
the value:

```python
import game_locale as gl
ru = gl.load("ru")
hits = [(k, v) for k, v in ru.items() if v.strip() == "Недостаточно предметов"]
```

Five keys carry exactly that sentence, and the English side tells them apart:
`120021` («Not enough items.», the generic one), `Treasure_map_23` (the piece-exchange
board), `quick_upgrade_tips`, `s0_alliance_boss_donation_null_tips` and
`activity_sports_useitem_desc3`. **So the text alone can never name the caller** — five
unrelated abilities say the same words, and the toast shows the words.

## 2. `UIUtil.ShowTips` is the sink

Read off the live VM (a scan of `_G` two levels deep for names holding `ShowTip`,
`FloatTip`, `Toast`, `ShowFloat`, `FlyText`, `ShowText`):

    GameMain.ShowTips, UIExtraEffect.ShowTip, UIUtil.ShowFloatAnim,
    UIUtil.ShowTipsWithImage, UIUtil.DoFlyText, UIUtil.ShowTipsLocalization,
    UIUtil.ShowTipsId, UIUtil.ShowFlyText, UIUtil.ShowTips,
    NoticeTipsManager.ShowTip, RaceEntranceUtil.CheckCanShowTip

`debug.getinfo(f, 'u')` then says which one to wrap:

| function | nparams | vararg |
|---|---|---|
| `UIUtil.ShowTips` | 8 | no |
| `UIUtil.ShowTipsId` | 1 | yes |
| `UIUtil.ShowTipsLocalization` | 1 | yes |
| `NoticeTipsManager.ShowTip` | 1 | no |

The two vararg ones are front doors that resolve a key and call `ShowTips`;
`NoticeTipsManager.ShowTip` takes only `self` (it draws what was queued with `AddItem`)
and is NOT the mid-screen toast. **Wrap `UIUtil.ShowTips` and you catch all of them.**

## 3. The wrapper, and the two ways it silently catches nothing

Same two rules `dev/wire_catch.md` learned the hard way:

* **fixed parameters, never `...`** — a vararg wrapper catches nothing at all. Eight of
  them here, because that is what `getinfo` said;
* **nothing parked on `_G`** — `Global/GlobalProtect.lua` refuses a new global and only
  logs about it (#2656), so the box is never created and every run stacks another
  wrapper. The state hangs off `DataCenter`, which is an ordinary table.

The catch records `os.date('%H:%M:%S')`, the first argument and `debug.traceback` — both
of which the sandbox still allows, unlike `getupvalue` / `string.dump`. The stack is
what answers the question: the client is built with full paths, so a line reads

    …/LuaScripts/DataCenter/AllianceData/AllianceWarDataManager.lua:306
      in function 'UpdateOneAllianceWarList'
    …/LuaScripts/Net/Msgs/Alliance/PushAllianceMarchRefreshMessage.lua:20
      in function 'HandleMessage'

— i.e. that toast was raised by the client applying a push, and not by anything the
panel pressed.

The whole ear is three throwaway `actions/dev/_*.md` files (armed, read, unarmed), and
`dev/` recipes starting with `_` are git-ignored on purpose. The Lua is:

```lua
-- arm: records and passes through, so the toast still shows exactly as it would
(function() local B = DataCenter.__lw_toast if B == nil then B = {} DataCenter.__lw_toast = B end
  B.box = B.box or {}
  if B.wrapper ~= nil and UIUtil.ShowTips == B.wrapper then return end
  local old = UIUtil.ShowTips if type(old) ~= 'function' then return end
  B.orig = old
  B.wrapper = function(p1, p2, p3, p4, p5, p6, p7, p8)
    pcall(function()
      local box = B.box if #box > 60 then table.remove(box, 1) end
      local when = '?' pcall(function() when = os.date('%H:%M:%S') end)
      local st = '' pcall(function() st = debug.traceback('', 2) end)
      box[#box + 1] = when .. ' :: ' .. tostring(p1) .. ' :: ' .. string.gsub(tostring(st), '%s+', ' ')
    end)
    return B.orig(p1, p2, p3, p4, p5, p6, p7, p8)
  end
  UIUtil.ShowTips = B.wrapper end)()

-- unarm: the pair, and it must be run — a wrapper left on is a wrapper the next agent
-- finds and cannot explain
(function() local B = DataCenter.__lw_toast
  if B ~= nil and B.wrapper ~= nil and UIUtil.ShowTips == B.wrapper then UIUtil.ShowTips = B.orig end
  DataCenter.__lw_toast = nil end)()
```

**Prove the ear before trusting a silence.** One `UIUtil.ShowTips('lw-ear-selftest')`
appears in the box; if it does not, the sink is somewhere else and «nothing caught»
means nothing.

## 4. What it cost, and what it does not survive

Nothing measurable: `ShowTips` is called when a toast is shown and at no other time —
it is not a per-frame hook. It does not survive a CLIENT restart (the wrapper lives in
that client's Lua VM), so a hunt that has to span one re-arms on a clock; a PANEL restart
does not touch it.

## 5. What the hunt of #2677 actually found

The ear was armed on the live client at 13:26 and read every minute for half an hour. It
caught real toasts throughout — an ally's march that had already left, a stamina claim,
two research helps — and **not one «Недостаточно предметов»**. The operator confirmed in
the same window that the toasts had stopped, so what they saw was a burst earlier in the
day rather than a standing behaviour, and there is nothing to gate yet. The way to answer
it is written down above: arm while it is happening, and the stack names the caller.
