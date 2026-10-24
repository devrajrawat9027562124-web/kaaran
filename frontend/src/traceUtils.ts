// Small helpers that read the trace for the UI.
import type { ExplainFacts, Frame, Language, Step, Trace, WhyAnswer } from './types'

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

/** Index of the next step in the same function call, or -1. */
export function nextInFrame(trace: Trace, index: number): number {
  const frameId = trace.steps[index].frame_id
  for (let i = index + 1; i < trace.steps.length; i++) {
    if (trace.steps[i].frame_id === frameId) return i
  }
  return -1
}

/** "set total = 3 (using i = 2, total = 1)" -> "set total = 3": short enough for a table cell. */
export function shortNote(text: string): string {
  return text.replace(/\s*\(using .*\)$/, '')
}

/** Function definitions and classes aren't values a dry run tracks. */
export function isDefinition(value: string): boolean {
  return /^(function|class|method|module) /.test(value)
}

/**
 * C/C++ variables that the line at `index` declared without giving a value
 * (`int choice;`), seen at the later step `after`. Until something sets them
 * they hold whatever was in that memory, so a dry run writes "?" for them.
 * In C++ only built-in types and pointers: a class (string, vector) is set
 * by its constructor.
 */
export function declaredWithoutValue(trace: Trace, index: number, after: Step): string[] {
  const step = trace.steps[index]
  if (trace.language === 'python' || step.event !== 'line') return []
  const before = step.stack.find((f) => f.frame_id === step.frame_id)
  const now = after.stack.find((f) => f.frame_id === step.frame_id)
  if (!before || !now) return []
  const leftover = (type = '') => trace.language === 'c'
    || /\*\s*$|^(const\s+)?((un)?signed\s+)?(char|short|int|long|float|double|bool|size_t)\b/.test(type)
  return Object.keys(now.locals).filter((name) => !(name in before.locals) && !step.writes.includes(name)
    && !step.mutates.includes(name) && leftover(now.types?.[name]))
}

/**
 * What the line that just ran did, for showing next to it in the editor:
 * "total: 1 → 3", "→ False", "printed 3". Null at the start.
 */
export function justRan(trace: Trace, narration: string[], index: number): { line: number; text: string } | null {
  const now = trace.steps[index]
  const before = now.event === 'line' ? previousInFrame(trace, index) : -1
  if (before < 0 || trace.steps[before].event !== 'line') return null
  const ran = trace.steps[before]
  const old = ran.stack.find((f) => f.frame_id === ran.frame_id)?.locals ?? {}
  const current = now.stack.find((f) => f.frame_id === ran.frame_id)?.locals ?? {}
  const unset = declaredWithoutValue(trace, before, now)
  const parts: string[] = []
  for (const [name, value] of Object.entries(current)) {
    if (old[name] !== value && !isDefinition(value)) {
      parts.push(name in old ? `${name}: ${old[name]} → ${value}`
        : unset.includes(name) ? `${name}: not set yet` : `${name} = ${value}`)
    }
  }
  const note = narration[before] ?? ''
  const condition = note.match(/condition was (True|False)/)
  if (condition) parts.unshift(`→ ${condition[1]}`)
  if (/went to the case on line \d+/.test(note)) parts.unshift(`→ ${note.match(/line \d+/)![0]}`)
  const printed = now.stdout.slice(ran.stdout.length).trim()
  if (printed) parts.push(`printed ${printed.length > 24 ? `${printed.slice(0, 23)}…` : printed}`)
  if (parts.length === 0) return null
  const text = parts.join('   ')
  return { line: ran.line, text: text.length > 90 ? `${text.slice(0, 89)}…` : text }
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

/**
 * The facts the explainer gets for the current position: the step the
 * narration describes (the line that just ran), the variables before and
 * after it, and the open Why answer. The backend checks every value the
 * LLM mentions against exactly these facts.
 */
export function explainFacts(trace: Trace, narration: string[], index: number, why: WhyAnswer | null): ExplainFacts {
  const now = trace.steps[index]
  let target = index
  if (now.event === 'line') {
    const before = previousInFrame(trace, index)
    if (before >= 0) target = before
  }
  const step = trace.steps[target]
  const after = target !== index ? now.stack.find((f) => f.frame_id === step.frame_id)?.locals ?? null : null
  const q = why?.question
  return {
    language: trace.language,
    code: trace.code,
    step: step.step,
    line: step.line,
    event: step.event,
    narration: narrationFor(trace, narration, index),
    before: Object.fromEntries(step.stack.map((f) => [frameLabel(f), f.locals])),
    after,
    output: now.stdout.slice(-2000),
    why: why && q
      ? {
          question: q.name !== undefined ? `Why is ${q.name} = ${q.value}?` : `Why did line ${q.line} run?`,
          summary: why.summary,
          chain: why.chain.filter((c) => c.kind !== 'definition').slice(-30)
            .map((c) => `step ${c.step}, line ${c.line}: ${c.text}`),
        }
      : null,
  }
}

export function frameLabel(frame: Frame): string {
  return frame.func === '<module>' ? 'main program' : frame.func === 'globals' ? 'globals' : `${frame.func}()`
}

/** Does the program read input? Then an empty Input tab means it will run out. */
export function readsInput(code: string, language: Language): boolean {
  return language === 'python'
    ? /\binput\s*\(/.test(code)
    : /\b(scanf|getchar|gets|fgets|getline|fscanf|getc|fgetc)\s*\(|\bcin\s*>>/.test(code)
}

/**
 * A guess at the language of some code, from unmistakable signs only
 * (#include, int main, printf/cout; def/import/print without semicolons).
 * Null when it isn't clear.
 */
export function guessLanguage(code: string): Language | null {
  if (/#include\s*<(iostream|vector|string|map|bits\/stdc\+\+\.h)>|\bstd::|\bcout\s*<<|\bcin\s*>>|\busing\s+namespace\b/.test(code)) {
    return 'cpp'
  }
  if (/^\s*#include\s*[<"]|\bint\s+main\s*\(|\b(printf|scanf|malloc)\s*\(/m.test(code)) return 'c'
  if (/^\s*(def\s+\w+\s*\(.*\)\s*:|import\s+\w+|from\s+\w+\s+import\b|print\s*\()/m.test(code) && !/;\s*$/m.test(code)) {
    return 'python'
  }
  return null
}
