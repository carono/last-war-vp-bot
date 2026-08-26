import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post } from '../api'
import { t, when } from '../i18n'
import { pressWord } from '../ui/press'
import { useToast } from '../ui/Toast'
import { SwitchRow } from '../ui/SwitchRow'
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

/* A KNOB, drawn as the control its kind names (#1976). The kind comes from the type the
 * knob was declared with, so nothing here guesses from a name — and the value is sent
 * back as the same `set` press whatever the control, so a tab answers for its own knobs
 * in one handler.
 *
 * A TYPED FIELD IS COMMITTED ON LEAVING IT, never on every keystroke: a panel that saved
 * «4», «40», «400» on the way to «4000» would spend three of those readings acting on a
 * number nobody meant. A switch is committed at once, because there is nothing half-typed
 * about it. */
function FieldRow({
  field,
  screen,
  after,
}: {
  field: Field
  screen: string
  after: () => void
}) {
  const toast = useToast()
  const [draft, setDraft] = useState(String(field.value ?? ''))
  const sent = useRef(String(field.value ?? ''))

  useEffect(() => {
    // The screen re-reads on the poll; a box nobody is typing in follows the panel.
    if (document.activeElement?.getAttribute('data-field') !== field.key) {
      setDraft(String(field.value ?? ''))
      sent.current = String(field.value ?? '')
    }
  }, [field.value, field.key])

  const send = async (value: string | number | boolean) => {
    const answer = await post<PressAnswer>('/api/screen/press', {
      id: screen,
      action: 'set',
      args: { key: field.key, value },
    })
    if (answer.ok === false || answer.error) toast(pressWord(answer))
    else if (answer.reason) toast(t(answer.reason))
    window.setTimeout(after, 400)
  }

  if (field.kind === 'choice') {
    return (
      <div className="field">
        <label className="muted small" htmlFor={'f-' + field.key}>
          {t(field.label)}
        </label>
        <select
          id={'f-' + field.key}
          value={String(field.value ?? '')}
          onChange={(e) => void send(e.target.value)}
        >
          {(field.options || []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.text}
            </option>
          ))}
        </select>
        {field.hint ? <p className="muted small">{t(field.hint)}</p> : null}
      </div>
    )
  }
  if (field.kind === 'switch') {
    return (
      <>
        <SwitchRow
          title={t(field.label)}
          on={!!field.value}
          onChange={async (want) => {
            await send(want)
          }}
        />
        {field.hint ? <p className="muted small">{t(field.hint)}</p> : null}
      </>
    )
  }
  return (
    <div className="field">
      <label className="muted small" htmlFor={'f-' + field.key}>
        {t(field.label)}
      </label>
      <input
        id={'f-' + field.key}
        data-field={field.key}
        type={field.kind === 'number' ? 'number' : 'text'}
        inputMode={field.kind === 'number' ? 'decimal' : undefined}
        min={field.min}
        max={field.max}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (draft === sent.current) return
          sent.current = draft
          void send(draft)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        }}
      />
      {field.hint ? <p className="muted small">{t(field.hint)}</p> : null}
    </div>
  )
}

function Item({ item, now, screen, after }: { item: ViewItem; now: number; screen: string; after: () => void }) {
  const facts = item.facts || []
  const bits = facts.map((f) => t(f.label) + ' ' + (f.translate && f.value ? t(f.value) : f.value))
  if (item.until) bits.push(when(item.until, now || item.until))
  return (
    <div className="item">
      <div className="row">
        {/* A FACE and AN ICON are LINKS into the panel's own routes, never bytes inside
            the view: the browser keeps them, so a screen repainting every couple of
            seconds fetches each one once (#1324, #1469). One that will not load simply
            leaves the name alone. */}
        {item.avatar ? <img className="face" src={item.avatar} alt="" /> : null}
        {item.icon ? <img className="icon" src={item.icon} alt="" /> : null}
        <span className="title">{item.label ? t(item.label) : item.text || ''}</span>
        {item.detail ? <span className="muted small">{item.detail}</span> : null}
      </div>
      {item.note ? <p className="muted small">{item.note}</p> : null}
      {bits.length ? <p className="muted small">{bits.join(' · ')}</p> : null}
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

/* How many rows of a list a card draws before it stops and offers the rest. The map
 * screen sends 288 warzones, 285 starred tiles and 61 monsters in one payload, and the
 * phone drew every one of them under every other card — «огромная страница, сплошные
 * списки». A screen is a dashboard: the first screenful has to answer, and the rest is
 * one tap away. */
const PAGE_ITEMS = 20

/* What to call a card in the strip: its own title if it has one, its `head` (data, not a
 * key) otherwise, and a dash when it has neither — a chip with no word on it is worse
 * than a chip with a dash. */
function cardName(card: ViewCard): string {
  if (card.title) return t(card.title)
  if (card.head) return card.head
  return '—'
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
  const [shown, setShown] = useState(PAGE_ITEMS)
  // A narrowed search starts from the top again: «показать ещё» over a list that has
  // just changed under the person is the wrong twenty.
  useEffect(() => setShown(PAGE_ITEMS), [needle, card.title])
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
      {card.head ? <div className="head">{card.head}</div> : null}
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
        <FieldRow key={field.key} field={field} screen={screen} after={after} />
      ))}
      {rows.map((row, i) => (
        <div className="kv" key={i}>
          <span className="k">{t(row.label)}</span>
          <span className="v">{row.value}</span>
        </div>
      ))}
      {items.slice(0, shown).map((item, i) => (
        <Item key={i} item={item} now={now} screen={screen} after={after} />
      ))}
      {rest ? (
        <button className="more" onClick={() => setShown((was) => was + PAGE_ITEMS)}>
          {t('web.ui.show_more', { n: Math.min(rest, PAGE_ITEMS) })}
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
}: {
  id: string
  onBack: () => void
  pollKey: number
}) {
  const [view, setView] = useState<View | null>(null)
  const [needle, setNeedle] = useState('')
  //: Which part of the screen is open: 0 is the summary, i+1 is card i.
  const [part, setPart] = useState(0)
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
    setPart(0)
    setNeedle('')
  }, [draw])

  useEffect(() => {
    if (pollKey) void draw(true)
     
  }, [pollKey])

  useEffect(() => {
    if (held.current) window.scrollTo(0, held.current)
  }, [view])

  const cards = view?.cards || []
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
              {(card.items || []).length ? (
                <span className="count">{(card.items || []).length}</span>
              ) : null}
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
                {(card.items || []).length ? (
                  <span className="count">{(card.items || []).length}</span>
                ) : null}
              </div>
              {(card.rows || []).slice(0, 2).map((row, k) => (
                <div className="kv" key={k}>
                  <span className="k">{t(row.label)}</span>
                  <span className="v">{row.value}</span>
                </div>
              ))}
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
