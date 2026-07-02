"""mitmproxy addon for capturing and decoding Last War traffic.

Run it with mitmproxy/mitmdump/mitmweb:

    mitmdump -s tools/lastwar_mitm_addon.py
    mitmweb  -s tools/lastwar_mitm_addon.py --listen-port 8080

What it does per flow:
  * appends a structured record to  results/traffic_<timestamp>.jsonl
  * dumps raw request/response bodies to  results/raw/<flow_id>.{req,resp}.bin
  * tries to decode bodies as Protobuf (via blackboxprotobuf) when the
    Content-Type says protobuf OR the first bytes look like a protobuf message
  * prints a compact colourised summary to the console

Optional filtering — only record hosts matching a substring, to avoid logging
unrelated OS/browser traffic:

    LASTWAR_HOST_FILTER=lastwar mitmdump -s tools/lastwar_mitm_addon.py

The output timestamp is fixed once at addon load, so a whole session lands in a
single traffic_<ts>.jsonl file.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from mitmproxy import ctx, http

try:
    import blackboxprotobuf  # type: ignore
except Exception:  # pragma: no cover - optional dep
    blackboxprotobuf = None


# --- paths -----------------------------------------------------------------
# addon file lives in <repo>/tools/, results live in <repo>/results/
REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "results"
RAW = RESULTS / "raw"


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# A protobuf message starts with a tag byte = (field_number << 3) | wire_type.
# Real messages almost always open with a low field number (1..8) using either
# wire-type 2 (length-delimited: strings/sub-messages) or wire-type 0 (varint:
# ints/enums/opcodes). We accept both so a frame that opens with e.g. an opcode
# varint (0x08 = field1/type0) is still attempted — blackboxprotobuf validates
# the parse, so a false positive just fails harmlessly.
#   wire-type 2: 0x0A 0x12 0x1A 0x22 0x2A 0x32 0x3A 0x42  (field 1..8)
#   wire-type 0: 0x08 0x10 0x18 0x20 0x28 0x30 0x38 0x40  (field 1..8)
_PROTOBUF_MAGIC = {
    0x0A, 0x12, 0x1A, 0x22, 0x2A, 0x32, 0x3A, 0x42,
    0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40,
}


def looks_like_protobuf(body: bytes, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if "protobuf" in ct or "application/x-protobuf" in ct or "grpc" in ct:
        return True
    if "json" in ct or "text" in ct or "html" in ct or "image" in ct:
        return False
    if not body:
        return False
    return body[0] in _PROTOBUF_MAGIC


def try_decode_protobuf(body: bytes):
    """Return (decoded_dict, typedef) or (None, None)."""
    if not body or blackboxprotobuf is None:
        return None, None
    try:
        message, typedef = blackboxprotobuf.decode_message(body)
        return message, typedef
    except Exception:
        return None, None


class LastWarCapture:
    def __init__(self) -> None:
        RAW.mkdir(parents=True, exist_ok=True)
        self.tag = _now_tag()
        self.jsonl_path = RESULTS / f"traffic_{self.tag}.jsonl"
        self.host_filter = os.environ.get("LASTWAR_HOST_FILTER", "").lower()
        self.count = 0

    def load(self, loader):  # noqa: ARG002 - mitmproxy hook signature
        ctx.log.info(f"[lastwar] logging to {self.jsonl_path}")
        if blackboxprotobuf is None:
            ctx.log.warn("[lastwar] blackboxprotobuf not installed — protobuf decode disabled")
        if self.host_filter:
            ctx.log.info(f"[lastwar] host filter: '{self.host_filter}'")

    # --- helpers -----------------------------------------------------------
    def _wanted(self, flow: http.HTTPFlow) -> bool:
        if not self.host_filter:
            return True
        return self.host_filter in flow.request.pretty_host.lower()

    def _dump_raw(self, flow_id: str, suffix: str, body: bytes) -> str | None:
        if not body:
            return None
        path = RAW / f"{flow_id}.{suffix}.bin"
        path.write_bytes(body)
        return str(path.relative_to(REPO_ROOT))

    def _decode_side(self, body: bytes, content_type: str) -> dict:
        info: dict = {
            "len": len(body) if body else 0,
            "is_protobuf": False,
            "protobuf": None,
        }
        if looks_like_protobuf(body, content_type):
            decoded, typedef = try_decode_protobuf(body)
            if decoded is not None:
                info["is_protobuf"] = True
                # blackboxprotobuf returns bytes values that are not JSON-serialisable
                info["protobuf"] = json.loads(
                    json.dumps({"message": decoded, "typedef": typedef}, default=_json_default)
                )
        return info

    # --- mitmproxy hook ----------------------------------------------------
    def response(self, flow: http.HTTPFlow) -> None:
        if not self._wanted(flow):
            return

        self.count += 1
        fid = flow.id[:12]
        req_body = flow.request.raw_content or b""
        resp_body = flow.response.raw_content or b"" if flow.response else b""

        req_ct = flow.request.headers.get("content-type", "")
        resp_ct = flow.response.headers.get("content-type", "") if flow.response else ""

        raw_req = self._dump_raw(fid, "req", req_body)
        raw_resp = self._dump_raw(fid, "resp", resp_body)

        req_info = self._decode_side(req_body, req_ct)
        resp_info = self._decode_side(resp_body, resp_ct)

        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "flow_id": fid,
            "scheme": flow.request.scheme,
            "method": flow.request.method,
            "host": flow.request.pretty_host,
            "port": flow.request.port,
            "path": flow.request.path,
            "status": flow.response.status_code if flow.response else None,
            "request": {"content_type": req_ct, "raw": raw_req, **req_info},
            "response": {"content_type": resp_ct, "raw": raw_resp, **resp_info},
        }

        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._print_summary(record)

    def websocket_message(self, flow) -> None:
        """Log individual WebSocket frames (many games use wss for gameplay)."""
        if not self._wanted(flow):
            return
        msg = flow.websocket.messages[-1]
        body = bytes(msg.content)
        fid = flow.id[:12]
        direction = "→srv" if msg.from_client else "←srv"
        info = self._decode_side(body, "application/octet-stream")
        raw = self._dump_raw(f"{fid}_ws{len(flow.websocket.messages)}", direction.strip("→←"), body)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "flow_id": fid,
            "kind": "websocket",
            "host": flow.request.pretty_host,
            "direction": direction,
            "raw": raw,
            **info,
        }
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        pb = " [protobuf]" if info["is_protobuf"] else ""
        ctx.log.info(f"[lastwar] WS {direction} {flow.request.pretty_host} {info['len']}B{pb}")

    # --- console -----------------------------------------------------------
    def _print_summary(self, r: dict) -> None:
        req_pb = " [pb]" if r["request"]["is_protobuf"] else ""
        resp_pb = " [pb]" if r["response"]["is_protobuf"] else ""
        line = (
            f"[lastwar] #{self.count:04d} {r['method']:6s} "
            f"{r['status']} {r['host']}:{r['port']}{r['path'][:60]}  "
            f"req={r['request']['len']}B{req_pb} resp={r['response']['len']}B{resp_pb}"
        )
        ctx.log.info(line)

    def done(self) -> None:
        ctx.log.info(f"[lastwar] captured {self.count} flows -> {self.jsonl_path}")


def _json_default(o):
    if isinstance(o, bytes):
        # keep it readable: try utf-8, else hex
        try:
            return o.decode("utf-8")
        except UnicodeDecodeError:
            return {"__bytes_hex__": o.hex()}
    return str(o)


addons = [LastWarCapture()]
