import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { traceOnBackend } from './backend'
import { BottomPanel } from './components/BottomPanel'
import { CodeEditor, type LineMarks } from './components/CodeEditor'
import { StatePanel } from './components/StatePanel'
import { StepControls } from './components/StepControls'
import { WhyPanel } from './components/WhyPanel'
import { EXAMPLES, defaultProgram } from './examples'
import { PythonEngine, type EngineStatus } from './python/runner'
import { narrationFor, previousInFrame, previousLocals } from './traceUtils'
import type { Language, Trace, WhyAnswer } from './types'

const PLAY_DELAY_MS = 700

// What the "input" examples read, so they work on the first Run
const EXAMPLE_INPUT: Record<Language, string> = { python: 'Asha\n19\n', c: '41\n', cpp: '3 4\n' }

const LANGUAGES: { id: Language; label: string }[] = [
  { id: 'python', label: 'Python' },
  { id: 'c', label: 'C' },
  { id: 'cpp', label: 'C++' },
]

function useDarkMode(): boolean {
  const query = '(prefers-color-scheme: dark)'
  const [dark, setDark] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setDark(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return dark
}

export default function App() {
  const dark = useDarkMode()
  const [language, setLanguage] = useState<Language>('python')
  const [code, setCode] = useState(() => defaultProgram('python'))
  const [stdin, setStdin] = useState('')
  const [status, setStatus] = useState<EngineStatus>('loading')
  const [statusDetail, setStatusDetail] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const [trace, setTrace] = useState<Trace | null>(null)
  const [narration, setNarration] = useState<string[]>([])
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [frameChoice, setFrameChoice] = useState<number | null>(null)
  const [stale, setStale] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [why, setWhy] = useState<WhyAnswer | null>(null)
  const [whyLoading, setWhyLoading] = useState(false)
  const [whyError, setWhyError] = useState<string | null>(null)
  const [asking, setAsking] = useState<{ name: string; frameIndex: number } | null>(null)
  const engine = useRef<PythonEngine | null>(null)

  useEffect(() => {
    const created = new PythonEngine((s, detail) => {
      setStatus(s)
      setStatusDetail(detail)
    })
    engine.current = created
    return () => created.dispose()
  }, [])

  const count = trace?.steps.length ?? 0
  const step = trace && count > 0 ? trace.steps[Math.min(index, count - 1)] : null
  const frameIndex = step ? Math.min(frameChoice ?? step.stack.length - 1, step.stack.length - 1) : 0

  const go = useCallback((target: number) => {
    setIndex(Math.max(0, Math.min(target, count - 1)))
    setFrameChoice(null)
  }, [count])

  const clearWhy = () => {
    setWhy(null)
    setWhyError(null)
    setAsking(null)
  }

  const run = async () => {
    if (!engine.current || busy) return
    setBusy(true)
    setPlaying(false)
    setRunError(null)
    clearWhy()
    try {
      let result: { trace: Trace; narration: string[] }
      if (language === 'python') {
        result = await engine.current.run(code, stdin)
      } else {
        const fromBackend = await traceOnBackend(language, code, stdin)
        result = { trace: fromBackend, narration: await engine.current.load(fromBackend) }
      }
      setTrace(result.trace)
      setNarration(result.narration)
      setIndex(0)
      setFrameChoice(null)
      setStale(false)
    } catch (error) {
      setRunError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const askWhy = async (name: string, frame: number) => {
    if (!engine.current || !step) return
    setAsking({ name, frameIndex: frame })
    setWhyLoading(true)
    setWhyError(null)
    try {
      setWhy(await engine.current.why(step.step, name, frame))
    } catch (error) {
      setWhy(null)
      setWhyError(error instanceof Error ? error.message : String(error))
    } finally {
      setWhyLoading(false)
    }
  }

  const askWhyOutput = async (line: number) => {
    if (!engine.current) return
    setAsking(null)
    setWhyLoading(true)
    setWhyError(null)
    try {
      const answer = await engine.current.whyOutput(line)
      setWhy(answer)
      if (!answer) setWhyError("Couldn't find the line that printed this.")
    } catch (error) {
      setWhyError(error instanceof Error ? error.message : String(error))
    } finally {
      setWhyLoading(false)
    }
  }

  // Play: one step at a time until the end
  useEffect(() => {
    if (!playing) return
    const timer = window.setTimeout(() => {
      if (index + 1 >= count - 1) setPlaying(false)
      go(index + 1)
    }, PLAY_DELAY_MS)
    return () => clearTimeout(timer)
  }, [playing, index, count, go])

  // Arrow keys step through, unless typing in the editor or a text box
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (!trace || target.closest('.monaco-editor, textarea, input, select')) return
      if (e.key === 'ArrowRight') go(index + 1)
      else if (e.key === 'ArrowLeft') go(index - 1)
      else if (e.key === 'Home') go(0)
      else if (e.key === 'End') go(count - 1)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [trace, index, count, go])

  const marks: LineMarks = useMemo(() => {
    if (!trace || !step || stale) return { slice: [], origins: [] }
    const before = previousInFrame(trace, index)
    const atEnd = index === count - 1
    const origins = why ? why.origins.map((n) => trace.steps[n - 1]?.line).filter(Boolean) : []
    return {
      current: step.event === 'line' ? step.line : undefined,
      previous: before >= 0 && trace.steps[before].event === 'line' ? trace.steps[before].line : undefined,
      error: atEnd && trace.error_line ? trace.error_line : undefined,
      slice: why?.lines ?? [],
      origins,
    }
  }, [trace, step, index, count, why, stale])

  const changeLanguage = (next: Language) => {
    setLanguage(next)
    setCode(defaultProgram(next))
    setTrace(null)
    setRunError(null)
    clearWhy()
  }

  const loadExample = (name: string) => {
    const example = EXAMPLES[language].find((e) => e.name === name)
    if (!example) return
    setCode(example.code)
    setTrace(null)
    setRunError(null)
    clearWhy()
    if (name.toLowerCase().includes('input') && !stdin.trim()) setStdin(EXAMPLE_INPUT[language])
  }

  const canRun = !busy && (language !== 'python' || status === 'ready')
  const statusText = {
    loading: 'Loading Python (the first time takes a few seconds)…',
    ready: busy ? 'Running…' : language === 'python' ? 'Python is ready' : 'Runs on the Kaaran backend',
    running: 'Running…',
    failed: `Python couldn't load: ${statusDetail ?? 'unknown error'}. Check your internet connection and reload.`,
  }[status]

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">
          Kaaran <span className="brand-deva" lang="hi">कारण</span>
        </h1>
        <div className="topbar-tools">
          <label className="field">
            <span className="sr-only">Language</span>
            <select value={language} onChange={(e) => changeLanguage(e.target.value as Language)}>
              {LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="sr-only">Example program</span>
            <select value="" onChange={(e) => loadExample(e.target.value)} disabled={EXAMPLES[language].length === 0}>
              <option value="" disabled>Examples</option>
              {EXAMPLES[language].map((e) => <option key={e.name} value={e.name}>{e.name}</option>)}
            </select>
          </label>
          <button type="button" className="run" onClick={run} disabled={!canRun}>
            {busy ? 'Running…' : 'Run'}
          </button>
        </div>
        <p className={status === 'failed' ? 'status failed' : 'status'} role="status">{statusText}</p>
      </header>

      <main className="workspace">
        <div className="left">
          <div className="editor-box">
            <CodeEditor
              code={code}
              language={language}
              dark={dark}
              marks={marks}
              onChange={(value) => {
                setCode(value)
                if (trace) setStale(true)
              }}
            />
          </div>
          <BottomPanel
            trace={stale ? null : trace}
            index={index}
            stdin={stdin}
            sliceSteps={why?.slice ?? []}
            onStdin={setStdin}
            onGo={go}
            onWhyOutput={askWhyOutput}
          />
        </div>

        <aside className="right" aria-label="Program state">
          {runError && <p className="panel error-text" role="alert">{runError}</p>}
          {stale && <p className="panel notice">You changed the code. Press Run to step through the new version.</p>}
          {!trace && !runError && (
            <div className="panel intro">
              <h2>Step through your program</h2>
              <p>
                Press <strong>Run</strong>, then step through the program one line at a time. Next to any
                variable, press <strong>Why?</strong> to see which lines gave it its value.
              </p>
              <p>
                The example computes an average, but prints 53.33 instead of 80. Run it and ask why
                <code> total</code> is 160.
              </p>
            </div>
          )}
          {trace && !stale && step && (
            <>
              <StepControls index={index} count={count} step={step} playing={playing}
                onGo={go} onTogglePlay={() => setPlaying((p) => !p)} />
              <p className="narration" aria-live="polite">{narrationFor(trace, narration, index)}</p>
              <StatePanel
                step={step}
                frameIndex={frameIndex}
                previous={index > 0 ? previousLocals(trace, index, step.stack[frameIndex].frame_id) : null}
                asking={asking}
                onSelectFrame={setFrameChoice}
                onWhy={askWhy}
              >
                <WhyPanel answer={why} loading={whyLoading} error={whyError} currentStep={step.step}
                  onGo={(n) => go(n - 1)} onClear={clearWhy} />
              </StatePanel>
            </>
          )}
          {trace && !stale && !step && (
            <p className="panel error-text" role="alert">
              {trace.error_line ? `Line ${trace.error_line}: ` : ''}{trace.error ?? 'The program did not run.'}
            </p>
          )}
        </aside>
      </main>
    </div>
  )
}
