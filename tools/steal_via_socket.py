r"""Feasibility harness for stealing a running client's game socket.

The idea under test: instead of injecting a TCP frame from the outside (which
needs a kernel driver to forge the right seq/ack) or driving the UI, borrow the
game's *own* connected socket and write `hero.dispatch.steal` down it. The
kernel already owns the TCP control block, so anything we send inherits the
correct sequence numbers for free — no WinDivert, no raw sockets, no driver.

That is the appeal, and — measured on the PC client 2026-07-19 — the mechanic
actually works. This file runs the safe reconnaissance for real and gates every
step that touches the game behind an explicit flag, because the target is
Carono's main account on server #972 and the failure mode is a ban.

Read `docs/research/socket-duplication.md` for the write-up. What was measured
(each point overturned an earlier theoretical "no"):

  1. PROCESS_DUP_HANDLE is GRANTED on the game — ACE here does not strip it
     (both QUERY_LIMITED and DUP_HANDLE come back kept). Duplication is open.

  2. DuplicateHandle of the game's socket handles WORKS — 1406/1630 duplicated
     into our process. (The x64 argtypes in `_win()` are load-bearing: without
     them the GetCurrentProcess pseudo-handle truncates and every dup fails
     ERROR_INVALID_HANDLE.)

  3. ws2_32 accepts the duplicated handle — getpeername answers on 300-600 of
     them, so send() is usable. The old WSAENOTSOCK assumption was wrong; no raw
     AFD IOCTL is needed. WSADuplicateSocket stays cooperative-only and unused.

  4. What still blocks a real send is ENVIRONMENTAL, not ACE: a local VPN/proxy
     rewrites every socket's peer to a :443 tunnel endpoint, so the game's
     :17935 socket cannot be singled out by peer port, and getsockname (local
     port) blocks on this machine. Disable the tunnel for a clean go.to.world
     test.

  5. Send-only is safe. A duplicated socket shares ONE kernel receive buffer
     with the game; any recv() would steal bytes and desync it mid-frame. We
     only send. The server's reply still lands in the game's reader — fine for
     go.to.world (`{success, _id}`), and the reason steal waits until the
     mechanic is confirmed on the reversible command.

Test order: prove the transport on `go.to.world` (reversible, no cost) BEFORE
`steal` (irreversible, notifies the alliance). `--command` selects which; it
defaults to the safe one.

Usage (default is safe recon; nothing below --probe touches the game):

    python tools/steal_via_socket.py                 # recon + verdict
    python tools/steal_via_socket.py --sniff-id       # next _id off the wire (passive)
    python tools/steal_via_socket.py --build \
        --server-id 935 --k1 0x5a --k2 0x00 --id 181  # build go.to.world test frame
    python tools/steal_via_socket.py --command steal --build \
        --uuid 1394584906709054020 --target-server 946 \
        --server-id 935 --k1 0x5a --k2 0x00 --id 9159 # build the steal frame
    python tools/steal_via_socket.py --probe-access    # ACE access probe (touches game)
    python tools/steal_via_socket.py --find-handle      # needs PROCESS_DUP_HANDLE
    python tools/steal_via_socket.py --sniff-and-inject --force          # live-sniff _id → inject
    python tools/steal_via_socket.py --send --command go.to.world --force \
        --server-id 935 --k1 0x11 --k2 0x22 --id 181   # manual send (need --id)
    python tools/steal_via_socket.py --command steal --send \
        --force --i-understand-ban-risk ...             # send steal (gated harder)

Run it with the Windows Python, not WSL's — it uses Win32/NT APIs directly:

    /mnt/c/Python312/python.exe tools/steal_via_socket.py
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GAME_PORT = 17935
GAME_PROCESS = "lastwar.exe"

C_OK = "\033[92m"
C_WARN = "\033[93m"
C_ERR = "\033[91m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"


def _is_windows() -> bool:
    return sys.platform == "win32"


# --------------------------------------------------------------------------
# 1. Safe reconnaissance — process + socket, no handle to the game opened
# --------------------------------------------------------------------------


def find_game():
    """Return (pid, exe) for the running client, or (None, None).

    Pure query against the process table — the same information Task Manager
    shows. Nothing here opens a handle to the game.
    """
    try:
        import psutil
    except ImportError:
        print(f"{C_ERR}psutil not installed — pip install psutil{C_RESET}")
        return None, None
    for p in psutil.process_iter(["pid", "name", "exe"]):
        if (p.info["name"] or "").lower() == GAME_PROCESS:
            return p.info["pid"], p.info.get("exe")
    return None, None


def game_socket(pid: int):
    """Return the (laddr, raddr) tuple of the game's :17935 connection.

    Uses the TCP table (GetExtendedTcpTable under the hood, via psutil), which
    maps a connection to a pid without touching the owning process. It tells us
    the endpoints and that the socket exists — it does NOT give the in-process
    handle value; that is what step 2 is for, and why step 2 needs elevated
    access to the game.
    """
    import psutil

    for c in psutil.net_connections(kind="tcp"):
        if c.pid == pid and c.raddr and c.raddr.port == GAME_PORT:
            return c.laddr, c.raddr, c.status
    return None


def recon() -> int:
    pid, exe = find_game()
    if not pid:
        print(f"{C_ERR}Last War is not running.{C_RESET}")
        return 1
    print(f"{C_OK}game{C_RESET}   pid={pid}  {exe}")
    sock = game_socket(pid)
    if not sock:
        print(f"{C_WARN}no established :{GAME_PORT} socket — is the client on the world map?{C_RESET}")
        return 1
    laddr, raddr, status = sock
    print(f"{C_OK}socket{C_RESET} {laddr.ip}:{laddr.port} -> {raddr.ip}:{raddr.port}  [{status}]")
    print(f"{C_DIM}       this is the connection a duplicate would share.{C_RESET}")
    return 0


# --------------------------------------------------------------------------
# 2. Frame construction — safe, builds bytes only (mirrors lastwar_encode)
# --------------------------------------------------------------------------
#
# Two commands matter here, and the ORDER is the point:
#
#   go.to.world  — the transport test. Payload is `{}` (just the `_id`), the
#                  server answers `{success:true, _id:<same>}`, and the effect
#                  (client flips to the world map) is fully reversible via the
#                  base button / `user.leave.world`. Nothing is spent, no one is
#                  notified. Prove the duplicated socket can send AND that the
#                  server accepted it — by watching the reply come back with the
#                  `_id` *we* chose, which the client never would have sent — on
#                  this before ever building a steal.
#
#   steal        — the real target. Irreversible, notifies the owner's alliance,
#                  costs a daily attempt. Only after go.to.world round-trips
#                  cleanly does sending this make sense.


def build_command_frame(command: str, params: dict, server_id: int,
                        k1: int, k2: int, req_id: int) -> bytes:
    """Build any client RPC frame, with `_id` folded into the params.

    `_id` is the per-connection monotonic counter — it must be the NEXT value
    the client would use, or the server rejects the frame as a replay/out of
    order. There is no way to read that counter from outside the process, so a
    real send has to snoop the last upstream frame's `_id` off the wire and add
    one (see `sniff_live_params`). `k1`/`k2` are free per-frame key bytes;
    `server_id` is the home server in the header (935 here).
    """
    from lastwar_encode import build_request

    body = dict(params)
    body["_id"] = req_id
    return build_request(command, body, server_id=server_id,
                         k1=k1, k2=k2, request_id=-1)


def build_test_frame(server_id: int, k1: int, k2: int, req_id: int) -> bytes:
    """The safe transport probe: `go.to.world {_id}` (empty payload)."""
    return build_command_frame("go.to.world", {}, server_id, k1, k2, req_id)


def build_steal_frame(uuid: int, target_server: int, server_id: int,
                      k1: int, k2: int, req_id: int) -> bytes:
    """The real thing: `hero.dispatch.steal {targetServer, uuid, _id}`.

    Exactly the exchange trapped live on 2026-07-19 (protocol.md §7).
    """
    params = {"targetServer": target_server, "uuid": uuid}
    return build_command_frame("hero.dispatch.steal", params, server_id,
                               k1, k2, req_id)


def _frame_for(args) -> bytes | None:
    """Build whichever command the CLI selected, or None if args are missing."""
    common = ("server_id", "k1", "k2", "id")
    if args.command == "steal":
        need = ("uuid", "target_server") + common
        if any(getattr(args, n) is None for n in need):
            print(f"{C_ERR}steal needs --uuid --target-server --server-id --k1 --k2 --id{C_RESET}")
            return None
        return build_steal_frame(args.uuid, args.target_server, args.server_id,
                                 args.k1, args.k2, args.id)
    # default: the go.to.world transport test
    if any(getattr(args, n) is None for n in common):
        print(f"{C_ERR}go.to.world needs --server-id --k1 --k2 --id{C_RESET}")
        return None
    return build_test_frame(args.server_id, args.k1, args.k2, args.id)


def cmd_build(args) -> int:
    frame = _frame_for(args)
    if frame is None:
        return 2
    print(f"{C_OK}{args.command} frame{C_RESET} {len(frame)} bytes")
    print(frame.hex(" "))
    print(f"{C_DIM}bytes only — nothing was sent.{C_RESET}")
    return 0


# --------------------------------------------------------------------------
# 2b. Live parameter snoop — the NEXT _id, read passively off the wire
# --------------------------------------------------------------------------


def _wireshark_binary(name: str, find_binary) -> str | None:
    """Locate a Wireshark binary under Windows *or* WSL paths.

    `find_binary` (from live_tshark) only knows the /mnt/c form; add the native
    C:\\ form so the same code works whichever Python is running it.
    """
    import os

    native = (r"C:\Program Files\Wireshark",
              r"C:\Program Files (x86)\Wireshark")
    for directory in native:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return find_binary(name, None)


def sniff_live_params(seconds: float = 15.0):
    """Watch upstream frames and return (next_id, server_id) or None.

    Passive — it drives the same dumpcap capture the rest of the toolkit uses,
    reads the client's own frames, and takes the highest `_id` seen. `next_id`
    is that + 1: the value a real send must carry so the server does not reject
    it as out of order. This is ACE-safe (capture only), unlike everything in
    sections 3-4.

    Needs upstream traffic to exist in the window — keepalives and map scrolls
    both carry an `_id`, so nudging the client during the sniff helps.
    """
    tools = Path(__file__).resolve().parent
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import threading
        import lastwar_proto as proto
        from live_sniffer import LiveDecoder
        from live_tshark import capture, find_binary, list_interfaces
    except ImportError as exc:
        print(f"{C_ERR}live snoop needs the capture stack: {exc}{C_RESET}")
        return None

    # live_tshark's default search paths are WSL-style (/mnt/c/...). This tool
    # runs under the *Windows* Python (for the Win32 handle APIs), where those
    # do not resolve — so look under native Program Files too.
    tshark = _wireshark_binary("tshark.exe", find_binary)
    dumpcap = _wireshark_binary("dumpcap.exe", find_binary) or tshark
    if not (tshark and dumpcap):
        print(f"{C_ERR}tshark/dumpcap not found — cannot snoop.{C_RESET}")
        return None
    ifaces = list_interfaces(tshark)
    if not ifaces:
        print(f"{C_ERR}no capture interfaces.{C_RESET}")
        return None

    state = {"max_id": -1, "server_id": None}

    class _Collector(LiveDecoder):
        def emit(self, direction, env):
            if direction != "up":
                return
            payload = proto.envelope_payload(env) or {}
            rid = payload.get("_id")
            if isinstance(rid, int) and rid > state["max_id"]:
                state["max_id"] = rid
            sid = payload.get("serverId")
            if isinstance(sid, int):
                state["server_id"] = sid

    decoder = _Collector()
    stop = threading.Event()
    procs: list = []
    threads = [
        threading.Thread(target=capture,
                         args=(dumpcap, num, lbl, decoder, "tcp", stop, False, procs),
                         daemon=True)
        for num, lbl in ifaces
    ]
    print(f"{C_DIM}sniffing upstream _id for {seconds:g}s (passive)…{C_RESET}")
    for t in threads:
        t.start()
    stop.wait(seconds)
    stop.set()
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    if state["max_id"] < 0:
        print(f"{C_WARN}no upstream _id seen — nudge the client and retry.{C_RESET}")
        return None
    nxt = state["max_id"] + 1
    sid = state["server_id"]
    extra = f"  server_id = {sid}" if sid else ""
    print(f"{C_OK}next _id = {nxt}{C_RESET}{extra}")
    return nxt, sid


# --------------------------------------------------------------------------
# 3. ACE access probe — opens a handle to the game (gated, touches the target)
# --------------------------------------------------------------------------

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_SAME_ACCESS = 0x2

_ACCESS_NAMES = {
    PROCESS_QUERY_LIMITED_INFORMATION: "QUERY_LIMITED_INFORMATION",
    PROCESS_DUP_HANDLE: "DUP_HANDLE",
}

_WIN = {}


def _win():
    """kernel32/ws2_32 with EXPLICIT x64 signatures, configured once.

    This is not cosmetic. Without argtypes/restype, ctypes marshals HANDLE
    arguments as 32-bit `int`, so the `(HANDLE)-1` pseudo-handle from
    GetCurrentProcess truncates and every DuplicateHandle fails with
    ERROR_INVALID_HANDLE (6). With the signatures below, DuplicateHandle
    succeeds — the whole duplication path hinges on this.
    """
    if _WIN:
        return _WIN
    H = wintypes.HANDLE
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ws2 = ctypes.WinDLL("ws2_32", use_last_error=True)
    k32.OpenProcess.restype = H
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetCurrentProcess.restype = H
    k32.DuplicateHandle.restype = wintypes.BOOL
    k32.DuplicateHandle.argtypes = [H, H, H, ctypes.POINTER(H),
                                    wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [H]
    ws2.getpeername.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    ws2.getsockname.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    ws2.getsockname.restype = ctypes.c_int
    ws2.send.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    ws2.send.restype = ctypes.c_int
    ws2.WSAStartup(0x0202, ctypes.create_string_buffer(512))
    _WIN.update(k32=k32, ws2=ws2)
    return _WIN


def _granted_access(handle: int) -> int | None:
    """Read the access mask actually granted on `handle` via NtQueryObject.

    OpenProcess can *succeed* yet return a handle whose rights ACE has stripped.
    The requested mask is a lie; the granted mask in ObjectBasicInformation is
    the truth, and the gap between them is the whole answer to "does ACE strip
    DUP_HANDLE?".
    """
    ntdll = ctypes.WinDLL("ntdll")

    class PUBLIC_OBJECT_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Attributes", wintypes.ULONG),
            ("GrantedAccess", wintypes.DWORD),
            ("HandleCount", wintypes.ULONG),
            ("PointerCount", wintypes.ULONG),
            ("Reserved", wintypes.ULONG * 10),
        ]

    info = PUBLIC_OBJECT_BASIC_INFORMATION()
    status = ntdll.NtQueryObject(wintypes.HANDLE(handle), 0,
                                 ctypes.byref(info), ctypes.sizeof(info), None) & 0xFFFFFFFF
    if status != 0:
        return None
    return info.GrantedAccess


def probe_access(pid: int) -> int:
    """Open the game with escalating rights and report what ACE actually grants.

    This DOES open a handle to the protected process. It is the single
    ACE-relevant action here, and it is the cheapest way to answer question (3)
    empirically rather than from theory — but it is still active work against
    #972, so it lives behind --probe-access and prints a warning first.
    """
    if not _is_windows():
        print(f"{C_ERR}--probe-access needs the Windows Python.{C_RESET}")
        return 2
    print(f"{C_WARN}probe: opening a handle to the ACE-protected game process. "
          f"This is active work; on #972 it may be logged/flagged.{C_RESET}")
    k32 = _win()["k32"]
    for want in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_DUP_HANDLE):
        handle = k32.OpenProcess(want, False, pid)
        if not handle:
            err = ctypes.get_last_error()
            print(f"  request {_ACCESS_NAMES[want]:26} -> "
                  f"{C_ERR}OpenProcess failed (err {err}){C_RESET}")
            continue
        granted = _granted_access(handle)
        got = granted if granted is not None else 0
        ok = bool(got & want)
        colour = C_OK if ok else C_WARN
        print(f"  request {_ACCESS_NAMES[want]:26} -> granted 0x{got:08x}  "
              f"{colour}{'kept' if ok else 'STRIPPED'}{C_RESET}")
        k32.CloseHandle(handle)
    print(f"{C_DIM}Measured on the PC client 2026-07-19: BOTH kept — ACE here "
          f"does NOT strip DUP_HANDLE, so the duplication path is open.{C_RESET}")
    return 0


# --------------------------------------------------------------------------
# 4. Handle enumeration + duplication — needs PROCESS_DUP_HANDLE (gated)
# --------------------------------------------------------------------------

SystemExtendedHandleInformation = 0x40
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


def _enum_system_handles():
    """Yield (pid, handle_value, object_ptr) for every handle on the system.

    NtQuerySystemInformation(SystemExtendedHandleInformation) is a global read;
    it does not open the game. But it only gives handle *values* — turning one
    into "this is the game's socket" needs DuplicateHandle into our process and
    NtQueryObject(TypeName), and the DuplicateHandle is what needs the access
    ACE strips. So this enumeration is necessary but not sufficient on its own.
    """
    ntdll = ctypes.WinDLL("ntdll")

    class SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX(ctypes.Structure):
        _fields_ = [
            ("Object", ctypes.c_void_p),
            ("UniqueProcessId", ctypes.c_void_p),
            ("HandleValue", ctypes.c_void_p),
            ("GrantedAccess", wintypes.ULONG),
            ("CreatorBackTraceIndex", wintypes.USHORT),
            ("ObjectTypeIndex", wintypes.USHORT),
            ("HandleAttributes", wintypes.ULONG),
            ("Reserved", wintypes.ULONG),
        ]

    size = 0x10000
    while True:
        buf = ctypes.create_string_buffer(size)
        ret = wintypes.ULONG()
        # NTSTATUS comes back as a signed c_int; mask to compare with the
        # unsigned status constants (0xC0000004 would otherwise read negative
        # and the length-mismatch retry below would never fire).
        status = ntdll.NtQuerySystemInformation(
            SystemExtendedHandleInformation, buf, size, ctypes.byref(ret)) & 0xFFFFFFFF
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size = max(ret.value, size * 2) + 0x10000
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation failed: 0x{status:08x}")
        break

    count = ctypes.cast(buf, ctypes.POINTER(ctypes.c_size_t))[0]
    entries_off = ctypes.sizeof(ctypes.c_size_t) * 2  # NumberOfHandles + Reserved
    entry_t = SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX
    base = ctypes.addressof(buf) + entries_off
    for i in range(count):
        e = entry_t.from_address(base + i * ctypes.sizeof(entry_t))
        yield (e.UniqueProcessId or 0, e.HandleValue or 0, e.Object or 0,
               e.ObjectTypeIndex)


class _SockAddrIn(ctypes.Structure):
    _fields_ = [("family", ctypes.c_short), ("port", ctypes.c_ushort),
                ("addr", ctypes.c_ubyte * 4), ("zero", ctypes.c_byte * 8)]


def _peer(ws2, handle: int) -> tuple | None:
    """getpeername → (ip, port), or None if not a socket or if the call hangs.

    Non-socket handles return SOCKET_ERROR (WSAENOTSOCK) immediately. Socket
    handles in a VPN/proxy transient state can block indefinitely — the 200 ms
    deadline in the thread guard abandons those hangers rather than stalling the
    entire handle enumeration.
    """
    import socket
    import threading

    result: list = [None]
    done = threading.Event()

    def _call() -> None:
        sa = _SockAddrIn()
        ln = ctypes.c_int(ctypes.sizeof(sa))
        if ws2.getpeername(ctypes.c_void_p(handle), ctypes.byref(sa),
                           ctypes.byref(ln)) == 0:
            result[0] = (".".join(str(b) for b in sa.addr), socket.ntohs(sa.port))
        done.set()

    threading.Thread(target=_call, daemon=True).start()
    done.wait(0.2)
    return result[0]


def _local(ws2, handle: int) -> tuple | None:
    """getsockname -> (ip, port), or None if not a bound socket.

    Wrapped in a 50 ms daemon thread: some duplicated handles that pass the
    ObjectTypeIndex filter are not true TCP sockets and block indefinitely in
    getsockname.  The timeout makes the scan safe even for those edge cases.
    """
    import socket as _socket
    import threading as _threading

    result: list = [None]
    done = _threading.Event()

    def _call() -> None:
        sa = _SockAddrIn()
        ln = ctypes.c_int(ctypes.sizeof(sa))
        if ws2.getsockname(ctypes.c_void_p(handle),
                           ctypes.byref(sa), ctypes.byref(ln)) == 0:
            port = _socket.ntohs(sa.port)
            if port:
                result[0] = (".".join(str(b) for b in sa.addr), port)
        done.set()

    _threading.Thread(target=_call, daemon=True).start()
    done.wait(0.050)
    return result[0]


def _collect_socket_candidates(pid: int) -> tuple[list, int | None]:
    """Return (candidates, sock_tidx) from a single _enum_system_handles() call.

    candidates  — list of hval integers for game handles whose ObjectTypeIndex
                  matches the socket type index (or ALL game handles if the
                  socket type index can't be determined).
    sock_tidx   — the detected socket ObjectTypeIndex, or None.

    This is Phase 1 of the two-phase pre-dup: enumerate ONLY (no OpenProcess,
    no DuplicateHandle).  The enumeration itself is ACE-safe.  Phase 2
    (DuplicateHandle on the short candidate list) is called later, after scapy
    threads have been running, so that ACE does not see the suspicious
    "NtQuerySystemInformation → OpenProcess(game)" sequence with no delay.
    """
    import socket as _socket
    import os as _os
    my_pid = _os.getpid()
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    test_val = s.fileno()
    sock_tidx: int | None = None
    game_handles: list = []
    for hpid, hval, _obj, tidx in _enum_system_handles():
        if hpid == my_pid and hval == test_val:
            sock_tidx = tidx
        elif hpid == pid:
            game_handles.append((hval, tidx))
    s.close()
    candidates = [hv for hv, tidx in game_handles
                  if sock_tidx is None or tidx == sock_tidx]
    return candidates, sock_tidx


def dup_game_socket_by_lport(pid: int, local_port: int,
                             candidates: list | None = None,
                             handle_timeout: float = 0.005) -> tuple:
    """Phase 2: DuplicateHandle + getsockname on a pre-collected candidate list.

    Call _collect_socket_candidates(pid) first (Phase 1, no OpenProcess) and
    store the result.  Then call dup_game_socket_by_lport() LATER — after scapy
    threads have been running for a while — so ACE does not see the suspicious
    "NtQuerySystemInformation → OpenProcess(game)" sequence without delay.

    If candidates is None, a fresh _collect_socket_candidates(pid) scan is run.

    Returns (orig_handle_value, dup_handle: wintypes.HANDLE) or raises OSError.
    NOTE: hgame is not closed; background DuplicateHandle threads may reference
    it.  It leaks cleanly when the inject process exits.
    """
    import threading as _th

    win = _win()
    k32, ws2 = win["k32"], win["ws2"]

    if candidates is None:
        candidates, _ = _collect_socket_candidates(pid)

    hgame = k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not hgame:
        raise OSError(f"OpenProcess(PROCESS_DUP_HANDLE) failed: "
                      f"{ctypes.get_last_error()}")
    hself = k32.GetCurrentProcess()
    found = None

    for hval in candidates:
        _dup_result: list = [None]
        _dup_done = _th.Event()

        def _dup_call(_hg=hgame, _hv=hval, _hs=hself,
                      _r=_dup_result, _e=_dup_done):
            _d = wintypes.HANDLE()
            if k32.DuplicateHandle(_hg, wintypes.HANDLE(_hv), _hs,
                                   ctypes.byref(_d), 0, False,
                                   DUPLICATE_SAME_ACCESS):
                _r[0] = _d
            _e.set()

        _th.Thread(target=_dup_call, daemon=True).start()
        _dup_done.wait(handle_timeout)  # fast DuplicateHandle returns in < 1 ms

        dup = _dup_result[0]
        if dup is None:
            continue   # timed out or failed; skip this handle

        laddr = _local(ws2, dup.value)
        if laddr and laddr[1] == local_port:
            found = (hval, dup)
            break
        k32.CloseHandle(dup)

    if found is None:
        raise OSError(f"game socket with local port :{local_port} not found "
                      f"(scanned {len(candidates)} socket-type handles)")
    return found


def dup_game_socket_blind_scan(pid: int, local_port: int,
                               max_hval: int = 0x4000) -> tuple:
    """Find the game socket by brute-forcing handle values (no NtQuerySystemInformation).

    Avoids the ACE-triggered DuplicateHandle block that follows a
    NtQuerySystemInformation call — empirically, without that call DuplicateHandle
    on the game socket succeeds quickly (task #961 confirmed: 61 bytes sent).

    Tries every multiple of 4 from 0x4 to max_hval.  Most fail immediately
    (DuplicateHandle returns 0 for non-existent handles).  Matching is done via
    getsockname on successful dups.

    Returns (orig_handle_value, dup_handle: wintypes.HANDLE) or raises OSError.
    """
    win = _win()
    k32, ws2 = win["k32"], win["ws2"]
    hgame = k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not hgame:
        raise OSError(f"OpenProcess(PROCESS_DUP_HANDLE) failed: "
                      f"{ctypes.get_last_error()}")
    hself = k32.GetCurrentProcess()
    found = None
    tried = 0
    for hval in range(4, max_hval + 1, 4):
        _d = wintypes.HANDLE()
        if not k32.DuplicateHandle(hgame, wintypes.HANDLE(hval), hself,
                                   ctypes.byref(_d), 0, False, DUPLICATE_SAME_ACCESS):
            continue
        tried += 1
        laddr = _local(ws2, _d.value)
        if laddr and laddr[1] == local_port:
            found = (hval, _d)
            break
        k32.CloseHandle(_d)
    # NOTE: hgame intentionally not closed — it leaks cleanly on process exit.
    if found is None:
        raise OSError(f"game socket :{local_port} not found "
                      f"(tried {tried} successful dups up to hval=0x{max_hval:x})")
    return found


def dup_game_sockets(pid: int, match_port: int | None = None):
    """Duplicate the game's connected sockets into our process.

    Returns [(orig_handle_value, dup_handle, (ip, port))]. The caller owns the
    dup handles and must CloseHandle them. If `match_port` is given, only
    sockets whose peer port equals it are kept (e.g. 17935 for the game
    connection when no VPN/proxy is rewriting the endpoint).

    Note (measured 2026-07-19): with a local VPN/proxy in the path, every
    socket's peer reads as the tunnel endpoint (198.19.x / 101.32.x : 443), so
    the game's :17935 does not surface here. Matching then needs getsockname's
    local port — which blocks on this machine — or the tunnel disabled.
    """
    win = _win()
    k32, ws2 = win["k32"], win["ws2"]
    hgame = k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not hgame:
        raise OSError(f"OpenProcess(PROCESS_DUP_HANDLE) failed: {ctypes.get_last_error()}")
    granted = _granted_access(hgame) or 0
    if not granted & PROCESS_DUP_HANDLE:
        k32.CloseHandle(hgame)
        raise OSError(f"DUP_HANDLE stripped (granted 0x{granted:08x})")

    hself = k32.GetCurrentProcess()
    out = []
    for hpid, hval, _obj, _type_idx in _enum_system_handles():
        if hpid != pid:
            continue
        dup = wintypes.HANDLE()
        if not k32.DuplicateHandle(hgame, wintypes.HANDLE(hval), hself,
                                   ctypes.byref(dup), 0, False, DUPLICATE_SAME_ACCESS):
            continue
        peer = _peer(ws2, dup.value)
        if peer and (match_port is None or peer[1] == match_port):
            out.append((hval, dup, peer))
        else:
            k32.CloseHandle(dup)
    k32.CloseHandle(hgame)
    return out


def find_handle(pid: int) -> int:
    """Duplicate the game's sockets and report their endpoints.

    Empirically (2026-07-19) this works: DUP_HANDLE is granted, DuplicateHandle
    succeeds, and ws2_32.getpeername answers on the duplicates — proving the
    duplicated handles are usable through Winsock. What it cannot do on this
    machine is single out the :17935 game socket, because a VPN/proxy rewrites
    every peer to a :443 tunnel endpoint.
    """
    if not _is_windows():
        print(f"{C_ERR}--find-handle needs the Windows Python.{C_RESET}")
        return 2
    print(f"{C_WARN}duplicating the game's handles (PROCESS_DUP_HANDLE) — active "
          f"work against an ACE-protected process.{C_RESET}")
    try:
        socks = dup_game_sockets(pid)
    except OSError as exc:
        print(f"{C_ERR}{exc}{C_RESET}")
        return 1
    from collections import Counter
    eps = Counter(f"{ip}:{port}" for _, _, (ip, port) in socks)
    game = [(h, d, p) for (h, d, p) in socks if p[1] == GAME_PORT]
    for _h, d, _p in socks:
        _win()["k32"].CloseHandle(d)
    print(f"{C_OK}{len(socks)} duplicated socket(s){C_RESET}; peer endpoints: {dict(eps)}")
    if game:
        print(f"{C_OK}game socket handle(s) at :{GAME_PORT}: "
              f"{[hex(h) for h, _, _ in game]}{C_RESET}")
        return 0
    print(f"{C_WARN}no socket shows peer :{GAME_PORT} — a VPN/proxy is rewriting "
          f"endpoints. Disable it (or add getsockname local-port matching) to "
          f"pin the game socket. The duplication mechanic itself works.{C_RESET}")
    return 1


def _object_type_name(ntdll, handle: int) -> str | None:
    ObjectTypeInformation = 2
    size = 0x1000
    buf = ctypes.create_string_buffer(size)
    ret = wintypes.ULONG()
    status = ntdll.NtQueryObject(wintypes.HANDLE(handle), ObjectTypeInformation,
                                 buf, size, ctypes.byref(ret)) & 0xFFFFFFFF
    if status != 0:
        return None
    # PUBLIC_OBJECT_TYPE_INFORMATION starts with a UNICODE_STRING
    # {USHORT Length; USHORT MaximumLength; PWSTR Buffer;}. Length is in bytes;
    # the wide buffer follows the pointer-aligned struct head.
    length = ctypes.cast(buf, ctypes.POINTER(wintypes.USHORT))[0]
    head = 2 * ctypes.sizeof(ctypes.c_void_p)
    try:
        return ctypes.wstring_at(ctypes.addressof(buf) + head, length // 2)
    except Exception:
        return None


# --------------------------------------------------------------------------
# 5. Send — write a frame down a duplicated game socket (gated)
# --------------------------------------------------------------------------


def send_via_dup(pid: int, frame: bytes) -> int:
    """Duplicate the game's :17935 socket and send `frame` down it.

    Uses the reliable dup-all-then-filter path (same as --find-handle): duplicate
    every game handle, then select those whose peer port is GAME_PORT. The earlier
    match_port= variant was flaky because it applied the port filter inside the
    enumeration loop, where a transient getpeername hang stalled the whole scan.
    Now _peer() has a 200 ms per-call timeout, and the filter runs after the full
    enumeration completes.

    Send-only: never recv()s, so it cannot steal bytes the game is waiting on.
    """
    win = _win()
    k32, ws2 = win["k32"], win["ws2"]
    try:
        socks = dup_game_sockets(pid)           # dup all, filter by port after
    except OSError as exc:
        print(f"{C_ERR}{exc}{C_RESET}")
        return 1
    game = [(h, d, p) for (h, d, p) in socks if p[1] == GAME_PORT]
    for _h, d, p in socks:
        if p[1] != GAME_PORT:
            k32.CloseHandle(d)
    if not game:
        print(f"{C_ERR}could not pin the :{GAME_PORT} game socket "
              f"(VPN/proxy rewrites peers — disable the tunnel).{C_RESET}")
        return 1
    _hval, dup, peer = game[0]
    for _h, d, _p in game[1:]:
        k32.CloseHandle(d)
    sent = ws2.send(ctypes.c_void_p(dup.value), frame, len(frame), 0)
    k32.CloseHandle(dup)
    if sent == len(frame):
        print(f"{C_OK}sent {sent} bytes to {peer[0]}:{peer[1]} via the "
              f"duplicated socket.{C_RESET}")
        print(f"{C_DIM}watch for the server reply carrying your _id "
              f"(tools/live_tshark.py) to confirm it landed.{C_RESET}")
        return 0
    print(f"{C_ERR}send returned {sent} (WSA err {ctypes.get_last_error()}).{C_RESET}")
    return 1


# --------------------------------------------------------------------------
# 5b. Live-sniff + inject — the _id race solver
# --------------------------------------------------------------------------
#
# Problem: the client's per-connection _id counter advances with every RPC.
# An idle client emits no upstream frames, so any pre-sniffed _id goes stale
# before we can use it (the client may have sent a few RPCs in the gap). A
# guessed or stale _id is silently dropped by the server.
#
# Solution: keep the capture running, block until the client emits ANY upstream
# frame carrying _id (a map scroll, a button tap, a heartbeat), then
# immediately use max(seen_ids)+1 as the injection counter. The window between
# sniff and send is a few milliseconds — far shorter than any human interaction
# interval — so the counter cannot have advanced in the gap.


def sniff_and_inject(pid: int, args) -> int:
    """Passive-sniff the live _id counter, then inject go.to.world immediately.

    Flow:
      1. Start passive pcap on all interfaces (upstream + downstream).
      2. Block until the game emits any upstream frame carrying _id.
         (Nudge: open a menu, scroll the map — anything that triggers an RPC.)
      3. Take max(seen_ids) + 1 as the injection _id. The send follows in the
         same millisecond, so the counter cannot have advanced in the gap.
      4. Build go.to.world{_id=N+1} and send it via the duplicated socket.
      5. Watch downstream for a reply with _id=N+1 and success=true.

    Logs: got _id=N → injecting _id=N+1 → server_reply or timeout.
    """
    import threading
    import time

    tools = Path(__file__).resolve().parent
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import lastwar_proto as proto
        from live_sniffer import LiveDecoder
        from scapy.arch import get_if_list
    except ImportError as exc:
        print(f"{C_ERR}sniff-and-inject needs the capture stack "
              f"(scapy): {exc}{C_RESET}")
        return 1

    # Get the local port of the game's TCP connection (no NtQuerySystemInformation).
    # Calling NtQuerySystemInformation before DuplicateHandle triggers an ACE
    # timing block that makes DuplicateHandle hang for > 75 s.  Without it,
    # DuplicateHandle succeeds quickly (confirmed: task #961, 61 bytes sent).
    import psutil as _psutil
    _local_port: int | None = None
    for _conn in _psutil.net_connections(kind="tcp"):
        if (_conn.raddr and _conn.raddr.port == GAME_PORT
                and _conn.status == "ESTABLISHED"):
            _local_port = _conn.laddr.port
            break
    if _local_port:
        print(f"{C_DIM}game local port: :{_local_port}{C_RESET}", flush=True)
    else:
        print(f"{C_WARN}no :{GAME_PORT} ESTABLISHED found via psutil{C_RESET}")

    pre_dup_handle: wintypes.HANDLE | None = None
    _blind_event = threading.Event()
    _blind_result: list = [None]   # set to (hval, HANDLE) or OSError

    # Transport is scapy-over-npcap, exactly as map_capture.py / scan_players.py:
    # dumpcap on the "Сетевой мост" adapter never surfaced upstream _id frames,
    # while the scapy path (with the Ether re-parse below) does. No dumpcap.exe
    # and no tshark.exe are spawned.
    ifaces = get_if_list()
    if not ifaces:
        print(f"{C_ERR}scapy sees no capture interfaces.{C_RESET}")
        return 1

    state: dict = {
        "max_id": -1,
        "server_id": None,
        "inject_id": None,   # set just before send; downstream watcher checks this
        "reply": None,
        "got_id": threading.Event(),
    }

    class _Collector(LiveDecoder):
        def emit(self, direction, env):
            try:
                payload = proto.envelope_payload(env) or {}
            except Exception:
                return
            if not isinstance(payload, dict):
                return
            if direction == "up":
                rid = payload.get("_id")
                if isinstance(rid, int) and rid > state["max_id"]:
                    state["max_id"] = rid
                    sid = payload.get("serverId")
                    if isinstance(sid, int):
                        state["server_id"] = sid
                    state["got_id"].set()
            elif direction == "down":
                inj = state["inject_id"]
                if inj is None:
                    return
                rid = payload.get("_id")
                ok = payload.get("success")
                cmd = proto.envelope_command(env)
                # Log ALL downstream frames in the reply window for diagnosis.
                print(f"{C_DIM}down  cmd={cmd}  _id={rid}  success={ok}{C_RESET}",
                      flush=True)
                # Accept any downstream frame whose _id matches inject_id —
                # go.to.world elicits world.get.block (map data) rather than
                # a bare {success:true} ack, so success is None but _id matches.
                if rid == inj and not state["reply"]:
                    state["reply"] = {"_id": rid, "success": ok, "cmd": cmd}

    decoder = _Collector()
    stop = threading.Event()
    procs: list = []   # kept empty: the scapy path spawns no child processes,
                       # so the `for p in procs` cleanups below are no-ops.

    # npcap reports linktype 1 on these adapters but scapy fails to map it, so
    # it hands back an unparsed Packet with no IP/TCP layer that the decoder
    # then discards. Re-parsing the raw bytes as Ether ourselves sidesteps the
    # guess — this is the same fix map_capture.feed_packet uses.
    from scapy.layers.inet import IP
    from scapy.layers.l2 import Ether
    from scapy.sendrecv import sniff

    def _feed(pkt):
        if not pkt.haslayer(IP):
            try:
                pkt = Ether(bytes(pkt))
            except Exception:
                return
        decoder.handle(pkt, None)

    def _sniff_forever(iface):
        try:
            sniff(filter=f"tcp port {GAME_PORT}", iface=iface, prn=_feed,
                  store=False, stop_filter=lambda _p: stop.is_set())
        except Exception as exc:  # one dead interface must not end the run
            if not stop.is_set():
                print(f"{C_DIM}iface {iface}: {exc}{C_RESET}")

    threads = [
        threading.Thread(target=_sniff_forever, args=(iface,), daemon=True)
        for iface in ifaces
    ]

    print(f"{C_DIM}sniffing upstream _id via scapy/npcap "
          f"(open a menu or scroll the map)…{C_RESET}")
    for t in threads:
        t.start()

    # Phase 2: DuplicateHandle on socket-type candidates with 50 ms per-handle
    # timeout.  The ACE-protected handle (#301 in enumeration order) blocks
    # DuplicateHandle indefinitely; with 50 ms we waste at most 50 ms on it and
    # continue to the actual game socket.  The scan runs in background so it
    # overlaps with the _id wait (scapy sniff).
    #
    # Separately, dup_game_sockets (getpeername) is tried first — it finds the
    # socket instantly when the server IP is directly visible (no VPN masking).
    if _local_port is not None:
        # Phase 1 candidate collection — NtQuerySystemInformation only (no OpenProcess).
        try:
            _p2_candidates, _p2_tidx = _collect_socket_candidates(pid)
            print(f"{C_DIM}phase-1: {len(_p2_candidates)} socket candidates "
                  f"(tidx={_p2_tidx}){C_RESET}", flush=True)
        except Exception as _exc:
            _p2_candidates = None
            print(f"{C_WARN}phase-1 failed: {_exc}{C_RESET}", flush=True)

        def _run_bg_dup(_pid=pid, _port=_local_port,
                        _cands=_p2_candidates, _r=_blind_result, _e=_blind_event):
            # Long timeout per handle (130 s) so we wait out the ACE block on the
            # game socket.  ACE lifts the block after ~60–120 s; then DuplicateHandle
            # returns and getsockname confirms the local port.  The continuous panning
            # loop in the orchestrator keeps max_id fresh during this wait, so inject_id
            # will not be stale when we finally send.
            if _cands is None:
                _r[0] = OSError("no candidates (phase-1 failed)")
                _e.set()
                return
            try:
                result = dup_game_socket_by_lport(_pid, _port, _cands,
                                                  handle_timeout=130.0)
                _r[0] = result
                print(f"{C_OK}bg-dup: found :{_port} socket "
                      f"(hval=0x{result[0]:x}){C_RESET}", flush=True)
            except OSError as exc:
                _r[0] = exc
                print(f"{C_WARN}bg-dup: {exc}{C_RESET}", flush=True)
            finally:
                _e.set()

        threading.Thread(target=_run_bg_dup, daemon=True).start()
        print(f"{C_DIM}bg-dup running in background (parallel with _id sniff)…{C_RESET}",
              flush=True)

    got = state["got_id"].wait(timeout=30.0)
    if not got or state["max_id"] < 0:
        stop.set()
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        if pre_dup_handle is not None:
            _win()["k32"].CloseHandle(pre_dup_handle)
        print(f"{C_WARN}no upstream _id seen within 30 s — nudge the client.{C_RESET}")
        return 1

    # Settle: wait for the RPC burst (triggered by a button click) to finish
    # so we capture the true final max_id and don't inject mid-burst.
    time.sleep(1.5)

    sid = state["server_id"] or getattr(args, "server_id", None)
    k1 = getattr(args, "k1", None) if getattr(args, "k1", None) is not None else 0x11
    k2 = getattr(args, "k2", None) if getattr(args, "k2", None) is not None else 0x22

    if sid is None:
        stop.set()
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        if pre_dup_handle is not None:
            _win()["k32"].CloseHandle(pre_dup_handle)
        print(f"{C_ERR}server_id not seen on wire — pass --server-id.{C_RESET}")
        return 1

    # Wait up to 135 s for bg-dup.  With handle_timeout=130 s the worst case is
    # one blocking handle (the game socket, protected by ACE for ~120 s) plus a
    # handful of fast handles.  The orchestrator pans every 12 s, so max_id stays
    # fresh throughout this wait.
    if _local_port is not None and not _blind_event.is_set():
        print(f"{C_DIM}waiting for bg-dup (up to 135 s — ACE block expires ~120 s)…{C_RESET}",
              flush=True)
        _blind_event.wait(timeout=135.0)
    if isinstance(_blind_result[0], tuple):
        _hv, _hd = _blind_result[0]
        pre_dup_handle = _hd
        print(f"{C_DIM}bg-dup handle ready (hval=0x{_hv:x}){C_RESET}", flush=True)

    if pre_dup_handle is None:
        stop.set()
        print(f"{C_ERR}bg-dup could not find the game socket — "
              f"the blocking handle may be the game socket itself.{C_RESET}")
        print(f"{C_DIM}Try again; each run creates a fresh OpenProcess handle "
              f"which may bypass the ACE block.{C_RESET}")
        return 1

    # Fast path: the socket is dup'd; capture the freshest _id at the very
    # moment of send.  The window between capture and ws2.send() is ~1 µs —
    # the game cannot race us in that time.
    win = _win()
    k32, ws2 = win["k32"], win["ws2"]
    # Brief settle so the latest orchestrator-pan RPC burst lands in scapy.
    time.sleep(0.5)
    inject_id = state["max_id"] + 1
    frame = build_test_frame(sid, k1, k2, inject_id)
    state["inject_id"] = inject_id   # arm BEFORE send — reply may arrive fast
    print(f"{C_OK}injecting _id={inject_id}  server_id={sid}{C_RESET}", flush=True)
    sent = ws2.send(ctypes.c_void_p(pre_dup_handle.value), frame, len(frame), 0)
    k32.CloseHandle(pre_dup_handle)
    pre_dup_handle = None
    if sent == len(frame):
        print(f"{C_OK}sent {sent} bytes via dup'd socket (local:{_local_port}){C_RESET}")
        rc = 0
    else:
        err = ctypes.get_last_error()
        print(f"{C_ERR}send returned {sent} (WSA err {err}){C_RESET}")
        rc = 1

    if rc != 0:
        stop.set()
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        return rc

    # state["inject_id"] was already set (BEFORE send) in both paths above.
    # Wait for downstream ACK carrying our _id.
    # go.to.world elicits world.get.block (map data), not {success:true}.
    print(f"{C_DIM}waiting up to 30 s for server reply _id={inject_id}…{C_RESET}")
    deadline = time.time() + 30.0
    while time.time() < deadline:
        if state["reply"]:
            break
        time.sleep(0.05)

    stop.set()
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass

    if state["reply"]:
        r = state["reply"]
        print(f"{C_OK}server_reply  _id={r['_id']}  success={r['success']}  "
              f"cmd={r['cmd']}{C_RESET}")
        return 0

    print(f"{C_WARN}timeout — no downstream reply for _id={inject_id}.{C_RESET}")
    print(f"{C_DIM}The server ACK lands in the game's TCP buffer — it is visible "
          f"in pcap even if this watcher missed it.{C_RESET}")
    return 1


# --------------------------------------------------------------------------
# 6. The verdict — reflects what was MEASURED on the PC client, not theory
# --------------------------------------------------------------------------


def verdict() -> None:
    print(f"\n{C_WARN}== feasibility (measured 2026-07-19, PC client) =={C_RESET}")
    ok = [
        ("PROCESS_DUP_HANDLE on the game",
         "GRANTED — ACE here does not strip it (both QUERY and DUP kept)."),
        ("DuplicateHandle of the game's socket handles",
         "WORKS — 1406/1630 handles duplicated into our process."),
        ("ws2_32 on the duplicated handle",
         "WORKS — getpeername answers, so send() is usable (the earlier "
         "WSAENOTSOCK assumption was wrong)."),
        ("WSADuplicateSocket",
         "still cooperative-only and unused — the manual DuplicateHandle path "
         "above replaces it."),
    ]
    blocked = [
        ("pinning the :17935 game socket",
         "a local VPN/proxy rewrites every peer to a :443 tunnel endpoint, so "
         "the game socket does not surface by peer port; getsockname (local "
         "port) blocks on this machine. Disable the tunnel for a clean test."),
        ("shared receive buffer",
         "send-only is safe; any recv() would desync the game mid-frame, and "
         "the unsolicited reply still lands in the client's reader."),
    ]
    for head, body in ok:
        print(f"  {C_OK}+{C_RESET} {head}: {body}")
    for head, body in blocked:
        print(f"  {C_WARN}~{C_RESET} {head}: {body}")
    print(f"\n{C_WARN}Bottom line:{C_RESET} the duplication mechanic is proven on "
          f"the official PC client. The remaining blocker is environmental (the "
          f"VPN/proxy), not ACE. Test the actual go.to.world send with the "
          f"tunnel off; keep steal for later.")


# --------------------------------------------------------------------------


def _int_auto(s: str) -> int:
    return int(s, 0)


def main() -> int:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--command", choices=["go.to.world", "steal"],
                    default="go.to.world",
                    help="which frame to build/send (default: go.to.world — the "
                         "safe reversible transport test; steal is the real one)")
    ap.add_argument("--build", action="store_true",
                    help="build the selected frame and print its bytes (no send)")
    ap.add_argument("--sniff-id", action="store_true",
                    help="passively read the next _id (and server_id) off the wire")
    ap.add_argument("--probe-access", action="store_true",
                    help="open a handle to the game and report ACE-granted rights")
    ap.add_argument("--find-handle", action="store_true",
                    help="enumerate + duplicate the game's socket handle (needs DUP_HANDLE)")
    ap.add_argument("--sniff-and-inject", action="store_true",
                    help="passive-sniff for upstream _id, then immediately inject "
                         "go.to.world and wait for the server ACK; requires --force; "
                         "use --server-id / --k1 / --k2 if not seen on wire")
    ap.add_argument("--send", action="store_true",
                    help="actually send the selected frame down the duplicated socket "
                         "(manual mode: requires --server-id --k1 --k2 --id)")
    ap.add_argument("--force", action="store_true",
                    help="required by --send and --sniff-and-inject")
    ap.add_argument("--i-understand-ban-risk", action="store_true",
                    help="required by --send steal; you accept the #972 ban risk")
    ap.add_argument("--uuid", type=_int_auto, help="task uuid (tile field f100)")
    ap.add_argument("--target-server", type=int, help="server the task lives on")
    ap.add_argument("--server-id", type=int, help="home server for the header")
    ap.add_argument("--k1", type=_int_auto, help="per-frame key byte 1")
    ap.add_argument("--k2", type=_int_auto, help="per-frame key byte 2")
    ap.add_argument("--id", type=int, help="next per-connection _id counter")
    args = ap.parse_args()

    if args.build:
        return cmd_build(args)

    if args.sniff_id:
        return 0 if sniff_live_params() else 1

    if args.sniff_and_inject:
        if not args.force:
            print(f"{C_ERR}--sniff-and-inject is gated behind --force.{C_RESET}")
            return 2
        pid, _ = find_game()
        if not pid:
            print(f"{C_ERR}Last War is not running.{C_RESET}")
            return 1
        return sniff_and_inject(pid, args)

    rc = recon()

    if args.probe_access or args.find_handle or args.send:
        pid, _ = find_game()
        if not pid:
            return 1
        if args.send:
            # go.to.world is reversible; steal is not. Both ride the duplicated
            # socket, so both need --force — only steal demands the explicit
            # ban-risk acknowledgement.
            gated = args.force and (args.command != "steal" or args.i_understand_ban_risk)
            if not gated:
                need = "--force --i-understand-ban-risk" if args.command == "steal" else "--force"
                print(f"{C_ERR}--send {args.command} is gated behind {need}. Refusing.{C_RESET}")
                return 2
            frame = _frame_for(args)
            if frame is None:
                return 2
            print(f"{C_WARN}sending {args.command} down a duplicated game socket "
                  f"(send-only, no recv)…{C_RESET}")
            rc_send = send_via_dup(pid, frame)
            verdict()
            return rc_send
        if args.probe_access:
            probe_access(pid)
        if args.find_handle:
            find_handle(pid)

    verdict()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
