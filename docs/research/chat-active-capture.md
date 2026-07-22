# Chat transport — active capture (2026-07-22)

Raw evidence behind the "chat is split across two connections" finding in
[`chat.md`](chat.md#1-transport--chat-is-split-across-two-connections). Unlike
the earlier passive-only work, this was an **active** investigation: the running
client was driven, every TCP socket of `LastWar.exe` was enumerated, and all of
them were captured at once — specifically to test the premise "chat lives on a
separate connection that can drop while the game runs."

## Method

1. `netstat -ano | findstr <pid>` to list **all** established sockets of
   `LastWar.exe` (not just `:17935`).
2. `dumpcap -i <wifi>` and `-i \Device\NPF_Loopback`, broad capture (all IP,
   only SSH/RDP/DNS excluded) for the whole login + chat session.
3. A background `netstat` poller (2 s) tagged each remote endpoint to the game
   PID over time, so pcap flows could be attributed to the game with certainty.
4. Drove the client (`tools/_chat_recon.py` for focus/screenshot/click): logged
   in, opened the chat panel, and visited World / National / Alliance / DM with
   timestamped action markers (`results/chat/actions.log`).
5. Post-analysis: `tshark -z conv,tcp`, `-z io,stat`, TLS SNI extraction, and
   `tools/lastwar_proto.py` to decode the plain-TCP `:17935` stream.

Capture artefacts live under `results/chat/` (git-ignored — they contain login
credential material and account identifiers; do not commit).

## All sockets of LastWar.exe at login

```
:17935  15.197.233.176          game gateway (plain TCP, lastwar_proto)
:443    15.197.233.176          lastwar-chat-wss-us-aws-ali / serverlist   (TLS)
:443    34.149.98.177  (GCP)    lastwar-chat-wss-us-gcp-ali / serverlist   (TLS)  <- live chat
:443    47.90.174.119  (Ali)    lastwar-chat-wss-us-ali                    (TLS)  dropped ~17s
:443    128.75.238.186 (x4)     lastwar-fight-report.akamaized.net         (TLS)  CDN
:443    104.17.132.15  (CF)     lw-c-log.lastwarapp.net                    (TLS)  telemetry
:443    198.19.223.146          te-receiver.lastwar.com                    (TLS)  telemetry
:80     198.18.55.8             (VPN-range HTTP)
10012/443/80  101.32.143.{247,64,142}, 129.226.{1.157,2.37}  Tencent SDK stubs (idle)
127.0.0.1     socketpairs (59882/59883, 61294/61295)         internal IPC
```

## TCP conversation volumes (tshark `-z conv,tcp`, game hosts)

| Flow | Pkts | Bytes | Dur | Note |
|---|---|---|---|---|
| `…:17935` (game) | 1195 | **471 KB** | 184 s | main gateway, full session |
| `104.17.132.15:443` (lw-c-log) | 403 | 234 KB | 180 s | telemetry/log upload |
| `34.149.98.177:443` (**chat-wss-gcp**) | 409 | 81 KB | 180 s | **live chat WebSocket** |
| `128.75.238.186:443` ×4 (fight-report) | ~55 | ~35 KB ea | ~26 s | battle-report CDN burst |
| `198.19.223.146:443` (te-receiver) | 138 | 54 KB | 179 s | telemetry |
| Tencent `:10012` / `:443` / `:80` (×15) | 5 ea | ~294 B ea | idle | SDK stubs, no chat |

The Tencent `:10012` servers — the obvious "separate chat" suspects — are inert:
each exchanges ~2 up / 3 down packets (~300 B) then sits idle for 3 minutes.

## Chat on `:17935` (decoded)

`python tools/lastwar_proto.py results/chat/game_17935.pcapng --timeline`:

```
common.chat.room.id      -> allRooms = [country_935, custom_lang_ru_935]
chat.get.system.mails    -> push.chat.get.system.mails
lw.user.push.chat.msg  x4 (DM room custom_1697…_1522…_v2): '', 'hhhhh'  + acks
chat.stat              x4 (roomId=…_v2, type=1, msgExtra.srcLang=ru)
al.show.help / alliance.notice.* / get.alliance.share.mission.list
push.all.notice / push.new.news / push.al.help.new
```

**`push.chat` broadcast frames on `:17935` during the session: 0.** The world
ticker was scrolling continuously the whole time, so the client was receiving
world chat — just not here.

## Chat WebSocket timeline (tshark `-z io,stat`, `34.149.98.177:443`)

```
Interval (s)  frames  bytes      <- 15s buckets
  0 .. 240        0       0      (pre-login: socket exists but quiet)
240 .. 255       25    7799      login handshake
255 .. 270      133   55220      *** opened chat tabs -> history load (world/alliance) ***
270 .. 405    ~20-49/bucket  1-17KB   steady live stream + heartbeats
```

Established at login, held open persistently, streaming for the entire session
= a long-lived WebSocket, not a one-shot fetch. The 255–270 s spike aligns with
the recorded chat-tab actions in `results/chat/actions.log`.

## Conclusion

- The **live broadcast chat** (world / national / alliance firehose) rides a
  **dedicated TLS WebSocket**, `lastwar-chat-wss-us-*-ali.lastwargame.com:443`,
  separate from the `:17935` game gateway and **multi-cloud with failover**
  (Alibaba → GCP observed) — so it can drop independently of the game. This
  confirms the task premise.
- The `:17935` game gateway still carries chat **control**: room registry, DM
  send/receive, system mails, alliance-social RPCs and game notifications — all
  in the plain-TCP `lastwar_proto` binary format.
- Because the broadcast leg is TLS, its wire format is not passively decodable;
  the SNI (`chat-wss`) plus the zero-`push.chat`-on-`:17935` result identify it
  by elimination. Decoding it would need a TLS keylog / MITM, which project
  policy rules out (passive only).

## Open follow-ups

- Confirm the WSS is literally a WebSocket upgrade (needs TLS decryption) and
  whether it speaks JSON, protobuf, or the same TLV as `:17935`.
- Does an **outgoing** world/alliance message go out on `:17935`, on the WSS, or
  both? Only a DM send was captured on `:17935`; a world/alliance send was not
  exercised (would post visibly to other players).
- Map the `lastwar-serverlist-*` role (shares IPs with the chat WSS).
