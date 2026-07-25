"""Tiny i18n helper for the control panel.

UI strings live in ``panel/locales/<lang>.json`` (flat ``key -> template`` maps).
Look a string up with :func:`I18n.t`; ``{name}``-style placeholders are filled via
``str.format``. Missing keys fall back to the default language, then to the key
itself, so a half-translated locale never crashes the UI.

The active language is persisted to ``~/.last_war_panel.json`` and restored on the
next launch. Default language is English.
"""
from __future__ import annotations

import json
import os

DEFAULT_LANG = "en"
LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_PREF_FILE = os.path.join(os.path.expanduser("~"), ".last_war_panel.json")

# Display names shown in the Language menu (kept in each language's own script).
LANG_NAMES = {"en": "English", "ru": "Русский"}


def available_langs() -> list[str]:
    """Languages that have a ``<lang>.json`` locale file, sorted, default first."""
    try:
        found = {f[:-5] for f in os.listdir(LOCALES_DIR) if f.endswith(".json")}
    except OSError:
        found = set()
    found.add(DEFAULT_LANG)
    return sorted(found, key=lambda lang: (lang != DEFAULT_LANG, lang))


class I18n:
    def __init__(self, lang: str | None = None) -> None:
        self._cache: dict[str, dict[str, str]] = {}
        self.lang = lang or self._load_pref()
        if self.lang not in available_langs():
            self.lang = DEFAULT_LANG

    # -- lookup -------------------------------------------------------------
    def _locale(self, lang: str) -> dict[str, str]:
        if lang not in self._cache:
            path = os.path.join(LOCALES_DIR, f"{lang}.json")
            try:
                with open(path, encoding="utf-8") as fh:
                    self._cache[lang] = json.load(fh)
            except (OSError, ValueError):
                self._cache[lang] = {}
        return self._cache[lang]

    def t(self, key: str, **fmt) -> str:
        template = self._locale(self.lang).get(key)
        if template is None:
            template = self._locale(DEFAULT_LANG).get(key, key)
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
