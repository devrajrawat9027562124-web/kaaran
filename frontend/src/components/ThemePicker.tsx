import { useId, useRef } from 'react'
import { setTheme, THEMES, useTheme } from '../theme'
import { useDismiss } from '../useDismiss'

/** The theme choices, each with a small sample of its paper, ink and highlighter. */
export function ThemePicker() {
  const { choice } = useTheme()
  const name = useId()
  return (
    <fieldset className="theme-picker">
      <legend>Theme</legend>
      {THEMES.map((t) => (
        <label key={t.id} className={t.id === choice ? 'theme-option chosen' : 'theme-option'}>
          <input type="radio" name={name} value={t.id} checked={t.id === choice} onChange={() => setTheme(t.id)} />
          <span className={`swatch swatch-${t.id}`} aria-hidden="true" />
          <span className="theme-text">
            <span className="theme-label">{t.label}</span>
            <span className="theme-about">{t.about}</span>
          </span>
        </label>
      ))}
    </fieldset>
  )
}

/** A "Theme" button that opens the picker: for guests and the site's pages. */
export function ThemeMenu() {
  const menu = useRef<HTMLDetailsElement | null>(null)
  useDismiss(menu)
  return (
    <details className="pop-menu theme-menu" ref={menu}>
      <summary className="nav-link">Theme</summary>
      <div className="menu-pop">
        <ThemePicker />
      </div>
    </details>
  )
}
