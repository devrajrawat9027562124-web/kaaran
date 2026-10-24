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

export interface WhyAnswer {
  question: { step: number; name?: string; frame?: string; value?: string; line?: number; output?: string }
  summary: string
  origins: number[]
  slice: number[]
  lines: number[]
  chain: ChainItem[]
}
