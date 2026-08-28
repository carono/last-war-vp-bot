"""A profile's SETTINGS, in that profile's database instead of a JSON file (#2017).

THE PERSON'S DECISION, in their words: «Никаких json, все должно быть в базе». The rule
in `CLAUDE.md` used to say the opposite for settings — a catalogue, a config block and
a table of caps were named there as files a person could open and hand-edit — and that
half of it is what this replaces. Everything else the rule says still holds: a LOG is
appended to and never rewritten, a CHECKPOINT is a channel to a child process and worth
nothing after a restart, and session bookkeeping is the panel's note about itself.
Those stay files, and they are not settings.

WHAT MOVES: the three per-profile settings stores that are ONLY settings — the timer
catalogue, the trigger catalogue and the rally caps. Each becomes one row in that
profile's own `panel.db`, under the name it had.

WHAT DOES NOT, and why each is a QUESTION for the person rather than a decision taken
here:

* `profiles/<name>/config.json` — this profile's tab blocks. It is a settings store AND
  the thing that says a directory IS a profile: the panel lists profiles by looking for
  it, repairs one that has lost it, and refuses to treat a directory without it as an
  account (#1306). Moving the contents into the database would mean redefining what a
  profile is, in the same commit as a storage change, which is not a call to make in
  passing.
* `profiles/settings.json` — panel-wide: which profile is showing, the web block, the
  language, the autostart list. There is no machine-wide database. `panel.db` is per
  profile on purpose («A profile is a whole panel of its own»), so this needs either a
  new machine-wide store or a written exception — and both are agreed with the person
  rather than invented by whoever is in the file.

HOW A PROFILE THAT PREDATES THIS CARRIES ITS SETTINGS ACROSS: exactly once, by the
shared import (`panel/runtime/store.py::blob_import_once`), leaving the old file beside
the database as `<name>.imported`. Never deleted — an import that turns out to have
misread a field is answered by opening the file, and a delete is answered by nothing.

WHERE THE DATABASE IS. Beside the file it replaces: `<the settings file's directory>/
panel.db`, which for a profile's own settings IS that profile's database. A path with no
directory to speak of — a template shipped inside `panel/` — is left alone: the shipped
templates are code, read-only, and belong to the repository rather than to an account.
"""
from __future__ import annotations

import contextlib
import os
import threading

from . import store as storemod

#: The directory names whose files are NOT a profile's settings: the templates that ship
#: with the panel. A template is read (never written) and lives in the source tree, so
#: putting it in a database would put part of the repository inside an account's data.
_CODE_DIRS = ("panel",)

#: NOT CACHED, deliberately. A settings store is read at a boot and at a profile
#: switch and written when somebody moves a knob — a handful of times an hour, against
#: the milliseconds it costs to open a small SQLite file. A kept-open handle, on the
#: other hand, is a file Windows will not let anybody delete, which is a profile that
#: cannot be removed and a temporary directory a test cannot clean up.
_LOCK = threading.Lock()


def blob_name(path: str) -> str:
    """The row one settings file lives in — `settings:<file name without .json>`.

    Prefixed, so a settings store can never collide with the game-data blobs that share
    the table (`secret_tasks_state`, `rally_counts`, …).
    """
    base = os.path.basename(path)
    if base.endswith(".json"):
        base = base[:-len(".json")]
    return "settings:" + base


def _database(path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(path)), "panel.db")


def owned(path: str) -> bool:
    """Is this a file whose contents belong in a database?

    A template inside the source tree is not: it is code. Everything else with a
    directory of its own is a profile's, which is what this module is for.
    """
    folder = os.path.dirname(os.path.abspath(path))
    if not folder:
        return False
    return os.path.basename(folder) not in _CODE_DIRS


@contextlib.contextmanager
def opened(path: str):
    """The database beside `path`, open for one piece of work and closed after it."""
    store = storemod.Store(_database(path))
    try:
        yield store
    finally:
        try:
            store.close()
        except Exception:                     # noqa: BLE001 — closing, never the panel
            pass


def read(path: str, default=None):
    """This settings store's contents — carrying the old file across the first time.

    `None` (or whatever `default` says) means «nothing has ever been saved», which is
    what a brand-new profile answers and what every caller already knew how to seed.

    A READ NEVER CREATES A DATABASE. With neither a database nor a file there is
    nothing to answer with, and opening one would build the whole schema to find that
    out — measured at 29 s across one test that walks a great many empty profiles.
    """
    if not owned(path) or _nothing_there(path):
        return default
    try:
        with _LOCK, opened(path) as store:
            storemod.blob_import_once(store, blob_name(path), path)
            found = store.blob_get(blob_name(path))
    except Exception:                         # noqa: BLE001 — a read, never the panel
        return default
    return default if found is None else found


def write(path: str, value) -> bool:
    """Write this settings store. `False` when it could not be written down."""
    if not owned(path):
        return False
    try:
        with _LOCK, opened(path) as store:
            # An import that has not run yet must not overwrite what was just written
            # the next time it is read, so the mark is settled before the value lands.
            storemod.blob_import_once(store, blob_name(path), path)
            store.blob_set(blob_name(path), value)
    except Exception:                         # noqa: BLE001 — one write, never the panel
        return False
    return True


def _nothing_there(path: str) -> bool:
    """Neither a database nor a file — so there is nothing to read and nothing to
    import, and no reason to build a schema in order to discover it."""
    return not os.path.exists(_database(path)) and not os.path.exists(path)


def exists(path: str) -> bool:
    """Has anything ever been saved here — in the database, or in the file that has
    not been carried across yet?"""
    if not owned(path):
        return os.path.exists(path)
    if os.path.exists(path):
        return True
    if _nothing_there(path):
        return False
    try:
        with _LOCK, opened(path) as store:
            return store.blob_get(blob_name(path)) is not None
    except Exception:                         # noqa: BLE001 — a read, never the panel
        return False
