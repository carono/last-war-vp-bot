# The banners standing right now: the live block on «Ралли» (#1324)

The tab could say that a rally had been HEARD of — one line in a log six producers write
to — and never what was standing on the map at the moment somebody looked. This is the
other half: which banners are up, what each is going for, who is already in them, and
whether there is a seat left.

Two rules decide the whole shape of it, and they pull in opposite directions:

* **it lives on events, not on a clock** — a rally is worth tens of seconds, so anything
  polled once a minute would miss most of them;
* **the composition is the game's reading and never the panel's bookkeeping** — a
  membership list assembled out of log lines would be a second version of the truth, and
  the first time the two disagreed the panel's would be the wrong one (`CLAUDE.md`).

So the push is the WAKE-UP and the client's own march table is the ANSWER.

## What comes from where, and why it cannot all come from one place

| fact | source | why not the other one |
|---|---|---|
| a banner exists | `push.alliance.march.create` | the client's march table learns about it a **median of 10 s later**, and in 23 of 26 late cases only once somebody ELSE had joined (#1301) |
| somebody joined | `push.alliance.march.refresh` | same lag |
| the banner ENDED, and which way | `push.alliance.march.remove` — `{teamUuid, isCancel}` | the march table loses the banner whether it launched or was cancelled, so a reader of the table alone can never tell «стяг ушёл» from «стяг отменили» |
| how many seats it has | the push's `assemblyMarchMax` | **not in the march record at all** — 25 of the push's 33 fields survive into `GetAllMarches()` and this is not one |
| what it is going FOR | the push's `targetContentId` | likewise absent from the march record |
| who is standing in it | `DataCenter.WorldMarchDataManager:GetAllMarches()` | the pushes carry members too, but keeping them would be the panel maintaining a roster of its own |
| the leader, the target tile, the server | the same read | the leader is the march whose `uuid == teamUuid - 1` (`docs/research/rally-join.md`) |
| the species and level of the target | the push's content id, resolved in the game's own `lw_world_monster` | neither half answers alone |

The last row is the one worth spelling out: the wire has the id and the game has the
table, so the read is handed `team:contentId,…` — the same string the join's own sieve is
handed (`lua_actions.rally_join_all`) — and asks
`LocalController.instance():getValue('lw_world_monster', cid, 'name'/'level')`. The
`name` key that comes back goes through `rally_kinds.KIND_OF_NAME`, **the one table the
per-kind budget is keyed by**, so the block and the door can never name a banner
differently. There is no second classifier here, deliberately: the kind of a banner is
one question with one answer (#1323 owns it).

## The three states, which are three different pieces of news

| state | what it means on screen |
|---|---|
| `wire` | the push has landed and the client has not caught up. Shown at once, with the seats and the target the push carried, and «состав ещё не подтверждён» where the people go. |
| `open` | the client knows it: members, leader and target tile are the game's own reading. |
| `gone` | `launched` / `cancelled` off the wire, or `closed` when it simply left the march table. Kept for a couple of minutes, greyed — «what happened to that one» is asked after the fact. |

A banner that is announced and NEVER confirmed by the client is dropped quietly after 90
seconds rather than reported as closed: it was over before the client caught up, and
there is nothing to say about a banner nobody here ever saw the inside of.

**An empty reading and an unreadable one are not the same thing.** «The game says there
are no banners» retires them; a client that cannot answer leaves the block exactly as it
was. The same distinction the join is built on, and the same one that has bitten this
repository before — see «Незалогиненный клиент врёт правдоподобно» in
[`server-link-status.md`](server-link-status.md).

## The seat count takes the LARGER of the two

Both counts are floors of the truth. Measured over three and a half hours: of 21 squads
sent at a banner the wire had last announced as 5 of 5, not one arrived — the client's
count was the one that was behind (#1281). The block therefore shows
`max(len(members), what the wire last said)` of the cap, which is exactly the rule the
join's own seat filter follows.

## The faces

Out of the client's own cache, never fetched:

1. **the photo the player uploaded** — `player_photos.newest_for(uid)`, which finds it by
   hashing `uid_0` … `uid_4000` against the bucket, because nothing on the rally wire
   carries `picVer` ([`player-avatars.md`](player-avatars.md));
2. **the built-in avatar** their `headSkinId` names — `head_icons_map.icon_path`, which
   maps one family by a numbering hypothesis and deliberately leaves the rest unmapped
   rather than putting a stranger's face on a row;
3. **nothing**, and the front-end draws the name alone.

`tools/lib/player_faces.py` is the join of the two: it answers with a path inside the
SHARED folder (`game_paths.avatar_cache()`), shrinks the original into it once, and
remembers in-process both what it found and what it could not. The first lookup for a uid
walks a few thousand md5 sums, so it is done on the read's own worker and never on the Tk
thread.

`headSkinId` itself is read from the march record when it carries one and from
`AllianceMemberDataManager.allianceMembers` otherwise — the roster is the only source for
a member whose march does not repeat it.

### The phone gets the pictures too, as links

`web_view` runs on **every poll** while somebody is looking (about every 2.5 s), so the
faces cannot travel inside it — twenty photos per poll is a megabyte a minute to leave a
screen open. The view carries `avatar: "/api/avatar?face=<file name>"`, the browser
fetches each face once and caches it for a day, and `panel/web/server.py` serves that one
folder behind the same token as everything else. Only a bare NAME travels, and
`player_faces.file_named` checks it three ways — a plain name, one of the two suffixes the
folder holds, and a path that resolves inside the folder — because the route is reachable
from a phone and therefore from whatever else can reach that port.

## The isolation

One roster belongs to one tab, which belongs to one profile. Two accounts are two
alliances, and a banner of one showing up on the other's screen is the same class of leak
that `game_process.capture_narrowing` exists to stop
([`profile-isolation.md`](profile-isolation.md)). Nothing here is module state, the model
is emptied on a profile switch, and the shared thing — the folder of faces — is shared on
purpose and by an explicit decision (#1306): the same player has the same face whichever
account met them first.

## The read, and what it costs

One chunk, one round trip, at most one in flight and never more often than every 1.5 s. A
call into the game VM was measured at 0.14 s with the daemon free and 10–19 s under the
panel's ordinary background load (#1281), so a block that asked four questions would be a
block four banners behind — and a read per push, on an alliance that pushes several times
a second, would be a client held in front of the next banner all evening.

## Where the events arrive from, and what happens when they do not

The block hears through the «Ралли» tab's own capture — the one child «Монитор
стягиваний» / «Оповещать» / «Присоединяться сам» keep up between them, narrowed to this
profile's client (`game_process.capture_narrowing`, #1306). With all three switched off
there is no ear, and the block then falls back to a reading: it asks the game when the
tab is opened and when «Обновить» is pressed. That is honest rather than ideal — a
banner raised while nobody is looking and nothing is listening is a banner nobody heard.

The profile's runtime has a second, narrower ear since #1323
(`panel/runtime/wire.py` → `panel/runtime/rally_wire.py`), which exists so that the
auto-join knows a banner's kind in a profile whose window never draws this tab. Feeding
the block from that one as well would close the gap above; it is deliberately left for
whoever owns that module, because two writers into one model is exactly the sort of
thing that wants to be designed rather than bolted on.

## What it does NOT do

* **it does not press anything.** «Обновить» starts a reading; joining is the switches
  above it and the join scenario, unchanged.
* **it keeps no tally.** Every number in it is the game's own or the wire's own.
* **it does not classify a banner's kind for itself** — see the table above.
