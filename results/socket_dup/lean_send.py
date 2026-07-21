"""Lean sender: dup the :17935 game socket and send a go.to.world bracket.

No sniffing, no threads — takes the next `_id` as argv so a bash retry loop can
wrap each attempt in `timeout` (the handle-dup path can transiently miss the
socket or block in getpeername). Prints SENT lines on success. go.to.world only.

Usage: python lean_send.py <next_id>
"""
import ctypes
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import steal_via_socket as S  # noqa: E402

SERVER_ID = 935
K1, K2 = 0x11, 0x22


def main():
    next_id = int(sys.argv[1])
    pid, _ = S.find_game()
    if not pid:
        print("NO_PID", flush=True)
        return 1
    socks = S.dup_game_sockets(pid)
    win = S._win()
    k32, ws2 = win["k32"], win["ws2"]
    game = [(h, d, p) for (h, d, p) in socks if p[1] == S.GAME_PORT]
    for _h, d, p in socks:
        if p[1] != S.GAME_PORT:
            k32.CloseHandle(d)
    if not game:
        print("NO_SURFACE", flush=True)
        return 2
    hval, dup, peer = game[0]
    for _h, d, _p in game[1:]:
        k32.CloseHandle(d)
    print(f"PINNED 0x{hval:x} {peer[0]}:{peer[1]}", flush=True)
    for rid in range(next_id - 2, next_id + 4):
        frame = S.build_test_frame(SERVER_ID, K1, K2, rid)
        sent = ws2.send(ctypes.c_void_p(dup.value), frame, len(frame), 0)
        print(f"SENT id={rid} bytes={sent}/{len(frame)}", flush=True)
    k32.CloseHandle(dup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
