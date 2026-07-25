"""Диагностика: убедиться что scapy (iface=None) видит upstream _id.

Запуск (Windows Python, без инжекта):
    /mnt/c/Python312/python.exe tools/_diag_sniff_id.py

Слушает :17935 30 секунд и выводит все upstream _id, которые найдёт.
"""
from __future__ import annotations
import os, sys, time, threading
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, "tools/lib")
    sys.path.insert(0, str(TOOLS))

GAME_PORT = 17935

import lastwar_proto as proto
from scapy.layers.inet import IP, TCP
from scapy.layers.l2 import Ether
from scapy.sendrecv import sniff

import psutil
conn = None
for c in psutil.net_connections(kind="tcp"):
    if c.raddr and c.raddr.port == GAME_PORT and c.status == "ESTABLISHED":
        conn = c
        break

if not conn:
    print(f"[diag] ERROR: no :{GAME_PORT} ESTABLISHED — is the game running?")
    sys.exit(1)

local_ip  = conn.laddr.ip
local_port= conn.laddr.port
server_ip = conn.raddr.ip
print(f"[diag] game TCP  {local_ip}:{local_port} -> {server_ip}:{GAME_PORT}")
print(f"[diag] sniffing with scapy iface=None for 30 s …")
print(f"[diag] (прокрути карту мира или открой меню, чтобы появились upstream RPC)")

found: list[int] = []
up_raw = 0
stop = threading.Event()

def _feed(pkt):
    global up_raw
    if not pkt.haslayer(IP):
        try:
            pkt = Ether(bytes(pkt))
        except Exception:
            return
    if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
        return
    ip, tcp = pkt[IP], pkt[TCP]
    payload_len = len(bytes(tcp.payload))
    if payload_len == 0:
        return
    # Upstream: local -> server
    if (ip.src == local_ip and tcp.sport == local_port
            and ip.dst == server_ip and tcp.dport == GAME_PORT):
        up_raw += 1
        raw = bytes(tcp.payload)
        try:
            for env, fstart, fend in proto.iter_frames(raw, "up"):
                ep = proto.envelope_payload(env)
                if not isinstance(ep, dict):
                    continue
                rid = ep.get("_id")
                cmd = proto.envelope_command(env) or "(keepalive)"
                if isinstance(rid, int):
                    found.append(rid)
                    print(f"[diag] upstream  _id={rid}  cmd={cmd}", flush=True)
        except Exception as exc:
            print(f"[diag] decode error: {exc}", flush=True)


def _sniff():
    try:
        sniff(filter=f"tcp port {GAME_PORT}", iface=None, prn=_feed,
              store=False, stop_filter=lambda _: stop.is_set())
    except Exception as exc:
        print(f"[diag] sniff error: {exc}", flush=True)

t = threading.Thread(target=_sniff, daemon=True)
t.start()

deadline = time.time() + 30.0
while time.time() < deadline:
    time.sleep(1.0)
    remaining = int(deadline - time.time())
    if found:
        print(f"[diag] {len(found)} upstream _id found so far, max={max(found)}  "
              f"up_raw={up_raw}  {remaining}s remaining", flush=True)

stop.set()
time.sleep(0.5)

print()
if found:
    print(f"[diag] SUCCESS  found {len(found)} upstream frames with _id")
    print(f"[diag] max _id = {max(found)}  (inject would use {max(found)+1})")
else:
    print(f"[diag] FAIL  no upstream _id found in 30 s  (up_raw={up_raw})")
    print("[diag] Попробуй: прокрути карту мира, или открой Events/Alliance")
