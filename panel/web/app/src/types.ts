/* The shapes `panel/web/api.py` answers with.
 *
 * Deliberately loose where the panel is loose: a card, an item and a control are grown
 * by whichever tab drew them, and a front-end that insisted on knowing every field
 * would have to be edited every time a tab learns a new one. What is typed here is what
 * the renderer actually reads.
 */

export type Colour = 'ok' | 'warn' | 'bad' | string

export interface Control {
  id: string
  label: string
  enabled?: boolean
  running?: boolean
  confirm?: string
}

export interface Light {
  name: string
  colour: Colour
  text?: string
  tip?: string[]
}

export interface Profiles {
  profiles: string[]
  home?: string
  showing?: string
  lights?: Light[]
}

export interface Recovery {
  held_by?: string
  kick_hold_left?: number
  player_hold_left?: number
  stalled_for?: number
  stalled_next?: number
  stalled_restarts?: number
  fruitless?: number
  barren?: number
  barren_of?: number
  cooldown_left?: number
  deaf_for?: number
  strikes?: number
  restarts?: number
}

export interface RunningRun {
  name: string
  step?: string
}

export interface State {
  profile: string
  time: number
  game: {
    running?: boolean
    colour?: Colour
    reason?: string
    text?: string
    controls?: Control[]
    recovery?: Recovery
  }
  link: { port?: number; busy?: boolean; user?: string; shared?: string[] }
  activity?: { name?: string; text?: string } | null
  interrupt?: { running?: RunningRun[]; elsewhere?: number; stopping?: boolean }
  timers: { on: number; next?: number | null; next_name?: string }
  power?: { on?: boolean; off_for_sec?: number }
  watchdog?: boolean
  gate?: { held?: boolean; for_sec?: number; reason?: string }
  panel?: { version?: string; controls?: Control[] }
}

export interface TimerRow {
  name: string
  title: string
  enabled: boolean
  immediate?: boolean
  interval_sec: number
  weekdays?: number[]
  next?: number | null
  last?: number | null
  last_state?: string
  retry_sec?: number
  queued?: boolean
  /* What the EDITOR needs and the list does not: the steps, the args, and the title the
     operator typed — empty on a built-in row, whose `title` above is a translated label
     and must not be sent back as one (#1976). */
  steps?: string[]
  args?: Record<string, unknown>
  custom_title?: string
}

export interface TriggerRow {
  name: string
  title: string
  enabled: boolean
  immediate?: boolean
  poll?: boolean
  signal?: string
  status?: string
}

export interface ActionRow {
  name: string
  title: string
}

export interface LogLine {
  text: string
  sev?: string
  text_parts?: MarkedText
}

/* A COORDINATE THE PANEL HAS MARKED (#1982). The parsing is the panel's — one parser,
 * `tools/lib/coords.py` — and what arrives here is the string already cut into plain
 * pieces and places. See `panel/web/coordlinks.py`. */
export interface CoordPart {
  x: number
  y: number
  server: number
  text: string
}

export type MarkedText = ({ t: string } | { c: CoordPart })[]

export interface Fact {
  label: string
  value: string
  translate?: boolean
  value_parts?: MarkedText
}

export interface ViewAction {
  id: string
  label: string
  args?: Record<string, unknown>
  prompt?: string
  value?: string
  /* A press that ASKS FIRST — a locale key, with `confirm_fmt` filling its placeholders.
     Destructive presses only: an ordinary one asked «are you sure?» is a press that
     arrives a second late every time (#1976). */
  confirm?: string
  confirm_fmt?: Record<string, unknown>
}

export interface ViewItem {
  label?: string
  text?: string
  detail?: string
  note?: string
  text_parts?: MarkedText
  detail_parts?: MarkedText
  note_parts?: MarkedText
  avatar?: string
  icon?: string
  pill?: string
  facts?: Fact[]
  until?: number
  actions?: ViewAction[]
}

export interface Field {
  key: string
  label: string
  hint?: string
  kind: 'switch' | 'number' | 'text' | 'choice'
  value: string | number | boolean
  min?: number
  max?: number
  /* `value` is the id the panel knows; `text` is what that choice calls ITSELF — data,
   * like a player's name, never a key to translate. */
  options?: { value: string; text: string }[]
}

export interface ViewCard {
  title?: string | null
  head?: string
  head_parts?: MarkedText
  empty?: string
  search?: boolean
  flow?: { state?: string; colour?: string; key: string; fmt?: Record<string, unknown> }
  rows?: { label: string; value: string; value_parts?: MarkedText }[]
  items?: ViewItem[]
  actions?: ViewAction[]
  fields?: Field[]
  note?: string
}

export interface Screen {
  id: string
  title: string
}

export interface ScreenView {
  title?: string
  now?: number
  cards?: ViewCard[]
  actions?: ViewAction[]
}

export interface PressAnswer {
  ok?: boolean
  /* What to put into `reason`'s placeholders — «имя «{name}» уже занято». */
  fmt?: Record<string, unknown>
  pending?: boolean
  error?: string
  reason?: string
  detail?: string
  queued?: boolean
  unavailable?: boolean
  stopped?: string[]
}
