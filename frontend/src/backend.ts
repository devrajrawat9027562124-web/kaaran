// C and C++ run on the Kaaran backend (compile + GDB in a sandbox);
// Python runs in the browser and never needs it.
import type { Language, Trace } from './types'

export const BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

export async function traceOnBackend(language: Language, code: string, stdin: string): Promise<Trace> {
  let response: Response
  try {
    response = await fetch(`${BACKEND_URL}/trace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language, code, input: stdin }),
    })
  } catch {
    throw new Error(
      `C and C++ run on the Kaaran backend, and it isn't reachable at ${BACKEND_URL}. ` +
        'Start it from the backend folder (see the README), then press Run again.',
    )
  }
  if (!response.ok) {
    let detail = await response.text()
    try {
      detail = JSON.parse(detail).detail ?? detail
    } catch {
      // plain text
    }
    throw new Error(`The backend couldn't trace this program: ${detail}`)
  }
  return (await response.json()) as Trace
}
