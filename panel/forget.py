r"""What a RECIPE remembered about an account, read and cleared from a command line (#2390).

    C:\Python312\python.exe -m panel.forget                       # everything remembered
    C:\Python312\python.exe -m panel.forget --profile second
    C:\Python312\python.exe -m panel.forget stamina_refill_block  # clear that one

WHY THIS EXISTS. `REMEMBER` / `RECALL` (docs/dsl.md) let a scenario carry one fact from
one run to the next, and the first of them is a REFUSAL: `actions/buy_stamina_refill.md`
stops buying energy for diamonds the moment a refill costs more than its ceiling, because
the price is not readable anywhere in the client and a re-priced game would otherwise be
paid silently every day (docs/research/march-energy.md).

A refusal nobody can lift is a dead ability, and the panel has no screen for a recipe's
private memory — so the way to lift one is here, on the machine, deliberately. It is
never lifted by a scenario and never by a press: clearing it is a person saying «yes, the
new price is fine», which is exactly the decision the ceiling exists to ask for.

WHEN IT TAKES EFFECT. Immediately — the next run of the recipe reads the row this wrote.
Nothing is restarted, because nothing is cached: `RECALL` reads the database every time.
"""
from __future__ import annotations

import argparse
import sys

from . import profile as profilemod
from .runtime import store as storemod

#: The one row a recipe's `REMEMBER` writes into — see `script_engine._MEMORY_BLOB`.
BLOB = "recipe_memory"


def _held(store) -> dict:
    """Every fact this profile's recipes have remembered — `{}` when none have."""
    held = store.blob_get(BLOB)
    return held if isinstance(held, dict) else {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="panel.forget",
        description="Read or clear what a scenario REMEMBERed about one account.")
    ap.add_argument("key", nargs="?", default="",
                    help="the fact to clear; left out, everything is listed")
    ap.add_argument("--profile", default="default",
                    help="which account's memory (default: default)")
    args = ap.parse_args(argv)

    path = profilemod.os.path.join(profilemod.PROFILES_DIR, storemod.DB_FILE)
    store = storemod.Store(path, args.profile)
    try:
        held = _held(store)
        if not args.key:
            if not held:
                print(f"{args.profile}: nothing remembered")
                return 0
            for key in sorted(held):
                print(f"{args.profile}: {key} = {held[key]}")
            return 0
        if args.key not in held:
            print(f"{args.profile}: {args.key} was not remembered — nothing to clear")
            return 1
        was = held.pop(args.key)
        store.blob_set(BLOB, held)
        print(f"{args.profile}: {args.key} cleared (was {was})")
        return 0
    finally:
        try:
            store.close()
        except Exception:                       # noqa: BLE001 — closing, never the caller
            pass


if __name__ == "__main__":
    sys.exit(main())
