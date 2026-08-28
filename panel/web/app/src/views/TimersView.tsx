import { useEffect, useState, type ReactNode } from 'react'
import { get, post } from '../api'
import { span, t, when } from '../i18n'
import { FieldRow } from '../ui/FieldRow'
import { Modal } from '../ui/Modal'
import { SwitchRow } from '../ui/SwitchRow'
import { useToast } from '../ui/Toast'
import type {
  ActionRow,
  ErrandStat,
  Field,
  OrderRow,
  PressAnswer,
  TimerRow,
  TriggerRow,
} from '../types'

/* THE GEAR (#2017). An errand's own knobs, on the row that says whether it is on.
 *
 * They lived on the page holding the list the errand spends — the level «Автолут ★»
 * robs at on «Секретки», the squads the auto-join sends on «Ралли» — so this screen,
 * which is where a person comes to ask what runs by itself, showed a name and a switch
 * and nothing that decides what the switch DOES. The values have not moved: the field
 * writes the owner's own variable (`panel/runtime/errand_options.py`), so the number
 * typed here is the number that page shows, and there is no second copy to disagree.
 *
 * Closed until asked, because most rows have no knobs and a screen of open forms is a
 * screen nobody reads. */
/* THE GEAR IS TWO PIECES, because they sit in two places (#2050 follow-up): the button
 * belongs on the head row beside the switch, and the fields it opens belong under the
 * whole block. So the hook hands back both and the block puts each where it goes —
 * rendering them together would mean a form unfolding inside a flex row. */
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
        {'\u2699'}
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

/* THE GAME'S OWN PICTURE FOR AN ERRAND (#2019), beside its switch.
 *
 * A link and not a blob: the panel sends `/api/errandicon?icon=…` and the browser fetches
 * each sprite once, exactly as it already does for a player's face. A machine that has
 * not extracted the art sends nothing and the block draws as it always did — the picture
 * is a help, never a thing the row depends on. */
function ErrandIcon({ src }: { src?: string }) {
  if (!src) return null
  return <img className="errand-icon" src={src} alt="" aria-hidden="true" />
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
 * near-identical functions and laid out two different ways — the listeners as small
 * cards in a grid, the errands as full-width rows one under another — so the same fact
 * was told in two shapes on one screen. Now there is one block and one grid.
 *
 * WHAT MAKES IT SMALLER IS THE HEAD ROW, not a smaller font. Every block used to end in
 * a `foot` of its own holding one or two buttons; the buttons are on the head row now,
 * beside the switch, so each block loses a whole row and the gap under it — thirty-odd
 * blocks on this screen, so it is the one change worth making.
 *
 * The two buttons are SIGNS rather than words, exactly as the gear already was: «⚙» and
 * «▶», each with the panel's own sentence on it as a title and as an aria-label. A
 * «Запустить» spelled out is half the width of a card on a phone, and this is the one
 * screen where every card carries one.
 *
 * What a TIMER keeps that a listener has not: its schedule, its next firing and its last
 * result on the fact line, and the «▶» that plays it now. What it does NOT get back is
 * «Изменить / Дублировать / Удалить» — the person removed those from this screen
 * (bfb8418d) and they stay removed; the editor is still what «+» opens, and the window
 * still has all three.
 */
function ErrandBlock({
  icon,
  title,
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
  return (
    <div className="item errand">
      <div className="errand-head">
        <ErrandIcon src={icon} />
        <SwitchRow title={title} on={on} onChange={onToggle} />
        {gear.button}
        {run}
      </div>
      <p className="muted small facts">
        {queued ? <span className="pill warn">{t('web.ui.queued')}</span> : null}
        {facts}
      </p>
      <Stat stat={stat} />
      {gear.panel}
    </div>
  )
}

/* The errands and, under them, the standing orders — the same two lists in the same
 * order the window's «Таймеры» tab draws them in. The listeners are a grid: one column
 * on a phone, two once the page is wide enough, decided by the stylesheet rather than by
 * a breakpoint somebody has to keep in step with the window's own thresholds. */

function weekdayNames(days: number[]): string {
  const names = (t('timers.weekday.names') || '').split(',').map((w) => w.trim())
  return days.map((d) => names[d - 1] || String(d)).join(', ')
}

/* THE WHOLE ENTRY of an errand, and not only its schedule (#1976). The window has had
 * an editor since it had a Timers tab, and the phone had the period and the weekdays —
 * so the steps, the args and the title could be read on a phone and written only at the
 * machine. That was a divergence with a reason («a phone that could rewrite a scenario
 * by a mistyped character is not a remote control»), and the person has ended it: the
 * web is the front-end, so it gets the whole function.
 *
 * Nothing is written until Save, exactly as in the window's dialog: «4», «40», «400» on
 * the way to «4000» are three schedules nobody asked for. The panel refuses the same
 * four things the dialog does — no name, a name another row answers to, no steps, args
 * that are not a JSON object — and says so with the same keys, so a refusal reads the
 * same whichever front-end asked. */
function TimerEditor({
  row,
  onDone,
  onCancel,
}: {
  row: TimerRow | null
  onDone: () => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState(row?.name || '')
  const [title, setTitle] = useState(row?.custom_title || '')
  const [every, setEvery] = useState(String(row?.interval_sec ?? 3600))
  const [retry, setRetry] = useState(String(row?.retry_sec ?? 300))
  const [days, setDays] = useState((row?.weekdays || []).join(','))
  const [args, setArgs] = useState(
    row && row.args && Object.keys(row.args).length ? JSON.stringify(row.args) : '',
  )
  const [steps, setSteps] = useState((row?.steps || []).join('\n'))
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [scripts, setScripts] = useState<ActionRow[]>([])
  const [pick, setPick] = useState('')

  /* The picker: every scenario this profile has, appended as a step — the thirty-odd
   * recipes are no more memorable on a phone than at the machine. Asked once, when an
   * editor opens, and never on the poll. */
  useEffect(() => {
    void (async () => {
      try {
        setScripts((await get<{ actions?: ActionRow[] }>('/api/actions')).actions || [])
      } catch {
        /* a picker that could not be filled is a box the person types into */
      }
    })()
  }, [])

  const save = async () => {
    setBusy(true)
    try {
      const answer = await post<PressAnswer>('/api/timers/save', {
        name,
        original: row?.name || '',
        title,
        interval_sec: every,
        retry_sec: retry,
        weekdays: days,
        args,
        steps,
      })
      if (!answer.ok) {
        setProblem(
          answer.error === 'unknown' ? t('web.ui.unknown') : t(answer.reason, answer.fmt),
        )
        return
      }
      await onDone()
    } finally {
      setBusy(false)
    }
  }

  const field = (key: string, value: string, set: (v: string) => void, numeric = false) => (
    <div className="field grow">
      <label className="muted small" htmlFor={key + '-' + (row?.name || 'new')}>
        {t(key)}
      </label>
      <input
        id={key + '-' + (row?.name || 'new')}
        type={numeric ? 'number' : 'text'}
        inputMode={numeric ? 'numeric' : undefined}
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    </div>
  )

  return (
    <div className="editor">
      <div className="row wrap">
        {field('timers.editor.name', name, setName)}
        {field('timers.editor.title', title, setTitle)}
      </div>
      <div className="row wrap">
        {field('timers.editor.interval', every, setEvery, true)}
        {field('timers.editor.retry', retry, setRetry, true)}
        {field('timers.editor.weekdays', days, setDays)}
      </div>
      <div className="row wrap">{field('timers.editor.args', args, setArgs)}</div>
      <p className="muted small">{t('timers.editor.steps_hint')}</p>
      <textarea
        className="steps"
        rows={6}
        spellCheck={false}
        value={steps}
        onChange={(e) => setSteps(e.target.value)}
      />
      <div className="row wrap">
        <select className="grow" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">{t('timers.editor.pick')}</option>
          {scripts.map((script) => (
            <option key={script.name} value={script.name}>
              {script.name + ' — ' + script.title}
            </option>
          ))}
        </select>
        <button
          className="go"
          disabled={!pick}
          onClick={() => setSteps((was) => (was.trim() ? was.replace(/\s*$/, '\n') : '') + pick)}
        >
          {t('timers.editor.add_step')}
        </button>
      </div>
      {problem ? <p className="bad small">{problem}</p> : null}
      <div className="foot">
        <button className="go" onClick={onCancel}>
          {t('timers.editor.cancel')}
        </button>
        <button className="go" disabled={busy} onClick={() => void save()}>
          {t('timers.editor.save')}
        </button>
      </div>
    </div>
  )
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
          {'\u25B6'}
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
  const [adding, setAdding] = useState(false)
  return (
    <>
      <div className="foot">
        <span />
        <button className="go" onClick={() => setAdding(true)}>
          {t('timers.add')}
        </button>
      </div>
      {adding ? (
        <div className="item">
          <TimerEditor
            row={null}
            onCancel={() => setAdding(false)}
            onDone={async () => {
              setAdding(false)
              await refresh()
            }}
          />
        </div>
      ) : null}
      {/* THE SAME GRID THE LISTENERS ARE IN — one column on a phone, two once there is
          room, decided by the stylesheet. The errands used to be full-width rows under
          it, which is what made two lists of the same thing look like two kinds of
          thing. */}
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
