r"""General-purpose live Lua function tracer for the game.

Wraps every function reachable from `_G` (and nested tables up to a small depth) with a
logging shim that writes `XSCALL <table.fn> <- <args>` to Player.log, and installs a
`debug.sethook('c')` call-level hook as well. Everything the game does through those Lua
functions then shows up in Player.log, which this tool tails to the terminal in real time.

There is NO action-specific logic here — it is a raw tracer, useful while reverse
engineering ANY behaviour (march, rally, scene switch, UI, ...). Narrow the noise with
`--filter <keyword>`.

Single command, self-restoring::

    C:\Python312\python.exe tools\lua_trace.py                 # trace everything
    C:\Python312\python.exe tools\lua_trace.py --filter March  # only names containing "March"
    C:\Python312\python.exe tools\lua_trace.py --depth 3 --hook-all

Patches install immediately on start. On Ctrl+C (or any exit) the original functions are
restored and the hook is cleared automatically via atexit + a finally block — there is no
separate install/restore step to remember.

The tracer talks to the game through `get_evaluator()` (the warm Lua daemon when it is up,
otherwise a fresh local `LuaEval`), exactly like the other tools/ scripts.
"""
from __future__ import annotations

import argparse
import atexit
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lua_client
from lua_eval import player_log_path


def _lua_str(s):
    """Render a Python str as a safe Lua single-quoted literal, or `nil` for None."""
    if s is None:
        return "nil"
    esc = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")
    return "'" + esc + "'"


def install_chunk(filter_kw, depth, hook_all):
    r"""Build the Lua chunk that wraps functions and arms the call hook.

    State lives in `_G.__XSTRACE.saved` = list of {tbl, key, orig} so restore can put every
    original function back. Core Lua funcs and standard libraries are skipped (wrapping
    `pcall`/`string.find`/`tostring` — which the shim itself uses — would recurse or break
    the game), and the `CS` bridge is never descended into.
    """
    return r"""
local FILTER = %(filter)s
local MAXDEPTH = %(depth)d
local HOOKALL = %(hookall)s

-- capture core funcs as locals so a wrapped global can never break the shim
local Log = CS.UnityEngine.Debug.LogError
local pcall, select, tostring, type = pcall, select, tostring, type
local sfind, concat, tinsert = string.find, table.concat, table.insert
local pairs, ipairs = pairs, ipairs

_G.__XSTRACE = _G.__XSTRACE or {}
local T = _G.__XSTRACE
T.saved = T.saved or {}

local function MATCH(nm)
  if not FILTER then return true end
  return sfind(nm, FILTER, 1, true) ~= nil
end

local function argstr(...)
  local n = select('#', ...)
  local lim = n < 6 and n or 6
  local parts = {}
  for i = 1, lim do
    local v = select(i, ...)
    local ok, s = pcall(tostring, v)
    parts[i] = ok and s or ('<'..type(v)..'>')
  end
  local out = concat(parts, ', ')
  if n > lim then out = out..' ...(+'..(n - lim)..')' end
  return out
end

local function wrap(tbl, key, name, fn)
  local w = function(...)
    if MATCH(name) then
      pcall(function() Log('XSCALL '..name..' <- '..argstr(...)) end)
    end
    return fn(...)
  end
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
          wrap(tbl, k, name, v)
          nwrap = nwrap + 1
        elseif tv == 'table' and depth < MAXDEPTH then
          walk(v, name, depth + 1)
        end
      end
    end
  end
end
walk(_G, '', 0)

-- call-level hook: fires on every Lua call. Unfiltered it would flood Player.log and stall
-- the game, so only arm it when a filter is set or --hook-all was explicitly requested.
if FILTER or HOOKALL then
  pcall(function()
    debug.sethook(function()
      local info = debug.getinfo(2, 'nS')
      if info then
        local nm = info.name or '?'
        if MATCH(nm) then
          pcall(function()
            Log('XSCALL[hook] '..nm..' @'..(info.short_src or '?')..':'..(info.linedefined or -1))
          end)
        end
      end
    end, 'c')
  end)
  T.hook = true
end

T.installed = true
Log('XSTRACE installed wrapped='..nwrap..' depth='..MAXDEPTH
    ..' filter='..(FILTER and ('"'..FILTER..'"') or 'none')
    ..' hook='..tostring(FILTER ~= nil or HOOKALL))
""" % {
        "filter": _lua_str(filter_kw),
        "depth": depth,
        "hookall": "true" if hook_all else "false",
    }


RESTORE_CHUNK = r"""
local T = _G.__XSTRACE
if T then
  if T.hook then pcall(function() debug.sethook() end) end
  local n = 0
  if T.saved then
    for i = #T.saved, 1, -1 do
      local e = T.saved[i]
      local ok = pcall(function() e.tbl[e.key] = e.orig end)
      if ok then n = n + 1 end
    end
  end
  T.saved = {}
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
                    help="arm debug.sethook even without a filter (very noisy — may stall the game)")
    ap.add_argument("--all", action="store_true", help="print every Player.log line, not just XSCALL/XSTRACE")
    args = ap.parse_args()

    log = player_log_path()
    ev = lua_client.get_evaluator()

    restored = {"done": False}

    def restore():
        if restored["done"]:
            return
        restored["done"] = True
        try:
            ev.run(RESTORE_CHUNK, marker="XSTRACE", settle=1.2)
            print("[lua_trace] restored original functions + cleared hook")
        except Exception as e:  # never let teardown crash
            print("[lua_trace] restore failed: %s" % e, file=sys.stderr)

    atexit.register(restore)

    print("[lua_trace] installing patches (filter=%s depth=%d hook=%s) ..."
          % (args.filter or "none", args.depth, bool(args.filter) or args.hook_all))
    lines = ev.run(install_chunk(args.filter, args.depth, args.hook_all), marker="XSTRACE", settle=1.5)
    for ln in lines:
        print(ln)
    print("[lua_trace] tailing %s — Ctrl+C to stop and restore\n" % log)

    offset = os.path.getsize(log) if os.path.exists(log) else 0
    try:
        while True:
            offset, new = _tail(log, offset)
            for ln in new:
                ln = ln.rstrip("\r")
                if args.all or ("XSCALL" in ln or "XSTRACE" in ln):
                    print(ln)
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n[lua_trace] stopping ...")
    finally:
        restore()
        try:
            ev.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
