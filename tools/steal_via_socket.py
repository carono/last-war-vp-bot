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
    python tools/steal_via_socket.py --send --force    # send go.to.world (emulator)
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


def _peer(ws2, handle: int):
    """getpeername on a duplicated handle → (ip, port), or None if not a socket.

    Safe on ANY handle: a non-socket returns SOCKET_ERROR immediately. Used to
    tell sockets from the game's ~1600 other handles WITHOUT getsockname, which
    was observed to block indefinitely on some objects.
    """
    import socket
    sa = _SockAddrIn()
    ln = ctypes.c_int(ctypes.sizeof(sa))
    if ws2.getpeername(ctypes.c_void_p(handle), ctypes.byref(sa), ctypes.byref(ln)) != 0:
        return None
    return ".".join(str(b) for b in sa.addr), socket.ntohs(sa.port)


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

    Returns 0 on a successful send. Fails (non-zero) if the game socket cannot
    be pinned — which on a VPN/proxy machine it cannot, because every peer reads
    as the tunnel endpoint. This is send-only: it never recv()s, so it cannot
    steal bytes the game is waiting on (a shared-buffer read would desync it).
    """
    win = _win()
    k32, ws2 = win["k32"], win["ws2"]
    try:
        socks = dup_game_sockets(pid, match_port=GAME_PORT)
    except OSError as exc:
        print(f"{C_ERR}{exc}{C_RESET}")
        return 1
    if not socks:
        print(f"{C_ERR}could not pin the :{GAME_PORT} game socket (VPN/proxy "
              f"rewrites peers). Disable the tunnel or add local-port matching."
              f"{C_RESET}")
        return 1
    _hval, dup, peer = socks[0]
    for _h, d, _p in socks[1:]:
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
    ap.add_argument("--send", action="store_true",
                    help="actually send the selected frame down the duplicated socket")
    ap.add_argument("--force", action="store_true", help="required by --send")
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
