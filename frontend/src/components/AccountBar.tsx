import { useRef, useState } from 'react'
import { updateProgram, type Program, type ProgramFields, type Session } from '../account'
import { BackendError } from '../backend'
import { linkTo } from '../router'
import { FeedbackDialog } from './FeedbackDialog'
import { ProgramsDialog, type DialogMode } from './ProgramsDialog'
import { useDismiss } from '../useDismiss'
import { ThemeMenu, ThemePicker } from './ThemePicker'

interface Props {
  session: Session | null
  current: Omit<ProgramFields, 'title'>       // the program in the editor
  saved: { id: number; title: string } | null  // the saved program it was opened from, if any
  step: number | null                          // the step being looked at, for feedback
  onSaved: (program: Program) => void
  onOpen: (program: Program) => void
  onSignOut: () => void  // the session ended
  onLogOut: () => void   // the Log out button
}

function initials(name: string): string {
  return name.split(' ').filter(Boolean).slice(0, 2).map((word) => word[0].toUpperCase()).join('')
}

/**
 * The top bar's account corner. Guests: Theme, Log in, Sign up. Logged in:
 * Save, My programs, and the profile menu (feedback, theme, log out).
 */
export function AccountBar({ session, current, saved, step, onSaved, onOpen, onSignOut, onLogOut }: Props) {
  const [dialog, setDialog] = useState<DialogMode | 'feedback' | null>(null)
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [error, setError] = useState<string | null>(null)
  const menu = useRef<HTMLDetailsElement | null>(null)
  useDismiss(menu)

  if (!session) {
    return (
      <div className="account">
        <ThemeMenu />
        <a className="nav-link" href={linkTo('login')}>Log in</a>
        <a className="button-link primary" href={linkTo('signup')} title="An account saves your programs">Sign up</a>
      </div>
    )
  }

  // Save: changes go to the program it was opened from; a new program is named first
  const save = async () => {
    setError(null)
    if (!saved) {
      setDialog('save')
      return
    }
    setSaving('saving')
    try {
      onSaved(await updateProgram(session.token, saved.id, { title: saved.title, ...current }))
      setSaving('saved')
      window.setTimeout(() => setSaving('idle'), 1800)
    } catch (e) {
      setSaving('idle')
      if (e instanceof BackendError && e.status === 401) onSignOut()
      else if (e instanceof BackendError && e.status === 404) setDialog('save')  // deleted meanwhile
      else setError(e instanceof Error ? e.message : String(e))
    }
  }

  const openFeedback = () => {
    if (menu.current) menu.current.open = false
    setDialog('feedback')
  }

  return (
    <div className="account">
      <button type="button" className={saving === 'saved' ? 'quiet save done' : 'quiet save'} onClick={save}
        disabled={saving === 'saving'}
        title={saved ? `Save changes to "${saved.title}"` : 'Save this program to your account'}>
        {saving === 'saving' ? 'Saving…' : saving === 'saved' ? 'Saved' : 'Save'}
      </button>
      <button type="button" className="quiet" onClick={() => setDialog('programs')}>My programs</button>
      <details className="pop-menu account-menu" ref={menu}>
        <summary aria-label={`Your profile: ${session.user.name}`} title="Your profile, feedback and theme">
          <span className="avatar" aria-hidden="true">{initials(session.user.name)}</span>
        </summary>
        <div className="menu-pop profile-pop">
          <p className="profile-who"><strong>{session.user.name}</strong><br />{session.user.email}</p>
          <button type="button" className="menu-item" onClick={openFeedback}>
            <span className="menu-item-label">Send feedback</span>
            <span className="menu-item-about">Report a problem with Kaaran or your program, or suggest something</span>
          </button>
          <ThemePicker />
          <button type="button" className="menu-item" onClick={onLogOut}>
            <span className="menu-item-label">Log out</span>
          </button>
        </div>
      </details>
      {error && (
        <p className="account-error" role="alert">
          {error}
          <button type="button" className="quiet" onClick={() => setError(null)}>Dismiss</button>
        </p>
      )}
      {dialog === 'feedback' && (
        <FeedbackDialog session={session} current={current} step={step} onClose={() => setDialog(null)}
          onSessionEnded={onSignOut} />
      )}
      {(dialog === 'save' || dialog === 'programs') && (
        <ProgramsDialog mode={dialog} session={session} current={current} onMode={setDialog}
          onSaved={onSaved} onOpen={onOpen} onClose={() => setDialog(null)} onSessionEnded={onSignOut} />
      )}
    </div>
  )
}
