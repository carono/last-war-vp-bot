# «Найм» — the recruit banners: heroes and survivors

What the game calls **Recruit** (`110021`, «Найм») is two gacha banners: one for heroes
and one for survivors. Each is pulled x1, x10 or x100, each is paid for in its own
ticket, and each has a **free pull** on a clock of its own.

Everything below was read off one recorded session — run `20260813_103441`, the player
pulling once and ten times on the heroes, then one FREE pull and a ten on the
survivors — and then confirmed field by field in the live Lua VM.

## 1. The two messages

The traffic file of that run is empty (the wire capture did not start), so the
recording's evidence is the trace, which carries the send and the serializer's own calls
under it:

```
SFSNetwork.SendMessage  lottery.hero.card    <banner>, 0, 0, <ticket>
  SFSObject.PutUtfString  id       <banner>
  SFSObject.PutInt        isTen    0
  SFSObject.PutInt        useFree  0

SFSNetwork.SendMessage  lottery.worker.card  1, 0, <banner>
  SFSObject.PutInt        useFree    1
  SFSObject.PutInt        isTen      0
  SFSObject.PutInt        officerId  <banner>
```

so the whole ability is ONE message either way, with no window opened and nothing
clicked. The parameter order is the message class's own
(`debug.getinfo(...).nparams` + `debug.getlocal`):

| message | parameters |
|---|---|
| `Net.Msgs.HeroAbout.LotteryHeroCardMessage.OnCreate` | `self, id, isTen, useFree, itemId, jigsawCount` |
| `Net.Msgs.Worker.WorkerLottery.LotteryWorkerCardMessage.OnCreate` | `self, useFree, isTen, officerId` |

`itemId` never reaches the wire as a field of its own — the client uses it to fill the
chat-AI push object beside the pull — but it must still be passed, and see §4 for the
one thing about it that costs a whole send.

## 2. `isTen` is a SIZE, not a flag — which is where x100 comes from

The recording only ever carried `isTen = 0` and `isTen = 1`, because the player pulled
one and ten. A x100 button therefore had nothing to send, and two samples of a field
called `isTen` read exactly like a boolean.

They are not. The client picks the value out of its own enum:

```lua
UIHeroMultiRecruitType = { Ten = 1, OneHundred = 2 }
```

which `UIHeroRecruitView.ExecuteMultiRecruitAction` uses when the player has switched the
big button over to a hundred (`string.dump` of that function names `curMultiRecruitType`,
`UIHeroMultiRecruitType` and the confirmation key `hero_recruit_100_tips3`). So the field
is **0 = one, 1 = ten, 2 = a hundred**, and the hundred is derived from the game's own
table rather than guessed from the two values that happened to be recorded.

The cost table agrees, and it is the second, independent witness: every banner carries

```
costItems            = { {itemId, itemNum = 1}, {itemId, itemNum = 10} }
recruit100CostInfo   = { itemId, itemNum = 100 }
recruit100ConditionInfo = { itemId, itemNum = 100 }
```

— a hundred exists on BOTH banners, and it costs a hundred of the same ticket.

## 3. The free pull, and why it is never computed here

Both banners have one and they are different shapes:

| | heroes | survivors |
|---|---|---|
| the gate | `LotteryInfo:CanFreeRecruit()` | `WorkerLotteryInfo:CanFreeRecruit()` |
| «has one at all» | `LotteryInfo:IsSupportFreeRecruit()` (`dailyFreeLimit`) | always |
| the clock | `dailyFreeNextFreshTime`, server **seconds** | `nextFreeTime`, **milliseconds** |

Both gates compare the client's own `GetServerSeconds()` against those fields, and each
does it in its own units — so **the gate is CALLED, never reimplemented**. A copy of that
arithmetic in the panel would disagree with what the person sees on screen the first time
one of the two changes, and the panel's copy would be the wrong one.

The reading normalises the timestamp to epoch seconds (anything past 10^11 is
milliseconds) purely so the countdown can be drawn; whether the pull is available is
still the client's own yes/no.

## 4. The ticket id is a STRING, and turning it into a number sends nothing

The one thing that cost a live pull. `costItems[n].itemId` is TEXT in the client, and the
message puts it into the chat-AI push object with `PutUtfString`. Reading it back through
`tonumber()` — the obvious tidy-up, since it looks like a number — makes the client's own
serializer throw before a byte leaves:

```
SFSDataSerializer.lua:55: attempt to get length of a number value (local 'val')
```

and `SendMessage` returns the error rather than raising, so a caller that does not check
reports a clean success over a pull that never happened. The same value passed as the
string it already was sent immediately. `ItemData:GetItemById` accepts either, which is
why the ticket COUNT looked right all along.

## 5. Which banner

`LotteryDataManager.curRecruitIdList` holds the hero banners the client is currently
showing — three on the account this was read on. **All three resolve through
`GetLotteryDataById`, and each is a banner of its own** with its own ticket, its own
`dailyFreeLimit = 1` and its own free-pull clock: one standing banner and two the season
added beside it. The 2026-08-13 reading claimed only one of the three resolved; that was
wrong, and #2074 is what it cost — the errand took «the first id that resolves» and
stopped there, so two free pulls a day were lost every day while every run reported a
clean success.

So there is no «the current banner». A caller that wants one names it, and a caller that
wants them all **walks the list**, which is what `tavern_free_pull.md` does — the number
of banners is a property of the season, not of the account, and nothing in the client
says how many the next one will bring.

Read live on 2026-09-02, three banners, ids and tickets of the same shape as these:

| banner | ticket | free pull |
|---|---|---|
| the standing one | its own | daily, its own `dailyFreeNextFreshTime` |
| season banner A | its own, different | daily, a clock of its own |
| season banner B | its own, different again | daily, a clock of its own |

The three clocks are genuinely different — an hour and a quarter apart on the reading
above — so «take them all and come back at the nearest» needs the whole list, not one
banner's timer.

The survivors have exactly one: `LotteryDataManager:GetOnlyWorkerLotteryData()` is the
config row (its `id` is the `officerId` the message carries) and
`WorkerLotteryDataManager:GetWorkerLotteryData()` is the account's own half, with the
free timer on it.

## 6. What is proven, and what is not

Live, on a running client (2026-08-13):

* **heroes x1** — sent, the ticket count moved, the reward window opened;
* **survivors x1** — the same;
* **the refusals** — «only free» with no free pull available sends nothing and says so;
* **the free pull itself** (2026-09-02, #2074) — two season banners in one run, `useFree
  = 1`, `cost = 0`, on a banner the account held **zero** tickets for; both went through
  and both banners' own `CanFreeRecruit()` closed behind them, which is the proof they
  really were free rather than paid for out of something else;
* **the reading** — both banners, the free gate, the timers, the tickets and all three
  prices.

From the recording, not re-sent: **x10** (`isTen = 1`, exactly as the player's own pull
went out). Not sent at all: **x100**, because it costs a hundred tickets of somebody's
own account to prove a value the client's enum and cost table both already name. It is
`isTen = 2` and the panel offers it; the first person to press it confirms it.

## 7. Where it lives

* the primitives — `tools/lib/lua_actions.py`, `recruit_state` / `recruit_draw` /
  `recruit_moved` / `recruit_verify`; the press is the `recruit_draw` button in
  `tools/lib/game_buttons.py`;
* the abilities — `src/lastwar_bot/actions/read_recruit_state.md` (the reading) and
  `src/lastwar_bot/actions/recruit_draw.md` (the pull, with `kind` / `count` / `free`);
* the panel — `panel/tabs/recruit/`, which reads with the first and presses the second,
  and holds no gate of its own.
