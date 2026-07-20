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
> client or Carono's main account (server #972).

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
| `live_sniffer.py` | **Windows** (Python, admin) | decode live via scapy — see caveat below |
| `live_tshark.py` | **WSL** (Python) | decode live by driving Wireshark's `dumpcap.exe` — **preferred** |
| `secret_task_capture.py` | **Windows** (Python) | stream secret tasks live via scapy/npcap, no Wireshark binaries spawned |
| `scan_players.py` | **Windows** (Python) | sweep player bases (name / HQ level / alliance) off the map into JSON |
| `map_capture.py` | **Windows** (Python) | shared capture + which-server-is-on-screen logic behind the two scanners |
| `watch_captures.sh` | **WSL** (bash) | auto-decode captures dropped into `results/` |

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
`--raw` to dump full payloads, `--port` to narrow the capture filter.

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

## Step-by-step

### 0. Python env (WSL, one-time)
```bash
cd "/mnt/p/projects abandoned/carono/last-war-vp-bot"
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

## Output layout
```
results/
├── trap.jsonl              # trapped envelopes (trap_command.py)
├── traffic_<ts>.jsonl      # one JSON record per HTTP flow / WS frame (mitm addon)
├── analysis_<ts>.json      # offline pcap analysis
└── raw/                     # raw request/response bodies (*.bin)
```
Traffic dumps can contain session tokens — they are gitignored; do not commit them.
