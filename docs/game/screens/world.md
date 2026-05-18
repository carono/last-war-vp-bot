# Screen — World map (`Карта мира`)

> Living document.

One of the two primary screens. A pannable strategic map populated with interactable objects (resources, monsters, missions, enemy bases, alliance objects, event objects, …).

## Centre / gameplay area

- Pannable in any direction.
- Most visible objects are clickable. Clicks open a context-action menu or start an interaction (collect, attack, scout, etc.).
- Zoom level changes which UI buttons are shown around the edges (see "Zoom-dependent UI" below).

## Edge UI — buttons by zone

| Zone           | Contents                                                                            |
|----------------|-------------------------------------------------------------------------------------|
| Top-left       | Player profile photo/button; indicators                                             |
| Top-right      | Event buttons; **energy indicator**; **busy-squads indicator**                      |
| Bottom-left    | World-action buttons (monster hunt, secret missions, …); heroes menu                |
| Bottom-right   | Alliance, mail, inventory; **"go to base"** navigation                              |
| Bottom (centre)| In-game chat strip                                                                  |

### Top-right details

The event button set is **variable**:

- Order may differ between players.
- Visible set depends on whether the player is in an alliance.
- A particular event button can change skin during a season but stays in roughly the same position.

Always present in the top-right block (when on world):

- **Energy** (`Энергия`) — current value of the spendable resource consumed by rallies and other actions.
- **Busy squads** — how many of the player's squads are currently dispatched (rally, secret mission, training).

### Bottom-right — screen toggle

The "go to base" button lives in the same slot that, on the base screen, holds "go to world". The slot is shared; the icon swaps with the current screen.

## Zoom-dependent UI

On the world map, some interface elements appear or disappear depending on the zoom level.

> _TODO: enumerate concretely — at which zoom thresholds which buttons toggle._

## Navigation out

- Bottom-right "go to base" button → switches to the [Base](base.md) screen.

## Open questions

- Concrete event types in the top-right group.
- Concrete world-action buttons in the bottom-left group.
- Zoom thresholds and what toggles at each.
- Full list of in-world object types (resource node, monster, secret-mission marker, enemy base, alliance flag, ...).
