#!/usr/bin/env python3
r"""Read Last War chat (world / national / alliance / DM) out of the game's Lua VM.

Why this exists
---------------
The live chat broadcast (world / national / alliance firehose) does NOT ride the
plain-TCP game leg on :17935 -- it flows over a dedicated TLS WebSocket
(``lastwar-chat-wss-*``) and is therefore NOT passively decodable without a TLS
keylog / MITM (ruled out by project policy). See ``docs/research/chat.md``.

Passive ``tools/chat_monitor.py`` only ever sees the TCP control leg (DM
send/ack, room registry, map-object shares). It can never see world/alliance
broadcast text.

This tool takes the other route that project policy DOES allow: read the messages
*after* the client has decrypted them, from inside the game's own Lua state via
the warm xLua daemon (see ``docs/research/game-launch-and-scene-control.md`` and
the ``project_xlua_dostring_live`` memory). Every incoming ``ChatMessage`` (class
``ChatMessage`` in the client) is intercepted at the Lua ingress and copied into a
ring buffer that this script polls, hex-decodes (to survive Player.log's mangling
of non-ASCII) and emits as one JSON line per message.

Requirements / caveats
----------------------
* The warm Lua daemon must be running (``tools/lua_daemon.py``) and the game
  alive. Run under the Windows Python so it can reach the daemon:
      C:\Python312\python.exe -u tools\chat_reader.py --seconds 300
* The chat window does NOT need to be open. The hook sits on the class-level
  ``ChatMessage:onParseServerData``, which the client runs for every parsed
  message whether or not the chat UI is up, so capture is always-on.
* Capture is LIVE-forward from the moment the hook is installed: it sees new
  messages, not pre-existing backlog.
* Non-ASCII text is carried as hex and decoded here, so Cyrillic/CJK survive.

Output: one JSON record per message to stdout and, if given, appended to --out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import chat_records  # noqa: E402
import lua_client  # noqa: E402

MARKER = chat_records.MARKER

# The recording, the drain and the decoding are shared with the one-off backlog read
# the panel plays (`READ_CHAT`, docs/dsl.md) -- see tools/lib/chat_records.py for why
# they must be one copy. What stays here is what only the LISTENER does: installing the
# class hook, and the polling loop around the drain.
hexdec = chat_records.hexdec
classify_room = chat_records.classify_room

# ---------------------------------------------------------------------------
# Lua side: install idempotent hooks that copy each incoming ChatMessage into
# the global ring buffer _G.__CR_BUF. Fields are hex-encoded so non-ASCII text
# reaches Python intact (LogError mangles raw UTF-8 in Player.log).
# ---------------------------------------------------------------------------
_INSTALL_LUA = chat_records.record_lua() + r"""
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..tostring(s)) end
-- Single class-level ingress hook. ChatMessage:onParseServerData fires exactly
-- once for every parsed message regardless of room / UI routing (world / national
-- / alliance / DM). Bind the class table directly from package.loaded so it works
-- on a fresh session with no captured instance yet -- and, crucially, WITHOUT the
-- chat window open (the client parses the stream whether or not the UI is up).
--
-- We deliberately do NOT also hook the UI-routing handlers
-- (ChatViewTipBubbleDataManager:OnGetNewChatMsg / UpdateOnNewMessage): they fire
-- in addition to onParseServerData for the same message, producing duplicates, and
-- only work while the chat view is open. The single class hook is both sufficient
-- and duplicate-free. Older revisions of this tool DID hook those handlers
-- (originals stashed in _G.__CR_H); if a stale set is still wrapped in this long
-- running game session, restore it so it stops double-recording.
if type(_G.__CR_H) == "table" then
  local mgr = DataCenter.ChatViewTipBubbleDataManager
  for m, orig in pairs(_G.__CR_H) do pcall(function() mgr[m] = orig end) end
  _G.__CR_H = nil
  L("legacy UI hooks restored")
end

local CM = package.loaded["Chat.Model.ChatMessage"]
if type(CM) == "table" and type(CM.onParseServerData) == "function" then
  -- Save the pristine method exactly once, then always rebuild the wrapper from
  -- it. This keeps re-install idempotent AND lets an updated recorder take effect
  -- without a game restart, with no ever-growing wrapper chain. The wrapper calls
  -- `_G.__CR_REC` BY NAME rather than closing over it, so re-running the recorder
  -- chunk alone (which the backlog read does) updates what an already-installed
  -- hook records.
  _G.__CR_ORIG = _G.__CR_ORIG or CM.onParseServerData
  local orig = _G.__CR_ORIG
  CM.onParseServerData = function(self, ...)
    local r = {orig(self, ...)}
    pcall(_G.__CR_REC, self)
    return table.unpack(r)
  end
  _G.__CR_CLASS_HOOKED = true
  L("class-hook on")
else
  L("class-hook FAIL: Chat.Model.ChatMessage type="..type(CM))
end
L("chat_reader hooks installed; buf="..#_G.__CR_BUF)
"""


_DRAIN_LUA = chat_records.drain_lua()


_parse_record_line = chat_records.parse_record_line


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seconds", type=float, default=120,
                    help="how long to capture (0 = until Ctrl+C)")
    ap.add_argument("--interval", type=float, default=5,
                    help="seconds between buffer drains")
    ap.add_argument("--out", metavar="PATH", help="append JSONL here as well as stdout")
    ap.add_argument("--no-open", action="store_true",
                    help="deprecated no-op (the chat window no longer needs to be open)")
    args = ap.parse_args()

    # Chat text is UTF-8 (Cyrillic / Arabic / CJK / emoji). The Windows console
    # defaults to a legacy codepage (e.g. cp1251), so a raw print() of a foreign
    # message raises UnicodeEncodeError and kills the whole capture mid-stream --
    # the classic "nothing shows up" symptom. Force UTF-8 on both streams.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    ev = lua_client.get_evaluator()

    # THE EAR MUST OUTLIVE A BUSY GAME (#2064). The panel holds the client's Lua VM and
    # hands it out one caller at a time, so a scenario in the middle of a run makes this
    # read fail -- and every such failure used to leave the process, because it was one
    # unguarded call. The panel logged «монитор завершён» and stopped recording, which
    # is indistinguishable from a quiet chat. So a failure is a WAIT, never an exit: the
    # hook is (re)installed whenever it is not known to be in, and a drain that raises
    # only costs the seconds until the next one.
    installed = False

    def _install() -> bool:
        """Put the class-level hook in. Idempotent in the game, and safe to retry."""
        try:
            # No need to open the chat window -- onParseServerData fires regardless.
            ev.run(_INSTALL_LUA, marker=MARKER, settle=1.5)
            return True
        except Exception as exc:            # noqa: BLE001 -- a busy VM, not a bug
            print(f"# chat_reader: hook not installed ({exc}); retrying",
                  file=sys.stderr, flush=True)
            return False

    installed = _install()

    print(f"# chat_reader: capturing for {args.seconds or '∞'}s",
          file=sys.stderr, flush=True)

    seen: set[tuple] = set()
    out_fh = open(args.out, "a", encoding="utf-8") if args.out else None
    total = 0
    deadline = time.time() + args.seconds if args.seconds > 0 else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(args.interval)
            if not installed:
                installed = _install()
                if not installed:
                    continue
            try:
                lines = ev.run(_DRAIN_LUA, marker=MARKER, settle=1.2)
            except Exception as exc:        # noqa: BLE001 -- a busy VM, not a bug
                # A read that could not be made is one drain missed, not the end of the
                # recording: the buffer it drains is in the game and keeps filling. A
                # client that went away takes the hook with it, so the next round puts
                # it back before reading again.
                print(f"# chat_reader: drain failed ({exc}); waiting",
                      file=sys.stderr, flush=True)
                installed = False
                continue
            for ln in (lines or []):
                rec = _parse_record_line(ln)
                # Routable? Not an optimistic seqId-less echo of my own send? Both
                # rules live beside the parser, so the backlog read applies the same
                # ones (tools/lib/chat_records.py).
                if not chat_records.usable(rec):
                    continue
                key = chat_records.identity(rec)
                if key in seen:
                    continue
                seen.add(key)
                total += 1
                out = json.dumps(rec, ensure_ascii=False)
                print(out, flush=True)
                if out_fh:
                    out_fh.write(out + "\n")
                    out_fh.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if out_fh:
            out_fh.close()
    print(f"# chat_reader: {total} messages captured", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
