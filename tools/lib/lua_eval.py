r"""Evaluate a Lua chunk in the live game and read the result back from Player.log.

Runs arbitrary Lua via the static facade GameEntry.get_Lua() -> XLuaManager
.SafeDoString(string) (docs/research/xlua-state.md §12). SafeDoString has full CS.*
bindings but returns nothing and swallows Lua errors, so a chunk reports results by
logging: `CS.UnityEngine.Debug.LogError('<MARKER> ...')`. This tool captures the
Player.log lines written during the call and prints the ones matching the marker.

    C:\Python312\python.exe tools\lua_eval.py "CS.UnityEngine.Debug.LogError('HI '..(1+1))"
    C:\Python312\python.exe tools\lua_eval.py --marker CAM --file chunk.lua

Importable: `from lua_eval import run_lua` -> run_lua(chunk, marker=None) -> [log lines].
"""
from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, "tools/lib")
import game_paths

# The il2cpp stack (`xlua_route`, `il2cpp_probe`) is imported by `LuaEval` itself, not
# here: it is Windows-only and it is only the DRIVING half of this module. Reading the
# answer back out of the log — `collect`, and the deadline it honours — is plain file
# handling, and a test of it should not need a game, a Windows or a hijack.

#: How often the log is re-read while an answer is being waited for, and how long a
#: chunk that HAS answered is given to write one more line before the wait is over.
#: Both only apply to an `early` call — see :func:`collect`.
#:
#: The quiet window is short because the game's own writing is not lazy: a chunk that
#: logs thirty lines has all thirty in `Player.log` by the time the call returns, read
#: with no wait at all (measured live, #1230). It is a guard against a half-written
#: answer, not a wait for one — a chunk whose lines arrive with a SERVER reply is not
#: something a quiet window can catch, and that caller must stay patient instead.
POLL_SEC = 0.01
QUIET_SEC = 0.02


def player_log_path():
    """Where every Lua result is read back from — this ACCOUNT's `Player.log`.

    `%LOCALAPPDATA%` is ``…\\AppData\\Local``; the log lives beside it under
    ``…\\AppData\\LocalLow``. Deliberately the calling process's own: two accounts have
    two logs, another user's LocalLow is unreadable without a grant, and a daemon
    pointed at the wrong one silently returns nothing at all
    (docs/research/multi-instance-second-user.md). So each daemon must run as its own
    account — which is what `GameLink` now makes sure of.

    The publisher/product folder is `tools/lib/game_paths.py`'s answer rather than a
    literal, so a game installed elsewhere moves this too (`LW_GAME_FOLDER`), and
    `LW_PLAYER_LOG` names the file outright for anything stranger.
    """
    forced = (os.environ.get("LW_PLAYER_LOG") or "").strip()
    if forced:
        return forced
    local = os.environ.get("LOCALAPPDATA", "")
    low = os.path.join(os.path.dirname(local), "LocalLow")
    return os.path.join(low, game_paths.game_folder(), "Player.log")


def _tail(path: str, since: int) -> str:
    """Whatever was written to `path` after byte `since` ("" if it cannot be read)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(since)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _matching(text: str, marker) -> list:
    return [ln.rstrip("\r") for ln in text.splitlines()
            if marker is None or marker in ln]


def collect(path: str, since: int, marker, settle: float, early: bool = False,
            poll: float = POLL_SEC, quiet: float = QUIET_SEC) -> list:
    """The marker lines a chunk wrote to `path`, waiting for them up to `settle`.

    `settle` has always been a plain sleep, and it is what a press cost: the answer of
    an ordinary chunk is in the log ~30 ms after the call returns (measured live, #1230)
    and the panel then sat out the remaining second and a half. It cost more than the
    wait itself — the game lease is held for the whole of it, so the NEXT press is
    refused as «занято», and a recipe pays it once per step.

    `early` makes `settle` a DEADLINE instead: poll the log, and stop as soon as the
    marker has appeared and stopped growing for `quiet`. Never longer than `settle`, so
    it can only make a call faster.

    It is opt-in, and deliberately so. For a chunk that answers by itself — a read, a
    press that reports `ACT tap=ok`, a jump that logs where it went — the settle is
    pure waiting and `early` is right. For a chunk that ASKS THE SERVER something and
    logs its acknowledgement at once (the treasure refresh, the command-post reads), the
    settle is the round trip to the server, the marker lands long before the answer
    does, and cutting it short would return an empty list. The caller knows which of
    the two it wrote; this function cannot tell them apart.

    With no marker there is nothing to recognise an answer by, so an `early` call waits
    exactly as a patient one does.
    """
    if not early or marker is None:
        time.sleep(settle)
        return _matching(_tail(path, since), marker)
    deadline = time.monotonic() + settle
    lines, grew_at = [], None
    while True:
        found = _matching(_tail(path, since), marker)
        if len(found) > len(lines):
            lines, grew_at = found, time.monotonic()
        now = time.monotonic()
        if lines and (now - grew_at) >= quiet:
            break
        if now >= deadline:
            break
        time.sleep(min(poll, max(0.0, deadline - now)))
    return lines


class LuaEval:
    """Reusable SafeDoString driver — resolve once, run many chunks."""

    def __init__(self):
        import xlua_route as XR
        self.x = XR.X()
        self.x.find_luaenv_class()  # sets gameentry_cls / xluamgr_cls
        m, _, _ = self.x.gmfn(self.x.gameentry_cls, "get_Lua", 0)
        self.mgr, exc = self.x.invoke(m, 0, [], "GameEntry.get_Lua")
        if not self.mgr or exc:
            raise SystemExit(f"GameEntry.get_Lua failed mgr=0x{self.mgr:x} exc=0x{exc:x}")
        self.sd, _, _ = self.x.gmfn(self.x.xluamgr_cls, "SafeDoString", 1)
        if not self.sd:
            raise SystemExit("XLuaManager.SafeDoString not resolved")
        self.log = player_log_path()

    def run(self, chunk, marker=None, settle=1.2, early=False):
        since = os.path.getsize(self.log) if os.path.exists(self.log) else 0
        s = self.x.il2_string_new(chunk)
        self.x.invoke(self.sd, self.mgr, [("ref", s)], "SafeDoString")
        return collect(self.log, since, marker, settle, early=early)

    def close(self):
        import il2cpp_probe as P
        P.CloseHandle(self.x.h)


def run_lua(chunk, marker=None, settle=1.2, early=False):
    """One-shot convenience: build a LuaEval, run one chunk, tear down."""
    ev = LuaEval()
    try:
        return ev.run(chunk, marker=marker, settle=settle, early=early)
    finally:
        ev.close()


def main():
    argv = sys.argv[1:]
    marker = None
    if "--marker" in argv:
        i = argv.index("--marker")
        marker = argv[i + 1]
        del argv[i:i + 2]
    if "--file" in argv:
        i = argv.index("--file")
        chunk = open(argv[i + 1], encoding="utf-8").read()
    elif argv:
        chunk = argv[0]
    else:
        chunk = "CS.UnityEngine.Debug.LogError('LUA_EVAL alive '..tostring(1+1))"
        marker = marker or "LUA_EVAL"
    for ln in run_lua(chunk, marker=marker):
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
