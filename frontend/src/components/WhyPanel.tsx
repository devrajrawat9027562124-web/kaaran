import type { ReactNode } from 'react'
import type { WhyAnswer } from '../types'

/** The engine writes code between backticks: `total += i` */
function withCode(text: string): ReactNode[] {
  return text.split('`').map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part))
}

interface Props {
  answer: WhyAnswer | null
  loading: boolean
  error: string | null
  currentStep: number
  onGo: (step: number) => void
  onClear: () => void
}

export function WhyPanel({ answer, loading, error, currentStep, onGo, onClear }: Props) {
  if (!answer && !loading && !error) return null
  const q = answer?.question
  let title = 'Why?'
  if (q?.name !== undefined) title = `Why is ${q.name} = ${q.value}?`
  else if (q?.output !== undefined) title = `Why was "${q.output}" printed?`
  else if (q) title = `Why did line ${q.line} run?`

  return (
    <section className="panel why" aria-labelledby="why-heading" aria-live="polite">
      <div className="why-head">
        <h2 id="why-heading">{title}</h2>
        <button type="button" className="quiet" onClick={onClear}>Close</button>
      </div>
      {loading && <p className="empty">Tracing back the causes…</p>}
      {error && <p className="error-text">{error}</p>}
      {answer && (
        <>
          <p className="why-summary">{withCode(answer.summary)}</p>
          {answer.chain.length > 0 && (
            <>
              <h3>How it got there, step by step</h3>
              <ol className="chain">
                {answer.chain.filter((item) => item.kind !== 'definition').map((item) => {
                  const origin = answer.origins.includes(item.step)
                  const classes = ['chain-item', `kind-${item.kind}`]
                  if (origin) classes.push('origin')
                  if (item.step === currentStep) classes.push('here')
                  return (
                    <li key={item.step} className={classes.join(' ')}>
                      <button type="button" onClick={() => onGo(item.step)} title={`Go to step ${item.step}`}>
                        <span className="chain-where">
                          Step {item.step}, line {item.line}
                          {origin && <span className="origin-tag">direct cause</span>}
                        </span>
                        {item.code && <code className="chain-code">{item.code}</code>}
                        <span className="chain-text">{item.text}</span>
                      </button>
                    </li>
                  )
                })}
              </ol>
            </>
          )}
        </>
      )}
    </section>
  )
}
