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
| `live_sniffer.py` | **Windows** (Python, admin) | decode the protocol **live**, no Wireshark |
| `watch_captures.sh` | **WSL** (bash) | auto-decode captures dropped into `results/` |

Capture (Wireshark/Npcap) must run **on Windows** — WSL2 is a separate NAT'd VM
and cannot see the Windows game's traffic directly. WSL is for offline analysis
of a `.pcapng` you saved on Windows, and for running mitmproxy (with
`networkingMode=mirrored`, see playbook §0).

## Live decoding on Windows (no Wireshark)

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

## Output layout
```
results/
├── traffic_<ts>.jsonl      # one JSON record per HTTP flow / WS frame (mitm addon)
├── analysis_<ts>.json      # offline pcap analysis
└── raw/                     # raw request/response bodies (*.bin)
```
Traffic dumps can contain session tokens — they are gitignored; do not commit them.
