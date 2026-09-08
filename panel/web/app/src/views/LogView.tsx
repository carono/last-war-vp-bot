import { useEffect, useRef } from 'react'
import { t } from '../i18n'
import { Marked } from '../ui/Coord'
import { SwitchRow } from '../ui/SwitchRow'
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
      {/* THE ONE SWITCH COMPONENT (#2660) — this row was a hand-written copy of it, so
          the whole-row target measured for a thumb stopped at the box on this page. */}
      <SwitchRow title={t('web.ui.notify')} on={notify} onChange={onNotify} />
      <div className="log">
        {/* A COORDINATE IN A LINE IS A PLACE TO GO (#1982) — the window's log has had
            this since it had a log, and the phone's now has it off the same marking. */}
        {lines.map((line, i) => (
          <div key={i} className={line.sev || ''}>
            <Marked text={line.text} parts={line.text_parts} />
          </div>
        ))}
        <div ref={end} />
      </div>
      {!lines.length ? <p className="muted">{t('web.ui.log.empty')}</p> : null}
    </>
  )
}
