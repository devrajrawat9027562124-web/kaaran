/// <reference lib="webworker" />
// Runs Python (Pyodide) in a Web Worker, so a slow or endless student program
// never freezes the page: the main thread can simply terminate this worker.
//
// The tracer and Why Engine are the same Python files the tests use
// (tracer/*.py), bundled here as text.
import type { PyodideInterface } from 'pyodide'
import analysisPy from '../../../tracer/analysis.py?raw'
import apiPy from '../../../tracer/api.py?raw'
import tracerPy from '../../../tracer/tracer.py?raw'
import whyPy from '../../../tracer/why.py?raw'

export const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/'
const HOME = '/home/pyodide/kaaran'

export interface Request {
  id: number
  method: string
  args: (string | number)[]
}

async function start(): Promise<PyodideInterface> {
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)
  const pyodide: PyodideInterface = await loadPyodide({ indexURL: PYODIDE_URL })
  pyodide.FS.mkdirTree(HOME)
  const files = { 'analysis.py': analysisPy, 'tracer.py': tracerPy, 'why.py': whyPy, 'api.py': apiPy }
  for (const [name, source] of Object.entries(files)) {
    pyodide.FS.writeFile(`${HOME}/${name}`, source, { encoding: 'utf8' })
  }
  pyodide.runPython(`import sys; sys.path.insert(0, "${HOME}"); import api`)
  return pyodide
}

const ready = start()

ready.then(
  () => postMessage({ type: 'ready' }),
  (error) => postMessage({ type: 'failed', error: String(error) }),
)

self.onmessage = async (event: MessageEvent<Request>) => {
  const { id, method, args } = event.data
  try {
    const pyodide = await ready
    const api = pyodide.pyimport('api')
    try {
      postMessage({ id, result: api[method](...args) })
    } finally {
      api.destroy()
    }
  } catch (error) {
    postMessage({ id, error: error instanceof Error ? error.message : String(error) })
  }
}
