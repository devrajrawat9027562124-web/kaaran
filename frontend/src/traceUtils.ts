// Small helpers that read the trace for the UI.
import type { Frame, Step, Trace } from './types'

/** Index of the previous step that ran in the same function call, or -1. */
export function previousInFrame(trace: Trace, index: number): number {
  const frameId = trace.steps[index].frame_id
  for (let i = index - 1; i >= 0; i--) {
    if (trace.steps[i].frame_id === frameId) return i
  }
  return -1
}

/**
 * What just happened, in words. A "line" step shows the state before its
 * line runs, so we describe the step before it in the same call: that is
 * the change the student sees in the variables.
 */
export function narrationFor(trace: Trace, narration: string[], index: number): string {
  const step = trace.steps[index]
  if (step.event !== 'line') return capitalize(narration[index] ?? '')
  const before = previousInFrame(trace, index)
  if (before < 0) return index === 0 ? 'The program starts.' : capitalize(narration[index - 1] ?? '')
  const previous = trace.steps[before]
  const text = narration[before] ?? ''
  if (previous.event === 'call') return capitalize(text)
  return `Line ${previous.line} ran: ${text}.`
}

/** Sentence-case English ("The loop finished."), but never a name ("square(n=4) was called."). */
function capitalize(text: string): string {
  if (!text) return ''
  const sentence = /^(the|an?|error)\b/.test(text) ? text.charAt(0).toUpperCase() + text.slice(1) : text
  return sentence.endsWith('.') ? sentence : `${sentence}.`
}

/** Variables of a frame at its previous step, to spot what changed. */
export function previousLocals(trace: Trace, index: number, frameId: number): Record<string, string> | null {
  for (let i = index - 1; i >= 0; i--) {
    const frame = trace.steps[i].stack.find((f) => f.frame_id === frameId)
    if (frame) return frame.locals
  }
  return null
}

export interface Holder {
  name: string
  frameIndex: number
  func: string
}

/** For each shared object, every variable (in any frame) that refers to it. */
export function holdersByObject(step: Step): Map<string, Holder[]> {
  const holders = new Map<string, Holder[]>()
  step.stack.forEach((frame: Frame, frameIndex) => {
    for (const [name, ref] of Object.entries(frame.refs ?? {})) {
      if (!holders.has(ref)) holders.set(ref, [])
      holders.get(ref)!.push({ name, frameIndex, func: frame.func })
    }
  })
  return holders
}

/** "list #3" for "obj_3"; C addresses stay as they are. */
export function objectLabel(id: string, type: string): string {
  return id.startsWith('obj_') ? `${type} #${id.slice(4)}` : `${type} at ${id}`
}

export function frameLabel(frame: Frame): string {
  return frame.func === '<module>' ? 'main program' : frame.func === 'globals' ? 'globals' : `${frame.func}()`
}
