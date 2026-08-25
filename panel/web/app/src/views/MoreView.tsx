import { t } from '../i18n'
import type { Screen } from '../types'

/* «Ещё»: the screens this profile's tabs offer. A tab switched off in the profile is not
 * built and therefore not here — the phone shows what this profile HAS, exactly as the
 * window does. */
export function MoreView({ screens, onOpen }: { screens: Screen[]; onOpen: (id: string) => void }) {
  return (
    <>
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
