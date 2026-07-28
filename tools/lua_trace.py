r"""General-purpose live Lua function tracer for the game.

Wraps every function reachable from `_G` (and nested tables up to a small depth) with a
logging shim that writes `XSCALL <table.fn> <- <args>` to Player.log, which this tool tails
to the terminal in real time. Everything the game does through those Lua functions shows up.

By default every call is logged with its FULL (untruncated) argument list — the real trace
you usually want. Because logging every call unfiltered writes thousands of lines per frame
to Player.log and freezes the game, pair a broad run with a narrow `--filter`. For a
filterless overview use `--dedup`: it logs only the first call of each name (the rest are
counted and summarised on exit) — a safe "which functions fire" discovery pass.

There is NO action-specific logic here — it is a raw tracer, useful while reverse
engineering ANY behaviour (march, rally, scene switch, UI, ...).

Single command, self-restoring::

    C:\Python312\python.exe tools\lua_trace.py --filter March  # every March call, full args
    C:\Python312\python.exe tools\lua_trace.py --dedup         # filterless overview (safe)
    C:\Python312\python.exe tools\lua_trace.py                 # every call of everything (floods!)
    C:\Python312\python.exe tools\lua_trace.py --depth 3 --hook-all     # + call-level hook (heavy)

Patches install immediately on start. On Ctrl+C (or any exit) the original functions are
restored and the hook is cleared automatically via atexit + a finally block — there is no
separate install/restore step to remember.

Every run also saves its trace to its own timestamped file,
``results/traces/YYYYMMDD_HHMMSS_trace.log`` — the same lines that reach the terminal, so a
restart never overwrites the previous session (``--out`` to pick the path, ``--no-out`` to
keep it terminal-only).

The tracer talks to the game through `get_evaluator()` (the warm Lua daemon when it is up,
otherwise a fresh local `LuaEval`), exactly like the other tools/ scripts.
"""
from __future__ import annotations

import argparse
import atexit
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Absolute, not "tools/lib": the shared modules resolve the same no matter what
# cwd the launcher (panel, daemon, shell) started us in.
sys.path.insert(0, os.path.join(_HERE, "lib"))
sys.path.insert(0, _HERE)

import lua_client
import run_output
from lua_eval import player_log_path


def _lua_str(s):
    """Render a Python str as a safe Lua single-quoted literal, or `nil` for None."""
    if s is None:
        return "nil"
    esc = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")
    return "'" + esc + "'"


def install_chunk(filter_kw, depth, hook_all, dedup=False):
    r"""Build the Lua chunk that wraps functions and arms the call hook.

    State lives in `_G.__XSTRACE.saved` = list of {tbl, key, orig} so restore can put every
    original function back, and `_G.__XSTRACE.counts` = per-name call counts. Core Lua funcs
    and standard libraries are skipped (wrapping `pcall`/`string.find`/`tostring` — which the
    shim itself uses — would recurse or break the game), and the `CS` bridge is never
    descended into.

    By default every call is logged with its full argument list. `dedup=True` logs only the
    FIRST call of each name (the rest are counted) — a safe discovery pass for a filterless
    run, which otherwise floods Player.log and freezes the game. Pair the default (every)
    mode with a narrow `filter_kw` to keep it safe.
    """
    return r"""
local FILTER = %(filter)s
local MAXDEPTH = %(depth)d
local HOOKALL = %(hookall)s
local DEDUP = %(dedup)s

-- capture Log first, outside the pcall, so the error handler can always report.
local Log = CS.UnityEngine.Debug.LogError

-- The whole install body runs inside pcall: SafeDoString swallows Lua errors, so any
-- failure here would otherwise be invisible (the classic "wrapped=0 / nothing installed").
-- On error we log XSTRACE INSTALL ERROR before returning, so the cause shows in Player.log.
local __ok, __err = pcall(function()

-- capture core funcs as locals so a wrapped global can never break the shim
local pcall, select, tostring, type = pcall, select, tostring, type
local sfind, concat, tinsert = string.find, table.concat, table.insert
local pairs, ipairs = pairs, ipairs

_G.__XSTRACE = _G.__XSTRACE or {}
local T = _G.__XSTRACE
T.saved = T.saved or {}
T.counts = T.counts or {}  -- name -> call count; dedup logs only the first hit
T.shims = T.shims or {}    -- set of shim functions we created (never wrap our own shim)

-- Guard against double-install: if we are already installed, revert to the TRUE originals
-- first. Wrapping an already-wrapped function would save the shim AS the "original", so a
-- later restore would leave that inner shim live forever — an orphan that keeps logging to
-- Player.log and can never be removed (it is no longer in T.saved).
if T.installed and #T.saved > 0 then
  for i = #T.saved, 1, -1 do
    local e = T.saved[i]
    pcall(function() e.tbl[e.key] = e.orig end)
  end
  T.saved = {}
  T.shims = {}
end
T.installed = false

local function MATCH(nm)
  if not FILTER then return true end
  return sfind(nm, FILTER, 1, true) ~= nil
end

local function argstr(...)
  local n = select('#', ...)
  local parts = {}
  for i = 1, n do
    local v = select(i, ...)
    local ok, s = pcall(tostring, v)
    parts[i] = ok and s or ('<'..type(v)..'>')
  end
  return concat(parts, ', ')  -- full arg list, never truncated
end

local function wrap(tbl, key, name, fn)
  if T.shims[fn] then return end  -- fn is already one of our shims: never double-wrap
  local w = function(...)
    if MATCH(name) then
      -- Default logs EVERY call with the full (untruncated) arg list — that is what you
      -- want for a real trace. --dedup collapses to the first hit of each name (the rest
      -- are only counted): a safe discovery pass for a filterless run, since logging every
      -- call unfiltered writes thousands of Debug.LogError lines per frame and freezes the
      -- game. Use a narrow --filter to keep the default (--every) mode safe.
      local c = (T.counts[name] or 0) + 1
      T.counts[name] = c
      if (not DEDUP) or c == 1 then
        -- build the arg string here, in w's vararg scope; a nested closure cannot see `...`
        local a = argstr(...)
        pcall(function() Log('XSCALL '..name..' <- '..a) end)
      end
    end
    return fn(...)
  end
  T.shims[w] = true
  local ok = pcall(function() tbl[key] = w end)  -- some xLua tables are read-only
  if ok then T.saved[#T.saved + 1] = {tbl = tbl, key = key, orig = fn} end
end

-- names never wrapped or descended: core funcs + std libs + the shim's own state
local SKIP = {}
for _, k in ipairs({
  'CS', '_G', '_ENV', '__XSTRACE',
  'string', 'table', 'math', 'coroutine', 'os', 'io', 'debug', 'package',
  'bit', 'bit32', 'utf8', 'jit', 'ffi',
  'pcall', 'xpcall', 'select', 'tostring', 'tonumber', 'type', 'error', 'assert',
  'pairs', 'ipairs', 'next', 'rawget', 'rawset', 'rawequal', 'rawlen',
  'setmetatable', 'getmetatable', 'print', 'require', 'load', 'loadstring',
  'dofile', 'loadfile', 'collectgarbage', 'unpack', 'module', 'setfenv', 'getfenv',
}) do SKIP[k] = true end

-- Broad mode (no filter): also skip per-frame / hot method names. Even with dedup these
-- add pure call overhead to the game's frame loop and rarely tell you anything. A filter
-- means the user is targeting on purpose, so honour it fully and skip nothing extra.
if not FILTER then
  for _, k in ipairs({
    'Update', 'LateUpdate', 'FixedUpdate', 'OnGUI', 'OnUpdate', 'OnLateUpdate',
    'Tick', 'OnTick', 'OnFrame', 'OnRender', 'OnDrawGizmos', 'DoUpdate',
  }) do SKIP[k] = true end
end

local visited = {}
local nwrap = 0
local function walk(tbl, prefix, depth)
  if visited[tbl] then return end
  visited[tbl] = true
  local ok, keys = pcall(function()
    local ks = {}
    for k in pairs(tbl) do ks[#ks + 1] = k end
    return ks
  end)
  if not ok then return end
  for _, k in ipairs(keys) do
    if type(k) == 'string' and not SKIP[k] then
      local ok2, v = pcall(function() return tbl[k] end)
      if ok2 then
        local name = (prefix == '' and k) or (prefix..'.'..k)
        local tv = type(v)
        if tv == 'function' then
          -- only wrap names that pass the filter: wrapping ALL ~9k game functions and
          -- then MATCH-checking every call is what floods Player.log and freezes the
          -- game. With a filter we wrap just the targets; MATCH inside the shim then
          -- always passes. No filter still wraps everything (the explicit noisy mode).
          if MATCH(name) then
            wrap(tbl, k, name, v)
            nwrap = nwrap + 1
          end
        elseif tv == 'table' and depth < MAXDEPTH then
          walk(v, name, depth + 1)
        end
      end
    end
  end
end
walk(_G, '', 0)

-- call-level hook: fires on EVERY Lua call — the heaviest mechanism here and the surest
-- way to stall the game. Wrapping already covers everything reachable from _G, so the hook
-- is opt-in only (--hook-all). It is dedup'd too so it does not flood on its own.
if HOOKALL then
  pcall(function()
    debug.sethook(function()
      local info = debug.getinfo(2, 'nS')
      if info then
        local nm = info.name or '?'
        if MATCH(nm) then
          local key = 'hook:'..nm
          local c = (T.counts[key] or 0) + 1
          T.counts[key] = c
          if (not DEDUP) or c == 1 then
            pcall(function()
              Log('XSCALL[hook] '..nm..' @'..(info.short_src or '?')..':'..(info.linedefined or -1))
            end)
          end
        end
      end
    end, 'c')
  end)
  T.hook = true
end

T.installed = true
Log('XSTRACE installed wrapped='..nwrap..' depth='..MAXDEPTH
    ..' filter='..(FILTER and ('"'..FILTER..'"') or 'none')
    ..' dedup='..tostring(DEDUP)..' hook='..tostring(HOOKALL))

end)  -- end of install-body pcall
if not __ok then
  pcall(function() Log('XSTRACE INSTALL ERROR: '..tostring(__err)) end)
end
""" % {
        "filter": _lua_str(filter_kw),
        "depth": depth,
        "hookall": "true" if hook_all else "false",
        "dedup": "true" if dedup else "false",
    }


RESTORE_CHUNK = r"""
local T = _G.__XSTRACE
if T then
  if T.hook then pcall(function() debug.sethook() end) end
  -- summarise what actually fired: dedup only logged first hits, so the counts are the
  -- only record of how often each name ran (and which fired at all).
  if T.counts then
    local distinct, total = 0, 0
    for _, c in pairs(T.counts) do distinct = distinct + 1 total = total + c end
    CS.UnityEngine.Debug.LogError('XSTRACE traced distinct='..distinct..' calls='..total)
  end
  local n = 0
  if T.saved then
    for i = #T.saved, 1, -1 do
      local e = T.saved[i]
      local ok = pcall(function() e.tbl[e.key] = e.orig end)
      if ok then n = n + 1 end
    end
  end
  T.saved = {}
  T.counts = {}
  T.shims = {}
  T.installed = false
  T.hook = false
  CS.UnityEngine.Debug.LogError('XSTRACE restored '..n)
else
  CS.UnityEngine.Debug.LogError('XSTRACE restored 0 (nothing installed)')
end
"""


def _tail(path, offset):
    """Return (new_offset, [complete lines]) for bytes appended to `path` since `offset`.

    Works at the byte level so the offset stays exact: only bytes up to the last newline are
    consumed, and any trailing partial line is left for the next poll.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return offset, []
    if size < offset:  # log rotated/truncated
        offset = 0
    if size == offset:
        return offset, []
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    nl = data.rfind(b"\n")
    if nl == -1:  # no complete line yet
        return offset, []
    complete = data[: nl + 1]
    lines = complete.decode("utf-8", "replace").splitlines()
    return offset + len(complete), lines


def main():
    ap = argparse.ArgumentParser(description="General live Lua tracer (auto install/restore).")
    ap.add_argument("--filter", help="only log calls whose name contains this keyword")
    ap.add_argument("--depth", type=int, default=2, help="how deep to descend nested tables (default 2)")
    ap.add_argument("--hook-all", action="store_true",
                    help="also arm debug.sethook (fires on EVERY Lua call — heaviest, may stall the game)")
    ap.add_argument("--dedup", action="store_true",
                    help="log only the FIRST call of each name (safe discovery pass; default logs every call)")
    ap.add_argument("--all", action="store_true", help="print every Player.log line, not just XSCALL/XSTRACE")
    ap.add_argument("--out", help="trace file path (default: a new "
                                  "results/traces/<timestamp>_trace.log per run)")
    ap.add_argument("--label", help="free-text session label folded into the default "
                                    "file name (spaces become underscores); ignored with --out")
    ap.add_argument("--no-out", action="store_true",
                    help="print to the terminal only, save no trace file")
    args = ap.parse_args()

    dedup = args.dedup

    log = player_log_path()

    # One fresh file per run: restarting the tracer must not overwrite the
    # previous session's trace nor append into it. Line-buffered, because a run
    # normally ends by being killed (the panel's Stop is TerminateProcess, which
    # flushes nothing) and because the file is usually tailed while it grows.
    trace_file = trace_path = None
    if not args.no_out:
        try:
            if args.out:
                os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
                trace_file, trace_path = open(args.out, "w", encoding="utf-8", buffering=1), args.out
            else:
                trace_file, trace_path = run_output.open_run_file(
                    "traces", "trace.log", label=args.label)
        except OSError as exc:
            print("[lua_trace] cannot open trace file (%s) — printing only" % exc, file=sys.stderr)

    def emit(line):
        """Print a line and mirror it into this run's trace file."""
        print(line)
        if trace_file is not None and not trace_file.closed:
            try:
                trace_file.write(line + "\n")
            except Exception:
                pass  # a failed write must never interrupt the trace

    ev = lua_client.get_evaluator()

    restored = {"done": False}

    def restore():
        if restored["done"]:
            return
        restored["done"] = True
        # Under the default (every) mode the game floods Player.log, and a single restore
        # can miss its confirmation window — leaving wraps live. Retry (idempotent: a second
        # restore just reports "nothing installed") until Player.log confirms it ran.
        for attempt in range(5):
            try:
                out = ev.run(RESTORE_CHUNK, marker="XSTRACE", settle=1.2 + attempt)
            except Exception as e:  # never let teardown crash
                print("[lua_trace] restore attempt %d failed: %s" % (attempt, e), file=sys.stderr)
                continue
            if any("XSTRACE restored" in ln for ln in out):
                emit("[lua_trace] %s" % "; ".join(out))
                return
        print("[lua_trace] WARNING: restore not confirmed after retries — "
              "rerun tools/lua_trace.py or restart the game to be safe", file=sys.stderr)

    atexit.register(restore)

    emit("[lua_trace] installing patches (filter=%s depth=%d dedup=%s hook=%s) ..."
         % (args.filter or "none", args.depth, dedup, args.hook_all))
    if trace_path:
        emit("[lua_trace] trace file: %s" % trace_path)
    lines = ev.run(install_chunk(args.filter, args.depth, args.hook_all, dedup), marker="XSTRACE", settle=1.5)
    for ln in lines:
        emit(ln)
    # One machine-readable verdict on top of the game-side wording, so a driver
    # (the panel) knows when the hooks are actually live instead of guessing
    # from the spawn time: installing costs ~2 s with a warm Lua daemon and
    # several more when it has to attach first, and every action taken before
    # that is simply not traced.
    # wrapped=0 counts as a failure, not as readiness: the chunk ran but armed
    # nothing, which makes the whole recording void (see docs/skills/sniff.md §8.1).
    wrapped = 0
    for ln in lines:
        if "XSTRACE installed" in ln:
            found = re.search(r"wrapped=(\d+)", ln)
            wrapped = int(found.group(1)) if found else 0
    if wrapped:
        emit("[lua_trace] TRACE READY — hooks live (wrapped=%d)" % wrapped)
    else:
        emit("[lua_trace] TRACE FAILED — no hooks installed (see the lines above)")
    emit("[lua_trace] tailing %s — Ctrl+C to stop and restore\n" % log)

    offset = os.path.getsize(log) if os.path.exists(log) else 0
    try:
        while True:
            offset, new = _tail(log, offset)
            for ln in new:
                ln = ln.rstrip("\r")
                if args.all or ("XSCALL" in ln or "XSTRACE" in ln):
                    emit(ln)
            time.sleep(0.3)
    except KeyboardInterrupt:
        emit("\n[lua_trace] stopping ...")
    finally:
        restore()
        try:
            ev.close()
        except Exception:
            pass
        if trace_file is not None:
            try:
                trace_file.close()
            except Exception:
                pass
            print("[lua_trace] trace written to %s" % trace_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
