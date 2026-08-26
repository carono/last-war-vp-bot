"""The service process: the door for panels, the port for people, and nothing else.

    C:\\Python312\\python.exe -m panel.service            # run it in the foreground
    C:\\Python312\\python.exe -m panel.service --status   # is one already up?

WHAT IT IS. `panel/web/server.py` already serves the whole API and the SPA off an object
that answers `dispatch(method, path, query, body)`; `panel/service/api.py::ServiceApi` is
such an object that forwards to a connected panel. So this file is the assembly and the
configuration, and there is no second copy of a single route.

WHAT IT IS NOT. It starts no panel, watches none and kills none — see the package
docstring. A machine with no panel running answers «no_panel» to everything that needs
one, which is a state the page can draw rather than a failure it has to guess at.

THE CONFIGURATION IS THE MACHINE'S, not a profile's: one port, one token, one certificate,
in `profiles/service.json` beside the panel-wide `settings.json` that already holds the
window's own web block. Environment variables win over the file, exactly as everywhere
else in this repository (`CLAUDE.md`, «Nothing about one machine is written into the
code»), so a machine that is not ordinary sets a variable rather than editing code.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time

from ..runtime import paths
# THE REPO'S OWN DIRECTORIES FIRST. `panel/web/api.py` imports the bare-name modules that
# live in `tools/lib` (`profile_health` and its neighbours), and the panel puts them on
# `sys.path` while it boots — a service that never opens a window has to do it itself.
paths.ensure()

from ..web import server as webmod   # noqa: E402 — after the paths above
from .api import ServiceApi
from .door import DEFAULT_DOOR_PORT, DOOR_HOST, Door
from .keeper import Keeper
from .registry import Registry

#: Where the machine's own service settings live: `service.json` in the repository root.
#:
#: NOT UNDER `profiles/`, which is the panel's working area — a directory several panel
#: processes list, write and tidy, and one this file has no business leaving something in.
#: The service belongs to the MACHINE, not to an account, so it sits beside the code it
#: runs, exactly as `.env` does for the tools.
CONFIG_NAME = "service.json"

#: The environment's say in it, for a machine that is not ordinary.
ENV = {"port": "LW_SERVICE_WEB_PORT", "door": "LW_SERVICE_PORT",
       "host": "LW_SERVICE_WEB_HOST", "token": "LW_SERVICE_TOKEN",
       "certfile": "LW_SERVICE_CERT", "keyfile": "LW_SERVICE_KEY"}

#: The same for the `keep` block — whether this service OWNS the panels, which profiles,
#: and which Windows session to start them in (`panel/service/keeper.py`).
KEEP_ENV = {"enabled": "LW_SERVICE_KEEP", "profiles": "LW_SERVICE_KEEP_PROFILES",
            "session": "LW_SERVICE_KEEP_SESSION"}


def config_path() -> str:
    """The settings file — `LW_SERVICE_CONFIG` first, then the repository's own root."""
    said = (os.environ.get("LW_SERVICE_CONFIG") or "").strip()
    return said or os.path.join(paths.REPO, CONFIG_NAME)


def load_config() -> dict:
    """The service's settings: the file, then the environment on top of it.

    A missing file is not an error and not a prompt: the defaults are «the port this
    machine's panels already use, a token made once and written down». The token is the
    one value that is GENERATED rather than defaulted — a service with a blank token
    would be a door with no lock, and `WebServer` refuses to start without one anyway.
    """
    values = {}
    try:
        with open(config_path(), encoding="utf-8") as fh:
            values = json.load(fh) or {}
    except (OSError, ValueError):
        values = {}
    for key, env in ENV.items():
        said = (os.environ.get(env) or "").strip()
        if said:
            values[key] = said
    values.setdefault("port", webmod.default_port())
    values.setdefault("door", DEFAULT_DOOR_PORT)
    values.setdefault("host", webmod.DEFAULT_HOST)
    values.setdefault("certfile", "")
    values.setdefault("keyfile", "")
    values["keep"] = _keep_block(values.get("keep"))
    if not str(values.get("token") or "").strip():
        values["token"] = secrets.token_urlsafe(9)
        save_config(values)
    return values


def _keep_block(said) -> dict:
    """The `keep` block: the file, then the environment on top of it.

    A machine that is not ordinary sets a variable rather than editing the file, exactly
    as it does for the ports — `LW_SERVICE_KEEP=0` is «be a door and nothing more».
    """
    from . import keeper

    block = dict(keeper.DEFAULTS)
    if isinstance(said, dict):
        block.update({k: v for k, v in said.items() if v is not None})
    on = (os.environ.get(KEEP_ENV["enabled"]) or "").strip().lower()
    if on:
        block["enabled"] = on not in ("0", "no", "off", "false")
    names = (os.environ.get(KEEP_ENV["profiles"]) or "").strip()
    if names:
        block["profiles"] = [part.strip() for part in names.split(",") if part.strip()]
    where = (os.environ.get(KEEP_ENV["session"]) or "").strip()
    if where:
        try:
            block["session"] = int(where)
        except ValueError:
            pass
    return block


def save_config(values: dict) -> None:
    """Write the settings back — used when a token had to be made."""
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(values, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass                        # a service that cannot write its token still runs


class _Shim:
    """The three things `WebServer` asks of a runtime, and no more.

    The panel's own server is handed a `PanelRuntime` and uses it for two lines in the
    log and for the name of the profile it belongs to. The service belongs to no profile
    and has no profile's log, so it says its own lines to stdout — which is what a
    service's log is, whether it is read by the Event Log, by a redirect or by a person
    running it in a window.
    """

    def __init__(self, log) -> None:
        self.log = type("_Log", (), {"put": staticmethod(log)})()
        self.profiles = type("_P", (), {"active": ""})()

    def say(self, tag: str, key: str, **fmt) -> None:
        said = " ".join(f"{k}={v}" for k, v in sorted(fmt.items()))
        self.log.put(f"[{tag}] {key}{' ' + said if said else ''}")

    def t(self, key: str, **fmt) -> str:
        return key


class Service:
    """Door + web server + the register between them."""

    def __init__(self, config: dict, log=None) -> None:
        self.config = dict(config or {})
        self._log = log or (lambda line: print(line, flush=True))
        self.registry = Registry()
        # `0` IS A PORT — the one that says «whatever the operating system has free», and
        # what the tests bind. So it is kept as itself and only a MISSING value falls back
        # to the machine's own number; `or` would have turned every test's ephemeral port
        # into the live panel's.
        door_port = self.config.get("door")
        web_port = self.config.get("port")
        #: Set by `main` for a service running in the FOREGROUND, so that
        #: `service.bat --stop` can put it down from anywhere on the machine. A service
        #: started by Windows is stopped by Windows and leaves this alone.
        self.on_shutdown = None
        self.door = Door(self.registry,
                         port=(DEFAULT_DOOR_PORT if door_port in (None, "")
                               else int(door_port)),
                         log=self._log,
                         on_shutdown=lambda: (self.on_shutdown or (lambda: None))())
        self.web = webmod.WebServer(
            _Shim(self._log),
            host=str(self.config.get("host") or webmod.DEFAULT_HOST),
            port=(webmod.default_port() if web_port in (None, "") else int(web_port)),
            token=str(self.config.get("token") or ""),
            api=ServiceApi(self.registry, log=self._log),
            certfile=str(self.config.get("certfile") or ""),
            keyfile=str(self.config.get("keyfile") or ""))
        self._pinger = None
        self._stop = threading.Event()
        #: THE OWNER of the panels (#1976). «Центр правды — это служба»: the machine has
        #: one thing to bring up, and the panels are its doing rather than a person's.
        self.keeper = Keeper(self.registry, self.config, log=self._log)

    def start(self) -> None:
        self.door.start()
        self.web.start()
        self._log(f"service: {self.web.scheme}://{self.web.host}:{self.web.port} "
                  f"(panels dial {DOOR_HOST}:{self.door.port})")
        self._pinger = threading.Thread(target=self._ping, name="service-ping",
                                        daemon=True)
        self._pinger.start()
        self.keeper.start()

    def stop(self) -> None:
        self._stop.set()
        # THE PANELS FIRST, and through their own sockets — which is why this happens
        # before the door is closed: «Заглушить» travels the same way every other press
        # does, and a killed panel leaves locks, children and a client nobody let go of.
        try:
            self.keeper.stop()
        except Exception:                     # noqa: BLE001 — going away anyway
            pass
        try:
            self.web.stop()
        except Exception:                     # noqa: BLE001 — going away anyway
            pass
        self.door.stop()

    def _ping(self) -> None:
        """Prove each panel is still there. A sleeping machine leaves an open socket."""
        from . import wire

        while not self._stop.wait(wire.PING_SEC):
            for panel in self.registry.all():
                if not panel.ping():
                    self.registry.remove(panel)


def status(config: dict) -> dict:
    """Is a service already answering on this machine's ports? For `--status`."""
    out = {"web": False, "door": False, "port": int(config.get("port") or 0),
           "door_port": int(config.get("door") or 0)}
    for key, port in (("web", out["port"]), ("door", out["door_port"])):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                out[key] = True
        except OSError:
            pass
    return out


def ask_to_stop(config: dict, *, timeout: float = 30.0) -> bool:
    """Tell a running service to put itself down — the door's own `shutdown` frame.

    For a service started by hand. One started by Windows is stopped by Windows
    (`sc stop`), which runs the same shutdown through the SCM's control handler.
    """
    port = int(config.get("door") or DEFAULT_DOOR_PORT)
    try:
        with socket.create_connection((DOOR_HOST, port), timeout=5) as sock:
            sock.sendall(json.dumps({"shutdown": 1}).encode() + b"\n")
            sock.settimeout(5)
            try:
                sock.recv(256)
            except OSError:
                pass
    except OSError as exc:
        print(f"service: nothing is answering on {DOOR_HOST}:{port} ({exc})",
              file=sys.stderr)
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((DOOR_HOST, port), timeout=1):
                pass
        except OSError:
            print("service: stopped")
            return True
        time.sleep(0.5)
    print("service: it was asked, and it is still up", file=sys.stderr)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="panel.service", description=__doc__)
    ap.add_argument("--status", action="store_true",
                    help="say whether a service is already answering, and exit")
    ap.add_argument("--stop", action="store_true",
                    help="ask the service that is running on this machine to stop")
    args = ap.parse_args(argv)
    config = load_config()
    if args.stop:
        return 0 if ask_to_stop(config) else 1
    if args.status:
        said = status(config)
        print(json.dumps(said, ensure_ascii=False))
        return 0 if said["web"] and said["door"] else 1
    service = Service(config)
    service.on_shutdown = service.stop
    try:
        service.start()
    except OSError as exc:
        print(f"service: cannot start — {exc}", file=sys.stderr)
        return 1
    try:
        while not service._stop.wait(1.0):    # noqa: SLF001 — its own module
            pass
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
    return 0
