r"""The remote control's own knobs, from a command line instead of a window (#1976, P3).

    C:\Python312\python.exe -m panel.web_settings                 # what is set now
    C:\Python312\python.exe -m panel.web_settings --on --port 9763
    C:\Python312\python.exe -m panel.web_settings --token new
    C:\Python312\python.exe -m panel.web_settings --address       # the link for a phone

WHY THIS EXISTS, AND WHY IT IS NOT A WEB SCREEN. The panel's own port, host, token and
certificate are a setting of the MACHINE (`panel/runtime/web_control.py`, #1313), and
they are deliberately unreachable from the web itself: they are the door the person came
in through, and managing a door from the far side of it is how somebody locks themselves
out. That divergence has NOT changed and is still pinned by
`tests/test_panel_web_screens.py`.

What changed is the other side of it. Until now the ONLY way to set them was the Tk
dialog (`panel/runtime/web_dialog.py`), and the window is being deleted
(`docs/research/panel-service-and-spa-plan.md`, P3). A knob nobody can reach once the
window is gone is worse than one somebody can get wrong, so the knobs get a way in that
is neither the window nor the door: a command on the machine itself, which is exactly the
kind of access the divergence was protecting them for.

WHEN IT TAKES EFFECT. This writes the setting down; it starts and stops nothing. A panel
that is already up keeps the server it started with until it is restarted («⟳
Перезапустить панель», or `POST /api/panel {"action": "restart"}`) — and a panel that is
not up will read this the next time it starts.

WHAT IT IS NOT. Not the machine's SERVICE (`service.json` at the repo root, the door on
9762 that routes to the panels). That is a different port with a different owner; this is
the panel's own remote control.
"""
from __future__ import annotations

import argparse
import json
import sys

from .runtime import web_control


def _apply(args) -> dict:
    """Turn the flags into the block to store — and store nothing when there are none."""
    values: dict = {}
    if args.on:
        values["enabled"] = True
    if args.off:
        values["enabled"] = False
    if args.port is not None:
        values["port"] = str(args.port)
    if args.host is not None:
        values["host"] = args.host
    if args.cert is not None:
        values["cert"] = args.cert
    if args.key is not None:
        values["key"] = args.key
    if args.token is not None:
        if args.token == "new":
            # `new_token` saves by itself, so the rest of the block travels with it and
            # the file is written once rather than twice.
            values["token"] = web_control.new_token()
        elif args.token == "none":
            values["token"] = ""
        else:
            values["token"] = args.token
    return web_control.save(values) if values else web_control.settings()


def _print(values: dict) -> None:
    """The block as a person reads it. The token is shown because typing it is the point."""
    print(f"enabled : {'on' if values['enabled'] else 'off'}")
    print(f"port    : {web_control.port_number(values)}")
    print(f"host    : {values['host']}")
    print(f"token   : {values['token'] or '(none — anybody who reaches the port is in)'}")
    print(f"cert    : {values['cert'] or '(none — plain http)'}")
    print(f"key     : {values['key'] or '(none)'}")
    print(f"serving : {'yes' if web_control.running() else 'no (this process sees none)'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="panel.web_settings", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--on", action="store_true", help="serve the remote control")
    ap.add_argument("--off", action="store_true", help="do not serve it")
    ap.add_argument("--port", type=int, help="the port to bind (1..65535)")
    ap.add_argument("--host", help="the interface to bind (0.0.0.0 = every one)")
    ap.add_argument("--token", metavar="VALUE",
                    help="a token; `new` generates one, `none` removes it")
    ap.add_argument("--cert", help="path to a TLS certificate, or '' for plain http")
    ap.add_argument("--key", help="path to the certificate's key")
    ap.add_argument("--address", action="store_true",
                    help="print only the link to type into a phone")
    ap.add_argument("--json", action="store_true", help="print the block as JSON")
    args = ap.parse_args(argv)

    if args.on and args.off:
        print("panel: --on and --off are the same knob", file=sys.stderr)
        return 2
    if args.port is not None and not (1 <= args.port <= 65535):
        print(f"panel: {args.port} is not a port", file=sys.stderr)
        return 2

    values = _apply(args)
    if args.address:
        print(web_control.address())
    elif args.json:
        print(json.dumps(values, ensure_ascii=False, indent=2))
    else:
        _print(values)
        print(f"link    : {web_control.address()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
