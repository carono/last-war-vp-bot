r"""Manual, stealth IL2CPP remote-call probe (step 1 of in-process inject).

No LoadLibrary, no Frida. It:
  1. finds LastWar.exe and the loaded base of GameAssembly.dll,
  2. parses the module's export table straight from process memory (the on-disk
     global-metadata.dat is hidden, but the loaded il2cpp_* exports are not),
  3. resolves il2cpp_domain_get,
  4. runs a tiny x64 thunk via CreateRemoteThread that calls it and stores the
     64-bit return into a scratch buffer, which we read back.

Success = a plausible non-null domain pointer, proving we can invoke already
loaded engine functions in-process without breaking anything. This is the
foundation for a later class/method dumper and the eventual "go.to.world"
call through the client's own network layer.

Run under Windows Python:
    C:\Python312\python.exe tools\il2cpp_probe.py
"""
from __future__ import annotations

import ctypes as C
import struct
import sys
from ctypes import wintypes

import game_paths  # the client's process name — LW_GAME_EXE, not a literal

MODULE = "GameAssembly.dll"

k32 = C.WinDLL("kernel32", use_last_error=True)


def _decl(fn, restype, argtypes):
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


# HANDLE args must be declared or the (HANDLE)-1 pseudo-handle truncates to
# 32-bit and calls fail with ERROR_INVALID_HANDLE — the load-bearing bug from
# the socket-dup work.
OpenProcess = _decl(k32.OpenProcess, wintypes.HANDLE,
                    [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD])
CloseHandle = _decl(k32.CloseHandle, wintypes.BOOL, [wintypes.HANDLE])
VirtualAllocEx = _decl(k32.VirtualAllocEx, C.c_void_p,
                       [wintypes.HANDLE, C.c_void_p, C.c_size_t,
                        wintypes.DWORD, wintypes.DWORD])
VirtualFreeEx = _decl(k32.VirtualFreeEx, wintypes.BOOL,
                      [wintypes.HANDLE, C.c_void_p, C.c_size_t, wintypes.DWORD])
WriteProcessMemory = _decl(k32.WriteProcessMemory, wintypes.BOOL,
                           [wintypes.HANDLE, C.c_void_p, C.c_void_p,
                            C.c_size_t, C.POINTER(C.c_size_t)])
ReadProcessMemory = _decl(k32.ReadProcessMemory, wintypes.BOOL,
                          [wintypes.HANDLE, C.c_void_p, C.c_void_p,
                           C.c_size_t, C.POINTER(C.c_size_t)])
CreateRemoteThread = _decl(k32.CreateRemoteThread, wintypes.HANDLE,
                           [wintypes.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p,
                            C.c_void_p, wintypes.DWORD, C.POINTER(wintypes.DWORD)])
WaitForSingleObject = _decl(k32.WaitForSingleObject, wintypes.DWORD,
                            [wintypes.HANDLE, wintypes.DWORD])
GetExitCodeThread = _decl(k32.GetExitCodeThread, wintypes.BOOL,
                          [wintypes.HANDLE, C.POINTER(wintypes.DWORD)])

PROCESS_ALL = 0x1FFFFF
MEM_COMMIT_RESERVE = 0x3000
MEM_RELEASE = 0x8000
PAGE_RW = 0x04
PAGE_EXEC_RW = 0x40


# --- module base via Toolhelp -------------------------------------------------
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010


class MODULEENTRY32W(C.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", C.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * 260),
    ]


def _session_of(pid: int) -> int | None:
    sid = wintypes.DWORD()
    if k32.ProcessIdToSessionId(pid, C.byref(sid)):
        return int(sid.value)
    return None


def find_game_pid() -> int:
    """The client to drive: `LW_GAME_PID` if set, else one in the caller's session.

    With a second client running in a second Windows session (task #1106) "the first
    LastWar.exe" is a coin toss, and the loser is a process this token usually cannot
    even open. The caller's own session is the right default — a daemon started inside
    a session belongs to the client of that session — and `LW_GAME_PID` overrides it.
    Falls back to any client, so the single-instance case is unchanged.
    """
    import os
    import psutil
    forced = os.environ.get("LW_GAME_PID")
    if forced:
        pid = int(forced)
        if not psutil.pid_exists(pid):
            raise SystemExit(f"LW_GAME_PID={pid} is not running")
        return pid
    mine = _session_of(k32.GetCurrentProcessId())
    others = []
    for p in psutil.process_iter(["name"]):
        # The client itself — not the launcher / the updater, which share the prefix,
        # have no il2cpp in them, and disappear once the client is up.
        if (p.info["name"] or "").lower() == game_paths.game_exe().lower():
            if _session_of(p.pid) == mine:
                return p.pid
            others.append(p.pid)
    if others:
        return others[0]
    raise SystemExit("LastWar.exe not running")


def module_base(pid: int, name: str) -> tuple[int, int]:
    CreateToolhelp32Snapshot = _decl(k32.CreateToolhelp32Snapshot,
                                     wintypes.HANDLE, [wintypes.DWORD, wintypes.DWORD])
    Module32FirstW = _decl(k32.Module32FirstW, wintypes.BOOL,
                           [wintypes.HANDLE, C.POINTER(MODULEENTRY32W)])
    Module32NextW = _decl(k32.Module32NextW, wintypes.BOOL,
                          [wintypes.HANDLE, C.POINTER(MODULEENTRY32W)])
    snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == wintypes.HANDLE(-1).value:
        raise SystemExit(f"snapshot failed err={C.get_last_error()}")
    me = MODULEENTRY32W()
    me.dwSize = C.sizeof(me)
    try:
        ok = Module32FirstW(snap, C.byref(me))
        while ok:
            if me.szModule.lower() == name.lower():
                return int(me.modBaseAddr), int(me.modBaseSize)
            ok = Module32NextW(snap, C.byref(me))
    finally:
        CloseHandle(snap)
    raise SystemExit(f"{name} not found in pid {pid}")


# --- remote read helpers ------------------------------------------------------
def rpm(hproc, addr: int, size: int) -> bytes:
    buf = (C.c_char * size)()
    got = C.c_size_t(0)
    if not ReadProcessMemory(hproc, C.c_void_p(addr), buf, size, C.byref(got)):
        raise OSError(f"RPM @0x{addr:x} failed err={C.get_last_error()}")
    return bytes(buf[:got.value])


def read_cstr(hproc, addr: int, maxlen: int = 128) -> str:
    data = rpm(hproc, addr, maxlen)
    end = data.find(b"\x00")
    return data[:end if end >= 0 else maxlen].decode("ascii", "replace")


def parse_exports(hproc, base: int) -> dict[str, int]:
    """Parse the PE export table from the loaded image in process memory."""
    hdr = rpm(hproc, base, 0x400)
    e_lfanew = struct.unpack_from("<I", hdr, 0x3C)[0]
    # optional header starts after PE sig(4) + COFF header(20)
    opt = base + e_lfanew + 4 + 20
    opt_hdr = rpm(hproc, opt, 0x100)
    magic = struct.unpack_from("<H", opt_hdr, 0)[0]
    if magic != 0x20B:
        raise SystemExit(f"not PE32+ (magic=0x{magic:x})")
    # data directory 0 = export table, located at optional header + 112 (PE32+)
    export_rva, export_size = struct.unpack_from("<II", opt_hdr, 112)
    if not export_rva:
        raise SystemExit("no export directory")
    ed = rpm(hproc, base + export_rva, 40)
    (n_funcs, n_names, addr_funcs, addr_names, addr_ord) = struct.unpack_from(
        "<IIIII", ed, 0x14)
    names_arr = rpm(hproc, base + addr_names, n_names * 4)
    ord_arr = rpm(hproc, base + addr_ord, n_names * 2)
    func_arr = rpm(hproc, base + addr_funcs, n_funcs * 4)
    exports: dict[str, int] = {}
    for i in range(n_names):
        name_rva = struct.unpack_from("<I", names_arr, i * 4)[0]
        name = read_cstr(hproc, base + name_rva, 96)
        ordi = struct.unpack_from("<H", ord_arr, i * 2)[0]
        func_rva = struct.unpack_from("<I", func_arr, ordi * 4)[0]
        exports[name] = base + func_rva
    return exports


# --- remote call of a 0-arg function returning a 64-bit value ------------------
def remote_call0(hproc, func_abs: int) -> int:
    """Run: result = func();  return result. Via a tiny x64 thunk.

    thunk layout (Win64 ABI, 32B shadow + 16B align):
        sub rsp,0x28 / mov rax,func / call rax / mov rcx,result / mov [rcx],rax
        / add rsp,0x28 / xor eax,eax / ret
    """
    region = VirtualAllocEx(hproc, None, 0x200, MEM_COMMIT_RESERVE, PAGE_EXEC_RW)
    if not region:
        raise OSError(f"VirtualAllocEx failed err={C.get_last_error()}")
    region = int(region)
    result_abs = region            # 8-byte result slot at region+0
    code_abs = region + 0x40       # shellcode at region+0x40
    sc = b"".join([
        b"\x48\x83\xEC\x28",                       # sub rsp,0x28
        b"\x48\xB8" + struct.pack("<Q", func_abs), # mov rax, func_abs
        b"\xFF\xD0",                               # call rax
        b"\x48\xB9" + struct.pack("<Q", result_abs),  # mov rcx, result_abs
        b"\x48\x89\x01",                           # mov [rcx], rax
        b"\x48\x83\xC4\x28",                       # add rsp,0x28
        b"\x31\xC0",                               # xor eax,eax
        b"\xC3",                                   # ret
    ])
    zero = b"\x00" * 0x40
    written = C.c_size_t(0)
    if not WriteProcessMemory(hproc, C.c_void_p(region), zero, len(zero), C.byref(written)):
        raise OSError(f"WPM zero failed err={C.get_last_error()}")
    if not WriteProcessMemory(hproc, C.c_void_p(code_abs), sc, len(sc), C.byref(written)):
        raise OSError(f"WPM code failed err={C.get_last_error()}")

    tid = wintypes.DWORD(0)
    hthread = CreateRemoteThread(hproc, None, 0, C.c_void_p(code_abs), None, 0,
                                 C.byref(tid))
    if not hthread:
        VirtualFreeEx(hproc, C.c_void_p(region), 0, MEM_RELEASE)
        raise OSError(f"CreateRemoteThread failed err={C.get_last_error()}")
    WaitForSingleObject(hthread, 5000)
    exit_code = wintypes.DWORD(0)
    GetExitCodeThread(hthread, C.byref(exit_code))
    CloseHandle(hthread)
    result = struct.unpack("<Q", rpm(hproc, result_abs, 8))[0]
    VirtualFreeEx(hproc, C.c_void_p(region), 0, MEM_RELEASE)
    return result, exit_code.value


def main() -> int:
    pid = find_game_pid()
    print(f"[probe] LastWar.exe pid={pid}")
    base, size = module_base(pid, MODULE)
    print(f"[probe] {MODULE} base=0x{base:x} size=0x{size:x}")
    hproc = OpenProcess(PROCESS_ALL, False, pid)
    if not hproc:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")
    try:
        # --- self-test: prove the thunk mechanism on a known 0-arg WinAPI ---
        kbase, _ = module_base(pid, "kernel32.dll")
        kexp = parse_exports(hproc, kbase)
        gcpi = kexp.get("GetCurrentProcessId")
        print(f"[probe] self-test kernel32!GetCurrentProcessId @0x{gcpi:x} …")
        val, ec = remote_call0(hproc, gcpi)
        got_pid = val & 0xFFFFFFFF
        ok_self = got_pid == pid
        print(f"[probe]   returned={got_pid} (expect {pid})  exit=0x{ec:x}  "
              f"{'THUNK OK' if ok_self else 'THUNK BROKEN'}")

        exports = parse_exports(hproc, base)
        il = {k: v for k, v in exports.items() if k.startswith("il2cpp_")}
        print(f"[probe] exports total={len(exports)}  il2cpp_={len(il)}")
        for k in ("il2cpp_domain_get", "il2cpp_thread_attach",
                  "il2cpp_domain_get_assemblies", "il2cpp_runtime_invoke",
                  "il2cpp_string_new"):
            print(f"    {k}: {'0x%x' % exports[k] if k in exports else 'MISSING'}")
        target = exports.get("il2cpp_domain_get")
        if not target:
            raise SystemExit("il2cpp_domain_get not exported — cannot probe")
        print(f"[probe] remote-calling il2cpp_domain_get @0x{target:x} …")
        domain, ec2 = remote_call0(hproc, target)
        plausible = 0x10000 < domain < 0x7FFFFFFFFFFF
        print(f"[probe] domain = 0x{domain:x}  exit=0x{ec2:x}  "
              f"({'PLAUSIBLE' if plausible else 'SUSPECT'})")
        if plausible:
            print("[probe] SUCCESS — in-process il2cpp call works, connection intact")
            return 0
        if ok_self:
            print("[probe] thunk works but il2cpp_domain_get returned 0 — export is "
                  "likely a stub/obfuscated; try xLua or internal resolver")
        return 1
    finally:
        CloseHandle(hproc)


if __name__ == "__main__":
    sys.exit(main())
