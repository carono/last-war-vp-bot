# Task #971 — go.to.world inject via ws2.send (dup'd socket)

**Date:** 2026-07-21

## Transport result: SUCCESS

`ws2.send: sent 63 bytes via dup'd socket (local:51387)` — no hang, no error.

## Comparison with sendp path (Task #970)

| | sendp (L2 raw) | ws2.send (dup'd socket) |
|---|---|---|
| Send mechanism | scapy pcap_sendpacket bypasses TCP stack | ws2_32.send via dup'd game socket handle |
| Sequence numbers | Desync — game client unaware of our bytes | Correct — goes through game's own kernel socket object |
| Server ACK | Yes, but triggers RST from game side | Yes, clean ACK, no RST |
| Game reconnect | TCP RST → reconnect (bug) | Server processes go.to.world → reconnects to world servers (expected) |

## What happened

1. `bg-dup: blind scan via getpeername` found game socket at `hval=0x18e4` with peer `15.197.233.176:17935`
2. `ws2.send: sent 63 bytes` — no error, no VPN WSP block
3. Game switched to world map servers: `172.65.210.24:17935`, `3.33.246.23:17935`, `34.145.128.94:17935`
4. Full world login sequence: `init → check.device.change(_id=2) → ... → world.get.block(_id=120)`
5. Game is alive on world map after inject — no crash, no ban

## Analysis of reconnect

The reconnect after our `go.to.world` is **NOT a TCP RST** (which was the sendp bug). It is the server-side behavior of the `go.to.world` command: the game disconnects from the city/home server (`15.197.233.176`) and connects to the world-map server cluster (CDN-backed, multiple IPs). This is what the command is supposed to do.

The old sendp reconnect: client TCP sequence desync → server sends RST → uncontrolled reconnect.  
The new ws2.send reconnect: server processes go.to.world → controlled session switch to world servers.

## Open issue: synthetic _id=50000

Because the upstream `_id` decoder couldn't extract the live counter (all upstream frames showed `_id=None` in the watcher), we fell back to synthetic `inject_id=50000`. The actual game counter was around 10–20 at the time of inject. The server likely processed `_id=50000` (perhaps rejecting it as out-of-sequence) which contributed to the session reset.

Next step: fix upstream `_id` extraction so we can use the real next _id. This would likely allow `go.to.world` to be a no-op if already on world map (rather than triggering a reconnect), and would be required for `hero.dispatch.steal`.

## Socket identification fix

- Old approach: `NtQuerySystemInformation` → phase-1 → `dup_game_socket_by_lport` (getsockname)
  - Problem: `NtQuerySystemInformation` triggers ACE timing block; getsockname blocks on game socket
  - Wrong socket was selected (hval=0x710, getsockname timeout heuristic)
  - `ws2.send` hung on wrong handle
  
- New approach: blind scan via `getpeername` (no NtQuerySystemInformation)
  - No ACE timing block → DuplicateHandle fast
  - `_peer` (200 ms timeout) identifies socket by server endpoint `15.197.233.176:17935`
  - Correct socket found at `hval=0x18e4`
  - `ws2.send` completes in < 5 s

## Connection

`192.168.1.254:51387 → 15.197.233.176:17935` (game socket)
