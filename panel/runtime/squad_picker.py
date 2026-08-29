"""The squad picker: four faces in a row, one per squad, click to switch it off (#2062).

THE PERSON'S DECISION, in their words: «должны быть 4 картинки в ряд с нашими героями,
именно те, что в игре у данного игрока, они меняются в зависимости от героев в отряде,
клик по картинке должен включать и отключать этот отряд, выключенный делаем серым. Везде
где есть выбор отрядов вставляем этот виджет и берем за правило».

WHY IT IS A WIDGET AND NOT MARKUP. «Which squads may go» is asked in several places — the
rally auto-join, the manual rally, the gear on «Таймеры», the golden-zombie hunt — and
every one of them drew its own row of boxes labelled «Отряд 1»..«Отряд 4». A number is not
what anybody recognises their own army by; the faces are. So there is ONE control, it is
declared like any other knob (`kind = "squads"`), and the front-end draws it —
`panel/web/app/src/ui/SquadPicker.tsx`.

WHAT THIS MODULE OWNS: the faces, and the shape of the field. It owns no value: a picker
reads and writes whatever variable the tab already kept its four booleans in, exactly as
the gear on «Таймеры» is a VIEW of the owner's knob and never a copy of it
(`panel/runtime/errand_options.py`).

READ ONCE, NEVER POLLED. A squad's composition changes when the PLAYER rearranges it — a
few times a month, announced to nobody — so `actions/read_squad_heroes.md` is played on
first need and then not again until something asks (`refresh_async`, wired to the pages'
own «Обновить»). That is the rule this repository works to (`CLAUDE.md`, «Read once, then
LISTEN»), and a composition that is a fortnight stale draws the right four faces anyway.

IT DEGRADES HONESTLY. The `heroId -> icon` table is encrypted on disk and the panel's own
copy of it has ten ids in it (`docs/research/hero-icons.md`), so the stem is read out of
the LIVE client and only falls back to that table. When neither can name a hero, or the
machine never ran `tools/extract_hero_icons.py`, the picker draws the squad's NUMBER and
its state — never a face that belongs to somebody else's hero.
"""
from __future__ import annotations

import threading
import urllib.parse as _url

#: The recipe that reads the composition.
ACTION = "read_squad_heroes"

#: What `rt.bus` carries a fresh reading under. The payload is `{index: [(id, stem), …]}`.
TOPIC = "squad_heroes"

#: The kind a field declares to be drawn as this control. It is `opt_value`'s fifth, and
#: it is here rather than there for the reason the four are there: those are the kinds a
#: DEFAULT can be recognised as, and «which squads» never is one.
KIND = "squads"

#: The slots the game gives a player. Four, and the panel has never had a reason to ask.
SQUADS = (1, 2, 3, 4)

#: How many faces one squad shows. ONE — the person looked at three of them side by side
#: and called it what it was: «в виджете героев оставляй спрайт первого героя, сейчас там
#: мешанина» (#2062). Three portraits inside a tile a quarter of a phone wide are three
#: things too small to recognise; one fills the tile and is recognised at a glance.
#:
#: «FIRST» IS THE GAME'S OWN FIRST, not ours. `read_squad_heroes.md` walks the formation's
#: `localIndexToHeroDic` by POSITION — 1, 2, 3… — so the first record of a squad is the
#: hero the game itself keeps in position 1, never whichever entry a Lua `pairs()` happened
#: to hand over first.
FACES = 1

#: The drone slot is not a hero and has no portrait of its own.
DRONE_ID = 1000000


def face_url(stem: str) -> str:
    """The LINK the phone draws for one hero, `""` when this machine has no picture.

    A link and not a blob, for the reason every other picture on these screens is one:
    a sprite is tens of kilobytes and the screen is polled, so the browser fetches it
    once and keeps it (`panel/runtime/errand_art.py`).
    """
    try:
        import hero_icons_map

        name = hero_icons_map.name_for(stem)
    except Exception:                       # noqa: BLE001 — a picture, never the page
        return ""
    if not name:
        return ""
    return "/api/heroicon?icon=" + _url.quote(name)


def parse(raw: str) -> dict:
    """What `read_squad_heroes.md` said, as `{slot: [(heroId, stem), …]}`.

    Anything unreadable is dropped rather than guessed at, exactly as
    `panel/runtime/squads.py::parse` drops a record with no slot number.
    """
    out: dict = {}
    if not isinstance(raw, str):
        return out
    for record in raw.split("|"):
        fields = {}
        for token in record.split():
            key, sep, value = token.partition("=")
            if sep:
                fields[key.strip()] = value.strip()
        if "squad" not in fields:
            continue
        try:
            index = int(float(fields.get("squad") or 0))
        except (TypeError, ValueError):
            continue
        if index <= 0:
            continue
        heroes = []
        for chunk in (fields.get("heroes") or "").split(","):
            hero_id, _sep, stem = chunk.partition(":")
            try:
                number = int(float(hero_id))
            except (TypeError, ValueError):
                continue
            if number <= 0 or number == DRONE_ID:
                continue
            heroes.append((number, stem.strip()))
        out[index] = heroes
    return out


class HeroReader:
    """The composition of every squad, read once and remembered.

    Built on first ask, exactly like `rt.squads` — a profile whose pages nobody opens
    pays nothing. `faces()` never blocks and never plays anything: it answers with what
    has been read, and asks for a reading in the background when there has been none.
    That is what lets it be called from `web_view`, which the phone polls.
    """

    def __init__(self, rt) -> None:
        self._rt = rt
        self._heroes: dict = {}
        self._read = False           # a reading has landed (even an empty one)
        self._reading = False        # one is in flight
        self._lock = threading.Lock()

    # -- reading ------------------------------------------------------------
    def latest(self) -> dict:
        return dict(self._heroes)

    def read(self) -> dict:
        """Play the recipe and remember what it said. BLOCKS — never on the Tk thread."""
        with self._lock:
            game = getattr(self._rt, "game", None)
            try:
                if game is None or not game.ready():
                    return dict(self._heroes)
            except Exception:               # noqa: BLE001 — a cold link may refuse
                return dict(self._heroes)
            try:
                # Silent: this is a reading behind a picture, and a line in the log per
                # screen somebody opens is noise nobody asked for.
                outcome = self._rt.actions.play(ACTION, on_event=lambda msg: None)
            except Exception:               # noqa: BLE001 — never the caller's problem
                return dict(self._heroes)
            ctx = getattr(outcome, "ctx", None)
            raw = (getattr(ctx, "vars", {}) or {}).get("squad_heroes") if ctx else None
            if outcome.ok and isinstance(raw, str):
                self._heroes = parse(raw)
                self._read = True
        self._publish()
        return dict(self._heroes)

    def refresh_async(self) -> None:
        """Read on a worker thread. Safe from Tk, and safe to call from a press."""
        if self._reading:
            return
        self._reading = True

        def work() -> None:
            try:
                self.read()
            finally:
                self._reading = False

        threading.Thread(target=work, daemon=True).start()

    def _publish(self) -> None:
        try:
            self._rt.bus.publish(TOPIC, dict(self._heroes))
        except Exception:                   # noqa: BLE001 — a deaf listener is not
            pass                            # the reader's problem

    # -- what a field is drawn with -----------------------------------------
    def faces(self, index: int) -> list:
        """The picture link for one squad — `[]` when its first hero has no picture.

        ASKS FOR A READING when there has never been one, and answers `[]` meanwhile.
        The screen is polled, so the face appears a moment later without anything
        blocking on the game.

        THE FIRST HERO AND NO OTHER. When the hero in position 1 cannot be named, the
        answer is «no picture» rather than the hero behind him: a tile is read as «this
        is who leads that squad», so standing somebody else in his place would be a
        wrong answer dressed as a right one — the same reason a hero nobody can name
        draws no face at all instead of a similar one.
        """
        if not self._read:
            self.refresh_async()
        links = []
        for hero_id, stem in self._heroes.get(int(index), ())[:FACES]:
            url = face_url(stem) if stem else ""
            if not url:
                url = _fallback_url(hero_id)
            if url:
                links.append(url)
        return links


def _fallback_url(hero_id: int) -> str:
    """The eyeball-confirmed table's answer for an id the game would not name."""
    try:
        import hero_icons_map

        stem = hero_icons_map.resname_for(int(hero_id))
    except Exception:                       # noqa: BLE001 — a picture, never the page
        return ""
    return face_url(stem) if stem else ""


def reader(rt) -> HeroReader:
    """This profile's reader, made on first ask and kept on the runtime."""
    found = getattr(rt, "_squad_heroes", None)
    if found is None:
        found = HeroReader(rt)
        try:
            rt._squad_heroes = found
        except Exception:                   # noqa: BLE001 — a harness may refuse
            pass
    return found


# ---------------------------------------------------------------------------
# The field a tab declares.

def field(rt, key: str, label_key: str, chosen, *, single: bool = False,
          hint_key: str = "", squads=SQUADS) -> dict:
    """One picker, as the web's `Field`.

    ``chosen`` is whichever slots are ON — a list, a set or a string of them. The value
    travels as a comma-joined list of slot numbers, so a press answers with exactly what
    it drew and the owner writes its own booleans back (:func:`chosen_from`).

    ``single`` is for the places where one squad is picked rather than several — the
    golden-zombie hunt sends ONE. The control is the same and a click still moves the
    choice; what changes is that switching one on switches the others off.
    """
    picked = set(chosen_from(chosen))
    heroes = reader(rt)
    return {
        "key": key,
        "label": label_key,
        "kind": KIND,
        "value": ",".join(str(s) for s in sorted(picked)),
        "single": bool(single),
        "hint": hint_key or None,
        "squads": [{"n": slot, "on": slot in picked,
                    "faces": heroes.faces(slot),
                    "state": _state(rt, slot)}
                   for slot in squads],
    }


def _state(rt, index: int) -> str:
    """What that squad is doing, in the panel's own word — `""` when unread.

    Off the reading `rt.squads` already holds; nothing here asks the game. It is a
    picture's caption, not a gate: the gate is in the recipe (`CLAUDE.md`).
    """
    try:
        state = rt.squads.latest()
    except Exception:                       # noqa: BLE001 — a reading, never the panel
        return ""
    if state is None or not getattr(state, "ok", False):
        return ""
    return state.kind(int(index))


def chosen_from(value) -> list:
    """Whatever a caller or a press has for «which slots», as a sorted list of ints."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p for p in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple, set, frozenset)):
        parts = list(value)
    else:
        parts = [value]
    out = set()
    for part in parts:
        try:
            number = int(float(str(part).strip()))
        except (TypeError, ValueError):
            continue
        if number in SQUADS:
            out.add(number)
    return sorted(out)
