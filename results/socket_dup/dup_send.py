"""One-off: dup the game's :17935 socket via the reliable find-handle path and
send a go.to.world frame. Reuses steal_via_socket's own functions; sends only
the safe reversible transport probe. Sniffs a fresh _id (nudging the client so
upstream frames flow) and sends a small bracket of ids to absorb an off-by-one
in the sniffed counter. Nothing here touches `steal`.
"""
import ctypes
import sys
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import steal_via_socket as S  # noqa: E402

SERVER_ID = 935
K1, K2 = 0x11, 0x22


def _game_hwnd():
    import win32gui
    r = []
    def cb(h, acc):
        if win32gui.IsWindowVisible(h) and "Last War" in win32gui.GetWindowText(h):
            acc.append(h)
    win32gui.EnumWindows(cb, r)
    return r[0] if r else None


def nudge_loop(stop):
    import win32gui, win32con, pydirectinput
    h = _game_hwnd()
    if not h:
        print("no game window for nudge")
        return
    win32gui.ShowWindow(h, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(h)
    time.sleep(0.3)
    pydirectinput.PAUSE = 0.08
    ox, oy = 128, 41
    targets = [(1605, 185), (1600, 790), (1600, 880)]  # events / alliance / mail
    while not stop.is_set():
        for (x, y) in targets:
            if stop.is_set():
                break
            pydirectinput.click(ox + x, oy + y)
            time.sleep(0.6)
            pydirectinput.press("esc")
            time.sleep(0.4)


def main():
    stop = threading.Event()
    th = threading.Thread(target=nudge_loop, args=(stop,), daemon=True)
    th.start()
    res = S.sniff_live_params(11.0)  # returns (next_id, server_id) or None
    stop.set()
    if not res:
        print("SNIFF FAILED")
        return 1
    next_id, sid = res
    sid = sid or SERVER_ID
    print(f"sniffed next_id={next_id} server_id={sid}")

    pid, _ = S.find_game()
    if not pid:
        print("no game pid")
        return 1

    # Reliable path: dup ALL sockets (this is what --find-handle uses and it
    # surfaces :17935 dependably), then pick the game socket.
    socks = S.dup_game_sockets(pid)
    game = [(h, d, p) for (h, d, p) in socks if p[1] == S.GAME_PORT]
    others = [d for (h, d, p) in socks if p[1] != S.GAME_PORT]
    win = S._win()
    k32, ws2 = win["k32"], win["ws2"]
    for d in others:
        k32.CloseHandle(d)
    if not game:
        print("game :17935 socket did not surface in dup pass")
        for _h, d, _p in game:
            k32.CloseHandle(d)
        return 1
    hval, dup, peer = game[0]
    for _h, d, _p in game[1:]:
        k32.CloseHandle(d)
    print(f"pinned game socket 0x{hval:x} -> {peer[0]}:{peer[1]}")

    # Bracket ids: next_id-1 .. next_id+2 to absorb a capture off-by-one. Each
    # frame is go.to.world (reversible, no cost); the server accepts the one
    # matching its expected counter and drops the rest.
    for rid in (next_id - 1, next_id, next_id + 1, next_id + 2):
        frame = S.build_test_frame(sid, K1, K2, rid)
        sent = ws2.send(ctypes.c_void_p(dup.value), frame, len(frame), 0)
        err = ctypes.get_last_error() if sent != len(frame) else 0
        print(f"  id={rid} sent={sent}/{len(frame)} err={err}")
        time.sleep(0.25)
    k32.CloseHandle(dup)
    print("DONE (bracket sent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
