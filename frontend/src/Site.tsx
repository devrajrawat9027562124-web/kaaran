import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { currentUser, logout, storeToken, storedToken, type Session } from './account'
import { BackendError } from './backend'
import { AuthPage } from './pages/AuthPage'
import { Home } from './pages/Home'
import { navigate, useRoute, type Route } from './router'
import './site.css'

// The tool (editor, Python, tracer) loads only when it's opened, so the home page is quick
const Workbench = lazy(() => import('./App'))

const TITLES: Record<Route, string> = {
  home: 'Kaaran: ask your program why',
  login: 'Log in to Kaaran',
  signup: 'Sign up for Kaaran',
  app: 'Kaaran',
}

export function Site() {
  const route = useRoute()
  const [session, setSession] = useState<Session | null>(null)
  // Once opened, the tool stays loaded (hidden) on the other pages, so going to
  // log in and back keeps the program, its run and Python ready
  const [toolOpened, setToolOpened] = useState(route === 'app')
  if (route === 'app' && !toolOpened) setToolOpened(true)

  // A login from an earlier visit
  useEffect(() => {
    const token = storedToken()
    if (!token) return
    currentUser(token)
      .then((user) => setSession({ token, user }))
      .catch((error: unknown) => {
        if (error instanceof BackendError && error.status === 401) storeToken(null)  // it ended: forget it
      })
  }, [])

  useEffect(() => {
    document.title = TITLES[route]
    window.scrollTo(0, 0)
  }, [route])

  // Logged in, the login and signup pages have nothing to do
  useEffect(() => {
    if (session && (route === 'login' || route === 'signup')) navigate('app')
  }, [session, route])

  const signedIn = (next: Session) => {
    storeToken(next.token)
    setSession(next)
    navigate('app')
  }

  // Kept in a ref so signOut stays the same function (dialogs depend on it)
  const sessionRef = useRef<Session | null>(null)
  useEffect(() => {
    sessionRef.current = session
  }, [session])

  const signOut = useCallback(() => {
    const token = sessionRef.current?.token
    if (token) void logout(token).catch(() => {})  // forgotten here even if the backend can't be told
    storeToken(null)
    setSession(null)
  }, [])

  // Logging out on purpose ends at the home page; a session that ended by itself
  // (signOut alone) leaves the student where they were
  const logOut = useCallback(() => {
    signOut()
    navigate('home')
  }, [signOut])

  return (
    <>
      {route === 'home' && <Home user={session?.user ?? null} />}
      {(route === 'login' || route === 'signup') && <AuthPage mode={route} onSignedIn={signedIn} />}
      {toolOpened && (
        <div hidden={route !== 'app'}>
          <Suspense fallback={<p className="page-loading">Opening Kaaran…</p>}>
            <Workbench active={route === 'app'} session={session} onSignOut={signOut} onLogOut={logOut} />
          </Suspense>
        </div>
      )}
    </>
  )
}
