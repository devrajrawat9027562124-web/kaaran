# Trace format

The tracer outputs a JSON list of steps. Every module (visualizer, Why Engine, Diff Engine, quiz, explainer) reads this format, so change it only after agreeing as a team.

```json
{
  "step": 14,
  "line": 6,
  "event": "line",
  "stack": [{"func": "main", "locals": {"i": 3, "total": 6}}],
  "heap": {"obj_41": {"type": "list", "value": [1, 2, 3]}},
  "stdout": "1\n3\n",
  "reads": ["total", "i"],
  "writes": ["total"],
  "control_parent": 12
}
```

| Field | Meaning |
|---|---|
| `step` | Step number, starting at 1 |
| `line` | Line about to run |
| `event` | `line`, `call`, `return`, or `exception` |
| `stack` | Call frames, outermost first, with their local variables |
| `heap` | Mutable objects by id, so aliasing (`b = a`) can be shown |
| `stdout` | All output printed so far |
| `reads` / `writes` | Variables this line uses / changes (from `ast`) |
| `control_parent` | Step of the `if`/`while`/`for` that made this line run (Phase 2) |

Start with `step`, `line`, `event`, `stack`, `stdout`. Add `reads`/`writes`, then `heap` and `control_parent`.
