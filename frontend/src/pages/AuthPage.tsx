import { useEffect, useId, useState, type FormEvent } from 'react'
import { login, needsCode, resendCode, signup, verifyEmail, type Session } from '../account'
import { BackendError } from '../backend'
import { linkTo } from '../router'
import { SiteNav } from './Home'

type Field = 'name' | 'email' | 'password' | 'code'

interface Problem {
  field: Field | null  // null: about the whole form (the backend is down, too many tries)
  message: string
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function prefersLessMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/** Which field a message from the backend is about, so it's shown next to it. */
function fieldFor(error: unknown, confirming: boolean): Field | null {
  if (!(error instanceof BackendError) || error.status === 0 || error.status === 429 || error.status === 502) return null
  if (confirming) return /code/i.test(error.message) ? 'code' : null
  if (error.status === 409 || /email/i.test(error.message)) return 'email'
  if (/password/i.test(error.message)) return 'password'
  if (/name/i.test(error.message)) return 'name'
  return null
}

interface Props {
  mode: 'login' | 'signup'
  onSignedIn: (session: Session) => void
}

/**
 * Log in and sign up: an answer sheet to fill in. A new account (or one that
 * never confirmed its email) then gets a second sheet for the code that was emailed.
 */
export function AuthPage({ mode, onSignedIn }: Props) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState(false)
  const [welcome, setWelcome] = useState<string | null>(null)
  const [shownMode, setShownMode] = useState(mode)
  // Waiting for the emailed code: to which address, and seconds until another can be sent
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [wait, setWait] = useState(0)
  const [resent, setResent] = useState(false)
  const formId = useId()
  const signingUp = mode === 'signup'

  // A message about the other form doesn't belong on this one
  if (shownMode !== mode) {
    setShownMode(mode)
    setProblem(null)
    setCodeSentTo(null)
  }

  useEffect(() => {
    if (wait <= 0) return
    const timer = window.setTimeout(() => setWait((w) => w - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [wait])

  const signedIn = (session: Session) => {
    setWelcome(session.user.name.split(' ')[0])
    // Let the tick be drawn, then open the tool
    window.setTimeout(() => onSignedIn(session), prefersLessMotion() ? 0 : 1100)
  }

  const fail = (error: unknown, confirming: boolean) => {
    setProblem({ field: fieldFor(error, confirming), message: error instanceof Error ? error.message : String(error) })
    setBusy(false)
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
      const result = signingUp ? await signup(name, email, password) : await login(email, password)
      if (needsCode(result)) {
        setCodeSentTo(result.email)
        setWait(result.wait)
        setCode('')
        setResent(false)
        setBusy(false)
      } else {
        signedIn(result)
      }
    } catch (error) {
      fail(error, false)
    }
  }

  const confirm = async (event: FormEvent) => {
    event.preventDefault()
    if (!codeSentTo) return
    if (code.length !== 6) {
      setProblem({ field: 'code', message: 'The code has 6 digits.' })
      return
    }
    setBusy(true)
    setProblem(null)
    try {
      signedIn(await verifyEmail(codeSentTo, code, password))
    } catch (error) {
      fail(error, true)
    }
  }

  const sendAgain = async () => {
    if (!codeSentTo) return
    setProblem(null)
    try {
      const { wait: next } = await resendCode(codeSentTo, password)
      setWait(next)
      setCode('')
      setResent(true)
    } catch (error) {
      fail(error, true)
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
  const general = problem && !problem.field && <p className="margin-note general" role="alert">{problem.message}</p>
  const done = welcome !== null && (
    <div className="sheet-done" role="status">
      <svg viewBox="0 0 64 64" width="72" height="72" aria-hidden="true">
        <circle className="done-ring" cx="32" cy="32" r="28" pathLength={1} />
        <path className="done-tick" d="M19 33 L28 42 L46 23" pathLength={1} />
      </svg>
      <p>Welcome{welcome ? `, ${welcome}` : ''}. Opening Kaaran…</p>
    </div>
  )

  return (
    <div className="site auth">
      <SiteNav user={null} accountLinks={false}>
        <a className="nav-link" href={linkTo('app')}>Continue as guest</a>
      </SiteNav>

      <main className="auth-main">
        <div className="sheet-stack">
          {codeSentTo ? (
            // The second sheet: the code from the email
            <form key="code" className="sheet" onSubmit={confirm} noValidate aria-labelledby={`${formId}-code-heading`}>
              <h1 id={`${formId}-code-heading`}><span className="marked">Check your email</span></h1>
              <p className="sheet-lead">
                {resent ? 'A new code is on its way to ' : 'We sent a 6-digit code to '}
                <strong className="sent-to">{codeSentTo}</strong>. Type it here to confirm that this email is yours.
              </p>

              <div className="blank">
                <label htmlFor={`${formId}-code`}>Code</label>
                <input {...fieldProps('code')} className="code-input" value={code}
                  onChange={edit('code', (value) => setCode(value.replace(/\D/g, '').slice(0, 6)))}
                  inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus
                  />
                {note('code')}
                <p className="blank-hint">It works for 10 minutes.</p>
              </div>

              {general}

              <button type="submit" className="run sheet-submit" disabled={busy}>
                {busy ? 'Checking…' : 'Confirm'}
              </button>

              <p className="sheet-switch">
                No email? Look in spam, or{' '}
                {wait > 0
                  ? <span>ask for a new code in {wait} s</span>
                  : <button type="button" className="link-button" onClick={sendAgain}>send a new code</button>}.
              </p>
              <p className="sheet-switch">
                <button type="button" className="link-button" onClick={() => { setCodeSentTo(null); setProblem(null) }}>
                  Use a different email
                </button>
              </p>
              {done}
            </form>
          ) : (
            /* Keyed by mode: switching between log in and sign up slides in a fresh sheet */
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
                {signingUp && problem?.field !== 'email' && (
                  <p className="blank-hint">We'll email you a code to confirm it.</p>
                )}
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

              {general}

              <button type="submit" className="run sheet-submit" disabled={busy}>
                {busy ? (signingUp ? 'Creating your account…' : 'Logging in…') : signingUp ? 'Create account' : 'Log in'}
              </button>

              <p className="sheet-switch">
                {signingUp
                  ? <>Already have an account? <a href={linkTo('login')}>Log in</a></>
                  : <>New to Kaaran? <a href={linkTo('signup')}>Create an account</a></>}
              </p>
              {done}
            </form>
          )}
        </div>
        <p className="auth-guest">
          Just trying it out? <a href={linkTo('app')}>Use Kaaran without an account</a>.
        </p>
      </main>
    </div>
  )
}
