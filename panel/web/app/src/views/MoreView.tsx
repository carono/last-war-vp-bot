import { t } from '../i18n'
import type { Screen } from '../types'
import type { Theme } from '../ui/theme'

/* THE THEME PICKER LIVES HERE (#2061) — «Ещё» is where the things that belong to the
 * front-end itself have always gone, and this one belongs to the front-end more
 * literally than any of them: it is the browser's own setting and never reaches the
 * panel (`ui/theme.ts` says why). Three chips rather than a switch, because there are
 * three answers and the third — «как на телефоне» — is the one most people want. */
const THEMES: { id: Theme; key: string }[] = [
  { id: 'system', key: 'web.ui.theme.system' },
  { id: 'dark', key: 'web.ui.theme.dark' },
  { id: 'light', key: 'web.ui.theme.light' },
]

/* «Ещё»: the screens this profile's tabs offer. A tab switched off in the profile is not
 * built and therefore not here — the phone shows what this profile HAS, exactly as the
 * window does. */
export function MoreView({
  screens,
  onOpen,
  theme,
  onTheme,
}: {
  screens: Screen[]
  onOpen: (id: string) => void
  theme: Theme
  onTheme: (want: Theme) => void
}) {
  return (
    <>
      <div className="card">
        <div className="head">{t('web.ui.theme')}</div>
        <div className="chips">
          {THEMES.map((entry) => (
            <button
              key={entry.id}
              className={'chip' + (theme === entry.id ? ' on' : '')}
              onClick={() => onTheme(entry.id)}
            >
              {t(entry.key)}
            </button>
          ))}
        </div>
      </div>
      <div>
        {screens.map((screen) => (
          <button key={screen.id} className="item act row wide" onClick={() => onOpen(screen.id)}>
            {t(screen.title)}
          </button>
        ))}
      </div>
      {!screens.length ? <p className="muted">{t('web.ui.more.empty')}</p> : null}
    </>
  )
}
