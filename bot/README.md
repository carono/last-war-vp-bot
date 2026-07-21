# `bot/` — runtime bot infrastructure

A clean, modular layer over the research tooling. It composes the proven pieces
(the wire protocol in `tools/lastwar_proto.py`, window capture in
`lastwar_bot.perception`) instead of re-implementing them — **no duplication**,
and `tools/` is never modified.

```
bot/
  core/
    protocol.py       transport primitives (TLV / XOR / zstd) — one source of truth
    process.py        find_game_pid(), get_hwnd(), is_game_running(), launch_game()
  state/
    game_state.py     GameState dataclass + Scene enum
    stream_reader.py  passive TCP decoder → keeps GameState current
    live.py           LiveState: drives dumpcap live → keeps GameState current
  actions/
    input.py          touch_tap(x, y), get_screenshot()
    navigation.py     go_to_world(), go_to_base()  (static toggle tap, no CV)
```

## State comes from the wire, not the screen

The client speaks plain TCP (no TLS), so state is inferred **passively** from
server push/response messages — never from screenshots:

| Signal | Source command(s) |
|---|---|
| `scene = WORLD` | `go.to.world`, `meteorite.enter.world`, `world.get.block`, `world.get.march.infos` |
| `scene = CITY` | `user.leave.world`, `building.production.collect` |
| `zoom` | `viewLvl` of the `world.get.block` request |
| `resources` | `push.resource.item.update` |

Navigation clicks are **static**: the base↔world switch is a single touch on the
shared bottom-right map toggle (`navigation.TOGGLE_BUTTON`), which sits in the
same spot on both screens and only swaps its icon. No template matching, no
screenshot — the tap is confirmed against the passive stream state, not pixels.

## Usage

```python
from bot.state import StreamReader

# Replay a capture offline (no game, no Windows needed):
reader = StreamReader.from_pcap("capture.pcapng")
print(reader.state.summary())        # <GameState scene=world zoom=0 ...>

# Or feed raw half-stream bytes from any tap (tshark / socket-dup):
reader = StreamReader()
reader.feed("down", server_bytes)
reader.feed("up", client_bytes)
```

Live, on the game host (Windows + Wireshark/npcap):

```python
from bot.state import LiveState, Scene
from bot.actions import navigation

with LiveState() as live:                 # dumpcap in a thread → live GameState
    live.wait_for(Scene.CITY, timeout=30)
    navigation.go_to_world(live.state)     # static tap; returns once WORLD is seen
    navigation.go_to_base(live.state)      # static tap; returns once CITY is seen
```

`StreamReader.from_pcap` runs on any platform with `scapy` installed and is the
basis for offline tests. `LiveState`, screenshot, touch and navigation need the
Windows runtime. The end-to-end round trip is exercised by
`tests/test_city_world_roundtrip.py` (skips cleanly when the game isn't running).
