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

/* ONE ACCOUNT IN THE PICKER (#2061): its face, its HQ level, the name the character
   goes by in the game and the name of the PROFILE that drives it — which are two
   different things and both are drawn. A closed profile has no light and answers out of
   what was written down the last time it was open (`panel/runtime/player_card.py`). */
export interface Account {
  name: string
  open?: boolean
  nick?: string
  level?: number
  avatar?: string
  colour?: Colour
  text?: string
  tip?: string[]
}

export interface Profiles {
  profiles: string[]
  home?: string
  showing?: string
  accounts?: Account[]
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

export interface ProgressStep {
  key: string
  text?: string
  state: 'running' | 'done' | 'failed'
  secs: number
}

export interface Progress {
  action: string
  label: string
  text?: string
  running: boolean
  ok?: boolean | null
  secs: number
  age: number
  steps: ProgressStep[]
  final?: { key: string; text?: string } | null
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
    /* Seconds since the game SERVER last answered, -1 while it never has (#2061). Green
       rests on that moment and it has a five-minute shelf life, so the colour is drawn
       with its age beside it. */
    server_age?: number
    controls?: Control[]
    recovery?: Recovery
  }
  link: { port?: number; busy?: boolean; user?: string; shared?: string[] }
  activity?: { name?: string; text?: string } | null
  /* WHERE THE LIFECYCLE PRESS HAS GOT TO (#2742). The steps the SCENARIO named itself
     (`STEP` in the recipe), each already said in this panel's language, with the seconds
     it took and whether it is running, done or the one it stopped on. `final` is the
     point the run ended at — «готово, клиент в игре» or why not — and it is what makes a
     press answerable half a minute after it was made. Null when nothing was pressed
     lately; a finished run stays for ten minutes. */
  progress?: Progress | null
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
  /* THE CARD COUNTS DOWN INSTEAD OF SAYING HOW OLD ITS READING IS (#2744) — set by the
     one errand that has a clock of its own, «Сбор ресурсов». The countdown is worked out
     from the row's own `next`, on the screen's clock, so nothing is asked of the game;
     an errand that is switched off has no next run and the age comes back. */
  countdown?: boolean
}

/* ONE RESOURCE THE BASE PAID TODAY, drawn as a picture and a short number (#2743).
 *
 * The person's words: «вместо количества прогонов, красиво и ровно выводим иконки
 * ресурсов что собрали сегодня, только те, что с базы, сокращаем до #.##M». `key` is a
 * locale key for the resource's name — used as the label when this machine has no
 * sprite, and as the title of the pill when it has — `value` is the short figure
 * («12.34M»), `exact` the same number in full, and `icon` a link to the game's own art,
 * empty where nothing was extracted. Nothing stands in for a missing picture. */
export interface ErrandRes {
  key: string
  value: string
  exact?: string
  icon?: string
  /* THE GAME'S OWN WORD FOR IT (#2744) — sent for the ITEMS the base's production lines
     pay in (drone parts, gears, the pet's training papers), which have no locale key and
     never will: the game already names them in the player's own language, and a second
     name written in the panel would be the panel naming something it did not make. When
     it is there it is used as-is; when it is not, `key` is a locale key as before. */
  label?: string
}

/* ONE PHASE OF «Гонка вооружений», for the sheet behind the card's «i» (#2579).
 *
 * The person asked for it in these words: «при нажатии на i, выводим иконками каждый час
 * события за сегодня и сколько там собрано сундуков в каждом часе». `label` is a locale
 * KEY — a phase the server invents tomorrow says so in words rather than putting a bare
 * number where a key belongs — `clock` is the window in the reader's own time, `chests`
 * is how many of its three were taken and `null` where nobody read that phase while it
 * was running (which is NOT the same as none), and `icon` is a link to the game's own
 * picture, empty where this machine has none. */
export interface ArmsPhase {
  stage?: number
  label: string
  clock?: string
  chests?: number | null
  all?: number
  icon?: string
}

/* THE HOUR OF «Гонка вооружений», ON THE CARD ITSELF (#2635).
 *
 * The person's words: «В карточке гонки выведи текущий час, сундуки которые взяты,
 * прямо как в игре, 3 сундука, серые и цветные, в зависимости от того взяты или нет.
 * Так же текущие очки гонки».
 *
 * `label` is a locale KEY for the kind of hour, `clock` its window in the reader's own
 * time, `points` the score against the top chest as the panel already words it (data,
 * ungrouped), `chests` one flag per chest of the hour — `null` where the game would not
 * say, which is NOT «none taken» — `icon` the game's own picture for the kind, `until`
 * the seconds the hour has left and `age` how old the reading is. */
export interface ArmsNow {
  label?: string
  clock?: string
  points?: string
  chests?: number[] | null
  icon?: string
  until?: number | null
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
  /* Whether one of this row's scenarios is out RIGHT NOW (#2408). A detached run — the
     golden hunt — is not «queued», so this is what turns the card's ▶ into a ■. */
  running?: boolean
  /* What the EDITOR needs and the list does not: the steps, the args, and the title the
     operator typed — empty on a built-in row, whose `title` above is a translated label
     and must not be sent back as one (#1976). */
  steps?: string[]
  args?: Record<string, unknown>
  custom_title?: string
  /* WHAT THIS ERRAND CARRIES (#2017) — the fields behind the gear on its row. Absent
     or empty for a row with no knobs, which is most of them. */
  options?: Field[]
  /* The picture drawn for this card, and one live line under it (#2019, #2340): a
     cover at card size, shown in full colour with the card's own signs moved out of its
     way. ABSENT IS NOT A SECOND FORMAT (#2407) — a row this machine has no cover for
     sends nothing and the card wears the one placeholder; the sprite fallback that used
     to make it a differently-drawn card is gone. */
  icon?: string
  /** Where the card crops that cover — a CSS vertical position, e.g. `"45%"` (#2340). */
  focus?: string
  stat?: ErrandStat | null
  /* WHAT THE BASE PAID TODAY (#2743) — sent by the two rows about the base's own pile
     and empty for every other errand, which therefore draws exactly what it did. */
  res?: ErrandRes[]
  /* THE CARD IS THE TALL TYPE (#2744) — half again as high as an ordinary one, so a row
     of chips too long for one line has somewhere to go. The PANEL decides and says so;
     the phone draws the one card component in the shape it is told. It is not a property
     of the errand: the same row is ordinary on a day the base paid four things. */
  tall?: boolean
  /* THE DAY, PHASE BY PHASE (#2579) — sent for «Гонка вооружений» alone, and only once
     the day's book has something in it. Every other errand sends nothing and the sheet
     grows no section. */
  phases?: ArmsPhase[]
  /* …and the hour running RIGHT NOW (#2635), on the face of the card rather than behind
     the «i». The same one row sends it and every other one leaves it out. */
  arms?: ArmsNow
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
  /* …and a listener's picture is a cover too since #2370, on the same terms a timer's
     is — and absent, the same placeholder (#2407). */
  icon?: string
  focus?: string
  stat?: ErrandStat | null
  /* WHAT THE BASE PAID TODAY (#2743) — the listener that watches the same pile. */
  res?: ErrandRes[]
  /* …and the TALL card when that row is long (#2744), on the same terms as a timer's. */
  tall?: boolean
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
  /* …and the same cover a timer and a listener may carry (#2370), or the same
     placeholder when there is none (#2407). */
  icon?: string
  focus?: string
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
  /* What fills the label's placeholders — the same thing `label_fmt` does for a field
     row, so a press whose words carry a number does not need a second mechanism. */
  label_fmt?: Record<string, unknown>
  args?: Record<string, unknown>
  prompt?: string
  value?: string
  /* A press that ASKS FIRST — a locale key, with `confirm_fmt` filling its placeholders.
     Destructive presses only: an ordinary one asked «are you sure?» is a press that
     arrives a second late every time (#1976). */
  confirm?: string
  confirm_fmt?: Record<string, unknown>
  /* THE SIGN THIS PRESS WEARS (#2621). Absent, the press is the wide text button a
     screen's actions have always been. `"run"` draws it as the errand card's own «▶» —
     the same class, the same size, the same place in the foot as «Таймеры» — because a
     card that IS the errand card must not carry a different button from it. The label
     stays: it becomes the button's title and what a screen reader says. */
  icon?: string
  /* A PRESS THAT IS ALREADY RUNNING, said by the tab rather than by this button (#2593).
     The button's own `busy` lasts only as long as the request; a jump to another warzone
     takes seconds after that, and the person pressed it again because nothing on the
     page said so. The tab holds the state and sends it here, so every copy of the button
     on the card goes dead — not only the one that was tapped. */
  disabled?: boolean
}

/* ONE ABILITY BEHIND A GEAR (#2624) — see `ViewItem.options_groups`. */
export interface OptionGroup {
  title?: string
  fields?: Field[]
  actions?: ViewAction[]
  items?: ViewItem[]
  note?: string
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
  /** The short form of the number a resource pill shows — `38.0M` (#2418). */
  short?: string
  /* WHICH SECTION OF A `grid` CARD THIS ITEM BELONGS TO (#2670) — a locale KEY, drawn
     as a heading with a line under it the first time it changes. It is how the autobuy's
     order is «отделено от остальных»: the queue is one group, the rest of the shelf is
     the next. Absent, and the items are one wall as before. */
  group?: string
  /* WHAT THIS ROW IS CALLED — a name of the panel's own choosing, stable across
     re-reads and reorders (#2670). It is what the front-end keys the row by and what an
     open sheet remembers: keyed by POSITION, a list that reorders when a knob is ticked
     hands the sheet to the row that took that place. Data, never a key to translate. */
  id?: string
  /* THIS ROW IS USED UP (#2670) — drawn grey, and with whatever presses the panel chose
     not to send it. The panel decides what «used up» means (a shop row whose quota is
     spent); the front-end only greys it. */
  dim?: boolean
  /* THIS ROW IS WORTH LOOKING AT (#2740) — «готовые карточки секретки измени цветом».
     The panel says WHICH of its own states the row is in and the front-end paints it with
     the colours it already has (`--ok`, `--warn`, `--bad`); there is no second theme and
     no colour anywhere in the panel. It is the counterpart of `dim`, which greys a row
     that is used up: this lifts one that is ready. */
  tone?: 'ok' | 'warn' | 'bad' 
  /* THE NAME THIS ITEM TRAVELS UNDER WHEN IT IS DRAGGED (#2670). Present exactly when
     the item may be reordered; the whole list of them comes back to the tab as one
     `set` press with the key `order`. */
  drag_id?: string
  /* WHAT A `grid` TILE SAYS UNDER THE PICTURE (#2670) — the price, already composed by
     the panel in the game's own words. Data, never a key. It is a field of its own and
     not one fact among several because on a shop tile it is the line the eye goes to. */
  price?: string
  icon?: string
  pill?: string
  facts?: Fact[]
  until?: number
  actions?: ViewAction[]
  /* WHAT THIS ITEM IS, for the card's own filter chips (#2737) — words of the panel's
     own choosing, matched against `ViewCard.filters`, never translated. A card with no
     filters ignores them. */
  tags?: string[]
  /* THE ONE SWITCH THIS ROW IS ABOUT (#2068). An account has one state — «работает» or
     not — and the switch that moves it belongs ON the row rather than behind its gear.
     Drawn by `ui/FieldRow.tsx`, like every other switch on this front-end, and sent back
     as the screen's own `set` press. */
  toggle?: Field
  /* WHY it is not simply working, in the panel's own words — data, already translated
     (`panel/web/api.py::_working_state`), never a key. */
  state?: string
  /* THE MARK THIS ROW WEARS AT ITS NAME (#2308) — a player's own note, drawn beside the
     title rather than on the line of facts under it, because a mark is the reason
     somebody looks a row up. Data, never a key. */
  badge?: string
  /* WHAT THE «i» IN THE CORNER OPENS (#2308), and it is FETCHED rather than carried: a
     page of a thousand players would otherwise pay for the dozen provenance lines of
     every one of them so that a person could read one. `kind` and `args` are what the
     phone asks `/api/screen/data` for, `title` is what to call the sheet (data). */
  info?: { kind: string; args?: Record<string, string>; title?: string }
  /* WHAT THE GEAR HOLDS WHEN IT HOLDS MORE THAN KNOBS (#2624) — the person's words:
     «Жмем шестеренку, видим галку открывать чипы, под ним кнопка открыть все и список
     чипов со статистикой». A group is one ABILITY: its switch, the press that runs it
     now, and whatever it is about, in that order. Several groups are several abilities
     on one row, drawn one under another; a row with none of them keeps `options` below,
     which is the plain case every other screen uses. */
  options_groups?: OptionGroup[]
  /* THE KNOBS THIS TILE OWNS, behind its own gear (#2051). A screen's card may be a
     grid of things that each have settings of their own — the rally groups are the
     first — and they open in the same sheet the errands' gear opens. */
  options?: Field[]
  /* What to call that sheet: a key, or the tile's own words when it has no key. */
  options_title?: string
  /* WHICH DRAWING OF THE ONE CARD THIS ROW WANTS (#2408). `"cover"` is the errand
     drawing «Таймеры» uses for every row it has: the picture behind the words, or the
     one placeholder when this machine has no cover for it. Absent, and the row is drawn
     as it has been — a picture beside the name, which is what a player's face is. It is
     a WORD and not a flag on purpose: there are two drawings, and the day there is a
     third it is named here rather than added as a second boolean.
     `"picture"` is that third (#2645): the ordinary row, with its icon drawn half the
     width of the card instead of as a stamp — a finished building is recognised by its
     own art long before its name is read. */
  shape?: 'cover' | 'picture'
  /* Where the card crops that picture — a CSS vertical position (#2340). */
  focus?: string
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
  /* `chips` is `choice` drawn as a STRIP of buttons instead of a dropdown (#2670) —
     the same chip the card strip and the sort bar are made of, so a thumb learns one
     shape. For a choice whose options are the page's own tabs: a shop's shelves are
     read by looking at them, and a dropdown hides eleven of the twelve. */
  kind: 'switch' | 'number' | 'text' | 'choice' | 'chips' | 'squads'
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

/* ONE SORT BUTTON OVER A GRID (#2308) — a column, and which way the list stands by it.
 *
 * The person's words: «Кнопки фильтра должны быть небольшие, клик по ним это
 * переключение по возрастанию/убыванию соответствующего фильтра». `dir` is `asc` or
 * `desc` on the ONE column the list is actually ordered by and empty on all the others,
 * so the row says where it stands without anybody pressing it. A press posts the card's
 * `sort` action with this `key`, and the panel flips the direction. */
export interface SortButton {
  key: string
  label: string
  dir?: string
}

export interface ViewCard {
  title?: string | null
  /* THE CARD A SCREEN OPENS ON (#2621) — the person's words: «в vs основным экраном
     делай неделю». A screen of more than two cards is drawn as a summary of tiles with a
     chip strip over it, which is right when the cards are peers and wrong when one of
     them IS the screen. The card that says `main` is what the screen opens on, and the
     summary chip is not offered at all: a page whose subject is one card does not need
     an index of itself. */
  main?: boolean
  /* HOW THE CARD'S ITEMS ARE DRAWN (#1999, #2119). Absent or `rows` is the full-width
     row a list has always been; `tiles` is a wrap of small buttons, for a card whose
     items are PLACES — a coordinate, a level, a state and the press that goes there;
     `cards` is the card an errand is drawn as (`ui/ErrandCard.tsx`), for a card whose
     items have a FACE — a picture behind them, a name on one line, a switch in the
     corner and their presses on one row.
     `grid` is the shop shelf (#2670): a small SQUARE tile — the item's own picture, its
     name on one line and its price under it, which is how the game itself draws a shop.
     The whole tile is the press where the item carries one. */
  layout?: 'rows' | 'tiles' | 'cards' | 'pills' | 'grid'
  head?: string
  head_parts?: MarkedText
  empty?: string
  search?: boolean
  flow?: { state?: string; colour?: string; key: string; fmt?: Record<string, unknown> }
  rows?: { label: string; value: string; value_parts?: MarkedText }[]
  items?: ViewItem[]
  /* A CARD WHOSE ITEMS ARE FETCHED RATHER THAN SENT (#2133). The register of players is
     three hundred thousand rows and a page of it is a thousand cards — some six hundred
     kilobytes, which may not ride a screen re-read every two and a half seconds. So the
     card carries no `items` and this instead: `kind` is what to ask
     `/api/screen/data` for, `size` is how many one page holds, and `stamp` MOVES
     whenever the page's contents changed — a merge that wrote rows, a turned page, a new
     sort, a new filter. The page is re-fetched when the stamp moves and at no other
     time, so a lap of the map refreshes the cards by itself and a lap that found nothing
     costs one unchanged integer. */
  paged?: { kind: string; size: number; stamp: string }
  actions?: ViewAction[]
  fields?: Field[]
  /* THE CARD'S OWN KNOBS, BEHIND ITS OWN GEAR (#2308) — the same sheet a tile's gear
     opens, one step up. A card that IS the grid keeps what narrows the grid on the grid,
     and out of the way: five controls standing open above a list are a list that starts
     below the fold. `options_title` is what to call the sheet (a key). */
  options?: Field[]
  options_title?: string
  /* HOW THE GRID IS ORDERED, as small buttons drawn directly over the rows (#2308). */
  sorts?: SortButton[]
  /* WHAT NARROWS THIS CARD, as chips over its items (#2737) — the person's words: «сделай
     кнопки-фильтры, только звездные дни секреток». One chip is chosen at a time and an
     `id` of `""` is «все»; an item is kept when its `tags` hold the chosen id. It is
     SCREEN STATE and nothing else: the chip lives in this front-end, the panel keeps no
     copy of it and no press is sent when one is tapped. `count` is drawn beside the word
     the way the card strip counts its cards. */
  filters?: { id: string; label: string; count?: number }[]
  /* THIS CARD'S ITEMS ARE DRAWN WHOLE (#2737) — no «Показать ещё» under them. For a card
     whose items are SMALL and whose whole point is the wall of them: the four hundred
     warzones of «Куда идти сегодня» are a chart a person reads at a glance, and cut to
     thirty they are a list nobody pages through. A card of wide rows keeps the cut. */
  whole?: boolean
  /* WHAT THE NUMBER BESIDE THE HEADING COUNTS, when it is not «how many rows» (#2740).
     The person's words: «счетчик во вкладке с секретками выводим только готовые». A list
     of eighty-two tiles of which twelve can be taken is answered by «12», not by «82» —
     the count is read as «how much is there for me», and the total is the one number that
     does not say that. The panel decides what it counts; the front-end only draws it, and
     a card that sends none is counted by its rows exactly as before. */
  count?: number
  note?: string
  /* ALREADY DRAWN BY THE PICTURE ABOVE (#2064). A screen that is DRAWN rather than
     listed still sends its cards, so a front-end that does not know that kind shows
     something; one that does draws the picture and skips these. */
  drawn?: boolean
}

export interface Screen {
  id: string
  title: string
}

export interface ScreenView {
  title?: string
  now?: number
  /** Warzone from the same confirmed jump that released this screen's button. */
  header_server?: number
  cards?: ViewCard[]
  actions?: ViewAction[]
  /* A SCREEN THAT IS DRAWN RATHER THAN LISTED (#2018). The tab says what kind of
     picture it has; the renderer for it fetches its own data off
     `/api/screen/data`, because a scene of thirty thousand objects may not ride the
     screen's poll (`panel/tabs/base.py::web_data`). */
  map?: { kind: string }
  /* The chat's channels, for the screen the chat DRAWS (#2064): which ones there are,
     which room each is, and how many messages arrived in one nobody was looking at. */
  rooms?: ChatRoomTab[]
  /* Is the chat monitor running — the reader child that hears the pushes and files
     them (#2064)? With it off the history simply stops growing, and the phone must be
     able to see that and to start it, not only the window. */
  listening?: boolean
  /* HOW OLD THE CHAT'S NEWEST MESSAGE IS, in seconds (#2418). A reading with no age on
     it is read as fresh, and an ear that died three days ago looks exactly like a quiet
     evening. */
  silent?: number | null
  /* The monitor is wanted but the reader is not up — it died and is being brought back. */
  waiting?: boolean
}

/** One channel of the chat: «Мир», «Альянс», «ЛС» … with its unread count. */
export interface ChatRoomTab {
  type: string
  room: string
  unread: number
  /* WHAT TO CALL IT (#2418). The list is the CLIENT's, so a chip may be a room the
     panel has no word for: `key` is a locale key when the id says what the room is, and
     `label` is the name the client itself gave it — which only a player's own custom
     group ever has. Exactly one of the two is set. */
  key?: string
  label?: string
  /* WHICH PART OF THE LIST IT BELONGS TO (#2418) — `channel`, `group` or `people`, in
     that order. The order is the panel's, so a new kind of room lands in the right
     place without the front-end learning about it. */
  section?: string
  /* The face drawn beside it: a player's own picture for a private conversation, and
     `''` for a room or a player that has none — those draw an initial, never somebody
     else's art. */
  face?: string
  /* The last thing said in a private conversation, and when — for the row's subtitle. */
  text?: string
  ts?: number
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
