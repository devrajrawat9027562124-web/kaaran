import { useEffect, useRef, useState } from 'react'

export interface LiveSession {
  status: 'starting' | 'running' | 'finished' | 'stopped' | 'failed'
  segments: { text: string; typed: boolean }[]  // what the screen shows
  inputs: string[]                              // every line the student typed
  note: string | null
}

interface Props {
  session: LiveSession
  explaining: boolean  // the run is being traced for stepping through
  onSend: (line: string) => void
  onEndInput: () => void
  onStop: () => void
  onExplain: () => void
}

const STATUS: Record<LiveSession['status'], string> = {
  starting: 'Compiling and starting your program…',
  running: 'Your program is running. Type input when it asks, then press Enter.',
  finished: 'The program finished. Press Explain this run to step through it, with your input.',
  stopped: 'Stopped.',
  failed: "The program couldn't run.",
}

/**
 * The program's console: it runs like it would in a terminal, the student
 * types its input, and afterwards Kaaran explains exactly this run.
 */
export function Terminal({ session, explaining, onSend, onEndInput, onStop, onExplain }: Props) {
  const [line, setLine] = useState('')
  const screen = useRef<HTMLPreElement | null>(null)
  const field = useRef<HTMLInputElement | null>(null)
  const running = session.status === 'running'

  useEffect(() => {
    screen.current?.scrollTo({ top: screen.current.scrollHeight })
  }, [session.segments])

  useEffect(() => {
    if (running) field.current?.focus()
  }, [running])

  const submit = () => {
    onSend(line)
    setLine('')
  }

  return (
    <div className="terminal">
      <div className="terminal-head">
        <p className={session.status === 'failed' ? 'error-text' : undefined}>{STATUS[session.status]}</p>
        {running && (
          <div className="terminal-actions">
            <button type="button" className="quiet" onClick={onEndInput}
              title="For programs that read until the input ends (like Ctrl+D)">End input</button>
            <button type="button" className="quiet" onClick={onStop}>Stop</button>
          </div>
        )}
        {/* The student decides when to move on from the run to explaining it */}
        {session.status === 'finished' && (
          <button type="button" className="run" onClick={onExplain} disabled={explaining}>
            {explaining ? 'Explaining…' : 'Explain this run'}
          </button>
        )}
        {session.status === 'stopped' && session.inputs.length > 0 && (
          <button type="button" className="quiet" onClick={onExplain} disabled={explaining}>Explain what ran</button>
        )}
      </div>
      <pre className="terminal-screen" ref={screen} aria-live="polite">
        {session.segments.map((s, i) => (
          <span key={i} className={s.typed ? 'typed' : undefined}>{s.text}</span>
        ))}
        {session.status === 'starting' && <span className="terminal-wait">…</span>}
      </pre>
      {session.note && <p className={session.status === 'failed' ? 'error-text' : 'terminal-note'}>{session.note}</p>}
      <form className="terminal-input" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <label htmlFor="terminal-line" className="sr-only">Input for the program</label>
        <span aria-hidden="true">›</span>
        <input id="terminal-line" ref={field} value={line} onChange={(e) => setLine(e.target.value)}
          disabled={!running} autoComplete="off" spellCheck={false}
          placeholder={running ? 'Type input and press Enter' : ''} />
      </form>
    </div>
  )
}
