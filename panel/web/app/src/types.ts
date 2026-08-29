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
  /* The palette, and it rides THIS answer because it is the PANEL's rather than an
     account's (#2061) — «Цветовая тема, это настройка панели, не аккаунта». */
  theme?: string
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

/* THE STRIP ALONG THE TOP (#2016, panel/runtime/header.py). Who this character is, and
 * where they are standing in the client right now. `scene` is the game's own answer —
 * `city` / `world` / `pve`, or `unknown` while it is loading; `window` is the game's id
 * of the screen on top, empty when the player is looking at the scene itself; `age` is
 * how many seconds old the place reading is, -1 when nothing has been read yet. */
export interface Header {
  nick?: string
  level?: number
  scene?: string
  window?: string
  depth?: number
  server?: number
  home?: number
  age?: number
  reading?: boolean
}

export interface State {
  profile: string
  time: number
  header?: Header
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
  /* `age` is seconds since the stock was read, -1 when it never has been. */
  power?: { on?: boolean; off_for_sec?: number }
  watchdog?: boolean
  gate?: { held?: boolean; for_sec?: number; reason?: string }
  panel?: { version?: string; controls?: Control[] }
}

/* ONE LIVE LINE UNDER AN ERRAND'S BLOCK (#2019) — «+377 023 ждёт сбора» under «Сбор
 * ресурсов». `key` is a locale key and `fmt` its placeholders, so the panel sends data
 * and the phone says the words. `age` is seconds since the reading it came from, and
 * `null` when the source has no clock of its own (a day's tally is «сегодня»).
 *
 * Bought with NO reading: every one of these comes off something the panel already had
 * (`panel/runtime/errand_stats.py`). An errand with nothing free to say has no `stat`,
 * and that blank is the honest answer rather than a gap. */
export interface ErrandStat {
  key: string
  fmt?: Record<string, unknown>
  age?: number | null
}

export interface TimerRow {
  name: string
  title: string
  /* THE SENTENCE THE SHORT NAME WAS CUT OUT OF (#2061) — what the «i» on the card opens.
     Empty when the label has no short form, and then no «i» is drawn. */
  about?: string
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
  /* WHAT THIS ERRAND CARRIES (#2017) — the fields behind the gear on its row. Absent
     or empty for a row with no knobs, which is most of them. */
  options?: Field[]
  /* The game's own picture for it, and one live line under it (#2019). */
  icon?: string
  stat?: ErrandStat | null
}

export interface TriggerRow {
  name: string
  title: string
  /* THE SENTENCE THE SHORT NAME WAS CUT OUT OF (#2061) — what the «i» on the card opens.
     Empty when the label has no short form, and then no «i» is drawn. */
  about?: string
  enabled: boolean
  immediate?: boolean
  poll?: boolean
  signal?: string
  status?: string
  /* The knobs behind this listener's gear (#2017) — what the auto-join may spend. */
  options?: Field[]
  icon?: string
  stat?: ErrandStat | null
}

/* A STANDING ORDER THAT IS IN NO CATALOGUE (#2017): «Автолут ★», «Автопомощь»,
 * «Автолут отрядов призрака». A watcher a tab owns, drawn among the listeners because
 * that is what it is to a person. `state` is what it is doing right now, in the panel's
 * own words — already translated, like a reading and unlike `title`'s neighbours. */
export interface OrderRow {
  name: string
  title: string
  /* THE SENTENCE THE SHORT NAME WAS CUT OUT OF (#2061) — what the «i» on the card opens.
     Empty when the label has no short form, and then no «i» is drawn. */
  about?: string
  enabled: boolean
  state?: string
  hint?: string
  options?: Field[]
  icon?: string
  stat?: ErrandStat | null
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
  /* THE KNOBS THIS TILE OWNS, behind its own gear (#2051). A screen's card may be a
     grid of things that each have settings of their own — the rally groups are the
     first — and they open in the same sheet the errands' gear opens. */
  options?: Field[]
  /* What to call that sheet: a key, or the tile's own words when it has no key. */
  options_title?: string
}

/* ONE SQUAD ON THE PICKER (#2062) — the slot, whether it is on, and the faces standing
 * in it. `faces` are links into `/api/heroicon`, empty when this machine has no picture
 * for any of that squad's heroes, and then the tile draws the slot's number instead of a
 * face that belongs to somebody else's hero. `state` is what the squad is doing, in the
 * panel's own word (`squads.kind.*`) — a caption, never a gate. */
export interface SquadSlot {
  n: number
  on: boolean
  faces?: string[]
  state?: string
}

export interface Field {
  key: string
  label: string
  /* What goes into the label's placeholders — «Отряд {n}» is one key and four knobs
     (#2017). Data, filled in by the panel, never a second key to translate. */
  label_fmt?: Record<string, unknown>
  hint?: string
  kind: 'switch' | 'number' | 'text' | 'choice' | 'squads'
  value: string | number | boolean
  min?: number
  max?: number
  /* `value` is the id the panel knows; `text` is what that choice calls ITSELF — data,
   * like a player's name, never a key to translate. */
  options?: { value: string; text: string }[]
  /* `squads` ONLY (#2062): the four slots as the panel drew them, and whether exactly
   * one of them may be picked (the golden-zombie hunt sends one; the rally auto-join
   * spends as many as it is given). The value is the slots that are on, joined by
   * commas — «1,3». */
  squads?: SquadSlot[]
  single?: boolean
}

export interface ViewCard {
  title?: string | null
  /* HOW THE CARD'S ITEMS ARE DRAWN (#1999). Absent or `rows` is the full-width row a
     list has always been; `tiles` is a wrap of small buttons, for a card whose items
     are PLACES — a coordinate, a level, a state and the press that goes there. */
  layout?: 'rows' | 'tiles'
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
  /* A SCREEN THAT IS DRAWN RATHER THAN LISTED (#2018). The tab says what kind of
     picture it has; the renderer for it fetches its own data off
     `/api/screen/data`, because a scene of thirty thousand objects may not ride the
     screen's poll (`panel/tabs/base.py::web_data`). */
  map?: { kind: string }
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
