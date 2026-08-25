import { useState } from 'react'
import { post } from '../api'
import { t } from '../i18n'
import { useToast } from '../ui/Toast'
import type { ActionRow, PressAnswer } from '../types'

/* Every scenario this profile has, and one press each. The list only changes when the
 * files on disk do, so it is fetched once per profile and filtered in the browser. */
export function ActionsView({
  actions,
  running,
  refresh,
}: {
  actions: ActionRow[]
  running: string
  refresh: () => void
}) {
  const toast = useToast()
  const [needle, setNeedle] = useState('')
  const [busy, setBusy] = useState('')
  const shown = actions.filter(
    (a) =>
      !needle ||
      a.title.toLowerCase().includes(needle.toLowerCase()) ||
      a.name.includes(needle.toLowerCase()),
  )
  return (
    <>
      <input
        type="search"
        autoComplete="off"
        placeholder={t('web.ui.search')}
        value={needle}
        onChange={(e) => setNeedle(e.target.value)}
      />
      <div>
        {shown.map((action) => (
          <div key={action.name} className={'item act' + (action.name === running ? ' running' : '')}>
            <div className="title">{action.title}</div>
            <div className="foot">
              <span className="muted small">{action.name}</span>
              <button
                className="go"
                disabled={busy === action.name}
                onClick={async () => {
                  setBusy(action.name)
                  try {
                    const answer = await post<PressAnswer>('/api/actions/run', { name: action.name })
                    toast(answer.ok ? t('web.ui.started', { name: action.title }) : t('web.ui.refused'))
                    if (answer.ok) refresh()      // show the running mark now, not in 2.5 s
                  } finally {
                    setBusy('')
                  }
                }}
              >
                {t('web.ui.run')}
              </button>
            </div>
          </div>
        ))}
      </div>
      {!shown.length ? <p className="muted">{t('web.ui.actions.none')}</p> : null}
    </>
  )
}
