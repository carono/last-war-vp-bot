r"""Named game instances — "main" and "casper" instead of 47654 and 47655.

One client per Windows session, one Lua daemon per client, one port per daemon
(docs/research/multi-instance-rdp.md). Ports are machine-wide, so every instance is
reachable from every session; what a caller wants is a *name*, not a port number.

    from instance_manager import get_instance, status

    ev = get_instance()            # the client in this session
    ev = get_instance("casper")    # the second account, in its own session
    ev.run("CS.UnityEngine.Debug.LogError('MARK hi')", marker="MARK")

The registry is a two-entry default — `main` (this session, :47654) and `casper`
(:47655) — overridden by ``tools/data/instances.json`` when it exists:

    [{"name": "main", "port": 47654},
     {"name": "casper", "port": 47655, "user": "casper"}]

`user` is the Windows account the instance runs as; it is what `tools/rdp_instance.py`
needs to bring that instance up, and it is empty for the one in this session.
`LW_INSTANCE` names the default instance for a whole process, the way `LW_DAEMON_PORT`
sets a bare port — so an unmodified tool can be pointed at the second account either way.

This module stays dependency-light (it imports `lua_client` and nothing heavy), so it is
safe to import from the panel, from scripts and from `tools/` entrypoints alike.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lua_client  # noqa: E402

REGISTRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             os.pardir, "data", "instances.json")

DEFAULT_INSTANCES = [
    {"name": "main", "port": lua_client.DEFAULT_PORT, "user": ""},
    {"name": "casper", "port": 47655, "user": "casper"},
]


def instances() -> list[dict]:
    """The registry: `tools/data/instances.json` if present, else the default pair."""
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return [dict(i) for i in DEFAULT_INSTANCES]
    if isinstance(data, dict):                     # tolerate {"instances": [...]}
        data = data.get("instances", [])
    out = []
    for i, item in enumerate(data or []):
        if not isinstance(item, dict) or not item.get("name") or not item.get("port"):
            raise SystemExit(f'{REGISTRY_FILE}: entry {i} needs "name" and "port"')
        out.append({"name": item["name"], "port": int(item["port"]),
                    "user": item.get("user", "")})
    return out or [dict(i) for i in DEFAULT_INSTANCES]


def default_name() -> str:
    return os.environ.get("LW_INSTANCE") or "main"


def resolve(name: str | None = None) -> dict:
    """The registry entry for `name` (default: `LW_INSTANCE`, else "main")."""
    name = name or default_name()
    for entry in instances():
        if entry["name"].lower() == name.lower():
            return entry
    known = ", ".join(e["name"] for e in instances())
    raise SystemExit(f"unknown instance {name!r} — known: {known}")


def port_of(name: str | None = None) -> int:
    """`LW_DAEMON_PORT` still wins: an explicit port is an explicit port."""
    if name is None and os.environ.get("LW_DAEMON_PORT"):
        return lua_client.PORT
    return resolve(name)["port"]


def is_up(name: str | None = None) -> bool:
    return lua_client.is_running(port=port_of(name))


def get_instance(name: str | None = None, prefer_daemon: bool = True):
    """An evaluator for one instance — same `.run()/.close()` as `LuaEval`.

    Only the instance of *this* session can fall back to a local `LuaEval`; for any
    other one a dead daemon raises, because a silent fallback would drive the wrong
    client (`lua_client.get_evaluator` enforces that on the port).
    """
    return lua_client.get_evaluator(prefer_daemon=prefer_daemon, port=port_of(name))


def status() -> list[dict]:
    """Every instance with its port, account and whether its daemon answers."""
    out = []
    for entry in instances():
        state = {"ok": False}
        try:
            state = lua_client.DaemonClient(port=entry["port"], timeout=5)._rpc(
                {"op": "ping"})
        except OSError:
            pass
        out.append({**entry, "up": bool(state.get("ok")),
                    "warm": bool(state.get("warm")), "pid": state.get("pid")})
    return out


def main() -> int:
    for i in status():
        mark = "warm" if i["warm"] else "up (cold)" if i["up"] else "down"
        who = i["user"] or "this session"
        print(f"  {i['name']:<10} :{i['port']}  {who:<14} {mark}"
              + (f"  pid {i['pid']}" if i.get("pid") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
