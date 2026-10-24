import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  createProgram, deleteProgram, getProgram, listPrograms, type Program, type ProgramFields, type ProgramSummary,
  type Session,
} from '../account'
import { BackendError } from '../backend'
import type { Language } from '../types'

const LABEL: Record<Language, string> = { python: 'Python', c: 'C', cpp: 'C++' }

export type DialogMode = 'save' | 'programs'

interface Props {
  mode: DialogMode
  session: Session
  current: Omit<ProgramFields, 'title'>  // the program in the editor
  onMode: (mode: DialogMode) => void
  onSaved: (program: Program) => void
  onOpen: (program: Program) => void
  onClose: () => void
  onSessionEnded: () => void
}

/** A name from the program's first comment ("# Average of marks"), or a plain one. */
function guessTitle(code: string): string {
  const first = code.split('\n').map((line) => line.trim()).find(Boolean) ?? ''
  const comment = first.match(/^(?:#|\/\/|\/\*)\s*(.*?)\s*(?:\*\/)?$/)
  return comment?.[1].slice(0, 80) || 'Untitled program'
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

function savedWhen(seconds: number): string {
  const minutes = Math.round((seconds * 1000 - Date.now()) / 60_000)
  if (Math.abs(minutes) < 60) return relative.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return relative.format(hours, 'hour')
  return relative.format(Math.round(hours / 24), 'day')
}

/** My programs (open or delete one) and Save (name a new one), in one modal dialog. */
export function ProgramsDialog({ mode, session, current, onMode, onSaved, onOpen, onClose, onSessionEnded }: Props) {
  const dialog = useRef<HTMLDialogElement | null>(null)
  const [title, setTitle] = useState(() => guessTitle(current.code))
  const [programs, setPrograms] = useState<ProgramSummary[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)

  useEffect(() => {
    if (dialog.current && !dialog.current.open) dialog.current.showModal()
  }, [])

  const fail = (e: unknown) => {
    if (e instanceof BackendError && e.status === 401) onSessionEnded()
    setError(e instanceof Error ? e.message : String(e))
  }

  useEffect(() => {
    if (mode !== 'programs') return
    let current = true
    listPrograms(session.token)
      .then((list) => current && setPrograms(list))
      .catch((e: unknown) => {
        if (!current) return
        if (e instanceof BackendError && e.status === 401) onSessionEnded()
        setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      current = false
    }
  }, [mode, session.token, onSessionEnded])

  const close = () => dialog.current?.close()

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onSaved(await createProgram(session.token, { title: title.trim() || 'Untitled program', ...current }))
      close()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const open = async (id: number) => {
    setBusy(true)
    setError(null)
    try {
      onOpen(await getProgram(session.token, id))
      close()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    setBusy(true)
    setError(null)
    try {
      await deleteProgram(session.token, id)
      setPrograms((list) => list?.filter((p) => p.id !== id) ?? null)
      setConfirming(null)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog ref={dialog} className="programs-dialog" aria-labelledby="programs-heading" onClose={onClose}
      onClick={(e) => { if (e.target === dialog.current) close() }}>
      {mode === 'save' ? (
        <form className="dialog-body" onSubmit={save}>
          <h2 id="programs-heading">Save this program</h2>
          <label className="dialog-field">
            Name
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} autoFocus />
          </label>
          <p className="dialog-note">
            {LABEL[current.language]}{current.input.trim() ? ', with what the Input tab holds' : ''}. Open it
            again any time from My programs.
          </p>
          {error && <p className="error-text" role="alert">{error}</p>}
          <div className="dialog-actions">
            <button type="button" className="quiet" onClick={close}>Cancel</button>
            <button type="submit" className="run" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
          </div>
        </form>
      ) : (
        <div className="dialog-body">
          <div className="dialog-head">
            <h2 id="programs-heading">My programs</h2>
            <button type="button" className="quiet" onClick={close}>Close</button>
          </div>
          {programs === null && !error && <p className="empty">Loading your programs…</p>}
          {programs?.length === 0 && (
            <p className="empty">Nothing saved yet. Write or open a program, then press Save.</p>
          )}
          {programs && programs.length > 0 && (
            <ul className="program-list">
              {programs.map((p) => (
                <li key={p.id}>
                  <button type="button" className="program-open" onClick={() => open(p.id)} disabled={busy}>
                    <span className="program-title">{p.title}</span>
                    <span className="program-meta">{LABEL[p.language]}, saved {savedWhen(p.updated)}</span>
                  </button>
                  {confirming === p.id ? (
                    <span className="program-confirm">
                      <button type="button" className="danger" onClick={() => remove(p.id)} disabled={busy}>
                        Delete
                      </button>
                      <button type="button" className="quiet" onClick={() => setConfirming(null)}>Keep</button>
                    </span>
                  ) : (
                    <button type="button" className="quiet" onClick={() => setConfirming(p.id)}
                      aria-label={`Delete ${p.title}`}>Delete</button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {error && <p className="error-text" role="alert">{error}</p>}
          <div className="dialog-actions">
            <button type="button" className="quiet" onClick={() => onMode('save')}>
              Save the program in the editor as a new one
            </button>
          </div>
        </div>
      )}
    </dialog>
  )
}
