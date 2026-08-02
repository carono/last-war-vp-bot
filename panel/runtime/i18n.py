"""The Translator: locale lookup plus the registry that re-renders on a language switch.

`panel/i18n.py` holds the lookup itself (locale files, fallback chain, the remembered
language). This adds the two things a UI needs on top of it:

* :meth:`Translator.tr` — set a widget's option from a key AND remember the pair, so a
  language switch can re-render it in place;
* :meth:`Translator.hook` — a callback for what `tr` cannot express (a whole page that
  redraws, a menu bar that is rebuilt), registered once however often it is reached.

Both were `Panel._tr` / `Panel._hook`. They move here because a tab needs them in both
launch modes and neither has anything to do with the shell's window
(docs/research/panel-tabs-refactor.md §4.1).

The registry holds WEAK references. Half the panel's translated widgets are rows a page
repaints — the ghost list every nine seconds, the inventory on every keystroke in its
search box — and each repaint destroys the previous row and builds a new one. A strong
reference meant every widget the panel had ever drawn stayed alive in this list for the
rest of the session: an unbounded list of dead Tk objects, and a language switch walking
all of them. A destroyed widget drops out of its parent's `children` map, so a weak
reference goes dead exactly when the widget does.
"""
from __future__ import annotations

import weakref

from .. import i18n as i18nmod

# How many entries the registry may hold before it is swept for widgets that have been
# destroyed. Comfortably above the number a fully built panel has, so a panel nobody
# repaints never pays for the sweep at all.
REGISTRY_SWEEP = 1000


class Translator:
    """Locale lookup + the retranslation registry. No Tk of its own beyond `configure`."""

    def __init__(self, lang: str | None = None) -> None:
        self._i18n = i18nmod.I18n(lang)
        # (weakref-to-widget, option, key, fmt) — retranslated in place.
        self._widgets: list = []
        self._watermark = REGISTRY_SWEEP
        self._hooks: list = []
        self._hook_keys: set = set()

    # -- lookup -------------------------------------------------------------
    @property
    def lang(self) -> str:
        return self._i18n.lang

    def t(self, key: str, **fmt) -> str:
        return self._i18n.t(key, **fmt)

    def tr(self, widget, key: str, option: str = "text", **fmt):
        """Set ``widget[option]`` from a locale key and remember it for retranslation."""
        widget.configure(**{option: self.t(key, **fmt)})
        self._widgets.append((weakref.ref(widget), option, key, fmt))
        if len(self._widgets) > self._watermark:
            self.sweep()
        return widget

    # -- hooks --------------------------------------------------------------
    def hook(self, func, key=None) -> None:
        """Register a language-change callback — once, however often this is reached.

        A hook registered twice is a page redrawn twice per language switch, growing
        every time the path is reached again. `key` names a lambda, which can never be
        recognised by identity; a bound method is its own key.
        """
        key = func if key is None else key
        if key in self._hook_keys:
            return
        self._hook_keys.add(key)
        self._hooks.append(func)

    # -- housekeeping -------------------------------------------------------
    def sweep(self) -> None:
        """Drop the entries whose widget has been destroyed.

        The next sweep is due at twice what survived this one (never below
        REGISTRY_SWEEP), so the cost stays amortised — a fixed threshold would re-walk
        the whole list on every registration once the live set passed it.
        """
        self._widgets[:] = [e for e in self._widgets if e[0]() is not None]
        self._watermark = max(REGISTRY_SWEEP, len(self._widgets) * 2)

    def set_lang(self, lang: str) -> bool:
        """Switch language. ``True`` if it changed (the caller then retranslates)."""
        return self._i18n.set_lang(lang)

    def retranslate(self) -> None:
        """Re-render every registered widget, then run the hooks."""
        import tkinter as tk

        self.sweep()
        for ref, option, key, fmt in self._widgets:
            widget = ref()
            if widget is None:
                continue
            try:
                widget.configure(**{option: self.t(key, **fmt)})
            except tk.TclError:              # the widget is going away mid-switch
                pass
        for hook in self._hooks:
            hook()

    # -- diagnostics --------------------------------------------------------
    def registry_size(self) -> int:
        """How many live registrations there are (what the health snapshot watches)."""
        return len(self._widgets)
