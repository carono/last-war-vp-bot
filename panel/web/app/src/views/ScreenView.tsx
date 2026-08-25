import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post } from '../api'
import { t, when } from '../i18n'
import { pressWord } from '../ui/press'
import { useToast } from '../ui/Toast'
import type { PressAnswer, ScreenView as View, ViewAction, ViewCard, ViewItem } from '../types'

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
  const rows = card.rows || []
  return (
    <div className="card">
      {card.title ? <div className="head">{t(card.title)}</div> : null}
      {card.head ? <div className="head">{card.head}</div> : null}
      {/* IS THE DATA ARRIVING, AND ARE WE TAKING IT (#1549) — the same strip the window
          draws above each table. The colour comes from `panel/runtime/flow.py` so the
          six states read the same in both front-ends. */}
      {card.flow ? (
        <div className="flow" style={{ color: card.flow.colour || undefined }}>
          {t(card.flow.key, card.flow.fmt)}
        </div>
      ) : null}
      {rows.map((row, i) => (
        <div className="kv" key={i}>
          <span className="k">{t(row.label)}</span>
          <span className="v">{row.value}</span>
        </div>
      ))}
      {items.map((item, i) => (
        <Item key={i} item={item} now={now} screen={screen} after={after} />
      ))}
      {!items.length && !rows.length && card.empty ? <p className="muted">{t(card.empty)}</p> : null}
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
  }, [draw])

  useEffect(() => {
    if (pollKey) void draw(true)
     
  }, [pollKey])

  useEffect(() => {
    if (held.current) window.scrollTo(0, held.current)
  }, [view])

  const cards = view?.cards || []
  const searchable = cards.some((c) => c.search)
  // A card titled the same as the screen it is on says it twice — «Альянс» over
  // «Альянс». One card, one heading, and the screen's own is the one that stays.
  const solo = cards.length === 1 && cards[0]?.title === view?.title
  return (
    <>
      <div className="row screen-head">
        <button className="back" onClick={onBack}>
          {t('web.ui.back')}
        </button>
        <b>{t(view?.title || '')}</b>
      </div>
      {searchable ? (
        <input
          type="search"
          autoComplete="off"
          placeholder={t('web.ui.search')}
          value={needle}
          onChange={(e) => setNeedle(e.target.value)}
        />
      ) : null}
      {cards.map((card, i) => (
        <Card
          key={i}
          card={solo ? { ...card, title: null } : card}
          needle={needle.toLowerCase()}
          now={view?.now || 0}
          screen={id}
          after={() => void draw(true)}
        />
      ))}
      {(view?.actions || []).map((action) => (
        <div className="controls" key={action.id}>
          <PressButton action={action} screen={id} after={() => void draw(true)} />
        </div>
      ))}
    </>
  )
}
