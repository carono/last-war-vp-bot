"""«Карта: схема» — the world as the PANEL sees it, drawn (#2018).

The person's words: «нужно в отдельной вкладке перерисовывать состояние игры, тайлы,
объекты, состояние читать из игры… достаточно схематично… вид пока ридонли, не значит,
что нужно делать управление, пока просто нужно сравнить, что видим мы с реальностью».

So this tab is a MIRROR, not a client. Everything the bot decides rests on a model of
the map assembled from the wire, and until now that model could only be read as tables
of coordinates — which is no way to notice that a whole quarter of the map is missing,
or that our mines are one tile off. The web front-end paints it on a canvas
(`panel/web/app/src/views/WorldMap.tsx`, PixiJS) and a person holds it up beside the
real client.

**Read-only, and it reads nothing from the game.** The scene is assembled by
`panel/runtime/worldscene.py` out of what is already on this profile's disk: the map
sweep's checkpoint, the monsters table, the two lists the other tabs keep, the treasure
scan. Opening this page starts no capture, plays no scenario and asks the client
nothing — `CLAUDE.md`'s «Read once, then LISTEN» is exactly what a page of this kind
would break if it went looking for fresher data on a timer. What it does instead is say
HOW OLD each source is, so a picture that is behind looks behind.

**The canvas is the phone's, and the window gets the numbers.** New work goes into the
web while the Tk window is being retired (`CLAUDE.md`, «…for the length of the migration
it travels ONE way»), and a WebGL map in Tk would be a second renderer built for a
front-end that is being deleted. So `build()` draws what the tab KNOWS — how many
objects of each kind, and how old each source is — and says where the picture is.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..runtime import worldscene
from ..widgets import tk_stringvar
from .base import PanelTab

#: How an age is written where a number has to be language-free — «12:04», «—».
_NEVER = "—"

#: Which sources are named on the page, and in what order. The key is the one
#: `worldscene` stamps its ages under; the locale key is `worldview.src.<name>`.
SOURCES = ("world_map", "monsters", "secret_tasks", "ghost_map", "treasures",
           "coverage")

#: WHAT WE DO NOT KNOW, said on the page itself.
#:
#: The picture is only half the answer to «сходится ли наша модель с игрой»; the other
#: half is what our data cannot contain at all. Without this list a person searches the
#: canvas for things that were never in the sources — alliance cities, terrain, a base's
#: real footprint — and concludes the tool is broken. Each is a locale key, and the
#: reasoning behind each one is `docs/research/world-schematic-map.md`.
GAPS = ("coverage", "alliance_cities", "terrain", "footprint", "monsters_view",
        "treasures_sniffer", "players_no_coords", "world_size", "marches", "assets")


def age_text(seconds) -> str:
    """`seconds` as m:ss — data, not a sentence, so it needs no translating."""
    if seconds is None:
        return _NEVER
    total = int(max(0.0, float(seconds)))
    if total >= 3600:
        return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


class WorldViewTab(PanelTab):
    """The map the panel believes in, as counts here and as a picture on the phone."""

    ID = "worldview"
    TITLE_KEY = "tab.worldview"
    ORDER = 350
    LOCALE_NS = ("worldview",)
    #: Nothing: every source is a file or a table this profile already has. No daemon,
    #: no capture child, no scenario — which is the whole claim this tab makes.
    NEEDS = frozenset()
    WEB_SCREEN = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: What the last read found. Made here rather than in `build()` because the
        #: phone may ask for the screen of a tab nobody has opened (`LAZY`, #1215).
        self._counts: dict = {}
        self._ages: dict = {}
        self._swept = 0
        self._count_vars: dict = {}
        self._age_vars: dict = {}

    # -- the window ---------------------------------------------------------
    def build(self) -> None:
        frame = ttk.Frame(self.parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tr(ttk.Label(frame, wraplength=560, justify=tk.LEFT),
                "worldview.window_hint").grid(row=0, column=0, columnspan=4,
                                              sticky="w", pady=(0, 8))

        counts = ttk.LabelFrame(frame, padding=8)
        self.tr(counts, "worldview.counts")
        counts.grid(row=1, column=0, columnspan=4, sticky="ew")
        for i, kind in enumerate(worldscene.KINDS):
            var = tk_stringvar(self.rt.root)
            var.set("0")
            self._count_vars[kind] = var
            self.tr(ttk.Label(counts), f"worldview.kind.{kind}").grid(
                row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 6))
            ttk.Label(counts, textvariable=var).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 20))

        ages = ttk.LabelFrame(frame, padding=8)
        self.tr(ages, "worldview.ages")
        ages.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        for i, name in enumerate(SOURCES):
            var = tk_stringvar(self.rt.root)
            var.set(_NEVER)
            self._age_vars[name] = var
            self.tr(ttk.Label(ages), f"worldview.src.{name}").grid(
                row=i, column=0, sticky="w", padx=(0, 6))
            ttk.Label(ages, textvariable=var).grid(row=i, column=1, sticky="w")

        self.tr(ttk.Button(frame, command=self.refresh), "worldview.refresh").grid(
            row=3, column=0, sticky="w", pady=(10, 0))
        self.refresh()

    def on_show(self) -> None:
        """Somebody is looking: re-read what is on disk. No game call, ever."""
        self.refresh()

    def refresh(self) -> None:
        """Re-read the counts and the ages — files and this profile's database."""
        try:
            data = worldscene.overview(self.rt)
        except Exception:      # noqa: BLE001 — a page of numbers is never worth a crash
            self.rt.dbg("worldview").exception("could not read the world overview")
            return
        self._counts = data.get("counts") or {}
        self._ages = data.get("ages") or {}
        self._swept = int(data.get("swept") or 0)
        for kind, var in self._count_vars.items():
            var.set(str(self._counts.get(kind, 0)))
        for name, var in self._age_vars.items():
            var.set(age_text(self._ages.get(name)))

    # -- the phone ----------------------------------------------------------
    def web_view(self) -> "dict | None":
        """The counts and the ages as a card — and the canvas that draws the rest.

        `map` is what tells the front-end to paint: it names the screen and the kind of
        scene, and the picture itself is fetched separately (`/api/screen/data`) because
        a screen is re-read on the ordinary poll and thirty thousand objects on every
        tick is a page nobody could keep open (`panel/web/api.py`).
        """
        self.refresh()
        counts = [{"label": f"worldview.kind.{kind}",
                   "value": str(self._counts.get(kind, 0))}
                  for kind in worldscene.KINDS]
        ages = [{"label": f"worldview.src.{name}",
                 "value": age_text(self._ages.get(name))} for name in SOURCES]
        ages.append({"label": "worldview.swept", "value": str(self._swept)})
        return {
            "map": {"kind": "world"},
            "cards": [
                {"title": "worldview.counts", "note": "worldview.hint", "rows": counts},
                {"title": "worldview.ages", "note": "worldview.ages_hint",
                 "rows": ages},
                # WHAT THE PICTURE CANNOT SHOW, on the picture's own page. See `GAPS`.
                {"title": "worldview.gaps", "note": "worldview.gaps_hint",
                 "items": [{"label": f"worldview.gap.{name}"} for name in GAPS]},
            ],
        }

    def web_data(self, kind: str, args: dict) -> "dict | None":
        """The scene itself, for the canvas — the one thing too big to poll.

        Read-only and off the Tk thread: files and SQLite, nothing that touches a widget
        (`panel/web/api.py`, «WHICH THREAD»).
        """
        if kind != "map":
            return None
        server = args.get("server") if isinstance(args, dict) else None
        try:
            server = int(server) if server not in (None, "", "all") else None
        except (TypeError, ValueError):
            server = None
        return worldscene.scene(self.rt, server=server)


if __name__ == "__main__":
    from .base import run_tab

    raise SystemExit(run_tab(WorldViewTab))
