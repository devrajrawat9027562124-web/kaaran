import { useId, useState, type FormEvent } from 'react'
import { login, signup, type Session } from '../account'
import { BackendError } from '../backend'
import { linkTo } from '../router'
import { SiteNav } from './Home'

type Field = 'name' | 'email' | 'password'

interface Problem {
  field: Field | null  // null: about the whole form (the backend is down, too many tries)
  message: string
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function prefersLessMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/** Which field a message from the backend is about, so it's shown next to it. */
function fieldFor(error: unknown): Field | null {
  if (!(error instanceof BackendError) || error.status === 0 || error.status === 429) return null
  if (error.status === 409 || /email/i.test(error.message)) return 'email'
  if (/password/i.test(error.message)) return 'password'
  if (/name/i.test(error.message)) return 'name'
  return null
}

interface Props {
  mode: 'login' | 'signup'
  onSignedIn: (session: Session) => void
}

/** Log in and sign up: an answer sheet to fill in. */
export function AuthPage({ mode, onSignedIn }: Props) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState(false)
  const [welcome, setWelcome] = useState<string | null>(null)
  const [shownMode, setShownMode] = useState(mode)
  const formId = useId()
  const signingUp = mode === 'signup'

  // A message about the other form doesn't belong on this one
  if (shownMode !== mode) {
    setShownMode(mode)
    setProblem(null)
  }

  const check = (): Problem | null => {
    if (signingUp && !name.trim()) return { field: 'name', message: 'Enter your name.' }
    if (!EMAIL.test(email.trim())) return { field: 'email', message: 'Enter an email address like name@example.com.' }
    if (signingUp && password.length < 8) return { field: 'password', message: 'Use a password of at least 8 characters.' }
    if (!password) return { field: 'password', message: 'Enter your password.' }
    return null
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const found = check()
    setProblem(found)
    if (found) {
      document.getElementById(`${formId}-${found.field}`)?.focus()
      return
    }
    setBusy(true)
    try {
      const session = signingUp ? await signup(name, email, password) : await login(email, password)
      setWelcome(session.user.name.split(' ')[0])
      // Let the tick be drawn, then open the tool
      window.setTimeout(() => onSignedIn(session), prefersLessMotion() ? 0 : 1100)
    } catch (error) {
      setProblem({ field: fieldFor(error), message: error instanceof Error ? error.message : String(error) })
      setBusy(false)
    }
  }

  // Editing a field clears the correction written next to it
  const edit = (field: Field, set: (value: string) => void) => (e: { target: { value: string } }) => {
    set(e.target.value)
    if (problem?.field === field) setProblem(null)
  }

  const fieldProps = (field: Field) => {
    const wrong = problem?.field === field
    return {
      id: `${formId}-${field}`,
      'aria-invalid': wrong || undefined,
      'aria-describedby': wrong ? `${formId}-${field}-problem` : undefined,
      disabled: busy,
    }
  }
  const note = (field: Field) => problem?.field === field && (
    <p className="margin-note" id={`${formId}-${field}-problem`} role="alert">{problem.message}</p>
  )

  return (
    <div className="site auth">
      <SiteNav user={null} accountLinks={false}>
        <a className="nav-link" href={linkTo('app')}>Continue as guest</a>
      </SiteNav>

      <main className="auth-main">
        <div className="sheet-stack">
          {/* Keyed by mode: switching between log in and sign up slides in a fresh sheet */}
          <form key={mode} className="sheet" onSubmit={submit} noValidate aria-labelledby={`${formId}-heading`}>
            <h1 id={`${formId}-heading`}>
              <span className="marked">{signingUp ? 'Create your account' : 'Welcome back'}</span>
            </h1>
            <p className="sheet-lead">
              {signingUp
                ? 'An account keeps your programs, so you can open them again later on any computer.'
                : 'Log in to open your saved programs.'}
            </p>

            {signingUp && (
              <div className="blank">
                <label htmlFor={`${formId}-name`}>Name</label>
                <input {...fieldProps('name')} value={name} onChange={edit('name', setName)}
                  autoComplete="name" maxLength={60} />
                {note('name')}
              </div>
            )}

            <div className="blank">
              <label htmlFor={`${formId}-email`}>Email</label>
              <input {...fieldProps('email')} type="email" inputMode="email" value={email}
                onChange={edit('email', setEmail)} autoComplete="email" maxLength={254} />
              {note('email')}
            </div>

            <div className="blank">
              <label htmlFor={`${formId}-password`}>Password</label>
              <div className="blank-row">
                <input {...fieldProps('password')} type={showPassword ? 'text' : 'password'} value={password}
                  onChange={edit('password', setPassword)}
                  autoComplete={signingUp ? 'new-password' : 'current-password'} maxLength={128} />
                <button type="button" className="quiet reveal" onClick={() => setShowPassword((s) => !s)}
                  aria-pressed={showPassword} aria-controls={`${formId}-password`}>
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              </div>
              {signingUp && problem?.field !== 'password' && <p className="blank-hint">At least 8 characters.</p>}
              {note('password')}
            </div>

            {problem && !problem.field && <p className="margin-note general" role="alert">{problem.message}</p>}

            <button type="submit" className="run sheet-submit" disabled={busy}>
              {busy ? (signingUp ? 'Creating your account…' : 'Logging in…') : signingUp ? 'Create account' : 'Log in'}
            </button>

            <p className="sheet-switch">
              {signingUp
                ? <>Already have an account? <a href={linkTo('login')}>Log in</a></>
                : <>New to Kaaran? <a href={linkTo('signup')}>Create an account</a></>}
            </p>

            {welcome !== null && (
              <div className="sheet-done" role="status">
                <svg viewBox="0 0 64 64" width="72" height="72" aria-hidden="true">
                  <circle className="done-ring" cx="32" cy="32" r="28" pathLength={1} />
                  <path className="done-tick" d="M19 33 L28 42 L46 23" pathLength={1} />
                </svg>
                <p>Welcome{welcome ? `, ${welcome}` : ''}. Opening Kaaran…</p>
              </div>
            )}
          </form>
        </div>
        <p className="auth-guest">
          Just trying it out? <a href={linkTo('app')}>Use Kaaran without an account</a>.
        </p>
      </main>
    </div>
  )
}
