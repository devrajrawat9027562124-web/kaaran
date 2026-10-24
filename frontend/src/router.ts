// The site's pages live after the # (#/login), because GitHub Pages serves
// files only: a path like /login would be a 404 there.
import { useSyncExternalStore } from 'react'

export type Route = 'home' | 'login' | 'signup' | 'app'

const ROUTES: Route[] = ['login', 'signup', 'app']

function current(): Route {
  const name = window.location.hash.replace(/^#\/?/, '')
  return (ROUTES as string[]).includes(name) ? (name as Route) : 'home'
}

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, current)
}

/** The link for a page: href={linkTo('login')}. */
export function linkTo(route: Route): string {
  return route === 'home' ? '#/' : `#/${route}`
}

export function navigate(route: Route) {
  window.location.hash = linkTo(route)
}
