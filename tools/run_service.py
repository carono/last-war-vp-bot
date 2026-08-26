r"""Start the panel's service from a path — what a Windows service registration points at.

A service is started by the Service Control Manager with the system directory as its
working directory and no `PYTHONPATH` of its own, so `-m panel.service` finds nothing:
the repository is not on `sys.path` and `sc` has nowhere to say that it should be. This
file is the answer, and it is deliberately three lines of work: put the repository this
file lives in on the path, and hand over to the service's own `main`.

    "<pythonw>" "<repo>\tools\run_service.py"

WHICH REPOSITORY is the one this file is IN — never a path written down anywhere. The
installer (`service_install.bat`) expands it from its own location at install time, so
the registration names the machine it was made on and the repository names nobody.

Runs in the foreground when started by hand, which is what `service.bat` does; under the
SCM it is `pythonw.exe`, so there is no console and the log is the service's own.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from panel.service.host import main   # noqa: E402  — after the path above

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
