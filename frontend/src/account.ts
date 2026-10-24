// Student accounts and saved programs, kept by the Kaaran backend
// (backend/accounts.py). Logging in is optional: everything else works without it.
import { request } from './backend'
import type { Language } from './types'

export interface User {
  id: number
  name: string
  email: string
}

export interface Session {
  token: string
  user: User
}

export interface ProgramSummary {
  id: number
  title: string
  language: Language
  updated: number  // seconds since 1970
}

export interface Program extends ProgramSummary {
  code: string
  input: string
}

export interface ProgramFields {
  title: string
  language: Language
  code: string
  input: string
}

const TOKEN_KEY = 'kaaran.session'
const WHAT = 'Accounts are kept'

/** The session token from an earlier visit. Storage can be blocked (private windows): then it's null. */
export function storedToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function storeToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token)
    else window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    // not remembered: the student logs in again next visit
  }
}

export const signup = (name: string, email: string, password: string) =>
  request<Session>('POST', '/auth/signup', { what: WHAT, body: { name, email, password } })

export const login = (email: string, password: string) =>
  request<Session>('POST', '/auth/login', { what: WHAT, body: { email, password } })

export const logout = (token: string) => request<void>('POST', '/auth/logout', { what: WHAT, token })

export const currentUser = (token: string) => request<User>('GET', '/auth/me', { what: WHAT, token })

const SAVED = 'Saved programs are kept'

export const listPrograms = (token: string) => request<ProgramSummary[]>('GET', '/programs', { what: SAVED, token })

export const getProgram = (token: string, id: number) =>
  request<Program>('GET', `/programs/${id}`, { what: SAVED, token })

export const createProgram = (token: string, fields: ProgramFields) =>
  request<Program>('POST', '/programs', { what: SAVED, token, body: fields })

export const updateProgram = (token: string, id: number, fields: ProgramFields) =>
  request<Program>('PUT', `/programs/${id}`, { what: SAVED, token, body: fields })

export const deleteProgram = (token: string, id: number) =>
  request<void>('DELETE', `/programs/${id}`, { what: SAVED, token })
