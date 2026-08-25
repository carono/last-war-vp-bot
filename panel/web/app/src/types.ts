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
  gate?: { held?: boolean; for_sec?: number }
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
}

export interface Fact {
  label: string
  value: string
  translate?: boolean
}

export interface ViewAction {
  id: string
  label: string
  args?: Record<string, unknown>
  prompt?: string
  value?: string
}

export interface ViewItem {
  label?: string
  text?: string
  detail?: string
  note?: string
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
  kind: 'switch' | 'number' | 'text'
  value: string | number | boolean
  min?: number
  max?: number
}

export interface ViewCard {
  title?: string | null
  head?: string
  empty?: string
  search?: boolean
  flow?: { state?: string; colour?: string; key: string; fmt?: Record<string, unknown> }
  rows?: { label: string; value: string }[]
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
  pending?: boolean
  error?: string
  reason?: string
  detail?: string
  queued?: boolean
  unavailable?: boolean
  stopped?: string[]
}
