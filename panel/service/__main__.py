"""`python -m panel.service` — see `panel/service/host.py` for what it is."""
from __future__ import annotations

import sys

from .host import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
