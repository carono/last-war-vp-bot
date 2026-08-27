import { useEffect, useState } from 'react'
import { get, post } from '../api'
import { span, t, when } from '../i18n'
import { FieldRow } from '../ui/FieldRow'
import { SwitchRow } from '../ui/SwitchRow'
import { useToast } from '../ui/Toast'
import type { ActionRow, Field, OrderRow, PressAnswer, TimerRow, TriggerRow } from '../types'

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
function Gear({
  errand,
  options,
  refresh,
}: {
  errand: string
  options?: Field[]
  refresh: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  if (!options || !options.length) return null
  return (
    <>
      <button className="go" title={t('timers.options')} onClick={() => setOpen((was) => !was)}>
        {'\u2699'}
      </button>
      {open ? (
        <div className="editor">
          {options.map((field) => (
            <FieldRow
              key={field.key}
              field={field}
              after={() => void refresh()}
              send={(key, value) => post<PressAnswer>('/api/errand/option', { errand, key, value })}
            />
          ))}
        </div>
      ) : null}
    </>
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
  return (
    <div className="item">
      <SwitchRow
        title={row.title}
        on={row.enabled}
        onChange={async (want) => {
          await post('/api/timers/set', { name: row.name, enabled: want })
          await refresh()
        }}
      />
      {/* «СРАЗУ, БЕЗ ОЧЕРЕДИ» IS NOT DRAWN HERE ANY MORE — the person's decision, in
          their words: «настройку сразу без очереди тоже скрывай». The setting itself is
          untouched: what a row obeys is still whatever was last set, `/api/timers/now`
          still answers, and the window's own box still moves it. Only the phone stops
          offering it, because a screen full of knobs nobody moves is what this screen
          was becoming. */}
      <p className="muted small">{bits.join(' · ')}</p>
      {/* ONE BUTTON PER ROW, AND IT IS «ЗАПУСТИТЬ» — the person's decision, in their
          words: «в таймерах из кнопок оставляй только запустить». Изменить / Дублировать
          / Удалить are gone from the phone; every one of them still exists — the routes
          answer, the window's tab has all three, and the editor below is still what «+»
          opens — so nothing has been taken away from the panel, only from this screen.
          A row's own switch still turns it on and off, which is the one thing a person
          away from the machine actually does to an errand. */}
      <div className="foot">
        {row.queued ? <span className="pill warn">{t('web.ui.queued')}</span> : <span />}
        <Gear errand={row.name} options={row.options} refresh={refresh} />
        <button
          className="go"
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
          {t('web.ui.run')}
        </button>
      </div>
    </div>
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
  return (
    <div className="item">
      <SwitchRow
        title={row.title}
        on={row.enabled}
        onChange={async (want) => {
          await post('/api/triggers/set', { name: row.name, enabled: want })
          await refresh()
        }}
      />
      {/* …and the standing orders' own «сразу, без очереди» is hidden with the
          errands' (see `TimerItem`): one setting, one decision, and half a screen of it
          left drawn would be the confusing half. */}
      <p className="muted small">{signal + ' · ' + state}</p>
      {/* WHAT THE ORDER SPENDS (#2017): the squads «rally_auto_join» may send, the
          soldier floor, the day's ceiling. Nothing is drawn for a listener that has
          declared no knobs, which is most of them. */}
      <div className="foot">
        <span />
        <Gear errand={row.name} options={row.options} refresh={refresh} />
      </div>
    </div>
  )
}

/* A WATCHER THAT IS IN NO CATALOGUE (#2017) — «Автолут ★», «Автопомощь», «Автолут
 * отрядов призрака». Same block as a listener, because to a person it is the same
 * thing; what it says instead of an event is what it is DOING right now, which is the
 * answer to «почему он не грабит» and the reason a silent order and a stopped one used
 * to look identical. */
function OrderItem({ row, refresh }: { row: OrderRow; refresh: () => Promise<void> }) {
  return (
    <div className="item">
      <SwitchRow
        title={row.title}
        on={row.enabled}
        onChange={async (want) => {
          await post('/api/orders/set', { name: row.name, enabled: want })
          await refresh()
        }}
      />
      {row.state ? <p className="muted small">{row.state}</p> : null}
      <div className="foot">
        <span />
        <Gear errand={row.name} options={row.options} refresh={refresh} />
      </div>
    </div>
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
      <div>
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
