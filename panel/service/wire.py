"""The frame a panel and the service speak in: one JSON object per line.

Small on purpose. There is no library here and there is not going to be one: the whole
conversation is «here is a request, here is its answer», both sides are on this machine,
and the payloads are the same dictionaries `panel/web/api.py` already builds.

    panel  → service   {"hello": {"session": "…", "pid": 1234, "profiles": [...]}}
    service → panel    {"id": 7, "method": "GET", "path": "/api/state",
                        "query": {...}, "body": {...}}
    panel  → service   {"id": 7, "status": 200, "payload": {...}}
    either →           {"ping": 1} / {"pong": 1}

LINE-DELIMITED JSON, not a length prefix: every value here is a dictionary that JSON has
no way of spelling with a raw newline in it, the frames are small, and a protocol a person
can read with `nc` is a protocol a person can debug at three in the morning. The one thing
the reader must not do is trust the length — :data:`MAX_LINE` is what stops a wedged
sender from eating the service's memory.
"""
from __future__ import annotations

import json

#: How long one frame may be. A screen with a hundred rows is tens of kilobytes; a
#: megabyte is either a bug or somebody who found the port.
MAX_LINE = 4 * 1024 * 1024

#: How long the service waits for a panel to answer one request. Longer than any read the
#: API makes on its own (`web_view` is contracted to touch no game) and shorter than a
#: person's patience: a panel that has not answered in this long is a panel to say so
#: about rather than to keep a browser hanging on.
ANSWER_TIMEOUT_SEC = 20.0

#: How often each side proves it is still there. The panel dials out, so a dead service
#: is noticed by the panel's own read failing; this is for the other direction — a panel
#: whose machine went to sleep leaves a socket that looks perfectly open.
PING_SEC = 20.0


def dumps(frame: dict) -> bytes:
    """One frame, ready for the socket."""
    return (json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def reader(sock):
    """Yield frames off ``sock`` until it closes. Never raises on a bad frame.

    A line that is not JSON, or is longer than :data:`MAX_LINE`, ends the conversation:
    both mean the thing on the other end is not what this protocol expects, and carrying
    on with a half-read buffer is how a router starts answering the wrong request.
    """
    buf = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        if len(buf) > MAX_LINE:
            return
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            if not isinstance(frame, dict):
                return
            yield frame
