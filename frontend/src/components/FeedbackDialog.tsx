import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  listFeedback, sendFeedback, type FeedbackCategory, type FeedbackReport, type ProgramFields, type Session,
} from '../account'
import { BackendError } from '../backend'
import type { Language } from '../types'

const CATEGORIES: { id: FeedbackCategory; label: string }[] = [
  { id: 'bug', label: "Something in Kaaran isn't working" },
  { id: 'wrong-answer', label: 'A step, Why answer or explanation looks wrong' },
  { id: 'my-program', label: 'A question or problem with my program' },
  { id: 'idea', label: 'An idea or suggestion' },
  { id: 'other', label: 'Something else' },
]
const LABEL: Record<Language, string> = { python: 'Python', c: 'C', cpp: 'C++' }
const MAX = 4000

interface Props {
  session: Session
  current: Omit<ProgramFields, 'title'>  // the program in the editor
  step: number | null                    // the step being looked at, if any
  onClose: () => void
  onSessionEnded: () => void
}

function sentOn(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** Report a problem (with Kaaran or with a program) or suggest something; earlier reports and replies below. */
export function FeedbackDialog({ session, current, step, onClose, onSessionEnded }: Props) {
  const dialog = useRef<HTMLDialogElement | null>(null)
  const [category, setCategory] = useState<FeedbackCategory>('bug')
  const [message, setMessage] = useState('')
  const [attachChoice, setAttachChoice] = useState<boolean | null>(null)  // null: decided by the category
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const [earlier, setEarlier] = useState<FeedbackReport[]>([])

  const hasProgram = current.code.trim() !== ''
  const lines = current.code.split('\n').filter((line) => line.trim()).length
  // A report about a step or a program is much easier to act on with the program
  const attach = hasProgram && (attachChoice ?? category !== 'idea')

  useEffect(() => {
    if (dialog.current && !dialog.current.open) dialog.current.showModal()
  }, [])

  useEffect(() => {
    let live = true
    listFeedback(session.token).then((list) => live && setEarlier(list)).catch(() => {
      // the form still works without the list
    })
    return () => {
      live = false
    }
  }, [session.token])

  const close = () => dialog.current?.close()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (message.trim().length < 10) {
      setError('Tell us a little more (at least 10 characters).')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const report = await sendFeedback(session.token, {
        category,
        message,
        step,
        ...(attach ? { language: current.language, code: current.code, input: current.input } : {}),
      })
      setEarlier((list) => [report, ...list])
      setSent(true)
    } catch (e) {
      if (e instanceof BackendError && e.status === 401) onSessionEnded()
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const another = () => {
    setSent(false)
    setMessage('')
    setAttachChoice(null)
  }

  return (
    <dialog ref={dialog} className="programs-dialog feedback-dialog" aria-labelledby="feedback-heading" onClose={onClose}
      onClick={(e) => { if (e.target === dialog.current) close() }}>
      <div className="dialog-body">
        <div className="dialog-head">
          <h2 id="feedback-heading">Send feedback</h2>
          <button type="button" className="quiet" onClick={close}>Close</button>
        </div>

        {sent ? (
          <div className="feedback-sent" role="status">
            <p><strong>Thanks, {session.user.name.split(' ')[0]}. Your report was sent.</strong></p>
            <p className="dialog-note">
              It's read by the person who runs Kaaran. When they reply, the answer shows below, under
              Your earlier reports.
            </p>
            <div className="dialog-actions">
              <button type="button" className="quiet" onClick={another}>Send another</button>
              <button type="button" className="run" onClick={close}>Done</button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="feedback-form">
            <fieldset className="feedback-kinds">
              <legend>What is it about?</legend>
              {CATEGORIES.map((c) => (
                <label key={c.id}>
                  <input type="radio" name="feedback-category" value={c.id} checked={category === c.id}
                    onChange={() => setCategory(c.id)} />
                  {c.label}
                </label>
              ))}
            </fieldset>

            <label className="dialog-field">
              What happened?
              <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} maxLength={MAX}
                placeholder={category === 'idea' ? 'What would make Kaaran better for you?'
                  : 'What did you do, what did you expect, and what happened instead?'} />
              <span className="dialog-note counter">{message.length} / {MAX}</span>
            </label>

            {hasProgram && (
              <label className="attach">
                <input type="checkbox" checked={attach} onChange={(e) => setAttachChoice(e.target.checked)} />
                <span>
                  Include the program in the editor ({LABEL[current.language]}, {lines} line{lines === 1 ? '' : 's'}
                  {current.input.trim() ? ', with its input' : ''}{step ? `, at step ${step}` : ''}), so the problem
                  can be seen
                </span>
              </label>
            )}

            {error && <p className="error-text" role="alert">{error}</p>}
            <div className="dialog-actions">
              <button type="button" className="quiet" onClick={close}>Cancel</button>
              <button type="submit" className="run" disabled={busy}>{busy ? 'Sending…' : 'Send'}</button>
            </div>
          </form>
        )}

        {earlier.length > 0 && (
          <details className="earlier" open={sent}>
            <summary>Your earlier reports ({earlier.length})</summary>
            <ul>
              {earlier.map((r) => (
                <li key={r.id}>
                  <p className="earlier-head">
                    <span>{sentOn(r.created)}, {CATEGORIES.find((c) => c.id === r.category)?.label ?? r.category}</span>
                    <span className={r.status === 'resolved' ? 'chip resolved' : 'chip'}>
                      {r.status === 'resolved' ? 'Resolved' : 'Open'}
                    </span>
                  </p>
                  <p className="earlier-message">{r.message}</p>
                  {r.reply && <p className="earlier-reply"><strong>Reply:</strong> {r.reply}</p>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </dialog>
  )
}
