# Task #971 — go.to.world inject via ws2.send (dup'd socket)

**Status: SUCCESS** — world-init detected, rc=0  
**Date:** 2026-07-21

---

## What was proven

End-to-end inject into the live Last War world server via a duplicated socket:

1. **Socket identification** — `getsockname` returns the correct local port for the game socket
   (`hval=0x19b4`, local port :56743) using Phase 1 (NtQuerySystemInformation) + bg-dup thread.
2. **Transport** — `ws2_32.send` on the duplicated handle sends 60 bytes; scapy confirms the
   TCP segment left the machine (`up_next_seq 0xd673200e→0xd673204a`).
3. **Server receipt** — TCP-ACK from the server covers our injected seq range (confirmed in
   intermediate runs; final run shows world-init instead).
4. **Server response** — `go.to.world {}` caused a full world-session reinit. The server opened
   fresh connections (172.65.210.24, 34.145.128.94, 128.1.26.69 all on :17935) and sent 87
   init-burst frames with monotonically increasing _id starting from 2.
   World-init detected: `world.get.march.infos _id=86 << inject_id=157`.

---

## Root cause of previous failures (task #961 → #971 history)

**Symptom:** `up_packets=15` (all keepalives), no upstream _id, timeout after 60s.

**Root cause:** `early-dup` ran 100 getsockname calls × 0.5 s timeout = ~50 s **in the main
thread before scapy started**. All orchestrator UI clicks happened during that window; scapy
wasn't listening. By the time scapy started, ≤10 s remained of the 60 s budget.

**Fix:** Remove `early-dup`. Start scapy immediately after Phase 1. Run Phase 2
(DuplicateHandle + getsockname) in a bg thread with a 50 ms timeout per candidate.

The ~300 ms delay between Phase 1 (NtQuerySystemInformation) and the bg thread's first
getsockname call (thread start overhead + scapy imports in main thread) moves execution
past ACE's hook window. Result: getsockname returns the correct port on the first matching
candidate.

---

## ACE behavior (measured)

| Approach | DuplicateHandle | getsockname | ws2.send |
|---|---|---|---|
| Blind scan (no NtQuerySystemInformation) | FALSE for hval > ~0x9a4 | — | — |
| Phase 1+2, getsockname in main thread within ~100ms of Phase 1 | OK | **BLOCKED** (ACE hook active) | — |
| Phase 1+2, getsockname in bg thread ~300ms after Phase 1 | OK | **WORKS** | OK |

The hook window for getsockname lasts ≈100–200 ms after NtQuerySystemInformation. By
moving getsockname into a bg thread that starts after scapy imports, we naturally fall
outside this window.

---

## Probe-send fallback (not triggered in success run)

If getsockname blocks for all candidates, build the inject frame and call `ws2.send` on
each blocking candidate with 200 ms timeout:
- VPN/tunnel sockets: `ws2.send` hangs (WSP intercept) → timeout, skip
- Non-connected sockets: `ws2.send` returns WSAENOTCONN → negative result, skip
- Game socket: `ws2.send` returns `len(frame)` in < 5 ms → identified + inject done

---

## Final run output

```
game local port: :56743 (192.168.1.254 → 15.197.233.176:17935)
phase1: 106 socket candidates (tidx=40)
sniffing upstream _id via scapy/npcap…
bg-dup: phase2 + probe-send started in background…
bg-dup: found via getsockname hval=0x19b4
upstream _id=155  server_id=935
[09:04:17] GAME STREAM FOUND — 15.197.233.176:17935
injecting _id=157  server_id=935  frame=60B  pre_seq=0xd673200e up_pkts=3
ws2.send: sent 60 B — scapy confirmed (up_next_seq 0xd673200e→0xd673204a)
[09:04:31] GAME STREAM FOUND — 172.65.210.24:17935  (world reinit)
[09:04:31] GAME STREAM FOUND — 34.145.128.94:17935
[09:04:31] GAME STREAM FOUND — 128.1.26.69:17935
... [87 init-burst frames _id=2..87] ...
[SUCCESS] world-init detected: world.get.march.infos _id=86 << inject_id=157
server_reply  _id=86  success=True  cmd=world.get.march.infos
```

---

## Next step

`hero.dispatch.steal` inject. Needs:
- `uuid` — dispatch-complete troop UUID (from `hero.dispatch.list` downstream)
- `targetServer` — target server ID (from scan, e.g. `rank.get`)
- Free loot slot on our side
- Same inject mechanism (unchanged), just swap `build_test_frame` → `build_steal_frame`
