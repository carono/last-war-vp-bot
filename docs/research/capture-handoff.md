# Capture handoff — what to run on Windows, what to send back

The analysis pipeline (`tools/analyze_pcap.py`, `tools/lastwar_mitm_addon.py`) is
smoke-tested and ready, but **it needs a real capture that only the Windows side
can produce**: WSL2 runs in a NAT'd VM (its `eth0` is `172.19.x.x`, not the
host's IP), so it cannot see the Windows game's packets. Do the capture on
Windows, drop the file into `results/`, and WSL analyses it offline.

Read `sniffing-playbook.md` for the full reasoning; this page is the short
checklist. **Anti-cheat rule stands:** passive capture (steps 1–2) is safe on
the official client; anything active (MITM/Frida, steps 3–4) is emulator +
throwaway account only — never server #300.

---

## Fastest safe path — passive capture (do this first)

1. **Start the game** (official client or emulator), get to a logged-in screen.

2. **Find the transport.** In the repo root, in PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\tools\find_lastwar_connections.ps1 -Watch -IncludeUdp
   ```
   Note the line `Distinct established remote ports: …` and the ready-made
   `Wireshark filter: …`. If nothing matches, add the exe name to `-NameFilter`.

3. **Capture in Wireshark** (needs Npcap):
   - Capture on the adapter carrying the game traffic (physical NIC, or the
     emulator's virtual adapter).
   - Paste the filter from step 2 (`tcp.port == <p> || …`).
   - Do ~30–60 s covering a **login + one gameplay action** (open profile,
     collect resources — whatever we want to reproduce later).
   - `File → Save As…` → **pcapng** → save it as `capture.pcapng`.

4. **Hand it back.** Copy the file where WSL can read it, e.g.
   `\\wsl$\...\last-war-vp-bot\results\capture.pcapng`, or any path under
   `C:\Users\…`. Then on the WSL side:
   ```bash
   .venv/bin/python tools/lastwar_proto.py results/capture.pcapng --json results/transcript.json
   ```
   `lastwar_proto.py` finds the game flows itself and fully decodes them — see
   `protocol.md`. Do **not** pass `--port`; hard-coding the port would
   hide a second endpoint (login/region server) if one appears.

### What to send back for analysis
- **`capture.pcapng`** (the raw capture), **or** if it is large/sensitive, just
  the generated **`results/analysis_<ts>.json`** — but note that file's own
  gitignore: it may embed payload bytes / tokens, so share it privately, don't
  commit it.
- The **port list** and the **`find_lastwar_connections.ps1` output** (tells us
  the host/port topology).
- One sentence: **what action you performed during the capture** (login only?
  opened profile? collected resources?) — so decoded frames can be matched to
  behaviour.

---

## If the capture comes back all-TLS (encrypted)

`analyze_pcap.py` will print *"payloads are mostly TLS … you need MITM or a TLS
keylog."* Two ways to get plaintext — **emulator + throwaway account only**:

- **TLS keylog (least invasive):** if the client honours `SSLKEYLOGFILE`, set it
  before launch, then point Wireshark at it
  (*Preferences → Protocols → TLS → (Pre)-Master-Secret log filename*). Send back
  the `.pcapng` **and** the keylog file. See playbook §2.
- **MITM:** run `mitmweb -s tools/lastwar_mitm_addon.py --listen-port 8080`,
  install the mitmproxy CA, route the client through `:8080` (Proxifier /
  emulator proxy). Output lands in `results/traffic_<ts>.jsonl` + `results/raw/`.
  Send back the `traffic_<ts>.jsonl` (privately — holds tokens). See playbook §3–4.

If TLS is certificate-pinned and MITM fails, the fallback is Frida
(`tools/unity_ssl_unpin.js`) or a custom-TCP dissector
(`tools/lastwar_dissector.lua`) — both need per-build offsets/ports; see
playbook §5 and the dissector header.

---

## Current status (2026-07-02)
- Toolkit committed on branch `v2`; offline path smoke-tested on a synthetic pcap.
- **No real capture exists yet** — `results/` holds only old perception
  benchmark PNGs, no `.pcap*`. Nothing to analyse until a Windows-side capture
  arrives.
- Next actionable step is **step 2–3 above on Windows.**
