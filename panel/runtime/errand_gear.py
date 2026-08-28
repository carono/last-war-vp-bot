"""The ⚙ beside an errand — one small window holding that errand's knobs (#2017).

WHY IT IS HERE and not in the tab that owns the values: the knobs are declared by
whoever owns them (`panel/runtime/errand_options.py`) and drawn by whoever LISTS the
errands, which is «Таймеры». Neither of them should have to know how a switch, a number
or a choice is drawn — that is one function, and it is this one.

THE VALUES ARE NOT COPIED. Every control writes through the `Option` it was made from,
which writes the owner's own variable. So a level typed here is the level the owning
tab's page shows the moment somebody looks at it, and the two can never drift apart.

A TYPED BOX IS WRITTEN WHEN IT IS LEFT, never on every keystroke: «4», «40», «400» on
the way to «4000» are three rules nobody asked for, and one of them aims a robbery. A
switch and a choice are written at once, because there is nothing half-typed about them.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import errand_options as errandopts


def open_gear(rt, parent, errand: str, title: str) -> "tk.Toplevel | None":
    """Open the knobs of one errand. ``None`` when it declared none."""
    options = rt.schedule.options.spec(errand)
    if not options:
        return None
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    body = ttk.Frame(win, padding=10)
    body.pack(fill="both", expand=True)
    for option in options:
        _draw(rt, body, option)
    foot = ttk.Frame(body)
    foot.pack(fill="x", pady=(10, 0))
    ttk.Button(foot, text=rt.t("timers.options.close"),
               command=win.destroy).pack(side="right")
    win.bind("<Escape>", lambda _e: win.destroy())
    return win


def _label(rt, option) -> str:
    """What the knob is called — a key, with whatever the owner put in its places."""
    return rt.t(option.label_key, **(option.label_fmt or {}))


def _draw(rt, parent, option) -> None:
    """One knob, as the control its kind names."""
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=3)
    value = option.read(rt)

    if option.kind == errandopts.SWITCH:
        var = tk.BooleanVar(value=bool(value))
        ttk.Checkbutton(row, text=_label(rt, option), variable=var,
                        command=lambda: option.write(rt, var.get())).pack(side="left")
    elif option.kind == errandopts.CHOICE:
        ttk.Label(row, text=_label(rt, option)).pack(side="left", padx=(0, 6))
        words = {str(o.get("value")): str(o.get("text"))
                 for o in option.choices(rt)}
        var = tk.StringVar(value=words.get(str(value), ""))
        box = ttk.Combobox(row, textvariable=var, values=list(words.values()),
                           state="readonly", width=18)
        box.pack(side="left")
        back = {text: ident for ident, text in words.items()}
        box.bind("<<ComboboxSelected>>",
                 lambda _e: option.write(rt, back.get(var.get(), "")))
    else:
        ttk.Label(row, text=_label(rt, option)).pack(side="left", padx=(0, 6))
        var = tk.StringVar(value="" if value is None else str(value))
        entry = ttk.Entry(row, textvariable=var, width=10)
        entry.pack(side="left")
        entry.bind("<FocusOut>", lambda _e: option.write(rt, var.get()))
        entry.bind("<Return>", lambda _e: option.write(rt, var.get()))

    if option.hint_key:
        ttk.Label(parent, text=rt.t(option.hint_key), foreground="#888",
                  wraplength=380, justify="left").pack(anchor="w", pady=(0, 4))
