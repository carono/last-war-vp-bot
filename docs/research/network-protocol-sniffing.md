# Research — Network protocol sniffing for Last War

> **Correction — this spike's recommendation was reversed.** The TL;DR below
> concluded "protocol automation not recommended / passive capture yields
> undecryptable TLS / stay vision-based." That was wrong on the decisive point:
> the `:17935` transport turned out to be **plaintext TLV over TCP, not TLS**, so
> passive capture decodes 100% and protocol-level automation became the project's
> **primary** approach (Lua-VM routes + decoded protocol; see [`protocol.md`](protocol.md),
> [`sniffing-playbook.md`](sniffing-playbook.md), [`xlua-state.md`](xlua-state.md)).
> What still holds is the **anti-cheat map**: *active* techniques (MITM/Frida/
> debuggers) are ACE-flagged, *passive* capture is safe — those empirical facts
> are why this page is kept (they are cited from
> [`dll-injection-vs-ace.md`](dll-injection-vs-ace.md)). Read the recommendation
> as historical; the ACE-behaviour findings as current.

**Status:** research spike (task #366). No code shipped. This document records
what the client is, what interception would take, what the anti-cheat allows,
and a recommendation.

**TL;DR:** Protocol-level automation is **not recommended** for this game right
now. The official PC client is Unity/IL2CPP behind Tencent **ACE** (Ring-0
kernel anti-cheat). Every *active* interception technique (MITM cert injection,
Frida, memory reading, debuggers) is exactly what ACE is built to detect and
will get the account banned and/or crash the client. The only ACE-transparent
technique — *passive* packet capture — yields TLS ciphertext we cannot decrypt
without a key we can only get through the active techniques ACE blocks. The
effort/risk/reward is poor. Vision-based automation (current approach) stays
the right layer. This doc keeps the full methodology on file in case the
calculus changes (e.g. we decide to run the *emulator* build instead of the
official client).

---

## 1. What the client actually is

| Property | Finding | Source |
|---|---|---|
| Engine | Unity | search: Unity Discussions thread on Last War / Whiteout networking |
| Scripting backend | **IL2CPP** (C# → C++ → native `GameAssembly.dll`) | Unity docs; il2cpp RE guides |
| Anti-cheat | **ACE — Anti-Cheat Expert** (Tencent), Ring-0 kernel driver on the official PC client | anticheatexpert.com; PCGamingWiki |
| PC distribution | Official standalone **FUNFLY / FirstFun** DirectX client (native, ships ACE). Also runnable via Google Play Games for PC and Android emulators (BlueStacks/MEmu/LDPlayer). | uptodown / bluestacks / ldplayer listings |

Our bot targets the **official native client** (see `AGENTS.md` §1). That is the
worst target for protocol RE and the best-protected one.

### Why IL2CPP matters
The classic easy path (see nc-lp.com "Reverse engineering games for fun and
SSRF") relies on Unity's **Mono** backend, where all game logic sits in a
plain-.NET `Assembly-CSharp.dll` you open in dotPeek/dnSpy and read directly.
**IL2CPP does not give you that.** Logic is compiled to native code in
`GameAssembly.dll`; you must first run `Il2CppInspector` / `Il2CppDumper`
against the binary + `global-metadata.dat` to reconstruct type/method names,
then work in IDA/Ghidra on machine code. That is an order of magnitude more work
and produces no clean protocol schema by itself.

---

## 2. Expected protocol shape (hypothesis, unverified)

Based on the genre (FirstFun / Century Games survival-4X titles behave alike):

- **Login / config / CDN:** HTTPS REST (JSON). Returns a session token and the
  gateway address for the realtime channel.
- **Realtime gameplay channel:** a persistent connection — most likely
  **WebSocket (`wss://`)** or raw TCP — carrying **length-prefixed binary
  frames**.
- **Frame payload:** almost certainly **Protobuf**, likely **gzip-compressed**,
  and very likely wrapped in an **app-layer cipher (AES or XOR/stream)** whose
  key is negotiated at handshake or derived from the session token.
- **Transport crypto:** TLS on top of all of it, quite possibly with
  **certificate pinning** (common in this genre and trivially added by the ACE
  SDK).

This means **two independent layers of encryption**: transport TLS *and* an
application-layer cipher inside the protobuf frames. Breaking TLS alone is not
enough — you still hit the inner cipher, whose key lives in the IL2CPP binary.

---

## 3. The interception toolbox, mapped to this target

| Technique | What it gets you | ACE-visible? | Verdict here |
|---|---|---|---|
| **Passive capture** — Wireshark / `pcap` on host NIC, or port-mirror on a router | Packet timing, endpoints (SNI/IP), sizes. **Payload = TLS ciphertext.** | **No** — out-of-process, no injection, no cert tampering. Truly transparent. | Safe, but **decodes nothing** without keys. Good only for mapping endpoints. |
| **TLS MITM** — mitmproxy / Burp / Charles + install proxy CA | Decrypted TLS → the WS/HTTP frames | **Yes** — installing a CA + redirecting traffic + (if pinned) needing a pin bypass is exactly what ACE flags. Pinning also just drops the connection. | **Blocked / risky.** Ban vector. |
| **`SSLKEYLOGFILE`** — dump TLS session keys, feed to Wireshark | Decrypted TLS, passively, no MITM | Depends: only works if the client's TLS stack honors the env var. Unity/IL2CPP typically bundles its **own BoringSSL**, which does **not** read `SSLKEYLOGFILE`. | Usually **not available**. Worth a 5-min check but expect failure. |
| **Frida** — hook send/recv or the cipher functions in-process | Plaintext frames *before* encryption + the cipher keys | **Yes, loudly** — ACE advertises comprehensive anti-Frida / anti-debug; it kills injected modules and force-quits. | **Blocked / ban vector.** |
| **Static RE** — Il2CppDumper + IDA/Ghidra on `GameAssembly.dll` | The protobuf schema + cipher algorithm + key derivation, offline | Offline analysis is not detectable (ACE is a runtime guard). But the *result* still has to be exercised against a live server. | Legal-of-detection but **very high effort**; only worthwhile if we commit hard. |

---

## 4. The blocking chain (why the easy path fails)

```
want plaintext frames
  └─ need to defeat app-layer cipher  ── key is in GameAssembly.dll (IL2CPP) ──► heavy static RE
        └─ but first need to defeat TLS
              ├─ MITM + CA install ──────────────► ACE flags cert tampering / pinning drops conn
              ├─ SSLKEYLOGFILE ──────────────────► BoringSSL ignores it
              └─ Frida hook below TLS ───────────► ACE kills injected module / bans
```

Every branch either requires a technique ACE is purpose-built to detect, or
lands on a wall (BoringSSL, pinning, native binary).

---

## 5. Empirical signal from a sibling game

`batazor/whiteout-survival-autopilot` (GitHub) automates **Whiteout Survival** —
same publisher lineage, same Unity/IL2CPP/ACE stack, same 4X genre. Its authors
chose **screen-scraping + OCR + device control**, *not* protocol interception,
for end-to-end automation. When people who specialize in automating this exact
class of game do not go protocol-level, that is a strong prior that the
protocol path is not worth it for a bot.

---

## 6. Recommendation

1. **Keep vision/OCR as the automation layer.** It is ACE-transparent (no
   injection), matches the sibling-project consensus, and already works.
2. **Do the two cheap, zero-risk experiments** (below) purely to *characterize*
   the traffic — not to decode it. This turns "we think it's wss+protobuf" into
   fact and tells us how hard the real path would be, without touching ACE.
3. **Do not** install a proxy CA, run Frida, or attach a debugger against the
   **official client** — treat those as ban vectors.
4. **If** protocol access ever becomes worth the effort, do it against an
   **Android emulator build** in a throwaway/farm account (the emulator route is
   explicitly the "macros & farming" route per the PC-client comparisons), where
   Frida-on-Android + `frida-gadget` + Il2CppDumper is a well-trodden path and a
   ban costs nothing. Never against the operator's own main account.

---

## 7. Zero-risk next experiments (safe to run)

These are **passive only** — no injection, no cert install, no debugger. Safe on
the official client.

1. **Endpoint map (Wireshark, ~15 min).** Capture the host NIC while launching
   and playing. Record: login/CDN hosts (from TLS SNI + DNS), the realtime
   gateway host/port, whether the realtime channel is `:443` (likely wss) or a
   custom port (likely raw TCP), and connection lifetime/keepalive cadence.
   *Output: a table of hosts/ports/roles. No payloads.*
2. **Client-side log scrape (~10 min).** Check
   `%USERPROFILE%\AppData\LocalLow\<Company>\<Product>\` (Unity's `Player.log`
   / `output_log.txt`) for logged endpoints or WS URLs — the nc-lp write-up got
   the `wss://…:port` for free this way. Also grep the install dir for config
   files naming gateways.
3. **`SSLKEYLOGFILE` probe (~5 min).** Set the env var, launch, see if Wireshark
   can decrypt any TLS session. Expected to fail (BoringSSL), but it is free to
   confirm.

Anything beyond these three steps crosses into ACE's detection surface and needs
an explicit go/no-go decision plus an emulator + throwaway account.

---

## 8. Sources

- [Unity Discussions — how Whiteout Survival / Last War handle networking](https://discussions.unity.com/t/how-do-games-like-whiteout-survival-and-last-war-handle-networking/1597919)
- [Il2Cpp reverse-engineering guide (Il2CppInspector scaffold)](https://github.com/jadis0x/il2cpp-reverse-engineering-guide)
- [Unity Manual — IL2CPP scripting backend](https://docs.unity3d.com/6000.0/Documentation/Manual/scripting-backends-il2cpp.html)
- [Anti-Cheat Expert (ACE) — Tencent, product pages](https://intl.anticheatexpert.com/products/anti-cheat-pc/)
- [PCGamingWiki — Anti-Cheat Expert](https://www.pcgamingwiki.com/wiki/Anti-Cheat_Expert)
- [nc-lp.com — Reverse engineering games for fun and SSRF, part 1 (invisible-proxy + dotPeek methodology)](https://www.nc-lp.com/blog/reverse-engineering-games-for-fun-and-ssrf-part-1)
- [pbtk — toolkit for reverse-engineering Protobuf apps](https://github.com/marin-m/pbtk)
- [batazor/whiteout-survival-autopilot — sibling game, screen-scraping approach](https://github.com/batazor/whiteout-survival-autopilot)
- [Last War PC client / emulator listings (Uptodown, BlueStacks, LDPlayer)](https://last-war-survival.en.uptodown.com/windows)
