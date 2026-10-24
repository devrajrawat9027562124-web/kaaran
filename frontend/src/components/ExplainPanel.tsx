import type { ExplainResult } from '../types'

export interface ExplainState {
  loading: boolean
  result: ExplainResult | null
  error: string | null
}

interface Props {
  state: ExplainState
  onExplain: () => void
}

/** "Explain this step": an LLM's words, with every value checked against the trace. */
export function ExplainPanel({ state, onExplain }: Props) {
  const { loading, result, error } = state
  return (
    <div className="explain" aria-live="polite">
      {!result && (
        <button type="button" className="explain-button" onClick={onExplain} disabled={loading}>
          {loading ? 'Writing an explanation…' : 'Explain this step'}
        </button>
      )}
      {error && <p className="error-text">{error}</p>}
      {result && (
        <div className="explain-result">
          <p>{result.explanation}</p>
          {result.verified ? (
            <p className="checked">Every value in this explanation matches the trace.</p>
          ) : (
            <p className="unchecked">
              Some values don't match the trace, so don't rely on them:{' '}
              {result.problems.map((p) => (
                <span key={`${p.name}=${p.value}`}>
                  <code>{p.name} = {p.value}</code>
                  {p.trace_has.length > 0 ? ` (the trace has ${p.trace_has.join(' or ')})` : ' (not in the trace)'}{' '}
                </span>
              ))}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
