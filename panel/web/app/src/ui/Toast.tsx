import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

/* The one thing this front-end says out of turn: what a press came to. Three seconds,
 * one line, never stacked — a phone screen has no room for a queue of them. */
const TOAST_MS = 3000

const Ctx = createContext<(text: string) => void>(() => {})

export function useToast() {
  return useContext(Ctx)
}

export function ToastHost({ children }: { children: React.ReactNode }) {
  const [text, setText] = useState('')
  const timer = useRef<number | undefined>(undefined)
  const say = useCallback((what: string) => {
    setText(what)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setText(''), TOAST_MS)
  }, [])
  const value = useMemo(() => say, [say])
  return (
    <Ctx.Provider value={value}>
      {children}
      {text ? <p className="toast">{text}</p> : null}
    </Ctx.Provider>
  )
}
