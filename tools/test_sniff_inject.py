"""End-to-end test: sniff live _id, inject go.to.world, verify server reply.

Approach: call sniff_and_inject() directly in a thread (same process, no
subprocess) while the main thread clicks the game to trigger upstream RPCs.
Running in-process avoids the focus-stealing that happens when dumpcap.exe
console windows appear from a subprocess chain.

Usage (Windows Python):
    /mnt/c/Python312/python.exe tools/test_sniff_inject.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

# Log file for debugging — written in append mode alongside stdout.
_LOG_PATH = r"C:\Temp\inject_test.log"
try:
    os.makedirs(r"C:\Temp", exist_ok=True)
except Exception:
    _LOG_PATH = None

_log_lock = threading.Lock()


def _log(msg: str) -> None:
    """Write msg to the log file (non-blocking, never raises)."""
    if not _LOG_PATH:
        return
    try:
        with _log_lock:
            with open(_LOG_PATH, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(msg if msg.endswith("\n") else msg + "\n")
    except Exception:
        pass

GAME_TITLE = "Last War-Survival Game"


# ---------------------------------------------------------------------------
# Monkey-patch subprocess.Popen inside live_tshark so dumpcap processes are
# launched without a console window, which would otherwise briefly steal focus
# from the game and cause pydirectinput clicks to land in the console instead.
# ---------------------------------------------------------------------------

_orig_popen = subprocess.Popen


class _NoConsolePopen(_orig_popen):
    def __init__(self, args, **kwargs):
        kwargs.setdefault("creationflags", 0)
        kwargs["creationflags"] |= 0x08000000   # CREATE_NO_WINDOW
        super().__init__(args, **kwargs)


subprocess.Popen = _NoConsolePopen   # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Game window helpers
# ---------------------------------------------------------------------------


def _game_hwnd() -> int:
    import win32gui
    hwnd = win32gui.FindWindow(None, GAME_TITLE)
    if not hwnd:
        results: list[int] = []

        def _cb(h: int, _: object) -> None:
            t = win32gui.GetWindowText(h)
            if "last war" in t.lower():
                results.append(h)

        win32gui.EnumWindows(_cb, None)
        hwnd = results[0] if results else 0
    return hwnd


def _refocus() -> None:
    """Bring the game to the foreground and verify it actually got there."""
    import win32gui
    hwnd = _game_hwnd()
    if not hwnd:
        return
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception as _e:
        print(f"[orch] SetForegroundWindow skipped: {_e}")
        return
    time.sleep(0.3)
    # Confirm the game window is actually in the foreground now.
    fg = win32gui.GetForegroundWindow()
    if fg != hwnd:
        print(f"[orch] WARNING SetForegroundWindow failed "
              f"(current fg={hex(fg)}, game={hex(hwnd)})")


def dismiss_dialogs() -> None:
    """Close any open menu/dialog by clicking the back button (bottom-left panel).

    NOTE: pressing Escape is intentionally avoided because in Last War it
    opens the 'Exit game?' confirmation dialog instead of closing popups.
    """
    import pydirectinput
    import win32gui

    hwnd = _game_hwnd()
    if not hwnd:
        return
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    rect = win32gui.GetWindowRect(hwnd)
    ox, oy = rect[0], rect[1]
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]

    # Back-arrow button appears at ~(460, 1083) in window coords when a
    # sub-menu (Events, Alliance, etc.) is open. Click it to go back to base.
    bx = ox + int(0.276 * w)
    by = oy + int(0.970 * h)
    print(f"[orch] clicking back button at ({bx},{by}) to close any open menu.")
    pydirectinput.click(bx, by)
    time.sleep(0.8)


def click_game_buttons() -> bool:
    """Click Events then UserPanel to trigger upstream RPCs with _id.

    Empirically measured 2026-07-20 on window (128,41)→(1791,1158) = 1663×1117:
      Events button : abs (1726, 152) → fires activity.hero.get.info + rank RPCs
      UserPanel     : abs (1726, 677) → fires get.user.info.multi
    """
    try:
        import win32gui
        import pydirectinput

        hwnd = _game_hwnd()
        if not hwnd:
            print("[orch] WARNING: game window not found")
            return False

        _refocus()
        rect = win32gui.GetWindowRect(hwnd)
        ox, oy = rect[0], rect[1]
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]

        # First close any open submenu so Events click fires fresh RPCs.
        # Back button (bottom-left) closes submenus without triggering exit dialog.
        back_x = int(ox + 0.276 * w)
        back_y = int(oy + 0.970 * h)
        print(f"[orch] clicking Back at ({back_x},{back_y}) to close any open menu", flush=True)
        pydirectinput.click(back_x, back_y)
        time.sleep(1.0)

        # Then open Events — fires a burst of 3 RPCs (activity.hero.get.info etc.).
        # UserPanel is intentionally NOT clicked: it would send an RPC right as
        # we finish the burst-settle, colliding with inject_id.
        ev_x = int(ox + 0.960 * w)
        ev_y = int(oy + 0.100 * h)
        print(f"[orch] clicking Events at ({ev_x},{ev_y})", flush=True)
        pydirectinput.click(ev_x, ev_y)
        time.sleep(0.5)   # short delay — just enough to let the click register

        return True
    except Exception as exc:
        print(f"[orch] click error: {exc}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    import steal_via_socket as steal

    # Bring the game to foreground without any spurious map clicks.
    _refocus()
    time.sleep(0.5)

    pid, exe = steal.find_game()
    if not pid:
        print("[orch] Last War is not running.")
        return 1
    print(f"[orch] game pid={pid}  {exe}")

    # -----------------------------------------------------------------------
    # Pre-capture the game socket BEFORE starting the 17 capture threads.
    # Strategy: use psutil TCP table (getpeername-free, no VPN issue) to learn
    # the LOCAL port of the game's :17935 connection, then find the handle by
    # getsockname() (local port only — also VPN-independent and fast).
    # -----------------------------------------------------------------------
    print("[orch] pre-capturing game socket handle (getsockname approach)…", flush=True)
    _gsock = steal.game_socket(pid)
    if not _gsock:
        print("[orch] ERROR: no established :17935 connection found via psutil")
        return 1
    _laddr, _raddr, _status = _gsock
    _local_port = _laddr.port
    print(f"[orch] game TCP {_laddr.ip}:{_local_port} -> {_raddr.ip}:{_raddr.port} [{_status}]", flush=True)

    import ctypes as _ct
    import ctypes.wintypes as _wt
    import struct as _struct
    _k32 = steal._win()["k32"]
    _ws2 = steal._win()["ws2"]
    _ws2.getsockname.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_void_p]
    _ws2.getsockname.restype = _ct.c_int
    _hgame = _k32.OpenProcess(steal.PROCESS_DUP_HANDLE, False, pid)
    if not _hgame:
        print("[orch] ERROR: OpenProcess failed")
        return 1
    _hself = _k32.GetCurrentProcess()

    def _sockname(dup_val):
        """Get local port from a socket handle via getsockname — no VPN issue."""
        sa = _ct.create_string_buffer(128)
        sa_len = _ct.c_int(128)
        rc = _ws2.getsockname(_ct.c_void_p(dup_val), sa, _ct.byref(sa_len))
        if rc != 0:
            return None
        # sockaddr_in: family(2) + port(2 BE) + addr(4) + pad(8)
        if sa_len.value >= 4:
            port = _struct.unpack_from(">H", sa.raw, 2)[0]
            return port
        return None

    _game_dup = None
    _game_peer = (_raddr.ip, _raddr.port)
    _game_h_orig = None
    _n_scanned = 0
    for _hpid, _hval, _obj, _tidx in steal._enum_system_handles():
        if _hpid != pid:
            continue
        _n_scanned += 1
        _dup = _wt.HANDLE()
        if not _k32.DuplicateHandle(_hgame, _wt.HANDLE(_hval), _hself,
                                    _ct.byref(_dup), 0, False, steal.DUPLICATE_SAME_ACCESS):
            continue
        _port = _sockname(_dup.value)
        if _port == _local_port:
            _game_dup = _dup
            _game_h_orig = _hval
            print(f"[orch] game socket found: local={_laddr.ip}:{_port} "
                  f"handle={_hval} scanned={_n_scanned}", flush=True)
            break
        else:
            _k32.CloseHandle(_dup)
    _k32.CloseHandle(_hgame)

    if _game_dup is None:
        print(f"[orch] ERROR: handle for local port {_local_port} not found "
              f"after scanning {_n_scanned} game handles")
        return 1

    # sniff_and_inject blocks until it has captured an upstream _id, injected
    # the frame, and optionally received the server reply. Run it in a thread
    # so the main thread can click the game to produce the upstream traffic.
    result: dict[str, object] = {}

    class _Args:
        # server_id confirmed from Events leaderboard: "#935 [TLou]Carono"
        server_id = 935
        k1 = 0x11
        k2 = 0x22

    def _inject():
        # Inline version of sniff_and_inject with verbose emit logging.
        import threading as _th
        import lastwar_proto as _proto
        from live_sniffer import LiveDecoder as _LD
        from live_tshark import capture as _cap, find_binary as _fb, list_interfaces as _li

        _tshark = steal._wireshark_binary("tshark.exe", _fb)
        _dumpcap = steal._wireshark_binary("dumpcap.exe", _fb) or _tshark
        _ifaces = _li(_tshark)
        print(f"[inject] {len(_ifaces)} interfaces, tshark={_tshark}", flush=True)

        _state: dict = {
            "max_id": -1, "server_id": None, "inject_id": None,
            "reply": None, "got_id": _th.Event(), "inject_seen_at": None,
        }
        _stop = _th.Event()
        _procs: list = []

        class _Verbose(_LD):
            def emit(self, direction, env):
                try:
                    payload = _proto.envelope_payload(env) or {}
                except Exception:
                    return
                if not isinstance(payload, dict):
                    return
                cmd = _proto.envelope_command(env) or "(keepalive)"
                rid = payload.get("_id")
                print(f"[emit] {direction} {cmd} _id={rid}", flush=True)
                if direction == "up":
                    if isinstance(rid, int) and rid > _state["max_id"]:
                        _state["max_id"] = rid
                        sid = payload.get("serverId")
                        if isinstance(sid, int):
                            _state["server_id"] = sid
                        print(f"[emit] got_id={rid} server_id={_state['server_id']}", flush=True)
                        _state["got_id"].set()
                elif direction == "down":
                    inj = _state["inject_id"]
                    # Log ALL downstream frames with _id while waiting for reply.
                    if inj is not None and isinstance(rid, int):
                        msg = f"[emit] down-id cmd={cmd} _id={rid} payload={dict(list(payload.items())[:8])}"
                        print(msg, flush=True)
                        _log(msg)
                    if inj is not None and payload.get("_id") == inj:
                        _state["reply"] = {"_id": payload.get("_id"),
                                           "success": payload.get("success"),
                                           "cmd": cmd}
                        msg = f"[emit] REPLY _id={payload.get('_id')} success={payload.get('success')} cmd={cmd} payload={dict(list(payload.items())[:12])}"
                        print(msg, flush=True)
                        _log(msg)

                # Track when pcap confirms our injected frame upstream
                if direction == "up" and _state["inject_id"] is not None:
                    if payload.get("_id") == _state["inject_id"]:
                        import time as _tt
                        _state["inject_seen_at"] = _tt.time()
                        msg = f"[emit] INJECT CONFIRMED upstream _id={payload.get('_id')}"
                        print(msg, flush=True)
                        _log(msg)

        _decoder = _Verbose()
        _threads = [
            _th.Thread(target=_cap,
                       args=(_dumpcap, num, lbl, _decoder, "tcp", _stop, False, _procs),
                       daemon=True)
            for num, lbl in _ifaces
        ]
        print(f"[inject] starting {len(_threads)} capture threads", flush=True)
        for t in _threads:
            t.start()

        print("[inject] waiting up to 30s for upstream _id…", flush=True)
        got = _state["got_id"].wait(timeout=30.0)
        if not got or _state["max_id"] < 0:
            _stop.set()
            for p in _procs:
                try: p.kill()
                except: pass
            print("[inject] TIMEOUT: no upstream _id in 30s", flush=True)
            result["rc"] = 1
            return

        # The game fires a burst of RPCs when a button is clicked (e.g. Events
        # triggers activity.hero.get.info + rank.info + rank.reward in <0.5 s).
        # Wait for the burst to settle so we read the final max_id and don't
        # collide with a frame the client sends in the same burst.
        print("[inject] settling 1.5s for burst to finish…", flush=True)
        import time as _t
        _t.sleep(1.5)

        try:
            inject_id = _state["max_id"] + 1
            _state["inject_id"] = inject_id
            sid = _state["server_id"] or _Args.server_id
            k1 = _Args.k1
            k2 = _Args.k2
            msg = f"[inject] inject _id={inject_id} server_id={sid} k1={k1} k2={k2}"
            print(msg, flush=True); _log(msg)
            frame = steal.build_test_frame(sid, k1, k2, inject_id)
            print(f"[inject] frame hex: {frame.hex()}", flush=True)

            # Use the pre-captured dup handle from main() (captured before any
            # capture threads started, so VPN thread-affinity doesn't matter).
            import ctypes as _ct
            _ws2 = steal._win()["ws2"]
            print(f"[inject] dup handle value: {_game_dup.value!r}", flush=True)
            print(f"[inject] sending {len(frame)}B via pre-dup'd handle…", flush=True)
            _sent = _ws2.send(_ct.c_void_p(_game_dup.value), frame, len(frame), 0)
            _wsa_err = _ct.get_last_error()
            if _sent == len(frame):
                msg = f"[inject] sent {_sent} bytes to {_game_peer[0]}:{_game_peer[1]} (WSAerr={_wsa_err})"
                print(msg, flush=True); _log(msg)
                rc_send = 0
            else:
                msg = f"[inject] send() returned {_sent}/{len(frame)}, WSA error {_wsa_err}"
                print(msg, flush=True); _log(msg)
                rc_send = 1
            if rc_send != 0:
                _stop.set()
                for p in _procs:
                    try: p.kill()
                    except: pass
                result["rc"] = rc_send
                return

            # Wait up to 20s for reply, but extend to +8s after pcap confirms the
            # upstream frame (pcap delay on Сетевой мост can be 7-8 seconds).
            msg = f"[inject] waiting for server reply _id={inject_id} (deadline=60s, extend=+25s after confirm)…"
            print(msg, flush=True); _log(msg)
            deadline = _t.time() + 60.0
            while _t.time() < deadline:
                if _state["reply"]:
                    break
                seen_at = _state.get("inject_seen_at")
                if seen_at and _t.time() > seen_at + 25.0:
                    break  # 25s after pcap confirmed upstream, still no reply
                _t.sleep(0.05)

            _stop.set()
            for p in _procs:
                try: p.kill()
                except: pass

            if _state["reply"]:
                r = _state["reply"]
                ok = r.get("success") is True
                msg = (f"[inject] {'SUCCESS' if ok else 'REPLY(no success)'} "
                       f"server_reply _id={r['_id']} success={r['success']} cmd={r.get('cmd')}")
                print(msg, flush=True); _log(msg)
                result["rc"] = 0 if ok else 3  # 3 = reply received but success!=True
            else:
                msg = f"[inject] frame sent but no reply for _id={inject_id} (confirm={'YES' if _state.get('inject_seen_at') else 'NO'})"
                print(msg, flush=True); _log(msg)
                result["rc"] = 2  # sent but unconfirmed
        except Exception as exc:
            import traceback as _tb
            print(f"[inject] UNCAUGHT EXCEPTION: {exc}", flush=True)
            _tb.print_exc()
            _stop.set()
            for p in _procs:
                try: p.kill()
                except: pass
            result["rc"] = 1

    inject_thread = threading.Thread(target=_inject, daemon=True)
    inject_thread.start()

    # Wait for dumpcap processes to initialize, then click the game.
    print("[orch] waiting 3 s for capture to initialise…")
    time.sleep(3)

    click_game_buttons()

    # Wait for the inject thread to finish (up to 150 s total).
    inject_thread.join(timeout=150)
    rc = result.get("rc", 99)
    print(f"[orch] sniff_and_inject returned rc={rc}")

    # Outcome summary
    if rc == 0:
        print("\n[orch] SUCCESS  server_reply received with success=True")
        return 0
    if rc == 1:
        print("\n[orch] TIMEOUT or send failed — see output above")
        return 1
    print(f"\n[orch] rc={rc}  — see output above")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
