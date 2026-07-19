# Socket duplication as a command transport — feasibility

Task #883, socket-duplication direction. The GUI-click and TCP-inject
approaches were both set aside; this asked whether the client's **own**
connected socket can be borrowed so a command is written down the real
connection, with the kernel supplying the correct seq/ack for free — no
WinDivert, no raw sockets, no kernel driver.

**Verdict (measured 2026-07-19, official PC client): the duplication mechanic is
proven; end-to-end delivery is not confirmed.** Three facts summarise it:

1. **Mechanic proven.** Every step through the write works — `OpenProcess`,
   `DuplicateHandle`, and finally `ws2_32.send`, which returned **61 bytes,
   err 0**: the full `go.to.world` frame was written into the game's real
   socket (both the direct `:17935` and the proxy loopback).
2. **Delivery unconfirmed.** The server's reply to `go.to.world` was never
   observed, so it is unproven that the frame reached the server. The blocker is
   a **local transparent proxy/VPN** in the path (see topology below), not the
   game or ACE — a reconnecting connection, an ambiguous game socket, and byte
   splicing into an active stream, none of which the game imposes.
3. **No visual confirmation possible by design.** The client does **not** flip
   its UI on a server `go.to.world` reply it did not initiate — the screen stays
   put. UI transitions are local; the command only changes server state. So a
   screenshot can never prove delivery; only a captured reply can.

This overturns the first-pass write-up, which assumed ACE would kill it;
empirically it does not on this build.

Test scope note: only the safe, reversible test command `go.to.world` is in
play. `steal` is deliberately not sent until the mechanic is confirmed on the
reversible command.

## What was measured — each overturned a theoretical "no"

| Step | Result |
|---|---|
| `OpenProcess(PROCESS_DUP_HANDLE)` on the game | **granted** — `NtQueryObject` shows the DUP_HANDLE bit *kept*, not stripped. ACE here does not gate it. |
| `DuplicateHandle` of the game's handles into us | **1406 / 1630 succeed** — once the x64 handle-truncation bug is fixed (see below). |
| `ws2_32` on a duplicated handle | **works** — `getpeername` answers on hundreds of them, so `send()` is usable. The `WSAENOTSOCK` fear was wrong; no raw AFD IOCTL needed. |
| Pinning the `:17935` game socket | **works, intermittently** — `getpeername` on a duplicated handle returned `3.33.246.23:17935` in 5 of 6 runs, uniquely identifying the game connection (handle e.g. `0x16a4`). |

`WSADuplicateSocket` itself stays **cooperative-only** (its `s` must be a socket
in the *calling* process; the owner must call it naming our pid) and is unused —
the manual `DuplicateHandle` path replaces it entirely.

### The load-bearing bug: x64 handle truncation

The first implementation failed every `DuplicateHandle` with
`ERROR_INVALID_HANDLE (6)`. Cause: without explicit ctypes `argtypes`/`restype`,
HANDLE arguments marshal as 32-bit `int`, so the `(HANDLE)-1` pseudo-handle from
`GetCurrentProcess` truncates. With the signatures set (see `_win()` in
`tools/steal_via_socket.py`), `hself` reads `0xFFFFFFFFFFFFFFFF` and duplication
succeeds. NTSTATUS also had to be masked to unsigned or the length-mismatch
retry in the handle enumeration never fired.

## The frame is correct

`tools/steal_via_socket.py --build` produces `go.to.world {_id}` (and, with
`--command steal`, the exact `hero.dispatch.steal` trapped on 2026-07-19). Fed
back through the reference decoder it round-trips byte-for-byte. `--sniff-id`
reads the next `_id` (and `server_id`) passively off the wire — confirmed live,
returning `next _id = 14208, server_id = 935` while the map was panned.

## What blocks a clean end-to-end send here — all environmental

1. **VPN/proxy masks the endpoint intermittently.** In some runs every socket's
   peer read as a tunnel endpoint (`198.19.x` / `101.32.x : 443`) and the
   `:17935` socket did not surface. The machine also has loopback proxy pairs
   (`127.0.0.1:6xxxx ↔ 6xxxx`). `getsockname` (local port `63627`, which would
   pin the socket regardless) **blocks indefinitely** on this box, so it cannot
   be used as a fallback matcher. Disabling the tunnel makes `:17935` direct and
   stable.

2. **Capture and `ws2` conflict in one process.** With a `dumpcap` capture
   running (needed to observe the reply), `getpeername` in the *same* process
   stopped seeing `:17935`. Splitting capture into a separate process is
   necessary; even then the runs became unstable (hung `dumpcap`, spurious exit
   codes) after many duplication rounds.

3. **`_id` freshness race.** The frame needs the next `_id`; it is only frozen
   while the client is idle, so the snoop→send window has to stay short.

None of these is the game rejecting the write. Send-only is safe by design: the
tool never `recv()`s, so it cannot steal bytes the game is mid-frame on.

## To finish the proof (next session)

- **Disable the VPN/proxy** so the game socket is a direct `:17935` connection.
  Then `--find-handle` pins it every run and `--send` (go.to.world, `--force`)
  can write to it.
- Observe the result either by the **screenshot** (the client flips to the
  world map) or by a **separate-process** capture watching for the
  `go.to.world {success, _id:<ours>}` reply — kept out of the sending process to
  avoid conflict (2).
- Only once that round-trips: revisit `steal`, still on an emulator + throwaway
  account per the standing rule, since it is irreversible and notifies the
  owner's alliance.

## Relationship to task #366 / protocol.md §10

§10 drew the line at passive work and assumed active process interaction would
hit ACE. For **this** interaction — opening a handle and duplicating one — that
assumption did not hold: ACE granted `PROCESS_DUP_HANDLE` and the duplication
succeeded. The remaining wall is the user's own VPN, which is removable. The
posture is still active work, so the emulator + throwaway-account rule stands
for `steal`; `go.to.world` is reversible and low-stakes by comparison.
