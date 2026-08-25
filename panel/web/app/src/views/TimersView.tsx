import { useState } from 'react'
import { post } from '../api'
import { span, t, when } from '../i18n'
import { SwitchRow } from '../ui/SwitchRow'
import { useToast } from '../ui/Toast'
import type { PressAnswer, TimerRow, TriggerRow } from '../types'

/* The errands and, under them, the standing orders — the same two lists in the same
 * order the window's «Таймеры» tab draws them in. The listeners are a grid: one column
 * on a phone, two once the page is wide enough, decided by the stylesheet rather than by
 * a breakpoint somebody has to keep in step with the window's own thresholds. */

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
      <div className="foot">
        {row.queued ? <span className="pill warn">{t('web.ui.queued')}</span> : <span />}
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
  return (
    <>
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
