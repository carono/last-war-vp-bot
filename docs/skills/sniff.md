# Skill — sniff Last War traffic (worker cheat-sheet)

Stop re-discovering the toolkit. This page is the copy-paste path from "I need
to see the game's traffic" to a decoded stream. The *why* (anti-cheat, protocol
format) lives in [`../research/protocol.md`](../research/protocol.md),
[`../research/sniffing-playbook.md`](../research/sniffing-playbook.md) and
[`../../tools/README.md`](../../tools/README.md).

> **ACE rule.** §1-§6 are **passive capture** — transparent to the anti-cheat.
> MITM / Frida / socket injection is not; emulator + throwaway account only.
> §7 (Lua-function tracing) is the **in-process, active** exception — it injects
> Lua by thread-hijacking; same emulator + throwaway-account rule applies.

> **Turning an in-game action into a bot recipe? Start at [§8](#8-the-basic-workflow--one-sniffer-run--a-working-recipe).**
> §1-§7 are the reference for each tool on its own; §8 is the end-to-end loop
> (panel Sniffer → player acts → read both files → live-probe the VM → buttons →
> a `TAP` recipe) that those tools exist to serve.

---

## 1. Environment — what works

| Fact | Value |
|---|---|
| **Interpreter for capture** | `/mnt/c/Python312/python.exe` — the **Windows** Python. Sees `C:` and `D:`, has scapy + npcap. |
| **Never** use for capture | The WSL `python3`. WSL2 is a NAT'd VM; its sockets **cannot see** the Windows game's packets — it captures nothing, silently. |
| **Capture interface** | `#13 "vEthernet (Создать виртуальный коммутатор)"` — the Hyper-V virtual-switch adapter. Confirm with `--list-ifaces`; the number can shift, the name is the anchor. |
| **Game endpoint** | TCP `34.145.128.94:17935` (server IP changes per session — match by **port 17935**, not IP). |
| **Game running?** | The game process holds an **ESTABLISHED** connection to `:17935` (`netstat -ano | findstr 17935`). No such line = not logged in = nothing to capture. |

One-time on the Windows interpreter:
`C:\Python312\python.exe -m pip install scapy zstandard`
(`zstandard` is mandatory — the 445 KB login `init` and other big frames are
zstd-compressed and won't decode without it.)

npcap needs **no** Administrator prompt when installed with "allow
non-administrator capture" (Wireshark's default).

---

## 2. Ready-made tools

All four run from the repo root. The first three talk to **npcap directly via
scapy** — no Wireshark, nothing spawned. Every tool takes `--list-ifaces`,
`--iface <name>`, `--seconds N` (else Ctrl+C), and `--dump traffic.jsonl` (record
**every** decoded frame as JSONL for later mining).

### `secret_task_capture.py` — secret tasks (map tiles `f2 = 17`)
```bash
/mnt/c/Python312/python.exe tools/secret_task_capture.py                  # stream, print
/mnt/c/Python312/python.exe tools/secret_task_capture.py --seconds 300 --json out.json
/mnt/c/Python312/python.exe tools/secret_task_capture.py --level 7 --can-loot
```

### `secret_mission_capture.py` — ghost-recon missions (tiles `f2 = 29`)
"Операция Призрак" / Secret Command Post co-op weekly.
```bash
/mnt/c/Python312/python.exe tools/dev/secret_mission_capture.py              # stream, print
/mnt/c/Python312/python.exe tools/dev/secret_mission_capture.py --done       # only lootable-now
/mnt/c/Python312/python.exe tools/dev/secret_mission_capture.py --server 991,992 --json out.json
```

### `ghost_recon_tile_dump.py` — every `f2 = 29` tile, no filter
Diagnostic twin of the mission scanner: dumps all ghost-recon tiles plus the
off-map ghost-recon polls, and cross-references them by uuid/coordinate. Use it
when the mission scanner shows nothing and you need to know whether the tile is
on the wire at all.
```bash
/mnt/c/Python312/python.exe tools/dev/ghost_recon_tile_dump.py --seconds 300 --json out.json
```

### `rally_monitor.py` — alliance rallies / стяги
Harvests every participant's `armyInfo` out of `push.alliance.march.*`. Same
scapy/npcap transport as the three above (no `dumpcap.exe`/`tshark.exe`), but it
listens on the `push.alliance.march.*` push stream instead of `world.get.block`,
so **no map panning is needed** — a rally arrives the moment it is launched or
refreshed.
```bash
/mnt/c/Python312/python.exe tools/rally_monitor.py --seconds 1800 --out results/rally/monitor.jsonl
```

**Map tiles need the map moving.** Secret tasks, missions and ghost tiles ride
`world.get.block`, which the server sends **only while you pan the map**. Zero
map responses = nobody was dragging, not a broken capture (the closing line says
which). Rallies are pushed unprompted and need no panning.

---

## 3. Capture from scratch (wide dump / a new stream)

When no ready tool fits, reuse the transport — don't reimplement sniffing.

**Building blocks** (all in `tools/`):
- `map_capture.start_capture(index, args)` → starts scapy sniffer threads,
  returns `(stop_event, bpf)`. BPF defaults to `tcp port 17935` (`--all-tcp`
  widens it). Exits the process on `--list-ifaces`.
- `map_capture.add_capture_arguments(ap)` → adds `--iface / --list-ifaces /
  --seconds / --dump / --all-tcp` to your argparser.
- `live_sniffer.LiveDecoder` → base decoder: per-flow TCP reassembly, finds the
  game stream **by frame shape** (not port), calls `emit(direction, env)` per
  decoded envelope. Subclass it and override `emit`.
- `map_capture.MapIndex(LiveDecoder)` → adds server-on-screen election + the
  `--dump` FrameLog; subclass **this** for any map-tile scanner.
- `run_output.open_run_file(subdir, name, label=None)` → `(handle, path)` for a
  fresh `results/<subdir>/<YYYYMMDD_HHMMSS>_[<label>_]<name>`; use it whenever a
  probe should keep its own record instead of overwriting the last run's. The
  optional `label` is free text (spaces → underscores) describing what the run
  is about — `live_sniffer.py` and `lua_trace.py` expose it as `--label`, and
  the panel's Develop menu asks for it before starting either. `LiveDecoder`
  takes such a handle as `transcript=` and writes one JSON object per message;
  that is how `live_sniffer.py` / `live_tshark.py` fill `results/traffic/`, and
  `lua_trace.py` fills `results/traces/`.

**Minimal skeleton** (run under the Windows Python):
```python
import argparse, sys, os, time
sys.path.insert(0, "tools")
from live_sniffer import LiveDecoder
from map_capture import add_capture_arguments, start_capture

class Dump(LiveDecoder):
    def emit(self, direction, env):
        import lastwar_proto as proto
        name = proto.envelope_command(env) or "(keepalive)"
        print(direction, name, proto.envelope_payload(env))

ap = argparse.ArgumentParser(); add_capture_arguments(ap, include_dump=False)
args = ap.parse_args()
index = Dump()
stop, _ = start_capture(index, args)          # threads running
try:
    time.sleep(args.seconds or 1e9)
except KeyboardInterrupt:
    pass
stop.set()
```

**Decoding (offline or inside `emit`)** — everything is in `lastwar_proto.py`
(alias it `proto`); this is the reference decoder, imported everywhere, never
copied:
- `proto.iter_frames(stream_bytes, direction)` → yields `(env, start, end)`.
  `direction` is `"down"` (server, magic `0x80`) or `"up"` (client, `0xc4`).
  Handles XOR mask, TLV, zlib/zstd. *(Live reassembly is `live_sniffer.Stream`
  — `feed(seq, data)` + `drain()`; you rarely call it directly.)*
- `proto.classify(data)`, `proto.envelope_command(env)`,
  `proto.envelope_payload(env)` → shape/name/body of an envelope.
- `proto.secret_tasks(payload)` → `[SecretTask]` from a `world.get.block` body.
- `proto.ghost_recon_tiles(payload)` → `[GhostReconMission]` likewise.

Decode a **saved `.pcapng`** (this runs fine under the WSL `python3`):
```bash
python3 tools/lastwar_proto.py results/capture.pcapng                 # survey + summary
python3 tools/lastwar_proto.py results/capture.pcapng --timeline      # every message
python3 tools/lastwar_proto.py results/capture.pcapng --grep chat
python3 tools/lastwar_proto.py results/capture.pcapng --json out.json
```
Don't pass `--port` — the client races several gateways and a second endpoint
(chat/login) would hide behind a port assumption.

Mining a `--dump` JSONL:
```bash
jq -r '.name' traffic.jsonl | sort | uniq -c | sort -rn        # command histogram
jq -c 'select(.name == "get.user.info.multi")' traffic.jsonl
jq -c 'select(.name == null)' traffic.jsonl                    # unnamed (only .action)
```

---

## 4. Common errors → fix

| Symptom | Cause | Fix |
|---|---|---|
| 0 packets / 0 frames, no error | Ran under the **WSL** Python | Use `/mnt/c/Python312/python.exe`. WSL sees none of the game's packets. |
| `scapy is not installed on this interpreter` | The capturing Python lacks scapy | `pip install scapy zstandard` on that interpreter (npcap itself ships with Wireshark). All four tools share this one transport. |
| `Unable to guess datalink type` / "npcap delivered N packets but none decoded" | scapy mis-maps the npcap linktype | Already worked around (frames re-parsed as Ethernet). If it persists, pin the right adapter with `--iface`. |
| "No packets at all" | Game not running, or wrong interface | Check the `:17935` ESTABLISHED line; `--list-ifaces` and pin `#13 vEthernet (…)`. |
| Empty capture, game clearly online | Idle base sends only keepalives; map tiles need motion | **Pan the map / open the screen** during the run. |
| Big server frames warn/fail to decode | `zstandard` missing | `pip install zstandard` on the **capturing** interpreter. |
| pcap decodes as mostly `tls` | Wrong pcap — some other process | The game is **not** TLS; re-capture the `:17935` socket only. |
| "unknown TLV tags" counter > 0 | **False alarm** — counts frames the decoder already discarded | Ignore; never document those tags. |

---

## 5. Protocol cheat-sheet

Full spec: [`../research/protocol.md`](../research/protocol.md).

**Transport:** one TCP connection to `…:17935`; XOR-masked, length-prefixed TLV
envelopes `{c, a, p:{…}}`, big frames zstd-compressed. **Not TLS.** Chat rides
the same socket. `_id` in a payload pairs a request with its reply; server
**pushes** carry none.

**Map tile kinds** (`world.get.block`, field `f2`):

| `f2` | Tile |
|---|---|
| `6` | player base (public profile inline: uid, name, HQ level, alliance) |
| `7` | resource mine |
| `17` | secret task (raidable) |
| `29` | ghost-recon mission ("Операция Призрак") |

**Key commands:** `world.get.block` (map tiles), `push.alliance.march.*`
(rallies/marches/trucks), `get.user.info.multi` (profile stats on click),
`al.rank` (alliance roster). Command names and payload fields are catalogued in
`protocol.md` and `tools/known_commands.txt`.

---

## 6. Decision cheat-sheet

- Specific stream as JSON → the matching `/mnt/c/Python312/python.exe tools/*_capture.py`.
- Watch commands live / new stream → §3 skeleton on `LiveDecoder` + `start_capture`.
- Saved `.pcapng` → `python3 tools/lastwar_proto.py <file>`.
- Command never captured → `python3 tools/trap_command.py --match <x>`, then do it by hand.
- Active work (inject/MITM) → stop; read the ACE rule and `sniffing-playbook.md` first.
- Need *which Lua function* an in-game action calls (not the wire) → §7.
- Automating an in-game action end-to-end (the everyday job) → **§8**.

---

## 7. Lua-function tracing (in-process — NOT passive wire)

The wire tells you *what bytes* cross the socket. Sometimes you instead need
*which client Lua function* fires for an in-game action, and with what arguments
— e.g. to learn that the "switch server" button calls
`CrossServerUtil.SetCrossEnableList(...)`. That is done by **monkey-patching**
the Lua function live through `tools/lua_eval.py` and reading `Player.log`.

> **Not passive.** `lua_eval.py` injects Lua by thread-hijacking the running
> process (see `../research/game-launch-and-scene-control.md`). It is the
> *active* side of the toolkit — emulator + throwaway account only, never a real
> account. The ACE rule at the top still applies.

**How it works.** Wrap the target with a shim that logs its args via
`CS.UnityEngine.Debug.LogError(...)` (which lands in `Player.log`), keep the
original in a global so you can restore it, perform the action in-game, then
grep the log.

**Arm** the trace (one or many functions — add `wrap(...)` lines as needed):
```bash
/mnt/c/Python312/python.exe tools/lua_eval.py --marker MP "
_G.__TRACE = _G.__TRACE or {}
local function argstr(...) local n=select('#',...) local s='' for i=1,n do s=s..i..':'..tostring(select(i,...))..' ' end return s end
local function wrap(tbl,name,tag)
  if not tbl or type(tbl[name])~='function' then return end
  local key=tag..'.'..name if _G.__TRACE[key] then return end
  local orig=tbl[name] _G.__TRACE[key]=orig
  tbl[name]=function(...) CS.UnityEngine.Debug.LogError('TRACE '..key..' <- '..argstr(...)) return orig(...) end
end
wrap(CrossServerUtil,'SetCrossEnableList','CSU')
wrap(CrossServerUtil,'OnCrossServer','CSU')
CS.UnityEngine.Debug.LogError('MP armed')"
```
`argstr` uses `select('#',...)` (not `ipairs`) so a `nil` in the middle of the
argument list is still logged. To capture a **table argument's contents** (only
its address prints otherwise), store it and dump it in the shim:
`_G.__CAP = arg` + a small `dump(t,depth)` walker that recurses to depth ~3 —
this is how the `{[0]={935},[1]={972}}` shape of the enable list was recovered.

**Read** the trace — the game appends to `Player.log`:
```bash
LOG=$(ls -t "/mnt/c/Users/"*"/AppData/LocalLow/FunFly/Last War-Survival Game/Player.log" | head -1)
grep -aE "TRACE " "$LOG" | tail -40
```

**Restore** — always, when done. The shims live in the running Lua state until
the game restarts; leaving them wrapped spams the log and slows hot functions:
```bash
/mnt/c/Python312/python.exe tools/lua_eval.py --marker UN "
local n=0
if _G.__TRACE then for key,orig in pairs(_G.__TRACE) do
  local tag,name=key:match('([^.]+)%.(.+)')
  local tbl=(tag=='CSU' and CrossServerUtil) or (tag=='GTU' and GoToUtil) or (tag=='SU' and SceneUtils)
  if tbl then tbl[name]=orig n=n+1 end
end _G.__TRACE=nil end
CS.UnityEngine.Debug.LogError('UN restored='..n)"
```
(Extend the `tag`→table map for any other holder table you wrap.)

**Workflow:** arm → perform the normal in-game action (you or the player) →
grep `Player.log` for `TRACE` → restore. This trace is what exposed the
cross-server `SetCrossEnableList` gate and its table shape
(`../research/world-tiles.md`). It is an ad-hoc technique, not a committed
script — re-arm it each session.

---

## 8. The basic workflow — one sniffer run → a working recipe

§1-§7 describe each tool alone. This section is the **standard loop** the project
actually runs: the player performs an action once with both sniffers on, and the
session ends with a committed `actions/*.md` recipe that reproduces it headlessly.
Everything below is the general procedure; `../research/alliance-tech-donate.md`
is one full worked instance of it, and `src/lastwar_bot/actions/help_ally.md` is
the instance where the trace came back empty (§8.11).

```
 1  panel: Develop → Sniffer ON, type a label, WAIT for the «[sniff] ГОТОВ» line
 2  the player performs ONE in-game action
 3  panel: Develop → Sniffer OFF   → the panel asks: keep it (+ describe what was
                                     done) or delete the run
 4  read the description:  python3 tools/sniff_runs.py --last 1
    missing?  ASK the player before analysing anything
 5  read results/traces/*<label>*_trace.log   (XSCALL — which Lua fired)
    read results/traffic/*<label>*_traffic.jsonl (wire — which command was sent)
 6  line the two up (order + the panel log; per-line timestamps exist only on the wire side)
 7  pin the real API by probing the LIVE Lua VM — the trace only nominates candidates
 8  add the named buttons to tools/lib/game_buttons.py
 9  write src/lastwar_bot/actions/<name>.md as TAP lines
10  run it from the panel's Scenarios tab, write the research note, commit
```

Steps 1-3 are the operator's; 4-10 are the worker's. The two files are the whole
handover: they answer the same question from opposite ends — *what the client
called* vs *what crossed the socket*.

### 8.1 Start the sniffer

**Panel (the normal way).** Menu **Develop → Sniffer** (`develop.sniff.toggle`;
«Разработка → Снифер» in the Russian UI). It asks once for a **session label** —
free text describing what is about to be done, in whatever language the operator
types — and hands the same label to **both** children, so the session's two files
share a name:

| child | command the panel spawns | writes |
|---|---|---|
| traffic | `live_sniffer.py --label <L>` | `results/traffic/<YYYYMMDD_HHMMSS>_<L>_traffic.jsonl` |
| functions | `lua_trace.py --dedup --label <L>` | `results/traces/<YYYYMMDD_HHMMSS>_<L>_trace.log` |

Both stream into the panel log tagged `[traffic]` / `[trace]`. Each start opens
**new** files, so a stop/start cycle never overwrites the previous session
(`tools/lib/run_output.py`). The label names the files; *what was actually done*
is asked at the **end** of the run (§8.3) and stored beside them.

**Neither child records the moment its pid appears — wait for the ready line.**
The pids are printed instantly, but npcap still has to open every interface and
the tracer still has to install ~8700 Lua wraps through the VM. Measured on this
machine: capture goes live ~0.7-1.0 s in, `XSTRACE installed` lands ~1.8 s in
with a warm `lua_daemon`, and later when `get_evaluator()` has to attach a fresh
`LuaEval` first. An action performed inside that window is simply not in the
files. So each child now prints its own verdict —

| child | ready marker | failure marker |
|---|---|---|
| traffic | `CAPTURE READY — N/M interface(s) live` | `CAPTURE FAILED — no interface could be opened` |
| functions | `[lua_trace] TRACE READY — hooks live` | `[lua_trace] TRACE FAILED — hooks not installed` |

— and the panel folds the pair into one line: **`[sniff] ГОТОВ (2.0 с) — оба
потока пишут, можно выполнять действия в игре`**. That line, not the pid, is the
go signal. `ЧАСТИЧНО ГОТОВ` means half the session is being lost; if nothing is
confirmed within 25 s the panel says so instead of waiting silently.

**Headless equivalent**, when there is no panel:

```bash
/mnt/c/Python312/python.exe tools/lib/live_sniffer.py --label "alliance gifts"   &
/mnt/c/Python312/python.exe tools/lua_trace.py --dedup --label "alliance gifts"
```

Prerequisites, in the order they bite:

1. The game is running **and logged in** — an ESTABLISHED `:17935` line (§1).
   No socket, no traffic.
2. Windows Python for the traffic side (§1). The WSL `python3` captures nothing,
   silently.
3. The Lua tracer needs the VM: it goes through `get_evaluator()`, i.e. the warm
   daemon `tools/lua_daemon.py` if it is up, otherwise a fresh local `LuaEval`
   (slower to start, same result).
4. `--dedup` is mandatory for a filterless run. Without it the tracer logs *every*
   call of ~8700 wrapped functions and **freezes the client**.

Sanity line in the trace file — read it before anything else:

```
XSTRACE installed wrapped=8730 depth=2 filter=none dedup=true hook=false
```

`wrapped=0`, a missing line, or `XSTRACE INSTALL ERROR:` means nothing was armed
and the run is void — fix that and re-record rather than analysing an empty file.

### 8.2 The player performs the action

Rules that make the recording readable — all of them are about keeping the
correlation in §8.6 trivial:

- **One action per run.** Two actions in one file cost more time to untangle than
  a second 30-second recording.
- **Short.** 15-60 s. The trace grows by every UI element the game rebuilds.
- **Start from a known screen** (base or world), do the action deliberately,
  once, then stop moving.
- **Don't pan the map / open unrelated windows** while recording — every panel
  the client opens adds a page of `UI*` churn to the trace.
- **Repeat the click a few times** when the action is counter-gated (donate,
  gifts) — that is how the counter's behaviour becomes visible on the wire.
- **Say what you did.** The label is the primary record; if the action has a
  sequence ("alliance → gifts → collect all"), the sequence matters more than the
  label text.

### 8.3 Stop — and say what was done

Toggle **Develop → Sniffer** off (it stops both children), or Ctrl+C the
standalone runs.

The panel then asks what to do with the recording — **«Запись снифера»**. The
dialog opens with what was actually captured (duration, and per file: path, size
and how much is in it — traced calls resp. decoded frames, which is what tells a
real run from an empty one), a description box, and two answers:

| answer | what happens |
|---|---|
| **Сохранить** (also the window's X, and `Ctrl+Enter`) | the run is kept; whatever was typed in the description box is written beside **both** files as `<stamp>_<label>_desc.txt` — same base name, `_desc.txt` instead of the file's own kind (`tools/lib/run_notes.py`) |
| **Удалить запись** | after a confirmation, the two files and their descriptions are deleted — a run that recorded the wrong thing is noise in a directory that is read by hand |

```
results/traces/20260728_155726_сокровище_trace.log
results/traces/20260728_155726_сокровище_desc.txt      <- "тапнул на сокровище и собрал его"
results/traffic/20260728_155731_сокровище_traffic.jsonl
results/traffic/20260728_155731_сокровище_desc.txt
```

The description file holds the operator's words and nothing else, so it can be
read straight into an analysis prompt ("what the player did: …").

**Fill the description in.** The two files say which Lua fired and what crossed
the wire; they never say which buttons were pressed, in what order, or what
changed on screen — and that is exactly what the analysis needs (§8.4 is the
list of questions; answering them here means they never have to be asked). An
empty box still keeps the files, the panel just logs that no description was
given. A run stopped without the panel (the headless pair) gets no prompt, so
attach the description afterwards:

```bash
python3 tools/sniff_runs.py --describe "alliance → gifts → collect all, ×3"
```

The tracer restores every wrapped function on exit — confirm it:

```
XSTRACE traced distinct=… calls=…
XSTRACE restored 8730
```

If instead you see `WARNING: restore not confirmed after retries`, the shims are
still live in the running Lua state (they persist until the game restarts, spam
`Player.log` and slow hot functions). Fix by re-running and stopping the tracer
once more, or restart the game.

### 8.4 Read the description first — no description? Ask

**Start every analysis here**, before opening either file:

```bash
python3 tools/sniff_runs.py --last 1      # the newest run: files + its description
python3 tools/sniff_runs.py ресурс        # runs whose label/description match
python3 tools/sniff_runs.py --undescribed # runs still missing one
```

It lists each recorded session — both files, their sizes, and the operator's
answer to «что делал в игре» (§8.3), read from the `_desc.txt` beside them. That
description is the context both files lack; read it as the statement of what the
run was supposed to record, and treat the files as the evidence for it.

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
have) **and** repeat it in the research note (§8.10). The file name only carries
the label, not the sequence.

### 8.5 Read the two files

#### a) `results/traces/*_trace.log` — which Lua fired

Format: raw `Player.log` lines the tracer tailed, one call per line —
`XSCALL <table.fn> <- <arg>, <arg>, …`. With `--dedup` only the **first** call of
each name is logged (the rest are counted and summarised at exit), so the file is
a *set of names in first-call order*, not a call count. Arguments are never
truncated.

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
- the sniffer missed it (§4): wrong interpreter/interface, or the game was not
  actually connected.

### 8.6 Line the two files up

Be aware of the asymmetry before trying anything clever:

| | timestamps | ordering |
|---|---|---|
| `*_traffic.jsonl` | yes, `ts` per line, 1 s resolution | wire order |
| `*_trace.log` | **no** — they are raw `Player.log` lines | first-call order (deduped) |

So there is no join key. What works, in order of effort:

1. **One action per run** (§8.2). Then both files describe the same 30 seconds and
   correlation is reading, not joining.
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

### 8.7 Pin the API on the live VM

**The trace nominates candidates; it does not prove the API.** Every recipe in
this repo was finished by probing the running game through the Lua VM — the warm
daemon (`tools/lua_daemon.py` + `tools/lib/lua_client.py`) or
`tools/lib/lua_eval.py` directly. Results come back through `Player.log`, because
`SafeDoString` returns nothing and swallows errors (`../research/xlua-state.md`).

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
    count_lua=_lua_actions.alliance_help_pending(),  # enables `xall`
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

`src/lastwar_bot/actions/<name>.md`, in `TAP` notation — the everyday form is a
list of button presses with a comment header explaining the flow and its limits.
Grammar: [`../dsl.md`](../dsl.md); authoring conventions:
[`../actions-authoring.md`](../actions-authoring.md).

```
# Donate to the alliance's priority (recommended) technology.
#
# Every line is just "tap a button". The messy engine calls behind each button
# live in the button library tools/lib/game_buttons.py.

TAP alliance_tech     # the "Alliance Tech" button (opens the tech list directly)
TAP recommended_tech  # the tech marked as priority
TAP donate_1000 xall  # press "Donate 1000" for every attempt currently banked
TAP close x3          # close the windows we opened
```

The patterns that keep recurring:

| pattern | when |
|---|---|
| `TAP <b> xall` | counter-gated repeats — donate, help, claim. Needs `count_lua`; re-reads the count each round, so it stops exactly when the server says so. |
| `TAP <b> xN` | fixed, known repeats (rare — prefer `xall`) |
| `TAP close xN` | unwind the window stack at the end — `close` pops the top window (`Ctrl:CloseSelf()`), so press it once per window the recipe opened. `donate_alliance_tech.md` ships `x3`. Don't over-press: past the recipe's own windows you start popping the HUD, and there is no in-session recovery from that. |
| no `close` at all | the action was headless — a data-manager call that opened nothing (`help_ally.md`). Do not add windows the flow does not need. |
| `WHILE <var> > 0` + `READ_LUA … INTO <var>` | a bespoke count-gated loop when `xall` does not fit |
| `LUA <chunk>` | the authoring layer — a one-off engine call while a button is still being designed. Do not ship a whole multi-step flow inside one `LUA`. |
| `GAME WORLD` / `GAME CITY`, `JUMP x, y[, server]` | scene switch / coordinate jump sugar |

Write the header comment as if for someone who never saw the trace: what the
in-game action is, which single Lua call is behind it, whether a window is
involved, and **what the daily limit really counts** (for `help_ally` it is help
*points*, not helps — a distinction that only came out of §8.7 probing).

New scripts land in `src/lastwar_bot/actions/dev/` until they are verified
end-to-end; promote to `actions/` (which is what the panel's Scenarios picker
lists) once they are.

### 8.10 Verify, document, commit

1. **Parse:** `python -X utf8 -c "from lastwar_bot import script_engine; print(script_engine.parse_file(script_engine.ACTIONS_DIR / 'NAME.md'))"`
2. **Run:** panel → **Scenarios** tab → pick the script → Run. A game-primitive-only
   recipe runs with `hwnd=0`, no window handle needed.
3. **Watch it on the wire:** keep the traffic sniffer on during the first run.
   The recipe is correct when it produces **the same `up` commands** as the
   human's recording did. That is the acceptance test.
4. **Write the research note** — `docs/research/<feature>.md`, following
   `alliance-tech-donate.md`: which labelled trace it came from, what the trace
   showed, what had to be live-probed, the API table, the freeze pitfalls, and
   the usage lines. Name the source files by path; `results/` is git-ignored, so
   the note is the only durable record of the session.
5. **Add any new wire command** to `tools/known_commands.txt`.
6. **Commit** the recipe + buttons + note together, and say in the message what
   was recorded vs what was live-probed (see `feat(alliance): help every
   alliancemate via OnHelpAll`).

### 8.11 The trace came back empty — what then

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

Write down in the commit and the research note that the API was **live-probed
because the trace was empty**. That single sentence saves the next session from
re-recording a trace that will be empty again.

### 8.12 Quick reference

```bash
# record (panel Develop → Sniffer does both, with one shared label)
/mnt/c/Python312/python.exe tools/lib/live_sniffer.py --label "<label>" &
/mnt/c/Python312/python.exe tools/lua_trace.py --dedup --label "<label>"

# analyse — the description of what was done comes first
python3 tools/sniff_runs.py --last 1
L=$(ls -t results/traces/*_trace.log | head -1); T=$(ls -t results/traffic/*_traffic.jsonl | head -1)
grep -c XSCALL "$L"
grep XSCALL "$L" | grep -vE '\.(getters|super)\.' | grep -E 'DataCenter\.|Utils?\.|Message|SFSObject\.'
jq -r 'select(.dir=="up" and .cmd!="(keepalive)")|[.ts,.cmd]|@tsv' "$T"

# probe
/mnt/c/Python312/python.exe tools/lib/lua_eval.py --marker P "CS.UnityEngine.Debug.LogError('P '..tostring(<expr>))"

# ship
#   tools/lib/game_buttons.py     -> one Button per press (lua / wait / label / count_lua)
#   src/lastwar_bot/actions/*.md  -> TAP lines
#   docs/research/<feature>.md    -> the durable record
```
