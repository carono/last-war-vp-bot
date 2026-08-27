import { useEffect, useRef, useState } from 'react'
import { t } from '../i18n'
import { pressWord } from './press'
import { SwitchRow } from './SwitchRow'
import { useToast } from './Toast'
import type { Field, PressAnswer } from '../types'

/* ONE FIELD, WHEREVER IT IS DRAWN (#2017).
 *
 * It was a tab screen's knob and nothing else, and the gear on «Таймеры» draws exactly
 * the same four controls over exactly the same `Field` — the only difference being which
 * route the value is posted to. So the control moved here and the route became a prop:
 * a screen sends its `set` press, a gear sends `/api/errand/option`, and neither has a
 * copy of how a switch or a number is drawn.
 */
/* A KNOB, drawn as the control its kind names (#1976). The kind comes from the type the
 * knob was declared with, so nothing here guesses from a name — and the value is sent
 * back as the same `set` press whatever the control, so a tab answers for its own knobs
 * in one handler.
 *
 * A TYPED FIELD IS COMMITTED ON LEAVING IT, never on every keystroke: a panel that saved
 * «4», «40», «400» on the way to «4000» would spend three of those readings acting on a
 * number nobody meant. A switch is committed at once, because there is nothing half-typed
 * about it. */
export function FieldRow({
  field,
  send,
  after,
}: {
  field: Field
  /* Where the moved value goes. Answers the same `PressAnswer` every press does. */
  send: (key: string, value: string | number | boolean) => Promise<PressAnswer>
  after: () => void
}) {
  const toast = useToast()
  const [draft, setDraft] = useState(String(field.value ?? ''))
  const sent = useRef(String(field.value ?? ''))

  useEffect(() => {
    // The screen re-reads on the poll; a box nobody is typing in follows the panel.
    if (document.activeElement?.getAttribute('data-field') !== field.key) {
      setDraft(String(field.value ?? ''))
      sent.current = String(field.value ?? '')
    }
  }, [field.value, field.key])

  const commit = async (value: string | number | boolean) => {
    const answer = await send(field.key, value)
    if (answer.ok === false || answer.error) toast(pressWord(answer))
    else if (answer.reason) toast(t(answer.reason))
    window.setTimeout(after, 400)
  }

  if (field.kind === 'choice') {
    return (
      <div className="field">
        <label className="muted small" htmlFor={'f-' + field.key}>
          {t(field.label, field.label_fmt)}
        </label>
        <select
          id={'f-' + field.key}
          value={String(field.value ?? '')}
          onChange={(e) => void commit(e.target.value)}
        >
          {(field.options || []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.text}
            </option>
          ))}
        </select>
        {field.hint ? <p className="muted small">{t(field.hint)}</p> : null}
      </div>
    )
  }
  if (field.kind === 'switch') {
    return (
      <>
        <SwitchRow
          title={t(field.label, field.label_fmt)}
          on={!!field.value}
          onChange={async (want) => {
            await commit(want)
          }}
        />
        {field.hint ? <p className="muted small">{t(field.hint)}</p> : null}
      </>
    )
  }
  return (
    <div className="field">
      <label className="muted small" htmlFor={'f-' + field.key}>
        {t(field.label, field.label_fmt)}
      </label>
      <input
        id={'f-' + field.key}
        data-field={field.key}
        type={field.kind === 'number' ? 'number' : 'text'}
        inputMode={field.kind === 'number' ? 'decimal' : undefined}
        min={field.min}
        max={field.max}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (draft === sent.current) return
          sent.current = draft
          void commit(draft)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        }}
      />
      {field.hint ? <p className="muted small">{t(field.hint)}</p> : null}
    </div>
  )
}
