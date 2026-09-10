import { useState } from 'react'
import { span, t } from '../i18n'
import { Modal } from './Modal'
import { Pill } from './Pill'
import type { Colour, State } from '../types'

/* THE TRAFFIC LIGHT, IN THE HEADER — the person's words: «В хеадер перенеси светофор
 * состояния игры и панели» (#2705).
 *
 * It used to be the head of the first card on «Состояние», which meant the one reading
 * that answers «работает ли вообще что-нибудь» could only be seen by going to that page.
 * A person on a phone reads the errands, the map, the chat — and had no way to tell,
 * from any of them, that the client had been dead for an hour. The header is drawn over
 * every screen, so that is where it belongs.
 *
 * A MOVE, NOT A COPY. The pill on «Состояние» is gone with the same commit: two drawings
 * of one verdict is exactly what `CLAUDE.md` calls a second version of the truth. The
 * card keeps its FACTS — the pid, the port, the session, the presses of the client's
 * life — and the light that stood over them lives here.
 *
 * NOTHING NEW IS POLLED. Both halves are read off the `/api/state` the app already asks
 * for on its own clock; this component works nothing out that the panel has not already
 * decided (`tools/lib/profile_health.py` for the game, and for the panel the facts
 * `/api/state` carries beside it). The rule is `CLAUDE.md`'s «читаем один раз, дальше
 * слушаем» — a strip on every page may not be the reason the panel asks anything.
 *
 * TWO DOTS, because the person named two things. The GAME dot is the panel's own verdict
 * about the client and the game server. The PANEL dot is about the panel itself: whether
 * this page is reaching it at all, and whether it is allowed to do anything when it is.
 * They fail independently — a panel nobody can reach still paints the last colour it
 * sent, and a panel answering perfectly may be switched off — so one dot could only ever
 * be lying about the other.
 */

/* THE THREE STATUSES (#1911), in the phone's two vocabularies: the word on the pill and
 * the colour it is worn in. The reasons are `tools/lib/profile_health.py`'s own ids, so
 * a reason added there cannot end up wordless here — the lookup falls back to the
 * colour. Red is «нет клиента», amber is «есть клиент, трафика нет» with WHICH half
 * failed in the word, green is «сервер отвечает».
 *
 * They live HERE rather than in `views/StateView.tsx`, where they were written, because
 * the light moved and the words go with it. That page imports them from this file: one
 * table, and a reason added to the panel cannot be worded twice. */
export const LINK_WORDS: Record<string, string> = {
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
  /* …and the account taken by another device (#2061): amber, above green, and the one
   * state whose cure is neither «restart it» nor «fix us» — somebody else is playing. */
  kicked: 'health.kicked',
  not_in_game: 'health.not_in_game',
}

/* THE SAME STATES IN TWO OR THREE WORDS — what goes ON the pill (#2061).
 *
 * A pill is a READING, and a reading is short. The sentences above were being drawn
 * inside it, and the longest of them is 121 characters (`health.not_in_game` in German):
 * on a 360 px phone that is a lozenge some seven hundred pixels wide, and the page grew a
 * horizontal scrollbar — the person's report, «желтое сообщение ломает мобильную вёрстку,
 * появляется прокрутка». It was never only the yellow one: every state here can be long,
 * and #2060, #1982 and #2061 each added another.
 *
 * SPELLED OUT rather than built as `LINK_WORDS[reason] + '.short'`, because a key nobody
 * can grep for is a key that quietly stops being translated — the same reason `WHERE` in
 * `App.tsx` is a table (`tests/test_panel_web.py` checks exactly this).
 */
export const LINK_SHORT: Record<string, string> = {
  traffic: 'health.traffic.short',
  no_client: 'health.no_client.short',
  client_hung: 'health.client_hung.short',
  no_connection: 'health.no_connection.short',
  no_traffic: 'health.no_traffic.short',
  maintenance: 'health.maintenance.short',
  kicked: 'health.kicked.short',
  not_in_game: 'health.not_in_game.short',
}

/* WHAT THE PANEL'S OWN DOT IS SAYING, worst first — the same order a person reads a
 * fault in. Each entry is a fact that is already on `/api/state` (or, for the first, the
 * app's own failed poll), so nothing here is a new reading:
 *
 *   bad   the page did not reach the panel at all — every other colour on the screen is
 *         then as old as the last answer, which is what makes this the first test;
 *   warn  the panel is answering and DOING nothing on purpose: the profile's switch is
 *         off, or the gate is holding everything until the game comes back;
 *   ok    it is answering and free to work.
 */
function panelLight(state: State | undefined, offline: boolean): {
  colour: Colour
  key: string
  fmt?: Record<string, unknown>
} {
  if (offline || !state) return { colour: 'bad', key: 'web.ui.light.panel.offline' }
  if (state.power?.on === false) {
    return {
      colour: 'warn',
      key: 'web.ui.light.panel.power',
      fmt: { mins: Math.floor((state.power?.off_for_sec || 0) / 60) },
    }
  }
  if (state.gate?.held) {
    return {
      colour: 'warn',
      key: 'web.ui.light.panel.gate',
      fmt: { mins: Math.floor((state.gate?.for_sec || 0) / 60) },
    }
  }
  return { colour: 'ok', key: 'web.ui.light.panel.ok' }
}

/* The word on the PANEL's own pill, one key per colour — spelled out for the reason
 * `LINK_SHORT` is: a key built by joining strings is a key nobody can grep for, and a key
 * nobody can grep for quietly stops being translated (`tests/test_panel_web.py`). */
const PANEL_WORD: Record<string, string> = {
  ok: 'web.ui.light.panel.word.ok',
  warn: 'web.ui.light.panel.word.warn',
  bad: 'web.ui.light.panel.word.bad',
}

export function LinkLight({ state, offline }: { state?: State; offline: boolean }) {
  const [open, setOpen] = useState(false)
  /* The GAME's colour is the panel's verdict and is never worked out here — but an
     unreachable panel makes it stale, and a green dot over a page that has not heard
     anything for a minute is the one thing this light must not do. */
  const game: Colour = offline ? 'bad' : (state?.game.colour
                                          || (state?.game.running ? 'warn' : 'bad'))
  const reason = state?.game.reason || ''
  const word = t(LINK_SHORT[reason] || LINK_WORDS[reason] || 'web.ui.off')
  /* The sentence under the pill: the panel's own diagnosis where it has one, and the
     client's own words otherwise. Never `t('')`, which asks the dictionary for nothing
     and gets nothing back. */
  const why = LINK_WORDS[reason] ? t(LINK_WORDS[reason]) : (state?.game.text || '')
  const panel = panelLight(state, offline)
  const age = state?.game.server_age ?? -1
  return (
    <>
      <button
        className="head-light"
        onClick={() => setOpen(true)}
        aria-label={t('web.ui.light.open')}
        title={t('web.ui.light.open')}
      >
        <span className={'dot ' + game} />
        <span className={'dot ' + panel.colour} />
      </button>
      {open ? (
        <Modal title={t('web.ui.light.title')} onClose={() => setOpen(false)}>
          <div className="row">
            <span>{t('web.ui.light.game')}</span>
            <Pill tone={game}>{offline ? t('web.ui.light.stale') : word}</Pill>
          </div>
          {why ? <p className="muted small">{why}</p> : null}
          {age >= 0 ? (
            <p className="muted small">{t('web.ui.link.answered', { span: span(age) })}</p>
          ) : null}
          <div className="row">
            <span>{t('web.ui.light.panel')}</span>
            <Pill tone={panel.colour}>{t(PANEL_WORD[panel.colour])}</Pill>
          </div>
          <p className="muted small">{t(panel.key, panel.fmt)}</p>
          {state?.panel?.version ? (
            <p className="muted small">
              {t('web.ui.version')}: {state.panel.version}
            </p>
          ) : null}
          {/* WHAT THE COLOURS MEAN, spelled out. The light is now on every screen and is
              the first thing a person away from the machine looks at, so «жёлтый» has to
              say what to do about it rather than only that something is off. */}
          <p className="muted small">
            <b>{t('web.ui.light.legend')}</b>
          </p>
          <p className="muted small">{t('web.ui.light.legend.ok')}</p>
          <p className="muted small">{t('web.ui.light.legend.warn')}</p>
          <p className="muted small">{t('web.ui.light.legend.bad')}</p>
        </Modal>
      ) : null}
    </>
  )
}
