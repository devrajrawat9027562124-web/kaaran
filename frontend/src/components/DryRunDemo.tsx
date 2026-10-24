import { useEffect, useState } from 'react'

// The home page's demo: the average bug, stepped through and asked about,
// the way Kaaran does it. Every value here is what the program really does.
const CODE = [
  'marks = [80, 90, 70]',
  'total = 0',
  'for i in range(1, len(marks)):',
  '    total += marks[i]',
  'print(total / len(marks))',
]

type Column = 'marks' | 'total' | 'i' | 'out'

const RUN: { line: number; values: Partial<Record<Column, string>>; note?: string }[] = [
  { line: 1, values: { marks: '[80, 90, 70]' } },
  { line: 2, values: { total: '0' } },
  { line: 3, values: { i: '1' } },
  { line: 4, values: { total: '90' } },
  { line: 3, values: { i: '2' } },
  { line: 4, values: { total: '160' } },
  { line: 3, values: {}, note: 'loop ends' },
  { line: 5, values: { out: '53.333…' } },
]

const ASKED_ROW = 5        // total = 160
const SLICE = [1, 2, 3, 4]  // the lines that made total 160
const ORIGIN = 4
const QUESTION = RUN.length
const ANSWER = RUN.length + 1
const LAST = ANSWER
const DELAY = { step: 950, question: 1300, answer: 6500 }

function prefersLessMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/** A dry run being done by hand: the highlighter moves, the table is written, the question is answered. */
export function DryRunDemo() {
  const [still] = useState(prefersLessMotion)
  const [tick, setTick] = useState(() => (still ? LAST : 0))

  useEffect(() => {
    if (still) return
    const wait = tick < QUESTION ? DELAY.step : tick === QUESTION ? DELAY.question : DELAY.answer
    const timer = window.setTimeout(() => setTick((t) => (t >= LAST ? 0 : t + 1)), wait)
    return () => window.clearTimeout(timer)
  }, [tick, still])

  const running = tick < QUESTION
  const rows = RUN.slice(0, running ? tick + 1 : RUN.length)
  const current = running ? RUN[tick].line : null
  const answered = tick >= ANSWER

  return (
    <figure className="demo">
      <div className="demo-sheet" aria-hidden="true">
        <ol className="demo-code">
          {CODE.map((text, n) => {
            const line = n + 1
            const classes = ['demo-line']
            if (line === current) classes.push('current')
            if (answered && SLICE.includes(line)) classes.push(line === ORIGIN ? 'origin' : 'in-slice')
            return (
              <li key={line} className={classes.join(' ')}>
                <span className="demo-ln">{line}</span>
                <code>{text}</code>
              </li>
            )
          })}
        </ol>

        <table className="demo-table">
          <thead>
            <tr><th>Line</th><th>marks</th><th>total</th><th>i</th><th>Output</th></tr>
          </thead>
          <tbody>
            {rows.map((row, k) => (
              <tr key={k} className={running && k === tick ? 'writing' : undefined}>
                <td>{row.line}</td>
                <td>{row.values.marks}</td>
                <td className={!running && k === ASKED_ROW ? 'asked' : undefined}>{row.values.total}</td>
                <td>{row.values.i ?? (row.note && <span className="demo-note">{row.note}</span>)}</td>
                <td>
                  {row.values.out && <><span className="wrong">{row.values.out}</span> <span className="demo-expected">expected 80</span></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className={tick >= QUESTION ? 'demo-why shown' : 'demo-why'}>
          <p className="demo-question">Why is <code>total</code> 160?</p>
          <p className={answered ? 'demo-answer shown' : 'demo-answer'}>
            Line 4 added <code>marks[1]</code> and <code>marks[2]</code>. The loop on line 3 starts at 1,
            so <code>marks[0]</code> = 80 is never added.
          </p>
        </div>
      </div>
      <figcaption>
        The average of 80, 90 and 70 is 80, but this program prints 53.333… instead. Stepping through it and asking
        why <code>total</code> is 160 shows that the loop skips the first mark.
      </figcaption>
    </figure>
  )
}
