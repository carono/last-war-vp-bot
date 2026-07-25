"""Diagnose where dup_game_socket_by_lport hangs.

Run:
    /mnt/c/Python312/python.exe tools/_diag_handle_scan.py
"""
import sys, os, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, "tools/lib")
sys.path.insert(0, os.path.dirname(__file__))

import steal_via_socket as steal
import ctypes, ctypes.wintypes as wintypes
import psutil

GAME_PORT = 17935

def diag():
    # 1. Find game PID and local port
    pid = None
    local_port = None
    for c in psutil.net_connections(kind="tcp"):
        if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
            pid = c.pid
            local_port = c.laddr.port
            print(f"[diag] game pid={pid} local_port={local_port}")
            break
    if not pid:
        print("[diag] ERROR: no :17935 ESTABLISHED")
        return 1

    win = steal._win()
    k32, ws2 = win["k32"], win["ws2"]

    # 2. OpenProcess
    t0 = time.perf_counter()
    hgame = k32.OpenProcess(steal.PROCESS_DUP_HANDLE, False, pid)
    print(f"[diag] OpenProcess: {'ok' if hgame else 'FAIL err=' + str(ctypes.get_last_error())}  {(time.perf_counter()-t0)*1000:.1f}ms")
    if not hgame:
        return 1

    hself = k32.GetCurrentProcess()

    # 3. _enum_system_handles — just count how many and how long
    t0 = time.perf_counter()
    count = 0
    game_count = 0
    gen = steal._enum_system_handles()
    print("[diag] starting _enum_system_handles iteration...")
    for hpid, hval, _obj, _tidx in gen:
        count += 1
        if hpid == pid:
            game_count += 1
        if count == 1:
            print(f"[diag] first yield at {(time.perf_counter()-t0)*1000:.1f}ms")
        if count % 50000 == 0:
            print(f"[diag] ... {count} handles ({game_count} game)  {(time.perf_counter()-t0)*1000:.1f}ms")
    elapsed = (time.perf_counter()-t0)*1000
    print(f"[diag] enumerated {count} total handles, {game_count} for pid={pid} in {elapsed:.1f}ms")

    # 4. Get socket ObjectTypeIndex
    import socket as _socket, os
    print("\n[diag] finding socket ObjectTypeIndex...")
    t0 = time.perf_counter()
    sock_tidx = steal._socket_type_idx()
    print(f"[diag] socket ObjectTypeIndex={sock_tidx}  {(time.perf_counter()-t0)*1000:.1f}ms")

    # 5. Single-pass dup_game_socket_by_lport
    print(f"\n[diag] calling steal.dup_game_socket_by_lport (single-pass)...")
    t0 = time.perf_counter()
    k32.CloseHandle(hgame)  # close our test hgame; function opens its own
    try:
        hv, hd = steal.dup_game_socket_by_lport(pid, local_port)
        elapsed = (time.perf_counter()-t0)*1000
        print(f"[diag] FOUND game socket hval=0x{hv:x} in {elapsed:.1f}ms")
        k32.CloseHandle(hd)
        return 0
    except OSError as e:
        elapsed = (time.perf_counter()-t0)*1000
        print(f"[diag] NOT FOUND: {e} in {elapsed:.1f}ms")
        return 1

if __name__ == "__main__":
    raise SystemExit(diag())
