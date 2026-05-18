# Screen — Base (`База`)

> Living document.

One of the two primary screens. The player's settlement. Mostly static (no large-scale panning), with buildings and floating UI prompts.

## Centre / gameplay area

Buildings laid out across the base. Clickable to open per-building modals (production, upgrades, research, training, etc.).

> _TODO: list of buildings the bot must recognise (with Russian labels and template references)._

## Player actions on this screen

- Collect produced resources from passively-producing buildings or from a roaming hauler/truck. **Critical**: storage overflows; once full, new production halts.
- Build new buildings and upgrade existing ones.
- Start and queue research from the relevant building.
- Train units from military buildings — including the **forbidden zone** tower (`Запретная зона`), whose UI changes by development stage.
- Open per-building modals to manage their state.

> _TODO: enumerate which building hosts research, training, the forbidden-zone tower, etc._

## Edge UI

Layout shape mirrors the [world screen](world.md), but the top-right and the bottom-right screen-toggle slot differ:

| Zone           | Contents                                                                            |
|----------------|-------------------------------------------------------------------------------------|
| Top-left       | Player profile photo/button; indicators                                             |
| Top-right      | **Build / research queue indicators** — what's being built/researched, slot usage   |
| Bottom-left    | (shared with world — heroes menu, world-action launchers — _TODO confirm_)          |
| Bottom-right   | Alliance, mail, inventory; **"go to world"** navigation                             |
| Bottom (centre)| (chat strip — _TODO confirm whether it's also shown on base_)                       |

The "go to world" button uses the same slot that holds "go to base" on the world screen; the icon swaps with the current screen.

Edge buttons and individual buildings can carry **red dots** when something is pending (e.g. resource ready for collection, build finished, research done). See [overview.md → Attention markers](../overview.md#attention-markers-red-dots).

## Open questions

- Whether the chat strip lives on the base too, or only on the world.
- Whether the bottom-left group (monster hunt, secret missions, heroes) is identical to the world screen, or trimmed.
- Whether the base is pannable / zoomable at all on the building level.
- Catalogue of building types and what each offers.
