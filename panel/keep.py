r"""What this machine keeps a panel open for, from a command line (#2068).

    C:\Python312\python.exe -m panel.keep                    # what is wanted now
    C:\Python312\python.exe -m panel.keep --set default
    C:\Python312\python.exe -m panel.keep --add second --drop test
    C:\Python312\python.exe -m panel.keep --clear            # back to «whatever was open»

WHAT THE SETTING IS. The service keeps one panel up per profile this machine wants farmed
(`panel/service/keeper.py`). It used to ask that of `open_profiles` — the record every
panel process rewrites on every open, close and switch — so a panel somebody started for
ten minutes to look at two test accounts became the machine's boot list, and the service
then put those accounts back five seconds after every attempt to quit them. «What was
open last» and «what this machine wants farmed» are two questions; this is the second.

WHO NORMALLY WRITES IT. A person opening or closing a profile on purpose, in either
front-end (`panel/runtime/profile_control.py`). This command exists for the other case:
reading it, and repairing it when the drift already happened — the same machine-side door
`python -m panel.web_settings` is for the remote control's own knobs.

WHEN IT TAKES EFFECT. On the service's next look, within seconds. Nothing here starts or
stops a panel: `--drop` says «stop bringing it back», it does not put down the one that
is up (`POST /api/panels {"action": "quit", "pid": N}` on the service door does that).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import profile as profilemod


def _show(as_json: bool) -> int:
    said = profilemod.keep_profiles()
    manager = profilemod.ProfileManager()
    effective = profilemod.keep_or_last_open()
    if as_json:
        print(json.dumps({"keep": said, "effective": effective,
                          "open_profiles": manager.open_profiles(),
                          "decided": said is not None}, ensure_ascii=False, indent=2))
        return 0
    if said is None:
        print("keep: not decided — falling back to what was last open: "
              + (", ".join(effective) or "(nothing)"))
    else:
        print("keep: " + (", ".join(said) or "(nothing)"))
    print("last open: " + (", ".join(manager.open_profiles()) or "(nothing)"))
    missing = [n for n in effective if not manager.exists(n)]
    if missing:
        print("no such profile: " + ", ".join(missing))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="panel.keep", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", metavar="NAME", action="append", default=[],
                    help="the whole list, replacing what is there (repeatable)")
    ap.add_argument("--add", metavar="NAME", action="append", default=[],
                    help="want this profile too (repeatable)")
    ap.add_argument("--drop", metavar="NAME", action="append", default=[],
                    help="stop wanting this profile (repeatable)")
    ap.add_argument("--clear", action="store_true",
                    help="undecide it: fall back to whatever was last open")
    ap.add_argument("--json", action="store_true", help="print the answer as JSON")
    args = ap.parse_args(argv)

    if args.clear:
        data = profilemod.ProfileManager._read_settings()
        if profilemod.KEEP_KEY in data:
            data.pop(profilemod.KEEP_KEY)
            profilemod.set_panel_settings(data)
    elif args.set:
        profilemod.set_keep_profiles(args.set)
    for name in args.add:
        profilemod.keep_add(name)
    for name in args.drop:
        profilemod.keep_drop(name)
    return _show(args.json)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
