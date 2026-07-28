# Ministry — applying for a kingdom position

*Source recording:* `results/traces/20260728_234844_министерство_министр_внутр_дел_trace.log`
(label: «министерство, министр внутр. дел»). The matching
`results/traffic/…_traffic.jsonl` holds **one keepalive and nothing else**, so the wire
half of that session is unusable — everything below was live-probed against the running
client through the warm Lua daemon (`docs/skills/sniff.md` §8.7 / §8.11).

Ships: `tools/lib/lua_actions.py` (the chunks), `tools/lib/game_buttons.py` (one `TAP`
button per post), `src/lastwar_bot/actions/submit_ministry.md` (the recipe) and
`tools/ministry.py` (read the board / apply from the command line).

## What the feature is

Each kingdom has eight appointed posts — the in-game «министерство». A player asks for
one by submitting an application; the President either lets the queue sit or has the
server grant applications automatically. On the servers observed here it grants
instantly, and posts change hands every few minutes.

| positionId | name | slug (button `apply_<slug>`) |
|---|---|---|
| `10002` | Вице-президент | `vice_president` |
| `10003` | Министр стратегии | `minister_strategy` |
| `10004` | Министр обороны | `minister_defence` |
| `10005` | Министр строительства | `minister_construction` |
| `10006` | Министр науки | `minister_science` |
| `10007` | Министр внутренних дел | `minister_interior` |
| `10008` | Военный командир | `commander_military` |
| `10009` | Административный командир | `commander_admin` |

Ids come from `DataCenter.OfficialApplyManager:GetCanApplyGovernmentList()`, names from
`DataCenter.GovernmentTemplateManager:GetTemplateName(id)`. `10008`/`10009` are the zone-war
commanders and sit vacant outside it.

## What the trace gave, and what it did not

The 314-line trace is almost entirely the government screen rebuilding its widgets. Two
lines carry the whole signal:

```
XSCALL CommonUtil.PlayerPrefsSetString <- GOVERMENT_OWN_POSITIONID,     <- held nothing
XSCALL BaseClass <- KingdomPositionApplyMessage, table: …               <- the apply class
XSCALL SFSBaseMessage.__init <- table: …, false, 10007                  <- …for post 10007
```

`KingdomPositionApplyMessage` is loaded lazily, on the first application of a session —
its appearance *is* the recorded click. `10007` matched the label, which is how the post
was identified before any probing. What the trace could not give: the controller (window
controllers live in `package.loaded["UI.…"]`, which the `_G` walk never reaches — the
known blind spot in §8.5a) and the message schema (`--dedup` keeps only the *first*
`SFSObject.Put*`, and that was another message's).

## The API

```lua
-- the press ("Подать заявку"), headless — no window has to be open
local C = require('UI.UIGovernment.OfficialApply.Controller.UIOfficialApplyCtrl')
C.SendKingdomPositionApply(C, '10007')       -- self is never touched; the id is a STRING

-- the gate the in-game button applies before sending
DataCenter.OfficialApplyManager:CheckCanApply('10007')
```

On the wire that is one command, discovered by wrapping `SFSNetwork.SendMessage` and
`SFSObject.Put*` around a call:

```
SEND cmd=kingdom.position.apply
PUT  PutUtfString positionId = 10007
```

Reads, all off `DataCenter`:

| what | call |
|---|---|
| the eight applicable posts | `OfficialApplyManager:GetCanApplyGovernmentList()` → **strings** |
| may I apply right now | `OfficialApplyManager:CheckCanApply(id)` |
| the applicant queue | `OfficialApplyManager:GetApplyList(id)` (fetch first, below) |
| my place in that queue | `OfficialApplyManager:GetApplyListOwnIndex(id)` |
| when I last applied here | `OfficialApplyManager.ownApplyTimeList[id]` (epoch ms) |
| the post I hold | `GovernmentManager.self_positionId` / `:GetOwnPositionId()` |
| who holds a post, since when | `GovernmentManager:GetPositionInfoByPositionId(id)` → `{name, abbr, uid, appointTime}` |
| minimum time in office | `OfficialApplyManager:GetResignOfficeTime()` → `1801` s (a configured constant, not a countdown) |
| ministry post or zone-war commander | `GovernmentTemplateManager:GetTemplate(id).type` → `0` / `1` |
| is my alliance the conqueror | `GovernmentManager:IsConqueror(serverId)` |

Two things must be *asked for* before they can be read — both fire-and-forget, so read
them from a separate chunk after ~1.6 s (never loop-and-wait inside one chunk):

* `OfficialApplyManager:SendKingdomPositionApplyList(id)` → `kingdom.position.apply.list`
  fills the applicant queues. They are never pushed; unfetched reads as an empty queue,
  which is indistinguishable from "nobody is waiting".
* `SFSNetwork.SendMessage('get.kingdom.positions', <kingdom>)` refreshes the holder
  table (see the board section below).

## The trap: position ids are strings

`GetCanApplyGovernmentList()` returns `"10007"`, not `10007`, and the apply manager keys
its own tables the same way. The two forms are **not** interchangeable and the failure is
silent in the direction that matters:

```
CheckCanApply(10007)    -> false      -- confident, and wrong
CheckCanApply('10007')  -> true
```

This cost a shipped-but-dead recipe: the first `submit_ministry.md` run logged
`0 press(es)` with a perfectly healthy gate. The number form is louder one layer down —
`SendKingdomPositionApply` with a number throws
`SFSDataSerializer.lua:55: attempt to get length of a number value` inside the client's
own serialiser, because `positionId` goes out as a UtfString. Every chunk in
`lua_actions.py` quotes the id.

## The other trap: `CheckCanApply` does not cover the commander posts

The template's `type` splits the eight posts in two: `type == 0` is the ordinary
ministry, `type == 1` are the two zone-war commanders. They are **not** applied for on
the same terms — the commanders belong to the war's conqueror — but
`CheckCanApply` returns `true` for them regardless, including with the zone war long
over and both seats empty.

So the client happily puts a doomed request on the wire. Firing one deliberately, with
`SFSNetwork.SendMessage` and `KingdomPositionApplyMessage.HandleMessage` wrapped:

```
SEND  kingdom.position.apply
REPLY errorCode = officer_apply_045
      errorMsg  = "not conqueror uuid:<alliance uuid>"
```

That is the resource-collect trap again (`resource-collection.md`): "the client did not
complain" is not evidence of a no-op — the request left, was rejected, and the player got
a toast for it. The gate in `lua_actions._ministry_gate` therefore adds
`IsConqueror(curDataServerId)` for `type == 1` posts, and `ministry_can_apply` mirrors it
so `TAP … xall` never reports a press the chunk then declines to make. Verified: with the
gate in place the commander application produces **no** `SEND` at all.

Only the negative half is proven. No conqueror account was available, so "the gate opens
for someone who *is* the conqueror" is inference, not observation.

## Whose ministry is on the board?

`GetPositionInfoByPositionId` serves *whatever kingdom's positions were last loaded*, and
browsing another server (the cross-server world view, `world-tiles.md`) leaves that
kingdom's holders cached. Holders from several different servers on one board are normal
rather than suspicious: a season merges a group of servers under a single government.

`tools/ministry.py` prints the server each holder came from and does not judge it. Naming
"your own" kingdom was tried and dropped: the logged-in account is not a constant during a
session (operators switch accounts), so anything derived from the current identity is a
claim the tool cannot stand behind. Showing what is actually loaded is the honest form.

Applying is unaffected either way — `kingdom.position.apply` carries **only**
`positionId`, with no server field, so the kingdom is the server's business and not
something the client chooses.

## Verification

1. Read `GovernmentManager.self_positionId` → `0` (no post).
2. `C.SendKingdomPositionApply(C, '10007')`.
3. Re-read → `10007`, `GetOwnPositionId()` → `10007`,
   `GetTemplateName(10007)` → «Министр внутренних дел». Confirmed in-game by the
   operator; **no window was opened at any point**.
4. Re-run through the DSL: `run_action('submit_ministry', 0)` →
   `TAP Apply: Minister of the Interior … (1; 1 available)` → `1 press(es)`.

5. The Administrative Commander post, applied for on purpose because it was known to be
   unavailable: request sent, `officer_apply_045` back. After the conqueror gate landed,
   the same call sends nothing.

The post was lost again minutes later to another applicant — where the server grants
applications automatically the ministry churns, which is exactly why the queue and "how
long has the holder sat" reads exist: scheduling *when* to apply is left to the recipes
that will use them.

## Usage

```bash
C:\Python312\python.exe tools\ministry.py                        # the board
C:\Python312\python.exe tools\ministry.py --apply minister_science
C:\Python312\python.exe tools\ministry.py --apply 10007 --dry-run
```

```
TAP apply_minister_interior xall     # the recipe form; `xall` = press only if eligible
```

Gating a scheduling recipe (note the quotes):

```
READ_LUA (DataCenter.OfficialApplyManager:CheckCanApply('10007') and 1 or 0) INTO can
READ_LUA (function() local n=0 for _ in pairs(DataCenter.OfficialApplyManager:GetApplyList('10007') or {}) do n=n+1 end return n end)() INTO queue
```

`lua_actions.ministry_can_apply / ministry_queue_len / ministry_held_minutes` build those
expressions, so a recipe and the CLI never drift apart.

## Not done

* **Appointment notification** — `push.*` for "you were appointed" was not isolated;
  polling `self_positionId` covers it for now.
* **Resigning** — `KingdomPositionInfo:Deposition()` and the 1801 s lock are read but
  never exercised.
* **Applying during the alliance duel** (the legacy script's third ministry item) — the
  duel gate was not investigated.
