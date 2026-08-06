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
   socket (both the direct gateway connection and the proxy loopback).
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

> ## Point 2 above is OUT OF DATE — delivery WAS confirmed, two days later
>
> **#971, 2026-07-21: the injected command reached the server and the server
> acted on it.** The proof sat only in `results/socket_dup/RESULTS.md` for a
> fortnight — a git-ignored tree, so the repository went on saying «unconfirmed»
> while the machine that ran it held the opposite (found writing up #963).
>
> What the run recorded, in order: the tool read the client's own next `_id` off
> the wire, duplicated the game's socket, and sent a 60-byte `go.to.world` frame
> — and **scapy saw the client's upstream sequence number advance by exactly
> those bytes**, on the game's own connection. Seconds later the client received
> a full **world-init burst** (`init`, the shop/notice/dispatch batch,
> `world.get.march.infos`) and was on the world map. Nothing else asked for it.
>
> **What was NOT obtained, and the distinction matters:** the reply carrying
> *our* `_id` back. The scene reload restarts the counter, so the burst arrived
> with fresh low `_id`s and the tool's own success line pairs its inject id with
> one of them (`world.get.march.infos _id=86 << inject_id=176`) — that pairing is
> presentation, not evidence. So delivery is proven **by effect**, which point 3
> above says a screenshot cannot do — but a whole scene load is not a screenshot,
> and it is the thing the command exists to cause. The `_id`-matched reply, the
> stricter proof that task #963 asked for, was never seen and is not worth
> another live run (below).
>
> Two footnotes for anyone re-reading the log: that run was on the gateway port
> of the day, and **the port has moved since** — the tool reads it live now
> (#1053, `docs/research/protocol.md` §1). And the harness that drove it lives in
> `tools/archive/` (`run_world_inject.py`, `test_sniff_inject.py`), where the
> tools split put it; it still speaks of the old port and predates `game_paths`.

Test scope note: only the safe, reversible test command `go.to.world` is in
play. `steal` is deliberately not sent until the mechanic is confirmed on the
reversible command.

## What was measured — each overturned a theoretical "no"

| Step | Result |
|---|---|
| `OpenProcess(PROCESS_DUP_HANDLE)` on the game | **granted** — `NtQueryObject` shows the DUP_HANDLE bit *kept*, not stripped. ACE here does not gate it. |
| `DuplicateHandle` of the game's handles into us | **1406 / 1630 succeed** — once the x64 handle-truncation bug is fixed (see below). |
| `ws2_32` on a duplicated handle | **works** — `getpeername` answers on hundreds of them, so `send()` is usable. The `WSAENOTSOCK` fear was wrong; no raw AFD IOCTL needed. |
| Pinning the `:17935` game socket | **works, intermittently** — `getpeername` on a duplicated handle returned `<server-ip>:17935` in 5 of 6 runs, uniquely identifying the game connection (handle e.g. `0x16a4`). |

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
returning `next _id = 14208, server_id = 100` while the map was panned.

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

*Written before #971 did finish it. Kept because the recipe is still the right
one if this channel is ever picked up again — see the closing section for why it
should not be.*

- **Disable the VPN/proxy** so the game socket is a direct connection to the
  gateway. Then `--find-handle` pins it every run and `--send` (go.to.world,
  `--force`) can write to it.
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

## Where this direction stands now (#963, 2026-08-07)

**The question it was opened to answer is answered, and not by this.** «Can the
game be commanded at all» is settled by the Lua route — `GameEntry.get_Lua()` →
`XLuaManager.SafeDoString` runs a chunk inside the client, and everything the bot
does rides it: 30 abilities in `src/lastwar_bot/actions/*.md`, played by
`script_engine`, pressed from the panel, gated on the link (#1259/#1266). The very
command this harness injected is one line of DSL today —
`SceneUtils.ChangeToWorld()` (`docs/dsl.md`) — with no capture, no handle and no
`_id` race.

| | socket duplication | the Lua route |
|---|---|---|
| what it can send | one hand-built wire frame at a time | anything the client itself can do |
| what it needs | live `_id` off a capture, a duplicated handle, the VPN off, capture in a separate process | a warm daemon |
| answer channel | none — it never `recv()`s, so the reply lands in the client | the call returns its value |
| proven | delivery, once, by effect (#971) | every day, by every scenario |

So `--sniff-and-inject` is **a research artefact, not a transport**, and the
autonomous harness task #963 asked for was written (`tools/archive/`), run, and
succeeded before being archived. Two things in this file are still worth keeping,
and they are the reasons the tool is not deleted:

* **the frame builders and `--sniff-id`** — `build_command_frame` round-trips
  through the reference decoder, which is how a new command's bytes get
  understood before anybody tries to send one. That is protocol work, and it does
  not touch the game;
* **the finding itself** — ACE grants `PROCESS_DUP_HANDLE` on this build. It is
  the thing to re-measure first if the Lua route ever stops working after a game
  update, and the fallback is then a known quantity rather than a new project.

**Not recommended to finish.** Chasing the `_id`-matched reply costs live runs
against the operator's own account for a proof whose practical value is now nil,
and the environmental blockers (§ above) are the operator's VPN and a
capture/`ws2` conflict in one process — real work for a channel nothing would
use. If the direction is ever reopened, reopen it against the fallback question
(«does this still work when the Lua route does not»), not against the proof.
