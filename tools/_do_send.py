"""Minimal subprocess helper: build frame and send via dup'd socket.

Runs steal_via_socket.send_via_dup() in a fresh subprocess so that the
per-handle thread pool (_peer / 200ms timeout each) runs without GIL
contention from the 17 capture threads in the parent process.

Usage:
    python _do_send.py <pid> <server_id> <k1> <k2> <inject_id>

Exits 0 on success, 1 on error, 2 if game socket not found.
"""
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)

sys.path.insert(0, os.path.dirname(__file__))
import steal_via_socket as steal

pid        = int(sys.argv[1])
server_id  = int(sys.argv[2])
k1         = int(sys.argv[3])
k2         = int(sys.argv[4])
inject_id  = int(sys.argv[5])

frame = steal.build_test_frame(server_id, k1, k2, inject_id)
rc = steal.send_via_dup(pid, frame)
sys.exit(rc)
