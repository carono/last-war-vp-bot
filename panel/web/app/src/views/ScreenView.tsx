import type { ReactNode } from 'react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { get, post } from '../api'
import { t, when } from '../i18n'
import { pressWord } from '../ui/press'
import { useToast } from '../ui/Toast'
import { ErrandCard, ErrandSwitch } from '../ui/ErrandCard'
import { FieldRow } from '../ui/FieldRow'
import { Modal } from '../ui/Modal'
import { firstPlace, Marked, useJump } from '../ui/Coord'
import { WorldMap } from './WorldMap'
import { ChatView } from './ChatView'
import type { Field, OptionGroup, PressAnswer, ScreenView as View, SortButton, ViewAction, ViewCard, ViewItem } from '../types'

/* ONE RENDERER FOR EVERY TAB'S SCREEN.
 *
 * `title`, `label`, `empty` and `pill` are locale KEYS and go through `t()`; `head`,
 * `text`, `value`, `detail` and `note` are DATA — a player's name, a count, a date — and
 * are shown as they are (`panel/tabs/base.py`). Getting that backwards is how a screen
 * ends up showing `secret.tasks.left` to a person or a nickname to a translator.
 *
 * A tab's screen is DATA, so a tab that grows a card, a reading or a button reaches the
 * phone without a line of this file changing.
 */

function PressButton({
  action,
  screen,
  after,
}: {
  action: ViewAction
  screen: string
  after: () => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  /* A pending press outlives its HTTP request. The next screen answer changes
     `disabled` to true, and the answer after the confirmed landing changes it back;
     only that second edge releases the local lock that closed the request-to-poll gap. */
  useEffect(() => {
    if (action.disabled === false) setBusy(false)
  }, [action.disabled])
  /* THE SAME «▶» «Таймеры» DRAWS (#2621), when the press asks for it. Not a second
     button: the same classes the errand card's own run button wears, so the two pages
     cannot drift apart by a stylesheet. The label becomes the title, which is how a
     card with two of them says which is which. */
  const sign = action.icon === 'run'
  const label = t(action.label)
  return (
    <button
      className={sign ? 'go icon run' : 'go'}
      title={sign ? label : undefined}
      aria-label={sign ? label : undefined}
      disabled={busy || !!action.disabled}
      onClick={async () => {
        let pending = false
        let args = action.args || {}
        /* A press that DELETES asks first, in the panel's own sentence — the same one
         * the window's message box asks in (#1976). Only where the tab said so: an
         * ordinary press wearing a confirmation is a press that is always a second
         * late. */
        if (action.confirm && !window.confirm(t(action.confirm, action.confirm_fmt))) return
        /* A press that needs a WORD from the person (#1335). Without it the phone could
         * read a note and never write one, and the window would have a control the phone
         * has not. `prompt` is a locale KEY; `value` is the text the box opens with
         * (data). Cancelling presses nothing at all, which is the one thing a prompt has
         * to get right. */
        if (action.prompt) {
          const typed = window.prompt(t(action.prompt), action.value || '')
          if (typed === null) return
          args = { ...args, text: typed }
        }
        setBusy(true)
        try {
          const answer = await post<PressAnswer>('/api/screen/press', {
            id: screen,
            action: action.id,
            args,
          })
          toast(pressWord(answer))
          pending = !!answer.pending
          // The tab reads on its own thread, so the result is a moment behind the press.
          if (pending) after()
          else window.setTimeout(after, 900)
        } finally {
          if (!pending) setBusy(false)
        }
      }}
    >
      {sign ? '\u25B6' : label}
    </button>
  )
}

/* The screen's own way of sending a moved knob: the tab's `set` press. The control
 * itself is `ui/FieldRow.tsx` — the gear on «Таймеры» draws the same one (#2017). */
/* ONE TILE'S OWN SETTINGS, behind a gear and inside a sheet (#2051).
 *
 * The same gesture «Таймеры» has had since #2017 and the same sheet since #2051 — a
 * press opens a modal, never a collapse that pushes the list around under the thumb.
 * The knobs are ordinary screen fields, so they travel back through the screen's own
 * `set` press and no new route is needed.
 */
function useItemGear(item: ViewItem, screen: string, after: () => void) {
  const [open, setOpen] = useState(false)
  const options = item.options || []
  /* THE GEAR MAY HOLD ABILITIES RATHER THAN A LIST OF KNOBS (#2624). Same sheet, same
     component, same way of closing — what changes is only what is inside it: per
     ability, its switch, the press that runs it, and what it is about. */
  const groups: OptionGroup[] = item.options_groups || []
  if (!options.length && !groups.length) return { button: null, sheet: null }
  const name = item.options_title ? t(item.options_title) : (item.label ? t(item.label) : item.text || '')
  return {
    button: (
      <button
        className="go icon"
        title={t('web.ui.options')}
        aria-label={t('web.ui.options')}
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true)
        }}
      >
        {'\u2699'}
      </button>
    ),
    sheet: open ? (
      <Modal title={name} onClose={() => setOpen(false)}>
        {groups.map((group, gi) => (
          <div className="item" key={'g' + gi}>
            {group.title ? <b>{t(group.title)}</b> : null}
            {(group.fields || []).map((field) => (
              <ScreenField key={field.key} field={field} screen={screen} after={after} />
            ))}
            {(group.actions || []).length ? (
              <div className="foot">
                {(group.actions || []).map((action) => (
                  <PressButton key={action.id + String(action.args?.key || '')}
                               action={action} screen={screen} after={after} />
                ))}
              </div>
            ) : null}
            {(group.items || []).map((row, ri) => (
              <Item key={'i' + ri} item={row} now={0} screen={screen} after={after} />
            ))}
            {group.note ? <p className="muted small">{group.note}</p> : null}
          </div>
        ))}
        {options.map((field) => (
          <ScreenField key={field.key} field={field} screen={screen} after={after} />
        ))}
      </Modal>
    ) : null,
  }
}

/* THE GRID'S OWN KNOBS, behind the gear beside its heading (#2308).
 *
 * The person's words about the register of players: «фильтры к гриду перенеси». They
 * stood in a card of their own above the list — a screenful of controls a person had to
 * scroll past to reach the first row, and six cycling presses at that. A card may now
 * carry `options`, and they open in the ONE modal this front-end has, exactly as a
 * tile's gear does one step down (`useItemGear`). Nothing new is written: the knobs are
 * ordinary screen fields and travel back through the screen's own `set` press.
 */
function useCardGear(card: ViewCard, screen: string, after: () => void) {
  const [open, setOpen] = useState(false)
  const options = card.options || []
  if (!options.length) return { button: null, sheet: null }
  const name = card.options_title ? t(card.options_title) : card.title ? t(card.title) : ''
  return {
    button: (
      <button
        className="go icon"
        title={t('web.ui.options')}
        aria-label={t('web.ui.options')}
        onClick={() => setOpen(true)}
      >
        {'\u2699'}
      </button>
    ),
    sheet: open ? (
      <Modal title={name} onClose={() => setOpen(false)}>
        {options.map((field) => (
          <ScreenField key={field.key} field={field} screen={screen} after={after} />
        ))}
      </Modal>
    ) : null,
  }
}

/* HOW THE GRID IS ORDERED, as a row of small buttons over the rows themselves (#2308).
 *
 * One button per column. The one the list actually stands by wears its direction and
 * says so; pressing it flips ascending ↔ descending, and pressing another orders by
 * that column instead. It is the window's own gesture — a click on a table heading —
 * and it replaces two dropdowns that stood in a card four taps away from the rows they
 * ordered.
 *
 * The chip is the SAME control the card strip is drawn with, so a thumb learns one
 * shape; the arrow is the whole of the state, and a column that is not sorting anything
 * shows none.
 */
function SortBar({ sorts, screen, after }: { sorts: SortButton[]; screen: string; after: () => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState('')
  return (
    <div className="chips sorts">
      {sorts.map((sort) => (
        <button
          key={sort.key}
          className={'chip' + (sort.dir ? ' on' : '')}
          disabled={busy === sort.key}
          onClick={async () => {
            setBusy(sort.key)
            try {
              const answer = await post<PressAnswer>('/api/screen/press', {
                id: screen,
                action: 'sort',
                args: { key: sort.key },
              })
              if (answer.ok === false || answer.error) toast(pressWord(answer))
              window.setTimeout(after, 400)
            } finally {
              setBusy('')
            }
          }}
        >
          {t(sort.label)}
          {sort.dir ? <span className="way">{sort.dir === 'desc' ? '\u2193' : '\u2191'}</span> : null}
        </button>
      ))}
    </div>
  )
}

/* THE «i» IN A CARD'S TOP-RIGHT CORNER, and what it opens (#2308).
 *
 * The person's words about a base's card: «Убираем все кнопки. Добавляем аккуратный i в
 * правом верхнем углу, которая вызывает модалку с подробными данными базы». So the card
 * itself is what a person reads at a glance, and everything else — every field with who
 * said it and when, and the presses that act on that row — is one tap away in the one
 * modal.
 *
 * IT IS FETCHED WHEN IT IS OPENED, never carried: a dozen lines times a page of a
 * thousand rows would double what a page costs so that one of them could be read. The
 * card says WHAT to ask for (`item.info`) and this asks `/api/screen/data` for it, which
 * is answered on a worker rather than on the panel's own loop.
 */
interface InfoAnswer {
  title?: string
  rows?: { label: string; value: string; value_parts?: ViewItem['text_parts'] }[]
  actions?: ViewAction[]
  error?: string
}

function useItemInfo(item: ViewItem, screen: string, after: () => void) {
  const info = item.info
  const [open, setOpen] = useState(false)
  const [answer, setAnswer] = useState<InfoAnswer | null>(null)
  const kind = info ? info.kind : ''
  const args = info && info.args ? info.args : {}
  const key = JSON.stringify(args)
  useEffect(() => {
    if (!open || !kind) return
    let alive = true
    void (async () => {
      const query = Object.entries(JSON.parse(key) as Record<string, string>)
        .map(([k, v]) => '&' + encodeURIComponent(k) + '=' + encodeURIComponent(String(v)))
        .join('')
      try {
        const got = await get<InfoAnswer>(
          '/api/screen/data?id=' + encodeURIComponent(screen) + '&kind=' + encodeURIComponent(kind) + query,
        )
        if (alive) setAnswer(got)
      } catch {
        /* the screen's own tick says when the panel is unreachable */
      }
    })()
    return () => {
      alive = false
    }
  }, [open, kind, key, screen])
  if (!info) return { button: null, sheet: null }
  const name = info.title || (item.label ? t(item.label) : item.text || '')
  return {
    button: (
      <button
        className="go icon"
        title={t('web.ui.about')}
        aria-label={t('web.ui.about')}
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true)
        }}
      >
        {'\u2139'}
      </button>
    ),
    sheet: open ? (
      <Modal title={name} onClose={() => setOpen(false)}>
        {(answer?.rows || []).map((row, i) => (
          <div className="kv" key={i}>
            <span className="k">{t(row.label)}</span>
            <span className="v">
              <Marked text={row.value} parts={row.value_parts} />
            </span>
          </div>
        ))}
        {/* THE PRESSES THAT WERE ON THE CARD, beside the data they act on. A card of a
            thousand rows carries none of them; nothing is lost, because this sheet is
            one tap from every row. */}
        {(answer?.actions || []).length ? (
          <div className="foot">
            {(answer?.actions || []).map((action) => (
              <PressButton key={action.id} action={action} screen={screen} after={after} />
            ))}
          </div>
        ) : null}
      </Modal>
    ) : null,
  }
}

function ScreenField({ field, screen, after }: { field: Field; screen: string; after: () => void }) {
  return (
    <FieldRow
      field={field}
      after={after}
      send={(key, value) =>
        post<PressAnswer>('/api/screen/press', { id: screen, action: 'set', args: { key, value } })
      }
    />
  )
}

function Item({ item, now, screen, after }: { item: ViewItem; now: number; screen: string; after: () => void }) {
  const gear = useItemGear(item, screen, after)
  const facts = item.facts || []
  /* EVERY PIECE OF PROSE ON A ROW CAN HOLD A PLACE (#1982): the name of the tile, the
   * detail beside it, the note under it and each fact. They are drawn through `Marked`,
   * which turns what the panel marked into buttons and leaves everything else alone. */
  const bits: ReactNode[] = facts.map((f, i) => (
    <span key={i}>
      {i ? ' · ' : ''}
      {t(f.label)}{' '}
      {f.value_parts ? (
        <Marked text={f.value} parts={f.value_parts} />
      ) : f.translate && f.value ? (
        t(f.value)
      ) : (
        f.value
      )}
    </span>
  ))
  if (item.until) bits.push(<span key="until">{(bits.length ? ' · ' : '') + when(item.until, now || item.until)}</span>)
  return (
    <div className="item">
      <div className="row">
        {/* A FACE and AN ICON are LINKS into the panel's own routes, never bytes inside
            the view: the browser keeps them, so a screen repainting every couple of
            seconds fetches each one once (#1324, #1469). One that will not load simply
            leaves the name alone. */}
        {item.avatar ? <img className="face" src={item.avatar} alt="" /> : null}
        {item.icon ? <img className="icon" src={item.icon} alt="" /> : null}
        <span className="title">
          {item.label ? t(item.label) : <Marked text={item.text} parts={item.text_parts} />}
        </span>
        {item.detail ? (
          <span className="muted small">
            <Marked text={item.detail} parts={item.detail_parts} />
          </span>
        ) : null}
        {gear.button}
      </div>
      {gear.sheet}
      {item.note ? (
        <p className="muted small">
          <Marked text={item.note} parts={item.note_parts} />
        </p>
      ) : null}
      {bits.length ? <p className="muted small">{bits}</p> : null}
      {/* WHAT THIS ROW IS, AND THE ONE SWITCH THAT MOVES IT (#2068). An account says
          «работает» / «работает, но…» / «не работает» and carries a switch, and the
          switch is the same control every other switch on this front-end is — a `Field`
          through `FieldRow`, so there is nothing here to keep in step with it. */}
      {item.state ? <p className="muted small">{item.state}</p> : null}
      {item.toggle ? <ScreenField field={item.toggle} screen={screen} after={after} /> : null}
      {item.pill || (item.actions || []).length ? (
        <div className="foot">
          <span className="pill">{item.pill ? t(item.pill) : ''}</span>
          {(item.actions || []).map((action) => (
            <PressButton key={action.id} action={action} screen={screen} after={after} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

/* ONE ITEM OF A `layout: "cards"` CARD (#2119) — the SAME card an errand is drawn as.
 *
 * The person's words: «переделай таблицу игроков на карточки». A register of three
 * hundred thousand players was nine columns of a table, which on a phone is nine columns
 * nobody reads; and the shape it becomes is deliberately not a fourth one of this
 * front-end's own. It is `ui/ErrandCard.tsx`: the picture at full brightness behind the
 * card, the words in one bubble over it, the name on a single line, the switch — where
 * the item has one — in the top-right corner, and the presses on one short row at the
 * bottom.
 *
 * WHAT A PLAYER BRINGS TO IT: their own face out of the client's cache as the picture,
 * their name, and one line of facts — the level, the power, the alliance, where they
 * stand and when they were last seen. Their mark goes on that line too, because a mark
 * is the reason somebody looks a player up.
 *
 * The gear is the SAME sheet a tile's is (`useItemGear`) — one modal on this front-end
 * and never a second (`CLAUDE.md`).
 */
function CardItem({ item, now, screen, after }: { item: ViewItem; now: number; screen: string; after: () => void }) {
  const gear = useItemGear(item, screen, after)
  /* THE «i» IN THE CORNER (#2308) — everything this row is, and everything that can be
     done to it, one tap away and off the card itself. */
  const info = useItemInfo(item, screen, after)
  const title = item.label ? t(item.label) : item.text || ''
  /* Everything the card says under its name, as one line: what the row is (`detail`),
     the mark on it (`note`), each fact with its own word, and the countdown. A tile
     leaves the prose off on purpose (#1999) — a card has the room for it, and on a
     player that prose IS the answer. */
  const bits: ReactNode[] = []
  if (item.detail) bits.push(<Marked key="d" text={item.detail} parts={item.detail_parts} />)
  /* A row that wears its mark AT ITS NAME does not say it a second time underneath
     (#2308) — that is what `badge` is, and a row with no badge keeps the old line. */
  if (item.note && !item.badge) bits.push(<Marked key="n" text={item.note} parts={item.note_parts} />)
  bits.push(
    ...(item.facts || []).map((f, i) => (
      <span key={'f' + i}>
        {t(f.label)}{' '}
        {f.value_parts ? <Marked text={f.value} parts={f.value_parts} /> : f.translate && f.value ? t(f.value) : f.value}
      </span>
    )),
  )
  if (item.until) bits.push(<span key="u">{when(item.until, now || item.until)}</span>)
  const facts: ReactNode[] = []
  bits.forEach((bit, i) => {
    if (i) facts.push(<span key={'s' + i}>{' · '}</span>)
    facts.push(bit)
  })
  return (
    <ErrandCard
      icon={item.avatar || item.icon}
      /* THE ERRAND DRAWING, WHERE A ROW ASKS FOR IT (#2408) — the golden-zombie hunt is
         the first: it is an errand in everything but the catalogue it is not in, so it
         is drawn as one, and a machine with no cover for it wears the same placeholder
         every other errand card does. */
      cover={item.shape === 'cover'}
      focus={item.focus}
      title={title}
      /* THE MARK, AT THE NAME (#2308) — «Метку выводим у имени». */
      badge={item.badge}
      infoNode={info.button}
      on={item.toggle ? item.toggle.value !== false : true}
      facts={facts}
      pill={item.pill}
      state={item.state}
      /* THE ONE SWITCH THIS ROW IS ABOUT (#2068), in the corner every other card keeps
         it in. It is still the screen's own `set` press, so nothing about what the
         switch MEANS lives here. */
      switchNode={
        item.toggle ? (
          <ErrandSwitch
            title={title}
            on={item.toggle.value !== false}
            onToggle={async (want) => {
              await post<PressAnswer>('/api/screen/press', {
                id: screen,
                action: 'set',
                args: { key: item.toggle!.key, value: want },
              })
              after()
            }}
          />
        ) : null
      }
      acts={[
        gear.button,
        ...(item.actions || []).map((action) => (
          <PressButton key={action.id} action={action} screen={screen} after={after} />
        )),
      ].filter(Boolean)}
      sheets={
        <>
          {gear.sheet}
          {info.sheet}
        </>
      }
    />
  )
}

/* ONE ITEM OF A `layout: "tiles"` CARD — a small button rather than a wide row (#1999).
 *
 * The person's words: «карта, секретки грабеж: делаем не грид с секретками в одну строку,
 * а небольшие кнопки с минимальной информацией». The ★ list runs to hundreds of places,
 * and a place is recognised by four things — where it is, what level it is, what state it
 * is in, and whether it can be taken. Everything else on the row is why the card was
 * unreadable.
 *
 * So a tile carries the item's NAME (the coordinate), its first TWO facts as bare VALUES,
 * its pill and its own buttons.
 * Two, measured rather than chosen: a ★ tile has four readings and the fourth wrapped
 * the line, which is the page this exists instead of. What survives is what the person
 * asked for — «уровень, звезда, координата, состояние».
 * The fact's label survives as the tile's tooltip: a value with no word beside it is
 * readable at a glance and still nameable when somebody wonders what «1/3» was. A fact
 * with no value at all is a MARK — «переслано», «ограблено» — and there the label IS the
 * word, so it is drawn instead.
 *
 * THE WHOLE TILE IS THE PRESS, AND THE PRESS IS THE JUMP. An item whose name is a
 * coordinate goes there when the tile is tapped — the same `goto_coord` the underlined
 * coordinate in a line of prose plays (#1982), out of one place (`useJump`), so the two
 * cannot drift. Never the robbery: a jump walks the camera and costs nothing, where a
 * robbery spends one of the day's five and does not come back. Where the tab offers one
 * it stays a BUTTON OF ITS OWN on the tile, and pressing it does not also jump.
 *
 * An item whose name is not a place — a warzone number on «Куда идти сегодня», a player —
 * is left a plain tile with whatever buttons it came with. Nothing here guesses: the
 * panel marks the coordinates it sends (`panel/web/coordlinks.py`), and a tile is a
 * button exactly when there is a mark to press.
 *
 * Inside a tile that IS a button the marks are drawn as PLAIN TEXT: the tile already
 * carries the jump, so a second control inside it would be the same press twice. */
/* How many of an item's facts fit on a tile before the line wraps — measured on an
 * emulated iPhone against the live ★ list, which has four readings and wrapped at three. */
const TILE_FACTS = 2

function MiniItem({ item, now, screen, after }: { item: ViewItem; now: number; screen: string; after: () => void }) {
  const jump = useJump()
  const gear = useItemGear(item, screen, after)
  //: The place this tile IS, or `null` — see the note above. Only the NAME counts: a
  //: coordinate buried in a fact is not what the tile is about.
  const place = item.label ? null : firstPlace(item.text_parts)
  //: Inside a tile that is a button, a mark is drawn as text rather than as a second
  //: button — `mark` is that decision, made once and used for every piece of prose.
  const mark = (text?: string | null, parts?: ViewItem['text_parts']) =>
    place ? <>{text || ''}</> : <Marked text={text} parts={parts} />
  /* `detail` goes on the tile too, first — it is the one word that is not a fact and
     still tells the places apart: the alliance a chest belongs to, the owner of a base.
     `note` does not: it is prose, and prose is what a tile exists instead of. */
  const bits: ReactNode[] = item.detail
    ? [
        <span className="bit" key="detail">
          {mark(item.detail, item.detail_parts)}
        </span>,
      ]
    : []
  bits.push(
    ...(item.facts || []).slice(0, TILE_FACTS).map((f, i) => (
      <span className="bit" key={i} title={t(f.label)}>
        {!f.value ? (
          t(f.label)
        ) : f.value_parts ? (
          mark(f.value, f.value_parts)
        ) : f.translate ? (
          t(f.value)
        ) : (
          f.value
        )}
      </span>
    )),
  )
  if (item.until)
    bits.push(
      <span className="bit" key="until">
        {when(item.until, now || item.until)}
      </span>,
    )
  const inside = (
    <>
      {/* THE GAME'S OWN PICTURE ON THE TILE (#2051), the same link-not-a-blob the
          errands draw: the browser fetches each sprite once and a machine that has not
          extracted the art simply shows a tile with no picture. */}
      <div className="name">
        {item.icon ? <img className="mini-icon" src={item.icon} alt="" aria-hidden="true" /> : null}
        <span>{item.label ? t(item.label) : mark(item.text, item.text_parts)}</span>
        {gear.button}
      </div>
      {bits.length ? <div className="bits">{bits}</div> : null}
      {item.pill ? <span className="pill">{t(item.pill)}</span> : null}
      {gear.sheet}
      {(item.actions || []).length ? (
        /* A BUTTON ON A TILE THAT IS ITSELF A BUTTON. The press is about the button —
           «Ограбить» must never also walk the camera — so the click stops here. */
        <div className="acts" onClick={(e) => e.stopPropagation()}>
          {(item.actions || []).map((action) => (
            <PressButton key={action.id} action={action} screen={screen} after={after} />
          ))}
        </div>
      ) : null}
    </>
  )
  if (!place) return <div className="mini">{inside}</div>
  return (
    <button className="mini act" onClick={() => void jump(place)}>
      {inside}
    </button>
  )
}

/* How many rows of a list a card draws before it stops and offers the rest. The map
 * screen sends 288 warzones, 285 starred tiles and 61 monsters in one payload, and the
 * phone drew every one of them under every other card — «огромная страница, сплошные
 * списки». A screen is a dashboard: the first screenful has to answer, and the rest is
 * one tap away. */
/* WHAT `/api/screen/data` ANSWERS A PAGED CARD WITH (#2133): the rows of this page, its
 * number counted from zero, how many pages the filter leaves and how many rows in all. */
interface PagedAnswer {
  items: ViewItem[]
  page: number
  pages: number
  total: number
  size: number
}

const PAGE_ITEMS = 20

/* …and how many a card of TILES draws, which is more because a tile is smaller: twenty
 * wide rows are twenty screenfuls of scroll and thirty tiles are about five. Same
 * «Показать ещё», same restart on a narrowed search. */
const PAGE_TILES = 30

/* What to call a card in the strip: its own title if it has one, its `head` (data, not a
 * key) otherwise, and a dash when it has neither — a chip with no word on it is worse
 * than a chip with a dash. */
function cardName(card: ViewCard): string {
  if (card.title) return t(card.title)
  if (card.head) return card.head
  return '\u2014'
}

/* HOW BIG A CARD IS, for the strip and the summary tile (#2051 follow-up).
 *
 * A card is counted by its ITEMS, which is what the count meant when every card had
 * some. A card made ENTIRELY OF KNOBS has none — «За день, по видам стягов» is
 * sixty-eight numbers and not one row — so on the summary it drew a heading with
 * nothing under it and no count beside it, and the person reading that page reported
 * the caps as GONE. Only a card with nothing else to show is counted by its fields, so
 * a card that already draws items or readings is left exactly as it was.
 */
function tileCount(card: ViewCard): number {
  const items = (card.items || []).length
  if (items) return items
  if ((card.rows || []).length) return 0
  return (card.fields || []).length
}

/** One knob as a summary line: what it is called, and what it is set to. */
function fieldSummary(field: Field): string {
  const value = field.value
  if (typeof value === 'boolean') return value ? '\u2713' : '\u2014'
  if (value === null || value === undefined || value === '') return '\u2014'
  return String(value)
}

function Card({
  card,
  needle,
  now,
  screen,
  after,
}: {
  card: ViewCard
  needle: string
  now: number
  screen: string
  after: () => void
}) {
  /* A CARD WHOSE ROWS COME OFF `/api/screen/data` (#2133) — see `ViewCard.paged`. The
     fetch is what puts a lap of the map back on the screen: the register grows by
     hundreds of players a minute, and a page of a thousand cannot ride the poll. */
  const paged = card.paged
  const [paging, setPaging] = useState<PagedAnswer | null>(null)
  const stamp = paged ? paged.stamp : ''
  const kind = paged ? paged.kind : ''
  useEffect(() => {
    if (!kind) return
    let alive = true
    /* The typed word narrows the WHOLE register, in the database, so it travels with the
       fetch — and after a pause, because a request per keystroke over three hundred
       thousand rows is a search box that types back. */
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const answer = await get<PagedAnswer>(
            '/api/screen/data?id=' +
              encodeURIComponent(screen) +
              '&kind=' +
              encodeURIComponent(kind) +
              (needle ? '&needle=' + encodeURIComponent(needle) : ''),
          )
          if (alive) setPaging(answer)
        } catch {
          /* the screen's own tick says when the panel is unreachable */
        }
      })()
    }, needle ? 350 : 0)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [screen, kind, stamp, needle])
  /* A card sends its items or it is `paged` — never both. What the panel narrowed in SQL
     is not narrowed a second time here, or the search box would search the page it was
     given instead of the register it asked about. */
  const items = paged
    ? paging?.items || []
    : (card.items || []).filter((item) => {
        if (!needle) return true
        const hay = ((item.text || '') + ' ' + (item.detail || '') + ' ' + (item.note || '')).toLowerCase()
        return hay.includes(needle)
      })
  // A card of PLACES draws them as small buttons (#1999); a card of THINGS WITH A FACE
  // draws them as the card an errand is (#2119). `layout` is the tab's own word for it,
  // so nothing here guesses from a title or a count.
  const tiled = card.layout === 'tiles'
  const carded = card.layout === 'cards'
  /* PAIRS OF PICTURE-AND-NUMBER, LAID ACROSS AND WRAPPED (#2418) — the shape of the
     game's own header, which fits nine balances into three short rows because none of
     them is spelled out. The exact figure is the pill's title, so nothing is lost. */
  const pilled = card.layout === 'pills'
  const page = tiled ? PAGE_TILES : PAGE_ITEMS
  const [shown, setShown] = useState(page)
  // A narrowed search starts from the top again: «показать ещё» over a list that has
  // just changed under the person is the wrong twenty.
  useEffect(() => setShown(page), [needle, card.title, page])
  /* A PAGED CARD IS ALREADY ONE PAGE, AND IT IS DRAWN WHOLE (#2308 follow-up).
   *
   * The person asked for «пагинацию игроков по 1000 записей», got it in the payload and
   * did not get it on the screen: the panel cut a thousand rows in SQL, the fetch
   * carried a thousand — and this cut them again, to twenty, with a «Показать ещё 20»
   * under them. Measured live: `/api/screen/data` answered 1000 items and the page held
   * 20 cards. Two pagers over one list is one pager too many, and the one that was
   * visible was the wrong one: «страница 1 из 5» over twenty rows says nothing true.
   *
   * So `shown` only applies to a card that sent its items itself, where it is what keeps
   * the map's six hundred rows from being drawn under every other card. A page cut by
   * the panel is drawn as the panel cut it. */
  const rest = paged ? 0 : Math.max(0, items.length - shown)
  const drawing = paged ? items : items.slice(0, shown)
  const rows = card.rows || []
  /* WHAT NARROWS THIS GRID, behind the gear beside its heading (#2308). */
  const gear = useCardGear(card, screen, after)
  return (
    <div className="card">
      {card.title ? (
        <div className="head">
          {t(card.title)}
          {/* A PAGED CARD COUNTS THE REGISTER, not the thousand in hand: «1000» over a
              list of three hundred and twenty-six thousand is the very lie this task
              began as. */}
          {paged ? (
            paging ? <span className="count">{paging.total}</span> : null
          ) : items.length ? (
            <span className="count">{items.length}</span>
          ) : null}
          {gear.button ? <span className="head-acts">{gear.button}</span> : null}
        </div>
      ) : null}
      {gear.sheet}
      {card.head ? (
        <div className="head">
          <Marked text={card.head} parts={card.head_parts} />
        </div>
      ) : null}
      {card.note ? <p className="muted small">{t(card.note)}</p> : null}
      {/* IS THE DATA ARRIVING, AND ARE WE TAKING IT (#1549) — the same strip the window
          draws above each table. The colour comes from `panel/runtime/flow.py` so the
          six states read the same in both front-ends. */}
      {card.flow ? (
        <div className="flow" style={{ color: card.flow.colour || undefined }}>
          {t(card.flow.key, card.flow.fmt)}
        </div>
      ) : null}
      {/* THE KNOBS BEFORE THE READINGS (#1976). A card may carry both, and «Ралли»
          carries three switches above a table of sixty-eight budget lines — a control
          under that table is a control nobody scrolls to. Readings explain a card;
          knobs are what a person opened it to move. */}
      {(card.fields || []).map((field) => (
        <ScreenField key={field.key} field={field} screen={screen} after={after} />
      ))}
      {rows.map((row, i) => (
        <div className="kv" key={i}>
          <span className="k">{t(row.label)}</span>
          <span className="v">
            <Marked text={row.value} parts={row.value_parts} />
          </span>
        </div>
      ))}
      {/* WHERE THE PAGE STANDS — «страница 3 из 327 · всего в списке 326 118». Without
          it the two arrows below are two presses with nothing to say where they have
          got to, which is the same silence a sort nobody could read (#2119) already
          cost this page once. */}
      {paged && paging ? (
        <div className="kv">
          <span className="k">
            {t('web.ui.page', { page: paging.page + 1, pages: paging.pages, total: paging.total })}
          </span>
        </div>
      ) : null}
      {/* THE SORT, DIRECTLY OVER THE ROWS IT ORDERS (#2308) — small buttons, one per
          column, and a press flips that column's direction. */}
      {(card.sorts || []).length ? <SortBar sorts={card.sorts || []} screen={screen} after={after} /> : null}
      {pilled ? (
        <div className="pills">
          {drawing.map((item, i) => (
            <span className="pill-res" key={i} title={item.text + ' ' + (item.detail || '')}>
              {item.icon ? (
                <img src={item.icon} alt="" />
              ) : (
                <b className="letter">{(item.text || '?').slice(0, 1)}</b>
              )}
              <b>{item.short || item.detail}</b>
            </span>
          ))}
        </div>
      ) : tiled ? (
        <div className="minis">
          {drawing.map((item, i) => (
            <MiniItem key={i} item={item} now={now} screen={screen} after={after} />
          ))}
        </div>
      ) : carded ? (
        /* The same grid the errands are laid out on — one column on a phone, more as
           the page grows, decided by the stylesheet rather than by a breakpoint. */
        <div className="tiles">
          {drawing.map((item, i) => (
            <CardItem key={i} item={item} now={now} screen={screen} after={after} />
          ))}
        </div>
      ) : (
        drawing.map((item, i) => (
          <Item key={i} item={item} now={now} screen={screen} after={after} />
        ))
      )}
      {rest ? (
        <button className="more" onClick={() => setShown((was) => was + page)}>
          {t('web.ui.show_more', { n: Math.min(rest, page) })}
        </button>
      ) : null}
      {/* «Пусто» is said about an ANSWER, never about a page still being fetched: a
          card that has not come back yet has nothing to report, and «нет игроков» over a
          register of three hundred thousand is a lie a person acts on. */}
      {!items.length && !rows.length && !(card.fields || []).length && card.empty && (!paged || paging) ? (
        <p className="muted">{t(card.empty)}</p>
      ) : null}
      {/* A card may carry buttons of its own (#1251): a tab whose pages each have their
          own switches cannot put them all in one strip at the bottom, because then
          nobody can tell which list a press belongs to. */}
      {(card.actions || []).length ? (
        <div className="foot">
          {(card.actions || []).map((action) => (
            <PressButton key={action.id} action={action} screen={screen} after={after} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function ScreenPage({
  id,
  onBack,
  pollKey,
  part: asked,
  onPart,
  map,
  onMap,
  onServer,
}: {
  id: string
  onBack: () => void
  pollKey: number
  /** Which part of the screen is open: 0 is the summary, i+1 is card i. */
  part: number
  onPart: (part: number) => void
  /** Which picture the map draws, when this screen has one (#2018, #2050). */
  map: 'model' | 'live'
  onMap: (map: 'model' | 'live') => void
  /** Install a confirmed landing in the global strip before this render unlocks it. */
  onServer: (server: number) => void
}) {
  const [view, setView] = useState<View | null>(null)
  const [needle, setNeedle] = useState('')
  const held = useRef(0)

  /* An open screen is re-read on the ordinary poll, not only when it is opened (#1272).
   * It used to be drawn once and then stay exactly as it was for as long as the phone
   * was looking at it — countdowns frozen, loot counts frozen — which is the phone's
   * half of «очень редко обновляются». The panel side is a dictionary walk over what
   * the tab already holds (`web_view` reads nothing), so a re-read costs one small
   * request. */
  /* WHERE THE PAGE IS SCROLLED TO, READ WHEN THE ANSWER LANDS — NOT WHEN IT WAS ASKED
   * FOR (#2593). This used to take the position BEFORE the fetch and put it back after
   * the re-render, which on a poll every 2.5 s meant every scroll made during those
   * ~100 ms was undone: the person's report was «меня постоянно дергается экран, скроллит
   * то вверх то вниз», and a thumb dragging through a poll is exactly that. React
   * updates the DOM in place and does not move the scroll by itself, so the only thing
   * worth restoring is a position the BROWSER clamped — a card that got shorter — and
   * that is the one case the layout effect below covers. */
  const draw = useCallback(
    async (keep: boolean) => {
      try {
        const answer = await get<View>('/api/screen?id=' + encodeURIComponent(id))
        held.current = keep ? window.scrollY : 0
        if (answer.header_server) onServer(answer.header_server)
        setView(answer)
      } catch {
        /* the tick says so */
      }
    },
    [id, onServer],
  )

  useEffect(() => {
    void draw(false)
    setNeedle('')
  }, [draw])

  useEffect(() => {
    if (pollKey) void draw(true)
     
  }, [pollKey])

  /* A LAYOUT effect, and only when the browser actually moved us: it runs after the DOM
   * is written and before the paint, so a page that shrank is put back without a flash,
   * and a page that stayed the same height is not touched at all. The 2 px is the
   * rounding a zoomed viewport reports, not a tolerance for real scrolling. */
  useLayoutEffect(() => {
    const want = held.current
    if (want && Math.abs(window.scrollY - want) > 2) window.scrollTo(0, want)
  }, [view])

  /* A SCREEN THAT IS DRAWN sends its cards all the same, so a front-end that does not
     know the kind still shows something. This one does know it, so the cards the picture
     replaces are dropped and only what it does NOT draw is left (#2064: the chat's own
     emoji and sticker grids stay, the channel listings go). */
  const cards = (view?.cards || []).filter((c) => !(view?.map && c.drawn))
  /* WHICH CARD THE ADDRESS ASKED FOR, once the cards are known (#2050). A card is named
   * by its position, and a screen reopened tomorrow may have fewer of them — a warzone
   * that closed, a list that emptied — so a number past the end falls back to the
   * summary instead of drawing nothing at all. */
  const part = asked > cards.length ? 0 : asked
  const setPart = onPart
  // A card titled the same as the screen it is on says it twice — «Альянс» over
  // «Альянс». One card, one heading, and the screen's own is the one that stays.
  const solo = cards.length === 1 && cards[0]?.title === view?.title
  /* A SCREEN OF MANY CARDS IS A DASHBOARD, NOT A SCROLL (#1982 follow-up, the person's
   * words: «огромная страница, без табов, сплошные списки… считай, что делаешь мобильное
   * приложение с дашбордом»). «Карта» sends thirteen cards and six hundred rows between
   * them, and they were drawn one under another. So: a summary first — one tile per
   * card with its readings and how many rows it holds — and a chip strip that opens any
   * one card on its own. Two cards or fewer are left exactly as they were: a strip over
   * a screen that fits is furniture nobody asked for. */
  const sectioned = cards.length > 2
  /* THE CARD THE SCREEN IS ABOUT (#2621). A screen may name one, and then part 0 opens
     THAT rather than the summary of tiles — «в vs основным экраном делай неделю». The
     summary chip is left out with it: an index of a page whose subject is one card is a
     tap that leads away from what the person came for. */
  const mainAt = cards.findIndex((c) => c.main)
  const shown = sectioned && part === 0 && mainAt >= 0 ? mainAt + 1 : part
  const openCard = sectioned && shown > 0 ? cards[shown - 1] : null
  const drawn = sectioned ? (openCard ? [openCard] : []) : cards
  const searchable = drawn.some((c) => c.search || (c.items || []).length > PAGE_ITEMS)
  /* A SCREEN THAT DRAWS A CONVERSATION CARRIES ITS OWN HEAD (#2418). Two bars — this
     one and the chat's — is 88 px of a phone spent saying «Чат» twice, and the person
     asked for one: «вверху кнопки назад и чаты в одну строку сделай». */
  const ownHead = view?.map?.kind === 'chat'
  /* THE MAP AND VS CARRY NO «НАЗАД» (#2621) — the person's own words: «из вкладок
     карты, vs убираем кнопку назад». Both are reached straight off the footer now,
     not through «Ещё», so a back button pointed at a list they were never opened
     from; «Ещё» itself moved into the header for the same reason. The title stays.
     «Карта» is `secret_tasks` since #2622 — `worldview` moved out of the footer and
     back onto «Ещё», so IT keeps its «назад» again. */
  const noBack = id === 'secret_tasks' || id === 'vs'
  return (
    <>
      {ownHead ? null : (
        <div className="row screen-head">
          {noBack ? null : (
            <button className="back" onClick={onBack}>
              {t('web.ui.back')}
            </button>
          )}
          <b>{t(view?.title || '')}</b>
        </div>
      )}
      {/* A SCREEN MAY DRAW ITSELF INSTEAD OF LISTING (#2018, #2064). `map.kind` NAMES
          WHICH DRAWING — and every kind is matched by name, never by «there is a map,
          so paint the world». That default is how two different screens end up as one:
          a screen sending any other kind would have been painted as the world map, and
          the next drawn screen added would silently become the map too. An unknown kind
          draws NOTHING and leaves the screen its cards, which is wrong in a way a
          person can see and report, rather than wrong in a way that looks plausible. */}
      {view?.map?.kind === 'chat' ? (
        <ChatView
          screen={id}
          rooms={view.rooms || []}
          listening={!!view.listening}
          silent={view.silent ?? null}
          waiting={!!view.waiting}
          pollKey={pollKey}
          onBack={onBack}
          tools={view.actions || []}
        />
      ) : view?.map?.kind === 'world' ? (
        <WorldMap screen={id} mode={map} onMode={onMap} />
      ) : null}
      {sectioned ? (
        <div className="chips">
          {mainAt >= 0 ? null : (
            <button className={'chip' + (part === 0 ? ' on' : '')} onClick={() => setPart(0)}>
              {t('web.ui.overview')}
            </button>
          )}
          {cards.map((card, i) => (
            <button
              key={i}
              className={'chip' + (shown === i + 1 ? ' on' : '')}
              onClick={() => setPart(i + 1)}
            >
              {cardName(card)}
              {tileCount(card) ? <span className="count">{tileCount(card)}</span> : null}
            </button>
          ))}
        </div>
      ) : null}
      {searchable ? (
        <input
          type="search"
          autoComplete="off"
          placeholder={t('web.ui.search')}
          value={needle}
          onChange={(e) => setNeedle(e.target.value)}
        />
      ) : null}
      {sectioned && shown === 0 ? (
        <div className="tiles">
          {cards.map((card, i) => (
            <button className="tile" key={i} onClick={() => setPart(i + 1)}>
              <div className="head">
                {cardName(card)}
                {tileCount(card) ? <span className="count">{tileCount(card)}</span> : null}
              </div>
              {(card.rows || []).slice(0, 2).map((row, k) => (
                <div className="kv" key={k}>
                  <span className="k">{t(row.label)}</span>
                  <span className="v">
                    <Marked text={row.value} parts={row.value_parts} />
                  </span>
                </div>
              ))}
              {/* …AND A CARD THAT IS NOTHING BUT KNOBS SHOWS ITS FIRST TWO (#2051
                  follow-up). Otherwise the tile is a heading over blank space, which is
                  how sixty-eight rally caps read as «список пропал, ничего не вижу». */}
              {!(card.rows || []).length
                ? (card.fields || []).slice(0, 2).map((field, k) => (
                    <div className="kv" key={'f' + k}>
                      <span className="k">{t(field.label, field.label_fmt)}</span>
                      <span className="v">{fieldSummary(field)}</span>
                    </div>
                  ))
                : null}
              {card.flow ? (
                <div className="flow" style={{ color: card.flow.colour || undefined }}>
                  {t(card.flow.key, card.flow.fmt)}
                </div>
              ) : null}
            </button>
          ))}
        </div>
      ) : (
        drawn.map((card, i) => (
          <Card
            key={i}
            card={solo ? { ...card, title: null } : card}
            needle={needle.toLowerCase()}
            now={view?.now || 0}
            screen={id}
            after={() => void draw(true)}
          />
        ))
      )}
      {/* A CONVERSATION DRAWS ITS OWN (#2418): the chat's service presses live behind
          the ⚙ in its bar, not as buttons standing under the messages. */}
      {(ownHead ? [] : view?.actions || []).map((action) => (
        <div className="controls" key={action.id}>
          <PressButton action={action} screen={id} after={() => void draw(true)} />
        </div>
      ))}
    </>
  )
}
