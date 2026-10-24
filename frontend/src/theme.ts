// Colour themes. The choice is remembered in this browser and applied as
// <html data-theme="...">; index.css holds each theme's colours. index.html
// applies it before the page first draws, so there's no flash of the wrong one.
import { useSyncExternalStore } from 'react'

export type Theme = 'paper' | 'sepia' | 'blackboard' | 'night' | 'contrast'
export type ThemeChoice = Theme | 'system'

export const THEMES: { id: ThemeChoice; label: string; about: string }[] = [
  { id: 'system', label: 'Match my computer', about: 'Paper by day, Blackboard in dark mode' },
  { id: 'paper', label: 'Paper', about: 'White paper and blue ink' },
  { id: 'sepia', label: 'Sepia', about: 'Warm paper with less blue light, for long reading' },
  { id: 'blackboard', label: 'Blackboard', about: 'Dark green, like a classroom board' },
  { id: 'night', label: 'Night', about: 'Dim and warm, for studying late' },
  { id: 'contrast', label: 'High contrast', about: 'Black on white, strongest colours' },
]

const KEY = 'kaaran.theme'
const media = window.matchMedia('(prefers-color-scheme: dark)')
const listeners = new Set<() => void>()

function stored(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(KEY)
    return THEMES.some((t) => t.id === value) ? (value as ThemeChoice) : 'system'
  } catch {
    return 'system'
  }
}

let choice = stored()

function resolve(c: ThemeChoice): Theme {
  return c === 'system' ? (media.matches ? 'blackboard' : 'paper') : c
}

function apply() {
  document.documentElement.dataset.theme = resolve(choice)
  listeners.forEach((listener) => listener())
}

media.addEventListener('change', () => {
  if (choice === 'system') apply()
})

export function setTheme(next: ThemeChoice) {
  choice = next
  try {
    window.localStorage.setItem(KEY, next)
  } catch {
    // not remembered: it still applies for this visit
  }
  apply()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The chosen theme ("system" included) and the one actually showing. */
export function useTheme(): { choice: ThemeChoice; theme: Theme } {
  const snapshot = useSyncExternalStore(subscribe, () => `${choice} ${resolve(choice)}`)
  const [c, t] = snapshot.split(' ')
  return { choice: c as ThemeChoice, theme: t as Theme }
}
