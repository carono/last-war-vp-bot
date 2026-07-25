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
/mnt/c/Python312/python.exe tools/secret_mission_capture.py              # stream, print
/mnt/c/Python312/python.exe tools/secret_mission_capture.py --done       # only lootable-now
/mnt/c/Python312/python.exe tools/secret_mission_capture.py --server 991,992 --json out.json
```

### `ghost_recon_tile_dump.py` — every `f2 = 29` tile, no filter
Diagnostic twin of the mission scanner: dumps all ghost-recon tiles plus the
off-map ghost-recon polls, and cross-references them by uuid/coordinate. Use it
when the mission scanner shows nothing and you need to know whether the tile is
on the wire at all.
```bash
/mnt/c/Python312/python.exe tools/ghost_recon_tile_dump.py --seconds 300 --json out.json
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
