import { useState } from 'react'
import { post } from '../api'
import { span, t, when } from '../i18n'
import { LINK_SHORT, LINK_WORDS } from '../ui/LinkLight'
import { Pill } from '../ui/Pill'
import { SwitchRow } from '../ui/SwitchRow'
import { useToast } from '../ui/Toast'
import type { Control, PressAnswer, Progress, Recovery, State } from '../types'

/* THE LIGHT ITSELF IS IN THE HEADER SINCE #2705 — the person's words, «В хеадер
 * перенеси светофор состояния игры и панели». What stood here was the pill and the two
 * tables of words behind it; the tables moved to `ui/LinkLight.tsx` with the light and
 * are imported back for the one thing this page still says about a fault — the sentence
 * under the card, which is a paragraph and not a reading. Nothing is drawn twice: the
 * colour, the word and the legend are the header's now.
 */
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

/* …and no resources card here any more (#1990, second pass). What the base is holding
 * is «Профиль»'s now: this page answers one question — is the client alive and does the
 * server answer — and a balance was never part of it. The EAR moved with the card, which
 * is the half that matters: asking for the stock is what subscribes to
 * `push.resource.item.update`, so it now goes up when somebody opens that screen instead
 * of for every phone that merely has the front page open (`panel/tabs/profile.py`).
 */


/* WHAT THE PRESS IS DOING RIGHT NOW, AND HOW IT ENDED (#2742). The person's complaint
 * was not the button: «я должен видеть прогресс что происходит с финальной точкой и
 * когда все завершается». A restart is half a minute of a page that used to say nothing
 * at all — one log line the phone does not show, and then either a client or silence.
 *
 * Every line here is the SCENARIO's own (a `STEP` line in the recipe), so the phases are
 * the ability's and cannot drift from it; the panel says the words and counts the
 * seconds. Nothing new is polled: it rides the /api/state the page already asks for
 * every 2.5 s (`CLAUDE.md`, «читаем один раз, дальше слушаем»).
 *
 * The finished run stays on screen for ten minutes with its age, because a press made
 * from a pocket is read afterwards. */
function ProgressBlock({ progress }: { progress?: Progress | null }) {
  if (!progress) return null
  const mark = (state: string) => (state === 'done' ? '✓' : state === 'failed' ? '✕' : '●')
  const tone = progress.running ? 'warn' : progress.ok ? 'ok' : 'bad'
  return (
    <div className="progress">
      <div className="row">
        <span>{progress.text || t(progress.label)}</span>
        <Pill tone={tone}>
          {progress.running
            ? t('progress.running', { secs: Math.round(progress.secs) })
            : t('progress.took', { secs: Math.round(progress.secs) })}
        </Pill>
      </div>
      <ul className="progress-steps small">
        {progress.steps.map((step, i) => (
          <li key={`${step.key}-${i}`} className={step.state}>
            <span className="mark">{mark(step.state)}</span>
            <span className="what">{step.text || t(step.key)}</span>
            <span className="muted secs">{t('progress.secs', { secs: step.secs })}</span>
          </li>
        ))}
      </ul>
      {progress.final ? (
        <p className={'small ' + (progress.ok ? 'ok' : 'bad')}>
          {progress.final.text || t(progress.final.key)}
          {progress.age > 0 ? ' · ' + t('progress.ago', { secs: Math.round(progress.age) }) : ''}
        </p>
      ) : null}
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
  // WHY, and only when something is WRONG. On a green light the sentence says «сервер
  // игры отвечает — всё работает», which is an echo of a light that is now drawn over
  // every page anyway (#2705).
  const why = colour !== 'ok' && LINK_SHORT[reason] ? t(LINK_WORDS[reason]) : ''
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
      {/* ONE CARD FOR THE CLIENT AND THE LINK (#1990, the person's words: «объедини
          блоки игру и связь»). They were two cards asking one question — is there a
          client and does the server answer it — drawn one under the other with the SAME
          pill, in the same colour, saying the same word, because both were read off the
          one verdict (`tools/lib/profile_health.py`). Nothing was lost in the merge: the
          pid and the server the client is talking to, the port the panel reaches it on,
          which Windows session it lives in, the warning about a shared client, why it is
          being restarted and the three presses of its life are all still here, in the
          order somebody reads them — what it is, where it is, what is wrong, what to
          press. */}
      <div className="card">
        {/* THE PILL IS GONE FROM HERE (#2705). The light moved into the header, where
            it is drawn over every screen — this row was the OLD place, and a card head
            repeating the colour a person can already see at the top of the page is the
            second version of the truth `CLAUDE.md` forbids. The head keeps the name of
            what the card is about; everything under it is the FACTS the header's sheet
            does not carry. */}
        <div className="row">
          <span>{t('web.ui.gamelink')}</span>
        </div>
        {/* HOW OLD THE ANSWER IS (#2061) — the person's word for it was «показывай».
            Green means «the server replied», and that reply has a five-minute shelf
            life: an answer four seconds old and one four minutes old paint the same
            dot, so the dot says which it is. Its own line rather than inside the pill
            — a pill is a reading and a reading may not grow (see `LINK_SHORT`). */}
        {(state.game.server_age ?? -1) >= 0 ? (
          <p className="muted small">
            {t('web.ui.link.answered', { span: span(state.game.server_age || 0) })}
          </p>
        ) : null}
        {/* WHY, in the panel's own sentence — under the row rather than inside the pill,
            so it wraps instead of pushing the page sideways (#2061). */}
        {why ? <p className="muted small">{why}</p> : null}
        <p className="muted small">{state.game.text || ''}</p>
        <p className="muted small">{t('web.ui.port', { port: state.link.port })}</p>
        {state.link.user ? (
          <p className="muted small">{t('web.ui.link.user', { user: state.link.user })}</p>
        ) : null}
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
        {/* TWO PROFILES ON ONE CLIENT, which is the one fault about a profile that looks
            like nothing at all — both report themselves healthy while farming a single
            account (#1250). A reading and no button: the login that separates them is
            typed in the window. */}
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
        <ProgressBlock progress={state.progress} />
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
