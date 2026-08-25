import { useEffect, useRef } from 'react'
import { t } from '../i18n'
import type { LogLine } from '../types'

/* What has been said, this profile's own. The tail is held in the app and trimmed there;
 * this only draws it and keeps the newest line in sight. */
export function LogView({
  lines,
  notify,
  onNotify,
}: {
  lines: LogLine[]
  notify: boolean
  onNotify: (want: boolean) => void
}) {
  const end = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' })
  }, [lines])
  return (
    <>
      <label className="row switch-row">
        <span className="title">{t('web.ui.notify')}</span>
        <input type="checkbox" checked={notify} onChange={(e) => onNotify(e.target.checked)} />
      </label>
      <div className="log">
        {lines.map((line, i) => (
          <div key={i} className={line.sev || ''}>
            {line.text}
          </div>
        ))}
        <div ref={end} />
      </div>
      {!lines.length ? <p className="muted">{t('web.ui.log.empty')}</p> : null}
    </>
  )
}
