# Skill — capture Last War traffic (record a session yourself)

Everything here is for **producing** a recording: running the sniffers, capturing
a new stream, tracing which Lua fired. You only need this page when you are the
one at the keyboard sniffing. **Already have a recorded session** (a
`results/traffic/*_traffic.jsonl` + `results/traces/*_trace.log` pair) and want to
turn it into a recipe? That job is [`sniff.md`](sniff.md) — do not read this page
for it.

The *why* (anti-cheat, protocol format) lives in
[`../research/protocol.md`](../research/protocol.md),
[`../research/sniffing-playbook.md`](../research/sniffing-playbook.md) and
[`../../tools/README.md`](../../tools/README.md).

> **ACE rule.** §1-§6 are **passive capture** — transparent to the anti-cheat.
> MITM / Frida / socket injection is not; emulator + throwaway account only.
> §7 (Lua-function tracing) is the **in-process, active** exception — it injects
> Lua by thread-hijacking; same emulator + throwaway-account rule applies.

This page is §1-§7 (the toolkit) plus **§8.1-§8.3** (recording a session). The
analysis half of §8 — §8.0 and §8.4-§8.11 — is in `sniff.md`; the two share the
§8 numbering with no overlap.

---

## 1. Environment — what works

| Fact | Value |
|---|---|
| **Interpreter for capture** | `/mnt/c/Python312/python.exe` — the **Windows** Python. Sees `C:` and `D:`, has scapy + npcap. |
| **Never** use for capture | The WSL `python3`. WSL2 is a NAT'd VM; its sockets **cannot see** the Windows game's packets — it captures nothing, silently. |
| **Capture interface** | `#13 "vEthernet (Создать виртуальный коммутатор)"` — the Hyper-V virtual-switch adapter. Confirm with `--list-ifaces`; the number can shift, the name is the anchor. |
| **Game endpoint** | TCP `<server-ip5>:17935` (server IP changes per session — match by **port 17935**, not IP). |
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
- Automating an in-game action end-to-end (record it → §8.1-§8.3 below, then analyse it → `sniff.md`).

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
`CS.UnityEngine.Debug.LogError(...)`, keep the original in a global so you can
restore it, perform the action in-game, then grep the log.

> **A shim that logs LATER must say so.** Put `LW_GAME_LOG` in a comment in the
> install chunk, as `tools/lua_trace.py` does. Without it the shim captures the
> `CS` that `lua_eval` shadows for the length of a chunk and writes the whole
> recording into the private answer file instead of `Player.log`, where nothing
> tails it — the trace simply comes out empty
> (`../research/game-call-latency.md`).

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
this is how the `{[0]={100},[1]={300}}` shape of the enable list was recovered.

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

## 8. Recording a session (§8.1-§8.3)

The panel's **Develop → Sniffer** runs both sniffers at once and hands the pair
of files to the analysis workflow in [`sniff.md`](sniff.md). These three steps
are the operator's; the moment the run is saved, the job crosses over to
`sniff.md` §8.0.

### 8.1 Start the sniffer

**Panel (the normal way).** Menu **Develop → Sniffer** (`develop.sniff.toggle`;
«Разработка → Снифер» in the Russian UI). It asks once for a **session label** —
free text describing what is about to be done, in whatever language the operator
types — and hands the same label to **both** children, so the session's two files
share a name:

| child | command the panel spawns | writes |
|---|---|---|
| traffic | `live_sniffer.py --label <L>` | `results/traffic/<YYYYMMDD_HHMMSS>_<L>_traffic.jsonl` |
| functions | `lua_trace.py --filter SFS --label <L>` | `results/traces/<YYYYMMDD_HHMMSS>_<L>_trace.log` |

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
/mnt/c/Python312/python.exe tools/lua_trace.py --filter SFS --label "alliance gifts"
```

Prerequisites, in the order they bite:

1. The game is running **and logged in** — an ESTABLISHED `:17935` line (§1).
   No socket, no traffic.
2. Windows Python for the traffic side (§1). The WSL `python3` captures nothing,
   silently.
3. The Lua tracer needs the VM: it goes through `get_evaluator()`, i.e. the warm
   daemon `tools/lua_daemon.py` if it is up, otherwise a fresh local `LuaEval`
   (slower to start, same result).
4. A filterless run **must** have `--dedup`, or the tracer logs *every* call of
   ~8700 wrapped functions and **freezes the client**. But do not record a session
   that way — see the warning below. Narrow with `--filter` and keep every call.

**`--dedup` records which functions exist, not what somebody did.** It keeps only
the FIRST call of each name and counts the rest, so a player who opens a window,
picks an amount, confirms and later collects leaves *one* `UIButton.GetClickSound`
and *one* `SFSNetwork.SendMessage` in the file. The other three actions, the second
message, and every repeat of `SFSObject.PutInt` are dropped at write time — no
amount of re-reading recovers them, and the gaps read exactly like "the player
never pressed that". This cost task #1115 hours of chasing a message that looked
absent (`queue.finish`) and an `armyArray` that looked like a single entry. Several
keywords are allowed, so one narrow run covers both the wire and its caller:
`--filter SFS`, which is what the panel now spawns — it covers the whole wire and
fires only when a message is built.

Sanity line in the trace file — read it before anything else:

```
XSTRACE installed wrapped=61 depth=2 filter="SFS" dedup=false hook=false
```

`dedup=true` in a file you are about to analyse as a session means the repeats are
already gone; re-record instead of drawing conclusions from what is missing.

`wrapped=0`, a missing line, or `XSTRACE INSTALL ERROR:` means nothing was armed
and the run is void — fix that and re-record rather than analysing an empty file.

### 8.2 The player performs the action

Rules that make the recording readable — all of them are about keeping the
correlation (`sniff.md` §8.6) trivial:

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
changed on screen — and that is exactly what the analysis needs (`sniff.md` §8.4
is the list of questions; answering them here means they never have to be asked).
An empty box still keeps the files, the panel just logs that no description was
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

> **The panel's Stop reaches the same clean state, by a different route** (task
> #1084). It cannot Ctrl+C the child — it launched it — so it first drops the
> tracer's `--stop-flag` file, which breaks the tail loop and runs the same
> `restore()` + file close on the way out; if the child has not gone within ~1.5 s
> it is hard-killed, and either way the panel runs an idempotent `RESTORE_CHUNK`
> over the daemon as a safety net (it reports "nothing installed" when the child
> already cleaned up). So a run stopped from the panel unwraps the VM too — earlier
> it did not, because the hard `TerminateProcess` skipped both the atexit and the
> finally.

---

**Recording saved → analyse it:** [`sniff.md`](sniff.md) §8.0 is the strict
checklist that turns the pair of files into a committed recipe.
