# March energy («энергия») — the three sources, and the one that cannot be priced yet

Task #2390. Every attack march the bot sends is paid for out of the player's march energy
(`LuaEntry.Player.stamina`; a monster attack costs 10 on the account this was measured on).
A hunt that runs out of it stops, so this is where the energy comes from and in what order
it is spent.

## The order, and why it is that order

The operator's, in their own words: **«сначала бесплатные, потом за 300 алмазов и только в
конце из запасов»**.

1. **the day's free claim** — renews every server day;
2. **the cheap refill for diamonds** — renews every server day, and only the FIRST one of a
   day is cheap;
3. **the bag's own stamina items** — LAST, because they are the only one of the three that
   does not renew at all.

The reasoning is the third line: what is in the bag is a reserve that only ever goes down,
while the other two come back tomorrow. Spending the reserve while a free claim is standing
there is the one order of the three that cannot be undone.

## 1 — the free claim, proven live

* **the message**: `MsgDefines.ClaimDailyStamina` = `user.claim.daily.stamina`, sent with an
  empty table. No window is opened and nothing is read from the server first.
* **the gate**: `LuaEntry.Player.lastClaimFreeStaminaTime`, a server-ms stamp, measured
  against the SERVER's midnight — `UITimeManager:GetInstance():GetTomorrowZero()` less a
  day. Never the machine's clock, and never `todayFreeStamina`, which is a count and only
  as good as whoever resets it.
* **live, 2026-09-03**: `sent=true before=1430 now=1505 gained=75`, and a second run the
  same minute answered «today's free energy has already been taken» having sent nothing.

The ability is `src/lastwar_bot/actions/claim_free_stamina.md`; the hunt calls it before it
counts the purse.

## 2 — the refill for diamonds, and why nothing buys it yet

The rule is the operator's and it is strict: **buy only when the price is exactly 300** —
that is the first refill of a day, and the ladder goes 300, 500, 1000 after it. The price
is to be READ from the game before every purchase, never assumed, and the threshold is a
setting rather than a constant, so that a game which re-prices tomorrow makes the bot
silent instead of expensive.

**The price could not be read, so nothing buys anything.** What was searched, on a live
client, and what it answered:

| asked | answer |
|---|---|
| `MsgDefines` matching stamina / energy / recover | 20 names; the buy is `UserRecoverPlayerStamina` = `user.recover.player.stamina`, the board is `UserGetDailyStaminaInfo` = `user.get.daily.stamina.info` |
| sending `user.get.daily.stamina.info` | `ok`, and **not one readable field changed** — every stamina / gold / price / cost field on `LuaEntry.Player` was byte-identical before and after |
| config tables (`TableName`) matching price / cost / buy / daily | `credit_price`, `train_addition_price`, `goldbrick_and_price`, `lw_hero_unique_weapon_unit_cost` — none of them stamina |
| `APS_global` (`TableName.Global`), walked | `index` (`id`, `k1`, `k2`) and `data`; **no row mentioning stamina** |
| `UIAddStamina`, opened and read | the price field is `View.view.recoverCost`, and it reads **0** — the window is the generic `UIRepairBuildingPopUp` and is parameterised by data the caller gives it (`userData.n = 0` when opened cold) |
| wrapping `SFSNetwork.HandleMessage` from Lua to catch the reply | **it does take** — see the correction below; the first attempt was written wrong, not refused |

What IS readable, and is the gate for «one purchase a day» when the price is finally
found: `LuaEntry.Player.playerStaminaGoldNum` (refills bought today; `0` on a fresh day)
and `playerStaminaGoldTime` (the stamp of the last one).

### The reply IS catchable from Lua, and it does not carry a price (#2390)

The row above used to read «the assignment does not take — it is a C# static». That was
wrong, and correcting it is worth more than the search it belonged to: `SFSNetwork` is a
plain Lua table with exactly three functions in it — `SendMessage`, `HandleMessage`,
`GetMsgType` — and replacing `HandleMessage` with a closure that calls the old one
installs cleanly. **No sniffer, no second npcap listener, no capture index**: every reply
the client parses can be read in Lua, by name, at the moment it arrives.

Two things make the difference between a wrapper that installs and one that reports `?`:

* **fixed parameters, never `...`.** `function(a1, a2, a3, a4)` works; a vararg wrapper
  using `select('#', ...)` returned nothing at all.
* **nothing of the wrapper stored in `_G` but plain tables.** Parking the dump helper as
  `_G.__x = function` failed the same silent way; declaring it inside the closure works.

`src/lastwar_bot/actions/dev/wire_catch.md` is the working shape — wrap, listen,
read the box, unwrap — and it is worth reaching for on any question of the form
«what did the server actually answer».

What it caught, sending `user.get.daily.stamina.info` (values invented, shape verbatim):

    a1 = user.get.daily.stamina.info
    a2 = {lastClaimFreeStaminaTime = 1700000000000, lastStaminaTime = 1700000000000,
          todayFreeStamina = 2, stamina = 1234.0, _time = 1, _id = 1000}

    a1 = push.formation.stamina.update.new
    a2 = {lastStaminaTime = 1700000000000, stamina = 1234.0}

**Six fields, and not one of them is a price.** So the earlier «not one readable field
changed» was not a decoding failure — the board genuinely carries the purse, the stamps
and the free-claim count, and nothing about what a refill costs.

### …and it is not in the client's config either

Four more searches, all negative, all on the live client:

| asked | answer |
|---|---|
| `TableName` matching stamina / vigor / recover / energy | one table, `lw_hero_energy_levelup` — a hero's energy, not the player's |
| every one of the **743** config tables, every row, swept for a string value containing `stamina` / `vigor` | `aps_pve_trigger` (a battle trigger named `TriggerAttackStaminaBox`), `goods` rows `250000` / `250001` / `250006` and `score` — all of them the stamina POTION's icon, `Common_icon_stamina`, i.e. the bag items of §3 |
| `APS_global` rows, by value rather than by key | rows are `{id, k1, k2}` with the meaning carried by the id and no name in the row at all, so a name search cannot work; no value mentions stamina either |
| every Lua function in `_G` and in `package.loaded` whose name mentions stamina / vigor | 25 of them, and **none computes a cost**: the readable ones are `MarchUtil.GetCostStaminaByTargetType`, `UIUtil.GetFreeStaminaTime` and `DataCenter.Global.PlayerInfo.*` (`GetCurStamina`, `GetCurStaminaGoldNum`, `GetStaminaFullTime`, `SetStaminaGoldTime`, …) |

Taken together that is a conclusion rather than another gap: **the price is not in the
client.** It is not in a config table, no Lua function derives it, and the one message that
could carry it does not. The window shows it because whoever opens it is handed the number,
and the only place that number can come from is the server or the C# side — neither of
which answers a question the bot is able to ask.

### What is left, and it is the operator's call

The one thing that IS readable identifies the purchase rather than its price:
`DataCenter.Global.PlayerInfo:GetCurStaminaGoldNum()` — refills bought today, `0` on a
fresh server day. By the operator's own description of the ladder, the refill bought when
that count is `0` **is** the 300 one.

That was put to the operator with those numbers on 2026-09-04 and **they chose to buy on
the count, with a ceiling**: buy while the game says none has been bought today, price the
purchase afterwards off the diamond purse, and stop for good if that price came out above
the ceiling.

So `src/lastwar_bot/actions/buy_stamina_refill.md` is the ability, and the shape is:

    ARGS cap = 300
    RECALL stamina_refill_block INTO refill_block     -- a refusal a person has to lift
    …  refills_today == 0  and  gems >= cap           -- the gate
    TAP buy_stamina_refill                            -- user.recover.player.stamina, {}
    …  paid = gems_before - gems_now                  -- the price, learnt after the fact
    REMEMBER stamina_refill_block FROM refill_paid    -- …and never buy again

Three things about it are deliberate:

* **the diamond purse is `LuaEntry.Player.gold`.** The yellow bricks are
  `goldBrickInfos` and are a different currency; `gold` is what the refill spends;
* **a price that cannot be computed reads `-1`, never `0`.** If something credits
  diamonds in the same second, the subtraction is meaningless — and «meaningless» must
  not be allowed to look like «it was free»;
* **the refusal outlives the run, and only a PERSON lifts it.** It is written with the
  DSL's `REMEMBER` (docs/dsl.md), one row of this profile's own database, and cleared at
  the machine with `python -m panel.forget stamina_refill_block`. Nothing in the game and
  no press can clear it: lifting it is somebody saying «the new price is fine», which is
  the entire reason the ceiling exists.

The hunt and the radar both call it, immediately after the free claim (§1) and long
before the bag (§3), which is the operator's order of the three.

### A warning paid for live

Opening `UIAddStamina` and walking the window's own instance recursively — Unity objects
included — is the kind of reflection this repository already knows crashes the client, and
the client did go down seven minutes after one such walk on 2026-09-03 (`ClientGone` on
every errand at once, the process gone, a fresh pid a moment later). Read named fields;
do not walk a live window.

## 3 — the bag

`use_stamina_items` spends `STAMINA_ITEMS` — the fifty (`400401`) and the ten (`400402`) —
biggest first, one stack at a time, never past what was asked for. It is the LAST resort by
the operator's order above.
