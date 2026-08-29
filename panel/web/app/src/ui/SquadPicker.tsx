import { useState } from 'react'
import { t } from '../i18n'
import { pressWord } from './press'
import { useToast } from './Toast'
import type { Field, PressAnswer, SquadSlot } from '../types'

/* THE SQUAD PICKER (#2062) — four pictures in a row, click to switch a squad off.
 *
 * The person's decision, in their words: «должны быть 4 картинки в ряд с нашими героями,
 * именно те, что в игре у данного игрока, они меняются в зависимости от героев в отряде,
 * клик по картинке должен включать и отключать этот отряд, выключенный делаем серым.
 * Везде где есть выбор отрядов вставляем этот виджет и берем за правило».
 *
 * IT IS ONE CONTROL, WHEREVER SQUADS ARE PICKED. The rally auto-join, the manual rally,
 * the gear on «Таймеры» and the golden-zombie hunt all drew their own row of boxes
 * labelled «Отряд 1»..«Отряд 4», and a number is not what anybody recognises their own
 * army by. So a field declares `kind: 'squads'` and this draws it — the panel sends the
 * faces (`panel/runtime/squad_picker.py`), the browser fetches each picture once.
 *
 * ONE FACE, AS THE TILE'S BACKGROUND, AND THE TILE IS A SQUARE. The person looked at
 * three little portraits in a row and said what it was: «в виджете героев оставляй спрайт
 * первого героя, сейчас там мешанина, картинки фоном, квадратные». So the picture is the
 * tile — full brightness, edge to edge — and the name sits over it in its own bubble,
 * because the game's sprites run from near-white to near-black and a word laid straight
 * onto one of them is readable on some squads and not on others.
 *
 * THE FACE IS THE HERO THE GAME KEEPS FIRST, position 1 of the formation, and when he
 * cannot be named the tile draws its NUMBER rather than the hero behind him
 * (`panel/runtime/squad_picker.py`).
 *
 * THE PRESS IS OPTIMISTIC for exactly as long as the answer takes: the tile greys the
 * moment it is touched, because a screen that is polled every couple of seconds would
 * otherwise spring back under the thumb and read as a press that did not land.
 */
export function SquadPicker({
  field,
  send,
  after,
}: {
  field: Field
  send: (key: string, value: string) => Promise<PressAnswer>
  after: () => void
}) {
  const toast = useToast()
  const slots: SquadSlot[] = field.squads || []
  const [draft, setDraft] = useState<string | null>(null)
  const chosen = new Set(
    (draft ?? String(field.value ?? ''))
      .split(',')
      .map((piece) => piece.trim())
      .filter(Boolean),
  )

  const move = async (slot: number) => {
    const key = String(slot)
    const want = new Set(chosen)
    if (field.single) {
      // ONE SQUAD, AND CLICKING IT AGAIN LEAVES IT ON: the hunt has to send something,
      // so an empty choice here is not a state the panel can act on.
      want.clear()
      want.add(key)
    } else if (want.has(key)) want.delete(key)
    else want.add(key)
    const value = [...want].sort().join(',')
    setDraft(value)
    const answer = await send(field.key, value)
    if (answer.ok === false || answer.error) {
      setDraft(null)
      toast(pressWord(answer))
    } else if (answer.reason) toast(t(answer.reason))
    window.setTimeout(() => {
      setDraft(null)
      after()
    }, 400)
  }

  return (
    <div className="field">
      <label className="muted small">{t(field.label, field.label_fmt)}</label>
      <div className="squads">
        {slots.map((slot) => {
          const on = chosen.has(String(slot.n))
          const face = (slot.faces || [])[0] || ''
          /* THE KEY IS BUILT HERE AND NOT INSIDE `t(...)`: the i18n scan reads the
             literal an argument starts with, so a glued key is reported as the half key
             «squads.kind.» that no locale has (tests/test_panel_web.py). */
          const stateKey = slot.state ? `squads.kind.${slot.state}` : ''
          return (
            <button
              key={slot.n}
              type="button"
              className={'squad' + (on ? '' : ' off')}
              aria-pressed={on}
              title={t('squads.pick.one', { n: slot.n })}
              onClick={() => void move(slot.n)}
            >
              {face ? (
                /* THE PICTURE IS THE TILE, not an image inside it: a background paints
                   edge to edge, needs no size of its own and cannot drag the square out
                   of shape whatever the sprite's own proportions are. */
                <span
                  className="squad-art"
                  style={{ backgroundImage: `url(${face})` }}
                  aria-hidden="true"
                />
              ) : (
                /* NO PICTURE IS THE HONEST ANSWER, never a stand-in face. */
                <span className="squad-blank">{slot.n}</span>
              )}
              <span className="squad-name">
                {t('squads.pick.one', { n: slot.n })}
                {stateKey ? <em>{t(stateKey)}</em> : null}
              </span>
            </button>
          )
        })}
      </div>
      {field.hint ? <p className="muted small">{t(field.hint)}</p> : null}
    </div>
  )
}
