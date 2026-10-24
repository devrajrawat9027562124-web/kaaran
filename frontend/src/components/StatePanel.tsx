import type { ReactNode } from 'react'
import type { Step } from '../types'
import { frameLabel, holdersByObject, type Holder } from '../traceUtils'
import { MemoryView } from './MemoryView'

interface Props {
  step: Step
  frameIndex: number
  previous: Record<string, string> | null
  previousStep: Step | null  // to animate only what this step changed
  unset: string[]            // C/C++: declared without a value, so holding leftover memory
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

export function StatePanel({ step, frameIndex, previous, previousStep, unset, asking, onSelectFrame, onWhy, children }: Props) {
  const frame = step.stack[frameIndex]
  const oldFrames = new Set(previousStep?.stack.map((f) => f.frame_id) ?? [])
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
                const old = changed && previous && name in previous ? previous[name] : null
                const isNew = changed && previous !== null && !(name in previous)
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
                      {old !== null && old.length <= 40 && (
                        // The change itself, as a dry run on paper shows it: old value crossed out
                        <><del className="was" title="Value before this line">{old}</del><span className="becomes" aria-label="became"> → </span></>
                      )}
                      <code className="value">{value}</code>
                      {isNew && (unset.includes(name)
                        ? <span className="new-tag unset" title="Declared without a value, so it holds whatever was left in that memory">not set yet</span>
                        : <span className="new-tag">new</span>)}
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
              <li key={f.frame_id} className={previousStep && !oldFrames.has(f.frame_id) ? 'entering' : undefined}>
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

      <MemoryView step={step} frameIndex={frameIndex} previous={previousStep} />
    </>
  )
}
