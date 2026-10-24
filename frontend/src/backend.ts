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
