import { useEffect, type RefObject } from 'react'

/** A <details> pop-up closes when you click elsewhere or press Escape. */
export function useDismiss(ref: RefObject<HTMLDetailsElement | null>) {
  useEffect(() => {
    const close = () => {
      if (ref.current) ref.current.open = false
    }
    const away = (e: PointerEvent) => {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) close()
    }
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && ref.current?.open) {
        close()
        ref.current.querySelector('summary')?.focus()
      }
    }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', escape)
    }
  }, [ref])
}
