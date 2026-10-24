import type { ReactNode } from 'react'
import type { Step } from '../types'
import { frameLabel, holdersByObject, objectLabel, type Holder } from '../traceUtils'

interface Props {
  step: Step
  frameIndex: number
  previous: Record<string, string> | null
  asking: { name: string; frameIndex: number } | null
  onSelectFrame: (index: number) => void
  onWhy: (name: string, frameIndex: number) => void
  children?: ReactNode  // shown right under the variables (the Why answer)
}

/** "*" for a C/C++ pointer type, "&" for a reference. */
function pointerKind(type?: string): '*' | '&' | null {
  const t = (type ?? '').replace(/\b(const|volatile)\b/g, '').trim()
  return t.endsWith('*') ? '*' : t.endsWith('&') ? '&' : null
}

/** std::vector<int, std::allocator<int> > -> vector<int> */
function shortType(type: string): string {
  return type.replace(/std::/g, '').replace(/,\s*allocator<[^<>]*>\s*/g, '').replace(/\s+>/g, '>')
}

/**
 * Who else uses this variable's memory: "same list as b" in Python, where
 * names share objects; "points to x" / "p points here" in C and C++.
 */
function sharingNote(step: Step, frameIndex: number, name: string, holders: Map<string, Holder[]>): string | null {
  const frame = step.stack[frameIndex]
  const ref = frame.refs?.[name]
  if (!ref) return null
  const others = (holders.get(ref) ?? []).filter((h) => h.name !== name || h.frameIndex !== frameIndex)
  if (others.length === 0) return null
  const label = (h: Holder) => (h.frameIndex === frameIndex ? h.name : `${h.name} in ${frameLabel(step.stack[h.frameIndex])}`)
  if (!frame.types) return `same ${step.heap[ref]?.type ?? 'object'} as ${others.map(label).join(', ')}`

  const kindOf = (h: Holder) => pointerKind(step.stack[h.frameIndex].types?.[h.name])
  const own = pointerKind(frame.types[name])
  if (own) {
    const targets = others.filter((h) => !kindOf(h))
    const verb = own === '&' ? 'refers to' : 'points to'
    return targets.length > 0
      ? `${verb} ${targets.map(label).join(', ')}`
      : `${verb} the same place as ${others.map(label).join(', ')}`
  }
  const pointers = others.filter((h) => kindOf(h))
  if (pointers.length === 0) return null
  return `${pointers.map(label).join(', ')} ${pointers.length > 1 ? 'point' : 'points'} here`
}

export function StatePanel({ step, frameIndex, previous, asking, onSelectFrame, onWhy, children }: Props) {
  const frame = step.stack[frameIndex]
  const holders = holdersByObject(step)
  const names = Object.keys(frame.locals)
  const innermost = frameIndex === step.stack.length - 1
  // Python's shared objects get their own panel; in C/C++ the notes on pointers say it
  const showObjects = Object.keys(step.heap).length > 0 && step.stack.every((f) => !f.types)

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
                const note = sharingNote(step, frameIndex, name, holders)
                const type = frame.types?.[name]
                const isAsked = asking?.name === name && asking.frameIndex === frameIndex
                return (
                  <tr key={`${step.step}-${name}`} className={changed ? 'changed' : undefined}>
                    <th scope="row">
                      {name}
                      {type && <span className="var-type" title={type}>{shortType(type)}</span>}
                    </th>
                    <td>
                      <code className="value">{value}</code>
                      {note && (
                        <span className="shared" title="Changing the memory through one name changes it for the other">
                          {note}
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
                  <span className={f.func === '<module>' || f.func === 'globals' ? undefined : 'frame-name'}>
                    {frameLabel(f)}
                  </span>
                  {f.line != null && <span className="frame-line">line {f.line}</span>}
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      {showObjects && (
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
