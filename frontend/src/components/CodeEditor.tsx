import Editor from '@monaco-editor/react'
import type * as Monaco from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import { monacoReady } from '../monaco'
import type { Language } from '../types'

export interface LineMarks {
  current?: number    // about to run (highlighter yellow)
  previous?: number   // just ran
  error?: number
  slice: number[]     // lines in the Why answer (blue ink)
  origins: number[]   // the direct causes
}

interface Props {
  code: string
  language: Language
  dark: boolean
  marks: LineMarks
  onChange: (code: string) => void
}

const MONACO_LANGUAGE: Record<Language, string> = { python: 'python', c: 'c', cpp: 'cpp' }

export function CodeEditor({ code, language, dark, marks, onChange }: Props) {
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<typeof Monaco | null>(null)
  const decorations = useRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
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
    decorations.current.set(list)
    if (marks.current) editor.revealLineInCenterIfOutsideViewport(marks.current)
  }, [marks, mounted, code])

  if (!loaded) return <div className="editor-loading">Loading the editor…</div>

  return (
    <Editor
      value={code}
      language={MONACO_LANGUAGE[language]}
      theme={dark ? 'kaaran-dark' : 'kaaran-light'}
      onChange={(value) => onChange(value ?? '')}
      onMount={(editor, monaco) => {
        editorRef.current = editor
        monacoRef.current = monaco
        decorations.current = editor.createDecorationsCollection()
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
