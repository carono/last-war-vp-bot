#!/usr/bin/env python3
"""Monitor Last War chat messages from live TCP traffic.

Only the plain-TCP leg of the game connection decodes passively. The live
broadcast firehose (world/alliance chat) rides a dedicated TLS WebSocket and
is not accessible without a TLS keylog. What this monitor captures:

  - push.chat                        rare push on the TCP leg (chat gifts)
  - lw.user.push.chat.msg + chat.stat  direct message you send
  - common.chat.room.id              room registry at login
  - chat.room.send / hero.dispatch.share.chat  map-object shares into chat

Output: one JSON line per message to stdout AND the --out file.

    C:\\Python312\\python.exe -u tools\\chat_monitor.py
    C:\\Python312\\python.exe -u tools\\chat_monitor.py --out results\\chat.jsonl
    C:\\Python312\\python.exe -u tools\\chat_monitor.py --seconds 300

roomId prefixes and their chat_type:
    country_<server>              -> world
    custom_lang_<lang>_<server>   -> national
    alliance_<id>_<allianceId>    -> alliance
    custom_<uid1>_<uid2>_v2       -> dm
    (anything else)               -> other
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
sys.path.insert(0, _HERE)

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_OK, C_RESET, LiveDecoder  # noqa: E402
from map_capture import add_capture_arguments, check_platform, start_capture  # noqa: E402

CHAT_COMMANDS = frozenset({
    "push.chat",
    "lw.user.push.chat.msg",
    "chat.stat",
    "common.chat.room.id",
    "chat.room.send",
    "hero.dispatch.share.chat",
})

# Substrings present in every chat-related command name; used as a fast pre-filter
# before checking the full CHAT_COMMANDS set (avoids full string membership test on
# every decoded frame from non-chat traffic).
_CHAT_KEYWORDS = ("chat", "lw.user.push")


def classify_room(room_id: str) -> str:
    """Map a roomId string to one of the five UI chat types."""
    if not room_id:
        return "other"
    if room_id.startswith("country_"):
        return "world"
    if room_id.startswith("custom_lang_"):
        return "national"
    if room_id.startswith("alliance_"):
        return "alliance"
    if room_id.endswith("_v2"):
        return "dm"
    return "other"


def extract_chat_record(command: str, payload: dict) -> dict | None:
    """Build a normalised chat record from one decoded frame.

    Returns None for frames that carry no user-facing text (keepalives,
    frames with an empty msg, or commands we have no extractor for).
    """
    if not isinstance(payload, dict):
        return None

    record: dict = {
        "ts": time.time(),
        "command": command,
        "room_id": "",
        "chat_type": "other",
        "sender_uid": "",
        "sender_name": "",
        "alliance": "",
        "msg": "",
    }

    if command == "push.chat":
        record["sender_uid"] = str(payload.get("senderUid", ""))
        record["sender_name"] = payload.get("senderName", "") or ""
        record["msg"] = payload.get("msg", "") or ""
        record["room_id"] = payload.get("roomId", "") or ""
        # customJsonParam is a nested JSON string with the sender's alliance info
        cpj = payload.get("customJsonParam")
        if isinstance(cpj, str):
            try:
                cpj = json.loads(cpj)
            except Exception:
                cpj = {}
        if isinstance(cpj, dict):
            record["alliance"] = (
                cpj.get("abbr") or cpj.get("allianceAbbr") or ""
            )
        if not record["msg"]:
            return None

    elif command == "lw.user.push.chat.msg":
        record["msg"] = payload.get("msg", "") or ""
        record["room_id"] = payload.get("roomId", "") or ""
        record["sender_name"] = "[me]"
        if not record["msg"]:
            return None

    elif command == "chat.stat":
        record["msg"] = payload.get("msg", "") or ""
        record["room_id"] = payload.get("roomId", "") or ""
        extra = payload.get("msgExtra")
        if isinstance(extra, dict):
            record["sender_name"] = extra.get("senderName", "") or ""
        if not record["msg"]:
            return None

    elif command == "common.chat.room.id":
        rooms = payload.get("roomId")
        if isinstance(rooms, list):
            record["msg"] = "rooms: " + ", ".join(str(r) for r in rooms[:10])
        elif rooms:
            record["msg"] = f"room: {rooms}"
        else:
            return None
        record["chat_type"] = "system"

    elif command in ("chat.room.send", "hero.dispatch.share.chat"):
        record["room_id"] = payload.get("roomId", "") or ""
        attach = payload.get("attachmentId") or ""
        record["msg"] = f"[share] {str(attach)[:200]}" if attach else f"[{command}]"

    else:
        return None

    if record["chat_type"] == "other":
        record["chat_type"] = classify_room(record["room_id"])

    return record


class ChatMonitor(LiveDecoder):
    """LiveDecoder subclass that extracts and records chat messages."""

    def __init__(self, out_path: str | None = None) -> None:
        super().__init__()
        self.out_path = out_path
        self._out_lock = threading.Lock()
        self.chat_count = 0

    def emit(self, direction: str, env) -> None:
        command = proto.envelope_command(env) or ""
        # Fast path: skip frames with no chat keyword in the command name.
        if not any(kw in command for kw in _CHAT_KEYWORDS):
            return
        if command not in CHAT_COMMANDS:
            return

        payload = proto.envelope_payload(env) or {}
        record = extract_chat_record(command, payload)
        if record is None:
            return

        self.chat_count += 1
        line = json.dumps(record, ensure_ascii=False)
        print(line, flush=True)

        if self.out_path:
            with self._out_lock:
                try:
                    with open(self.out_path, "a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                except OSError:
                    pass

    def report(self) -> None:
        super().report()
        print(f"chat messages captured: {self.chat_count}")


def main() -> int:
    check_platform()
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_capture_arguments(ap)
    ap.add_argument("--out", metavar="PATH",
                    help="JSONL output file (appended; stdout is always written too)")
    ap.add_argument("--seconds", type=float, default=0,
                    help="stop after this many seconds (0 = run until Ctrl+C)")
    args = ap.parse_args()

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    monitor = ChatMonitor(out_path=args.out)

    print(f"{C_OK}chat monitor started{C_RESET} — only plain-TCP chat decodes passively;",
          file=sys.stderr)
    print(f"{C_DIM}world/alliance broadcast rides TLS WSS and is not captured here{C_RESET}",
          file=sys.stderr)
    if args.out:
        print(f"{C_DIM}writing to: {args.out}{C_RESET}", file=sys.stderr)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if args.seconds > 0:
        threading.Timer(args.seconds, stop.set).start()

    start_capture(monitor, args, stop)
    monitor.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
