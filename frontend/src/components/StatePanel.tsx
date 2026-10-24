import type { ReactNode } from 'react'
import type { Step } from '../types'
import { frameLabel, holdersByObject, objectLabel } from '../traceUtils'

interface Props {
  step: Step
  frameIndex: number
  previous: Record<string, string> | null
  asking: { name: string; frameIndex: number } | null
  onSelectFrame: (index: number) => void
  onWhy: (name: string, frameIndex: number) => void
  children?: ReactNode  // shown right under the variables (the Why answer)
}

export function StatePanel({ step, frameIndex, previous, asking, onSelectFrame, onWhy, children }: Props) {
  const frame = step.stack[frameIndex]
  const holders = holdersByObject(step)
  const names = Object.keys(frame.locals)
  const innermost = frameIndex === step.stack.length - 1

  let heading = `Variables in ${frameLabel(frame)}`
  if (innermost && step.event === 'line') heading += `, before line ${step.line} runs`

  return (
    <>
      <section className="panel" aria-labelledby="vars-heading">
        <h2 id="vars-heading">{heading}</h2>
        {names.length === 0 ? (
          <p className="empty">No variables yet.</p>
        ) : (
          <table className="vars">
            <tbody>
              {names.map((name) => {
                const value = frame.locals[name]
                const changed = previous !== null && previous[name] !== value
                const ref = frame.refs?.[name]
                const sharedWith = ref
                  ? (holders.get(ref) ?? []).filter((h) => h.name !== name || h.frameIndex !== frameIndex)
                  : []
                const isAsked = asking?.name === name && asking.frameIndex === frameIndex
                return (
                  <tr key={`${step.step}-${name}`} className={changed ? 'changed' : undefined}>
                    <th scope="row">{name}</th>
                    <td>
                      <code className="value">{value}</code>
                      {sharedWith.length > 0 && (
                        <span className="shared" title="Both names refer to one object: changing it through one changes it for both">
                          same {step.heap[ref!]?.type ?? 'object'} as{' '}
                          {sharedWith.map((h) => (h.frameIndex === frameIndex ? h.name : `${h.name} in ${frameLabel(step.stack[h.frameIndex])}`)).join(', ')}
                        </span>
                      )}
                    </td>
                    <td className="why-cell">
                      <button
                        type="button"
                        className={isAsked ? 'why-button asked' : 'why-button'}
                        onClick={() => onWhy(name, frameIndex)}
                        aria-label={`Why is ${name} ${value}?`}
                      >
                        Why?
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {step.event === 'return' && step.return_value !== undefined && innermost && (
          <p className="returning">{frame.func}() returns <code>{step.return_value}</code></p>
        )}
      </section>

      {children}

      {step.stack.length > 1 && (
        <section className="panel" aria-labelledby="stack-heading">
          <h2 id="stack-heading">Call stack</h2>
          <ol className="stack" reversed>
            {[...step.stack].map((f, i) => ({ f, i })).reverse().map(({ f, i }) => (
              <li key={f.frame_id}>
                <button
                  type="button"
                  className={i === frameIndex ? 'frame selected' : 'frame'}
                  onClick={() => onSelectFrame(i)}
                  aria-pressed={i === frameIndex}
                >
                  <span className={f.func === '<module>' ? undefined : 'frame-name'}>{frameLabel(f)}</span>
                  <span className="frame-line">line {f.line}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      {Object.keys(step.heap).length > 0 && (
        <section className="panel" aria-labelledby="objects-heading">
          <h2 id="objects-heading">Objects</h2>
          <ul className="objects">
            {Object.entries(step.heap).map(([id, obj]) => {
              const users = holders.get(id) ?? []
              return (
                <li key={id} className={step.mutates.includes(id) ? 'object changing' : 'object'}>
                  <span className="object-label">{objectLabel(id, obj.type)}</span>
                  <code className="value">{obj.value}</code>
                  {users.length > 0 && (
                    <span className="object-users">
                      used by {users.map((h) => h.name).join(', ')}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </>
  )
}
