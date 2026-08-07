r"""Evaluate a Lua chunk in the live game and read the result back out of a log.

Runs arbitrary Lua via the static facade GameEntry.get_Lua() -> XLuaManager
.SafeDoString(string) (docs/research/xlua-state.md §12). SafeDoString has full CS.*
bindings but returns nothing and swallows Lua errors, so a chunk reports results by
logging: `CS.UnityEngine.Debug.LogError('<MARKER> ...')`. This module captures the lines
written during the call and returns the ones matching the marker.

    C:\Python312\python.exe tools\lua_eval.py "CS.UnityEngine.Debug.LogError('HI '..(1+1))"
    C:\Python312\python.exe tools\lua_eval.py --marker CAM --file chunk.lua

Importable: `from lua_eval import run_lua` -> run_lua(chunk, marker=None) -> [log lines].

WHERE that line is written is this module's business and nobody else's — see
:func:`wrap_chunk`. Every chunk in the repository is still written as a `Debug.LogError`
and none of them had to change: the answer goes into a private file beside `Player.log`
because a chunk that logs through the GAME costs the caller 50–120 ms more than one that
does not, per chunk and regardless of how many lines (measured, #1230 / #1232 —
docs/research/game-call-latency.md).
"""
from __future__ import annotations
import itertools
import os
import sys
import threading
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
#: logs thirty lines has all thirty in the answer log by the time the call returns, read
#: with no wait at all (measured live, #1230). It is a guard against a half-written
#: answer, not a wait for one — a chunk whose lines arrive with a SERVER reply is not
#: something a quiet window can catch, and that caller must stay patient instead.
POLL_SEC = 0.01
QUIET_SEC = 0.02

#: The name of the private answer file, kept beside `Player.log` — see
#: :func:`answer_log_path`. `LW_ANSWER_LOG` names another one outright.
ANSWER_FILE = "lw_answers.log"

#: The answer file is appended to for ever, so it is emptied at the start of a call once
#: it grows past this. A megabyte is thousands of answers — far more than anybody would
#: ever read back — and emptying it is only ever done between calls, never during one.
ANSWER_CAP = 1 << 20

#: A chunk carrying this word anywhere in it keeps the OLD channel: it is run exactly as
#: written, and its answer is read out of `Player.log`.
#:
#: One kind of chunk needs that, and it is not a matter of taste. `wrap_chunk` shadows
#: `CS` for the length of the chunk, so a chunk that INSTALLS something which logs later
#: — tools/lua_trace.py's call shim is the one in the tree — would capture the shadow and
#: divert its whole trace into our file, where the tracer (which tails `Player.log`
#: itself) would never see it. Such a chunk says so, in a comment, and travels through
#: the daemon protocol unchanged because the flag is part of the payload.
GAME_LOG_SENTINEL = "LW_GAME_LOG"


def answer_channel() -> str:
    """``"file"`` (the default) or ``"log"`` — where chunks are made to write.

    `LW_ANSWER_CHANNEL=log` puts every answer back into `Player.log`, which is how this
    worked before #1232. It is the escape hatch for a client whose xLua binding has no
    `System.IO` at all; nothing else should need it, because a chunk that cannot write
    the file falls back to the game's log by itself (see :func:`wrap_chunk`).
    """
    return (os.environ.get("LW_ANSWER_CHANNEL") or "file").strip().lower()


def redirects(chunk: str) -> bool:
    """Whether this chunk's answer is written to the private file rather than the log."""
    return answer_channel() != "log" and GAME_LOG_SENTINEL not in (chunk or "")


def player_log_path():
    """This ACCOUNT's `Player.log` — the fallback answer channel, and the only one for a
    chunk that opted out of the private file (:data:`GAME_LOG_SENTINEL`).

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


def answer_log_path():
    """Where a chunk's answer is written when the channel is the private file.

    Beside `Player.log`, and deliberately so: that folder is this ACCOUNT's, the game
    already writes into it, and two clients are two Windows accounts with two folders —
    so the separation that keeps two daemons from reading each other's answers is the
    same one that already keeps their logs apart, with nothing new to get wrong.

    `LW_ANSWER_LOG` names the file outright for anything stranger.
    """
    forced = (os.environ.get("LW_ANSWER_LOG") or "").strip()
    if forced:
        return forced
    return os.path.join(os.path.dirname(player_log_path()), ANSWER_FILE)


def answer_path_for(chunk: str) -> str:
    """The file THIS chunk's answer will land in — the private one, or `Player.log`.

    For anything that watches the answer arrive rather than asking for it (the latency
    probe, tools/dev/call_latency.py): the choice is made per chunk, so a watcher cannot
    guess it from the environment alone.
    """
    return answer_log_path() if redirects(chunk) else player_log_path()


def _lua_quoted(text: str) -> str:
    """A Lua single-quoted literal of `text` — a Windows path is mostly backslashes."""
    escaped = text.replace("\\", "\\\\").replace("'", "\\'")
    return "'" + escaped + "'"


def wrap_chunk(chunk: str, path: str) -> str:
    r"""`chunk`, with its `Debug.LogError` answers diverted into the file at `path`.

    The reason is one number: a chunk that logs ANYTHING through the game costs 50–120 ms
    more than one that does not, and it costs the same whether it logs one line or five
    (measured live on two clients — #1230, and again under #1232). Writing the same answer
    to a file of our own costs nothing at all; five appends measure cheaper than one log
    line. `LogWarning` is no better, the stack trace is not the cause, and `Debug.Log`
    proper never reaches `Player.log` on this build, which is why the codebase logs errors.

    Where that time goes is NOT where it looks. Timed on the main thread itself, the
    `Debug.LogError` call takes a quarter of a millisecond, and its line is readable in
    `Player.log` as promptly as ours is in the file — so it is neither the call nor a
    flush. It is paid after the chunk returns, in the main thread's availability for the
    NEXT hijack, which is why it is per chunk rather than per line and why the game never
    looks slow while the panel does (docs/research/game-call-latency.md).

    Two hundred and eighty chunks say `CS.UnityEngine.Debug.LogError('MARK …')` and not
    one of them changes, because what is swapped is the `CS` they see: a local table that
    forwards everything to the real one except `UnityEngine.Debug`, whose logging
    functions buffer instead. The chunk runs inside a `pcall`ed function — so a top-level
    `return` still returns, and `...` is still legal — and the buffer is written in ONE
    append when it comes back. A line logged AFTER that (a callback the chunk installed)
    is appended on its own, so nothing is silently dropped.

    Three fallbacks, because this is the answer channel of every chunk in the repository
    and it must not be able to go silent:

      * a client whose xLua binding cannot reach `System.IO.File` logs to the game the
        way it always did, and :meth:`LuaEval.run` reads `Player.log` when the private
        file stayed empty;
      * a failing append does the same, per call;
      * a chunk that raised has its error appended — where `SafeDoString` used to
        swallow it in silence. It carries no marker, so it reaches a person reading the
        file and never a caller parsing lines.
    """
    return (
        # Every reach into the CS bridge is made through a pcall, INCLUDING the member
        # access — `pcall(File.AppendAllText, …)` would resolve the method before the
        # pcall could catch anything, and a throw there happens after the chunk has run,
        # where it takes the whole answer with it.
        "local __lwR=CS "
        "local __lwUE do local o,v=pcall(function() return __lwR.UnityEngine end) "
        "__lwUE=o and v or nil end "
        "local __lwD0 do local o,v=pcall(function() return __lwUE.Debug end) "
        "__lwD0=o and v or nil end "
        "local __lwL do local o,v=pcall(function() return __lwD0.LogError end) "
        "__lwL=o and v or nil end "
        "local __lwF do local o,v=pcall(function() return __lwR.System.IO.File end) "
        "__lwF=o and v or nil end "
        "local __lwP=%s "
        "local __lwB,__lwN,__lwSHUT={},0,false "
        "local function __lwFlush() if __lwN==0 then return end "
        "local t=table.concat(__lwB,'\\n')..'\\n' __lwB,__lwN={},0 "
        "if __lwF and pcall(function() __lwF.AppendAllText(__lwP,t) end) then return end "
        "if __lwL then pcall(__lwL,t) end end "
        "local function __lwW(m) __lwN=__lwN+1 __lwB[__lwN]=tostring(m) "
        "if __lwSHUT then __lwFlush() end end "
        "local __lwD=setmetatable({LogError=__lwW,LogWarning=__lwW,Log=__lwW},"
        "{__index=__lwD0}) "
        "local __lwU=setmetatable({Debug=__lwD},{__index=__lwUE}) "
        "local CS=setmetatable({UnityEngine=__lwU},{__index=__lwR}) "
        "local __lwOK,__lwE=pcall(function(...)\n"
        "%s\n"
        "end) __lwSHUT=true "
        "if not __lwOK then __lwW('lua-error: '..tostring(__lwE)) end __lwFlush()"
    ) % (_lua_quoted(path), chunk)


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _empty_if_huge(path: str) -> int:
    """The byte to start reading `path` from, emptying it first when it has grown past
    :data:`ANSWER_CAP`.

    Called BETWEEN chunks, never during one, so the game is never mid-write. Two
    PROCESSES driving one client would be a different matter — an emptying here moves the
    offset another one is already holding — but that is the case the game lease exists to
    prevent (`LW_GAME_LEASE`), because two hijacks racing the same main thread is a worse
    problem than a lost answer, and it is excluded first.
    """
    size = _size(path)
    if size <= ANSWER_CAP:
        return size
    try:
        with open(path, "wb"):
            pass
    except OSError:
        return size          # somebody has it open — keep appending, prune next time
    return 0


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
            poll: float = POLL_SEC, quiet: float = QUIET_SEC,
            sentinel: "str | None" = None) -> list:
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

    `sentinel` is the SURE version of the same saving, for a chunk whose answer has a
    known last line (#1272). `early` guesses that an answer is complete because it has
    stopped growing for `quiet`, and a chunk that prints a hundred lines through
    `Debug.LogError` — a stack trace apiece — can pause for longer than that mid-answer,
    so the guess truncates it. A chunk that ENDS by printing one recognisable line does
    not need guessing: the wait is over the moment that line appears, whole answer in
    hand, typically inside a poll interval instead of a whole settle. It is a substring
    match against the collected lines, and `settle` remains the deadline for the case
    where the line never comes.
    """
    if sentinel is None and (not early or marker is None):
        time.sleep(settle)
        return _matching(_tail(path, since), marker)
    deadline = time.monotonic() + settle
    lines, grew_at = [], None
    # Only what is NEW, each time round (#1282). This used to re-read and re-split the
    # whole answer on every poll — 10 ms apart, so a 200-line answer waited out over two
    # seconds was up to 200 full reads and 200 full splits of the same text, and the
    # cost grew with the very answers that are biggest: the map sweep and the alliance
    # dumps. The reader now advances as lines are consumed and keeps only the trailing
    # PARTIAL line, so a line that was written in two appends is still seen whole.
    reader = _LineReader(path, since)
    while True:
        fresh = reader.read()
        if fresh:
            picked = _matching(fresh, marker)
            if picked:
                lines, grew_at = lines + picked, time.monotonic()
        if sentinel is not None and any(sentinel in ln for ln in lines):
            break
        now = time.monotonic()
        if early and lines and (now - grew_at) >= quiet:
            break
        if now >= deadline:
            break
        time.sleep(min(poll, max(0.0, deadline - now)))
    return lines


class _LineReader:
    """Whole lines out of a growing file, reading each byte exactly once.

    The offset is in BYTES and the decode happens after the split, so a multi-byte
    character straddling two appends cannot desynchronise the cursor. A last line with
    no newline yet is held back rather than returned half-written — the chunk's buffer
    is flushed in one append, but the game may still be mid-write when a poll lands.
    """

    def __init__(self, path: str, since: int) -> None:
        self.path = path
        self.cursor = since
        self._partial = b""

    def read(self) -> str:
        """Every COMPLETE line written since the last call, as one string."""
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.cursor)
                data = fh.read()
        except OSError:
            return ""
        if not data:
            return ""
        self.cursor += len(data)
        data = self._partial + data
        head, sep, tail = data.rpartition(b"\n")
        if not sep:                      # nothing complete yet — keep waiting
            self._partial = data
            return ""
        self._partial = tail
        return (head + b"\n").decode("utf-8", "replace")


class Pending:
    """A chunk that has ALREADY run in the game, and the answer still to be read.

    Everything :func:`harvest` needs and nothing else — no evaluator, no process handle,
    no lock. That is deliberate: the daemon lets go of its run lock the moment
    :meth:`LuaEval.send` returns, and what it carries out of that lock must not be able
    to touch the hijack.
    """

    __slots__ = ("path", "since", "marker", "settle", "early", "sentinel",
                 "log_path", "log_since", "record")

    def __init__(self, path, since, marker, settle, early, sentinel,
                 log_path=None, log_since=0, record=None) -> None:
        self.path, self.since = path, since
        self.marker, self.settle = marker, settle
        self.early, self.sentinel = early, sentinel
        #: The game's own log, read only when the private file stayed empty. ``None``
        #: for a chunk that opted out of the private file — then `path` IS that log.
        self.log_path, self.log_since = log_path, log_since
        #: The shared answer file a per-call one is folded back into, or ``None``.
        self.record = record

    def harvest(self) -> list:
        """Wait for this chunk's answer and hand back its marker lines.

        A method as well as a function so that what :meth:`LuaEval.send` returns knows
        how to finish itself. That is what a stand-in has to imitate — one object with
        one method — instead of a file layout it would have to fake
        (`tests/test_daemon_lease.py`, whose evaluator stand-in has drifted from this
        interface twice already).
        """
        return harvest(self)


#: Serialises the fold-back of per-call answer files into the shared record. Two
#: harvests finish whenever their settles are over, and an append is not atomic.
_RECORD_LOCK = threading.Lock()

#: Numbers the per-call answer files of this process. `os.getpid()` is in the name too,
#: so two daemons on one machine cannot collide either.
_CALL_SEQ = itertools.count(1)

#: How old a leftover per-call answer file has to be before it is swept. A call that is
#: still running owns its file; an hour is far past any settle in the tree (the longest
#: is 4 s) and past any wedged call worth keeping evidence of.
STALE_ANSWER_SEC = 3600.0


def _per_call_path(base: str) -> str:
    """An answer file for one call, beside the shared one."""
    root, ext = os.path.splitext(base)
    return "%s.%d-%d%s" % (root, os.getpid(), next(_CALL_SEQ), ext or ".log")


def _sweep_per_call(base: str, older_than: float = STALE_ANSWER_SEC) -> int:
    """Delete per-call answer files nobody is going to collect. Returns how many.

    A call whose process died between :meth:`LuaEval.send` and :func:`harvest` leaves
    its file behind, and the daemon that replaces it would otherwise accumulate them for
    ever in the account's own log folder.
    """
    root, ext = os.path.splitext(base)
    folder = os.path.dirname(base) or "."
    prefix, cutoff, gone = os.path.basename(root) + ".", time.time() - older_than, 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(prefix) or (ext and not name.endswith(ext)):
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.getmtime(path) > cutoff:
                continue
            os.remove(path)
            gone += 1
        except OSError:
            continue
    return gone


def _fold_back(path: str, record: str) -> None:
    """Append a per-call answer file to the shared record and delete it.

    The shared file is what a person reads when something went wrong — a `lua-error` is
    written there deliberately, unmarked, so that it reaches a reader and never a caller
    (:func:`wrap_chunk`), and `tools/dev/check_answer_channel.py` checks exactly that.
    Giving each call its own file to avoid cross-talk must not quietly end that, so the
    transport is per call and the RECORD stays one file.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        data = b""
    try:
        os.remove(path)
    except OSError:
        pass
    if not data:
        return
    with _RECORD_LOCK:
        try:
            _empty_if_huge(record)
            with open(record, "ab") as fh:
                fh.write(data)
        except OSError:
            pass


def harvest(pending: "Pending") -> list:
    """The marker lines of a chunk that has already been sent. Waits; takes no lock.

    Split out of :meth:`LuaEval.run` so a daemon can sit out a settle without holding
    the hijack (#1287, `docs/research/architecture-audit.md` §1.1).
    """
    lines = collect(pending.path, pending.since, pending.marker, pending.settle,
                    early=pending.early, sentinel=pending.sentinel)
    if pending.record is not None:
        _fold_back(pending.path, pending.record)
    if lines or pending.log_path is None:
        return lines
    # The settle has already been sat out, so the fallback is a plain read.
    return _matching(_tail(pending.log_path, pending.log_since), pending.marker)


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
        self.answers = answer_log_path()
        # Whatever a previous evaluator left behind when it died mid-call. Once per
        # build, which for a daemon is once per client.
        _sweep_per_call(self.answers)

    def _send(self, chunk) -> None:
        s = self.x.il2_string_new(chunk)
        self.x.invoke(self.sd, self.mgr, [("ref", s)], "SafeDoString")

    def send(self, chunk, marker=None, settle=1.2, early=False, sentinel=None,
             private: bool = False) -> "Pending":
        """Run the chunk in the game and hand back what READING its answer needs.

        THE INJECTION IS OVER WHEN THIS RETURNS. `SafeDoString` is synchronous on the
        game's main thread, and `wrap_chunk` flushes the chunk's whole buffer as the
        chunk comes back — so by the time this returns, an ordinary chunk's answer is
        already in the file, and the settle that follows is a wait for whatever arrives
        LATER (a server reply, a callback the chunk installed).

        That is the whole reason this is a separate call: the hijack must be serialised
        and the waiting must not be. Measured on this machine (#1287): one call is 60 ms
        free and 3 855 ms behind three background readers holding patient settles, and
        95 % of that lock occupancy is :func:`collect` sleeping inside it.

        ``private`` gives THIS call an answer file of its own. Two calls collecting from
        one file at once cannot tell their lines apart — both filter by the same marker
        — so the caller that means to overlap them says so, and everything that does not
        keeps the one shared file it always had. What the private file collected is
        folded back into the shared one afterwards (:func:`harvest`), because that file
        is also the record a person reads a `lua-error` out of.
        """
        if not redirects(chunk):
            since = _size(self.log)
            self._send(chunk)
            return Pending(self.log, since, marker, settle, early, sentinel)
        if private:
            path, since_file, record = _per_call_path(self.answers), 0, self.answers
        else:
            path, since_file, record = self.answers, _empty_if_huge(self.answers), None
        since_log = _size(self.log)
        self._send(wrap_chunk(chunk, path))
        return Pending(path, since_file, marker, settle, early, sentinel,
                       log_path=self.log, log_since=since_log, record=record)

    def run(self, chunk, marker=None, settle=1.2, early=False, sentinel=None,
            private: bool = False):
        """Run one chunk and hand back the marker lines it wrote.

        The answer comes out of the private file (:func:`wrap_chunk`) unless this chunk
        opted out of it. `Player.log` is still read when that file stayed empty — a
        client that could not write it logged to the game instead, and the caller must
        get its answer either way, slowly rather than not at all.

        `sentinel` names the chunk's own last line, and ends the wait when it lands —
        see :func:`collect`.

        Send and harvest in one, for every caller that does its own waiting anyway. The
        daemon splits them (:meth:`send` / :func:`harvest`) so that only the first half
        is under its lock.
        """
        return harvest(self.send(chunk, marker=marker, settle=settle, early=early,
                                 sentinel=sentinel, private=private))

    def close(self):
        import il2cpp_probe as P
        P.CloseHandle(self.x.h)


def run_lua(chunk, marker=None, settle=1.2, early=False, sentinel=None):
    """One-shot convenience: build a LuaEval, run one chunk, tear down."""
    ev = LuaEval()
    try:
        return ev.run(chunk, marker=marker, settle=settle, early=early,
                      sentinel=sentinel)
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
