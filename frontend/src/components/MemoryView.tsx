import type { HeapObject, Step } from '../types'
import { frameLabel, objectLabel } from '../traceUtils'

interface Props {
  step: Step
  frameIndex: number
}

interface Placed {
  id: string
  x: number
  y: number
  node: HeapObject
}

const BOX_W = 128
const BOX_H = 48
const GAP_X = 24
const GAP_Y = 46
const TOP = 40  // room for the variable names above the first row

// Arrows with these names go down a level (a tree); others go right (a list)
const DOWN = /left|right|child|kid|\[\d+\]|^l$|^r$/i

/**
 * Objects on the heap and the arrows between them, drawn like a textbook:
 * a binary tree in in-order (so a BST reads left to right in sorted order),
 * a linked list across the page.
 */
function layout(heap: Record<string, HeapObject>, roots: string[]): { placed: Placed[]; columns: number; rows: number } {
  const placed = new Map<string, Placed>()
  let column = 0
  let rows = 0
  const visit = (id: string, depth: number) => {
    if (placed.has(id) || !heap[id]) return
    placed.set(id, { id, x: -1, y: depth, node: heap[id] })  // reserve, against cycles
    rows = Math.max(rows, depth + 1)
    const edges = heap[id].edges ?? []
    const left = edges.filter((e) => /left|^l$/i.test(e.label))
    const rest = edges.filter((e) => !left.includes(e))
    for (const e of left) visit(e.to, depth + 1)
    placed.get(id)!.x = column++
    for (const e of rest) visit(e.to, DOWN.test(e.label) ? depth + 1 : depth)
  }
  for (const root of roots) visit(root, 0)
  return { placed: [...placed.values()], columns: column, rows }
}

function title(node: HeapObject): string {
  return node.type.replace(/^(struct|class|union)\s+/, '')
}

function body(node: HeapObject): string {
  if (node.freed) return 'freed'
  const fields = Object.entries(node.fields ?? {}).map(([k, v]) => `${k} = ${v}`)
  const text = fields.length > 0 ? fields.join(', ') : node.value
  return text.length > 20 ? `${text.slice(0, 19)}…` : text
}

export function MemoryView({ step, frameIndex }: Props) {
  // C: only malloc'd structs (a variable's own memory is in the variable list)
  const heap = Object.fromEntries(Object.entries(step.heap).filter(([, node]) => node.kind !== 'variable'))
  if (Object.keys(heap).length === 0) return null

  // Variables pointing into the heap: the selected frame's first, then the others
  const order = [frameIndex, ...step.stack.map((_, i) => i).filter((i) => i !== frameIndex).reverse()]
  const names = new Map<string, string[]>()
  for (const i of order) {
    const frame = step.stack[i]
    for (const [name, ref] of Object.entries(frame.refs ?? {})) {
      if (!heap[ref]) continue
      const label = i === frameIndex ? name : `${name} (${frameLabel(frame)})`
      names.set(ref, [...(names.get(ref) ?? []), label])
    }
  }
  const roots = [...names.keys(), ...Object.keys(heap)]
  const { placed, columns, rows } = layout(heap, roots)
  const where = new Map(placed.map((p) => [p.id, p]))
  const px = (p: Placed) => 8 + p.x * (BOX_W + GAP_X)
  const py = (p: Placed) => TOP + p.y * (BOX_H + GAP_Y)
  const width = 16 + columns * (BOX_W + GAP_X)
  const height = TOP + rows * (BOX_H + GAP_Y)
  const isC = step.stack.some((f) => f.types)

  return (
    <section className="panel" aria-labelledby="memory-heading">
      <h2 id="memory-heading">Memory</h2>
      <p className="memory-note">
        {isC ? 'Structs made with malloc or new, and the pointers between them.'
          : 'Objects, and the references between them.'}
      </p>
      <div className="memory-scroll">
        {/* Shrinks to fit the panel, down to about half size; wider trees scroll */}
        <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="memory"
          style={{ maxWidth: width, minWidth: Math.round(width * 0.55) }}
          role="img" aria-label={`${placed.length} objects in memory`}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
              orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="memory-arrowhead" />
            </marker>
          </defs>
          {placed.flatMap((p) => (p.node.edges ?? []).map((e) => {
            const to = where.get(e.to)
            if (!to) return null
            const down = to.y > p.y
            const x1 = px(p) + (down ? BOX_W / 2 : BOX_W)
            const y1 = py(p) + (down ? BOX_H : BOX_H / 2)
            const x2 = px(to) + (down ? BOX_W / 2 : 0)
            const y2 = py(to) + (down ? 0 : BOX_H / 2)
            return (
              <g key={`${p.id}-${e.label}`}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} className="memory-edge" markerEnd="url(#arrow)" />
                <text x={(x1 + x2) / 2 + 4} y={(y1 + y2) / 2 - 2} className="memory-edge-label">{e.label}</text>
              </g>
            )
          }))}
          {placed.map((p) => {
            const label = names.get(p.id)
            const classes = ['memory-node']
            if (p.node.freed) classes.push('freed')
            if (step.mutates.includes(p.id)) classes.push('changing')
            return (
              <g key={p.id}>
                {label && (
                  <>
                    <text x={px(p) + BOX_W / 2} y={py(p) - 22} textAnchor="middle" className="memory-var">
                      {label.slice(0, 2).join(', ')}{label.length > 2 ? ' …' : ''}
                    </text>
                    <line x1={px(p) + BOX_W / 2} y1={py(p) - 16} x2={px(p) + BOX_W / 2} y2={py(p) - 2}
                      className="memory-edge" markerEnd="url(#arrow)" />
                  </>
                )}
                <rect x={px(p)} y={py(p)} width={BOX_W} height={BOX_H} rx={6} className={classes.join(' ')} />
                <text x={px(p) + 8} y={py(p) + 18} className="memory-type">{title(p.node)}</text>
                <text x={px(p) + 8} y={py(p) + 36} className="memory-body">{body(p.node)}</text>
              </g>
            )
          })}
        </svg>
      </div>
      <details className="memory-list">
        <summary>As a list</summary>
        <ul className="objects">
          {placed.map((p) => (
            <li key={p.id} className="object">
              <span className="object-label">
                {objectLabel(p.id, title(p.node))}{names.get(p.id) ? `, used by ${names.get(p.id)!.join(', ')}` : ''}
              </span>
              <code className="value">{p.node.freed ? 'freed memory' : p.node.value}</code>
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}
