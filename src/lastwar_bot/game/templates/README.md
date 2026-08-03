# UI templates — not shipped, cropped locally

This directory is **empty in a fresh clone, and that is deliberate.** Every file that
belongs here is a crop of a running game client — a screenshot of somebody's screen,
carrying whatever their client happened to be showing. The repository is public, so
none of them are committed (`.gitignore` covers `*.png` here); they are made on the
machine that runs the bot, from that machine's own client.

Nothing breaks quietly without them. The vision paths say so and carry on:

* `FIND` / `CLICK` / `PRESS` in a scenario raise «template not found: `<name>`» with
  this file's path in the message, instead of failing as if the scenario were wrong.
* Screen detection (`identify_screen`, «am I in the base or on the world map?») prints
  one line per missing template and answers «I cannot tell» rather than raising.

## What depends on them

| Template | Used by |
|---|---|
| `toggle_to_world.png`, `toggle_to_world_fs.png` | screen detection, «go to world» |
| `toggle_to_base.png`, `toggle_to_base_fs.png` | screen detection, «go to base» |
| `inventory.png`, `inventory_fs.png`, `inventory_world_fs.png` | «is the game chrome on screen» |
| `world_zoom_reset.png` | resetting the world-map zoom |
| `kicked_modal.png` | the watchdog's «logged in elsewhere» modal |
| `profile_modal_marker.png`, `profile_edit_button.png`, `profile_female_ico.png`, `profile_modal_close.png` | the profile-capture dev scenarios |
| `accept_likes.png` | the «thanks» button after a like |
| `res_*.png` (bread, exp, gold, material, oil, ore, steel) | `tools/dev/scan_resources.py` |
| `alliane_present.png`, `alliane_tech.png`, `hat_farming.png` | alliance gift / tech icons, ministry banner |

Everything the bot does **headlessly** — through the Lua daemon, which is nearly all
of it — needs none of this. Templates matter only to the pixel-driven paths.

## Making one

The panel's region picker crops and saves straight into this directory:

```
python -m lastwar_bot.ui_region
```

Point it at the running client, drag a box around the element, and give it the file
name from the table above. Keep the crop tight — just the distinctive part of the
button or icon, without surrounding background, which is what makes it match at
different window sizes. A PNG with an alpha channel is treated as a masked template
(transparent pixels are ignored), which helps for icons on a varying background.

`_fs` in a name means the full-screen variant of the same element: the client draws
some chrome differently when the window is maximised, so both crops exist and
whichever matches better wins.
