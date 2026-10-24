import type { Step } from '../types'

export type Speed = 'slow' | 'normal' | 'fast'

interface Props {
  index: number
  count: number
  step: Step
  playing: boolean
  speed: Speed
  onGo: (index: number) => void
  onTogglePlay: () => void
  onSpeed: (speed: Speed) => void
}

function where(step: Step, last: boolean): string {
  if (last && step.event === 'return') return 'program finished'
  if (step.event === 'call') return `entering ${step.stack[step.stack.length - 1].func}()`
  if (step.event === 'return') return `leaving ${step.stack[step.stack.length - 1].func}()`
  if (step.event === 'exception') return `error on line ${step.line}`
  return `line ${step.line} runs next`
}

export function StepControls({ index, count, step, playing, speed, onGo, onTogglePlay, onSpeed }: Props) {
  const atStart = index === 0
  const atEnd = index === count - 1
  return (
    <div className="controls" role="group" aria-label="Step through the program">
      <div className="controls-buttons">
        <button type="button" className="icon-button" onClick={() => onGo(0)} disabled={atStart}
          aria-label="First step" title="First step (Home)">⏮</button>
        <button type="button" onClick={() => onGo(index - 1)} disabled={atStart} title="Back (←)">Back</button>
        <button type="button" className="play" onClick={onTogglePlay} disabled={atEnd && !playing}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <button type="button" onClick={() => onGo(index + 1)} disabled={atEnd} title="Next (→)">Next</button>
        <button type="button" className="icon-button" onClick={() => onGo(count - 1)} disabled={atEnd}
          aria-label="Last step" title="Last step (End)">⏭</button>
      </div>
      <input
        type="range"
        className="slider"
        min={0}
        max={count - 1}
        value={index}
        onChange={(e) => onGo(Number(e.target.value))}
        aria-label="Step"
      />
      <div className="position-row">
        <p className="position">
          <strong>Step {index + 1}</strong> of {count}, {where(step, atEnd)}
        </p>
        <label className="speed">
          Play speed
          <select value={speed} onChange={(e) => onSpeed(e.target.value as Speed)}>
            <option value="slow">Slow</option>
            <option value="normal">Normal</option>
            <option value="fast">Fast</option>
          </select>
        </label>
      </div>
    </div>
  )
}
