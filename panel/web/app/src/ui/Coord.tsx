import { post } from '../api'
import { t } from '../i18n'
import { useToast } from './Toast'
import type { CoordPart, PressAnswer } from '../types'

/* ANY COORDINATE, ANYWHERE, IS A PLACE TO GO (#1982) — the person's rule: «любые
 * координаты должны быть кликабельны и приводить к переходу на них в игре». The window
 * has had this since it had a log; this is the same thing on the phone.
 *
 * NOTHING IS PARSED HERE. The panel marks the coordinates it is already about to send,
 * off the one parser this repository has (`tools/lib/coords.py`, via
 * `panel/web/coordlinks.py`), and hands over the string already cut into parts. A regex
 * in the browser would be a second answer to «is this a place» — and `0/3` is not one.
 *
 * NO QUESTION IS ASKED BEFORE THE JUMP. It walks the client's own camera: nothing is
 * marched, nothing is spent, and jumping back undoes it. Confirmation belongs on presses
 * that cost something (a squad leaving the base), not on looking. */
/* THE JUMP ITSELF, so that more than one control can offer it (#1999). A tile on «Карта»
 * IS the coordinate it draws — the whole of it is pressed to go there — and it must send
 * exactly what the underlined coordinate in a line of prose sends, out of one place. */
export function useJump() {
  const toast = useToast()
  return async (part: CoordPart) => {
    const answer = await post<PressAnswer>('/api/actions/run', {
      name: 'goto_coord',
      args: { x: part.x, y: part.y, server: part.server || 0 },
    })
    toast(answer.ok === false || answer.error
      ? t('web.ui.refused')
      : t('web.ui.coord.jumping', { where: part.text }))
  }
}

/* THE FIRST PLACE A MARKED STRING NAMES, or `null`. What a tile uses to decide whether
 * it is a button: an item whose name is a coordinate goes somewhere when it is pressed,
 * and an item whose name is a warzone number or a player does not. */
export function firstPlace(
  parts?: (CoordPart | { t: string } | { c: CoordPart })[] | null,
): CoordPart | null {
  for (const part of parts || []) {
    const piece = part as { c?: CoordPart }
    if (piece.c) return piece.c
  }
  return null
}

export function Coord({ part }: { part: CoordPart }) {
  const jump = useJump()
  const where = part.text
  return (
    <button
      className="coord"
      onClick={async (e) => {
        // A coordinate can sit inside a row that is itself a button (a summary tile, an
        // errand): the press is about the place, not about the row.
        e.stopPropagation()
        e.preventDefault()
        await jump(part)
      }}
    >
      {where}
    </button>
  )
}

/* A string the panel may have marked. Unmarked strings — the great majority — are drawn
 * exactly as before, so nothing pays for this but the lines that hold a coordinate. */
export function Marked({
  text,
  parts,
}: {
  text?: string | null
  parts?: (CoordPart | { t: string } | { c: CoordPart })[] | null
}) {
  if (!parts || !parts.length) return <>{text || ''}</>
  return (
    <>
      {parts.map((part, i) => {
        const piece = part as { t?: string; c?: CoordPart }
        if (piece.c) return <Coord key={i} part={piece.c} />
        return <span key={i}>{piece.t || ''}</span>
      })}
    </>
  )
}
