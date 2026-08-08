# Farming — what the bot can do

> На русском: [`farming.ru.md`](farming.ru.md)

<!-- progress:start -->
🟩🟩🟩🟩🟩🟩🟨🟨🟨🟨🟨🟨🟨🟥🟥🟥🟥🟥🟥🟥  **31%** — 40 of 127

🟩 40 done · 🟨 44 partly · 🟥 43 not automated
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
donating to the alliance's technology, claiming its gifts, each on its own. The
clock is kept per account and survives a restart, so an hour that ran out while
the panel was closed is worked off shortly after it opens. Two errands that come
due at the same moment never run at the same time: they queue and take their
turn, so the game is only ever being driven by one of them. Which errands the
schedule holds is a list you can edit — adding one, or changing what it does and
how often, needs no change to the program — and the list belongs to the account,
so two of them can be farmed on two different schedules.

The panel also keeps a **checklist** of the day: a board that says what is still
owed, read out of the game rather than ticked by hand. It shows one block at a
time, and only the blocks whose lines have been watched answering truthfully in a
live game — today that is «Codename» and nothing else. The rest of the day is
written down and switched off, and each block comes back once it has been checked
against a running game, the same way an ability earns its ✅ in this list. So a
feature below that mentions a row or a button on the checklist means it is built
and waiting for its block to be switched on; until then it is run from the tab
its theme belongs to, or from the schedule.

The one thing the panel cannot do yet is **play a whole session on its own**: it
repeats a chosen action and keeps a handful of abilities to their own clocks, but
nothing chains the routine together from start to finish. Every ✅ below that is
not on the schedule is still something a human starts.

---

### Ministry

- ✅ Applying for a post — one press asks for any of the eight ministry posts; the queue and how long the current holder has sat are readable too, so a script can decide when to ask. The daily checklist has «Apply for a ministry» with a button beside it, which asks for Secretary of Interior; whether the post was granted is not something the checklist can show, so the line stays «unknown» and the log carries the answer
- 🟡 Asking for Minister of the Interior on a schedule — one switch in the panel and every half hour the bot asks for the post by itself, with nobody watching. Only a post actually granted counts as done; an application the game turns down is asked again half an hour later instead of being written off as a run, so the panel's log tells a schedule that is working from one that has never once got in. A doomed application is never sent: while you hold another ministry post, and while the game's own half-hour wait between applications is still running, the bot asks for nothing — the game would refuse, and asking anyway only earns you a message on screen. The tab shows how the last attempt went and how long until the next one. Switched off until you turn it on; the refusals are proven live, a granted application on the schedule has not been seen yet
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

- ✅ Collecting alliance gifts — both ordinary and premium. The daily checklist has a button for it, though it cannot read how much is waiting, so the line beside the button stays «unknown»
- ✅ Helping the alliance — a single press answers every pending request at once
- ✅ Answering help requests the second they arrive — a panel checkbox («Авто-помощь союзникам») notices a new request by itself and makes that same press about two seconds later, so a request is answered while it is still worth points and nobody has to be watching. Proven live: five requests in a row answered right as they appeared. It also turned up why the press-on-demand version kept helping nobody, and that is fixed
- ✅ Donating to the alliance's priority technology — spends every attempt currently banked
- 🟡 Donating on a schedule — its own switch and its own period in the panel, every 20 minutes by default, which is the rate the game hands the attempts back at: once that long has passed the donation happens with nobody watching, so the attempts are spent instead of sitting banked until the day turns and takes them
- 🟡 Claiming the gifts on a schedule — a separate switch and a separate period, every 6 hours by default: nothing in the chest spoils while it waits, and this one opens a window in the game and closes it again, so looking oftener would cost the view for nothing. It used to share a switch and a clock with the donation above, which meant one period for two errands that want very different ones. For both: the clock belongs to the account and survives a restart, so a period that ran out while the panel was closed is worked off shortly after it opens; nothing fires while the game is not running, and a run that fails is retried instead of counted. The presses themselves are the proven ones above; the schedule has not yet run through a live session
- ✅ Healing units — one press sends every wounded soldier type for treatment at once, no window opened, and it does nothing when nobody is hurt. Proven live: 681 wounded went in on a single press. If the hospital is busy — a heal already running, or finished soldiers still waiting to be picked up — the game turns the press down, so collect first
- ✅ Collecting units from the hospital — takes the healed soldiers back and frees the hospital for the next heal. Costs nothing while a heal is still running, so it can be run on any schedule
- ✅ Asking for help with healing — one press puts the request in front of the alliance, and it is skipped when a request is already standing. Proven live: five alliancemates answered within seconds of the press. It also asks for the base's other working queues, but only the hospital is confirmed to register
- ✅ Putting the soldiers back into a squad that looks empty — a squad often reads «no soldiers» when the army is sitting in it the whole time and the bot has simply never asked; everything then refuses to send it anywhere. One press on the «Ралли» tab (and on the phone) asks about every squad that reads empty and puts the soldiers back — about a third of a second, nothing opened on screen. The rally join does it for itself when a banner is out and every squad looks empty, so nothing is missed while somebody presses a button. A squad that is still empty afterwards really is empty, and the log says exactly that instead of looking like a failure — then it is the barracks or the hospital, not the bot. Proven live: three squads reading empty, filled, and one of them sent into a live rally
- 🟡 Joining a rally — the bot can join or decline a live rally and pick which squad goes, and it can now be told «join with squads 2 and 3»: it reads the rallies that are out, sends each named squad to a different one, and skips any rally it is already in. Which rallies are worth joining is still nobody's decision, and no count is kept. Both halves are proven on live banners now: one run sent two squads to two different banners in a single press and both landed
- ✅ Being told a rally has gone out, and joining it without hunting for it — the moment one appears the panel says so and rings, once per rally rather than once per event; one button joins with the squads ticked right there on the «Ралли» tab, and a switch makes it join by itself as the alert lands — with the rally monitor off, if you like: the monitor only writes the armies down for later, and joining does not depend on it. It joins in one step and opens nothing on screen — two seconds from the alert to a squad standing in the rally, measured on live banners, where it used to walk the squad screen and take four. It goes for EVERY banner that is out at once rather than the first one, so two raised in the same minute cost one run. There is no screen left in it at all: the one case a message could not cover was a squad standing empty, and that turned out to be a squad the bot had simply never asked the game about — one question puts the soldiers back in a third of a second, and the join goes out on the next breath. Proven live on a real banner with all the squads reading empty: asked, filled, sent, and a squad of ours standing in the rally. And it only goes for THIS alliance's rallies: another alliance's cannot be joined at all, and every attempt at one came back as an error about the destination, which is what hid this for weeks. Proven live end to end, both ways: through the screens, and — since the destination was corrected, the troops gather at the base of whoever raised the banner rather than at the monster — in one step with nothing opened. Two things stay the person's: which rallies are worth joining, and the daily cap
- 🟡 Starting a rally on a Fatal Elite or an ordinary monster — its own «Ралли» tab: pick what to rally (a Fatal Elite or a world monster), set the level — 1 to 200 for both, since a season puts monsters far above the everyday range on the map: typed into the box, or one press on the button of a level rallied at most often (30, 35, 60, 120) — tick the squads that should each raise a rally, say how many times over, and «Запустить» runs «ask the game's own map search to bring up a target of that kind and level → raise the banner with the next squad», one squad to one rally, for as many repeats as asked. It uses the in-game magnifier the way a player does — the elite tab or the monster tab, a targeted search for the chosen level — rather than scanning whatever monsters happen to be on screen. Then it does what a player does: the target's window opens, it presses «Стягивание», waits for the squad screen, picks the squad there and launches. The flow was proven in a live game on a level-35 Fatal Elite — the banner went up on the map with the bot leading it — but the tab has since been rebuilt to raise its rallies exactly the way the errand below does, in one run, and THAT has not put a banner up in a live game yet. A repeat is only counted once the rally is actually standing, and when one comes to nothing the tab repeats what the run itself said: nothing of that level on the map, a target that cannot be rallied at all, the squad not being one the game knows, the press not bringing up the squad screen, the screen refusing that squad, or the launch leaving no banner behind. It narrates each step, «Стоп» interrupts it, and it stops on its own when the day's «monster» cap (the auto-rally page) is spent. The tab opens with the target, level, squads and repeat count it was last left with, so a repeat run is one press. Who to rally and when is still the person's call — the tab raises what it is told to
- 🟡 Raising one rally as an errand — the same «find a target of that level and raise the banner» run, written as a scenario: the scenario list on «Разработка» runs it, and a schedule can be given it. What it raises is filled in beside it — which squad raises the banner, what level, and whether to look for a Fatal Elite or an ordinary monster — so one errand covers every combination instead of a copy per level. One run raises one banner with one squad and says so. When nothing comes of it, it names the step — the map search turning up nothing of that level, the target being a solo one, the squad not being one the game knows, «Стягивание» not bringing up the squad screen, that screen refusing the squad, or the launch leaving no banner behind — and counts the run as a failure, so a schedule tries again instead of moving on as though a rally had gone out. It is also what the «Ралли» tab itself now runs, once per repeat, so the two are one flow with one set of words for what went wrong; neither has put a banner up in a live game since they became one
- ❌ Treasure notifications
- 🟡 Digging the treasure, collecting the treasure gift — the panel asks the server whether a chest is out, lists what came back with its place on the map, sends a chosen squad to join the dig, and takes the reward once the chest is dug. There are two ways it looks: it asks the server, and it watches the map itself, which is the only way a chest another alliance put out is ever seen — and the map is also what says the moment somebody finished the dig. The asking is confirmed against a live client (it correctly answers «nothing to dig»), and the map reading is confirmed against the one treasure that was ever recorded, down to the field that separates «being dug» from «dug». But no radar event has put a chest out since, so neither the dig nor the take has ever been carried through

### Radar assignments

- ❌ Collecting finished tasks
- ❌ Running the missions
- ❌ Saving tasks up for the alliance duel
- 🟡 The radar screen can be opened on command; nothing inside it is driven yet

### Events

- ❌ Alliance exercises
- ✅ Codename — the panel shows what the event owes and sends a squad at the boss. «События» keeps a block for it, and so does the checklist: how many attacks have gone out of the three that earn the reward, and the biggest single hit, which is what the daily ranking is made of. Both numbers are the game's own and are re-read, so an attack made in the game itself counts exactly as much as one the panel sent. «Атаковать сейчас» sends the first squad standing in the base — one attack a press, since the game rations no attempts and a fourth hit is still worth making for the ranking. On Sunday, the one day the event does not run, the block goes grey and the button dies rather than disappearing — «nothing to do today» must not look like «this panel has never heard of it». Both are confirmed against a live running event. The reading had been calling the event shut on every day of the week, because the game answers «shut» to a panel that has not asked it for the day's boss — it now asks. The attack is one press and no windows: the person's own route is five screens and a camera flight across the map, and all of it ends at one send, so the panel makes that send and the boss is hit from wherever the game happens to be. It proves itself by the count the game keeps, and a press that did not land says so instead of pretending. The biggest hit is drawn beside it but is a record, so it moves only when a hit beats the best one so far — the count is what says an attack happened
- ❌ Desert Storm
- ❌ Snow Storm
- 🟡 Street Run («Уличный забег», the three-lane endless runner) — the bot runs it by
  itself; it does not hold a distance past about 1000 m.

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
- 🟡 Collecting the base on a schedule — a switch and a period in the panel (an hour by default): once that long has passed since the last collection the sweep happens by itself, so the buildings do not sit full while nobody is looking. Same schedule as the alliance donation and the gifts above, each errand with its own period and the clock kept per account; not yet run through a live session
- ❌ Researching technology
- ❌ Upgrading and constructing buildings
- ❌ Upgrading the drone
- ❌ Raising the shield
- ❌ Expedition
- ❌ Levelling survivors
- ✅ Upgrading a decoration — finds the decorations that can be upgraded by itself and presses each one, with no window opened: the building, its handbook and the decoration cell are all skipped. A step costs one spare duplicate of that same decoration and buys one point towards its next star, so it presses exactly as many times as there are spares and otherwise says there is nothing to do — the usual answer, since spare copies are rare. There is a companion reading that lists every decoration with the star score it stands at, the threshold it is climbing to, and how many steps its spares would buy
- ✅ Accepting a survivor waiting at the base — one press per waiting survivor, no window opened, and it stops on its own when nobody is left at the gate. Wants the base on screen, same as the gifts below: from the world map nobody is standing at the gate yet, so the run reports that it could not be done — and on a schedule it is tried again a few minutes later, instead of counting as done and leaving the survivor at the gate for another whole hour
- ✅ Collecting gifts a survivor brought to the base — one press per gift-bearing visitor, no window opened, stopping on its own when nobody is left; a visitor still walking up to the base is left for the next round. Wants the base on screen: from the world map nobody is standing at the gate yet, so the run reports that it could not be done and, on a schedule, comes back to it a few minutes later rather than waiting out the full period
- ❌ Assembling the treasure from map pieces
- ❌ Daily VIP gift and points
- ❌ Collecting mail rewards

### Resources

- ✅ Collecting the basic resources — iron, food, gold
- ✅ Collecting the extra resources — drone components, seasonal, ore and the rest. The base sweep covers every production line, not a fixed list
- 🟡 Collecting the resources from the truck parked at the base — one press takes the whole load at once, no window opens and there is no congratulation modal left to close; it does not need the base on screen. The daily checklist has a button for it; how much the truck is holding cannot be read, so the line beside the button stays «unknown». Run live from that button: the presses go out, the game turns none of them down and no window is left open behind it — but whether the truck had a load to give was not visible, so this stays short of proven until one run is watched with the balance before and after
- 🟡 Sending squads out to gather on the map — the march goes out correctly, but the bot does not choose where to send it
- 🟡 Seeing every mine on the map — a page of its own listing every resource node the map watch has seen: where it is, what it yields, its level, and whether somebody is already gathering it. The taken ones are kept out of the way unless you ask for them, and the level range narrows the rest. It is filled by the same three-second lap of the map that finds the raids, so it costs no extra pass and no second watcher; a click on a coordinate walks the camera to the tile. Marching a squad to one is still done by hand. The reading was rebuilt from a recorded lap of a real server — nine thousand mines, three kinds, free and taken told apart — but it has not been watched filling up live

### Secret missions

- ✅ Listing the secret tasks the game already knows about — own and alliance, instantly, without panning the map
- 🟡 Seeing what the alliance is running, on a page of its own — one row per task an alliancemate has out, with their name on it, its rank, when it finishes and how many times it has already been robbed. Nothing is left out of the reading: the plain tiles as well as the starred ones, the ones already picked clean, and the odd one-per-player task, which is named rather than dressed up as a level. Two boxes narrow what the eye gets instead — the top rarity only, and the starred only — and they hide rows without changing a single robbery. Same countdown, same colours and the same click on a coordinate that walks the camera there as the raid list. It is redrawn whole every time it is read, so a task that has ended is simply not in it, and the phone shows the same lists as cards. Read live off a real alliance — 200 tasks from 52 members, every one with a name — but not yet lived with through a real session
- 🟡 The five lists as pages, not one squeezed window — the starred raids, the alliance's own tasks, your Ghost Operation squads, your alliancemates' and what a map sweep found each get a page of the «Секретки» tab, and one strip of buttons follows whichever page is in front, so «Собрать» is never aimed at a row nobody can see. Each page carries its OWN controls: its own level range, its own filters and its own sniffer switch, so watching the ghost tiles no longer stops the secret-task capture and narrowing one list no longer narrows another. And a watcher only FILLS these lists: what it finds stays on the table afterwards, kept across a restart and taken off only when its own clock runs out or somebody robs it — a find no longer disappears half an hour later merely because nobody has driven the map past it since. A row that has not been re-seen for a while says how old it is instead of vanishing. The countdowns move four times a second rather than once, so a tile you are waiting on is never a second behind the game's own clock — it is the drawing that got faster, not the asking: nothing on that page costs the client a question. And a tile the map sent with no finish time on it never reaches the list at all: it could never mature, never be robbed and never expire, and all it did was sit there showing a dash where a countdown belongs. The phone's copy of a page now keeps up too — it used to be drawn once when opened and then stay exactly as it was for as long as anybody read it. The phone gets the same split — each card has the buttons of the page it mirrors. The raid page keeps the tiles on your own server out of the way unless you ask for them — the raids worth a march are the ones abroad — and says how many it is holding back, so a short list is never mistaken for a tab that read nothing
- 🟡 Seeing the Ghost Operation as three lists — where your own three squads are and when each is back, and, separately, what everyone in the alliance has sent out: who sent it, its rank, where it landed, when it returns, how many times the tile has been robbed and the game's own word on whether it can be robbed at all. The alliance list is the one the game's own window draws, so it holds exactly what a player sees on screen — everything at once, not a handful — and it is read out of the client rather than asked for: while the listener is on, each announcement the alliance makes redraws it by itself. The header says whether the event is on today and how many of the five robberies are left. What a squad IS — its level, whether it is a star, and how many times its tile may be robbed — is taken from the event's own table rather than worked out from the id, which is the mistake that invented a star and a «level 99» on the other robbery. Empty dispatch slots of your own are not drawn as targets, and your own squads say what they are doing instead of pretending to be somebody to rob. The third list is the map sweep's own: the client is never told about OTHER alliances' squads, so a lap of the map is the only way to see the tiles a robbery is actually aimed at — and it now reaches a table again, after a spell where the capture was started without anywhere to write and a whole lap produced nothing but log lines. Robbing stays on the «Командный пункт» tab, which is **only in development mode** for now. Read live with the event open — my own squads with their countdowns, and the alliance list matching the game's own window row for row (thirteen of them at the time) — but not yet lived with through a whole event day. How many times a tile has already been robbed is not in the alliance's own list, so that column is left blank there rather than filled with a guess
- ✅ Finding raidable tasks on the map, with filters by level, star rank and whether a slot is actually free
- ✅ Sharing a task's coordinates in chat as a tappable pin
- 🟡 Marking the tasks the alliance has already been shown — on both lists, with a badge on the coordinate and the words beside the countdown, so the same raid is not forwarded to the same people twice. It counts a share made from the panel and a share pressed in the game itself, by this player or by an alliancemate: the game announces every one of them to the alliance, and the panel hears it while either the map monitor or the star auto-loot is running, so a tile shared from the game window is marked here without anybody telling the panel about it. The marks belong to the account, survive a restart, disappear on their own once the tile is long gone, and the phone shows them exactly as the window does. Not yet seen against a live share
- ✅ A secret task you have robbed stays on the list, marked — a badge on the coordinate and the words beside the countdown, the same shape the share mark has. It used to disappear the moment the robbery landed, and it took with it the one thing still worth having: a raid worth one of the day's five is exactly the raid worth telling the alliance about, and «Поделиться» has to be pressed on a row. What the marked row no longer offers is «Собрать» — there is nothing left there for you to take, and the game would refuse a second robbery anyway — while the jump to its coordinate and both ways of sharing it stay where they were. It leaves the list on its own clock, when the task expires, and the standing order never counts it as a target. The phone shows the mark exactly as the window does.
- ✅ «Собрать» appears ten seconds BEFORE the task is ready, so a finger can already be over it — a good target is taken in the first moment it exists and the race is decided far faster than a button appearing at the exact instant can be answered. Pressing inside those ten seconds does not throw a robbery at the server early: the press is held and sent at the moment the task matures, which is what a hand cannot do. The automatic looting gets a window of its own — two seconds, not ten — and inside it presses again and again, about seven times a second, until the server answers. Three answers are possible and it tells them apart: «taken» stops it and keeps the tile for sharing; «уже взято» / «больше не доступно» / «срок истёк» stops it too and takes the row OFF the list, because that is the server saying the tile is not there any more; anything else leaves it pressing. Before that it heard only the first of the three and would ask a vanished tile sixty times running. Nothing is spent on the presses that come back «not ready yet»: the daily five only move when a robbery actually lands, and the bot believes nothing else — a message leaving the client is not a robbery, the server's answer is. The two windows are different on purpose: ten seconds is what a hand needs to get onto a button, and ten seconds of a machine pressing is seventy questions a tile cannot answer yet. The phone says the same tile is about to open at the same instant the button appears, though the robbery itself is still made from the window
- 🟡 Four more pages beside the raid lists — mines, monsters, alliance trains and player trucks, each its own table with coordinates and its own details, and the same manners as the lists next to them: a count of what is shown and what is hidden, a live countdown where there is something to count down to, a click on a coordinate that takes the camera to the tile, and a list that is only ever FILLED by the watch rather than emptied by it. Three of the four are fed by the very same watcher that finds the raids — nothing new is started and nothing else is slowed down, which matters more than it sounds: a second watcher on the same connection gets a trickle and looks exactly like a game that has gone quiet. Nine thousand mines will not fit on a screen, so a page draws the best five hundred and SAYS how many it is holding back. The phone gets the same four as cards. Nothing on these pages presses anything: gathering, attacking and robbing are all marches, and none of them is an ability the bot has yet
- 🟡 Spotting ghost-recon missions ("Операция Призрак") as they appear
- 🟡 Robbing a ghost-recon squad — one press per squad, no window opened, and it holds its fire unless it is the event day, the five-a-day budget still has room and the game itself says the squad can be robbed. Every one of those checks is confirmed against the live game (including that it does nothing at all while the event is closed), but the event runs one day a week and no real squad was on the map to rob, so the robbery itself is still unproven
- ✅ Robbing a secret task — the whole robbery runs without a window ever opening, five a day, and stops on its own at the daily cap. Targets come from a map scan or from coordinates handed to the bot
- ✅ Auto-loot from the panel — one field aims it: the minimum level. It robs starred tasks at that level and every level above it, the best one first, and does nothing at all when no star up there is raidable. Both halves confirmed live: it held its fire with three stars still running their dispatch and 19 ordinary tiles raidable, then robbed the level-7 star the moment one came free
- 🟡 Auto-loot as a standing order — the panel's auto-loot is a checkbox, not a press: while it is ticked the panel watches its own list of raids and robs as soon as a star at or above the level asked for becomes raidable, so a target is no longer lost in the gap between the finding printing and a person noticing it. What it weighs is the list on screen — the one the map watch, the client's own tables and the alliance's announcements all fill and the panel keeps re-checking against the game — so what gets robbed is what you are looking at; there is no second reading of the map to disagree with it. One field sets the rule, and it is a floor rather than a range: a raidable level-6 star used to be left alone for ever under «от 1 до 7», because only the top of that range was ever taken, and now it is robbed too once the floor is 6. It sends a given task once, runs one robbery at a time, and pauses for half an hour when the day's five are spent. The level it robs at stays separate from the level filter on the list: narrowing what is shown re-aims no robbery. The rule it applies is the proven one above; the automatic trigger itself has not yet run a live session
- ✅ Helping an alliancemate finish a secret task — five a day, the whole thing without a window ever opening, and it is a different thing from «Помочь всем»: that answers building requests and is unlimited, this one takes one of the day's five and is what the daily plan means by «помочь выполнить 5 секретных заданий ранга UR или Звезда». It picks out of the alliance's own finished tasks, best first, and never below the level you asked for. It re-reads the alliance's list from the server before it chooses, and that is not a nicety: the game only tells the client that somebody else has already helped when it is listening, so a bot working off yesterday's list gets «спасибо, задача уже решена» and spends nothing while looking exactly like a bot that did nothing at all. Proven live: one run took the day's counter from one to five of five and stopped there by itself
- 🟡 Auto-assist as a standing order — a checkbox on the alliance page of «Секретки», beside the list it helps, with a minimum-level field of its own. While it is ticked the panel looks in every few minutes and helps whatever UR or starred task at that level and above has just finished, one run at a time, and waits out the rest of the day once the five are gone. Its level is its own number and not the robbery's: helping pays the owner as well as the helper, so there is nothing to keep abroad. The help it makes is the proven one above; the automatic trigger itself has not yet run through a live session
- ✅ «Обновить состояние» — a button beside «Обойти карту» that re-checks the tasks ALREADY on the list rather than looking for new ones: how many times each has been robbed, whether the tile is still there at all, when it expires. The ready ones are asked about first, because their state is the one that lives seconds — a task is raidable only until the first person reaches it, and those were the rows showing «готово к сбору» about something already emptied. A task the server says is not there comes off the list; a task nothing answered about STAYS, and the line says how many of each — the bot never throws away a find because its own connection went quiet. The phone has the same button, and the same one press it has always been allowed to make: this reads, it does not rob
- ✅ One lap of the WHOLE map, in about three seconds — «Обойти карту», beside the coordinate boxes on the «Секретки» tab. It walks the camera over every corner of the server and everything the game answers with lands in whatever the monitor is writing down: on a live run that was six hundred secret tasks and two hundred Ghost Operation tiles from one press. Beside it is «Зум», which decides what the lap and every jump from this tab are FOR — one tile to look at, the height at which secret tasks still arrive, or the widest one the game will still send anything at (four times the ground, bases and mines, no tasks). The phone has the same two. Proven from the panel itself: one press swept the whole server and the watcher wrote down 598 secret tasks and 33 starred ones; the same press on the widest setting brought in 56 000 more tiles and not one further task, which is exactly what that setting is for
- 🟡 Ghost-recon robbery as a standing order — the same checkbox idea, with a minimum-level field of its own: while it is ticked the bot looks once a minute and takes the squads at that level and above, best first, stopping at the five-a-day cap. It needs no map scan of its own — the game already knows which squads are out — and it chooses out of the page's own list, the one the client's list and a map sweep between them fill, so «Ограбить всё» by hand and the standing order take exactly the same squads. Its level is its own number, not the secret tasks': a squad runs levels 3-5 where a secret task runs 1-7. Six days a week the event is closed and it does nothing but check in hourly. The robbery it makes is the one above, still unproven on a live squad
- 🟡 One screen for the whole Secret Command Post — a «Командный пункт» tab with a page for each of the three things behind it: the Ghost Operation squads (each shown with the game's own verdict on it, a «Ограбить» button only on the ones it calls robbable, and the five-a-day standing order living here now, with the minimum level it takes from written out beside its checkbox), the raids alliancemates share (nothing to poll — the page listens, a share appears the moment it is announced, and with one more tick it robs whatever matches the level rule as it lands), and the map treasures (ask the server whether there is one, and — since the chest is also an ordinary map point — scan the map for it as well, then dig it or take it). The rule the shared raids are judged by and the squad that digs are kept between sessions, so the tab opens set up the way it was left. It is a place to see and press, not a new ability: every press behind it is one of the ones above, so what is proven stays proven and what is not — the ghost robbery, the treasure dig and take — is not. **Development mode only for now:** this part of the panel is still being worked on, so an ordinary panel does not show it — switch «Разработка» on in the tab list to get it and everything on it back
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
- 🟡 Counting the dispatches — the checklist says how many trade trucks have gone out today, how many the day allows and how many are standing ready to go, and the number moves by itself as trucks leave. Sending them is still done by hand
- 🟡 Finding trucks worth robbing — the bot can list every truck on the map with its type, level, cargo and how many robberies it has left, and there is now a page for them in the panel: where each one is right now, how big the load is, how many times it has been robbed and how long is left of its run, the fattest first. Robbing one is not automated
- 🟡 Watching the alliance train — a page of its own: whose train it is, how many carriages it has and how many people are aboard, how full it still is and when it arrives. It only runs during its event, so the page is empty most of the week and says so. Rebuilt from a recording; not yet watched during a live train

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

- 🟡 Seeing your heroes in the panel — a tab lists every hero with its picture, level, star count and which squad (1/2/3) it stands in, sorted the way the in-game hero screen is. It reads them straight from the game with no window opened, and lazily, only when the tab is first opened; the reading has not been checked against a real roster yet, and the weapon column is left blank for later. **Development mode only for now:** the page is still being worked on, so an ordinary panel does not show it — switch «Разработка» on in the tab list to get it back
- ❌ Free survivor and hero tickets
- ❌ Levelling heroes, raising their rank, levelling skills

### General

- ✅ Launching the game and waiting until the base is actually ready to be used — and it starts it where the account actually plays: an account running in its own Windows session in the background has its client started inside that session, not put on the screen in front of whoever is at the keyboard
- ✅ Closing the client, and having all three of start / close / restart in one place — the panel and the phone both show «Запустить игру», «Закрыть игру» and «Перезапустить игру» side by side, and each of them greys itself out when it would mean nothing: there is nothing to close when no client is running, and nothing to start when one already is. Closing used to be the one of the three the panel could not do at all — the Task Manager was the way — and it matters most for the account playing in a background Windows session, whose client is not on anybody's screen to close. It closes the client of the account named and no other, which on a machine farming two is the whole difficulty: the older restart button ended both at once, mid-farm, because it named the program rather than the account. Nothing in the game is spent by any of it and the session comes back on the same base. Proven live on the background account, from a phone: closed in four seconds, started again in six, restarted in eleven — and a press that arrives while the bot is busy waits to be told so rather than cutting in
- 🟡 Noticing the game has gone and putting it back — the panel now checks the client every few seconds instead of only when asked, says so the moment it disappears, and (if asked to) starts it again on its own, no oftener than once every five minutes. Before this the panel could sit for an hour claiming the game was running while every scheduled errand quietly failed. Not yet seen through a real crash
- 🟡 Telling «connected» from «merely running» — the panel and the phone now say whether the account is actually online, not merely whether the game's process exists. A client that has lost the server keeps its window, its process and every number it read yesterday, so the old green «работает» sat over an account that had done nothing since the small hours and every errand reported success. Green now means an open line to the game server, red means the server has hung up and the client has not noticed, and amber means it cannot be told yet — a client that is still coming up has no line to look at, and that is not a fault. It answers per account, so the one playing in a background Windows session gets its own verdict rather than the other one's. The moment the line goes, and the moment it comes back, goes into the log with a time on it, so the morning after says how long it was out. Proven on a real hang-up read through the shipped code path, and on both live clients; not yet caught against the game server dropping an account of its own accord
- ✅ Restarting the client on a clock — every six hours the game is closed and started again, and nothing else runs until the base is back up. A session left running all day gets slower and answers less, and this is the cure; nothing in the game is spent by it. It waits its turn rather than cutting in: whatever the bot is doing at that moment finishes first, and nothing is pressed while the client is coming up. It only counts as done once the base is in play again and the panel can drive it — a client that came back to a loading screen is tried again later instead of being written off as a restart that worked. Switched off until it is asked for. The client this account plays is the one closed, so the other account's game is left alone — including when this account's own client lives in a background Windows session, which is ended and started there rather than here. Proven live: closed, relaunched and back at the base in 45 seconds, with everything that talks to the game following it into its new process by itself
- ✅ Turning the picture down so the client stops loading the video card — a switch on the settings page, «Обычный» or «Упрощённый»: on simplified the game draws ten frames a second at its lowest quality in a 640×480 window, which takes it from about a quarter of the video card down to a fraction of a percent, and slows nothing the bot does. Nobody has to look at that picture — the bot reads the game rather than watching it. It takes effect the moment you press it, and it belongs to the account, so the one playing in the background can be economising while the one you are watching is not. Switching back gives you the picture YOU had, not a guess: it reads and remembers your settings before it changes them, which matters because the size you ask for is only a request and the game may seat it differently. Beside the switch is what the client is really drawing right now, asked of the game itself rather than taken on trust. Hiding the window instead does not work and never did: a game that is minimised, covered by another window, or running where there is no screen at all draws exactly as many frames as one you are looking at, and costs the card MORE, not less. Proven live on both clients, there and back
- 🟡 Keeping the picture down without being asked — restarting the game takes half the mode away, and leaves the misleading half: the small window comes back on its own while the frame rate and the quality go back to full, so a client that crashed LOOKS economised and is not. The panel spots exactly that and says the game has restarted and the mode wants pressing again — but it will not press it for you. Giving the errand «set_graphics_load» a period in the schedule covers it, and nothing sets that up for you yet
- 🟡 Reacting to the "logged in from another device" screen — the panel reads that screen on every check, whatever the connection looks like, and a kicked account is no longer answered by a restart thirty seconds later. It waits fifteen minutes first — a field on the settings page, 0 for the old behaviour — and says in the log and on the phone how long is left. Being kicked means somebody is playing the account: taking it straight back throws them out, their device takes it back again, and the two go round while nothing gets farmed. Nothing touches the client during the wait — not the crash watchdog, not the self-restart, not the six-hourly one — and afterwards everything proceeds as usual. Not yet lived through a real kick
- 🟡 A summary of the account on one line — how many robberies are left today of each kind, how many donations are banked, how many alliancemates are waiting for help, how many wounded are lying in the hospital, how many survivors are at the gate, how many profession skills are ready, how many rallies can still be joined. Read straight out of the game every half a minute with no window opened, and quiet about everything that has nothing waiting, so what is on it is what needs doing. Not yet watched through a whole day
- 🟡 Building your own list of errands — the schedule is edited in the panel now: add an errand, give it its steps (any of the abilities above, or a command written out by hand), its period and its arguments, copy one, delete one. Two errands due at the same moment still take their turn rather than pressing at once, a failed one is retried whole, and the clock survives a restart. This is what "play the whole session" needs; nothing ships a ready-made routine yet
- 🟡 Firing any single named press by hand — a one-line command box under the log speaks the same vocabulary a saved errand does, with a list of every press beside it. Nothing new happens in the game; what changed is that all thirty-odd of them are reachable without writing a file first
- 🟡 Sending a squad with a key — click a target in the game, and the number keys 1 to 4 send that squad at it instead of picking one with the mouse; CapsLock sends the same squad at the same target again, with nothing on screen at all. The keys do something only while the game is the window in front, and the digits still type normally everywhere else — CapsLock is the only key taken away, and only while the game has focus. Every press leaves a line: which squad, which target, and what the game answered, refusals included — nothing was chosen, there is no such squad, the squad is still out on the last march. Proven live on two kinds of target and on the repeat; not yet lived with through a session. A rally banner is deliberately not repeated — it is raised through its own screen, and re-raising one is not what «the same march again» is for
- 🟡 Watching and driving it from a phone — the panel puts a page on the home network and a phone opens it: whether the account is really on the line, what the panel is doing this second, what is due next, every errand with its switch and a «run now», every ability with one press each, the client itself to start, close or restart, and the log with the failures picked out of it and a notification the moment one appears. What the tabs read is on it too — resources, heroes, inventory, the alliance, the chat, the rallies and where the squads are, the starred secret tiles with their countdowns, today's duel plan — each behind its own «Обновить», so nothing is asked of the game until somebody actually looks. Some of those readings — the heroes, the inventory, the profile, the alliance roster, the chat, the gains tally and the duel plan — are **only in development mode** for now: their pages are still being worked on, so a phone does not show them either unless «Разработка» is switched on. Both accounts are on the same page and it says which one it is showing, so a press lands on the client of the account named rather than on the other one's. It is off until switched on, opened with a link that carries its own key, and encrypted only if you give it a certificate of your own; from outside the house it needs the port forwarded on the router. Drawn for a thumb and measured on real phone browsers rather than assumed to fit. Proven from a phone on the same network — the page answered and so did its readings; not yet lived with through a whole day, and nothing on it can be edited: it watches and presses, it does not configure
- ✅ Seeing the characters on this account — a panel tab lists them with the server each one is on, its zone, base level, name, power and alliance tag, and marks the one being played. The list is the account's own: it is asked of the game's servers, the same way the in-game «Characters» screen asks, and it arrives without that screen being opened, so what the tab shows is what the game shows — two characters where the tab used to draw six. Proven against a live session. **Development mode only for now:** the page is still being worked on, so an ordinary panel does not show it — switch «Разработка» on in the tab list to get it back
- ✅ Switching to another character from the panel — the «Switch» button beside a row moves the client onto that character: the game logs out and comes back on the other base about ten seconds later, exactly as tapping the character in the game does. Nothing has to be typed and no screen is opened. It refuses out loud instead of doing nothing when there is no character on that server, or when it is the one already being played, and it only reports success once the new character's base is up. Proven live in both directions
- 🟡 Driving two accounts at once — which client a profile talks to is a setting now, so the profile switch moves everything: the presses, the captures and the robberies. The second account's client is started AND restarted from the panel now, by the same buttons and the same crash watchdog as the first one: all of them reach the background session the account plays in rather than acting on the screen in front. The channel the panel talks to it over is brought up in that session too — until now it came up on the wrong desktop, so the second profile quietly read and pressed the FIRST account's game. Creating the background session in the first place is still a step outside the panel, and no live session has been played this way
- ❌ Pausing while the person at the keyboard is using the mouse. The screen-driven abilities need the game in front, so a person and the bot cannot share the computer during those
- ✅ Separate profiles per account — own settings, filters, logs and schedule — and an interface in eleven languages: English, Russian, German, French, Spanish, Italian, Portuguese, Polish, Turkish, Indonesian and Vietnamese. The phone speaks whichever the panel is set to, and anything the game itself has a word for is copied out of the game's own table rather than translated afresh
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
- ✅ Reading chat — world, national, alliance and private messages — with the chat window closed, including emoji, stickers and photos. The page that shows it is still being worked on, so it is **only in development mode** for now — switch «Разработка» on in the tab list to read chat in the panel
- ✅ Writing to chat — text, emoji, stickers, map pins and shared secret tasks. The chat page itself is **only in development mode** for now, but sending a raid's pin from the secret-task lists works as it always did
- ✅ Surveying the map: collecting a roster of players with their level, alliance and power; collecting rankings; indexing the trucks in motion
- 🟡 Attacking a monster on the map without clicking
- 🟡 Seeing the monsters on the map as a list — where each one stands, what kind it is and what level. This is the one thing on the map the game never tells anybody over the network: it decides where the monsters are inside the client itself, so the list is read out of the client's own memory rather than caught in flight. That has a price and the page is honest about it — it shows what the client can currently SEE, not the whole server, so it fills up as you move the camera around and press «Обновить». Not yet read beside a live map with monsters on it

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
