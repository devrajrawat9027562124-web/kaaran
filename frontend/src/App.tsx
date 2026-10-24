import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { explainStep, liveRun, traceOnBackend, type LiveControl } from './backend'
import { BottomPanel, type Tab } from './components/BottomPanel'
import { CodeEditor, type LineMarks } from './components/CodeEditor'
import { ExplainPanel, type ExplainState } from './components/ExplainPanel'
import { StatePanel } from './components/StatePanel'
import { StepControls } from './components/StepControls'
import { Terminal, type LiveSession } from './components/Terminal'
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

/** A live run's random seed, so its random numbers repeat in the explanation. */
function newSeed(): number {
  return Math.floor(Math.random() * 1_000_000_000)
}

/** Typed lines as the program's input: one per line. */
const toStdin = (lines: string[]) => lines.map((line) => `${line}\n`).join('')

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
  const [languageHint, setLanguageHint] = useState<Language | null>(null)
  const explainRequest = useRef(0)  // so a late answer can't land on a different step
  const engine = useRef<PythonEngine | null>(null)
  // A live run: the program runs, the student types, then that run is explained
  const [live, setLive] = useState<LiveSession | null>(null)
  const liveControl = useRef<LiveControl | null>(null)
  const liveRunInfo = useRef({ language: 'python' as Language, code: '', inputs: [] as string[], seed: -1 })

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

  /**
   * Run the program. If it reads input and the Input tab is empty, it first
   * runs live in the Terminal: the student types its input as it asks, and
   * then exactly that run is explained. Otherwise it is traced at once.
   * `as` runs in that language without asking; `stdin` and `seed` replay a live run.
   */
  const run = async (options: { as?: Language; withoutInput?: boolean; stdin?: string; seed?: number } = {}) => {
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
    const input = options.stdin ?? stdin
    if (!options.withoutInput && !input.trim() && readsInput(code, lang)) {
      startLive(lang)
      return
    }
    setBusy(true)
    setPlaying(false)
    setRunError(null)
    clearWhy()
    try {
      let result: { trace: Trace; narration: string[] }
      if (lang === 'python') {
        result = await engine.current.run(code, input, options.seed ?? -1)
      } else {
        const fromBackend = await traceOnBackend(lang, code, input)
        result = { trace: fromBackend, narration: await engine.current.load(fromBackend) }
      }
      setTrace(result.trace)
      setNarration(result.narration)
      setIndex(0)
      setFrameChoice(null)
      setStale(false)
      return true
    } catch (error) {
      setRunError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  // ---------- Live runs ----------

  const updateLive = (change: Partial<LiveSession>) => setLive((s) => (s ? { ...s, ...change } : s))

  const startLive = (lang: Language) => {
    liveControl.current?.stop()
    liveRunInfo.current = { language: lang, code, inputs: [], seed: newSeed() }
    setRunError(null)
    setTrace(null)
    clearWhy()
    setLive({ status: 'starting', segments: [], inputs: [], note: null })
    setTab('terminal')
    if (lang === 'python') {
      void pythonTurn(false)
      return
    }
    liveControl.current = liveRun(lang, code, {
      onCompiled: () => updateLive({ status: 'running' }),
      onOutput: (text) => setLive((s) => (s ? { ...s, segments: [...s.segments, { text, typed: false }] } : s)),
      onCompileError: (message, line) => updateLive({ status: 'failed', note: `${line ? `Line ${line}: ` : ''}${message}` }),
      onExit: (result) => {
        if (result.stopped) {
          updateLive({ status: 'stopped', note: null })
          return
        }
        const note = result.signal ? `${result.message} (${result.signal})`
          : result.code ? `The program finished with exit code ${result.code}.` : null
        updateLive({ status: 'finished', note })
        explainLive()
      },
      onError: (message) => updateLive({ status: 'failed', note: message }),
    })
  }

  /** Python runs in the browser, which can't pause for typing: it runs up to
   *  the next input() it has no line for, and again from the start once typed. */
  const pythonTurn = async (endOfInput: boolean) => {
    const info = liveRunInfo.current
    if (!engine.current) return
    try {
      const result = await engine.current.runLive(info.code, toStdin(info.inputs), info.seed, endOfInput)
      const segments = [{ text: result.stdout, typed: false }]
      if (result.status === 'input') {
        updateLive({ status: 'running', segments })
      } else {
        const note = result.error ? `${result.error_line ? `Line ${result.error_line}: ` : ''}${result.error}` : null
        updateLive({ status: 'finished', segments, note })
        explainLive()
      }
    } catch (error) {
      updateLive({ status: 'failed', note: error instanceof Error ? error.message : String(error) })
    }
  }

  const sendLine = (line: string) => {
    const info = liveRunInfo.current
    info.inputs = [...info.inputs, line]
    if (info.language === 'python') {
      updateLive({ inputs: info.inputs })
      void pythonTurn(false)
    } else {
      setLive((s) => (s ? { ...s, inputs: info.inputs, segments: [...s.segments, { text: `${line}\n`, typed: true }] } : s))
      liveControl.current?.send(line)
    }
  }

  const endLiveInput = () => {
    if (liveRunInfo.current.language === 'python') void pythonTurn(true)
    else liveControl.current?.endInput()
  }

  const stopLive = () => {
    if (liveRunInfo.current.language === 'python') updateLive({ status: 'stopped' })
    else liveControl.current?.stop()
  }

  /** Trace the program with exactly what the student typed in the live run. */
  const explainLive = () => {
    const info = liveRunInfo.current
    const input = toStdin(info.inputs)
    setStdin(input)
    void run({ as: info.language, withoutInput: true, stdin: input, seed: info.seed }).then((ok) => {
      if (ok) setTab('output')
    })
  }

  const endLive = () => {
    liveControl.current?.stop()
    liveControl.current = null
    setLive(null)
    setTab((t) => (t === 'terminal' ? 'output' : t))
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
    endLive()
    setLanguageHint(null)
    setTrace(null)
    setRunError(null)
    clearWhy()
  }

  const loadExample = (name: string) => {
    const example = EXAMPLES[language].find((e) => e.name === name)
    if (!example) return
    endLive()
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
            terminal={live ? (
              <Terminal session={live} onSend={sendLine} onEndInput={endLiveInput} onStop={stopLive}
                onExplain={explainLive} />
            ) : undefined}
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
          {live && (live.status === 'starting' || live.status === 'running') && (
            <div className="panel notice">
              <p>
                Your program is running in the <strong>Terminal</strong> below. Type its input there, as you
                would in a terminal. When it finishes, Kaaran explains this run step by step, with your input.
              </p>
            </div>
          )}
          {runError && <p className="panel error-text" role="alert">{runError}</p>}
          {stale && <p className="panel notice">You changed the code. Press Run to step through the new version.</p>}
          {!trace && !runError && !live && (
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
