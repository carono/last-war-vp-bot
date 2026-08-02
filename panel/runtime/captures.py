"""The passive captures the panel can run, as data.

One entry per kind the «Секретные задания» monitor offers: the locale key its combo
shows, and the script under ``tools/`` that does the capturing.

This used to be a constant in `panel/__main__.py`, which the secret-task tab could not
import — `python -m panel` runs that file *as* `__main__`, so `from . import __main__`
re-executes the whole module as a second copy. The workaround was to stash the list on
the app instance (`self.capture_options`) and read it from there. Here it is simply
importable, by the tab and by anything else, in either launch mode
(docs/research/panel-tabs-refactor.md §2).
"""
from __future__ import annotations

import os

# `script` is a path relative to tools/ — secret_mission_capture.py lives under
# tools/dev/, so the subdir must travel with the name or the launch FileNotFounds.
CAPTURE_OPTIONS = [
    {"key": "capture.secret_tasks", "script": "secret_task_capture.py"},
    {"key": "capture.ghost_op", "script": os.path.join("dev", "secret_mission_capture.py")},
]

# The one whose findings the auto-loot rule is written against. Handing the ghost-recon
# capture's checkpoint to the secret-task reader is exactly the mix-up worth naming.
SECRET_TASK_CAPTURE = CAPTURE_OPTIONS[0]["script"]
