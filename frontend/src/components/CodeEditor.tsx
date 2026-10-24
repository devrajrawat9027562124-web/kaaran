import Editor from '@monaco-editor/react'
import type * as Monaco from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import { monacoReady } from '../monaco'
import type { Theme } from '../theme'
import type { Language } from '../types'

export interface LineMarks {
  current?: number    // about to run (highlighter yellow)
  previous?: number   // just ran
  error?: number
  slice: number[]     // lines in the Why answer (blue ink)
  origins: number[]   // the direct causes
  ran?: { line: number; text: string }  // what the line that just ran did, written after it
}

interface Props {
  code: string
  language: Language
  theme: Theme
  marks: LineMarks
  onChange: (code: string) => void
}

const MONACO_LANGUAGE: Record<Language, string> = { python: 'python', c: 'c', cpp: 'cpp' }
// The editor's colours for each page theme (defined in monaco.ts)
const EDITOR_THEME: Record<Theme, string> = {
  paper: 'kaaran-light', sepia: 'kaaran-sepia', blackboard: 'kaaran-dark', night: 'kaaran-night',
  contrast: 'kaaran-contrast',
}

export function CodeEditor({ code, language, theme, marks, onChange }: Props) {
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<typeof Monaco | null>(null)
  const decorations = useRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
  const currentLine = useRef<number | undefined>(undefined)
  const [loaded, setLoaded] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    monacoReady.then(() => setLoaded(true))
  }, [])

  useEffect(() => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco || !decorations.current) return
    const lineCount = editor.getModel()?.getLineCount() ?? 0
    const list: Monaco.editor.IModelDeltaDecoration[] = []
    const mark = (line: number | undefined, className: string, glyph?: string, hover?: string) => {
      if (!line || line > lineCount) return
      list.push({
        range: new monaco.Range(line, 1, line, 1),
        options: {
          isWholeLine: true,
          className,
          glyphMarginClassName: glyph,
          glyphMarginHoverMessage: hover ? { value: hover } : undefined,
        },
      })
    }
    for (const line of marks.slice) {
      const origin = marks.origins.includes(line)
      mark(line, origin ? 'mark-origin' : 'mark-slice', origin ? 'glyph-origin' : 'glyph-slice',
        origin ? 'Direct cause' : 'Part of the cause')
    }
    if (marks.previous !== marks.current) mark(marks.previous, 'mark-previous')
    mark(marks.current, 'mark-current', 'glyph-current', 'Runs next')
    mark(marks.error, 'mark-error', 'glyph-error', 'Error here')
    if (marks.ran && marks.ran.line <= lineCount) {
      // "total: 1 → 3" at the end of the line that did it, like a note on a printout
      const end = editor.getModel()!.getLineMaxColumn(marks.ran.line)
      list.push({
        range: new monaco.Range(marks.ran.line, end, marks.ran.line, end),
        // an empty range: Monaco drops its injected text unless showIfCollapsed is set
        options: { showIfCollapsed: true, after: { content: `   ${marks.ran.text}`, inlineClassName: 'inline-change' } },
      })
    }
    decorations.current.set(list)
    currentLine.current = marks.current
    if (marks.current) editor.revealLineInCenterIfOutsideViewport(marks.current)
  }, [marks, mounted, code])

  if (!loaded) return <div className="editor-loading">Loading the editor…</div>

  return (
    <Editor
      value={code}
      language={MONACO_LANGUAGE[language]}
      theme={EDITOR_THEME[theme]}
      onChange={(value) => onChange(value ?? '')}
      onMount={(editor, monaco) => {
        editorRef.current = editor
        monacoRef.current = monaco
        decorations.current = editor.createDecorationsCollection()
        // A taller bottom panel shrinks the editor: keep the line about to run in view
        editor.onDidLayoutChange(() => {
          if (currentLine.current) editor.revealLineInCenterIfOutsideViewport(currentLine.current)
        })
        setMounted(true)
      }}
      loading={<div className="editor-loading">Loading the editor…</div>}
      options={{
        fontFamily: "'Atkinson Hyperlegible Mono', ui-monospace, Consolas, monospace",
        fontSize: 15,
        lineHeight: 24,
        glyphMargin: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        renderLineHighlight: 'none',
        tabSize: language === 'python' ? 4 : 2,
        automaticLayout: true,
        padding: { top: 12, bottom: 12 },
        overviewRulerLanes: 0,
        ariaLabel: 'Program code',
      }}
    />
  )
}
