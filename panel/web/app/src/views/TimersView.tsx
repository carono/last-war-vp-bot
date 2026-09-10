import { useState, type ReactNode } from 'react'
import { post } from '../api'
import { span, t, when } from '../i18n'
/* THE CARD IS NOT THIS FILE'S ANY MORE (#2119). It was written here for the errands and
 * it is now the one card every list on this front-end is drawn as — the register of
 * players is the second — so it lives in `ui/` and this screen is one of its callers.
 * Nothing about how a timer, a listener or a standing order READS changed with it. */
import { ErrandCard, ErrandSwitch } from '../ui/ErrandCard'
import { FieldRow } from '../ui/FieldRow'
import { Modal } from '../ui/Modal'
import { SwitchRow } from '../ui/SwitchRow'
import { useToast } from '../ui/Toast'
import type {
  ArmsNow,
  ArmsPhase,
  ErrandRes,
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

/* ONE BLOCK, THREE KINDS OF ERRAND — the person's words: «таймеры сделай так же
 * небольшими карточками, как и триггеры».
 *
 * A timer, a listener and a standing order are the same thing to whoever is reading the
 * page: something that runs by itself, with a switch, a picture, a line saying what it
 * is waiting for and a reading of what it has brought in. They are ONE card
 * (`ui/ErrandCard.tsx`) and this is what an errand brings to it: the gear with its own
 * knobs, the switch that turns it on, and — for a timer — the «▶» that plays it now.
 *
 * What an errand does NOT get back is «Изменить / Дублировать / Удалить»: the person
 * removed those from this screen (bfb8418d) and they stay removed; the window still has
 * all three.
 */
function ErrandBlock({
  icon,
  focus,
  title,
  about,
  on,
  onToggle,
  facts,
  queued,
  stat,
  next,
  now,
  tall,
  res,
  phases,
  arms,
  errand,
  options,
  refresh,
  run,
}: {
  icon?: string
  focus?: string
  title: string
  about?: string
  on: boolean
  onToggle: (want: boolean) => Promise<void>
  facts: string
  queued?: boolean
  stat?: ErrandStat | null
  next?: number | null
  now?: number
  tall?: boolean
  res?: ErrandRes[]
  phases?: ArmsPhase[]
  arms?: ArmsNow
  errand: string
  options?: Field[]
  refresh: () => Promise<void>
  run?: ReactNode
}) {
  const gear = useGear(errand, title, options, refresh)
  return (
    <ErrandCard
      icon={icon}
      /* EVERY CARD ON THIS PAGE IS THE SAME CARD (#2407) — the person's words: «все
         карточки в таймерах и триггерах должны быть по новому формату… больше старый
         формат не добавляем». It is not asked whether this machine HAS a picture: the
         shape is the format, and a row with no picture wears the placeholder rather
         than a second drawing of its own. */
      cover
      focus={focus}
      title={title}
      about={about}
      on={on}
      facts={facts}
      queued={queued}
      stat={stat}
      /* THE COUNTDOWN ON THE STAT LINE (#2744) — the card that has a clock of its own
         says «через 12 мин» where the others say how old their reading is. Every row
         hands over the two numbers; which card uses them is decided by the stat. */
      next={next}
      now={now}
      /* THE TALL TYPE (#2744) — the panel says when a card's row of chips needs the
         extra half a height; the card is the same component either way. */
      tall={tall}
      /* WHAT CAME IN TODAY (#2743), for the errand whose card is about a pile. */
      res={res}
      /* THE DAY, PHASE BY PHASE (#2579) — «Гонка вооружений» alone sends it, and it is
         drawn in the sheet the «i» opens rather than on the card: six rows with pictures
         are a screen of their own, and the card is a picture with three lines on it. */
      phases={phases}
      /* THE HOUR RUNNING NOW, ON THE FACE OF THE CARD (#2635) — «Гонка вооружений»
         alone sends it. The day behind the «i» answers «что было», this answers «что
         идёт»: the hour, its three chests and its points. */
      arms={arms}
      /* THE CARD IS THE PICTURE (#2370): the schedule — or, for a listener, what it is
         waiting for — travels under the «i» instead of standing over the art. */
      factsInSheet
      switchNode={<ErrandSwitch title={title} on={on} onToggle={onToggle} />}
      acts={[gear.button, run].filter(Boolean)}
      sheets={gear.panel}
    />
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

/* THE ONE ERRAND THAT IS DRAWN SOMEWHERE ELSE (#2634) — the person's words: «Перенеси
   карточку гонки вооружений из таймеров во вкладку vs на самый вверх». It is a MOVE and
   not a copy: the card is the very same component with the very same row, it simply
   stands at the top of the «VS» page, and this list leaves it out so that no page shows
   two of it. Nothing about the errand itself changes — the switch, the period, the ▶ and
   the knobs behind the gear all go on writing exactly where they wrote before. */
export const ARMS_ERRAND = 'perform_arms_race'

export function TimerItem({ row, now, refresh }: { row: TimerRow; now: number; refresh: () => Promise<void> }) {
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
      focus={row.focus}
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
      next={row.next}
      now={now}
      tall={row.tall}
      /* WHAT THE BASE PAID TODAY (#2743) — pictures instead of a count of runs, on the
         two cards about the base's own pile and on no other. */
      res={row.res}
      phases={row.phases}
      arms={row.arms}
      errand={row.name}
      options={row.options}
      refresh={refresh}
      run={
        /* ▶ WHILE IT IS NOT RUNNING, ■ WHILE IT IS (#2408). A detached chain — the
           golden hunt — lasts as long as its marches, and until now the only way to end
           one was «Прервать», which stops everything the profile is doing. The same
           button, because it is the same question: «идёт или нет». */
        <button
          key="run"
          /* THE PRIMARY SIGN OF THE ROW (#2579), and it says so in a class rather than
             in a position: «⚙» and «▶» sit together at the right of the foot, and which
             of the two a thumb is reaching for must not be decided by counting children
             — a card with no knobs has one sign and it is this one. */
          className={'go icon run' + (row.running ? ' running' : '')}
          title={row.running ? t('web.ui.stop') : t('web.ui.run')}
          aria-label={row.running ? t('web.ui.stop') : t('web.ui.run')}
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              if (row.running) {
                await post<PressAnswer>('/api/timers/stop', { name: row.name })
                toast(t('web.ui.stopping', { name: row.title }))
              } else {
                const answer = await post<PressAnswer>('/api/timers/run', { name: row.name })
                toast(answer.queued ? t('web.ui.started', { name: row.title }) : t('web.ui.refused'))
              }
              await refresh()
            } finally {
              setBusy(false)
            }
          }}
        >
          {row.running ? '■' : '▶'}
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
      /* A listener's picture is a cover too since #2370 — same card, same rules, and
         since #2407 the same card whether or not there is a picture at all. */
      focus={row.focus}
      title={row.title}
      about={row.about}
      on={row.enabled}
      onToggle={async (want) => {
        await post('/api/triggers/set', { name: row.name, enabled: want })
        await refresh()
      }}
      facts={signal + ' · ' + state}
      stat={row.stat}
      res={row.res}
      /* THE TALL TYPE (#2744) — the listener that watches the base's pile draws the same
         chips as the harvest, so it grows the same way rather than clipping them. */
      tall={row.tall}
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
      focus={row.focus}
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
  running,
  refresh,
}: {
  timers: TimerRow[]
  triggers: TriggerRow[]
  orders?: OrderRow[]
  now: number
  running: boolean
  refresh: () => Promise<void>
}) {
  return (
    <>
      {/* THE SCHEDULE'S MASTER SWITCH (#2660). «Прервать» stops the scheduler thread,
          and the only way back used to be the window's own checkbox — so on a panel
          nobody is standing at, a schedule stopped from a bus stayed stopped and every
          card below went on drawing its own switch as if it meant something. */}
      <SwitchRow
        title={t('timers.scheduler')}
        on={running}
        onChange={async (want) => {
          await post('/api/timers/scheduler', { enabled: want })
          await refresh()
        }}
      />
      <div className="tiles">
        {timers
          .filter((row) => row.name !== ARMS_ERRAND)
          .map((row) => (
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
