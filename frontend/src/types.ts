// The trace format, shared by every language. See docs/trace-format.md.

export type Language = 'python' | 'c' | 'cpp'

export interface Frame {
  func: string
  frame_id: number
  line: number
  locals: Record<string, string>
  refs?: Record<string, string>
  types?: Record<string, string>  // C/C++ only
}

export interface HeapObject {
  type: string
  value: string
  children?: string[]
  fields?: Record<string, string>              // plain values inside it (data = 50)
  edges?: { label: string; to: string }[]      // arrows to objects it holds (left, next, [0])
  kind?: 'heap' | 'variable'                   // C/C++: malloc'd struct, or a variable's memory
  freed?: boolean                              // C/C++: given to free()/delete
}

export interface Step {
  step: number
  line: number
  event: 'line' | 'call' | 'return' | 'exception'
  frame_id: number
  locals: Record<string, string>
  stack: Frame[]
  heap: Record<string, HeapObject>
  stdout: string
  reads: string[]
  writes: string[]
  mutates: string[]
  control_parent: number | null
  branch?: boolean
  header?: 'if' | 'loop' | 'except'
  return_value?: string
  exception?: string
  frees?: string[]  // C/C++: memory this line frees
}

export interface Trace {
  language: Language
  code: string
  steps: Step[]
  stdout: string
  error: string | null
  error_line: number | null
  truncated: boolean
  compile_output?: string
  internal_error?: string
  exit_code?: number  // C/C++ only
  input_ran_out?: number  // C/C++: line whose read found no more input
}

export interface ChainItem {
  step: number
  line: number
  code: string
  event: Step['event']
  func: string
  kind: 'data' | 'control' | 'call' | 'return' | 'error' | 'definition'
  text: string
}

/** What the LLM explainer is told about one step (backend/app.py ExplainRequest). */
export interface ExplainFacts {
  language: Language
  code: string
  step: number
  line: number
  event: Step['event']
  narration: string
  before: Record<string, Record<string, string>>
  after: Record<string, string> | null
  output: string
  why: { question: string; summary: string; chain: string[] } | null
}

export interface ExplainResult {
  explanation: string
  verified: boolean
  problems: { name: string; value: string; trace_has: string[] }[]
  retried: boolean
  cached: boolean
  model: string
}

export interface WhyAnswer {
  question: { step: number; name?: string; frame?: string; value?: string; line?: number; output?: string }
  summary: string
  origins: number[]
  slice: number[]
  lines: number[]
  chain: ChainItem[]
}
