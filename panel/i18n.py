"""Tiny i18n helper for the control panel.

UI strings live in ``panel/locales/<lang>.json`` (flat ``key -> template`` maps).
Look a string up with :func:`I18n.t`; ``{name}``-style placeholders are filled via
``str.format``. Missing keys fall back to the default language, then to the key
itself, so a half-translated locale never crashes the UI.

A LANGUAGE IS A FILE, and nothing else. The list is the contents of the locales
directory — the code stem comes from the file name, the name to show in the Language
menu from :data:`LANG_NAME_KEY` INSIDE that file, in its own script. So somebody who
wants the panel in their language copies ``en.json`` to ``de.json``, translates it,
sets ``language.name`` to «Deutsch», and it is in the menu on the next start. There is
deliberately no table of languages here to keep in step with the directory.

The active language is persisted to ``~/.last_war_panel.json`` and restored on the
next launch. Default language is English.
"""
from __future__ import annotations

import json
import os

DEFAULT_LANG = "en"
LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_PREF_FILE = os.path.join(os.path.expanduser("~"), ".last_war_panel.json")

#: The key a locale file names ITSELF with, in its own script — "English" in en.json,
#: "Русский" in ru.json. Read by :func:`lang_name` for the Language menu.
LANG_NAME_KEY = "language.name"

# Locale files do not change while the panel runs, so one read each per process. The
# cache is module-level rather than per-instance: the shell, every tab launched on its
# own and each test helper build their own I18n, and they all want the same two files.
_CACHE: dict[str, dict[str, str]] = {}


def load_locale(lang: str) -> dict[str, str]:
    """The ``<lang>.json`` map, or an empty one — a broken locale is not a crash."""
    if lang not in _CACHE:
        path = os.path.join(LOCALES_DIR, f"{lang}.json")
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        _CACHE[lang] = data if isinstance(data, dict) else {}
    return _CACHE[lang]


def available_langs() -> list[str]:
    """Languages that have a ``<lang>.json`` locale file, sorted, default first."""
    try:
        found = {f[:-5] for f in os.listdir(LOCALES_DIR) if f.endswith(".json")}
    except OSError:
        found = set()
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
    def __init__(self, lang: str | None = None) -> None:
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
        self._save_pref(lang)
        return True

    def _load_pref(self) -> str:
        try:
            with open(_PREF_FILE, encoding="utf-8") as fh:
                return json.load(fh).get("lang", DEFAULT_LANG)
        except (OSError, ValueError):
            return DEFAULT_LANG

    def _save_pref(self, lang: str) -> None:
        data = {}
        try:
            with open(_PREF_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        data["lang"] = lang
        try:
            with open(_PREF_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass
