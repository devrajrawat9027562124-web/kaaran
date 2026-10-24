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

  // Warm paper, less blue light
  monaco.editor.defineTheme('kaaran-sepia', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: '', foreground: '3A3127' },
      { token: 'keyword', foreground: '1D5A82', fontStyle: 'bold' },
      { token: 'comment', foreground: '857561', fontStyle: 'italic' },
      { token: 'string', foreground: '4F6B1F' },
      { token: 'number', foreground: '9A4A00' },
    ],
    colors: {
      'editor.background': '#F6EFDF',
      'editor.foreground': '#3A3127',
      'editorLineNumber.foreground': '#A8977A',
      'editorLineNumber.activeForeground': '#1D5A82',
      'editorGutter.background': '#F6EFDF',
      'editor.lineHighlightBackground': '#00000000',
      'editorIndentGuide.background1': '#E6DBC2',
    },
  })

  // Dim and warm: no bright white text
  monaco.editor.defineTheme('kaaran-night', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: '', foreground: 'D9CFBF' },
      { token: 'keyword', foreground: 'A3B1DC', fontStyle: 'bold' },
      { token: 'comment', foreground: '857B70', fontStyle: 'italic' },
      { token: 'string', foreground: 'B7C48E' },
      { token: 'number', foreground: 'DDA86A' },
    ],
    colors: {
      'editor.background': '#1B1916',
      'editor.foreground': '#D9CFBF',
      'editorLineNumber.foreground': '#5E564C',
      'editorLineNumber.activeForeground': '#D9CFBF',
      'editorGutter.background': '#1B1916',
      'editor.lineHighlightBackground': '#00000000',
      'editorIndentGuide.background1': '#2A2621',
    },
  })

  // Black on white, the strongest colours
  monaco.editor.defineTheme('kaaran-contrast', {
    base: 'hc-light',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '0000B8', fontStyle: 'bold' },
      { token: 'comment', foreground: '3D3D3D', fontStyle: 'italic' },
      { token: 'string', foreground: '005A00' },
      { token: 'number', foreground: '8A2C00' },
    ],
    colors: {
      'editor.background': '#FFFFFF',
      'editorGutter.background': '#FFFFFF',
      'editor.lineHighlightBackground': '#00000000',
    },
  })
}
