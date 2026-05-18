# Modals

> Living document.

Most non-trivial interactions open a **modal window** layered over the current primary screen. The base or world map underneath stays visible but inactive. Modals can themselves change shape — e.g. clicking "hire" inside the heroes modal swaps it for the hire modal.

## General modal pattern

- A modal is dismissable (close button, often top-right, plus tap-outside or back-button equivalents — _TODO confirm_).
- Modals frequently contain **tabs** (filter rows, category strips, action groups).
- Modals can nest / chain: clicking deep into a modal opens another modal or replaces the current one. The bot must track that it's inside a modal stack, not on the base/world.
- "Slider" / horizontal carousel rows are common (e.g. the hire slider lists hire types).

## Specific modals

### Heroes (`Герои`)

Opened from the bottom-left of the [world screen](world.md).

Contents:

- List of heroes the player owns and those still locked.
- Quick filter tabs / quick-action buttons across the top — filter by hero type.
- A "hire" button at the bottom. Clicking it **replaces** the modal contents with the hire view.

#### Hire view (inside the heroes modal)

Contents:

- Large centre image showing what the tickets are being spent on.
- Two action buttons below:
  - **Hire ×1** — free once every ~2 days; otherwise consumes tickets.
  - **Hire ×10** — consumes tickets.
- After confirming a hire, a card-flip **cutscene** plays. The player can flip cards one by one, "flip all", or simply close — the result is fixed at the moment of hire; the cutscene is cosmetic.
- Bottom **slider** lists hire types:
  - Baseline: **hero hire**, **survivor hire**.
  - Seasonal: additional hire types — only the ticket type and rewards change; interaction is identical.

### Alliance (`Альянс`)

Opened from the bottom-right of the [world screen](world.md).

Contents:

- **Header** with alliance parameters and description.
- Action buttons (left-to-right or in a grid):
  - **Alliance gift** (`Подарок альянса`) — collect bonuses.
  - **Members** (`Участники`) — alliance member list.
  - **Help** (`Помощь`) — list of your in-flight builds/research and how much help you've received from members.
  - **Alliance shop** (`Магазин альянса`) — tabs with shops in internal alliance currencies.
  - Other buttons — to be detailed.

> _TODO: enumerate the remaining buttons in the alliance modal and what each does._

## Open questions

- How a modal closes — single close button, swipe, back-key equivalent, tap-outside?
- Are nested modals stacked (close brings you to the previous modal) or replaced (close goes straight to the primary screen)?
- Do modals ever auto-dismiss on timers / completed actions?
