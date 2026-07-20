# Executing client commands without tripping ACE — vector brainstorm

Task #959. Free-form exploration of ways to make the client issue
`hero.dispatch.steal` / `go.to.world` on demand, given the constraints that ruled
out the earlier attempts. Companion to `socket-duplication.md` (which proved the
dup mechanic but stalled on delivery) and `protocol.md` (transport facts).

## Constraints this has to satisfy

1. No kernel-level interference (WinDivert-style TCP inject → ACE ban).
2. Must not corrupt the client's own TCP stream / framing.
3. No second account (auth == the TCP connection; a new connection is a new login).
4. Runs from Windows Python or WSL.

## Facts that steer the design (from protocol.md + socket-duplication.md)

- Transport is **plaintext TLV over TCP :17935**, no TLS. Nothing to unpin, and a
  man-in-the-middle can read/rewrite frames directly.
- The client dials a **bare gateway IP with no preceding DNS lookup**, and at
  login **races three :17935 gateways in parallel** (AWS Global Accelerator /
  Cloudflare / Google Cloud), keeping the one that answers. The winning IP is not
  stable across sessions. → **hosts-file / DNS redirection cannot catch the game
  connection.** Redirection has to key on `dst port 17935`, not on a name or a
  fixed IP.
- There is **already a transparent TUN VPN/proxy in this environment** that
  intercepts every socket, including the game's — that is exactly why
  `getpeername` on a duplicated handle read a `:443` tunnel endpoint instead of
  the real gateway. Crucially, **this reroute has not caused a ban.** ACE here
  tolerates the game's :17935 traffic being carried through a userland TUN.
- `_id` is a **strict per-connection counter**; the server rejects a frame whose
  `_id` is not the next expected value ("replay / out of order"). Any injected
  frame perturbs this counter for everything after it.
- ACE (empirically, this build): **does not** strip `PROCESS_DUP_HANDLE`, **does
  not** flag passive pcap; **does** ban kernel drivers placed on the game traffic
  and (by reputation) suspicious VM_WRITE/CREATE_THREAD injection handles.

## The reframe that unlocks everything

The dup-socket write-up treats the environment VPN as *the blocker*. Invert it:
a userland TUN is **already sitting transparently in the game's TCP path and ACE
does not care.** That is a working, ban-free interception point. We do not need
to forge packets into a stream (kernel) or borrow a handle (dup) — we can be a
**legitimate application-layer man-in-the-middle** that the OS gives real,
OS-owned TCP endpoints on both sides.

This is the primary recommendation. Everything else is fallback or recon.

---

## Vector A (primary): userland MITM relay via port-17935 redirection

Stand up an ordinary asyncio TCP relay (Windows Python or WSL — no driver of our
own):

```
game  ──real TCP──▶  our relay  ──real TCP──▶  real gateway :17935
```

- Both legs are **normal userland sockets**; the OS owns both TCP state machines,
  so seq/ack are correct for free and the client's stream is never spliced
  mid-frame. Requirement 1 (no kernel) and 2 (no TCP corruption) fall out of the
  architecture, not from care.
- Same connection end-to-end → same auth. Requirement 3 satisfied.
- asyncio relay → Requirement 4 satisfied.
- **Delivery becomes observable**: the server's reply flows back *through us*, so
  we finally see `go.to.world {success, _id}` — the exact thing
  socket-duplication could never confirm.

Reuse `lastwar_proto.py` to decode each frame in flight and `lastwar_encode.py`
to build the injected one.

### Getting the game onto the relay (the one real engineering question)

Because the game uses a bare IP on :17935 (no DNS), redirection must be by
destination port. Options, cleanest first:

1. **Reuse the existing tolerated TUN.** Identify what the environment VPN is
   (likely a userland TUN: clash / sing-box / v2ray / tun2socks — all
   rule-routing capable). If so, add a rule: `dst-port 17935 → local relay
   inbound`. Zero new drivers, and we inherit the ban-free posture already
   demonstrated. **This is the path to try first** — the interception is proven
   tolerated, we only redirect it one hop through our relay.
2. **Our own userland tun2socks** (wintun adapter + tun2socks process) capturing
   only `dst-port 17935` to the relay. wintun is a generic network adapter, not a
   hook on the game process or its traffic driver — the same category ACE already
   tolerates via the existing VPN. Falls back here if the env VPN has no rule API.
3. **Android emulator** (see Vector E): inside the emulator the network namespace
   is fully ours — a one-line `iptables` REDIRECT of dst-port 17935 to the relay,
   no driver question at all. This is where the relay + `_id` logic get **proven**
   before any PC run.

### The `_id` translation NAT (the crux)

Injecting a frame breaks the strict `_id` sequence for every later client frame.
The relay handles it as a small stateful translator:

- Maintain a running `offset` (starts 0) and a `pending` map.
- Client→server: rewrite each client frame's `_id` to `_id + offset`; remember
  `original → translated` so replies can be mapped back.
- To inject: at a **frame boundary** in the client→server direction (never
  mid-frame), during an idle gap, send our frame with the next `_id`, then
  `offset += 1`. Swallow that command's *reply* (the client never sent it and
  would be confused by an unsolicited `_id`).
- Server→client: rewrite each reply's `_id` back to the client's original value
  via the `pending` map before forwarding.

**Open question to settle empirically, cheaply:** is the server's `_id` check
*strictly sequential* (renumber-everything, as above) or merely
*monotonic-increasing with gaps allowed*? If gaps are allowed, the whole NAT
collapses to "inject at last+1, swallow the one reply, leave the client alone" —
dramatically simpler. Determine by injecting one `go.to.world` at `last+1` on the
emulator and watching whether the client's subsequent `last+2…` frames still get
served or start erroring.

### Race-of-three-gateways detail

At login the client opens three parallel :17935 connections and keeps one. The
relay must accept/relay all three and inject only on the **surviving** one (the
connection that keeps carrying frames after the first second). Also forward
keepalives promptly or the server drops the connection.

### Why this beats the two prior attempts

- vs **WinDivert**: no driver, no forged packets — the ban vector is absent.
- vs **socket duplication**: no shared kernel receive buffer, no mid-frame
  interleave risk with the client's own `send()`s (the relay only inserts whole
  frames at boundaries), and delivery is *observable*. The dup path can only ever
  send blind.

---

## Vector B (fallback): finish socket duplication

The mechanic is already proven (`send()` returned 61 bytes, err 0). The only wall
is the VPN masking the endpoint. If Vector A's redirection is not pursued, the
documented next step still stands: **disable the TUN VPN → the game socket becomes
a direct `:17935` → `--find-handle` pins it → `--send go.to.world --force`**, with
a *separate-process* capture watching for the reply. Lower ceiling than A: it
sends blind (no reply path through us), shares one receive buffer with the game,
and races the `_id` freshness window. Keep as backup, not primary.

Note A and B are mutually exclusive in one run: A *needs* an interception hop in
the path, B needs the path *clean*. Do not run both at once.

## Vector C (recon, cheap, possibly a free win): local control surfaces

Before committing to network work, check whether the client exposes a
**programmatic, no-network, no-memory-touch** trigger:

- Does `lastwar.exe` register a **custom URI scheme** (deeplink) that navigates or
  acts? Many mobile-derived clients do. Invoking a URI is pure shell, touches no
  game memory.
- Does it open a **local debug/IPC surface** — a named pipe, a localhost Unity
  profiler/debug port, an embedded webview with a JS bridge? (`unity_ssl_unpin.js`
  in the repo shows it is a Unity client.)

All of this is passive reconnaissance (process/handle/port enumeration, registry
read) — the same posture ACE already tolerates. If any command is reachable this
way, it sidesteps the network entirely. Low probability, but the cost to check is
minutes. **Avoid Frida/injection** here — that is the ACE-tripping posture the
whole task is trying to route around.

## Vector D (explicitly rejected, restated so it stays rejected)

- Kernel TCP inject (WinDivert) — bans.
- Second authenticated connection — auth is the connection; new socket = new
  login; not the same account's session.
- GUI clicking — user wants a programmatic path.

## Vector E (safety substrate for all of the above): emulator-first

The standing rule already mandates emulator + throwaway account for the
irreversible `steal`. Make it do double duty: **the Android emulator has no ACE
Ring-0 kernel driver and a fully controllable network namespace.** Prove the
entire Vector-A relay — redirection, `_id` NAT, reply observation, `go.to.world`
round-trip — inside the emulator on a throwaway account first. The protocol is
identical (mobile client, same TLV). Only after the mechanic is green there does
the PC port carry any residual risk, and that residual risk is now just "does PC
ACE tolerate one more redirect hop" — a question the environment's existing VPN
has already largely answered *yes*.

---

## Recommended order of work

1. **Recon (Vector C + identify the env VPN):** enumerate `lastwar.exe` URI
   schemes / local ports; identify the TUN client and whether it exposes
   rule-based routing. Both are passive, both cheap.
2. **Build the relay + `_id` NAT and prove it on the emulator (Vector E/A)** with
   `go.to.world`, throwaway account. Settle the strict-vs-gapped `_id` question.
3. **Port redirection to PC via the existing tolerated TUN (Vector A.1)**; confirm
   `go.to.world` round-trips through the relay on the real client.
4. Only then, `steal` — emulator + throwaway first per the standing rule.

Fallback if redirection proves impractical on PC: **Vector B** (disable VPN,
finish the dup send), accepting its blind-send limitations.

---

## Recon findings (2026-07-20, task #960)

The relay itself is built — `tools/relay.py`, Vector A end to end: transparent
MITM, per-frame decode/log through both legs, frame-boundary injection, the
`_id` NAT, and reply-swallow, all covered by an in-process loopback test. What
the recon settled about the **front-end** (getting the game onto it):

- **No TUN/VPN is active on this host right now.** Enumerating the Windows
  adapters and routes: the default route is direct (`0.0.0.0/0 → 192.168.1.1`,
  the Wi-Fi/vEthernet), and the only tunnel adapters present — `TAP-Windows
  Adapter V9` and `OpenVPN Connect DCO Adapter` — are **Disconnected**. So the
  "transparent TUN already in the game's path" the dup write-up saw (peer
  rewritten to a `:443` endpoint) was **OpenVPN, and it is currently off**.
  Consequence: Vector A.1 (piggyback the existing tolerated TUN) is not
  available as-is — it depends on that OpenVPN being switched on. When it is,
  redirecting dst-port 17935 through it still needs a routing rule OpenVPN does
  not obviously expose, so Vector A.2 (our own wintun + tun2socks scoped to
  dst-port 17935) is the more likely PC front-end. The emulator path (Vector E,
  `iptables REDIRECT` + `--transparent`) is unchanged and remains where to prove
  the mechanic first.
- **How the game dials.** With the client running but not on the world map there
  was no established `:17935` connection to sample — consistent with the client
  opening the gateway race only when it enters the game world. The localhost
  connections `lastwar.exe` holds (`127.0.0.1` ↔ `127.0.0.1` on ephemeral ports)
  are its own internal Unity socketpairs — **both ends are the game process** —
  not a local proxy. So there is no localhost proxy to hook; the `:17935` flow
  goes straight out and must be caught by a dst-port redirect while the client
  is on the map. Read the live gateway IP off a passive `live_tshark.py` capture
  taken at that moment and hand it to `relay.py --upstream`.

Net: the relay is ready and proven on loopback; the remaining PC blocker is
purely the port-17935 redirector, which is a network-plumbing step (emulator
`iptables` today, a scoped wintun/tun2socks for the PC run), not relay work.
