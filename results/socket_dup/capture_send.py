"""Definitive go.to.world socket-dup test with acceptance proof.

One live decoder watches BOTH directions on the game stream:
  * upstream  -> learn the client's current max `_id` (so we can send next+1)
  * downstream-> catch the server's reply carrying OUR `_id`

Sequence: capture starts, a nudge thread drives real client RPCs so upstream
frames (and their `_id`) flow, then mid-window we dup the :17935 socket (the
reliable find-handle path) and send a small bracket of go.to.world frames, then
keep capturing to record any downstream frame whose `_id` is one we sent. A
downstream frame echoing our `_id` == the server accepted a frame the client
never sent == the duplicated socket is a working command channel.

go.to.world only; reversible; no `steal`.
"""
import ctypes
import sys
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import steal_via_socket as S  # noqa: E402
import lastwar_proto as proto  # noqa: E402
from live_sniffer import LiveDecoder  # noqa: E402
from live_tshark import capture, find_binary, list_interfaces  # noqa: E402

SERVER_ID = 935
K1, K2 = 0x11, 0x22

state = {"max_up": -1}
down_frames = []  # list of dicts: {_id, command, success, keys}
sent_ids = set()
lock = threading.Lock()


class Collector(LiveDecoder):
    def emit(self, direction, env):
        try:
            command = proto.envelope_command(env) or "(keepalive)"
            payload = proto.envelope_payload(env) or {}
        except Exception:
            return
        rid = payload.get("_id") if isinstance(payload, dict) else None
        if direction == "up":
            if isinstance(rid, int) and rid > state["max_up"]:
                state["max_up"] = rid
        else:  # down
            with lock:
                down_frames.append({
                    "_id": rid,
                    "command": command,
                    "success": payload.get("success") if isinstance(payload, dict) else None,
                    "keys": list(payload.keys()) if isinstance(payload, dict) else None,
                })


def game_hwnd():
    import win32gui
    r = []
    def cb(h, acc):
        if win32gui.IsWindowVisible(h) and "Last War" in win32gui.GetWindowText(h):
            acc.append(h)
    win32gui.EnumWindows(cb, r)
    return r[0] if r else None


def nudge_loop(stop):
    import win32gui, win32con, pydirectinput
    h = game_hwnd()
    if not h:
        return
    win32gui.ShowWindow(h, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(h)
    time.sleep(0.3)
    pydirectinput.PAUSE = 0.08
    ox, oy = 128, 41
    targets = [(1605, 185), (1600, 790), (1600, 880)]
    while not stop.is_set():
        for (x, y) in targets:
            if stop.is_set():
                break
            pydirectinput.click(ox + x, oy + y)
            time.sleep(0.6)
            pydirectinput.press("esc")
            time.sleep(0.4)


def send_bracket():
    pid, _ = S.find_game()
    socks = S.dup_game_sockets(pid)
    game = [(h, d, p) for (h, d, p) in socks if p[1] == S.GAME_PORT]
    win = S._win()
    k32, ws2 = win["k32"], win["ws2"]
    for _h, d, p in socks:
        if p[1] != S.GAME_PORT:
            k32.CloseHandle(d)
    if not game:
        print("  !! game :17935 did not surface")
        return
    hval, dup, peer = game[0]
    for _h, d, _p in game[1:]:
        k32.CloseHandle(d)
    base = state["max_up"]
    if base < 0:
        print("  !! no upstream _id learned; using default 200")
        base = 200
    next_id = base + 1
    print(f"  learned max_up={base} -> next_id={next_id}; pinned 0x{hval:x} {peer}")
    for rid in range(next_id - 1, next_id + 4):
        frame = S.build_test_frame(SERVER_ID, K1, K2, rid)
        sent = ws2.send(ctypes.c_void_p(dup.value), frame, len(frame), 0)
        with lock:
            sent_ids.add(rid)
        print(f"    id={rid} sent={sent}/{len(frame)}")
        time.sleep(0.2)
    k32.CloseHandle(dup)


def main():
    tshark = S._wireshark_binary("tshark.exe", find_binary)
    dumpcap = S._wireshark_binary("dumpcap.exe", find_binary) or tshark
    ifaces = list_interfaces(tshark)
    if not ifaces:
        print("no interfaces")
        return 1
    decoder = Collector()
    stop = threading.Event()
    procs = []
    cap_threads = [
        threading.Thread(target=capture,
                         args=(dumpcap, num, lbl, decoder, "tcp", stop, False, procs),
                         daemon=True)
        for num, lbl in ifaces
    ]
    nstop = threading.Event()
    nth = threading.Thread(target=nudge_loop, args=(nstop,), daemon=True)

    print("capture starting…")
    for t in cap_threads:
        t.start()
    nth.start()
    time.sleep(9)          # let upstream _id flow via nudges
    print("=== sending bracket ===")
    send_bracket()
    time.sleep(6)          # catch the server reply
    nstop.set()
    stop.set()
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    # dumpcap.exe children don't die from p.kill() across the WSL boundary; nuke
    # them by name so the process can exit and this run doesn't leak captures.
    import subprocess
    try:
        subprocess.run(["taskkill.exe", "/F", "/IM", "dumpcap.exe"],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    time.sleep(0.5)

    print("\n=== downstream frames carrying one of our sent _ids ===")
    hits = [f for f in down_frames if f["_id"] in sent_ids]
    if hits:
        for f in hits:
            print(f"  ACCEPTED reply _id={f['_id']} command={f['command']} "
                  f"success={f['success']} keys={f['keys']}")
    else:
        print("  (none) — no downstream frame echoed our _id")
    print(f"\nsent_ids={sorted(sent_ids)}")
    down_ids = sorted({f['_id'] for f in down_frames if isinstance(f['_id'], int)})
    print(f"all downstream _ids seen ({len(down_frames)} frames): {down_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
