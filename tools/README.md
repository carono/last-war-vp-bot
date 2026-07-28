# tools/ — network-protocol analysis toolkit

Helper scripts for investigating Last War's server protocol (task #366).
Background and the go/no-go reasoning live in
[`../docs/research/`](../docs/research/) — read
`network-protocol-sniffing.md` and `sniffing-playbook.md` first.

> **⚠️ Anti-cheat.** The game's official client runs Tencent **ACE** (Ring-0).
> **Passive** work (capture in Wireshark, `analyze_pcap.py`) is transparent to
> it. **Active** work (mitmproxy MITM + CA install, `unity_ssl_unpin.js` /
> Frida) is exactly what ACE detects → crash/ban. Run active steps **only on an
> Android emulator build with a throwaway account**, never on the official
> client or the operator's own main account.

## Layout

The directory is split by role. **Run every script from the repo root** (paths like
`tools/rally_join.py` and the `tools/lib` import path are resolved relative to the CWD).

- **`tools/`** — human-verified production entrypoints, the ones confirmed working live:
  `rally_join.py` (rally listen/join/decline + squad select), `rally_monitor.py` (live
  rally capture), `lua_trace.py` (live Lua tracer), `lua_daemon.py` (the warm Lua
  evaluator behind them), `goto_coord.py` (jump to a tile), `attack.py` (attack /
  scout an enemy base), `chat_reader.py` (read world/national/alliance chat off the
  Lua VM), `chat_send.py` (send text / emoji / stickers / coordinates),
  `dispatch_tasks.py` (list the secret tasks the client knows),
  `secret_task_capture.py` (find secret tasks), `scan_leaderboard.py`,
  `scan_players.py`, `extract_hero_icons.py` and `extract_chat_assets.py` (pull
  hero-icon / chat-emoji / sticker sprites from the bundles).
  `chat_assets.py` sits here too, next to the two consumers it pairs with
  (`chat_reader.py` and the panel's Chat tab), but is a module, not an entrypoint:
  it maps a chat token (`[e:E006]`, `[sticker:35]`, `[photo:429]`) onto a local
  PNG/JPG path via the id→stem table in `tools/data/chat_assets_map.json`.
- **`tools/lib/`** — shared modules imported by the entrypoints (not run directly): the Lua/
  il2cpp stack (`lua_eval`, `lua_client`, `lua_actions`, `xlua_route`, `il2cpp_probe`,
  `il2cpp_dump`, `hijack_call`, `rip_gate`, `find_instance_rpm`, `lua_goto_world`), the
  capture stack (`lastwar_proto`, `live_sniffer`, `live_tshark`, `map_capture`,
  `lastwar_encode`), and helpers (`coords`, `chat_share` — build and send chat
  coordinate attachments, `hero_icons_map`, `steal_via_socket`, `run_output` — the
  per-run timestamped file under `results/`).
- **`tools/dev/`** — working-but-not-yet-human-verified entrypoints: captures
  (`secret_mission_capture.py`, `watch_rally.py`, `rally_report.py`), world actions
  (`cross_server.py`, `city_click.py`, `solo_attack_direct.py`,
  `ghost_recon_tile_dump.py`, `collect_base_resources.py`, `gather*.py`) and scanners
  (`scan_resources.py`, `scan_trucks.py`). Promote to `tools/` once verified live.
- **`tools/archive/`** — superseded approaches, one-offs, tests, old probes. Kept for
  reference; not part of the bot.
- **`tools/scratch/`** — throwaway RE probes (git-ignored).

## Which side runs what

| Script | Side | Purpose |
|---|---|---|
| `find_lastwar_connections.ps1` | **Windows** (PowerShell) | find the game PID + its TCP endpoints/ports |
| `lastwar_dissector.lua` | **Windows** (Wireshark) | decode custom length-prefixed TCP frames |
| `lastwar_mitm_addon.py` | either (mitmproxy) | log + protobuf-decode HTTP/WS via MITM |
| `unity_ssl_unpin.js` | **Windows** (Frida) | dump TLS plaintext from Unity BoringSSL |
| `analyze_pcap.py` | **WSL** (Python) | superseded — use `lastwar_proto.py` |
| `lastwar_proto.py` | **WSL** (Python) | decode a saved `.pcapng` — the reference decoder |
| `lastwar_encode.py` | **WSL** (Python) | build client frames — the mirror of the decoder |
| `trap_command.py` | **WSL** (Python) | record a command the captures have never shown |
| `steal_via_socket.py` | **Windows** (Python) | feasibility harness for duplicating the client socket — see [`../docs/research/socket-duplication.md`](../docs/research/socket-duplication.md) |
| `relay.py` | **Windows** (Python) or **Linux/emulator** | userland asyncio MITM relay — inject a command and see its reply, see [`../docs/research/command-injection-vectors.md`](../docs/research/command-injection-vectors.md) |
| `live_sniffer.py` | **Windows** (Python, admin) | decode live via scapy — see caveat below |
| `live_tshark.py` | **WSL** (Python) | decode live by driving Wireshark's `dumpcap.exe` — **preferred** |
| `secret_task_capture.py` | **Windows** (Python) | stream secret tasks (raidable map tiles) live via scapy/npcap, no Wireshark binaries spawned |
| `secret_mission_capture.py` | **Windows** (Python) | stream **secret missions** — "Операция Призрак" / ghost recon (`ghost.recon.*`) live via scapy/npcap, no Wireshark binaries spawned; `--discover` catches a new command family when the seasonal feature shifts |
| `ghost_recon_tile_dump.py` | **Windows** (Python) | dump **every** `world.get.block` tile of **every** `f2` kind (no filter), learn active ghost-recon missions off the same connection, and cross-reference the two by uuid and by coordinate — the test of whether a ghost-recon mission shows up as a map tile at all (task #1010) |
| `scan_players.py` | **Windows** (Python) | sweep player bases (name / HQ level / alliance) off the map into JSON |
| `scan_leaderboard.py` | **Windows** (Python) | collect ranking screens (name / uid / position / score) into JSON as you open them |
| `scan_trucks.py` | **Windows** (Python) | index the trucks moving on the map (type / level / position / cargo / robbed count) |
| `map_capture.py` | **Windows** (Python) | shared capture + which-server-is-on-screen logic behind the scanners |
| `watch_captures.sh` | **WSL** (bash) | auto-decode captures dropped into `results/` |
| `attack.py` | **Windows** (Python, Lua daemon) | attack (`ATTACK_CITY`) or scout (`SCOUT_CITY`) an enemy base without clicking, and read back the scout report — see [`../docs/research/attack-and-scout.md`](../docs/research/attack-and-scout.md) |
| `chat_reader.py` | **Windows** (Python, Lua daemon) | read world / national / alliance chat live off the Lua VM (no sniffing, chat window need not be open) — see [`../docs/research/chat-lua-readout.md`](../docs/research/chat-lua-readout.md) |
| `chat_send.py` | **Windows** (Python, Lua daemon) | send a DM / channel message: text, inline emoji, stickers — see [`../docs/research/chat-send.md`](../docs/research/chat-send.md) — and map coordinates (`--coords` / `--my-base` / `--coord-extra`) — see [`../docs/research/chat-coord-share.md`](../docs/research/chat-coord-share.md) |
| `dispatch_tasks.py` | **Windows** (Python, Lua daemon) | list the secret tasks ("секретки") the client already knows, straight off the Lua VM — no capture and no map panning; `--share-args` prints ready `chat_send.py` arguments |
| `extract_chat_assets.py` | **WSL** or **Windows** (Python, UnityPy) | extract chat emoji / sticker sprites from the cached asset bundles into `results/chat_assets/` |

Capture (Wireshark/Npcap) must run **on Windows** — WSL2 is a separate NAT'd VM
and cannot see the Windows game's traffic directly. WSL is for offline analysis
of a `.pcapng` you saved on Windows, and for running mitmproxy (with
`networkingMode=mirrored`, see playbook §0).

## Live decoding from WSL (preferred)

Scapy's own sniffing did not see any traffic against npcap on this machine.
Wireshark does, and WSL can execute Windows binaries — so `live_tshark.py`
drives `dumpcap.exe` (the capture engine Wireshark itself uses), reads the pcap
stream off its stdout and decodes it as it arrives. It reuses the framer and
the stream reassembler; it is only a transport.

```bash
python3 tools/live_tshark.py --list        # interfaces, each probed for traffic
python3 tools/live_tshark.py --iface 2     # decode on one interface
python3 tools/live_tshark.py               # decode on all of them
python3 tools/live_tshark.py --discover    # every TCP flow, decode nothing
```

No Administrator prompt is needed as long as npcap was installed with the
"allow non-administrator capture" option — which is Wireshark's default.

Wireshark is found automatically under `/mnt/c/Program Files/Wireshark`;
override with `--tshark` / `--dumpcap`.

Every run also saves what it decodes to its **own** file,
`results/traffic/<YYYYMMDD_HHMMSS>_traffic.jsonl` — one JSON object per message
(`{ts, dir, cmd, payload}`, full payload regardless of `--raw`). Restarting the
sniffer therefore never overwrites the previous session, and two sessions never
end up interleaved in one file. `--out PATH` picks the file, `--no-out` decodes
to the terminal only. Same flags, same layout in `live_sniffer.py`.

**Note on interfaces.** The game's traffic showed up on both the wireless
adapter and the network bridge, and *not* on the OpenVPN adapter — so an active
VPN does not necessarily mean the traffic is on its virtual interface. Run
`--list` and pick whichever is busy, or omit `--iface` to capture on all.

## Live decoding on Windows (scapy)

> Scapy sniffing did **not** work on the machine this was developed against —
> it saw no packets at all. Prefer `live_tshark.py` above. This script is kept
> because it is the same decoder and may work elsewhere.


`live_sniffer.py` sniffs the game port and prints decoded commands as they
happen. It imports the framer from `lastwar_proto.py`, so both tools always
speak the same protocol.

```powershell
# once — npcap must already be installed
pip install scapy colorama zstandard

# then, in an *Administrator* PowerShell, from the repo root:
python tools\live_sniffer.py
```

`zstandard` is not optional in practice: large server frames (including the
445 KB `init` sent at login) are zstd-compressed and will not decode without
it. The script warns and keeps going if it is missing.

Useful flags: `--iface "Ethernet"` to pin an interface, `--list-ifaces`,
`--raw` to dump full payloads, `--port` to narrow the capture filter,
`--out` / `--no-out` for the per-run JSONL transcript (see above).

There is deliberately **no port or IP filter**. The game's address changes
between sessions, and the client races several gateways at login, so anything
pinned loses traffic. The game stream is found by **frame shape** instead: a
valid flag byte, a frame that parses, and an envelope of the form
`{c, a, p:{…}}`. The detected endpoint and port are printed when found.

Detection also works when the game is **already running** — the sniffer
resyncs to the next frame boundary, and keeps re-probing as new data arrives so
that attaching in the middle of a large frame (the 68 KB compressed `init`)
does not write the stream off.

### If nothing appears

```powershell
python tools\live_sniffer.py --discover
```

Lists every TCP flow crossing the interface with its opening bytes and a shape
guess (`TLS`, `HTTP`, `GAME?`, `unknown`). If no flow is marked `GAME?`, the
game's traffic is not on that interface — check `--list-ifaces`, and check
whether the game is routed through a VPN adapter.

## Sweeping player bases (`scan_players.py`)

Every `f2 = 6` tile is a player's base and carries their public profile inline
— uid, name, HQ level, alliance id and abbreviation, country (protocol.md §7).
So a map sweep collects a roster with no OCR and without opening a single
profile screen.

```powershell
# from the repo root, under the Windows Python (npcap + scapy + zstandard)
python tools\scan_players.py --json results\players.json
python tools\scan_players.py --alliance VP --seconds 300
python tools\scan_players.py --level 30,31 --json results\hq30.json
```

Records are deduplicated by `(server_id, uid)` and re-stamped with `seen_at`
each time the map re-sends the tile. `--alliance` / `--level` narrow what is
*collected*, so the JSON and the console always agree; each run rewrites the
file rather than appending to it.

**Clicking bases while it runs adds their combat stats.** A click makes the
client ask `get.user.info.multi` for that uid, and the reply carries what the
tile does not — `power`, `armyPower`, `armyKill`, `svipLevel`. The scanner
listens for those replies and folds them into the matching record, or files a
new one (with null coordinates) if the click landed on a player the sweep
never passed over. Clicking before or after the tile arrives gives the same
result. So the usual session is: pan the map to collect the roster, then click
through whichever bases you want numbers for — one run, one file.

### Your notes on players (`remark`)

The private note you can write on another player in the client is **stored
server-side**, not locally. The client fetches the whole list with
`user.remark.list` (paginated, 500 per page) **once at login**, and the scanner
merges it into the matching records as `remark`.

That timing is the catch: **start the scan before logging into the game**, or
the list never crosses the wire and no record gets a note. Notes are keyed by
uid alone — a note follows the player, not their base — so one applies on
whichever server that player turns up on, and it survives a later profile
lookup rather than being overwritten by it.

Most notes are for players a given run never passes over: of the 869 in the
saved capture, 276 landed on a collected record. The closing summary reports
both numbers so the difference is not mistaken for a merge failure.

A note is **not** on the `f2 = 6` tile and not on the profile, which was
tested rather than assumed: the literal note text appears nowhere else in the
capture, and across 1094 base tiles no field is present on the 276 belonging
to noted players and absent from the other 818. The command that *writes* a
note has never been captured — every note in the capture was last edited 17
hours before it started — so this is read-only knowledge.

## Collecting rankings (`scan_leaderboard.py`)

A ranking crosses the wire **only when you open its screen** — the whole board
arrives in one reply, and nothing pushes it. So this scanner cannot make
anything happen: start it, then walk the ranking screens you want.

```powershell
# from the repo root, under the Windows Python (npcap + scapy + zstandard)
python tools\scan_leaderboard.py --json results\ranks.json
python tools\scan_leaderboard.py --board al.rank --seconds 300
python tools\scan_leaderboard.py --known-only --json results\ranks.json
```

Rows are deduplicated by `(uid, leaderboard)`, so re-opening a board refreshes
what it says about a player rather than appending them again, while the same
player on two boards stays two records — their score means a different thing
on each, which is what `score_field` names.

**`position` is often null, and that is the honest answer.** The field called
`rank` is the placement on some boards and something else on others: in
`al.rank` it is the alliance role (R1..R5), and that board arrives in no
sorted order, because the client sorts it locally by whichever column you
picked. The position on that screen was never on the wire. So a position is
reported only where it can be had honestly, and `position_source` says how —
`"field"` when the board numbered the row itself (verified to really be
`1..N`), `"order"` when the board stated nothing but the server sent the list
sorted, `null` when neither. `list_index` always says where the row sat in the
frame. See protocol.md §5 → Rankings.

**Not every board is about players.** The alliance ranking (`rank.get`, type
2) has alliances for rows: `uid` is an alliance id and `name` is the
alliance's. The `entity` field says which kind a row is — an alliance id must
not be joined against a player uid. Where one command serves several rankings
the board id carries the variant (`rank.get/type=2`), so opening another type
files its own board; `--board rank.get` matches every variant of it.

**Boards nobody has decoded are collected too.** Two are described in
`lastwar_proto.py` because two are what the captures hold; any other ranking
is recognised by shape — ≥3 players each with a uid, a name and a score or
rank column — and those rows carry `"discovered": true` so a reader can tell a
column the protocol file vouches for from one a heuristic picked. Replayed
over both saved captures the shape test found the two real boards and nothing
else, but a board it has never seen is still a guess: `--known-only` restricts
the run to the described ones.

### Recording everything (`--dump`)

All three scanners take `--dump <path>` and write **every** decoded frame, in both
directions, as JSONL — one `{"seq", "ts", "direction", "name", "action",
"payload"}` object per line. It is the companion to a clicking session: the
sweep's own JSON keeps only what the tool understands, while the transcript
keeps everything it does not, so a run can be mined afterwards for whatever
else the client asks and the server answers.

```powershell
python tools\scan_players.py --json results\players.json --dump results\traffic.jsonl
```

```bash
jq -r '.name' traffic.jsonl | sort | uniq -c | sort -rn    # what commands appeared
jq -c 'select(.name != "world.get.block")' traffic.jsonl  # drop the bulky map frames
jq -c 'select(.name == "get.user.info.multi")' traffic.jsonl
jq -c 'select(.name == null)' traffic.jsonl               # frames only .action names
```

`payload` is the decoded body, which is where `_id` lives — that is what pairs
a request with its reply (915 of 1336 frames in the replayed capture had one;
the rest are server pushes, which answer nothing). `action` is the envelope's
numeric `a`, kept because it is the only identifier on a frame the decoder
could not name — 58 frames of that replay had no command string, and those are
exactly what a transcript is read for. JSONL rather than one JSON array so the file is
readable while the run is still going and a process killed mid-write costs one
line, not the file. Expect volume: over a 1336-frame sample the transcript was
8.8 MB, of which `world.get.block` was 54% and `push.world.march.world.get.new`
another 23%. The running size is printed on every progress tick.

Every profile field was checked against the saved captures: `power`,
`armyPower`, `armyKill` and `svipLevel` are present on all 95 profiles seen,
and where a player appeared as both a tile and a profile (59 uids) the two
sources agreed 59/59 on level, server, name, alliance id and abbreviation.

The game only sends map data while the map is **moving**, so keep panning for
the whole run — a run with zero map responses means nobody was dragging, not
that the capture failed. The closing traffic line distinguishes the two.

Both this and `secret_task_capture.py` sit on `map_capture.py`, which owns the
transport and the rule for deciding which server's map is on screen (weight of
recent traffic, overruled by a `meteorite.enter.world` the client announces).
A base sweep keeps what it collected across a server change; a task capture
drops it, because dispatch timers keep running on a map nobody is watching.

## Finding trucks (`scan_trucks.py`)

Trucks are the one thing on the map that is **not a tile**. They ride the march
stream as marches of type 37 carrying a `train` object, so `world.get.block`
never mentions them and a scan built on map blocks finds none. This one listens
to the march stream instead — see protocol.md §7 → Trucks.

```powershell
# from the repo root, under the Windows Python (npcap + scapy + zstandard)
python tools\scan_trucks.py --json results\trucks.json
python tools\scan_trucks.py --type gold,sled --can-loot
python tools\scan_trucks.py --type 5 --level 34,35 --seconds 300
python tools\scan_trucks.py --not-alliance <your allianceId>
```

Unlike a task capture this does **not** need the map to be moving: the server
pushes marches unprompted. Panning still helps — it is what makes the server
volunteer the marches of the patch you pan over.

Each truck reports its type, level, interpolated position, server, owner uid,
alliance, escort power and squad, cargo total, and how many of its four
robberies are spent. `--can-loot` keeps the ones still running with a robbery
left. That is the wire's answer and it is narrower than the game's: whether
*you* may rob a given truck also depends on your own alliance (`--not-alliance`
covers that) and on your remaining daily attempts, which are not on the wire at
all.

**Position is interpolated, not reported.** A truck hops station to station and
the server describes only the current hop — where it set out (`startPos`) and
when the whole run ends (`arriveTime`) are both something else. So a truck that
stops being re-sent goes on gliding down a route it may have left, which is
what the 15-minute freshness window is for.

**The colour names are inferred and have never been checked by eye.** The
cargo ordering proves the *ranks* are graded (see protocol.md §7 → Trucks);
which colour the client paints each rank is not on the wire. `--type` takes
tier numbers 1-5 as well as names, which is what the wire actually says.

## Step-by-step

### 0. Python env (WSL, one-time)
```bash
cd /path/to/last-war-vp-bot   # the repo root
python3 -m venv .venv
.venv/bin/pip install mitmproxy blackboxprotobuf pyshark scapy
# pyshark also needs tshark:  sudo apt install -y tshark
```

### 1. Find the transport (Windows)
```powershell
# in the repo root on the Windows side, with the game running
powershell -ExecutionPolicy Bypass -File .\tools\find_lastwar_connections.ps1 -Watch -IncludeUdp
```
Note the **distinct remote ports** it prints. That answers "which host/port is
the gameplay channel" and gives you the Wireshark filter + the port for the
dissector.

### 2a. Passive capture (Windows, ACE-safe)
Open **Wireshark** on the physical/emulator adapter. Apply the filter the script
printed (`tcp.port == <p> || ...`). Classify streams by their first bytes
(`16 03 03` = TLS, `GET ... Upgrade: websocket` = plaintext WS, repeating
length-prefix = custom TCP). Save as `capture.pcapng`, then analyze in WSL:
```bash
.venv/bin/python tools/analyze_pcap.py /mnt/c/Users/you/capture.pcapng --port 9339
# → results/analysis_<timestamp>.json
```
If everything comes back `tls`, the pcap is encrypted — you need §2b or §3.

### 2b. Custom binary → dissector (Windows, Wireshark)
Edit `lastwar_dissector.lua`: set `LASTWAR_PORTS = { <your_port> }`, confirm the
frame layout against a hex dump (endianness / whether `length` includes the
opcode). Copy it to `%APPDATA%\Wireshark\plugins\` → Analyze → Reload Lua
Plugins. Frames now decode as `LASTWAR` with Length/Opcode/Body.

### 3. MITM to see decrypted HTTP/WS (EMULATOR + throwaway account)
```bash
# WSL (with networkingMode=mirrored) or Windows:
.venv/bin/mitmweb -s tools/lastwar_mitm_addon.py --listen-port 8080
# optionally scope logging to the game host:
LASTWAR_HOST_FILTER=lastwar .venv/bin/mitmdump -s tools/lastwar_mitm_addon.py
```
Install the mitmproxy CA into the client's trust store, route the client through
`:8080` (Proxifier on Windows, or emulator proxy). See playbook §2/§4.
Output: `results/traffic_<ts>.jsonl` + raw bodies in `results/raw/`.

### 4. TLS plaintext via Frida (EMULATOR / unprotected build only)
```bash
frida -f "C:\path\to\LastWar.exe" -l tools/unity_ssl_unpin.js --runtime=v8
```
If SSL_read/SSL_write aren't exported, recover their RVAs with Il2CppDumper +
IDA/Ghidra and fill in the offsets at the top of the script.

### 5. Protobuf decoding
`lastwar_mitm_addon.py` and `analyze_pcap.py` both auto-try
`blackboxprotobuf`; `analyze_pcap.py` also shells out to `protoc --decode_raw`
if `protoc` is installed. To recover real field *names*, dump the `.proto` from
`GameAssembly.dll` with Il2CppDumper (playbook §5).

## Encoding a client frame (task #882)

`lastwar_encode.py` is the writer half of the protocol: TLV serialiser, XOR
mask, zlib, and the 5-byte client header. It is verified against reality rather
than against itself — `--verify` re-encodes every client frame of a saved
capture and diffs the bytes:

```bash
python3 tools/lastwar_encode.py --verify capture.pcapng          # 113/113
python3 tools/lastwar_encode.py --verify results/capture.pcapng  # 490/490
```

603 frames, byte-exact, including the 4 zlib-compressed ones (those are
compared by re-decoding, since zlib output depends on the compressor). Building
a request:

```python
from lastwar_encode import build_request
frame = build_request("hero.dispatch.list", {}, server_id=935, k1=0x5a, k2=0x00)
```

`k1`/`k2` are free choices — they vary per frame in every capture (30 distinct
pairs in 113 frames) and ship in the clear. The header's `serverId` is the
account's **home** server (935 throughout), not the server being acted on.

**This module only builds bytes; nothing here opens a socket.** Sending is
active protocol work — see the warning at the top of this file and
`protocol.md` §10.

### Catching a command that has never been captured

The rob request behind task #882 is in no capture, because the captured account
never robbed anything. `trap_command.py` listens live and records it the one
time a human does it by hand:

```bash
python3 tools/trap_command.py --match hero.dispatch --seconds 300
# …then rob a secret task in the game
```

It writes matching envelopes to `results/trap.jsonl` and **also flags any
command outside `known_commands.txt`** — a 332-entry `<dir> <command>` baseline
built from the saved transcripts. That second net matters because
`hero.dispatch.rob.*` is a guess at the name; whatever the command is really
called, "never seen before" catches it. Direction is part of the key: without
it all 179 server pushes read as new and bury the one interesting line.

## Injecting a command and seeing its reply (`relay.py`)

`steal_via_socket.py` can *send* a frame but never sees the answer — it borrows
the client's socket and shares one receive buffer with the game, so it sends
blind. `relay.py` closes that gap. It is an ordinary application-layer
man-in-the-middle: the game connects to the relay, the relay connects to the
real gateway, and every frame is decoded and logged **through both legs** — so
an injected `go.to.world` finally shows its `{success, _id}` reply coming back.
Both legs are normal OS sockets, so the kernel owns the TCP state on each side
and the client's stream is never spliced mid-frame (the ban vector WinDivert
tripped is simply absent). See
[`../docs/research/command-injection-vectors.md`](../docs/research/command-injection-vectors.md)
(Vector A) for the full rationale.

```bash
# observe only — decode and log every frame through both legs
python tools/relay.py --upstream <gateway-ip>:17935

# inject a safe go.to.world 20s after the client connects, then swallow its reply
python tools/relay.py --upstream <gateway-ip>:17935 --inject-cmd go.to.world --inject-after 20

# Linux / Android emulator: iptables REDIRECT front-end, gateway read off the socket
sudo iptables -t nat -A OUTPUT -p tcp --dport 17935 -j REDIRECT --to-ports 17935
python3 tools/relay.py --transparent --inject-cmd go.to.world --inject-after 20
```

**Getting the game onto the relay is a separate, unsolved-on-PC step.** The
client dials a bare gateway IP on :17935 with no DNS and races three gateways at
login, so redirection must key on *destination port*, not a name or IP:

- **Linux / emulator** — `iptables -t nat` REDIRECT of dst-port 17935 to the
  relay, then `--transparent` recovers the real gateway from `SO_ORIGINAL_DST`.
  This is where the relay and the `_id` logic get proven first (research doc
  Vector E), on a throwaway account.
- **Windows** — a userland redirector (the tolerated env TUN with a dst-port
  rule, or a wintun + tun2socks of our own) sends the :17935 flow at the relay,
  and `--upstream <gateway-ip>:17935` names where to forward. Read the gateway
  IP off a passive `live_tshark.py` capture first. As of 2026-07 no TUN is
  active on this host (default route is direct), so this front-end has to be
  stood up before a PC run — the relay itself is ready.

The one real subtlety is the `_id` counter. Injecting a frame consumes an `_id`,
so the server's freshness check matters:

- `--id-mode passive` (default) leaves client frames untouched — correct if the
  server tolerates a *monotonic sequence with gaps*. Inject at `last+1`, swallow
  the one reply, and watch whether the client's later frames still get served.
  This is the experiment to run first.
- `--id-mode nat` shifts every later client `_id` up by the injection offset, so
  the server sees a strictly increasing sequence — correct if the check is
  *strict-sequential*. (The rewrite is byte-exact for the uncompressed client
  frame; the server's echoed `_id` is **not** remapped back, so the client may
  reject the shifted replies — the point of `nat` is to learn whether the server
  accepts the shifted client frames.)

Both modes and the inject/swallow path are covered by an in-process loopback
test rather than only against the live game.

## Output layout
```
results/
├── trap.jsonl              # trapped envelopes (trap_command.py)
├── traffic_<ts>.jsonl      # one JSON record per HTTP flow / WS frame (mitm addon)
├── analysis_<ts>.json      # offline pcap analysis
├── traffic/<ts>_traffic.jsonl  # one file per sniffer run (live_tshark / live_sniffer)
├── traces/<ts>_trace.log       # one file per Lua tracer run (lua_trace.py)
└── raw/                     # raw request/response bodies (*.bin)
```
`<ts>` is `YYYYMMDD_HHMMSS` taken when the run starts, so a restart always
lands in a new file (`_2`, `_3`, … disambiguate the same second).
Traffic dumps can contain session tokens — they are gitignored; do not commit them.
