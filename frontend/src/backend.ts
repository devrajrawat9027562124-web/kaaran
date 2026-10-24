// The Kaaran backend: traces C and C++ (compile + GDB in a sandbox) and runs
// the LLM explainer. Python runs in the browser and never needs it.
import type { ExplainFacts, ExplainResult, Language, Trace } from './types'

export const BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

async function post<T>(path: string, body: unknown, what: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error(
      `${what} on the Kaaran backend, and it isn't reachable at ${BACKEND_URL}. ` +
        'Start it from the backend folder (see the README), then try again.',
    )
  }
  if (!response.ok) {
    let detail = await response.text()
    try {
      detail = JSON.parse(detail).detail ?? detail
    } catch {
      // plain text
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as T
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
