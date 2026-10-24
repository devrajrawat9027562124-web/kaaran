import { useEffect, useMemo, useRef } from 'react'
import type { Trace } from '../types'

interface Props {
  trace: Trace
  index: number
  sliceSteps: number[]
  onGo: (index: number) => void
}

const MAX_ROWS = 600

/**
 * The trace table students draw on paper: one row per line that ran, one
 * column per variable, and a value written only when it changes.
 */
export function DryRunTable({ trace, index, sliceSteps, onGo }: Props) {
  const { columns, rows } = useMemo(() => {
    const columns: { key: string; func: string; name: string }[] = []
    const seen = new Set<string>()
    const rows: { index: number; step: number; line: number; func: string; cells: Record<string, string>; changed: Set<string> }[] = []
    const last: Record<string, string> = {}
    trace.steps.forEach((step, i) => {
      if (step.event !== 'line' && i !== trace.steps.length - 1) return
      const frame = step.stack[step.stack.length - 1]
      const func = frame.func
      const cells: Record<string, string> = {}
      const changed = new Set<string>()
      for (const [name, value] of Object.entries(frame.locals)) {
        if (/^(function|class|method|module) /.test(value)) continue
        const key = `${func}\u0000${name}`
        if (!seen.has(key)) {
          seen.add(key)
          columns.push({ key, func, name })
        }
        cells[key] = value
        if (last[key] !== value) changed.add(key)
        last[key] = value
      }
      rows.push({ index: i, step: step.step, line: step.line, func, cells, changed })
    })
    return { columns, rows: rows.slice(0, MAX_ROWS) }
  }, [trace])

  const currentRow = useRef<HTMLTableRowElement | null>(null)
  useEffect(() => {
    currentRow.current?.scrollIntoView({ block: 'nearest' })
  }, [index])

  const inSlice = new Set(sliceSteps)
  const showFunc = new Set(columns.map((c) => c.func)).size > 1
  // The row for a step shows the state before its line runs; mark the latest row at or before now
  const current = [...rows].reverse().find((r) => r.index <= index)?.index

  return (
    <div className="dryrun-wrap">
      <table className="dryrun">
        <thead>
          <tr>
            <th scope="col">Step</th>
            <th scope="col">Line</th>
            {columns.map((c) => (
              <th scope="col" key={c.key}>
                {showFunc && c.func !== '<module>' ? <span className="col-func">{c.func}: </span> : null}
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const classes = []
            if (row.index === current) classes.push('current')
            if (inSlice.has(row.step)) classes.push('in-slice')
            return (
              <tr key={row.step} className={classes.join(' ')} ref={row.index === current ? currentRow : undefined}
                onClick={() => onGo(row.index)}>
                <td>
                  <button type="button" className="row-go" onClick={() => onGo(row.index)}
                    aria-label={`Go to step ${row.step}`}>{row.step}</button>
                </td>
                <td>{row.line}</td>
                {columns.map((c) => (
                  <td key={c.key} className={row.changed.has(c.key) ? 'new-value' : 'same-value'}>
                    {row.changed.has(c.key) ? row.cells[c.key] : ''}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
      {trace.steps.length > MAX_ROWS && <p className="empty">Showing the first {MAX_ROWS} rows.</p>}
    </div>
  )
}
