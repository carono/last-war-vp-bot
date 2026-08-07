"""Tiny i18n helper for the control panel.

UI strings live in ``panel/locales/<lang>.json`` (flat ``key -> template`` maps), and/or
in ``panel/locales/<lang>/<tab>.json`` — one tab's keys on their own, merged into the
same table at load (see :func:`load_locale`; a split by tab is what stops two agents
adding two keys from colliding in eleven files, #1282).
Look a string up with :func:`I18n.t`; ``{name}``-style placeholders are filled via
``str.format``. Missing keys fall back to the default language, then to the key
itself, so a half-translated locale never crashes the UI.

A LANGUAGE IS A FILE, and nothing else. The list is the contents of the locales
directory — the code stem comes from the file name, the name to show in the Language
menu from :data:`LANG_NAME_KEY` INSIDE that file, in its own script. So somebody who
wants the panel in their language copies ``en.json`` to ``de.json``, translates it,
sets ``language.name`` to «Deutsch», and it is in the menu on the next start. There is
deliberately no table of languages here to keep in step with the directory.

The active language is persisted to ``profiles/settings.json`` — beside the profiles,
inside the project — and restored on the next launch. Default language is English.

It used to be written to ``~/.last_war_panel.json``, in the operator's home directory,
and was the ONE thing the panel kept outside the project altogether: a copy of the whole
project folder came up speaking the original's language with nothing on disk to explain
it (#1276). :func:`panel.profile.migrate_legacy_layout` brings the old answer across
once; the home file is left where it is, since another checkout may still be reading it.
"""
from __future__ import annotations

import json
import os

from . import paths

DEFAULT_LANG = "en"
LOCALES_DIR = os.path.join(paths.PANEL_DIR, "locales")

#: The panel-wide settings file, and the key in it. Shared with `panel/profile.py`,
#: which reads and writes the rest of that file — the two touch different keys and
#: each re-reads before writing, so neither loses the other's.
_PREF_FILE = paths.SETTINGS_FILE
_PREF_KEY = "language"

#: The key a locale file names ITSELF with, in its own script — "English" in en.json,
#: "Русский" in ru.json. Read by :func:`lang_name` for the Language menu.
LANG_NAME_KEY = "language.name"

# Locale files do not change while the panel runs, so one read each per process. The
# cache is module-level rather than per-instance: the shell, every tab launched on its
# own and each test helper build their own I18n, and they all want the same two files.
_CACHE: dict[str, dict[str, str]] = {}


def _read_map(path: str) -> dict[str, str]:
    """One JSON file as a flat map — a broken or missing one is an empty one."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def parts_dir(lang: str) -> str:
    """Where a language's per-tab files live: ``panel/locales/<lang>/``."""
    return os.path.join(LOCALES_DIR, lang)


def _part_files(lang: str) -> list[str]:
    try:
        names = sorted(f for f in os.listdir(parts_dir(lang)) if f.endswith(".json"))
    except OSError:
        return []
    return [os.path.join(parts_dir(lang), f) for f in names]


def load_locale(lang: str) -> dict[str, str]:
    """One language's whole table — the flat file plus every per-tab file it has.

    A language may be written two ways, and both are read into the same map (#1282):

        panel/locales/ru.json                 everything, one file — how it began
        panel/locales/ru/secret_tasks.json    one tab's keys, on their own

    The second exists because of the tree, not because of the panel. A key must land in
    every shipped locale in the SAME commit — that rule is why the tables are complete
    and it is not going anywhere — but it means 85 of the last 200 commits touched all
    eleven files, and two agents adding a key to two different tabs collided every time.
    Split by TAB and they do not meet at all.

    The per-tab files are read after the flat one and win on a key they both define. A
    key SHOULD only be in one of them; `tests/test_panel_locale_layout.py` says so, and
    the panel's own guarantee is unchanged either way — `tests/test_panel_i18n.py` walks
    the loaded table, not the files.
    """
    if lang not in _CACHE:
        data = _read_map(os.path.join(LOCALES_DIR, f"{lang}.json"))
        for path in _part_files(lang):
            data.update(_read_map(path))
        _CACHE[lang] = data
    return _CACHE[lang]


def available_langs() -> list[str]:
    """Languages that have a locale, sorted, default first.

    A locale is a `<lang>.json`, a `<lang>/` directory of per-tab files, or both — a
    language that has finished migrating no longer has a flat file, and it is still a
    language.
    """
    try:
        entries = os.listdir(LOCALES_DIR)
    except OSError:
        entries = []
    found = {f[:-5] for f in entries if f.endswith(".json")}
    found |= {d for d in entries
              if os.path.isdir(os.path.join(LOCALES_DIR, d)) and _part_files(d)}
    found.discard("")
    # The default is always offerable even with no file: `t` falls back to the key,
    # which is ugly but usable, whereas a menu with nothing in it is not.
    found.add(DEFAULT_LANG)
    return sorted(found, key=lambda lang: (lang != DEFAULT_LANG, lang))


def known(lang: str) -> bool:
    """Is there a locale for ``lang``?

    Asked BEFORE switching, because "no such language" and "already that language" are
    both a `False` out of :meth:`I18n.set_lang` and only one of them is worth a line in
    the log. A profile may name a language whose file this machine does not have — the
    person's own locale, a panel copied to a second machine — and that is a fallback
    with a log line, never a crash.
    """
    return bool(lang) and lang in available_langs()


def lang_name(lang: str) -> str:
    """What to call ``lang`` in the Language menu — its own file says so.

    Falls back to the bare code, so a locale added by hand that forgot
    :data:`LANG_NAME_KEY` still appears (as «de») rather than not at all.
    """
    name = load_locale(lang).get(LANG_NAME_KEY)
    return name.strip() if isinstance(name, str) and name.strip() else lang


class Message(str):
    """A sentence that knows how to be said in another language.

    Some of what the panel shows is worded far from the UI: the profile store refuses a
    duplicate name, the timers catalogue makes no sense of a hand-edited entry. Those
    modules are deliberately UI-agnostic — they have no translator and must not grow
    one — so the message reaching the person was whatever English the module happened to
    raise, dropped into a dialog or the log unchanged.

    This is that message and its locale key in one value. It IS the English string —
    printable, loggable, `in`-testable, formattable — so every consumer that already
    handled a plain `str` is untouched, and whatever puts it in front of a person calls
    :func:`translated` to say it in theirs.

        raise ValueError(Message("profile.error.exists",
                                 f"profile already exists: {name}", name=name))
    """

    key: str
    fmt: dict

    def __new__(cls, key: str, english: str, **fmt) -> "Message":
        self = super().__new__(cls, english)
        self.key = key
        self.fmt = fmt
        return self


def translated(t, value) -> str:
    """``value`` in the UI's language if it named one, in its own words otherwise.

    Takes a :class:`Message`, a plain string, or an exception raised with either —
    anything else is simply `str()`-ed, so a caller never has to know which it caught.
    """
    src = value
    if isinstance(value, BaseException) and value.args:
        src = value.args[0]
    key = getattr(src, "key", None)
    if not key:
        return str(value)
    return t(key, **getattr(src, "fmt", {}))


class I18n:
    """Locale lookup for one window, and the machine-wide fallback language.

    ``persist`` is what writes the chosen language to `profiles/settings.json`, which
    is only ever a FALLBACK: the language a profile is set to lives in that profile's
    own `config.json` and is applied when the profile is opened. With one profile open
    the two agree and writing it costs nothing. With two (#1206) they do not — whichever
    window's language was changed last would become the machine's, and the other
    profile would come back in it — so a window that belongs to a profile is built with
    ``persist=False`` and the profile alone remembers.
    """

    def __init__(self, lang: str | None = None, persist: bool = True) -> None:
        self.persist = persist
        self.lang = lang or self._load_pref()
        if self.lang not in available_langs():
            self.lang = DEFAULT_LANG

    # -- lookup -------------------------------------------------------------
    def _locale(self, lang: str) -> dict[str, str]:
        return load_locale(lang)

    def t(self, key: str, **fmt) -> str:
        template = self._locale(self.lang).get(key)
        if template is None:
            template = self._locale(DEFAULT_LANG).get(key, key)
        # A hand-written locale can put anything under a key; the UI wants a string.
        if not isinstance(template, str):
            template = key
        if fmt:
            try:
                return template.format(**fmt)
            except (KeyError, IndexError, ValueError):
                return template
        return template

    # -- language selection -------------------------------------------------
    def set_lang(self, lang: str) -> bool:
        if lang not in available_langs() or lang == self.lang:
            return False
        self.lang = lang
        if self.persist:
            self._save_pref(lang)
        return True

    def _load_pref(self) -> str:
        try:
            with open(_PREF_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return DEFAULT_LANG
        lang = data.get(_PREF_KEY) if isinstance(data, dict) else None
        return lang if isinstance(lang, str) and lang else DEFAULT_LANG

    def _save_pref(self, lang: str) -> None:
        data = {}
        try:
            with open(_PREF_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data[_PREF_KEY] = lang
        try:
            os.makedirs(os.path.dirname(_PREF_FILE), exist_ok=True)
            with open(_PREF_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass
