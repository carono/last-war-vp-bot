import { useEffect, useState } from 'react'
import { get, post } from '../api'
import { span, t, when } from '../i18n'
import { SwitchRow } from '../ui/SwitchRow'
import { useToast } from '../ui/Toast'
import type { ActionRow, PressAnswer, TimerRow, TriggerRow } from '../types'

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
  const [open, setOpen] = useState(false)
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
      {/* «СРАЗУ, БЕЗ ОЧЕРЕДИ» (#1288) — the window's row has this box, so the phone has
          it. A control the person can read but not move is the divergence CLAUDE.md
          forbids. */}
      <SwitchRow
        muted
        title={t('web.ui.at_once')}
        on={!!row.immediate}
        onChange={async (want) => {
          await post('/api/timers/now', { name: row.name, immediate: want })
          await refresh()
        }}
      />
      <p className="muted small">{bits.join(' · ')}</p>
      {open ? (
        <TimerEditor
          row={row}
          onCancel={() => setOpen(false)}
          onDone={async () => {
            setOpen(false)
            await refresh()
          }}
        />
      ) : null}
      <div className="foot">
        {row.queued ? <span className="pill warn">{t('web.ui.queued')}</span> : <span />}
        <button className="go" onClick={() => setOpen((was) => !was)}>
          {t('timers.edit')}
        </button>
        <button
          className="go"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await post('/api/timers/copy', { name: row.name })
              await refresh()
            } finally {
              setBusy(false)
            }
          }}
        >
          {t('timers.duplicate')}
        </button>
        <button
          className="go"
          disabled={busy}
          onClick={async () => {
            // The window asks before it deletes, so the phone asks — and a thumb on a
            // moving bus is the reason it asks, not a reason to skip asking.
            if (!window.confirm(t('timers.confirm_delete', { name: row.title }))) return
            setBusy(true)
            try {
              await post('/api/timers/delete', { name: row.name })
              await refresh()
            } finally {
              setBusy(false)
            }
          }}
        >
          {t('timers.delete')}
        </button>
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
      <SwitchRow
        muted
        title={t('web.ui.at_once')}
        on={!!row.immediate}
        onChange={async (want) => {
          await post('/api/triggers/now', { name: row.name, immediate: want })
          await refresh()
        }}
      />
      <p className="muted small">{signal + ' · ' + state}</p>
    </div>
  )
}

export function TimersView({
  timers,
  triggers,
  now,
  refresh,
}: {
  timers: TimerRow[]
  triggers: TriggerRow[]
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
      </div>
      {!triggers.length ? <p className="muted">{t('web.ui.triggers.empty')}</p> : null}
      <p className="muted small">{t('triggers.hint')}</p>
    </>
  )
}
