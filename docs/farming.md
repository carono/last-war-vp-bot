# Farming — what the bot can do

> На русском: [`farming.ru.md`](farming.ru.md)

<!-- progress:start -->
🟩🟩🟩🟩🟩🟩🟩🟩🟨🟨🟨🟨🟨🟨🟨🟨🟨🟥🟥🟥  **39%** — 81 of 206

🟩 81 done · 🟨 96 partly · 🟥 29 not automated
<!-- progress:end -->

A plain feature list: what is automated today, what is half-way there, and what is
still done by hand.

Most items are still ❌ — the rewrite went for depth first.

| Mark | Meaning |
|---|---|
| ✅ | works, confirmed in the live game |
| 🟡 | partly there — one step of the flow works, or it works but has not been proven in a real session |
| ❌ | not automated |

## How a run looks

Each ability is a separate named action you pick and run. Most of them never look
at the screen: they ask the game itself.

The panel's schedule runs the errands listed in it by itself, one at a time, and the
list belongs to the account.

The panel also keeps a **checklist** of the day, read out of the game rather than
ticked by hand.

What the panel cannot do yet is **play a whole session on its own**.

---

### Ministry

- ✅ Applying for a post — one press applies for any of the eight ministry posts; the queue and the holder's time are readable
- 🟡 Asking for Minister of the Interior on a schedule — a switch, and the bot applies every half hour by itself. Off until you turn it on
- ❌ Notification about an appointment
- ❌ Applying during the alliance duel

### Profession skills

The active skills of the profession the account picked (Engineer / Warlord). Each
is a banked charge on a 23.5-hour-plus cooldown.

- 🟡 Firing the skills that need no target — one press each for everything off cooldown, no window opened; a live run is not confirmed yet
- 🟡 Firing them on a schedule — a switch, and ready charges are spent unwatched. Off until you turn it on, and not yet watched through a live day
- ✅ «Win-Win Cooperation» — casts the one targeted skill on a War Leader the bot finds itself
- ❌ The other skills that need a target — helping an alliancemate's build or research, planting the siege banner

### Alliance support

- ✅ Collecting alliance gifts — claims both chests by the list, ordinary and premium, and says how many it took. No window opened
- ✅ Helping the alliance — a single press answers every pending request at once
- ✅ Answering help requests the second they arrive — a switch makes the same press by itself about two seconds after a request appears
- ✅ Donating to the alliance's priority technology — spends every attempt currently banked
- 🟡 Donating on a schedule — its own switch and its own period, every 20 minutes by default
- 🟡 Claiming the gifts on a schedule — its own switch and its own period, every 6 hours by default
- ✅ Healing units — one press sends every wounded soldier type for treatment, no window opened
- ✅ Collecting units from the hospital — takes the healed soldiers back and frees the hospital
- ✅ Asking for help with healing — one press puts the request in front of the alliance
- 🟡 Healing by portions, and the hospital kept working — you say how big a portion is, and the next batch goes in as the last is collected
- 🟡 Paying for the treatment out of the bag — the missing metal and food come out of your resource packs, if you let it
- ✅ Putting the soldiers back into a squad that looks empty — one press asks the game for the army that is standing in it
- 🟡 Joining a rally — joins or declines a live rally with the squads you name, one to each, skipping any it is already in
- ✅ Being told a rally has gone out, and joining it without hunting for it — the panel says so and rings once per rally; a button joins, a switch joins by itself
- 🟡 Starting a rally on a Fatal Elite or an ordinary monster — its own «Ралли» tab: pick the target, the level 1–200 and the squad
- 🟡 Raising one rally as an errand — the same run written as a scenario, so a schedule can be given it
- 🟡 Seeing the banners that are standing right now — «Ралли» draws every live rally: target, level, place, seats taken and who is in it
- ✅ Reading back who brought what to the rallies — one command turns every heard banner into a page of alliances, players and squads
- 🟡 Treasure notifications, and answering one on its own — with the switch on, the nearest free squad marches and the gift is taken as soon as it is dug
- 🟡 Digging the treasure, collecting the treasure gift — lists the chests that are out with their place, sends a squad and takes the reward

### Radar assignments

- ✅ Collecting finished tasks — one press empties the radar board and keeps going while it ripens
- ✅ Running the missions — the errands that need no march are set going at once and finished three seconds later
- ✅ The whole board on a clock — one press or one standing errand lays the errands out, sends the squads, runs the rest and takes the rewards
- 🟡 Saving tasks up for the alliance duel — finished tasks can be left standing all week and taken on the duel's radar day
- ✅ The errands that need a squad sent — one press puts each on the map and sends a free squad at it
- 🟡 The radar screen can be opened on command; nothing else inside it is driven

### Events

- ❌ Alliance exercises
- ✅ Codename — sends a squad at the boss and shows what the event still owes: attacks made of the three, and the biggest single hit
- ✅ Crystal Boss — makes the day's three attacks once a day, then takes all three chests: weekly damage, achievements and the day's own
- ✅ Golden zombies — one press hunts them one after another until the energy runs out or the number of kills you asked for is reached
- ✅ Golden zombies: the fast approach — the long haul is ridden on a gather order and only the last few tiles at attack speed
- ❌ Desert Storm
- ❌ Snow Storm
- 🟡 Street Run («Уличный забег», the three-lane endless runner) — the bot runs it by itself; it does not hold a distance past about 1000 m
- 🟡 Beneath the Ruins («Под руинами», the seasonal descent machine) — one press and the bot plays it round after round, about twice the depth of simply falling
- 🟡 Frontline Breakthrough («Прорыв обороны», the Sunday minigame) — one press plays it chain after chain and claims the three soldier boxes; stage 1 is cleared reliably, stage 2 once
- 🟡 …and it can be left to the weekly timer: a row that fires on the event's own day, by the game's clock. Ships switched off
- ✅ Alliance Star («Звезда альянса», the weekly ceremony) — one press likes every star of the week and takes both chests the likes pay. Nothing is spent

### Arms Race

- ✅ Reading the whole event in one go — the running phase, the score, what each of the three boxes costs, the time left and the week's plan of phases
- ✅ Taking the boxes — both ladders, the phase's three and the day's, claimed the moment the score has earned them
- ✅ The building phase and the technology phase — pours speed-up minutes into the queue with the most time left, cheapest kind first
- ✅ Hiring on the hero phase — the phase whose points come from the tavern. Live: one hire, 400 points.
- ✅ The drone phase — raises a rally per free squad for the points until the phase ends, waking on the game's own pushes
- 🟡 The unit phase — takes in every finished barracks and starts the biggest new batch each free one will take, under a ceiling in soldiers
- 🟡 The event on a schedule — one row that does whatever the phase pays for, claims the boxes and sleeps to the phase border. Off until you turn it on

### Alliance duel (VS)

- ✅ Opening the drone's chip chests — one press empties every chest of every grade the bag holds, in a single go
- 🟡 Spending the survivor tickets on a Tuesday — one press hires at the tavern with everything held, down to the reserve you asked to keep
- ✅ Opening the buildings that have finished — a page lists what is waiting with its picture and level, a button per row and one for all
- 🟡 Finishing a construction outright — the row says what closing it would take out of the bag before anything is pressed, and a button spends it
- 🟡 The score of the duel, on the page itself — your points and your place on the reward ladder, both alliances' points and their shares
- 🟡 Opening the drone's component chests on a Wednesday — one press empties every chest of every level the bag holds, in a single go
- ✅ The science centres, and what each one is studying — a row per queue with the technology, its level and its time left, finished ones first
- 🟡 Finishing a research outright — the row says what closing it would take out of the bag before anything is pressed, and a button spends it
- ❌ Training the army
- ❌ Opening drone components
- ❌ Collecting duel gifts
- ❌ Collecting finished tasks on a duel day

### Base

- ✅ Collecting everything produced at the base — one sweep over every building that has something waiting, skipping the ones still producing
- 🟡 Collecting the base on a schedule — a switch and a period in the panel, an hour by default
- ❌ Researching technology
- ❌ Upgrading and constructing buildings
- 🟡 Raising the drone's level — one press buys as many levels as the account can pay for, reading the price from the game each time
- ❌ Raising the shield
- ❌ Expedition
- ❌ Levelling survivors
- ✅ Upgrading a decoration — finds every decoration that can be upgraded and sends each to the top of what its spares will buy, no window opened
- ✅ Accepting a survivor waiting at the base — one press per waiting survivor, no window opened. Wants the base on screen
- ✅ Collecting gifts a survivor brought to the base — one press per gift-bearing visitor, no window opened. Wants the base on screen
- ❌ Assembling the treasure from map pieces
- 🟡 Collecting the two VIP rewards from the profile card — the daily points chest and the daily gift, both in one press with no window opened
- ❌ Collecting mail rewards

### Alert tower

- 🟡 The training run in the forbidden zone — one press claims the finished tasks, hands in what the rest ask for and starts the next run
- 🟡 The tower's own page — the stage, tasks waiting and running, starts left today, time left on the march and the boss's power beside the squad's
- 🟡 Working the tower on a schedule — a switch, and the routine runs unwatched, waking a minute after the game says the march ends. Off until you turn it on
- ❌ Fighting the tasks that want a battle, and challenging the tower's boss by hand — both are read and reported, neither is pressed
- ❌ Helping an alliance mate with a task of theirs

### Resources

- ✅ Collecting the basic resources — iron, food, gold
- ✅ Collecting the extra resources — drone components, seasonal, ore and the rest. The base sweep covers every production line, not a fixed list
- 🟡 Seeing what the base is holding, on the phone's «Профиль» page — every resource the account has any of, named as the game names it
- 🟡 Collecting the resources from the truck parked at the base — one press takes the whole load and closes the two modals the game puts up
- 🟡 Sending squads out to gather on the map — the march goes out correctly, but the bot does not choose where to send it
- 🟡 Seeing every mine on the map — a page listing every resource node the map watch has seen: place, yield, level, and whether it is taken
- ✅ Taking the day's free march energy — the free packet is taken before anything is spent
- ✅ Seeing what is in your bag — an «Инвентарь» tab draws every item the way the game draws it, with a search box that narrows the grid
- ✅ Taking the gift boxes from fireworks — the panel listens for the game's own announcement and claims each box
- 🟡 Handing out the free diamonds a surprise box drops — the packet is given away inside its hour; it costs the account nothing
- 🟡 Taking a share of somebody ELSE's packet of free diamonds — the chat message is heard and the share is claimed
- 🟡 Taking the gifts waiting in the Mail — presses «собрать всё» on every tab whose badge is above zero

### Secret missions

- ✅ Listing the secret tasks the game already knows about — own and alliance, instantly, without panning the map
- 🟡 Seeing what the alliance is running, on a page of its own — a row per alliancemate's task with its rank, finish time and how often it has been robbed
- 🟡 The five lists as pages, not one squeezed window — starred raids, the alliance's tasks, your Ghost squads, your alliancemates' and what a map sweep found
- 🟡 Seeing the Ghost Operation as three lists — where your three squads are and when each is back, and what the alliance has sent out
- ✅ Finding raidable tasks on the map, with filters by level, star rank and whether a slot is actually free
- ✅ Sharing a task's coordinates in chat as a tappable pin
- 🟡 Marking the tasks the alliance has already been shown — a badge on the coordinate on both lists, so the same raid is not forwarded twice
- ✅ A secret task you have robbed stays on the list, marked — a badge on the coordinate and the words beside the countdown
- ✅ «Собрать» appears ten seconds BEFORE the task is ready, so a finger can already be over it
- 🟡 Four more pages beside the raid lists — mines, monsters, alliance trains and player trucks, each a table with coordinates and its own details
- 🟡 Spotting ghost-recon missions ("Операция Призрак") as they appear
- ✅ Robbing a ghost-recon squad — one press per squad, no window opened, and the tile is re-asked of the game before anything is spent
- ✅ Robbing a secret task — without a window ever opening, five a day, stopping on its own at the daily cap
- ✅ Taking back what the secret tasks left behind — the day's pool behind «Вернуть» is claimed before it expires
- ✅ Auto-loot from the panel — one field aims it: the minimum level. It robs starred tasks at that level and above, best first
- 🟡 Auto-loot as a standing order — a checkbox: while it is ticked the panel robs as soon as a star at or above the level becomes raidable
- 🟡 Going round the warzones having their star day, every four hours — a timer that robs nothing, it only keeps the raid list filling
- ✅ Helping an alliancemate finish a secret task — five a day, without a window ever opening
- ✅ Auto-assist as a standing order — a checkbox with its own minimum-level field, beside the list it helps
- 🟡 Catching the star in the second it ripens — a star is taken by alliancemates in under two minutes, so the help has to be waiting for it
- 🟡 **Задание, которого больше нет, уходит из списка само** — a row no longer sits there saying «ready to rob» about empty ground
- 🟡 **Every tile the bot happens to hear now counts as a check** — each row says when the game last confirmed it, in words
- 🟡 «Обновить состояние» — re-checks the tasks already on the list, on demand only, and only the ones ready to rob
- ✅ One lap of the WHOLE map, in about three seconds — «Обойти карту» walks the camera over every corner of the server
- 🟡 Which warzones are having their star-secret-task day — three states beside the season, in the «Серверы» window and on the phone
- 🟡 «Куда идти сегодня» — a magnifier that opens a grid of the warzones a robbery is possible on today
- ✅ Ghost-recon robbery as a standing order — a checkbox with its own minimum-level field, on the «Призрак: карта» page
- 🟡 One screen for the whole Secret Command Post — a tab with a page each for the Ghost squads, your own missions and the day's pools
- ✅ Refreshing your own missions by a price rule, sending each UR the moment it falls, and putting every squad out — one order
- ✅ Collecting the finished missions and opening the boxes they pay out in — one press, and it comes first because a finished mission holds its squad
- 🟡 The whole day of secret missions on one switch — a timer row that wakes when the game says a mission ends, not on a period
- ❌ Collecting own or alliance missions
- 🟡 Swapping treasure-map pieces with the alliance — a page of its own and a card on the phone; the digs you have left are your scarcest piece
- ❌ Collecting the map-piece exchange rewards
- ✅ Opening the explorer's chests — one press opens every chest the keys will pay for
- ✅ Digging the hidden treasures until the week's 6000 compasses are earned

> Star rank is the one thing the bot cannot read reliably — the final call is
> still made by eye.

### Trucks

- 🟡 Collecting the trade trucks that came home — a truck cannot be sent out again until its load is taken, so the errand takes it first
- 🟡 Sending trucks out — one press collects, rotates the fleet to the rarity you asked for and sends as many as the day allows
- ✅ Taking back what the trucks left behind — the day's pool behind «Вернуть» is claimed before it expires
- 🟡 Counting the dispatches — the checklist says how many trucks have gone out today, how many the day allows and how many are ready
- 🟡 Finding trucks worth robbing — a page listing every truck on the map with its type, level, cargo, robberies left and where it is right now
- 🟡 Robbing other players' trade trucks — four a day, by a rule about which target is worth a fight
- 🟡 Watching the alliance train — a page with whose train it is, how full it is, where it is now, its next stop and when it arrives
- 🟡 Riding the alliance train — the bot hears the conductor being appointed and takes a seat inside the window before it leaves

### Daily quests

- ✅ Claiming the day's finished quests — every daily quest the game marks finished, then the list is re-read to see what actually arrived
- 🟡 Claiming the boxes on the day's progress bar — the five chests are taken one by one, so the log says which arrived

### Store

- ✅ Taking everything the shop gives for nothing, in one press with no window opened — week and month cards, and every free battle-pass level
- 🟡 Three more free claims the shop opens only on some days — the decoration shop's free spin, the recharge page's free reward and the camp's daily one
- ✅ Every shop the account has, on the phone, with the game's own pictures — the shelves are read out of the client without opening a window
- ✅ Buying one item by hand — press it on the shelf, answer «are you sure?», and the log names the item, the price and the limit left before anything is sent
- 🟡 Buying by an order of preference, on its own — behind each item's gear: buy it automatically or not, how many to own in all, and a ceiling
- 🟡 The storefronts that want real money are shown and never pressed
- ❌ Buying levels of a battle pass — a purchase, and it is never made
- 🟡 The shop opens and switches between its tabs on command

### Promotions

- ✅ «Glittering Market» — one errand takes the day's free reward and every item the market prices at nothing
- 🟡 Spending the market's coins — a second card, switched off: pick a row, how many and a ceiling, and the price is named before anything is sent
- ❌ "Battle of Arsenals" rewards
- ✅ Battle Pass rewards — the free track always, the premium one once unlocked, claimed with everything else the shop gives for nothing

### Arena

- ❌ Apex arena
- 🟡 3-on-3 battle — fights the matched opponent with the arena line-up until the day's five wins are in or its thirty challenges run out
- 🟡 Storm arena — takes the weakest of the five offered opponents that is not in our alliance and fights it, five times a day
- ❌ Storm arena: the promotion and choosing the line-up
- 🟡 The free diamonds both arenas pay for a LIKE — three likes a day on each, given to whoever stands first in the ladder

### Heroes

- 🟡 Seeing your heroes in the panel — a tab lists every hero with its picture, level, stars and squad, read with no window opened
- ✅ Spending only the FREE pull — the recruit run can be told «only if it is free» and sends nothing when the free pull has not come back
- ✅ Every free pull in the tavern on a clock — a timer takes the free survivor and the free hero on every banner the game is showing
- ❌ Levelling heroes, raising their rank, levelling skills

### General

- ✅ Launching the game and waiting until the base is actually ready — started in the Windows session the account really plays in
- ✅ Closing the client, and having start / close / restart in one place — each greys itself out when it would mean nothing
- 🟡 Noticing the game has gone and putting it back — checked every few seconds, and restarted by itself if asked, at most once every five minutes
- 🟡 Telling «the server is closed for maintenance» apart from «something is broken»
- 🟡 Telling «connected» from «merely running» — the panel says whether the account is actually online, not merely that the process exists
- 🟡 One light per account, on its own tab — the account that has stopped playing is visible without opening its page
- ✅ Restarting the client on a clock — every six hours, and nothing else runs until the base is back up
- ✅ Turning the picture down so the client stops loading the video card — a switch on the settings page, «Обычный» or «Упрощённый»
- 🟡 Keeping the picture down without being asked — a restart takes the mode away, so the panel puts it back
- 🟡 Reacting to the «logged in from another device» screen — read on every check, and answered by a wait rather than an instant restart
- 🟡 A summary of the account on one line — robberies left, donations banked, alliancemates waiting, wounded, survivors at the gate and skills ready
- 🟡 Building your own list of errands — add an errand, give it its steps, its period and its arguments, copy one, delete one
- 🟡 Firing any single named press by hand — a command box under the log, with a list of every press beside it
- 🟡 Sending a squad with a key — click a target on the map and press 1, 2, 3 or 4, with no window opened
- 🟡 Watching and driving it from a phone — a page on the home network with the link, what is running, what is due, and every errand's switch and «run now»
- 🟡 A strip along the top of every page on the phone — the character's name and HQ level, the warzone, and where in the game the player is standing
- 🟡 Seeing who this character IS, on the phone's «Профиль» page — name, HQ level, power, alliance, energy purse and registration day
- ✅ Seeing the characters on this account — a tab lists them with server, zone, base level, name, power and alliance tag, marking the one being played
- ✅ Switching to another character from the panel — one button moves the client onto that character in about ten seconds
- 🟡 Driving two accounts at once — which client a profile talks to is a setting, so switching the profile moves the presses, the captures and the robberies
- ❌ Pausing while the person at the keyboard is using the mouse
- ✅ Separate profiles per account — own settings, filters, logs and schedule — and an interface in eleven languages
- 🟡 A second account in parallel — its client lives in a second Windows session in the background, and any screenless ability can be aimed at either account
- ❌ A second account's client next to the first one *on the same screen* — the anti-cheat kills it
- 🟡 Asking the game about any warzone — when it opened and what day of the server it is on today, yours or anybody else's, without going there
- 🟡 The list of every warzone the game has — a grid with the number, name, kind, opening date and today's server day, searchable and sortable
- ✅ Closing the «here is what you were given» windows by itself, and keeping a record of them

### Seasonal

- ❌ Donating coal to the alliance furnace

---

## Things the old script could not do at all

These are new. The old script only ever saw pixels.

- ✅ Switching between the base and the world map instantly, without touching the screen
- ✅ Jumping to any coordinates — on your own server or another one — and viewing a foreign server's map
- ✅ Attacking or scouting a player's base, and reading the scouting report back automatically
- ✅ Reading chat — world, national, alliance and private — with the chat window closed, including emoji, stickers and photos
- ✅ Writing to chat — text, emoji, stickers, map pins and shared secret tasks. The chat page itself is **only in development mode** for now
- 🟡 Loading the chat history that was said BEFORE the panel was started — one press puts what the game still holds into the panel's own history
- 🟡 Reading the chat on a phone the way the game itself reads it — oldest at the top, newest at the bottom, the box to write in under them
- 🟡 Asking the game for chat older than anything the panel is still holding — a button fetches the next hundred messages from the server
- ✅ Surveying the map: collecting rankings, and indexing the trucks in motion
- ✅ A register of everyone the map has been driven past — name, base level, coordinates, server, alliance, and when each was first and last seen
- 🟡 The same register, filled by everything else the panel already sees — the chat, a rally banner, the alliance roster, a secret task's or a truck's owner
- ✅ Writing down the alliance duel (VS) — the whole week by day, both sides at once, every player's score
- 🟡 Attacking a monster on the map without clicking
- 🟡 Seeing the monsters on the map as a list — where each stands, its kind and its level, read out of the client itself
- ✅ A page that DRAWS the map instead of listing it — what the panel has gathered, beside the game's own picture of the same ground

---

## The daily routine, point by point

The routine as it is actually played, against what the bot covers.

### Repeating through the day

| | |
|---|---|
| Every 20 min — donate to alliance technology | ✅ · on a schedule 🟡 |
| Every 4 h — Arms Race objectives | 🟡 four phases of five run by themselves; the unit phase is read and left alone |
| Every 4 h — send the second batch of trucks | 🟡 one press, and it comes back by itself when the nearest truck is home |

### Every day

| | |
|---|---|
| Send 3 trucks, then 2 more | 🟡 rotated to the rarity you chose and sent up to the day's allowance |
| Collect the base and the resource truck | ✅ base, on a schedule 🟡 · 🟡 truck |
| Send secret missions out | ✅ refreshed by the price rule, each UR sent as it falls, every squad put out |
| Help with 5 UR or star secret tasks | ❌ |
| Steal 5 star tasks | 🟡 finding, picking and robbing work; the five are not chained together |
| Radar tasks | ✅ collecting, running the marchless ones and marching at the rest |
| 20 rally joins per monster type | 🟡 joining works and the day's total stops it; choosing which rallies are worth it does not |
| Attack marked players, scouting before and after | 🟡 attacking and scouting work, picking targets does not |
| Send squads to gather resources | 🟡 |
| Dig and collect treasures | 🟡 a chest is found three ways and answered on its own: squad out, gift taken once dug |
| Fireworks | ✅ boxes are taken by themselves; lighting one is still the person's |
| Alliance gifts | ✅ · on a schedule 🟡 |
| Golden eggs and lucky gifts in chat | 🟡 a share of somebody else's Lucky Gift · ❌ the golden eggs |
| Supplies, secret training, quests | ✅ the day's finished quests · 🟡 the progress-bar chests · ❌ supplies and secret training |
| Arena | 🟡 the 3-on-3 battles · 🟡 the storm arena · 🟡 the day's free likes on both · ❌ apex arena |
| Help alliancemates who ask | ✅ |
| Fire the profession skills that came off cooldown | 🟡 the no-target ones · ✅ Win-Win · ❌ the rest of the targeted ones |
| General's challenge, free heroes in the tavern | ❌ |
| Shop purchases from a list | 🟡 the shelves and buying one item by hand; the queue that spends by itself ships switched off |
| Free diamonds at the «Glittering Market» | ✅ the daily free reward and the zero-cost goods, on a schedule |
| Treasure maps and the exchange | ❌ |

### By weekday, and the recurring events

Everything tied to a particular weekday, and every recurring event, is ❌.

The one exception is the weekly hidden-treasure board above: it reads the week's
own opening and closing out of the game.

---

## What is needed before it can be left alone

1. **Something to run the whole session.** The list of errands is built in the
   panel; the daily routine itself is not written out yet.
2. **More of the game's screens.** Mail, radar, events, the duel, arena, heroes,
   shop and the building queues are untouched; the hospital is half done.
3. **Deciding, not just doing.** Nothing chooses targets or keeps daily counts.
4. **Seeing the map without driving it.** The scan learns tiles only from what the
   client asks the server for while it moves.
5. **Sharing the computer.** Anything that works through the screen needs the game
   focused.
