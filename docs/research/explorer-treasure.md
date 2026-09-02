# The explorer's chests — «Сундуки исследователя» (#2381)

The third thing on the mobile squad's window, beside our secret tasks and the piece
exchange: a chest the explorer opens for a handful of keys. This is what it is made of in
the client, measured live on 2026-09-02.

**Nothing in this file is a real identifier.** The numbers below are item and config ids,
which are the same for every account; no uid, name, alliance or coordinate appears.

---

## 1. Who owns it

| thing | where |
|---|---|
| the whole feature | `DataCenter.ExplorerTreasureManager` (Lua, `DataCenter.ExplorerTreasure.ExplorerTreasureManager`) |
| the key | item **771001**, «Ключ исследователя» — `nTreasureItemId`, `GetTreasureItemId()` |
| the chest item shown in the preview | 771002 — `GetTreasureItemBoxId()` |
| the price of one chest | `GetTreasureOpenNeedItemNum()` = `treasureNeedNum` = **5** keys |
| the purse | `GetTreasureHaveItemNum()` |
| is the activity running | `IsOpen()` |
| the guarantee | `GetGuaranteedTimes()` of `GetGuaranteedNeedTimes()` — 10 opens |
| the tiers | `tTreasureBoxCfg`, seven rows keyed by base level (`nMinLv`/`nMaxLv`, 1–12, 13–17, 18–22, 23–26, 27–30, 31–33, 34–35) |
| the send | `MsgDefines.ExplorerTreasureOpen` = **`hero.dispatch.explorer.treasure.open`** |
| the message class | `Net.Msgs.ExplorerTreasure.ExplorerTreasureOpenMessage` |

Not this feature: `DigTreasureManager` (the treasure-map mini game, item 771030),
`ActDispatchTreasureManager` (the piece exchange), `ActDetectTreasureDataManager` (the
chests on the world map). The three were told apart once already in
[`world-treasures.md`](world-treasures.md) and the disambiguation there still holds.

## 2. The send takes NO parameter, and that is the whole ability

The message class was instantiated offline and its `OnCreate` read for locals: it is
`OnCreate(self)`, with no `param` at all — the base class's is `OnCreate(self, param)` and
this one does not use it. So there is no count, no tier and no target to choose:

```lua
SFSNetwork.SendMessage(MsgDefines.ExplorerTreasureOpen)   -- one send, one chest
```

Which tier the chest comes from is the SERVER's business, decided by the base level
through `tTreasureBoxCfg`. Nothing the client sends can pick it.

## 3. What it costs, and what it does not

* **Five keys, and nothing else.** No diamonds, no daily attempt, no march, no window.
* **The keys come from our own finished secret tasks and from nowhere else** — which is
  the whole reason this errand is woken by a claim rather than by a clock. Between two
  claims the purse cannot move, so a period in front of it would be a question asked for
  nothing (`CLAUDE.md`, «Read once, then LISTEN»).
* **No daily cap was found.** Nothing on the manager counts opens the way
  `hero.dispatch.list` counts `todayStealNum`; the only ceiling is the purse. The `max`
  knob in the recipe is therefore OURS, a guard for a person saving up, not a rule of the
  game's.
* **The guarantee is a counter and not a cost:** every open raises `GetGuaranteedTimes`
  by one, and at ten the game owes the guaranteed reward.

## 4. Measured live, once

Five chests opened in one run of `actions/open_explorer_chests.md`, off the profile's own
log:

| reading | before | after |
|---|---|---|
| keys in the purse | 29 | 4 |
| chests the purse buys | 5 | 0 |
| guarantee | 3/10 | 8/10 |

Each press reported `explorer_open sent=1 have=<29,24,19,14,9> need=5 why=`, i.e. the
purse fell by exactly five between presses — which is what the button's `verify_lua`
watches, so a press the server ignored fails the recipe instead of being reported as done.
The bag gained training manuals, research speed-ups and SR resource chests; what fell out
is read as a DIFFERENCE of the bag, because the reward is a picture and the server sends
no receipt anything here can read (the same method `collect_secret_tasks.md` uses).

## 5. What the panel plays

| file | what it is |
|---|---|
| `actions/open_explorer_chests.md` | the ability: gate, open while the keys last, say what came out |
| `tools/lib/lua_actions.py` | `explorer_treasure_state` / `explorer_treasure_left` / `explorer_treasure_open` |
| `tools/lib/game_buttons.py` | button `open_explorer_treasure` — one chest, with the price gate and the purse as its proof |
| `actions/read_daily_checklist.md` | `explorer_keys` / `explorer_chests`, riding on the one reading the person allowed (#2019) |
| timer `open_explorer_chests` | six hours, off by default — the safety net, not the schedule |
| trigger `explorer_chests` | on `hero.dispatch.batch.reward`, off by default — the claim's own answer, which is the one moment a key can arrive |

The two knobs (`keep` — keys never spent; `max` — chests per run) are the recipe's ARGS
and live in the errand's own row, drawn behind the gear on «Таймеры»
(`panel/tabs/secret_tasks/tab.py::errand_options`). Nothing is copied: the gear writes the
row the run reads.

## 6. Dead ends worth not repeating

* `ExplorerTreasureTemplateManager` does not exist; the tier table is a field of the
  manager itself (`tTreasureBoxCfg`).
* The manager is full of Unity transforms (`bubbleObj`, `keyIconTrans`, `explorerAnim`) —
  it draws the bubble in the city as well as holding the data. None of that is needed:
  every number above is a plain method call and the send is headless.
* `GetRedPointCount()` answers the same number as `floor(have / need)`; it is the red dot
  and not a separate allowance.
