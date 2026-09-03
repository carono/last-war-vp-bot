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
| wrapping `SFSNetwork.HandleMessage` from Lua to catch the reply | the assignment does not take — it is a C# static, and the wrapper never installed |

What IS readable, and is the gate for «one purchase a day» when the price is finally
found: `LuaEntry.Player.playerStaminaGoldNum` (refills bought today; `0` on a fresh day)
and `playerStaminaGoldTime` (the stamp of the last one).

**The next step is a capture of the reply**, and it cannot be a second sniffer: two npcap
listeners over one interface starve each other and the starved one reads exactly like a
deaf client. It has to go through the index the panel is already running.

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
