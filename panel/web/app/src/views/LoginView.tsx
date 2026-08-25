import { useState } from 'react'
import { post } from '../api'
import { t } from '../i18n'

/* The token box, shown until the panel says the cookie is good. The locale table answers
 * without a token (`PUBLIC` in panel/web/server.py), so this speaks the panel's language
 * rather than showing locale keys to whoever is trying to get in. */
export function LoginView() {
  const [token, setToken] = useState('')
  const [bad, setBad] = useState(false)
  const enter = async () => {
    const answer = await post<{ ok?: boolean }>('/api/login', { token: token.trim() })
    if (answer.ok) location.replace(location.pathname)
    else setBad(true)
  }
  return (
    <section className="gate">
      <h1>{t('web.ui.title')}</h1>
      <p className="muted">{t('web.ui.login.hint')}</p>
      <input
        type="password"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        placeholder={t('web.ui.login.token')}
        value={token}
        onChange={(e) => setToken(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void enter()
        }}
      />
      <button onClick={() => void enter()}>{t('web.ui.login.enter')}</button>
      {bad ? <p className="bad">{t('web.ui.login.bad')}</p> : null}
    </section>
  )
}
