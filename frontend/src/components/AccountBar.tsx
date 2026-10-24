import { useEffect, useRef, useState } from 'react'
import { updateProgram, type Program, type ProgramFields, type Session } from '../account'
import { BackendError } from '../backend'
import { linkTo } from '../router'
import { ProgramsDialog, type DialogMode } from './ProgramsDialog'

interface Props {
  session: Session | null
  current: Omit<ProgramFields, 'title'>       // the program in the editor
  saved: { id: number; title: string } | null  // the saved program it was opened from, if any
  onSaved: (program: Program) => void
  onOpen: (program: Program) => void
  onSignOut: () => void
}

function initials(name: string): string {
  return name.split(' ').filter(Boolean).slice(0, 2).map((word) => word[0].toUpperCase()).join('')
}

/** The top bar's account corner: Log in / Sign up, or Save, My programs and the account menu. */
export function AccountBar({ session, current, saved, onSaved, onOpen, onSignOut }: Props) {
  const [dialog, setDialog] = useState<DialogMode | null>(null)
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [error, setError] = useState<string | null>(null)
  const menu = useRef<HTMLDetailsElement | null>(null)

  // The account menu closes when you click anywhere else
  useEffect(() => {
    const away = (e: PointerEvent) => {
      if (menu.current?.open && !menu.current.contains(e.target as Node)) menu.current.open = false
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [])

  if (!session) {
    return (
      <div className="account">
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

  return (
    <div className="account">
      <button type="button" className={saving === 'saved' ? 'quiet save done' : 'quiet save'} onClick={save}
        disabled={saving === 'saving'}
        title={saved ? `Save changes to "${saved.title}"` : 'Save this program to your account'}>
        {saving === 'saving' ? 'Saving…' : saving === 'saved' ? 'Saved' : 'Save'}
      </button>
      <button type="button" className="quiet" onClick={() => setDialog('programs')}>My programs</button>
      <details className="account-menu" ref={menu}>
        <summary aria-label={`Account: ${session.user.name}`}>
          <span className="avatar" aria-hidden="true">{initials(session.user.name)}</span>
        </summary>
        <div className="account-pop">
          <p><strong>{session.user.name}</strong><br />{session.user.email}</p>
          <button type="button" onClick={onSignOut}>Log out</button>
        </div>
      </details>
      {error && (
        <p className="account-error" role="alert">
          {error}
          <button type="button" className="quiet" onClick={() => setError(null)}>Dismiss</button>
        </p>
      )}
      {dialog && (
        <ProgramsDialog mode={dialog} session={session} current={current} onMode={setDialog}
          onSaved={onSaved} onOpen={onOpen} onClose={() => setDialog(null)} onSessionEnded={onSignOut} />
      )}
    </div>
  )
}
