# Skill — turn a recorded session into a recipe (worker cheat-sheet)

You have a recorded sniffer session — a `results/traffic/*_traffic.jsonl` +
`results/traces/*_trace.log` pair, ideally with a `_desc.txt` beside it. This page
turns that into a committed `actions/*.md` recipe. The whole job is
[§8.0](#80-the-strict-checklist--analysis-in-10-minutes) — nine commands, in
order; the rest is reference for when a step of §8.0 sends you there.

**Need to *record* a session yourself** (run the sniffers, capture a new stream,
trace which Lua fired)? That is the other half of the skill,
[`sniff-capture.md`](sniff-capture.md) — do not read it to analyse a recording you
already have.

> **ACE note.** Reading the two files is passive. The one active thing this page
> can send you to is live-probing the Lua VM (§8.7, §8.11), and the strict path
> only reaches it when the wire is empty — emulator + throwaway account only, per
> the ACE rule in `sniff-capture.md`.

This page is the analysis half of §8 — **§8.0 and §8.4-§8.11**. Recording
(§8.1-§8.3) and the capture toolkit (§1-§7) are in `sniff-capture.md`; the two
share the §8 numbering with no overlap.

---

## 8. From a recorded session to a recipe

The **standard loop** the project runs: the player performs an action once with
both sniffers on, and the session ends with a committed `actions/*.md` recipe that
reproduces it headlessly. `../research/alliance-tech-donate.md` is one full worked
instance of it, and `src/lastwar_bot/actions/help_ally.md` is the instance where
the trace came back empty (§8.11).

```
 1  panel: Develop → Sniffer ON, type a label, WAIT for «[sniff] ГОТОВ»  ┐ operator;
 2  the player performs ONE in-game action                               │ sniff-capture.md
 3  panel: Develop → Sniffer OFF → keep (+ describe) or delete the run    ┘ §8.1-§8.3
 4  read the description:  python3 tools/sniff_runs.py --last 1  (missing? ASK)
 5  list the outgoing wire msgs — that IS the action (empty? then, only then, §8.11)
 6  name the 1-2 key msgs (cmd + payload fields) + one grep for the owning manager
 7  primitive → tools/lib/lua_actions.py     (no live probe)
 8  button    → tools/lib/game_buttons.py
 9  scenario  → src/lastwar_bot/actions/dev/<name>.md  as TAP lines
10  farming.md + farming.ru.md 🟡, one line each → farming_progress.py --write → commit
```

Steps 1-3 are the operator's (`sniff-capture.md`); **4-10 are your whole job, in
strict form below.** The two files answer the same question from opposite ends —
*what the client called* vs *what crossed the socket*.

### 8.0 The strict checklist — analysis in ≤10 minutes

> **STRICT RULE. Trace analysis must complete in ≤10 minutes.** Do the nine steps
> below in order and nothing else. **No** exploratory reading, **no** live Lua
> probes (unless step 2's gate fires on an empty wire), **no** research note
> (unless the user asks for one), **no** re-checking the farming bar between
> steps, **no** "let me also verify X live." The recipe ships **🟡** — written
> from the wire, proven later by the player. §8.4-§8.11 are reference; open one
> only when a step here names it.

The whole of the worker's job (steps 4-10), as nine actions — one action, one
command, one output each. The only branch in the list is step 2's gate. Name the
files once:

```bash
# the newest run
L=$(ls -t results/traces/*_trace.log | head -1)
T=$(ls -t results/traffic/*_traffic.jsonl | head -1)

# a run the player named ("Лечение юнитов") — ask for the pair, never build it
L=$(python3 tools/sniff_runs.py --json <label> | jq -r '.[0].files.trace')
T=$(python3 tools/sniff_runs.py --json <label> | jq -r '.[0].files.traffic')
```

The two sniffers start a second or two apart, so **one run's trace and traffic
carry different timestamps** — `20260729_152841_…_trace.log` next to
`20260729_152842_…_traffic.jsonl`. A glob built from the trace's stamp finds no
traffic at all and reads as "the wire was silent". Take the pair from
`sniff_runs.py`, which knows they belong together.

1. **Read what the player did** (~30 s).
   ```bash
   python3 tools/sniff_runs.py --last 1
   ```
   No description, or too terse to know the button / order / result? → **stop and
   ask the player (§8.4).** That one wait is the exception to "no branching."

2. **List the outgoing messages** (~30 s) — this is the answer.
   ```bash
   jq -c 'select(.dir=="up" and .cmd!="(keepalive)")' "$T"
   ```
   The `up` lines minus keepalives **are the action**: command + payload.
   The field is `dir`. (`direction` belongs to the raw map-capture format —
   `tools/lib/map_capture.py`, a different file with a different shape; a grep
   for it here matches nothing and looks like a silent wire.)
   **GATE — the only branch.** Zero `up` lines → the wire is silent, so *only
   then* fall to the live VM (**§8.11**). Otherwise **never touch the VM** — go on.

3. **Name the 1-2 key messages** (~2 min). Pick the command(s) that *are* the
   action — ignore the list/refresh reads around them — and note in one line the
   `cmd` and the payload fields that are parameters (`{type:2}`, `{scienceId:…}`).
   One grep of the trace for the owning manager, no more:
   ```bash
   grep XSCALL "$L" | grep -vE '\.(getters|super)\.' \
     | grep -E 'DataCenter\.|Utils?\.|Manager\.|Message' | grep -i <noun>
   ```
   Take the `DataCenter.<X>Manager` / `<X>Util` carrying that noun — **not the
   loudest line** (§8.7a). That name + the wire command *is* the recipe. Do not
   probe it live.

4. **Write the primitive** (~30 s) — one named chunk in `tools/lib/lua_actions.py`
   that presses it: the manager method from step 3, args from step 2's payload.

5. **Write the button** (~15 s) — one `Button` in `tools/lib/game_buttons.py`
   (`lua=…` / `wait` / `label`; add `count_lua` only if the action is
   counter-gated). Fields → §8.8.

6. **Write the scenario** (~1 min) — `src/lastwar_bot/actions/dev/<name>.md`,
   `TAP` lines. Grammar → §8.9. It lands in `dev/` because it is not proven live.

7. **One line in the farming list** (~30 s) — `docs/farming.md` (EN) **then**
   `docs/farming.ru.md` (RU): same section, same position, marked **🟡** (recipe
   written, not yet proven in a real session). Both files, same edit — never one
   without the other.

8. **Redraw the bar, once** (~10 s).
   ```bash
   python3 tools/farming_progress.py --write
   ```

9. **Commit** (~15 s) — primitive + button + scenario + both farming files + bar,
   one commit. Message: what the wire showed, and that it is 🟡 pending live proof.

That is the whole job. The player proves it live in a later session; only then
does the mark flip 🟡 → ✅. Do not verify it yourself, do not write a research
note, do not grep a second time.

#### 8.0a What this checklist cannot see — the gates

Step 3 says the manager name plus the wire command *is* the recipe. For a press
the server may **refuse**, that is not enough, and the shortfall is invisible here:
a recording only ever shows the press the player made **succeed**, so the
conditions that had to hold first leave no trace at all.

Decoration upgrade (#1125) is the worked example, and it cost two commits. The wire
was complete and unambiguous — `decorator.progress.upgrade` with `{buildUuid, num}`
— and the recipe built from it did nothing in game, twice:

* both parameters looked free-form and were not (`buildUuid` is the decoration
  group's representative building, `num` is a count of steps, not a slot index);
* the press needs two gates that appear nowhere on the wire. One was found only by
  reading the server's **refusal** (`building_center_tips4`, "building no
  extra_lvup_para"); the other was read off a plausible neighbouring function that
  turned out to price something else entirely, so the button reported "nothing is
  affordable" forever.

So: ship 🟡 from the wire as the nine steps say, but **write the recipe so a missing
gate is loud.** A press that cannot tell "not ready" from "sent and ignored" hides
its own bug — and a readiness count that reads zero for every unit on the account is
a claim that needs evidence the gate itself cannot supply. When the player comes back
saying it did nothing, the wire has already told you everything it knows; go to the
VM (§8.7) and read the window's own sender, then `string.dump` the gate before
trusting it.

Full post-mortem: `docs/research/decoration-upgrade.md` §6.

### 8.4 Read the description first — no description? Ask

**Start every analysis here**, before opening either file:

```bash
python3 tools/sniff_runs.py --last 1      # the newest run: files + its description
python3 tools/sniff_runs.py ресурс        # runs whose label/description match
python3 tools/sniff_runs.py --undescribed # runs still missing one
```

It lists each recorded session — both files, their sizes, and the operator's
answer to «что делал в игре» (`sniff-capture.md` §8.3), read from the `_desc.txt`
beside them. That description is the context both files lack; read it as the
statement of what the run was supposed to record, and treat the files as the
evidence for it.

A trace without knowing what was done is a list of UI class names. If the run
carries no description, or the description is too terse to reconstruct the flow,
**ask the player first**. The questions that actually change the analysis:

1. What was pressed, **in what order**? (Which panel opened, which cell/tab.)
2. Did a **window open**, and did you close it afterwards? How many?
3. Was it **one press or several**? Did anything visibly count down
   (attempts / "N left" / a progress bar)?
4. What **changed** afterwards — resources arrived, a red dot cleared, a march
   left, a mail appeared?
5. Was the action **available at all** at that moment, or was the daily quota
   already spent? (A spent quota is why a send may be missing from the wire.)

Record the answer where the next session will find it: attach it to the run
(`tools/sniff_runs.py --describe "…"`, which writes the note the panel would
have). The file name only carries the label, not the sequence.

### 8.5 Read the two files

#### a) `results/traces/*_trace.log` — which Lua fired

Format: raw `Player.log` lines the tracer tailed, one call per line —
`XSCALL <table.fn> <- <arg>, <arg>, …`. Arguments are never truncated.

**Check the `XSTRACE installed …` header before you read a line of it.** With
`dedup=false` (what the panel records now) the file holds every call, in order.
With `dedup=true` only the **first** call of each name was written and the rest were
counted at exit — the file is then a *set of names*, not a session: a second
message, a second click, the second entry of an array are all absent. Absence in a
deduped file means nothing, so never reason from it — the one thing to do is
re-record (`docs/skills/sniff-capture.md`).

```bash
L=results/traces/20260728_171425_Сбор_ресурсов_trace.log

grep -c XSCALL "$L"                                     # did anything fire at all?
grep -o 'XSCALL [A-Za-z0-9_.]*' "$L" | sed 's/XSCALL //' | nl   # names, in call order

# signal only: drop the UI/engine churn, keep game logic
grep XSCALL "$L" | grep -vE '\.(getters|super)\.' \
  | grep -E 'DataCenter\.|Utils?\.|Manager\.|Message|SFSObject\.'
```

What is **noise** (the client rebuilding its UI — always the bulk of the file):
`UI*` widgets, `RadarImage.*`, `*.getters.*`, `*.super.*`, `New` / `__init` /
`Delete` / `OnDestroy` / `OnCreate`, `Vector3.New`, `Color.*`, layout groups,
`UIAnimator.Play`.

What is **signal**:

| pattern | meaning |
|---|---|
| `DataCenter.<X>Manager.<fn>` | the data layer — where the real API lives (`DataCenter.ProductLineManager.bindProductionTimer`) |
| `<X>Utils.<fn>` / `<X>Util.<fn>` | the action verb itself (`BuildingUtils.CityCollectionByItemId` — collecting a city resource bubble) |
| `SFSObject.Put*` (`PutInt`/`PutLong`/`PutLongArray`) | **the client is serialising an outgoing message right here** — the anchor for the matching `up` command on the wire |
| `SFSBaseMessage.HandleMessage` | a server reply is being parsed |
| `*Template.*`, `*Data.ParseData` | the config/data model behind the feature (ids, gates) |
| `EventManager.Broadcast*` | the feature's internal event id |

**Known blind spot — the UI click handler will not be there.** The tracer walks
`_G` to `--depth 2`, and window controllers (`UIAllianceScienceInfoCtrl` and
friends) live in `package.loaded["UI.…"]` modules, not on `_G`. Across every
session recorded so far, **no** `*Ctrl:On*Click` ever appeared in a trace. The
trace gives you the layer *underneath* the button; the controller name comes from
§8.7. `--depth 3` widens the walk (slower, noisier) and is worth one retry when
the interesting table is nested.

#### b) `results/traffic/*_traffic.jsonl` — what crossed the socket

One JSON object per message: `{"ts", "dir", "cmd", "payload"}`. `dir` is `up`
(client → server) or `down`.

```bash
T=results/traffic/20260728_172314_Подарки_альянса_traffic.jsonl

jq -r '.cmd' "$T" | sort | uniq -c | sort -rn            # command histogram
jq -r 'select(.dir=="up" and .cmd!="(keepalive)")|[.ts,.cmd]|@tsv' "$T"   # what WE sent
jq -c 'select(.cmd|test("alliance"))' "$T"               # domain grep, with payloads
jq -r '[.ts,.dir,.cmd]|@tsv' "$T"                        # full timeline
```

**The `up` lines minus keepalives are the action.** That short list *is* the
protocol-level answer, and it is usually readable without any further work:

| session label | the `up` lines | reading |
|---|---|---|
| Подарки альянса | `alliance.reward.list` → `alliance.reward.allreceive {type:2}` → `alliance.reward.list` | list the gifts, claim all of type 2, re-list to refresh |
| поздравление с повышением базы | `alliance.congratulation.thumbs.up` | one fire-and-forget send |
| Сбор грузовика | `train.batch.reward` → `train.record.batch.detail` | claim, then read back the record |

Cross-check the names against `tools/known_commands.txt`. A command **not** in
that file is newly observed (`alliance.reward.allreceive` and `train.batch.reward`
were, at the time of writing) — add it there as part of the commit, and see
`tools/trap_command.py` for catching a command you expect but have not seen yet.

Payload fields are the recipe's parameters: `{"type":2}` on `allreceive`,
`{"index":0,"len":1000}` on a list request, `_id` pairing a request with its reply
(server pushes carry none).

**Zero `up` lines is a real result too**, and it splits into three cases:

- the action was **client-only** (a UI toggle, a local read) — nothing to send;
- the action was **gated** (daily quota spent, nothing pending) — the client
  swallowed the click, which §8.4 question 5 is there to catch;
- the sniffer missed it (`sniff-capture.md` §4): wrong interpreter/interface, or
  the game was not actually connected.

### 8.6 Line the two files up

Be aware of the asymmetry before trying anything clever:

| | timestamps | ordering |
|---|---|---|
| `*_traffic.jsonl` | yes, `ts` per line, 1 s resolution | wire order |
| `*_trace.log` | **no** — they are raw `Player.log` lines | call order; first-call order only if the header says `dedup=true` |

So there is no join key. What works, in order of effort:

1. **One action per run** (the recording rule, `sniff-capture.md` §8.2). Then both
   files describe the same 30 seconds and correlation is reading, not joining.
2. **The panel log is the correlated view.** It interleaves `[traffic]` and
   `[trace]` lines from both children in real time — that interleaving *is* the
   timeline the files lack. Copy it out of the panel while the session is fresh
   if the ordering matters.
3. **Anchor on serialisation.** An `SFSObject.Put*` / `<X>Message` in the trace
   and an `up` command in the traffic file, both near the end of the action, are
   the same event seen twice.
4. **Names rhyme across the two layers.** Use the wire name as the search term
   for the Lua side, and vice versa. From the «Сбор грузовика» session, the two
   files pair up on sight:

   ```
   trace:   XSCALL RailwayUtil.ApplyArriveReward <- table: …
   traffic: 17:26:04  up  train.batch.reward
            17:26:06  up  train.record.batch.detail
   ```

   Same for `al.science.donate` ↔ `AllianceScienceDataManager` /
   `AlScienceDonateMessage`. One `*Util(s).<Verb>` in the trace plus one `up`
   command with the matching noun is a solved step.

### 8.7 Pin the API on the live VM (only when the wire is empty — §8.0 gate)

**The trace nominates candidates; it does not prove the API.** This is the
fallback for a silent wire (§8.0 step 2 gate → §8.11), not part of the fast path —
when the `up` command is on the wire, that command *is* the answer and you do not
probe. When you must probe, results come back through a log line, because
`SafeDoString` returns nothing and swallows errors (`../research/xlua-state.md`) —
`lua_eval.py` prints them for you, so you never have to know which file they landed in
(`lw_answers.log` beside `Player.log`, see `../research/game-call-latency.md`).

```bash
# one chunk, results printed by marker
/mnt/c/Python312/python.exe tools/lib/lua_eval.py --marker P "
CS.UnityEngine.Debug.LogError('P '..tostring(DataCenter.AllianceHelpDataManager:GetHelpNum()))"
```

The three questions to answer for every step of the flow:

| question | probe |
|---|---|
| **What holds the feature?** | `for k in pairs(DataCenter) do ... end` — list the managers, grep the domain noun (`Help`, `Reward`, `Science`) |
| **What can it do?** | walk the manager's metatable/`__index` and log every `function` key |
| **How many times can it be done now?** | a `Get*RestCount` / `Get*Num` / `Get*Count` on the same manager — this becomes `count_lua` in §8.8 |

```lua
-- 1. which managers exist
local out = {} for k,v in pairs(DataCenter) do out[#out+1] = tostring(k) end
CS.UnityEngine.Debug.LogError('P '..table.concat(out, ' '))

-- 2. what a manager exposes
local M = DataCenter.AllianceHelpDataManager
local out = {} for k,v in pairs(getmetatable(M) and getmetatable(M).__index or M) do
  if type(v) == 'function' then out[#out+1] = tostring(k) end end
CS.UnityEngine.Debug.LogError('P '..table.concat(out, ' '))

-- 3. a module-scoped class the _G walk never sees (the controllers from §8.5a)
for k in pairs(package.loaded) do
  if tostring(k):find('Help') then CS.UnityEngine.Debug.LogError('P mod '..tostring(k)) end end
```

**Read the candidate's body before you call it.** The client's Lua is compiled but
**not stripped**, so `string.dump` on any Lua function hands back a chunk whose
constant table still names every string it references — globals, fields, message
ids — plus its source path and its locals. Printing the printable runs of that dump
answers "does this function send anything?" without firing it:

```lua
-- 4. a poor man's decompiler: the strings a function references, in order
local function strings(f, tag)
  local ok, b = pcall(string.dump, f)          -- C functions are the only failure mode
  if not ok then CS.UnityEngine.Debug.LogError('P '..tag..' dump FAILED') return end
  local out, cur = {}, {}
  for i = 1, #b do
    local c = b:byte(i)
    if c >= 32 and c < 127 then cur[#cur+1] = string.char(c)
    else if #cur >= 4 then out[#out+1] = table.concat(cur) end cur = {} end
  end
  CS.UnityEngine.Debug.LogError('P '..tag..' :: '..table.concat(out, ' | '))
end
strings(DataCenter.AllianceHelpDataManager.OnHelpAll, 'Mgr.OnHelpAll')
```

A sender's constants contain `SFSNetwork | SendMessage | MsgDefines | <TheMsg>`. If
they don't, the function is a *reply applier* and calling it only rewrites local
state — which is precisely how `AllianceHelpDataManager:OnHelpAll` (constants:
`otherHelpInfoList | SetHelpNum | self`) shipped a help-all recipe that cleared the
pending list and helped nobody. See `../research/alliance-help.md`.

**Verification is a counter, not a screenshot.** Read the count → fire the call
once → read it again. That round trip is what turns a guess into an entry in
`game_buttons.py`. Keep the traffic sniffer running while probing: seeing your
own `up` command appear is the second half of the proof.

Two hard rules while probing (both learned the hard way):

- **Never loop-and-wait-on-server inside one Lua chunk.** A counter only drops
  after the server replies; a tight `while rest > 0 do press() end` spins the main
  thread and **freezes the client**. One press per chunk, pause, re-read.
- **Each UI step lands on the next frame.** A chunk cannot see the window it just
  opened — stage `OpenWindow` / `On…Click` / the action as separate chunks with a
  settle between them. This is exactly what the `wait` field in §8.8 is for.

### 8.7a Post-mortem — the resource-collect trap (read before you replay a trace)

`collect_base_resources` took a whole session to get right. Every wrong turn was a
violation of §8.7, so they are worth naming — this is the checklist that would have
found the answer in minutes.

1. **The flashiest XSCALL line is a symptom, not the API.** The resource trace's
   load-bearing line looks like `BuildingUtils.CityCollectionByItemId(itemId,
   worldPos...)` — a per-type, position-hungry call. Transcribing it literally forced
   a 205-building scan (`GetAllBuildData` → group by itemId → resolve each world
   position) and *still* didn't reliably collect. The real answer was the **quiet**
   line one row down — `ProductLineManager.bindProductionTimer(<uuid>)` — which names
   the owner: the base's generators are **production lines**, and the whole harvest is
   `DataCenter.ProductLineManager:SendCollect(uuid)` looped over `GetAllBuildUuids()`.
   **Read the trace to find the manager, then §8.7-walk it; don't replay the loudest
   call.**

2. **The inherited API is a hypothesis, not a fact.** The old recipe, this repo's
   research note, and the memory all asserted `CityCollectionByItemId`. Anchoring on
   that framing — trying to *simplify within it* — cost the most time. When a recipe
   "doesn't work," re-derive the mechanism from live state; don't optimise the wrong
   call.

3. **The verification signal must reset on success — per unit, not an aggregate.**
   The first checks watched a whole-base storage *sum*, which climbs every second from
   ongoing production: a real collect was buried in the noise and a no-op looked
   identical to a success. Switching to per-building `GetBuildingCurrStorage(uuid)` —
   which snaps to ~0 the instant that one building is collected — made it unambiguous
   in one read: `SendCollect` drops it; `CheckOneKeyCollectAll` (only *checks* whether
   to show the one-key button), `TryCollectRes()`/`OnCollectClick()` with no uuid, and
   `CampProduceDataManager:CollectAllRes` (a different, seasonal subsystem) do not.
   Pick a signal that is **zero-or-not for a single unit**, then fire and re-read.

4. **Prefer the data-layer call; ignore the window.** Hunting for "which modal the
   *resources* tap opens" was a rabbit hole — one candidate is a convert window that
   hangs when opened without its server data; another's "collect" button was a GM
   `gm.gain.item` cheat. None of it mattered: the harvest is a headless manager method
   that needs no UI. If the manager call works from the daemon with nothing open, the
   recipe needs no window tap (here: two imagined taps collapsed to one).

5. **State over screenshots.** A `*_collect_all.png` template says nothing about the
   API; reading one was pure detour. Decide everything by reading VM state through the
   daemon.

6. **"It silently no-ops" is a claim about the wire — go read the wire** (#1087). The
   sweep was shipped fire-at-everything because a not-ready building looked inert from
   the VM: `pcall` succeeded, nothing was logged, storage stayed 0. It was not inert —
   every one of those calls left the client and came back as
   `errorCode 602026 "In production, please be patient."`, one player-facing toast each.
   A 30-second `tools/lib/live_tshark.py` capture around a single call settled it. When
   a loop fires a *network* call speculatively, the capture — not the absence of a Lua
   error — is what proves the no-op.

The durable write-up for this specific feature, incl. the method-by-method test table,
is [`../research/resource-collection.md`](../research/resource-collection.md).

### 8.8 Add the buttons

`tools/lib/game_buttons.py` is the vocabulary the DSL's `TAP` speaks: one entry
per pressable thing, `name -> Button`. This is where the ugly engine calls live so
the recipe never names them.

```python
"help_ally_all": Button(
    lua=_lua_actions.alliance_help_all(),           # sends al.help.all
    wait=1.0, label="Help All (alliance)",
    count_lua=_lua_actions.alliance_help_waiting(),  # enables `xall`
    max_taps=10,                                     # safety cap
),
```

Anything longer than a call or two goes in `tools/lib/lua_actions.py` as a named
chunk builder, so the button stays one readable line and the engine reasoning lives
next to its own docstring.

| field | what to put there |
|---|---|
| `lua` | the chunk that presses it, verbatim; one step only |
| `wait` | pause **after** pressing. Opening a window ≈ 1.2-1.5 s; an in-place click ≈ 0.1-0.4 s; anything the server must confirm ≈ 0.6-1.0 s. The pause belongs here, not in the recipe. |
| `label` | the human phrase that shows up in the log |
| `count_lua` | optional expression = "how many times can this still do something *right now*". Present ⇒ the recipe may say `xall`, and the loop re-reads it, so throttled or dropped presses are retried. |
| `max_taps` | hard cap on `xall` iterations, so a miscounting expression cannot spin forever |

Add one entry per *button the player pressed*, not one per Lua call you found.
If the flow was "open panel → open detail → press → close", that is four entries
(and `close` already exists).

### 8.9 Write the recipe

`src/lastwar_bot/actions/dev/<name>.md`, in `TAP` notation — the everyday form is a
list of button presses with a comment header explaining the flow and its limits.
Grammar: [`../dsl.md`](../dsl.md); authoring conventions:
[`../actions-authoring.md`](../actions-authoring.md).

```
# Donate to the alliance's priority (recommended) technology.
#
# One line, because the donate press needs no window open: the controller method
# behind "Donate 1000" touches no window state, so it is called straight on the
# module. The messy engine calls live in tools/lib/game_buttons.py.

TAP donate_1000 xall  # press "Donate 1000" for every attempt currently banked
```

The patterns that keep recurring:

| pattern | when |
|---|---|
| `TAP <b> xall` | counter-gated repeats — donate, help, claim. Needs `count_lua`; re-reads the count each round, so it stops exactly when the server says so. |
| `TAP <b> xN` | fixed, known repeats (rare — prefer `xall`) |
| `TAP close xN` | unwind the window stack at the end — `close` pops the top window (`Ctrl:CloseSelf()`), so press it once per window the recipe opened. Don't over-press: past the recipe's own windows you start popping the HUD, and there is no in-session recovery from that. |
| no `close` at all | the action was headless — a data-manager call that opened nothing (`help_ally.md`). Do not add windows the flow does not need. |
| `WHILE <var> > 0` + `READ_LUA … INTO <var>` | a bespoke count-gated loop when `xall` does not fit |
| `LUA <chunk>` | the authoring layer — a one-off engine call while a button is still being designed. Do not ship a whole multi-step flow inside one `LUA`. |
| `GAME WORLD` / `GAME CITY`, `JUMP x, y[, server]` | scene switch / coordinate jump sugar |

Write the header comment as if for someone who never saw the trace: what the
in-game action is, which single Lua call is behind it, whether a window is
involved, and **what the daily limit really counts** (for `help_ally` it is help
*points*, not helps — a distinction that only came out of §8.7 probing).

New scripts stay in `src/lastwar_bot/actions/dev/`; promote to `actions/` (which is
what the panel's Scenarios picker lists) once the player has proven them live.

### 8.10 Verify live — optional, only when the game is up

The strict path (§8.0) **stops at the 🟡 commit**; the player proves the recipe in
a later session. Do the steps here only when the game is actually running and you
want to prove it now, or when the user explicitly asks for a durable research note.

1. **Parse:** `python -X utf8 -c "from lastwar_bot import script_engine; print(script_engine.parse_file(script_engine.ACTIONS_DIR / 'dev' / 'NAME.md'))"`
2. **Run:** panel → **Scenarios** tab → pick the script → Run. A game-primitive-only
   recipe runs with `hwnd=0`, no window handle needed.
3. **Watch it on the wire:** keep the traffic sniffer on during the first run.
   The recipe is correct when it produces **the same `up` commands** as the
   human's recording did. That is the acceptance test; on a pass, flip the farming
   mark 🟡 → ✅ and promote the script out of `dev/`.
4. **Research note — only if asked** — `docs/research/<feature>.md`, following
   `alliance-tech-donate.md`: which labelled trace it came from, what the trace
   showed, what had to be live-probed, the API table, the freeze pitfalls, and
   the usage lines. `results/` is git-ignored, so the note is the only durable
   record of the session. Not part of the fast path — write it on request.

### 8.11 The trace came back empty — what then (§8.0 step 2 gate)

This happens, and it is not a dead end. `20260728_162518_Помощь_союзнику_trace.log`
holds **zero** `XSCALL` lines, yet the session still shipped `help_ally.md` the
same day. Diagnose first, then fall back.

| symptom | cause | fix |
|---|---|---|
| no `XSTRACE installed` line, or `INSTALL ERROR` | the chunk never ran — daemon down, VM not reachable | restart `tools/lua_daemon.py`, re-record |
| `wrapped=0` | the walk found nothing to wrap — the VM reached is not the game's live state, or a `--filter` matched nothing | drop the filter, restart the daemon, re-record |
| `installed wrapped=8xxx` but **no `XSCALL`** | the action's code path is not reachable from `_G` at depth 2 (module-scoped controller — see §8.5a), or it is not Lua at all (C#/IL2CPP), or the click was gated and nothing ran | retry with `--depth 3`, or a targeted `--filter Help` (a filter wraps only matching names, so it is safe without `--dedup`), or `--hook-all` (heaviest — may stall the game) |
| `XSCALL` lines, but all `UI*` churn | the feature's logic is native / behind a controller | fall back below |

**The fallback that works — recover from the wire, then live-probe the VM:**

1. **Take the name from the traffic file.** The `up` command is the feature's
   true name (`al.help.all`, `alliance.reward.allreceive`). If traffic is empty
   too, take the noun from the in-game wording instead (Help → `Help`).
2. **Grep the VM for that noun** — `DataCenter` managers and `package.loaded`
   modules (§8.7 snippets). `al.help.all` ⇒ `DataCenter.AllianceHelpDataManager`.
3. **Enumerate its methods** and read them as a sentence: `GetHelpNum`,
   `OnHelpAll`, `GetAllianceHelpSliderData`. The `Get*` is the counter, the
   `*Data` is the limit model — and the `On*` is a **candidate**, not the action.
   Half the `On*` methods on a data manager are reply appliers called by
   `<Thing>Message:HandleMessage`. Dump its constants (§8.7 snippet 4) and look for
   `SFSNetwork | SendMessage` before you believe it: `AllianceHelpDataManager:OnHelpAll`
   has none, and shipped a recipe that helped nobody for a day.
4. **Prove it on the wire, not with the counter.** Read `GetHelpNum()` → call the
   candidate → read it again is only *half*; a reply applier passes that test,
   because it edits the very state you are reading. The proof is the `up` command
   appearing in the traffic sniffer, with the server's reply behind it. If the
   counter moved and the wire stayed quiet, you called the applier.
5. **Check the real limit** while you are in there. `help_ally` looked capped
   until `GetAllianceHelpSliderData` showed the 1000/day cap is on help *points*,
   not on helping — which changed the recipe.

Write down in the commit that the API was **live-probed because the trace was
empty**. That single sentence saves the next session from re-recording a trace
that will be empty again.
