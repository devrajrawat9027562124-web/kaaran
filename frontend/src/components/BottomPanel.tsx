import type { Trace } from '../types'
import { DryRunTable } from './DryRunTable'

export type Tab = 'output' | 'input' | 'table'

interface Props {
  trace: Trace | null
  index: number
  tab: Tab
  onTab: (tab: Tab) => void
  stdin: string
  sliceSteps: number[]
  onStdin: (value: string) => void
  onGo: (index: number) => void
  onWhyOutput: (line: number) => void
}

export function BottomPanel({ trace, index, tab, onTab: setTab, stdin, sliceSteps, onStdin, onGo, onWhyOutput }: Props) {
  const tabs: { id: Tab; label: string }[] = [
    { id: 'output', label: 'Output' },
    { id: 'input', label: stdin.trim() ? 'Input (given)' : 'Input' },
    { id: 'table', label: 'Dry-run table' },
  ]

  return (
    <section className="bottom">
      <div className="tabs" role="tablist" aria-label="Program output and input">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`tabpanel-${t.id}`}
            className={tab === t.id ? 'tab selected' : 'tab'}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="tab-body" role="tabpanel" id={`tabpanel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'output' && <Output trace={trace} index={index} onWhyOutput={onWhyOutput} />}
        {tab === 'input' && (
          <label className="stdin">
            <span>
              Everything your program reads with <code>input()</code> or <code>scanf</code>, one line per read.
              Press Run again after changing it.
            </span>
            <textarea value={stdin} onChange={(e) => onStdin(e.target.value)} rows={4} spellCheck={false} />
          </label>
        )}
        {tab === 'table' && (
          trace ? <DryRunTable trace={trace} index={index} sliceSteps={sliceSteps} onGo={onGo} />
            : <p className="empty">Run the program to fill in the dry-run table.</p>
        )}
      </div>
    </section>
  )
}

function Output({ trace, index, onWhyOutput }: { trace: Trace | null; index: number; onWhyOutput: (line: number) => void }) {
  if (!trace) return <p className="empty">Press Run to see what the program prints.</p>
  const step = trace.steps[index]
  const atEnd = index === trace.steps.length - 1
  const shown = step ? step.stdout : trace.stdout
  const lines = shown.split('\n')
  const complete = lines.slice(0, -1)
  const partial = lines[lines.length - 1]

  return (
    <div className="output">
      {trace.compile_output && <pre className="compile">{trace.compile_output}</pre>}
      {shown === '' && !trace.error && <p className="empty">Nothing printed yet.</p>}
      {shown !== '' && (
        <pre className="stdout">
          {complete.map((line, i) => (
            <button type="button" key={i} className="out-line" onClick={() => onWhyOutput(i)}
              title="Why was this printed?">
              {line || ' '}
            </button>
          ))}
          {partial && <span className="out-line partial">{partial}</span>}
        </pre>
      )}
      {(atEnd || trace.steps.length === 0) && trace.error && (
        <p className="error-text" role="alert">
          {trace.error_line ? `Line ${trace.error_line}: ` : ''}{trace.error}
        </p>
      )}
      {atEnd && trace.input_ran_out && !trace.error && (
        <p className="finished">
          The program asked for more input than the Input tab had (first on line {trace.input_ran_out}).
        </p>
      )}
      {atEnd && !trace.error && (
        <p className="finished">
          {trace.exit_code ? `The program finished with exit code ${trace.exit_code}.` : 'The program finished.'}
        </p>
      )}
    </div>
  )
}
