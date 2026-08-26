import { useState } from 'react'
import { post } from '../api'
import { t, when } from '../i18n'
import { Pill } from '../ui/Pill'
import { SwitchRow } from '../ui/SwitchRow'
import { useToast } from '../ui/Toast'
import type { Control, PressAnswer, Recovery, ResourceRow, State } from '../types'

/* THE THREE STATUSES (#1911), in the phone's two vocabularies: the word on the pill and
 * the colour it is worn in. The reasons are `tools/lib/profile_health.py`'s own ids, so
 * a reason added there cannot end up wordless here — the lookup falls back to the
 * colour. Red is «нет клиента», amber is «есть клиент, трафика нет» with WHICH half
 * failed in the word, green is «сервер отвечает». */
const LINK_WORDS: Record<string, string> = {
  traffic: 'health.traffic',
  no_client: 'health.no_client',
  client_hung: 'health.client_hung',
  no_connection: 'health.no_connection',
  no_traffic: 'health.no_traffic',
  /* …and the closed door (#1982): amber, but «wait» rather than «find the fault».
   * Recognised from the game's OWN maintenance message, so it says what is actually
   * happening instead of «трафика нет», which invites somebody to restart things that
   * are not broken. */
  maintenance: 'health.maintenance',
}

/* …and WHY nothing is running, which is a different question from what the light says
 * (`panel/runtime/gate.py`). «Нет связи с игрой» during maintenance is false — the link
 * is perfect and the server is shut — and the two send a person in opposite directions. */
const GATE_WORDS: Record<string, string> = {
  off: 'gate.held.off',
  maintenance: 'gate.held.maintenance',
  link: 'gate.held',
}

/* WHY THE CLIENT IS BEING RESTARTED, or why it is not — the window has a log scrolling
 * past and the person holding a phone does not, so «why did my client just restart» has
 * to be answerable from the card (`panel/runtime/recovery.py`). One sentence, the first
 * that applies, silent while nothing is wrong. */
function recoveryLine(rec: Recovery): string {
  if (rec.held_by === 'kick') {
    return t('web.ui.recovery.kick', { mins: Math.ceil((rec.kick_hold_left || 0) / 60) })
  }
  if (rec.held_by === 'player') {
    return t('web.ui.recovery.player', { mins: Math.ceil((rec.player_hold_left || 0) / 60) })
  }
  if (rec.stalled_for) {
    return t('web.ui.recovery.stalled', {
      mins: Math.floor((rec.stalled_for || 0) / 60),
      next: Math.ceil((rec.stalled_next || 0) / 60),
      n: rec.stalled_restarts || 0,
    })
  }
  if (rec.fruitless) return t('web.ui.recovery.fruitless', { n: rec.fruitless })
  if (rec.barren_of && (rec.barren || 0) >= rec.barren_of) {
    return t('web.ui.recovery.barren', { n: rec.barren })
  }
  if (rec.held_by === 'cooldown' || rec.cooldown_left) {
    return t('web.ui.recovery.wait', { mins: Math.ceil((rec.cooldown_left || 0) / 60) })
  }
  if (rec.deaf_for) return t('web.ui.recovery.deaf', { n: rec.deaf_for, of: rec.strikes || 0 })
  if (rec.restarts) return t('web.ui.recovery.done', { n: rec.restarts })
  return ''
}

/* The client's life: start it, close it, put it back — the same three the window has
 * (`panel/runtime/game_control.py`). Everything about them comes off /api/state: the
 * word on each, the question it asks first, and whether it applies to the client as it
 * stands. Nothing is decided here — a phone that worked out for itself when «Стоп» makes
 * sense is a phone that will one day disagree with the window about it. */
function ControlRow({
  controls,
  route,
  onDone,
}: {
  controls: Control[]
  route: string
  onDone: () => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState('')
  if (!controls.length) return null
  return (
    <div className="controls">
      {controls.map((control) => (
        <button
          key={control.id}
          className={'go' + (control.running ? ' running' : '')}
          disabled={control.enabled === false || !!control.running || busy === control.id}
          onClick={async () => {
            // Asked first when the panel says to ask: closing a client or replacing one
            // is a minute of an account's evening if the thumb slipped. `confirm` rather
            // than something drawn here — it is the one dialog already the right size
            // for a thumb on every phone, and it cannot be mis-tapped through.
            if (control.confirm && !window.confirm(t(control.confirm))) return
            setBusy(control.id)
            try {
              const answer = await post<PressAnswer>(route, { action: control.id })
              if (answer.ok) toast(t('web.ui.started', { name: t(control.label) }))
              else if (answer.unavailable) toast(t('web.ui.game.gone'))
              else toast(t('web.ui.refused'))
            } catch {
              toast(t('web.ui.refused'))
            } finally {
              setBusy('')
              onDone()
            }
          }}
        >
          {t(control.label)}
        </button>
      ))}
    </div>
  )
}

/* The panel itself, last on the page: which version is running and the press that puts
 * it back on the code that is now on disk (`panel/runtime/panel_control.py`). Not drawn
 * at all where there is no panel to restart — the same route answers for a tab launched
 * on its own, and there the press does not exist rather than merely not applying. */
function PanelCard({ state, onGone }: { state: State; onGone: () => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState('')
  const panel = state.panel || {}
  const controls = panel.controls || []
  if (!controls.length) return null
  return (
    <div className="card">
      <div className="row">
        <span>{t('web.ui.version')}</span>
        <Pill>{panel.version || ''}</Pill>
      </div>
      <p className="muted small">{t('web.ui.panel.hint')}</p>
      <div className="controls">
        {controls.map((control) => (
          <button
            key={control.id}
            className="go"
            disabled={control.enabled === false || busy === control.id}
            onClick={async () => {
              // ASKED FIRST, always: this is the one press that switches off the very
              // thing the thumb is holding.
              if (control.confirm && !window.confirm(t(control.confirm))) return
              setBusy(control.id)
              try {
                const answer = await post<PressAnswer>('/api/panel', { action: control.id })
                if (answer.ok) {
                  // Two presses, two truths: one comes back by itself and one does not,
                  // and a page promising «страница вернётся сама» over a panel that has
                  // just been switched off is lying to whoever is holding it.
                  toast(t(control.id === 'quit' ? 'web.ui.panel.quitting' : 'web.ui.panel.restarting'))
                  onGone()
                } else {
                  toast(t('web.ui.refused'))
                  setBusy('')
                }
              } catch {
                onGone()
              }
            }}
          >
            {t(control.label)}
          </button>
        ))}
      </div>
    </div>
  )
}

/* WHAT THE BASE IS HOLDING, on the front page and moving by itself (#1990). Every row
 * is `actions/read_base_resources.md`'s answer said back: the NAME is the game's own,
 * already in the player's language, so nothing here maps a resource onto a word of the
 * panel's — which is the only way «золото» and «хлеб» can be right, given that the
 * client's own field names call them `wood` and `money`.
 *
 * There is no «Обновить». The reading refreshes on its own, at most every half minute
 * (`panel/runtime/resources.py`), and the line under the list says how old it is —
 * because a number with no age on it is indistinguishable from one that stopped
 * updating an hour ago. */
function ResourcesCard({ state }: { state: State }) {
  const stock = state.resources || {}
  const rows: ResourceRow[] = stock.rows || []
  const age = stock.age ?? -1
  // A count is grouped in the browser's own locale — the one formatting job that is not
  // a translation: 712198273 is unreadable and «712 198 273» is the same number.
  const num = (value: number) => value.toLocaleString()
  const note = stock.reading
    ? t('web.ui.res.reading')
    : age < 0
      ? t('web.ui.res.never')
      : t('web.ui.res.age', { sec: Math.round(age) })
  return (
    <div className="card">
      <div className="row">
        <span>{t('web.ui.res.head')}</span>
        <Pill tone={rows.length ? 'ok' : undefined}>{note}</Pill>
      </div>
      {/* WHY AN OLD READING IS NOT A STALE ONE. The balance only moves when the game
          says so, and while this line is here the panel is listening to it being said
          (`push.resource.item.update`) — so «прочитано 4 минуты назад» means «nothing has
          happened», not «nobody has looked». Without the ear the age is all there is,
          and the line is absent, which is the honest difference. */}
      {stock.watching ? <p className="muted small">{t('web.ui.res.live')}</p> : null}
      {rows.length ? (
        rows.map((row) => (
          <div className="row" key={row.type}>
            <span>
              {row.name}
              {/* What one press of «Сбор ресурсов» would add. The game's own figure per
                  building, summed by what that building makes — so it is a reading and
                  not the panel's arithmetic. Silent at zero. */}
              {row.pending ? <span className="muted small"> {t('web.ui.res.pending', { n: num(row.pending) })}</span> : null}
            </span>
            <span>
              {num(row.count)}
              {/* Only what the game actually reported: a cap and a rate come back as 0
                  for most of the base's resources, and «из 0» would be a fact the client
                  never stated. */}
              {row.max ? ' ' + t('web.ui.res.cap', { max: num(row.max) }) : ''}
              {row.per_hour ? ' · ' + t('web.ui.res.rate', { rate: num(row.per_hour) }) : ''}
            </span>
          </div>
        ))
      ) : (
        <p className="muted small">{t('web.ui.res.empty')}</p>
      )}
    </div>
  )
}

export function StateView({
  state,
  refresh,
  onGone,
}: {
  state: State
  refresh: () => void
  onGone: () => void
}) {
  const toast = useToast()
  const colour = state.game.colour || (state.game.running ? 'warn' : 'bad')
  const reason = state.game.reason || ''
  const word = t(LINK_WORDS[reason] || 'web.ui.off')
  const rec = recoveryLine(state.game.recovery || {})
  const powerOn = state.power?.on !== false
  // NOT WHILE THE SWITCH IS OFF: the mark above already says that in the words somebody
  // chose, and a second sentence under it reads as an unrelated fault.
  const gateHeld = !!state.gate?.held && powerOn
  const runs = state.interrupt?.running || []
  const elsewhere = state.interrupt?.elsewhere || 0
  const working = !!state.activity || !!state.link.busy
  const shared = state.link.shared || []

  return (
    <>
      <div className="card">
        <div className="row">
          <span>{t('web.ui.game')}</span>
          <Pill tone={colour}>{word}</Pill>
        </div>
        <p className="muted small">{state.game.text || ''}</p>
        {rec ? <p className="muted small">{rec}</p> : null}
        {!powerOn ? (
          <p className="small bad">
            {t('power.mark', { mins: Math.floor((state.power?.off_for_sec || 0) / 60) })}
          </p>
        ) : null}
        {gateHeld ? (
          <p className="small bad">
            {t(GATE_WORDS[state.gate?.reason || ''] || 'gate.held',
               { mins: Math.floor((state.gate?.for_sec || 0) / 60) })}
          </p>
        ) : null}
        <div className="controls stack">
          <SwitchRow
            title={t('power.on')}
            on={powerOn}
            onChange={async (want) => {
              await post('/api/power', { on: want })
              refresh()
            }}
          />
          {/* THE SECOND BOX: with the watchdog off, a client that dies — or one the game
              takes off the account — is never put back, and the page would otherwise
              show a stopped account with no reason on it. */}
          <SwitchRow
            title={t('opt.watchdog')}
            on={state.watchdog !== false}
            onChange={async (want) => {
              await post('/api/watchdog', { on: want })
              refresh()
            }}
          />
        </div>
        <ControlRow controls={state.game.controls || []} route="/api/game" onDone={refresh} />
      </div>

      <ResourcesCard state={state} />

      <div className="card">
        <div className="row">
          <span>{t('web.ui.link')}</span>
          <Pill tone={colour}>{word}</Pill>
        </div>
        <p className="muted small">{t('web.ui.port', { port: state.link.port })}</p>
        {state.link.user ? (
          <p className="muted small">{t('web.ui.link.user', { user: state.link.user })}</p>
        ) : null}
        {shared.length ? (
          <p className="small bad">
            {t('web.ui.link.shared', {
              others: shared.join(', '),
              tab: t('tab.settings'),
              page: t('settings.tab.game'),
              frame: t('session.frame'),
            })}
          </p>
        ) : null}
      </div>

      <div className="card">
        <div className="row">
          <span>{t('web.ui.doing')}</span>
          <Pill tone={working ? 'warn' : 'ok'}>{working ? t('web.ui.busy') : t('web.ui.idle')}</Pill>
        </div>
        <p className="muted small">{state.activity ? state.activity.text : t('web.ui.nothing')}</p>
        {runs.length || elsewhere ? (
          <p className="muted small">
            {[
              ...runs.map((run) =>
                run.step
                  ? t('interrupt.run.step', { name: run.name, step: run.step })
                  : t('interrupt.run', { name: run.name }),
              ),
              ...(elsewhere ? [t('interrupt.elsewhere', { count: elsewhere })] : []),
            ].join('; ')}
          </p>
        ) : null}
        {/* ALWAYS DRAWN, greyed when nothing is playing, exactly as the window's is: a
            button that appears under a thumb already moving is pressed by accident. No
            confirmation — a Stop asked «are you sure?» is a Stop that arrives a second
            late, and the worst it can do is end a run that can be started again. */}
        <div className="row">
          <button
            className="go"
            disabled={!runs.length && !elsewhere}
            onClick={async () => {
              const answer = await post<PressAnswer>('/api/interrupt', {})
              const count = (answer.stopped || []).length
              toast(count ? t('interrupt.toast', { count }) : t('interrupt.idle'))
              refresh()
            }}
          >
            {t(state.interrupt?.stopping ? 'interrupt.stopping' : 'interrupt.button')}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="row">
          <span>{t('web.ui.timers.head')}</span>
          <Pill tone={state.timers.on ? 'ok' : undefined}>
            {t('web.ui.timers.count', { count: state.timers.on })}
          </Pill>
        </div>
        <p className="muted small">
          {state.timers.next
            ? t('web.ui.timers.next', {
                name: state.timers.next_name,
                when: when(state.timers.next, state.time),
              })
            : t('web.ui.timers.none')}
        </p>
      </div>

      <PanelCard state={state} onGone={onGone} />
    </>
  )
}
