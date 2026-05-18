# Last War — overview

> Living document. Filled in incrementally during design sessions.

## What the game is

A **resource grinder**. A typical player session is 15–30 minutes, two or three times a day; that's enough to clear all the daily activities and miss nothing important. The biggest social hook is the in-game chat — **we do not automate that**. The bot's purpose is to take over the **repetitive daily collection routine**, which is roughly 99 % identical from day to day.

Real change to mechanics happens only at **season turnover** (every 2–3 months, like a DLC). A new season may add mini-games and tweak some flows; once it ends, everything reverts to the canonical loop. Bot behaviour during a season may need a temporary override; the baseline routine should keep working.

See [daily_cycle.md](daily_cycle.md) for the canonical sequence of actions in a session.

## Two primary screens

- **Base** (`База`) — the player's settlement. Buildings, resource collection, research. See [screens/base.md](screens/base.md).
- **World** (`Карта мира`) — strategic map. Pan around, click objects to interact. See [screens/world.md](screens/world.md).

A single button toggles between the two — its slot in the bottom-right is the same; only its icon swaps depending on the current screen.

## UI layout — anchored to the window edges

Almost all controls live in fixed positions along the **edges** of the window. The middle is the gameplay area (the base, or a region of the world map).

The persistent layout zones are:

| Zone           | Typical contents                                                            |
|----------------|-----------------------------------------------------------------------------|
| Top-left       | Player profile photo/button, indicators                                     |
| Top-right      | On world: events + energy indicator + busy-squads indicator. On base: build/research queue indicators. |
| Bottom-left    | World-action buttons (monster hunt, secret missions, …), heroes menu        |
| Bottom-right   | Alliance / mail / inventory; world/base toggle button                       |
| Bottom (centre)| In-game chat strip                                                          |

Most buttons are **persistent** across screens, but the top-right slot is different on world vs base, and the world ↔ base button swaps direction. Per-screen lists live in `screens/*.md`.

The top-right **event button set varies per player and season**: order may differ, the visible set depends on whether the player is in an alliance and which events are currently live; even the "events" button itself can change skin during a season. The general slot location is stable.

## UI scales, controls stay in place

The game supports fullscreen and a freely resizable window. On resize:

- **Edge-anchored UI controls keep the same screen offset** from the window edge.
- The **gameplay area** (centre) changes size; objects inside it scale proportionally.

Practical consequence for the bot: UI templates can be matched relative to window edges with fixed offsets, but gameplay-area object templates need multi-scale matching (or normalised coordinates relative to the gameplay area).

## Zoom changes the UI

On the world map, zooming changes which interface buttons are visible.

> _TODO: enumerate exactly what shows/hides at each zoom threshold._

## Attention markers (red dots)

Anywhere in the UI where the player has something new to handle — unread mail, ready-to-collect rewards, completed builds, available alliance donations, freshly unlocked event rewards — the relevant button is decorated with a **small red dot in a corner**, usually the top-right corner of the button. The exact pixel position is button-specific but the convention is consistent across the game.

This is the bot's primary "is there work to do?" signal:

- **Red dot present** on an activity entry point → the activity has pending work; the bot should enter it.
- **Red dot absent** → there is nothing pending in that activity; the bot can skip it this session.

The dot also appears on **tabs / buttons inside modals**, surfacing exactly which sub-section has something new. The bot can drive its modal exploration off the dots instead of opening every tab blindly.

> _TODO: confirm corner position and approximate size; confirm whether the dot ever carries a number (e.g. count of pending items) or stays a plain dot._

## Modal-heavy interaction

Most non-trivial interactions open a **modal window** on top of the current screen. Heroes, alliance, mail, hire, event detail — all modals. The base/world map underneath remains visible but inactive. See [screens/modals.md](screens/modals.md) for the modal pattern and specific modals.

## Time-sensitive mechanics

Several systems penalise the player for not visiting in time:

- **Resource production** overflows storage; once full, new production stalls.
- **Alliance donation** accumulates 1 unit per 20 minutes, capped at 30; cap means lost donations.
- **Secret missions** sent out return in 2–3 hours and must be collected.
- **Arms Race** has fixed 4-hour windows, each with its own objective; missing a window means missing its rewards.

These deadlines drive the **session cadence** (2–3 sessions per day, ~8 hours apart).

## Interaction model

- **World map:** pannable. Most objects on the map are clickable; clicking opens a context menu or starts an interaction (collect, attack, scout, etc.).
- **Base:** mostly static (no large-scale panning). Buildings are clickable; many open dedicated modals.

## Open questions

- Exact zoom-dependent UI changes on the world map.
- Full breakdown of which buttons exist only on base vs. only on world (beyond the top-right and the screen-toggle slot).
- Whether the chat strip is collapsed-by-default and expands on click.
- What indicators sit next to the profile in the top-left.
