# City (base) protocol — what the wire shows on a City↔World switch

Passive capture experiment: enter the City/base while sniffing the game connection,
to enumerate base entities (buildings, troops, resources, NPCs, build queues) from the
protocol. **Headline result is negative and important:** on a *warm* (already-logged-in)
client, switching World→City transmits **no base data** — the server sends zero
application payload during a scene switch. Base state is loaded once at login and cached
client-side; `SceneUtils.ChangeToCity()` is a local render, not a data fetch.

This is a companion to `protocol.md` (framing/transport) and
`game-launch-and-scene-control.md` (the Lua scene switch used to drive the transition).

## Method (exact sequence run)

1. Game already running and logged in (pid 35688), scene = **World**.
2. Started a passive sniffer, then switched to City *during* the capture, then waited
   for the client to settle. Two capture passes:
   - **Pass A** — `tools/secret_task_capture.py --seconds 60 --dump results/city_capture.jsonl`
     (scapy/npcap, `--dump` = full decoded transcript, both directions) while firing
     `tools/lua_goto_world.py --to-city` (World→City).
   - **Pass B** — `dumpcap.exe -i 1 -i 2 -i 13 -f "tcp port 17935" -a duration:50 -w
     results/city_capture2.pcapng` (raw pcap on the physical Wireless + bridge +
     vEthernet interfaces at once) while doing a City→World→City round-trip, then decoded
     offline with the robust decoder: `tools/lastwar_proto.py results/city_capture2.pcapng
     --json results/city_decoded2.json`.

The scene switches were confirmed from the game's own Lua flags (Player.log markers):
`GetIsInWorld`/`GetIsInCity` flipped as expected each time.

## The decisive finding — the server sends nothing on a scene switch

`tshark` direction analysis of the raw pcap (`results/city_capture2.pcapng`), game flow
`172.65.210.24:17935`:

| direction | frames with TCP payload |
|---|---|
| client → server (up) | **51** |
| server → client (down) | **0** |
| total game-port frames | 102 (51 requests + 51 bare ACKs) |

The server **ACKs** every client packet (so the down direction *is* being captured — this
is not an asymmetric-routing miss) but sends **0 bytes of application payload**. The first
pass agreed independently: `up 1,728B / down 0B`.

Interface caveat learned along the way: capturing only on the Hyper-V `vEthernet` adapter
(`\Device\NPF_{6FEC8683…}`, dumpcap `-i 13`) sees **only the outbound** direction; the
physical Wireless/bridge adapters (`-i 1 -i 2`) see both — but even there the game server's
down payload was 0. So the negative result is real, not a capture artifact.

**Conclusion:** buildings, troops, resources, NPCs and build queues were **not** observed,
because that data does not cross the wire on a City↔World switch. It is part of the base
snapshot the client receives **once at login** and then keeps; re-entering the base renders
from the cached model without a server round-trip.

## What the capture *did* contain — client→server request schemas

The only game payload seen was client→server: a 4-second **keepalive** and a handful of
**world**-side requests fired while leaving/entering the world map. None of these are
base/city entities, but the schemas are useful protocol intel. Observed field sets and
example values (server IDs / coords are from this account's session):

| command | fields (example values) | notes |
|---|---|---|
| `(keepalive)` | `clientTime` (ms, monotonic) | ~every 4 s, action 29/13 |
| `user.leave.world` | `serverId=935, worldId=0, _id` | fired on World→City |
| `go.to.world` | `_id` | world-entry handshake |
| `world.get.block` | `bigMap=1, x=2561, y=2492, serverId=935, worldId=0, type=0, viewLvl=0, timeStamp, blockSize=10, index=[74354,74355,…], clearUuidSet=1, leftBottom=7412541, rightTop=7532581, _id` | **world-map tile query** — `index[]` is the list of tile IDs in the viewport; `leftBottom`/`rightTop` bound the block; `blockSize=10` tiles/side. This is the map-scan request `secret_task_capture` etc. rely on. |
| `world.get.march.infos` | `x=561, y=492, needCross=true, _id` | march/troop info at a world coord (the closest thing to "troops" seen, but world-side, not base) |
| `meteorite.enter.world` | `targetServerId=935, _id` | server/event enter |
| `world.flag.get.can.effect` | `worldId=0, _id` | alliance flag effect check |
| `surprise.point.get.info` | `_id` | world event point |
| `get.world.news.info` | `_id` | world news feed |

Every request carries an incrementing `_id` (per-connection request counter). No response
bodies were captured (see above), so field *types* here are from the request side only.

## How to actually capture base/city entities

Since the base snapshot is a **login cold-load**, the only reliable way to see buildings /
troops / resources / build queues on the wire is to **capture across a fresh login**:

1. Start the raw pcap first (`dumpcap -i 1 -i 2 -f "tcp port 17935" -w login.pcapng`,
   physical interfaces so the down direction is present).
2. *Then* start the game (cold), or force a re-login, so the full base+world state burst
   is on the wire.
3. Decode offline with `tools/lastwar_proto.py login.pcapng --json login.json` and look at
   the **server → client** messages (the down direction, empty here) for the base
   snapshot — command names likely `user.*` / `city.*` / `build.*` rather than `world.*`.

That is a more invasive run (it kills/relaunches the single-session client and risks an
account kick) and was **not** performed here — this experiment deliberately stayed within
the passive "switch scene and watch" method. Do the login capture only with explicit
sign-off.

## Artifacts (local, git-ignored under `results/`)

- `results/city_capture.jsonl` — pass A decoded transcript (20 frames, all up).
- `results/city_capture.pcapng` — pass B single-interface raw pcap (up only; interface lesson).
- `results/city_capture2.pcapng` — pass B multi-interface raw pcap (both directions; server down payload = 0).
- `results/city_decoded.json`, `results/city_decoded2.json` — offline `lastwar_proto` decodes.
