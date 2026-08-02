# Farming — what the bot can do

> На русском: [`farming.ru.md`](farming.ru.md)

<!-- progress:start -->
🟩🟩🟩🟩🟩🟨🟨🟨🟨🟨🟨🟥🟥🟥🟥🟥🟥🟥🟥🟥  **27%** — 27 of 101

🟩 27 done · 🟨 30 partly · 🟥 44 not automated
<!-- progress:end -->

A plain feature list: what is automated today, what is half-way there, and what
is still done by hand. The sections follow the feature list of the old script
([`legacy-ru/farming.md`](legacy-ru/farming.md) /
[`legacy-en/farming.md`](legacy-en/farming.md)) so the two can be compared line
by line.

The short version: **most items are still ❌**. The rewrite went for depth
first — the few things marked ✅ run reliably and without watching the screen —
so the breadth of the old script has not been caught up with yet.

| Mark | Meaning |
|---|---|
| ✅ | works, confirmed in the live game |
| 🟡 | partly there — one step of the flow works, or it works but has not been proven in a real session |
| ❌ | not automated |

## How a run looks

The old script was one button: start it and it played the whole routine by
watching pixels. Today there is a control panel where each ability is a separate
named action you pick and run, and it repeats on an interval if you want it to.

Most actions no longer look at the screen at all — they ask the game itself to
do the thing, which means they survive interface changes, work while the window
is in the background, and never mis-click. A handful of abilities that have no
such route still read the screen the old way.

A few abilities no longer need starting at all: the panel has a schedule, and an
errand listed there runs itself once its period has passed — collecting the base,
and keeping the alliance up (donate, then claim the gifts) as one errand. The
clock is kept per account and survives a restart, so an hour that ran out while
the panel was closed is worked off shortly after it opens. Two errands that come
due at the same moment never run at the same time: they queue and take their
turn, so the game is only ever being driven by one of them. Which errands the
schedule holds is a list you can edit — adding one, or changing what it does and
how often, needs no change to the program — and the list belongs to the account,
so two of them can be farmed on two different schedules.

The one thing the panel cannot do yet is **play a whole session on its own**: it
repeats a chosen action and keeps a handful of abilities to their own clocks, but
nothing chains the routine together from start to finish. Every ✅ below that is
not on the schedule is still something a human starts.

---

### Ministry

- ✅ Applying for a post — one press asks for any of the eight ministry posts; the queue and how long the current holder has sat are readable too, so a script can decide when to ask
- ❌ Notification about an appointment
- ❌ Applying during the alliance duel

### Profession skills

The active skills of the profession the account picked (Engineer / Warlord). Each
is a banked charge on a 23.5-hour-plus cooldown, so one left unspent is a day of
that payout thrown away. (Previously logged under Ministry as "the buffs a serving
minister hands out" — the recording shows it is the profession tree, not a post.)

- 🟡 Firing the skills that need no target — production, instant collect, speed-up chest, a survivor, an instant step off the build or research queue: one press each, no window opened, whatever is off cooldown. The press is proven against the live game, but no charge was free to spend, so a run has not been confirmed in-game yet
- ❌ The skills that need a target — helping an alliancemate's build or research, planting the siege banner: they want a world point and nothing picks one yet

### Alliance support

- ✅ Collecting alliance gifts — both ordinary and premium
- ✅ Helping the alliance — a single press answers every pending request at once
- ✅ Answering help requests the second they arrive — a panel checkbox («Авто-помощь союзникам») notices a new request by itself and makes that same press about two seconds later, so a request is answered while it is still worth points and nobody has to be watching. Proven live: five requests in a row answered right as they appeared. It also turned up why the press-on-demand version kept helping nobody, and that is fixed
- ✅ Donating to the alliance's priority technology — spends every attempt currently banked
- 🟡 Donating and claiming the gifts on a schedule — one switch and one period in the panel (an hour by default, and it goes down to the 20 minutes the routine actually asks for): once that long has passed, the donation happens and the gifts are claimed straight after it, in that order, with nobody watching. The clock belongs to the account and survives a restart, so a period that ran out while the panel was closed is worked off shortly after it opens; nothing fires while the game is not running, and a run that fails is retried whole instead of counted. Both presses are the proven ones above; the schedule itself has not yet run through a live session
- ✅ Healing units — one press sends every wounded soldier type for treatment at once, no window opened, and it does nothing when nobody is hurt. Proven live: 681 wounded went in on a single press. If the hospital is busy — a heal already running, or finished soldiers still waiting to be picked up — the game turns the press down, so collect first
- ✅ Collecting units from the hospital — takes the healed soldiers back and frees the hospital for the next heal. Costs nothing while a heal is still running, so it can be run on any schedule
- ✅ Asking for help with healing — one press puts the request in front of the alliance, and it is skipped when a request is already standing. Proven live: five alliancemates answered within seconds of the press. It also asks for the base's other working queues, but only the hospital is confirmed to register
- 🟡 Joining a rally — the bot can join or decline a live rally and pick which squad goes, and it can now be told «join with squads 2 and 3»: it reads the rallies that are out, sends each named squad to a different one, and skips any rally it is already in. Which rallies are worth joining is still nobody's decision, and no count is kept. The joining itself is the proven one; sending several squads in one go has not been tried on live rallies yet
- 🟡 Being told a rally has gone out, and joining it without hunting for it — the moment one appears the panel says so and rings, once per rally rather than once per event; one button joins with the squads ticked on the settings page, and a switch makes it join by itself as the alert lands. Which squads may go is finally the setting it always looked like — it used to be saved and read by nothing. Not yet seen against a live rally
- 🟡 Starting a rally on a Fatal Elite or an ordinary monster — its own «Ралли» tab: pick what to rally (a Fatal Elite or a world monster), drag the level slider — 1 to 200 for both, since a season puts monsters far above the everyday range on the map, with the level it sits on spelled out beside it — tick the squads that should each raise a rally, say how many times over, and «Запустить» runs «ask the game's own map search to bring up a target of that kind and level → raise the banner with the next squad», one squad to one rally, for as many repeats as asked. It uses the in-game magnifier the way a player does — the elite tab or the monster tab, a targeted search for the chosen level — rather than scanning whatever monsters happen to be on screen. It narrates each step, «Стоп» interrupts it, and it stops on its own when the day's «monster» cap (the auto-rally page) is spent. Driving the search is the working part; whether a target of the asked level actually comes back, and whether the banner then goes out, is not confirmed in a live game yet, so the tab warns as much
- ❌ Treasure notifications
- 🟡 Digging the treasure, collecting the treasure gift — the panel asks the server whether a chest is out, lists what came back with its place on the map, sends a chosen squad to join the dig, and takes the reward once the chest is dug. There are two ways it looks: it asks the server, and it watches the map itself, which is the only way a chest another alliance put out is ever seen — and the map is also what says the moment somebody finished the dig. The asking is confirmed against a live client (it correctly answers «nothing to dig»), and the map reading is confirmed against the one treasure that was ever recorded, down to the field that separates «being dug» from «dug». But no radar event has put a chest out since, so neither the dig nor the take has ever been carried through

### Radar assignments

- ❌ Collecting finished tasks
- ❌ Running the missions
- ❌ Saving tasks up for the alliance duel
- 🟡 The radar screen can be opened on command; nothing inside it is driven yet

### Events

- ❌ Alliance exercises
- ❌ Code Name
- ❌ Desert Storm
- ❌ Snow Storm
- 🟡 Street Run («Уличный забег», the three-lane endless runner) — the bot finds the open
  event, starts a run, runs it, writes down every distance and keeps a few attempts in
  reserve. **It no longer squints at the screen, and it no longer just reacts to whatever
  is nearest.** It sees the whole road about seven seconds ahead — every barrel, fence,
  parked carriage and driving truck, in which lane and how far — and picks a route through
  all of it: which lane to be in at which metre, when to hop, when to slide, and it takes a
  one-step detour for a shield or a jetpack on the way. It plays the run itself, without
  the game window needing to be in front, so the person can keep using the computer.
  When it picks up a jetpack it stops dodging altogether and just hoovers up coins, since
  nothing on the ground can touch it while it flies. It now also plans to go *over* a group
  of carriages instead of round it — up the ramp, along the roofs, hopping the gaps between
  them, and stepping off the end into whichever lane carries on — sideways as well as
  straight ahead — which is the way through the places the road is blocked in all three
  lanes. Stepping off sideways it now holds back until it is already falling off the end of
  the roof, the way a person does it — and while it is falling it no longer tries to cross
  over to the roof beside it. That crossing is what ended the last two runs: off the end of a
  roof it moved across onto what it took for the next one and was already in the air with
  nothing under it. The run after that fix came off a roof, held its lane the whole way down
  and landed safely — the first one to do so — though the sideways moves themselves are still
  unproven. What runs
  by itself: the whole
  start → run → revive → log loop. Measured live (2026-07-30): **720–1377 m on a single
  life**, against ~132 m for the older reflex version and ~88 m with no control at all;
  with revives, single attempts ran **1685 and 2700 m**; one run on 2026-08-02 went **976 m**
  on a single life, and six more the same day ran **1341, 1070, 288, 1062, 734 and 1100 m**.
  Left to the person: nothing during a run.
  Still open: the record 8185 m and the 20000 m target are not reached yet, the bot does not
  yet know about holes in the road — it reads one as a small thing to steer around rather
  than as ground it cannot land on.

### Arms Race

- ❌ Drone window, rally window, stamina window
- ❌ City, hero, technology and unit windows

### Alliance duel (VS)

- ❌ Opening drone chips
- ❌ Training the army
- ❌ Opening drone components
- ❌ Collecting duel gifts
- ❌ Collecting finished tasks on a duel day

### Base

- ✅ Collecting everything produced at the base — one sweep over every building that has something waiting, skipping the ones still producing
- 🟡 Collecting the base on a schedule — a switch and a period in the panel (an hour by default): once that long has passed since the last collection the sweep happens by itself, so the buildings do not sit full while nobody is looking. Same schedule as the alliance donation and gifts above, with the same clock kept per account; not yet run through a live session
- ❌ Researching technology
- ❌ Upgrading and constructing buildings
- ❌ Upgrading the drone
- ❌ Raising the shield
- ❌ Expedition
- ❌ Levelling survivors
- ✅ Upgrading a decoration — finds the decorations that can be upgraded by itself and presses each one, with no window opened: the building, its handbook and the decoration cell are all skipped. A step costs one spare duplicate of that same decoration and buys one point towards its next star, so it presses exactly as many times as there are spares and otherwise says there is nothing to do — the usual answer, since spare copies are rare. There is a companion reading that lists every decoration with the star score it stands at, the threshold it is climbing to, and how many steps its spares would buy
- ✅ Accepting a survivor waiting at the base — one press per waiting survivor, no window opened, and it stops on its own when nobody is left at the gate. Wants the base on screen, same as the gifts below: from the world map nobody is standing at the gate yet, so it quietly does nothing and the survivor keeps waiting
- ✅ Collecting gifts a survivor brought to the base — one press per gift-bearing visitor, no window opened, stopping on its own when nobody is left; a visitor still walking up to the base is left for the next round. Wants the base on screen: from the world map nobody is standing at the gate yet, so it quietly does nothing and the gifts keep waiting
- ❌ Assembling the treasure from map pieces
- ❌ Daily VIP gift and points
- ❌ Collecting mail rewards

### Resources

- ✅ Collecting the basic resources — iron, food, gold
- ✅ Collecting the extra resources — drone components, seasonal, ore and the rest. The base sweep covers every production line, not a fixed list
- 🟡 Collecting the resources from the truck parked at the base — one press takes the whole load at once, no window opens and there is no congratulation modal left to close; it does not need the base on screen. Not yet re-run in a live session
- 🟡 Sending squads out to gather on the map — the march goes out correctly, but the bot does not choose where to send it

### Secret missions

- ✅ Listing the secret tasks the game already knows about — own and alliance, instantly, without panning the map
- ✅ Finding raidable tasks on the map, with filters by level, star rank and whether a slot is actually free
- ✅ Sharing a task's coordinates in chat as a tappable pin
- 🟡 Spotting ghost-recon missions ("Операция Призрак") as they appear
- 🟡 Robbing a ghost-recon squad — one press per squad, no window opened, and it holds its fire unless it is the event day, the five-a-day budget still has room and the game itself says the squad can be robbed. Every one of those checks is confirmed against the live game (including that it does nothing at all while the event is closed), but the event runs one day a week and no real squad was on the map to rob, so the robbery itself is still unproven
- ✅ Robbing a secret task — the whole robbery runs without a window ever opening, five a day, and stops on its own at the daily cap. Targets come from a map scan or from coordinates handed to the bot
- ✅ Auto-loot from the panel — it robs starred tasks at the level its own «уровень до» asks for (the highest level found, when that field is empty), and does nothing at all when no star is raidable there. Both halves confirmed live: it held its fire with three stars still running their dispatch and 19 ordinary tiles raidable, then robbed the level-7 star the moment one came free
- 🟡 Auto-loot as a standing order — the panel's auto-loot is a checkbox, not a press: while it is ticked the panel watches the scan itself and robs the moment a star of the best level becomes raidable, so a target is no longer lost in the gap between the finding printing and a person noticing it. It sends a given task once, runs one robbery at a time, pauses for half an hour when the day's five are spent, and robs only at the level its own level row asks for — «от 1 до 7» takes level-7 stars and leaves a level-6 one alone, because the five daily attempts are the scarce thing and one spent on a 6 is one a 7 cannot have until the reset. That level row is its own now, separate from the level filter on the findings list: narrowing what is printed no longer quietly re-aims the robberies. The rule it applies is the proven one above; the automatic trigger itself has not yet run a live session
- 🟡 Panning the map by itself, so the scan has something to read — a checkbox walks the camera over a square of tiles around a point you choose, one hop at a time, and rests between passes; it says up front how many hops the square costs and how long a lap takes. That was the last manual thing left in the auto-loot: the scan only sees what the map shows while it is moving, and until now the moving was somebody's wrist. Nothing appears on screen while it works, and it stands aside whenever the bot is busy with anything else. Not yet run through a live session
- 🟡 Ghost-recon robbery as a standing order — the same checkbox idea, and it needs no map scan at all: the game already knows which squads are out, so while it is ticked the bot looks once a minute, robs everything the game says can be robbed, and stops at the five-a-day cap. Six days a week the event is closed and it does nothing but check in hourly. The robbery it makes is the one above, still unproven on a live squad
- 🟡 One screen for the whole Secret Command Post — a «Командный пункт» tab with a page for each of the three things behind it: the Ghost Operation squads (each shown with the game's own verdict on it, a «Ограбить» button only on the ones it calls robbable, and the five-a-day standing order living here now), the raids alliancemates share (nothing to poll — the page listens, a share appears the moment it is announced, and with one more tick it robs whatever matches the level rule as it lands), and the map treasures (ask the server whether there is one, and — since the chest is also an ordinary map point — scan the map for it as well, then dig it or take it). It is a place to see and press, not a new ability: every press behind it is one of the ones above, so what is proven stays proven and what is not — the ghost robbery, the treasure dig and take — is not
- ❌ Refreshing missions to UR — by tickets, diamonds or MEGA
- ❌ Sending own secret missions out
- ❌ Collecting own or alliance missions
- ❌ Setting up the map-piece exchange

> Star rank is the one thing the bot cannot read reliably — the game does not
> state it outright, so a starred task is worked out indirectly and the final
> call is still made by eye.

### Trucks

- 🟡 Collecting arrived trucks — see Resources
- ❌ Sending trucks out
- 🟡 Finding trucks worth robbing — the bot can list every truck on the map with its type, level, cargo and how many robberies it has left. Robbing one is not automated

### Store

- ❌ Daily diamond bonuses, weekly card
- ❌ Monthly card reward
- 🟡 The shop opens and switches between its tabs on command

### Promotions

- ❌ "Battle of Arsenals" rewards
- ❌ Battle Pass rewards and its daily missions

### Arena

- ❌ Apex arena
- ❌ 3-on-3 battle
- ❌ Free diamonds

### Heroes

- 🟡 Seeing your heroes in the panel — a tab lists every hero with its picture, level, star count and which squad (1/2/3) it stands in, sorted the way the in-game hero screen is. It reads them straight from the game with no window opened, and lazily, only when the tab is first opened; the reading has not been checked against a real roster yet, and the weapon column is left blank for later
- ❌ Free survivor and hero tickets
- ❌ Levelling heroes, raising their rank, levelling skills

### General

- ✅ Launching the game and waiting until the base is actually ready to be used
- 🟡 Noticing the game has gone and putting it back — the panel now checks the client every few seconds instead of only when asked, says so the moment it disappears, and (if asked to) starts it again on its own, no oftener than once every five minutes. Before this the panel could sit for an hour claiming the game was running while every scheduled errand quietly failed. Not yet seen through a real crash
- 🟡 Reacting to the "logged in from another device" screen — the reaction is written, but nothing watches for it yet
- 🟡 A summary of the account on one line — how many robberies are left today of each kind, how many donations are banked, how many alliancemates are waiting for help, how many wounded are lying in the hospital, how many survivors are at the gate, how many profession skills are ready, how many rallies can still be joined. Read straight out of the game every half a minute with no window opened, and quiet about everything that has nothing waiting, so what is on it is what needs doing. Not yet watched through a whole day
- 🟡 Building your own list of errands — the schedule is edited in the panel now: add an errand, give it its steps (any of the abilities above, or a command written out by hand), its period and its arguments, copy one, delete one. Two errands due at the same moment still take their turn rather than pressing at once, a failed one is retried whole, and the clock survives a restart. This is what "play the whole session" needs; nothing ships a ready-made routine yet
- 🟡 Firing any single named press by hand — a one-line command box under the log speaks the same vocabulary a saved errand does, with a list of every press beside it. Nothing new happens in the game; what changed is that all thirty-odd of them are reachable without writing a file first
- 🟡 Switching between the characters on one login — a panel tab lists every character this login can play, each with its server, zone, base level and name, highlights the one in play, and puts a one-press «Switch» beside every other one. A switch reconnects the client to that character, exactly what tapping the row in the game's own account screen does; it asks first, since it drops the current session. Reading the list is proven against the live game; the switch builds and sends the game's own reconnect, but a whole changeover has not been played through in a real session yet
- 🟡 Driving two accounts at once — which client a profile talks to is a setting now, so the profile switch moves everything: the presses, the captures and the robberies. Bringing the second client up is still a step outside the panel, and no live session has been played this way
- ❌ Pausing while the person at the keyboard is using the mouse. The screen-driven abilities need the game in front, so a person and the bot cannot share the computer during those
- ✅ Separate profiles per account — own settings, filters, logs and schedule — and an interface in Russian or English
- 🟡 A second account in parallel. Its client is started and kept in a second Windows session in the background — the bot brings the session, the client and its own control channel up by itself, and every ability that works without the screen can be pointed at either account. What cannot reach it is anything screen-driven: clicks and screenshots only ever land on the client in front. Not yet played through a real session on the second account
- ❌ A second account's client next to the first one *on the same screen*. Starting it as another Windows user works for any other program, but the anti-cheat kills the game a few seconds in

### Seasonal

- ❌ Donating coal to the alliance furnace

---

## Things the old script could not do at all

These are new. The old script only ever saw pixels; these abilities come from
the bot understanding what is actually going on in the game.

- ✅ Switching between the base and the world map instantly, without touching the screen
- ✅ Jumping to any coordinates — on your own server or another one — and viewing a foreign server's map
- ✅ Attacking or scouting a player's base, and reading the scouting report back automatically
- ✅ Reading chat — world, national, alliance and private messages — with the chat window closed, including emoji, stickers and photos
- ✅ Writing to chat — text, emoji, stickers, map pins and shared secret tasks
- ✅ Surveying the map: collecting a roster of players with their level, alliance and power; collecting rankings; indexing the trucks in motion
- 🟡 Attacking a monster on the map without clicking

---

## The daily routine, point by point

The routine as it is actually played, against what the bot covers.

### Repeating through the day

| | |
|---|---|
| Every 20 min — donate to alliance technology | ✅ · on a schedule 🟡 |
| Every 4 h — Arms Race objectives | ❌ |
| Every 4 h — send the second batch of trucks | ❌ |

### Every day

| | |
|---|---|
| Send 3 trucks, then 2 more | ❌ |
| Collect the base and the resource truck | ✅ base, on a schedule 🟡 · 🟡 truck |
| Send secret missions out | ❌ |
| Help with 5 UR or star secret tasks | ❌ |
| Steal 5 star tasks | 🟡 finding, picking the best star and robbing work; the map is panned on its own now, and the five are still not chained together |
| Radar tasks | ❌ |
| 20 rally joins per monster type | 🟡 joining works and a rally now announces itself and can be joined on the spot; counting and choosing do not |
| Attack marked players, scouting before and after | 🟡 attacking and scouting work, picking targets does not |
| Send squads to gather resources | 🟡 |
| Dig and collect treasures | 🟡 finding, digging and taking are built and on a panel page; no chest has been out to try them on |
| Fireworks | ❌ |
| Alliance gifts | ✅ · on a schedule 🟡 |
| Golden eggs and lucky gifts in chat | ❌ |
| Supplies, secret training, quests | ❌ |
| Arena | ❌ |
| Help alliancemates who ask | ✅ |
| Fire the profession skills that came off cooldown | 🟡 the no-target ones · ❌ the targeted ones |
| General's challenge, free heroes in the tavern | ❌ |
| Shop purchases from a list | ❌ |
| Treasure maps and the exchange | ❌ |

### By weekday, and the recurring events

Everything tied to a particular weekday — heroes, drone, T11, science, ghost
tasks, unit training, the Saturday shield — and every recurring event — Zombie
Invasion, Zombie Siege, alliance exercises, the storms, the train — is ❌. The
bot has no sense of the calendar and does not notice an event starting.

---

## What is needed before it can be left alone

1. **Something to run the whole session.** The list of errands is now built in the
   panel — several steps to one switch, its own period, its own arguments — so a
   morning routine is a matter of filling the list in rather than editing files by
   hand. What is still missing is the routine itself: nobody has written the daily
   list out, and nothing decides what to do next when the list runs dry. This
   remains the biggest gap versus the old script, but it is no longer blocked.
2. **More of the game's screens.** Mail, radar, events, the duel, arena, heroes,
   shop and the building queues are untouched; the hospital is only half done.
3. **Deciding, not just doing.** Attacking, gathering and rallying all work as
   actions, but nothing chooses targets or keeps daily counts.
4. **Seeing the map without driving it.** The moving is no longer a person's job —
   the bot walks the camera over a square around a chosen point by itself, without
   the game in front — but it is still *driving* the map: the scan learns tiles only
   from what the client asks the server for while it moves. A survey that costs the
   client nothing is not possible yet.
5. **Sharing the computer.** Anything that works through the screen needs the
   game focused, so the bot occupies the machine while it runs.
