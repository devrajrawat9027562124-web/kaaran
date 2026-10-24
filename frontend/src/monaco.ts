// Monaco is large, so it loads in its own chunk after the page appears.
// It is the bundled copy (not a CDN one), with its one editor worker.
import { loader } from '@monaco-editor/react'
import type * as Monaco from 'monaco-editor'

export const monacoReady: Promise<typeof Monaco> = (async () => {
  const [monaco, { default: EditorWorker }] = await Promise.all([
    import('monaco-editor'),
    import('monaco-editor/editor/editor.worker?worker'),
  ])
  self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
  loader.config({ monaco })
  defineThemes(monaco)
  return monaco
})()

// Paper and blue ink by day; a classroom blackboard by night
function defineThemes(monaco: typeof Monaco) {
  monaco.editor.defineTheme('kaaran-light', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '2747C7', fontStyle: 'bold' },
      { token: 'comment', foreground: '7A8291', fontStyle: 'italic' },
      { token: 'string', foreground: '1F7A4D' },
      { token: 'number', foreground: '9A4A00' },
    ],
    colors: {
      'editor.background': '#FBFCFE',
      'editorLineNumber.foreground': '#9AA6BF',
      'editorLineNumber.activeForeground': '#2747C7',
      'editorGutter.background': '#FBFCFE',
      'editor.lineHighlightBackground': '#00000000',
      'editorIndentGuide.background1': '#E4E9F3',
    },
  })

  monaco.editor.defineTheme('kaaran-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '9DB8FF', fontStyle: 'bold' },
      { token: 'comment', foreground: '8FA399', fontStyle: 'italic' },
      { token: 'string', foreground: 'B9E3A8' },
      { token: 'number', foreground: 'F2C38A' },
    ],
    colors: {
      'editor.background': '#1E2B26',
      'editorLineNumber.foreground': '#6F857B',
      'editorLineNumber.activeForeground': '#E9EEE7',
      'editorGutter.background': '#1E2B26',
      'editor.lineHighlightBackground': '#00000000',
      'editorIndentGuide.background1': '#2C3C35',
    },
  })
}
