import { useEffect, useMemo, useRef, useState } from 'react'
import type { Trace } from '../types'
import { declaredWithoutValue, isDefinition, nextInFrame, shortNote } from '../traceUtils'

interface Props {
  trace: Trace
  narration: string[]
  index: number
  sliceSteps: number[]
  onGo: (index: number) => void
  onWhy: (step: number, name: string, frameIndex: number) => void
}

interface Column {
  key: string    // func + variable
  func: string
  name: string
}

interface Row {
  index: number
  after: number                      // the step whose state the row shows (later, if the line made a call)
  step: number
  line: number
  event: string
  depth: number
  code: string
  values: Record<string, string>     // column -> value after this row ran
  changed: Set<string>               // columns this row changed
  unset: Set<string>                 // C/C++ columns declared but not set yet: written "?"
  why: Record<string, { step: number; frameIndex: number }>  // where to ask about a value
  output: string
  note: string
  newRound: boolean                  // a loop header running again
}

const MAX_ROWS = 600

/**
 * The trace table students draw on paper: one row per line that ran, with
 * the value each variable has after it. By default it fills in as you
 * step, like doing the dry run by hand.
 */
export function DryRunTable({ trace, narration, index, sliceSteps, onGo, onWhy }: Props) {
  const [fill, setFill] = useState(true)
  const [everyValue, setEveryValue] = useState(false)
  const [copied, setCopied] = useState(false)

  const { columns, groups, rows } = useMemo(() => build(trace, narration), [trace, narration])

  const visible = (fill ? rows.filter((r) => r.index <= index) : rows).slice(0, MAX_ROWS)
  const current = [...rows].reverse().find((r) => r.index <= index)?.index
  const inSlice = new Set(sliceSteps)

  const currentRow = useRef<HTMLTableRowElement | null>(null)
  useEffect(() => {
    currentRow.current?.scrollIntoView({ block: 'nearest' })
  }, [index, fill])

  const csv = () => {
    const header = ['Step', 'Line', 'Code', ...columns.map((c) => `${c.func === '<module>' ? '' : `${c.func}: `}${c.name}`),
      'Output', 'Note']
    const lines = [header, ...rows.slice(0, MAX_ROWS).map((r) => [
      String(r.step), String(r.line), r.code,
      ...columns.map((c) => (r.unset.has(c.key) ? '?' : everyValue || r.changed.has(c.key) ? r.values[c.key] ?? '' : '')),
      r.output, r.note,
    ])]
    return lines.map((cells) => cells.map((c) => `"${c.replace(/"/g, '""')}"`).join(',')).join('\n')
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(csv())
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard blocked: the download still works
    }
  }

  const download = () => {
    const url = URL.createObjectURL(new Blob([csv()], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'dry-run.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="dryrun-wrap">
      <div className="dryrun-tools">
        <label><input type="checkbox" checked={fill} onChange={(e) => setFill(e.target.checked)} /> Fill in as I step</label>
        <label><input type="checkbox" checked={everyValue} onChange={(e) => setEveryValue(e.target.checked)} /> Show every value</label>
        <span className="dryrun-hint">Click a value to ask why it is that.</span>
        <button type="button" className="quiet" onClick={copy}>{copied ? 'Copied' : 'Copy as CSV'}</button>
        <button type="button" className="quiet" onClick={download}>Download CSV</button>
      </div>
      <div className="dryrun-scroll">
      <table className="dryrun">
        <thead>
          {groups.length > 1 && (
            <tr className="dryrun-groups">
              <th colSpan={3} />
              {groups.map((g) => <th key={g.func} colSpan={g.span} scope="colgroup">{g.label}</th>)}
              <th colSpan={2} />
            </tr>
          )}
          <tr>
            <th scope="col" className="sticky">Step</th>
            <th scope="col" className="sticky line-col">Line</th>
            <th scope="col">Code</th>
            {columns.map((c) => <th scope="col" key={c.key} className="value-col">{c.name}</th>)}
            <th scope="col">Output</th>
            <th scope="col">Note</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => {
            // Filling in, a row waits until its line has finished: "result = f(x)" only after f returns
            const pending = fill && row.after > index
            const classes = [`event-${row.event}`]
            if (row.index === current) classes.push('current')
            if (inSlice.has(row.step)) classes.push('in-slice')
            if (!fill && row.index > index) classes.push('future')
            if (row.newRound) classes.push('new-round')
            if (fill && row.index === current) classes.push('appearing')
            return (
              <tr key={row.step} className={classes.join(' ')} ref={row.index === current ? currentRow : undefined}>
                <td className="sticky">
                  <button type="button" className="row-go" onClick={() => onGo(row.index)}
                    aria-label={`Go to step ${row.step}`}>{row.step}</button>
                </td>
                <td className="sticky line-col">{row.line}</td>
                <td className="code-cell" style={{ paddingLeft: 12 + row.depth * 14 }} title={row.code}>
                  <code>{row.code}</code>
                </td>
                {columns.map((c) => {
                  if (pending) return <td key={c.key} />
                  const value = row.values[c.key]
                  const isNew = row.changed.has(c.key)
                  if (value === undefined || (!isNew && !everyValue)) return <td key={c.key} />
                  const where = row.why[c.key]
                  const unset = row.unset.has(c.key)
                  return (
                    <td key={c.key} className={unset ? 'unset-value' : isNew ? 'new-value' : 'same-value'}>
                      <button type="button" className="value-go"
                        title={unset ? `${c.name} isn't set yet: it holds whatever was left in that memory (${value})`
                          : `Why is ${c.name} ${value}?`}
                        onClick={() => where && onWhy(where.step, c.name, where.frameIndex)}>
                        {unset ? '?' : value}
                      </button>
                    </td>
                  )
                })}
                <td className="output-cell">{pending ? '' : row.output}</td>
                <td className="note-cell" title={narration[row.index]}>
                  <span>{pending ? (row.index === index ? 'runs next' : 'waiting for the call to return') : row.note}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="empty">Showing the first {MAX_ROWS} steps.</p>}
      </div>
    </div>
  )
}

function build(trace: Trace, narration: string[]) {
  const columns: Column[] = []
  const seen = new Set<string>()
  const last: Record<string, string> = {}
  const unknown = new Set<string>()  // columns holding leftover memory until something sets them
  const lastHeader = new Map<string, number>()
  const source = trace.code.split('\n')
  const rows: Row[] = []
  const globalsOffset = (s: Trace['steps'][number]) => (s.stack[0]?.func === 'globals' ? 1 : 0)

  trace.steps.forEach((step, i) => {
    const frame = step.stack[step.stack.length - 1]
    const func = frame.func
    const depth = Math.max(0, step.stack.length - 1 - globalsOffset(step))
    // A row shows the values after its line ran: that line's frame at its next step
    const next = step.event === 'line' ? nextInFrame(trace, i) : i
    const after = next >= 0 ? next : i
    const afterStep = trace.steps[after]
    const afterIndex = afterStep.stack.findIndex((f) => f.frame_id === step.frame_id)
    const afterLocals = afterIndex >= 0 ? afterStep.stack[afterIndex].locals : frame.locals

    const values: Record<string, string> = {}
    const changed = new Set<string>()
    const unset = new Set<string>()
    const why: Row['why'] = {}
    const declared = new Set(declaredWithoutValue(trace, i, afterStep))
    const add = (owner: string, locals: Record<string, string>, frameIndex: number) => {
      for (const [name, value] of Object.entries(locals)) {
        if (isDefinition(value)) continue
        const key = `${owner}\u0000${name}`
        if (!seen.has(key)) {
          seen.add(key)
          columns.push({ key, func: owner, name })
        }
        values[key] = value
        if (owner === func && declared.has(name)) unknown.add(key)
        else if (last[key] !== value) unknown.delete(key)
        if (unknown.has(key)) unset.add(key)
        if (last[key] !== value) changed.add(key)
        last[key] = value
        why[key] = { step: afterStep.step, frameIndex }
      }
    }
    if (step.event !== 'return') {
      add(func, afterLocals, afterIndex >= 0 ? afterIndex : afterStep.stack.length - 1)
      // C globals live in their own frame; a function changing them still shows here
      if (afterStep.stack[0]?.func === 'globals' && func !== 'globals') add('globals', afterStep.stack[0].locals, 0)
    }

    let code = (source[step.line - 1] ?? '').trim()
    if (step.event === 'call') {
      const args = Object.entries(frame.locals).map(([k, v]) => `${k}=${v}`).join(', ')
      code = `→ ${func}(${args})`
    } else if (step.event === 'return') {
      code = step.return_value !== undefined ? `← ${func} returns ${step.return_value}`
        : step.stack.length - globalsOffset(step) <= 1 ? '■ the program ends' : `← ${func} ends`
    } else if (step.event === 'exception') {
      code = `✖ ${step.exception ?? 'error'}`
    }

    const following = trace.steps[i + 1]
    const output = following && following.stdout.startsWith(step.stdout) ? following.stdout.slice(step.stdout.length) : ''
    const headerKey = `${step.frame_id}:${step.line}`
    const newRound = step.header === 'loop' && lastHeader.has(headerKey)
    if (step.header === 'loop') lastHeader.set(headerKey, i)

    rows.push({
      index: i, after, step: step.step, line: step.line, event: step.event, depth, code, values, changed, unset, why,
      output: output.replace(/\n$/, '').replace(/\n/g, ' ⏎ '),
      note: step.event === 'line' ? shortNote(narration[i] ?? '') : '',
      newRound,
    })
  })

  // Columns grouped by function, main program first
  const order = [...new Set(columns.map((c) => c.func))]
  columns.sort((a, b) => order.indexOf(a.func) - order.indexOf(b.func))
  const groups = order.map((func) => ({
    func,
    span: columns.filter((c) => c.func === func).length,
    label: func === '<module>' ? 'main program' : func === 'globals' ? 'globals' : `${func}()`,
  })).filter((g) => g.span > 0)
  return { columns, groups, rows }
}
