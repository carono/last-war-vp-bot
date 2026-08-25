import { useState } from 'react'

/* A switch, and THE WHOLE ROW IS THE TARGET. The drawn box is 26 px of fingernail; the
 * label beside it is the width of the card, so the two are one `<label>` — measured on a
 * 360×640 phone, and the reason every switch on this front-end is built this way. */
export function SwitchRow({
  title,
  on,
  onChange,
  muted,
}: {
  title: string
  on: boolean
  onChange: (want: boolean) => Promise<void> | void
  muted?: boolean
}) {
  const [busy, setBusy] = useState(false)
  return (
    <label className="row switch-row">
      <span className={muted ? 'muted small' : 'title'}>{title}</span>
      <input
        type="checkbox"
        checked={on}
        disabled={busy}
        onChange={async (e) => {
          const want = e.target.checked
          setBusy(true)
          try {
            await onChange(want)
          } finally {
            setBusy(false)
          }
        }}
      />
    </label>
  )
}
