// The Kaaran backend: traces C and C++ (compile + GDB in a sandbox) and runs
// the LLM explainer. Python runs in the browser and never needs it.
import type { ExplainFacts, ExplainResult, Language, Trace } from './types'

// Set at build time (VITE_BACKEND_URL) for a deployed backend; `||` because CI
// passes an empty string when the repository variable isn't set
export const BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

/** A failed request. `status` is 0 when the backend couldn't be reached at all. */
export class BackendError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

interface RequestOptions {
  what: string           // for the "isn't reachable" message: "C and C++ run"
  body?: unknown
  token?: string | null  // a logged-in student's session
}

export async function request<T>(method: string, path: string, { what, body, token }: RequestOptions): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  let response: Response
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new BackendError(
      `${what} on the Kaaran backend, and it isn't reachable at ${BACKEND_URL}. ` +
        'Start it from the backend folder (see the README), then try again.',
      0,
    )
  }
  if (!response.ok) {
    let detail: unknown = await response.text()
    try {
      detail = JSON.parse(detail as string).detail ?? detail
    } catch {
      // plain text
    }
    // FastAPI's own validation errors are a list: the first message says enough
    if (Array.isArray(detail)) detail = detail[0]?.msg ?? 'The request was refused.'
    throw new BackendError(typeof detail === 'string' ? detail : JSON.stringify(detail), response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function post<T>(path: string, body: unknown, what: string): Promise<T> {
  return request<T>('POST', path, { what, body })
}

export function traceOnBackend(language: Language, code: string, stdin: string): Promise<Trace> {
  return post<Trace>('/trace', { language, code, input: stdin }, 'C and C++ run')
}

export function explainStep(facts: ExplainFacts): Promise<ExplainResult> {
  return post<ExplainResult>('/explain', facts, 'Explanations are written')
}

export interface LiveHandlers {
  onCompiled: () => void
  onOutput: (text: string) => void
  onCompileError: (message: string, line: number | null) => void
  onExit: (result: { code?: number | null; signal?: string | null; message?: string | null; stopped?: boolean }) => void
  onError: (message: string) => void
}

export interface LiveControl {
  send: (line: string) => void
  endInput: () => void
  stop: () => void
}

/** Run a C/C++ program live on the backend: its output streams in, typed lines go to it. */
export function liveRun(language: Language, code: string, handlers: LiveHandlers): LiveControl {
  const socket = new WebSocket(`${BACKEND_URL.replace(/^http/, 'ws')}/run`)
  let finished = false
  socket.onopen = () => socket.send(JSON.stringify({ type: 'start', language, code }))
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data)
    if (message.type === 'compiled') handlers.onCompiled()
    else if (message.type === 'output') handlers.onOutput(message.data)
    else if (message.type === 'compile_error') {
      finished = true
      handlers.onCompileError(message.compile_output || message.error, message.error_line ?? null)
    } else if (message.type === 'exit') {
      finished = true
      handlers.onExit(message)
    } else if (message.type === 'error') {
      finished = true
      handlers.onError(message.message)
    }
  }
  socket.onerror = () => {
    if (!finished) {
      finished = true
      handlers.onError(
        `C and C++ run on the Kaaran backend, and it isn't reachable at ${BACKEND_URL}. ` +
          'Start it from the backend folder (see the README), then try again.',
      )
    }
  }
  const sendJson = (data: object) => {
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data))
  }
  return {
    send: (line) => sendJson({ type: 'input', data: `${line}\n` }),
    endInput: () => sendJson({ type: 'eof' }),
    stop: () => sendJson({ type: 'stop' }),
  }
}
