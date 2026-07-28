# Farming — feature status (v2)

What the bot can actually do today, laid out against the feature list of the old
UOPilot/Lua script ([`legacy-ru/farming.md`](legacy-ru/farming.md) /
[`legacy-en/farming.md`](legacy-en/farming.md)) and against the daily routine the
operator runs by hand ([`game/daily_cycle.md`](game/daily_cycle.md)).

The legacy list is kept section by section so the two can be diffed at a glance;
sections and items with no legacy counterpart are collected under
[New in v2](#new-in-v2--no-legacy-counterpart). **Most items are still ❌** — v2
rebuilt the foundation (protocol, Lua VM, DSL, panel) rather than the breadth, so
the coverage is deliberately narrow and deep instead of wide and pixel-fragile.

## Legend

| Mark | Meaning |
|---|---|
| ✅ | implemented and confirmed on the live client |
| 🟡 | partial — works but is unverified (`tools/dev/`, `actions/dev/`), or only one step of the flow exists |
| 🔬 | researched only — the mechanism is decoded and written up, no runnable action yet |
| ❌ | not implemented |

## How it runs — legacy vs v2

| | Legacy (`master`) | v2 |
|---|---|---|
| Runner | `uopilot242.exe` + `scripts/farming.lua`, one "play" button | control panel (`C:\Python312\python.exe -m panel`), **Scenarios** tab, one action at a time, optional repeat interval |
| Acting on the game | pixel colour → mouse click | mostly the game's **own Lua VM** through the warm daemon (`tools/lua_daemon.py`); vision (`FIND`/`CLICK`/`READ_TEXT`) only where no Lua route exists |
| Scripts | one monolithic Lua file | one file per action: [`src/lastwar_bot/actions/*.md`](../src/lastwar_bot/actions/) in the DSL ([`dsl.md`](dsl.md), [`actions-authoring.md`](actions-authoring.md)) |
| Reading the game | screen only | screen, the Lua VM (`READ_LUA`), and the decoded network protocol ([`research/protocol.md`](research/protocol.md)) |
| Scheduling | the script's own loop | **none yet** — the panel repeats a *single* selected action; nothing sequences a session |

The single biggest gap versus the legacy script is that last row: there is no
"enable and forget" runner. Every ✅ below is a button or a recipe a human still
starts.

---

### Ministry

- ❌ Application submission
- ❌ Appointment notification (telegram)
- ❌ Application submission under VS

Nothing in v2 touches the Ministry (VP) screens.

### Alliance support

- ✅ Collecting alliance gifts, ordinary and premium — [`actions/collect_alliance_gifts.md`](../src/lastwar_bot/actions/collect_alliance_gifts.md), write-up in [`research/alliance-gift-collection.md`](research/alliance-gift-collection.md)
- ✅ Help to the alliance — [`actions/help_ally.md`](../src/lastwar_bot/actions/help_ally.md) (one `OnHelpAll` answers every pending request; helping is uncapped, only the 1000 daily help *points* are)
- ✅ Donating to alliance technology — [`actions/donate_alliance_tech.md`](../src/lastwar_bot/actions/donate_alliance_tech.md), spends every banked attempt (`TAP donate_1000 xall`); see [`research/alliance-tech-donate.md`](research/alliance-tech-donate.md)
- ❌ Unit treatment (healing)
- ❌ Collecting units from the hospital
- ❌ Request for help to treat units
- 🟡 Automatic entry into a rally — `tools/rally_join.py` joins or declines a live rally and picks the squad; `tools/rally_monitor.py` streams the alliance rally feed. No policy, no loop, no DSL primitive — see [`research/rally-join.md`](research/rally-join.md)
- ❌ Creating a rally
- ❌ Treasure notification (telegram)
- ❌ Treasure digging
- ❌ Collecting a treasure gift

### Radar assignments

- ❌ Collecting completed tasks
- ❌ Completing missions
- ❌ Accumulating tasks for VS
- 🟡 The radar window itself opens headless: `tools/dev/ui_left_panel.py --open radar` (`GoToUtil.GoRadarProbe()`), see [`research/ui-open.md`](research/ui-open.md). Nothing inside it is driven yet.

### Events

- ❌ Alliance exercises
- ❌ Code name
- ❌ Desert Storm
- ❌ Snow storm

### Arms Race (event)

- ❌ Drone objective, rally creation, stamina spending
- ❌ City objective
- ❌ Hero objective
- ❌ Technology objective
- ❌ Unit objective

### VS (alliance duel)

- ❌ Opening drone chips for VS
- ❌ Army training
- ❌ Opening components for the drone
- ❌ Collecting VS gifts
- ❌ Collecting ready tasks on a VS day

### Base

- ✅ Collecting production resources — [`actions/collect_base_resources.md`](../src/lastwar_bot/actions/collect_base_resources.md); one sweep of `SendCollect` over every building with something banked. The readiness gate matters: collecting a still-producing building is rejected server-side (`602026`) and pops a toast per rejection. See [`research/resource-collection.md`](research/resource-collection.md)
- ❌ Technology research
- ❌ Upgrading buildings / constructing new ones
- ❌ Drone upgrade
- ❌ Raising the shield
- ❌ Expedition
- ❌ Levelling survivors
- ❌ Levelling decorations
- ❌ Accepting survivor gifts
- ❌ Accepting new survivors
- ❌ Assembling the secret-mission treasure from map pieces
- ❌ Daily VIP gift and points
- ❌ Collecting mail rewards

### Resources

- ✅ Collecting the basic resources (iron, food, gold) — the same base sweep as above; it covers every production line, not a fixed list of buildings
- ✅ Collecting the extra resources (drone components, seasonal, ore, …) — same sweep
- 🟡 Collecting the supply truck at the base — [`actions/dev/collect_trucks.md`](../src/lastwar_bot/actions/dev/collect_trucks.md); the bubble mechanism is confirmed live, but `OnClick` has never been fired on a truck that was actually *ready*
- 🟡 Sending squads to gather on the map — `tools/dev/gather.py` (via the tile popup) and `tools/dev/gather_direct.py` (zero UI touch); both verified live to create a march. No target selection, no recipe, no loop

### Secret missions (hero dispatch / SecretTask)

- ✅ Listing the secret tasks the client already knows, own and alliance — `tools/dispatch_tasks.py`, straight off the Lua VM, no capture and no map panning
- ✅ Finding raidable tasks on the map — `tools/secret_task_capture.py` and the DSL's `SCAN_SECRET_MISSIONS LEVEL n STAR CAN_LOOT` ([`actions/dev/scan_secret_missions.md`](../src/lastwar_bot/actions/dev/scan_secret_missions.md)). Raidable means dispatch-complete **and** not expired **and** a free slot — not merely "0/3 looted"
- ✅ Sharing a task's coordinates in chat — `tools/chat_send.py --coords` / `dispatch_tasks.py --share-args`, see [`research/chat-coord-share.md`](research/chat-coord-share.md)
- 🟡 Detecting ghost-recon missions ("Операция Призрак") — `tools/dev/secret_mission_capture.py` (tile scan `f2=29` plus the `push.ghost.recon.alliance.single` stream), [`research/world-tiles.md`](research/world-tiles.md)
- 🔬 Robbing a secret task — the `ghost.recon.steal` command and its arguments are decoded, but no tool sends it
- ❌ Refreshing missions to UR (tickets / diamonds / MEGA)
- ❌ Dispatching own secret missions
- ❌ Collecting own or alliance missions
- ❌ Setting up the map-piece exchange
- ⚠️ Star rank is **not on the wire** — a starred task is `cfgId` family 6000 minus the level-99 class, and the final call stays a by-eye check

### Trucks

- 🟡 Collecting rewards from arrived trucks — see Resources above
- ❌ Sending trucks (the dispatch window opens headless: `tools/dev/ui_left_panel.py --open truck_dispatch`)
- 🟡 Finding trucks worth robbing — `tools/dev/scan_trucks.py` indexes the trucks on the map (type / level / position / cargo / robberies spent) off the march stream. ❌ the robbery itself

### Store

- ❌ Daily diamond bonuses (daily discount, weekly card)
- ❌ Monthly card reward
- 🟡 The shop opens and switches tabs headless — `tools/dev/ui_shop.py --tab 7`, [`research/ui-open.md`](research/ui-open.md)

### Promotions

- ❌ "Battle of Arsenals" rewards
- ❌ Battle Pass rewards
- ❌ Daily Battle Pass missions

### Arena

- ❌ Apex arena
- ❌ 3-on-3 battle
- ❌ Free diamonds

### Heroes

- ❌ Free survivor and hero tickets
- ❌ Levelling heroes
- ❌ Raising hero rank
- ❌ Levelling hero skills
- 🔬 `heroId` → icon mapping is partially solved (2 ids confirmed; the full table is blocked by an encrypted config) — `tools/hero_icons_map.py`, [`research/hero-icons.md`](research/hero-icons.md)

### System

- ✅ Automatic game launch — [`actions/launch_game.md`](../src/lastwar_bot/actions/launch_game.md); readiness is a **state** check (`WAIT scene == city`), not a pixel, and it survives the client's one self-restart after the first login
- 🟡 Reacting to "logged in from another device" — the recipe exists ([`actions/dev/watchdog.md`](../src/lastwar_bot/actions/dev/watchdog.md)) but needs the modal captured as a template; nothing runs it on a tick yet
- ❌ Pausing while the user moves the mouse. v2 still needs the game focused for synthetic input (PostMessage is ignored by this client), so a human and the bot cannot share the session
- ✅ Profiles (per account settings, logs, filters) and an EN/RU panel UI — `panel/profile.py`, `panel/locales/`

### S2

- ❌ Donating coal to the alliance furnace

---

## New in v2 — no legacy counterpart

The pixel-only legacy script could not do any of these; they exist because v2
decoded the protocol and got inside the client's Lua VM.

- ✅ **Scene control without clicking** — `GAME WORLD` / `GAME CITY` (`SceneUtils.ChangeToWorld` / `ChangeToCity`), [`research/game-launch-and-scene-control.md`](research/game-launch-and-scene-control.md)
- ✅ **Jumping to coordinates**, same server and cross-server — `JUMP x, y[, server]`, `tools/goto_coord.py`, `tools/goto_server.py`; every coordinate printed in the panel log is a clickable jump link
- ✅ **Attacking or scouting a player base** — `tools/attack.py` (`ATTACK_CITY` / `SCOUT_CITY`), including reading the scout report back out of the mail, [`research/attack-and-scout.md`](research/attack-and-scout.md)
- 🟡 **Solo monster attack** — `tools/dev/solo_attack_direct.py` creates the march from a known pid/uuid; verified live
- ✅ **Reading chat** (world / national / alliance / DM) off the Lua VM with the chat window closed — `tools/chat_reader.py`, panel **Chat** tab with inline emoji, stickers and photos
- ✅ **Sending chat** — text, inline emoji, stickers, map pins, secret-task shares — `tools/chat_send.py`, [`research/chat-send.md`](research/chat-send.md)
- ✅ **Map/player intelligence** — `tools/scan_players.py` (roster with HQ level, alliance, power), `tools/scan_leaderboard.py` (rankings), `tools/dev/scan_trucks.py`
- 🔬 **Alliance presence** — the `al.rank` reply carries a per-member `online` flag and an `offLineTime` last-seen stamp ([`research/protocol.md`](research/protocol.md) §5); decoded, but no tool surfaces it yet
- ✅ **Development tooling** — live protocol sniffer (`tools/lib/live_tshark.py`), Lua function tracer (`tools/lua_trace.py`), and the trace → recipe workflow in [`skills/sniff.md`](skills/sniff.md) §8
- ✅ **Cross-server world view** — `tools/dev/cross_server.py`

---

## Coverage of the daily plan

The routine the operator wants automated (tracker task **#1051**, and
[`game/daily_cycle.md`](game/daily_cycle.md)) against what exists.

### Recurring

| Item | Status | What exists |
|---|---|---|
| Every 20 min — donate to alliance technology | ✅ | `donate_alliance_tech.md`; the panel can repeat one action on an interval |
| Every 4 h — Arms Race objectives | ❌ | — |
| Every 4 h — second truck batch | ❌ | sending trucks is not implemented |

### Daily

| Item | Status | What exists |
|---|---|---|
| Send 3 + 2 trucks | ❌ | dispatch window opens headless only |
| Collect base resources / the resource truck | ✅ / 🟡 | base sweep ✅; truck bubble 🟡 |
| Dispatch secret tasks | ❌ | listing ✅, dispatching ❌ |
| Help 5 UR/star secret tasks | ❌ | — |
| Steal 5 star tasks | 🔬 | finding them ✅ (`SCAN_SECRET_MISSIONS`), the steal command is decoded but unsent |
| Radar tasks | ❌ | window opens only |
| 20 rally joins per monster type | 🟡 | join/decline works per rally; no counting, no policy |
| Attack marked players (scout before/after) | 🟡 | attack + scout + report exist; target selection and the "don't burn" rule do not |
| Send squads to gather resources | 🟡 | `gather*.py` create the march; no target choice or scheduling |
| Treasure digging and collection | ❌ | — |
| Fireworks, alliance gifts | ❌ / ✅ | alliance gifts ✅ |
| Golden eggs / lucky gifts in chat | ❌ | chat is read and written, but no reward-claim path |
| Supplies, secret training, quests | ❌ | — |
| Arena | ❌ | — |
| Help alliancemates on request | ✅ | `help_ally.md` |
| General's challenge, tavern heroes | ❌ | — |
| Shop purchases by list | ❌ | shop opens and switches tabs (🟡) |
| Treasure maps and the exchange | ❌ | — |

### Weekday-specific and events

Everything under "По дням недели" (heroes, drone, T11, science, ghost tasks,
unit training, the Saturday shield) and every periodic event (Zombie Invasion,
Zombie Siege, alliance exercises, storms, the train) is ❌. No calendar, no
weekday branching, no event detection exists in v2.

---

## What is missing before "enable and forget"

1. **A session runner.** Nothing sequences actions, retries a failed step or
   respects a cadence. The panel repeats one selected action; a real session
   needs an ordered plan (daily_cycle §"canonical sequence") plus timers.
2. **Breadth of screens.** Mail, radar, events, VS, arena, heroes, shop, hospital
   and the base build/research queues have no automation at all — most of them are
   opened programmatically at best.
3. **Target selection.** Attack, gather and rally can all *act*, but nothing
   decides *on what* — no target policy, no daily counters.
4. **Headless environment reads.** `GoToUtil.GotoPos` emits no `world.get.block`
   traffic, so reading the map without a foreground drag is still blocked
   (tracker **#1053**); the alternative is the Lua clone enumeration.
5. **Input model.** Synthetic clicks need the game focused (this client ignores
   `PostMessage`), so any vision-driven step occupies the desktop. Lua-VM actions
   do not, which is why recipes prefer `TAP`/`LUA` over `FIND`/`CLICK`.
6. **Tracer hygiene.** Stopping the sniffer from the panel leaves ~8700 wrapped
   Lua functions in the live VM (tracker **#1084**) — relevant to anyone running
   long farming sessions with Develop mode on.
