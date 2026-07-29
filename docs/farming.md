# Farming — what the bot can do

> На русском: [`farming.ru.md`](farming.ru.md)

<!-- progress:start -->
🟩🟩🟩🟩🟩🟨🟨🟨🟨🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥  **25%** — 22 of 87

🟩 22 done · 🟨 18 partly · 🟥 47 not automated
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

The one thing the panel cannot do yet is **play a whole session on its own**: it
repeats a single chosen action, but nothing chains the routine together from
start to finish. Every ✅ below is still something a human starts.

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
- 🟡 Healing units — one press sends every wounded soldier type for treatment at once, no window opened, and it does nothing when nobody is hurt. The list of wounded it works from has now been read off a live game and matches what the hospital shows. What is still missing is one heal the game actually accepts: healing takes one of the base's building slots, and every attempt so far ran into a base with all of them busy, so the game refused. The run now says out loud when that was the reason
- 🟡 Collecting units from the hospital — the bot makes the "receive" press, and while a heal is still running it costs nothing, so it can be run on any schedule. Never yet seen bringing soldiers back, because no heal has been accepted to finish
- ❌ Asking for help with healing — there is nothing separate to ask for: starting a heal already puts the request in front of the alliance, and that is the same help the bot answers for others
- 🟡 Joining a rally — the bot can join or decline a live rally and pick which squad goes, but nothing decides *which* rallies to join or keeps count
- ❌ Starting a rally
- ❌ Treasure notifications
- ❌ Digging the treasure, collecting the treasure gift

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
  event, starts a run, dodges what comes at it, buys a revive with coins when it dies,
  writes down every distance and keeps a few attempts in reserve. **It no longer squints
  at the screen to see the obstacles** — it knows what is coming, in which lane, and how
  many seconds away, roughly five seconds ahead, so it steps into a lane that is genuinely
  clear, jumps a low barrel when there is no clear lane, and never jumps into a fence or a
  truck. What runs by itself: the whole start → dodge → revive → log loop. Proven live
  (2026-07-29): it read the track exactly and got past the opening trap to **~132 m on a
  single life**, against ~88 m with no control at all. Left to the person: nothing; the
  deaths that remain are traps that need a lane change planned two moves ahead rather than
  one, so the record 8185 m and the 20000 m target are still open.

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
- ❌ Researching technology
- ❌ Upgrading and constructing buildings
- ❌ Upgrading the drone
- ❌ Raising the shield
- ❌ Expedition
- ❌ Levelling survivors and decorations
- ✅ Accepting a survivor waiting at the base — one press per waiting survivor, no window opened, and it stops on its own when nobody is left at the gate
- 🟡 Collecting gifts a survivor brought to the base — the same press per gift-bearing visitor, no window opened, stopping on its own when nobody is left. Rebuilt from a recording of a person doing it by hand (the gift arrives as a coin chest); not yet confirmed in a live run
- ❌ Assembling the treasure from map pieces
- ❌ Daily VIP gift and points
- ❌ Collecting mail rewards

### Resources

- ✅ Collecting the basic resources — iron, food, gold
- ✅ Collecting the extra resources — drone components, seasonal, ore and the rest. The base sweep covers every production line, not a fixed list
- 🟡 Collecting the supply truck at the base — the mechanism works, but it has never been tried on a truck that was actually standing ready
- 🟡 Sending squads out to gather on the map — the march goes out correctly, but the bot does not choose where to send it

### Secret missions

- ✅ Listing the secret tasks the game already knows about — own and alliance, instantly, without panning the map
- ✅ Finding raidable tasks on the map, with filters by level, star rank and whether a slot is actually free
- ✅ Sharing a task's coordinates in chat as a tappable pin
- 🟡 Spotting ghost-recon missions ("Операция Призрак") as they appear
- 🟡 Robbing a ghost-recon squad — one press per squad, no window opened, and it holds its fire unless it is the event day, the five-a-day budget still has room and the game itself says the squad can be robbed. Every one of those checks is confirmed against the live game (including that it does nothing at all while the event is closed), but the event runs one day a week and no real squad was on the map to rob, so the robbery itself is still unproven
- ✅ Robbing a secret task — the whole robbery runs without a window ever opening, five a day, and stops on its own at the daily cap. Targets come from a map scan or from coordinates handed to the bot
- ✅ Auto-loot from the panel — it robs starred tasks at the level the «уровень до» filter asks for (the highest level found, when that field is empty), and does nothing at all when no star is raidable there. Both halves confirmed live: it held its fire with three stars still running their dispatch and 19 ordinary tiles raidable, then robbed the level-7 star the moment one came free. The scan it reads still needs the map to be moving
- 🟡 Auto-loot as a standing order — the panel's auto-loot is a checkbox, not a press: while it is ticked the panel watches the scan itself and robs the moment a star of the best level becomes raidable, so a target is no longer lost in the gap between the finding printing and a person noticing it. It sends a given task once, runs one robbery at a time, pauses for half an hour when the day's five are spent, and robs only at the level «уровень до» asks for — «от 1 до 7» takes level-7 stars and leaves a level-6 one alone, because the five daily attempts are the scarce thing and one spent on a 6 is one a 7 cannot have until the reset. The rule it applies is the proven one above; the automatic trigger itself has not yet run a live session
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

- ❌ Free survivor and hero tickets
- ❌ Levelling heroes, raising their rank, levelling skills

### General

- ✅ Launching the game and waiting until the base is actually ready to be used
- 🟡 Reacting to the "logged in from another device" screen — the reaction is written, but nothing watches for it yet
- ❌ Pausing while the person at the keyboard is using the mouse. The screen-driven abilities need the game in front, so a person and the bot cannot share the computer during those
- ✅ Separate profiles per account — own settings, filters and logs — and an interface in Russian or English
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
| Every 20 min — donate to alliance technology | ✅ |
| Every 4 h — Arms Race objectives | ❌ |
| Every 4 h — send the second batch of trucks | ❌ |

### Every day

| | |
|---|---|
| Send 3 trucks, then 2 more | ❌ |
| Collect the base and the resource truck | ✅ base · 🟡 truck |
| Send secret missions out | ❌ |
| Help with 5 UR or star secret tasks | ❌ |
| Steal 5 star tasks | 🟡 finding, picking the best star and robbing work; nothing chains the five together or pans the map on its own |
| Radar tasks | ❌ |
| 20 rally joins per monster type | 🟡 joining works, counting and choosing do not |
| Attack marked players, scouting before and after | 🟡 attacking and scouting work, picking targets does not |
| Send squads to gather resources | 🟡 |
| Dig and collect treasures | ❌ |
| Fireworks | ❌ |
| Alliance gifts | ✅ |
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

1. **Something to run the whole session.** Today the panel repeats one chosen
   ability; nobody plays the routine in order, retries a step that failed, or
   keeps to a schedule. This is the single biggest gap versus the old script.
2. **More of the game's screens.** Mail, radar, events, the duel, arena, heroes,
   shop and the building queues are untouched; the hospital is only half done.
3. **Deciding, not just doing.** Attacking, gathering and rallying all work as
   actions, but nothing chooses targets or keeps daily counts.
4. **Seeing the map without driving it.** Surveying the map still needs the game
   in front and the map being moved; a quiet, background survey is not possible yet.
5. **Sharing the computer.** Anything that works through the screen needs the
   game focused, so the bot occupies the machine while it runs.
