import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { explainStep, traceOnBackend } from './backend'
import { BottomPanel, type Tab } from './components/BottomPanel'
import { CodeEditor, type LineMarks } from './components/CodeEditor'
import { ExplainPanel, type ExplainState } from './components/ExplainPanel'
import { StatePanel } from './components/StatePanel'
import { StepControls } from './components/StepControls'
import { WhyPanel } from './components/WhyPanel'
import { EXAMPLES, defaultProgram } from './examples'
import { PythonEngine, type EngineStatus } from './python/runner'
import { explainFacts, guessLanguage, narrationFor, previousInFrame, previousLocals, readsInput } from './traceUtils'
import type { Language, Trace, WhyAnswer } from './types'

const PLAY_DELAY_MS = 700
const NO_EXPLANATION: ExplainState = { loading: false, result: null, error: null }

// What the "input" examples read, so they work on the first Run
const EXAMPLE_INPUT: Record<Language, string> = { python: 'Asha\n19\n', c: '41\n', cpp: '3 4\n' }
// The menu example: add 5, add 7, show the total, exit
const MENU_INPUT = '1\n5\n1\n7\n2\n3\n'

const LANGUAGES: { id: Language; label: string }[] = [
  { id: 'python', label: 'Python' },
  { id: 'c', label: 'C' },
  { id: 'cpp', label: 'C++' },
]
const LABEL: Record<Language, string> = { python: 'Python', c: 'C', cpp: 'C++' }

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
  const [explanation, setExplanation] = useState<ExplainState>(NO_EXPLANATION)
  const [tab, setTab] = useState<Tab>('output')
  const [inputHint, setInputHint] = useState(false)
  const [languageHint, setLanguageHint] = useState<Language | null>(null)
  const explainRequest = useRef(0)  // so a late answer can't land on a different step
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

  const resetExplanation = useCallback(() => {
    explainRequest.current++
    setExplanation(NO_EXPLANATION)
  }, [])

  const go = useCallback((target: number) => {
    setIndex(Math.max(0, Math.min(target, count - 1)))
    setFrameChoice(null)
    resetExplanation()
  }, [count, resetExplanation])

  const clearWhy = () => {
    setWhy(null)
    setWhyError(null)
    setAsking(null)
    resetExplanation()
  }

  const explain = async () => {
    if (!trace) return
    const request = ++explainRequest.current
    setExplanation({ loading: true, result: null, error: null })
    try {
      const result = await explainStep(explainFacts(trace, narration, index, why))
      if (request === explainRequest.current) setExplanation({ loading: false, result, error: null })
    } catch (error) {
      if (request === explainRequest.current) {
        setExplanation({ loading: false, result: null, error: error instanceof Error ? error.message : String(error) })
      }
    }
  }

  /** `as` runs in that language without asking; `withoutInput` skips the input check. */
  const run = async (options: { as?: Language; withoutInput?: boolean } = {}) => {
    if (!engine.current || busy) return
    const lang = options.as ?? language
    if (!options.as) {
      // C code run as Python fails with a baffling Python error: ask first
      const guess = guessLanguage(code)
      if (guess && guess !== language) {
        setLanguageHint(guess)
        return
      }
    }
    setLanguageHint(null)
    if (!options.withoutInput && !stdin.trim() && readsInput(code, lang)) {
      // A menu program with no input just loops on "invalid choice": ask first
      setInputHint(true)
      setTab('input')
      return
    }
    setInputHint(false)
    setBusy(true)
    setPlaying(false)
    setRunError(null)
    clearWhy()
    try {
      let result: { trace: Trace; narration: string[] }
      if (lang === 'python') {
        result = await engine.current.run(code, stdin)
      } else {
        const fromBackend = await traceOnBackend(lang, code, stdin)
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
    resetExplanation()
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
    resetExplanation()
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
    // Keep the student's own code; only an untouched example is swapped for one in the new language
    const same = (a: string, b: string) => a.replace(/\r\n/g, '\n').trim() === b.replace(/\r\n/g, '\n').trim()
    const untouched = code.trim() === '' || Object.values(EXAMPLES).some((list) => list.some((e) => same(e.code, code)))
    setLanguage(next)
    if (untouched) setCode(defaultProgram(next))
    setLanguageHint(null)
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
    if (name.toLowerCase().includes('input')) setStdin(EXAMPLE_INPUT[language])
    if (name.toLowerCase().includes('menu')) setStdin(MENU_INPUT)
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
          <button type="button" className="run" onClick={() => run()} disabled={!canRun}>
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
                setLanguageHint(null)
                if (trace) setStale(true)
              }}
            />
          </div>
          <BottomPanel
            trace={stale ? null : trace}
            index={index}
            tab={tab}
            onTab={setTab}
            stdin={stdin}
            sliceSteps={why?.slice ?? []}
            onStdin={setStdin}
            onGo={go}
            onWhyOutput={askWhyOutput}
          />
        </div>

        <aside className="right" aria-label="Program state">
          {languageHint && (
            <div className="panel notice" role="alert">
              <p>
                This looks like {LABEL[languageHint]} code, but the language is set to {LABEL[language]}.
                Running it as {LABEL[language]} would only give a confusing error.
              </p>
              <div className="notice-actions">
                <button type="button" className="run" onClick={() => {
                  setLanguage(languageHint)
                  run({ as: languageHint })
                }}>
                  Switch to {LABEL[languageHint]} and run
                </button>
                <button type="button" className="quiet" onClick={() => run({ as: language })}>
                  Run as {LABEL[language]} anyway
                </button>
              </div>
            </div>
          )}
          {inputHint && (
            <div className="panel notice" role="alert">
              <p>
                This program reads input, and the Input tab is empty. Type everything it will read there,
                one value per line. For a menu, give each choice followed by the values it asks for, and end
                with the exit choice (for example: 1, 50, 1, 30, 4, 7).
              </p>
              <button type="button" className="quiet run-anyway" onClick={() => run({ as: language, withoutInput: true })}>
                Run without input
              </button>
            </div>
          )}
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
              <ExplainPanel state={explanation} onExplain={explain} />
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
