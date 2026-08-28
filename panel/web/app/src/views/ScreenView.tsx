import type { ReactNode } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post } from '../api'
import { t, when } from '../i18n'
import { pressWord } from '../ui/press'
import { useToast } from '../ui/Toast'
import { FieldRow } from '../ui/FieldRow'
import { firstPlace, Marked, useJump } from '../ui/Coord'
import { WorldMap } from './WorldMap'
import type { Field, PressAnswer, ScreenView as View, ViewAction, ViewCard, ViewItem } from '../types'

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
  return (
    <button
      className="go"
      disabled={busy}
      onClick={async () => {
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
          // The tab reads on its own thread, so the result is a moment behind the press.
          window.setTimeout(after, 900)
        } finally {
          setBusy(false)
        }
      }}
    >
      {t(action.label)}
    </button>
  )
}

/* The screen's own way of sending a moved knob: the tab's `set` press. The control
 * itself is `ui/FieldRow.tsx` — the gear on «Таймеры» draws the same one (#2017). */
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
      </div>
      {item.note ? (
        <p className="muted small">
          <Marked text={item.note} parts={item.note_parts} />
        </p>
      ) : null}
      {bits.length ? <p className="muted small">{bits}</p> : null}
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
      <div className="name">{item.label ? t(item.label) : mark(item.text, item.text_parts)}</div>
      {bits.length ? <div className="bits">{bits}</div> : null}
      {item.pill ? <span className="pill">{t(item.pill)}</span> : null}
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
  const items = (card.items || []).filter((item) => {
    if (!needle) return true
    const hay = ((item.text || '') + ' ' + (item.detail || '') + ' ' + (item.note || '')).toLowerCase()
    return hay.includes(needle)
  })
  // A card of PLACES draws them as small buttons (#1999): `layout` is the tab's own
  // word for it, so nothing here guesses from a title or a count.
  const tiled = card.layout === 'tiles'
  const page = tiled ? PAGE_TILES : PAGE_ITEMS
  const [shown, setShown] = useState(page)
  // A narrowed search starts from the top again: «показать ещё» over a list that has
  // just changed under the person is the wrong twenty.
  useEffect(() => setShown(page), [needle, card.title, page])
  const rest = Math.max(0, items.length - shown)
  const rows = card.rows || []
  return (
    <div className="card">
      {card.title ? (
        <div className="head">
          {t(card.title)}
          {items.length ? <span className="count">{items.length}</span> : null}
        </div>
      ) : null}
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
      {tiled ? (
        <div className="minis">
          {items.slice(0, shown).map((item, i) => (
            <MiniItem key={i} item={item} now={now} screen={screen} after={after} />
          ))}
        </div>
      ) : (
        items.slice(0, shown).map((item, i) => (
          <Item key={i} item={item} now={now} screen={screen} after={after} />
        ))
      )}
      {rest ? (
        <button className="more" onClick={() => setShown((was) => was + page)}>
          {t('web.ui.show_more', { n: Math.min(rest, page) })}
        </button>
      ) : null}
      {!items.length && !rows.length && !(card.fields || []).length && card.empty ? <p className="muted">{t(card.empty)}</p> : null}
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
  const draw = useCallback(
    async (keep: boolean) => {
      const at = keep ? window.scrollY : 0
      try {
        const answer = await get<View>('/api/screen?id=' + encodeURIComponent(id))
        setView(answer)
        held.current = at
      } catch {
        /* the tick says so */
      }
    },
    [id],
  )

  useEffect(() => {
    void draw(false)
    setNeedle('')
  }, [draw])

  useEffect(() => {
    if (pollKey) void draw(true)
     
  }, [pollKey])

  useEffect(() => {
    if (held.current) window.scrollTo(0, held.current)
  }, [view])

  const cards = view?.cards || []
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
  const openCard = sectioned && part > 0 ? cards[part - 1] : null
  const drawn = sectioned ? (openCard ? [openCard] : []) : cards
  const searchable = drawn.some((c) => c.search || (c.items || []).length > PAGE_ITEMS)
  return (
    <>
      <div className="row screen-head">
        <button className="back" onClick={onBack}>
          {t('web.ui.back')}
        </button>
        <b>{t(view?.title || '')}</b>
      </div>
      {/* A SCREEN MAY BE A PICTURE (#2018). It is drawn above its cards, which then
          read as the legend of what is on it — and it keeps its own data, so the
          screen's poll below never carries a scene. */}
      {view?.map ? <WorldMap screen={id} mode={map} onMode={onMap} /> : null}
      {sectioned ? (
        <div className="chips">
          <button className={'chip' + (part === 0 ? ' on' : '')} onClick={() => setPart(0)}>
            {t('web.ui.overview')}
          </button>
          {cards.map((card, i) => (
            <button
              key={i}
              className={'chip' + (part === i + 1 ? ' on' : '')}
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
      {sectioned && part === 0 ? (
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
      {(view?.actions || []).map((action) => (
        <div className="controls" key={action.id}>
          <PressButton action={action} screen={id} after={() => void draw(true)} />
        </div>
      ))}
    </>
  )
}
