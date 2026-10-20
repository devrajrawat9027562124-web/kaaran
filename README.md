# Kaaran

> Know why your code does what it does.

Kaaran is a debugging tutor for beginner programmers. Paste your code, step through its execution with animations, and ask *why* a variable has a value: Kaaran traces it back to the lines that caused it.

## Structure

| Folder | Purpose |
|---|---|
| `tracer/` | Core engine: runs code, records a step-by-step trace (JSON) |
| `frontend/` | React + Monaco editor UI, visualizer |
| `backend/` | FastAPI: LLM explainer proxy, teacher dashboard |
| `tests/programs/` | Sample programs used to test the tracer |
| `docs/` | Design notes, trace format, evaluation plan |

## Roadmap

1. **Tracer + step-through UI** (MVP)
2. **Why Engine**: backward slicing (MVP)
3. Diff Engine: compare with a reference solution
4. Prediction quiz + misconception detection
5. LLM explainer grounded in the trace
6. Stretch: algorithm visuals, complexity profiler, teacher dashboard
7. Future: C support

## Run the tracer

```
python tracer/tracer.py tests/programs/01_loop.py
```
