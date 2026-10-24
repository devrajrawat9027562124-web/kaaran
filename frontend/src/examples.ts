// Example programs: the same files the tests use (tests/programs).
import type { Language } from './types'

const python = import.meta.glob('../../tests/programs/*.py', { query: '?raw', import: 'default', eager: true })
const c = import.meta.glob('../../tests/programs/c/*.c', { query: '?raw', import: 'default', eager: true })
const cpp = import.meta.glob('../../tests/programs/cpp/*.cpp', { query: '?raw', import: 'default', eager: true })

export interface Example {
  name: string
  code: string
}

/** "04_recursion.py" -> "Recursion" */
function title(path: string): string {
  const file = path.split('/').pop()!.replace(/\.\w+$/, '').replace(/^\d+_/, '')
  const words = file.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function list(files: Record<string, unknown>): Example[] {
  return Object.keys(files).sort().map((path) => ({ name: title(path), code: files[path] as string }))
}

export const EXAMPLES: Record<Language, Example[]> = {
  python: list(python),
  c: list(c),
  cpp: list(cpp),
}

export function defaultProgram(language: Language): string {
  const examples = EXAMPLES[language]
  const bug = examples.find((e) => e.name.includes('bug'))
  return (bug ?? examples[0])?.code ?? ''
}
