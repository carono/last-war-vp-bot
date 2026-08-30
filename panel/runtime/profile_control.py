"""Opening and closing a PROFILE, from either front-end (#1976).

`panel/runtime/panel_control.py` for accounts instead of for the panel itself, and it
exists for the same reason: the press belongs to the SHELL. Opening a profile builds a
page and fifteen tabs on it, closing one takes that page out and stops everything on it,
and a runtime knows nothing about either — it is one profile and no more. So the shell
registers what to run (:func:`set_handler`) and everyone else only asks whether there is
one. A tab launched on its own registers nothing, and then there is no press to offer:
that process is not the panel and has no notebook to put a page into.

WHY THE PHONE GETS IT. Until the window is retired (#1976) this is the one control that
decides WHICH ACCOUNTS ARE BEING FARMED AT ALL, and it lived on a modal at the machine.
A person away from the desk could watch four profiles and not open a fifth, or close one
that was misbehaving. Neither is a game press, and neither can be a scenario: they are
the panel's own shape.

RENAMING AND DELETING TRAVEL TOO, and they got here the way the character switch did
(#1976). They were held back as «destructive and rare — the kind of press that wants a
keyboard, a directory listing and a second look», which was an argument for a
CONFIRMATION and never for exclusivity: with the window going, a press only the machine
has is a press nobody will be able to make. So each of them asks for a WORD to be typed
— the new name for a rename, the profile's own name for a delete — and a press whose
text does not match does nothing at all (`panel/web/api.py`, `_profiles_press`).

WHAT IS STILL DELIBERATELY NOT HERE. Opening the profile's folder: a directory listing
means nothing on a phone, and there is no press to carry it out with.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The ids a press travels under. Not the names of what they do — a press outlives its
#: carrying out, exactly as the client's three and the panel's two do.
OPEN = "open"
CLOSE = "close"
RENAME = "rename"
DELETE = "delete"


@dataclass(frozen=True)
class Control:
    """One press on a profile, in both front-ends."""

    id: str
    #: The word on the button — the SAME key in the window and in the browser.
    label: str
    #: The question asked first, or ``""`` for a press that costs nothing to undo.
    #: Opening a profile is «go there»; closing one stops its errands and its captures,
    #: so it asks.
    confirm: str
    #: Does this press need a WORD typed before it happens, and what is the box called?
    #: ``""`` for a press that needs none. A rename is typed because the new name IS the
    #: press; a delete is typed because the profile's own name typed back is the whole
    #: guard — an `rmtree` of an account's chat history, its stores and its logs is not
    #: undone by pressing anything.
    prompt: str = ""


CONTROLS = (
    Control(OPEN, "profile.open", ""),
    Control(CLOSE, "profile.close_one", "profile.close.confirm"),
    Control(RENAME, "profile.rename", "", "profile.prompt_name"),
    Control(DELETE, "profile.delete", "", "profile.delete.prompt"),
)

BY_ID = {control.id: control for control in CONTROLS}

#: The tag it is logged under — the panel's own doings, never «action».
TAG = "profile"

_HANDLER = None


def set_handler(func) -> None:
    """The shell says how a profile is opened and closed. ``None`` unregisters."""
    global _HANDLER                          # noqa: PLW0603 — one per process, like the panel
    _HANDLER = func


def available() -> bool:
    """Is there a shell to carry a press out? ``False`` in a standalone tab or a test."""
    return _HANDLER is not None


def carry_out(action: str, name: str, text: str = "") -> bool:
    """Do it. ``False`` when there is no shell, no such press, or no such profile.

    The handler is called ON THE TK THREAD by the caller (`panel/web/api.py` hands it
    over): it builds or destroys widgets, and nothing else in this panel may.

    ``text`` is what the person typed, for the two presses that ask for a word. It is
    passed through UNCHECKED — whether it is the right word is the CALLER's question,
    because only the caller knows what was on the screen when the press was made.
    """
    if _HANDLER is None or action not in BY_ID or not str(name or "").strip():
        return False
    name = str(name).strip()
    done = bool(_HANDLER(action, name, str(text or "")))
    if done:
        _remember_the_wish(action, name)
    return done


def _remember_the_wish(action: str, name: str) -> None:
    """A press that WORKED also says what this machine wants farmed from now on (#2068).

    Opening and closing a profile are the only two things a person does that mean «keep
    this account up» and «stop keeping it up», and until this the service had to guess
    them from `open_profiles` — a record every panel process rewrites, including one
    somebody started for ten minutes to look at two test accounts. Guessing turned that
    look into the machine's boot list, and then held it there against every attempt to
    put it down.

    A rename and a delete are not wishes and are not written here: they follow the name,
    and `panel/profile.py` does that inside the rename and the delete themselves, so a
    profile renamed by any route at all keeps its place in the list.
    """
    from .. import profile as profilemod

    try:
        if action == OPEN:
            profilemod.keep_add(name)
        elif action == CLOSE:
            profilemod.keep_drop(name)
    except Exception:                        # noqa: BLE001 — a wish, never the press
        pass
