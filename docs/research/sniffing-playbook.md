# Practical playbook — sniffing Last War traffic (WSL2 + Windows)

Companion to [`network-protocol-sniffing.md`](network-protocol-sniffing.md).
That doc says *whether* to do this (short answer: passive-only on the official
client; anything active only on an emulator + throwaway account, never the main
account on server #972). **This doc is the *how* — the concrete commands.**

---

## 0. Environment reality — read first

**WSL2 is a separate NAT'd VM.** Its network namespace is *not* the Windows
host's. You **cannot** `tcpdump` the Windows game from inside WSL2 by default —
you'd only see WSL2's own traffic. Two ways to bridge:

- **Capture** the game → do it **on Windows** (Wireshark + Npcap). WSL2 only
  helps for offline analysis of a saved `.pcapng`.
- **Proxy** the game → either run the proxy **on Windows**, or run it in WSL2
  and make Windows able to reach it. Easiest: enable **mirrored networking** so
  `localhost` is shared between Windows and WSL2:

  ```ini
  # %USERPROFILE%\.wslconfig   (Windows side)
  [wsl2]
  networkingMode=mirrored
  ```
  ```powershell
  wsl --shutdown   # restart WSL after editing .wslconfig
  ```
  With mirrored mode, a `mitmproxy` bound to `:8080` in WSL2 is reachable at
  `127.0.0.1:8080` from Windows. Without it, use the WSL2 IP (`ip addr` in WSL).

**ACE gate.** The active steps below (MITM CA install, Frida, Proxifier
redirect) are exactly what Tencent ACE flags on the **official native client** →
ban/crash. Run active steps **only against an Android emulator build**
(`com.fun.lastwar.gp` under LDPlayer/BlueStacks) with a disposable account.
Passive capture (§1) is safe anywhere.

---

## 1. Determine the transport (Wireshark)

**Step 1 — find the game's sockets first (narrows the capture).** On Windows,
with the game running, list the game process's live connections:

```powershell
# PowerShell — remote endpoints for the game process
Get-Process | ? { $_.ProcessName -match 'lastwar|LastWar|FUNFLY' }
Get-NetTCPConnection -State Established |
  ? OwningProcess -eq <PID> |
  Select RemoteAddress,RemotePort,State
netstat -ano | findstr <PID>          # classic equivalent, incl. UDP
```
Note the remote IPs/ports. Also run **TCPView** (Sysinternals) for a live view —
it maps sockets→process visually and shows short-lived login connections.

**Step 2 — capture on Windows** (Wireshark with Npcap on the physical
adapter, or on the emulator's virtual adapter). Useful display filters:

```
ip.addr == <server_ip>                         # scope to the game server
tcp.port == 443 || tcp.port == <custom_port>   # candidate channels
tls.handshake.type == 1                         # ClientHello — see SNI below
tls.handshake.extensions_server_name           # the SNI hostname
http.upgrade == "websocket"                     # WS handshake (if plaintext HTTP)
quic                                            # QUIC/HTTP3 (UDP 443)
dns                                             # resolve which hosts it hits
```

**Step 3 — classify.** Look at the *first bytes* of each TCP stream
(Follow → TCP Stream, "Hex Dump"):

| First bytes / signal | Meaning |
|---|---|
| `16 03 01` / `16 03 03` | TLS record (ClientHello) → it's TLS. Go to §2. |
| `GET … Upgrade: websocket` in clear | plaintext WebSocket → read directly, no MITM needed |
| Non-TLS binary, repeating length-prefix pattern | custom binary over TCP → §3 |
| UDP 443 + `quic` dissector hits | QUIC/HTTP3 → capture works but needs keylog to decrypt (§2) |

Record for each connection: host (SNI/DNS), IP, port, TLS-or-not, first-seen
timing (login vs. gameplay), frame-size cadence (keepalive heartbeats). That
table alone answers "HTTP vs WS vs raw TCP" — the primary goal here.

---

## 2. TLS/HTTPS → MITM proxy on Windows

> Active step. Emulator + throwaway account only (ACE).

**A. Install mitmproxy.** Simplest is to run it *on Windows* (no WSL bridging):
```powershell
pip install mitmproxy            # gives mitmproxy / mitmweb / mitmdump
mitmweb --listen-port 8080       # web UI at http://127.0.0.1:8080 ... actual UI on :8081
```
Or in WSL2 (with `networkingMode=mirrored` from §0):
```bash
pipx install mitmproxy
mitmweb --listen-host 0.0.0.0 --listen-port 8080
```

**B. Trust the CA.** Launch mitmproxy once; it writes the CA to
`~/.mitmproxy/mitmproxy-ca-cert.cer` (WSL) or `%USERPROFILE%\.mitmproxy\`
(Windows). Install into the **Windows machine (or emulator) trust store**:
```powershell
# Windows: import into Local Machine > Trusted Root
certutil -addstore -f Root "%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.cer"
```
For an **Android emulator**, push it as a *system* CA (user CAs are ignored by
apps targeting API 24+):
```bash
# rooted emulator (LDPlayer/BlueStacks are rootable)
HASH=$(openssl x509 -inform PEM -subject_hash_old -in mitmproxy-ca-cert.cer | head -1)
adb root && adb remount
adb push mitmproxy-ca-cert.cer /system/etc/security/cacerts/$HASH.0
adb shell chmod 644 /system/etc/security/cacerts/$HASH.0
adb reboot
```

**C. Point the client at the proxy.** Two options:

- *System/emulator proxy* (works only if the app respects it):
  ```bash
  adb shell settings put global http_proxy 10.0.2.2:8080   # emulator → host
  ```
- *Force-route a proxy-unaware app* with **Proxifier** on Windows (see §4) —
  this is the reliable path for games that ignore system proxy.

**D. Read.** In `mitmweb`, filter to the game host; each flow shows decrypted
HTTP/WS frames. For WebSocket, mitmproxy shows individual WS messages. If the
inner payload is still binary → it's the app-layer cipher/protobuf → §5.

**Alternatives:** **Charles** (`Proxy → SSL Proxying → add host`, install cert
via `Help → SSL Proxying → Install Charles Root Cert`) or **Burp** (needs
"invisible proxy" mode for non-proxy-aware clients + hosts-file redirect, as in
the nc-lp write-up). mitmproxy scripts the best for automation.

**QUIC / own-BoringSSL note.** If §1 showed QUIC, or MITM just fails, try a TLS
**keylog** instead of interception (passive, but needs the client to honor it —
Unity/IL2CPP usually bundles BoringSSL and does *not*, so expect failure):
```powershell
setx SSLKEYLOGFILE "C:\tmp\sslkeys.log"     # then in Wireshark:
# Preferences → Protocols → TLS → (Pre)-Master-Secret log filename = that file
```

---

## 3. Custom binary protocol over TCP

**Inspect the framing.** Follow → TCP Stream → Hex Dump. Look for a
**length-prefix**: first 2–4 bytes of each message = payload length (big- or
little-endian), then the body. Confirm by checking the prefix value == bytes
that follow. Many games do `[uint16/uint32 len][uint16 opcode][protobuf body]`.

**Write a Wireshark Lua dissector** for the custom port so frames decode
automatically. Minimal length-prefixed skeleton:

```lua
-- lastwar.lua  → drop into %APPDATA%\Wireshark\plugins\
local p = Proto("lastwar", "Last War game protocol")
local f_len    = ProtoField.uint32("lastwar.len",    "Length",  base.DEC)
local f_opcode = ProtoField.uint16("lastwar.opcode", "Opcode",  base.HEX)
local f_body   = ProtoField.bytes ("lastwar.body",   "Body")
p.fields = { f_len, f_opcode, f_body }

function p.dissector(buf, pinfo, tree)
    if buf:len() < 6 then
        pinfo.desegment_len = DESEGMENT_ONE_MORE_SEGMENT   -- ask for more (TCP reassembly)
        return
    end
    local n = buf(0,4):uint()                 -- try BE; use :le_uint() if LE
    if buf:len() < n + 4 then
        pinfo.desegment_len = (n + 4) - buf:len()
        return
    end
    pinfo.cols.protocol = "LASTWAR"
    local t = tree:add(p, buf(0, n + 4))
    t:add(f_len,    buf(0,4))
    t:add(f_opcode, buf(4,2))
    t:add(f_body,   buf(6, n - 2))
end
DissectorTable.get("tcp.port"):add(<custom_port>, p)
```

Iterate on endianness / header layout until the "Length" field lines up with
real frame sizes. For scripted extraction use `tshark`:
```bash
tshark -r capture.pcapng -Y "tcp.port==<port>" -T fields -e lastwar.opcode -e lastwar.body
```
If the body is high-entropy (looks random) → it's encrypted at the app layer;
the key/algo lives in `GameAssembly.dll` → static RE (Il2CppDumper + IDA), or
hook the cipher function with Frida (§4) to grab plaintext + key.

---

## 4. SSL pinning → Frida / Proxifier (different jobs!)

**Detect pinning:** with the MITM proxy in place, a pinned client sends its
ClientHello then **immediately RSTs / closes** the connection (mitmproxy logs a
TLS handshake error, the game shows "network error"). No pinning → traffic flows
decrypted.

**Proxifier does NOT bypass pinning.** Its job is *routing*: forcing a
proxy-unaware Windows process through mitmproxy. Config:
```
Proxifier → Proxy Servers → Add → 127.0.0.1 : 8080 (HTTPS)
Proxifier → Proxification Rules → Add:
    Applications: LastWar.exe      (or the emulator exe)
    Target: Any
    Action: Proxy 127.0.0.1:8080
```
That gets the bytes to mitmproxy but pinning will still reject the MITM cert.

**Frida bypasses pinning** (patches the cert-check in memory). Realistic only on
the **Android emulator** build (`frida-server` on the rooted emulator):
```bash
# on host (WSL/Windows) — needs the frida-server binary running on the emulator
pip install frida-tools
adb push frida-server-*-android-x86_64 /data/local/tmp/frida-server
adb shell "chmod 755 /data/local/tmp/frida-server && /data/local/tmp/frida-server &"

# universal pinning-bypass (Java layer): use a well-known script
frida -U -f com.fun.lastwar.gp -l frida-multiple-unpinning.js --no-pause
# or objection, which bundles a bypass:
objection -g com.fun.lastwar.gp explore
#   (in objection REPL) android sslpinning disable
```
On the **official native Windows client** Frida is an injected module → ACE
kills it and flags the account. Do not.

---

## 5. Protobuf analysis (most likely payload)

**A. Quick decode without a schema** — `protoc`:
```bash
# raw body dumped from a frame (bin file)
protoc --decode_raw < frame_body.bin
```
Shows field numbers + wire types + values (no names). Good enough to see
structure.

**B. In mitmproxy** — the built-in protobuf content view auto-renders protobuf
bodies; press `m` on a flow → "protobuf", or use **blackboxprotobuf**:
```bash
pip install blackboxprotobuf
python -c "import blackboxprotobuf,sys; d,t=blackboxprotobuf.decode_message(open('frame_body.bin','rb').read()); print(d)"
```

**C. Recover the real `.proto`** (names, not just field numbers):
- **Static, from the client** — `Il2CppDumper` / `Il2CppInspector` on
  `GameAssembly.dll` + `global-metadata.dat` reconstructs C# types; protobuf
  message classes come back with field names → dump to `.proto`.
- **Dynamic** — **pbtk** (`marin-m/pbtk`) extracts embedded `.proto` /
  `FileDescriptor` from the binary or hooks the runtime; `extractors/` pull
  descriptors, `gui.py` browses them.
- **Frida** — hook the protobuf `SerializeToString`/`ParseFromString` (or the
  IL2CPP method addresses from the dump) to log messages with names at runtime.

**D. Wireshark** has a Protobuf dissector: Preferences → Protocols → ProtoBuf →
point it at your `.proto` search paths, then map the custom port's body to
`protobuf` in your Lua dissector (`Dissector.get("protobuf"):call(...)`).

---

## 6. Suggested order of attack

1. **§1 passive** on the official client — safe, builds the endpoint/transport
   map. *Often enough to answer the research question.*
2. Decide go/no-go on active work. If go → **switch to an Android emulator +
   throwaway account.**
3. §2 MITM (+ §4 Frida if pinned) on the emulator → decrypted HTTP/WS.
4. §5 protobuf decode; if bodies are still encrypted, §3/RE for the app cipher.
5. Only after the schema is understood: prototype a request-replay client in a
   throwaway account. Keep it far away from server #972.
