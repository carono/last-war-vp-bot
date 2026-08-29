import { useState, type CSSProperties, type ReactNode } from 'react'
import { post } from '../api'
import { span, t, when } from '../i18n'
import { FieldRow } from '../ui/FieldRow'
import { Modal } from '../ui/Modal'
import { useToast } from '../ui/Toast'
import type {
  ErrandStat,
  Field,
  OrderRow,
  PressAnswer,
  TimerRow,
  TriggerRow,
} from '../types'

/* THE GEAR (#2017). An errand's own knobs, on the card that says whether it is on.
 *
 * They lived on the page holding the list the errand spends — the level «Автолут ★»
 * robs at on «Секретки», the squads the auto-join sends on «Ралли» — so this screen,
 * which is where a person comes to ask what runs by itself, showed a name and a switch
 * and nothing that decides what the switch DOES. The values have not moved: the field
 * writes the owner's own variable (`panel/runtime/errand_options.py`), so the number
 * typed here is the number that page shows, and there is no second copy to disagree.
 */
/* THE GEAR IS TWO PIECES, because they sit in two places (#2050 follow-up): the button
 * belongs on the card's row of signs, and the sheet it opens belongs under the whole
 * block. So the hook hands back both and the block puts each where it goes. */
function useGear(errand: string, title: string, options: Field[] | undefined, refresh: () => Promise<void>) {
  const [open, setOpen] = useState(false)
  if (!options || !options.length) return { button: null, panel: null }
  return {
    button: (
      <button
        className="go icon"
        title={t('timers.options')}
        aria-label={t('timers.options')}
        onClick={() => setOpen((was) => !was)}
      >
        {'⚙'}
      </button>
    ),
    /* A SHEET, NOT A COLLAPSE (#2051), in the person's words: «при клике на шестеренку
       открывалась модалка с параметрами, а не коллапс, это везде». The knobs used to
       open inside the list, so the row being edited slid under the thumb and everything
       below it jumped. */
    panel: open ? (
      <Modal title={title} onClose={() => setOpen(false)}>
        {options.map((field) => (
          <FieldRow
            key={field.key}
            field={field}
            after={() => void refresh()}
            send={(key, value) => post<PressAnswer>('/api/errand/option', { errand, key, value })}
          />
        ))}
      </Modal>
    ) : null,
  }
}

/* THE «i» (#2061), and it exists because the NAME got shorter.
 *
 * The person's words: «слишком длинные названия, сократи, должны быть лаконичные, а
 * подробное описание вынеси в кнопку i». A card's head used to carry the whole sentence
 * — «Секретки: собирать по созреванию, вскрывать ящики, обновлять и отправлять» — which
 * is three lines on a phone and the reason thirty cards could not be skimmed. The panel
 * now sends both (`panel/web/api.py`): the short label as `title` and the sentence as
 * `about`. An errand whose label has no short form sends an empty `about` and draws no
 * «i» at all, rather than one that opens the title again.
 */
function useAbout(title: string, about?: string) {
  const [open, setOpen] = useState(false)
  if (!about) return { button: null, panel: null }
  return {
    button: (
      <button
        className="go icon"
        title={t('web.ui.about')}
        aria-label={t('web.ui.about')}
        onClick={() => setOpen(true)}
      >
        {'ℹ'}
      </button>
    ),
    panel: open ? (
      <Modal title={title} onClose={() => setOpen(false)}>
        <p>{about}</p>
      </Modal>
    ) : null,
  }
}

/* THE GAME'S OWN PICTURE FOR AN ERRAND (#2019), and since #2061 it is the CARD'S
 * BACKGROUND rather than a stamp beside the name — the person's words: «картинка должна
 * быть большая и фоном, чтобы аккуратно была на карточке».
 *
 * A link and not a blob: the panel sends `/api/errandicon?icon=…` and the browser fetches
 * each sprite once, exactly as it already does for a player's face. The URL rides a
 * custom property because the SIZE, the position, the fade and the scrim over it are
 * decisions of the stylesheet, not of this component — it hands over one string and
 * nothing else.
 *
 * A machine that has not extracted the art (or an errand the client has no sprite for —
 * three of thirty-six, `tools/data/errand_icons.json`) sends nothing, the card gets no
 * `art` class, and it draws exactly as a card drew before this existed. That is the
 * honest answer: a plain card, never a broken frame or a grey block where a picture
 * failed.
 *
 * IT COSTS NO HEIGHT. The picture is painted by two pseudo-elements taken out of the
 * flow, so a card is the size its text makes it, which is the size it was (#1999,
 * 5daa8eb2 — the compactness was fought for and a background is not a reason to give it
 * back). Measured on an emulated iPhone 15 over the live list: 35 cards, min 93 px,
 * average 159 px, max 241 px, before and after. */
function artStyle(icon?: string): CSSProperties | undefined {
  if (!icon) return undefined
  // `url("…")` rather than the bare link: a sprite name is the game's own file name and
  // may hold anything a file name may hold.
  return { ['--art' as string]: 'url("' + icon + '")' } as CSSProperties
}

/* THE SWITCH, AND IT IS THE TOP-RIGHT CORNER OF THE CARD (#2061) — the person's words:
 * «чекбокс включения/выключения перемести в правый верхний угол».
 *
 * It was a `SwitchRow`, which makes the WHOLE row the target: right for a form, wrong
 * for a card whose head also holds a picture and a name that may wrap. Here the box is
 * its own target and the name is not part of it — a tap meant for the title used to
 * switch the errand off. It keeps `--tap` and carries the errand's name as its
 * `aria-label`, so nothing is lost to somebody reading the page aloud. */
function ErrandSwitch({ title, on, onToggle }: {
  title: string
  on: boolean
  onToggle: (want: boolean) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  /* The LABEL is the target and the box is what is drawn: a checkbox 28 px tall is
     under half a fingertip, and every other control on this front-end is `--tap`. */
  return (
    <label className="errand-switch">
    <input
      type="checkbox"
      checked={on}
      disabled={busy}
      aria-label={title}
      title={title}
      onChange={async (e) => {
        const want = e.target.checked
        setBusy(true)
        try {
          await onToggle(want)
        } finally {
          setBusy(false)
        }
      }}
    />
    </label>
  )
}

/* ONE LIVE LINE UNDER THE BLOCK (#2019) — «+377 023 ждёт сбора», «12 стягов сегодня».
 *
 * IT COST NOTHING TO KNOW. Every number here came off something the panel already had
 * (`panel/runtime/errand_stats.py`); nothing on this page asks the game, which is the
 * rule a screen of a dozen polled blocks must obey above all others.
 *
 * SO IT SAYS HOW OLD IT IS. A reading with an age is a reading a person can judge; one
 * without is a number that might be from yesterday and looks like now. A source with no
 * clock of its own — a day's tally — sends `age: null` and says nothing, because
 * «сегодня» is already the whole truth about when it is from. */
function Stat({ stat }: { stat?: ErrandStat | null }) {
  if (!stat || !stat.key) return null
  const age = stat.age
  const old = typeof age === 'number' && age >= 0 ? t('timers.stat.age', { span: span(age) }) : ''
  return (
    <p className="stat small">
      <b>{t(stat.key, stat.fmt)}</b>
      {old ? <span className="muted"> · {old}</span> : null}
    </p>
  )
}

/* ONE BLOCK, THREE KINDS OF ERRAND — the person's words: «таймеры сделай так же
 * небольшими карточками, как и триггеры».
 *
 * A timer, a listener and a standing order are the same thing to whoever is reading the
 * page: something that runs by itself, with a switch, a picture, a line saying what it
 * is waiting for and a reading of what it has brought in. They were drawn by three
 * near-identical functions and laid out two different ways, so the same fact was told in
 * two shapes on one screen. Now there is one block and one grid.
 *
 * THE CARD IS THREE ROWS AND THE ORDER OF THEM IS THE POINT (#2061): the name with its
 * switch in the corner, what it is waiting for and what it has brought in, and — last —
 * the signs that ACT: «i», «⚙», «▶». The buttons used to sit on the head row beside the
 * switch, and at 280 px (the narrowest a card gets in the grid) three of them and a
 * switch left the name about thirty pixels. They are one short row of their own now, and
 * a card with nothing to press does not draw it.
 *
 * The buttons are SIGNS rather than words: «ⓘ», «⚙» and «▶», each with the panel's own
 * sentence on it as a title and as an aria-label. A «Запустить» spelled out is half the
 * width of a card on a phone, and this is the one screen where every card carries one.
 *
 * What a TIMER keeps that a listener has not: its schedule, its next firing and its last
 * result on the fact line, and the «▶» that plays it now. What it does NOT get back is
 * «Изменить / Дублировать / Удалить» — the person removed those from this screen
 * (bfb8418d) and they stay removed; the window still has all three.
 */
function ErrandBlock({
  icon,
  title,
  about,
  on,
  onToggle,
  facts,
  queued,
  stat,
  errand,
  options,
  refresh,
  run,
}: {
  icon?: string
  title: string
  about?: string
  on: boolean
  onToggle: (want: boolean) => Promise<void>
  facts: string
  queued?: boolean
  stat?: ErrandStat | null
  errand: string
  options?: Field[]
  refresh: () => Promise<void>
  run?: ReactNode
}) {
  const gear = useGear(errand, title, options, refresh)
  const info = useAbout(title, about)
  const acts = [info.button, gear.button, run].filter(Boolean)
  /* A CARD THAT IS OFF LOOKS OFF (#2061) — «когда чекбокс выключен, вся карточка должна
     менять цвет, чтобы было видно, что она выключена». A screen of thirty cards is read
     by its colour before it is read by its switches, and a small grey box in the corner
     is not a colour. */
  return (
    <div
      className={'item errand' + (icon ? ' art' : '') + (on ? '' : ' off')}
      style={artStyle(icon)}
    >
      {/* ONE BUBBLE, NOT FOUR (#2061). The picture is at full brightness on the left, so
          the words need a panel of their own — and it is a single element around all of
          them rather than a background on each row: four paddings cost four times the
          height, and this card's height is fought for (#1999). A card with no picture
          gets no bubble at all and draws exactly as it did. */}
      <div className="errand-body">
        <div className="errand-head">
          <span className="title">{title}</span>
          <ErrandSwitch title={title} on={on} onToggle={onToggle} />
        </div>
        <p className="muted small facts">
          {queued ? <span className="pill warn">{t('web.ui.queued')}</span> : null}
          {facts}
        </p>
        <Stat stat={stat} />
        {acts.length ? <div className="errand-acts">{acts}</div> : null}
      </div>
      {gear.panel}
      {info.panel}
    </div>
  )
}

/* The errands and, under them, the standing orders — the same two lists in the same
 * order the window's «Таймеры» tab draws them in. They are a grid: one column on a
 * phone, two once the page is wide enough, decided by the stylesheet rather than by a
 * breakpoint somebody has to keep in step with the window's own thresholds. */

function weekdayNames(days: number[]): string {
  const names = (t('timers.weekday.names') || '').split(',').map((w) => w.trim())
  return days.map((d) => names[d - 1] || String(d)).join(', ')
}

function TimerItem({ row, now, refresh }: { row: TimerRow; now: number; refresh: () => Promise<void> }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const days = row.weekdays || []
  // A row that names its weekdays has no period: it fires at the start of a matching
  // GAME day and at nothing else, so it says its days where the others say «каждые …».
  const bits = [
    days.length
      ? t('timers.on_days', { days: weekdayNames(days) })
      : t('web.ui.every', { span: span(row.interval_sec) }),
  ]
  if (row.enabled && row.next !== null && row.next !== undefined) {
    bits.push(t('web.ui.next', { when: when(row.next, now) }))
  }
  if (row.last_state === 'ok') bits.push(t('web.ui.last.ok', { when: when(row.last, now) }))
  else if (row.last_state === 'failed') bits.push(t('web.ui.last.failed', { when: when(row.last, now) }))
  else bits.push(t('web.ui.last.none'))
  // Only after a failure: the retry is why an hourly errand says «следующий через 4 мин»,
  // and without it the phone shows the answer with no reason.
  if (row.last_state === 'failed' && row.retry_sec) {
    bits.push(t('web.ui.retry', { span: span(row.retry_sec) }))
  }
  /* «СРАЗУ, БЕЗ ОЧЕРЕДИ» IS NOT DRAWN HERE — the person's decision, in their words:
     «настройку сразу без очереди тоже скрывай». The setting is untouched: a row still
     obeys whatever was last set and `/api/timers/now` still answers; only the phone
     stops offering it. */
  return (
    <ErrandBlock
      icon={row.icon}
      title={row.title}
      about={row.about}
      on={row.enabled}
      onToggle={async (want) => {
        await post('/api/timers/set', { name: row.name, enabled: want })
        await refresh()
      }}
      facts={bits.join(' · ')}
      queued={row.queued}
      stat={row.stat}
      errand={row.name}
      options={row.options}
      refresh={refresh}
      run={
        <button
          key="run"
          className="go icon"
          title={t('web.ui.run')}
          aria-label={t('web.ui.run')}
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              const answer = await post<PressAnswer>('/api/timers/run', { name: row.name })
              toast(answer.queued ? t('web.ui.started', { name: row.title }) : t('web.ui.refused'))
              await refresh()
            } finally {
              setBusy(false)
            }
          }}
        >
          {'▶'}
        </button>
      }
    />
  )
}

function TriggerItem({ row, refresh }: { row: TriggerRow; refresh: () => Promise<void> }) {
  // What it waits for, and whether an ear is actually up — the same two readings and the
  // same three words the window's block shows, off the same keys.
  const signal = row.poll ? t('triggers.poll') : t('triggers.cell.event', { signal: row.signal })
  const state =
    row.status === 'queued'
      ? t('timers.queued')
      : row.status === 'listening'
        ? t('triggers.listening')
        : t('triggers.off')
  /* …and the standing orders' own «сразу, без очереди» is hidden with the errands' (see
     `TimerItem`): one setting, one decision. */
  return (
    <ErrandBlock
      icon={row.icon}
      title={row.title}
      about={row.about}
      on={row.enabled}
      onToggle={async (want) => {
        await post('/api/triggers/set', { name: row.name, enabled: want })
        await refresh()
      }}
      facts={signal + ' · ' + state}
      stat={row.stat}
      errand={row.name}
      /* WHAT THE ORDER SPENDS (#2017): the squads «rally_auto_join» may send, the
         soldier floor, the day's ceiling. A listener that has declared no knobs — which
         is most of them — draws no gear at all. */
      options={row.options}
      refresh={refresh}
    />
  )
}

/* A WATCHER THAT IS IN NO CATALOGUE (#2017) — «Автолут ★», «Автопомощь», «Автолут
 * отрядов призрака». Same block as a listener, because to a person it is the same
 * thing; what it says instead of an event is what it is DOING right now, which is the
 * answer to «почему он не грабит» and the reason a silent order and a stopped one used
 * to look identical. */
function OrderItem({ row, refresh }: { row: OrderRow; refresh: () => Promise<void> }) {
  return (
    <ErrandBlock
      icon={row.icon}
      title={row.title}
      about={row.about}
      on={row.enabled}
      onToggle={async (want) => {
        await post('/api/orders/set', { name: row.name, enabled: want })
        await refresh()
      }}
      facts={row.state || ''}
      stat={row.stat}
      errand={row.name}
      options={row.options}
      refresh={refresh}
    />
  )
}

/* THERE IS NO «ДОБАВИТЬ» ON THIS SCREEN (#2061) — the person's words: «из таймеров убери
 * кнопку добавить». The editor it opened went with it: an errand written on a phone is
 * a scenario name and a schedule typed with a thumb, and every row worth having is in
 * the catalogue already (`panel/timers.py`). The ROUTES are untouched — `/api/timers/save`
 * still answers, and `tests/test_panel_web.py` still holds it to the window's own rules —
 * so nothing has to be undone the day the person wants a way back in. */
export function TimersView({
  timers,
  triggers,
  orders,
  now,
  refresh,
}: {
  timers: TimerRow[]
  triggers: TriggerRow[]
  orders?: OrderRow[]
  now: number
  refresh: () => Promise<void>
}) {
  return (
    <>
      <div className="tiles">
        {timers.map((row) => (
          <TimerItem key={row.name} row={row} now={now} refresh={refresh} />
        ))}
      </div>
      {!timers.length ? <p className="muted">{t('web.ui.timers.empty')}</p> : null}
      <h2 className="section">{t('triggers.frame')}</h2>
      <div className="tiles">
        {triggers.map((row) => (
          <TriggerItem key={row.name} row={row} refresh={refresh} />
        ))}
        {(orders || []).map((row) => (
          <OrderItem key={row.name} row={row} refresh={refresh} />
        ))}
      </div>
      {!triggers.length ? <p className="muted">{t('web.ui.triggers.empty')}</p> : null}
      <p className="muted small">{t('triggers.hint')}</p>
    </>
  )
}
