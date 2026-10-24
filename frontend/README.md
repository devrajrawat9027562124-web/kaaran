# Kaaran frontend

React + TypeScript (Vite) app with the Monaco editor. Python runs entirely in the browser: Pyodide loads in a Web Worker and runs the same `tracer/*.py` files the tests use (imported as text, so there is one copy of the engine).

```
npm install
npm run dev        # http://localhost:5173
npm run build      # static site in dist/
```

| File | What it does |
|---|---|
| `src/python/worker.ts` | Loads Pyodide, writes `tracer/*.py` into it, answers `run` / `why` / `why_output` requests |
| `src/python/runner.ts` | Main-thread side: sends requests, stops the worker after 20 s (endless loops) and starts a fresh one |
| `src/backend.ts` | Sends C/C++ code to the backend (`VITE_BACKEND_URL`, default `http://localhost:8000`) |
| `src/App.tsx` | State: code, trace, current step, Why answer |
| `src/components/` | Editor, step controls, variables/stack/objects, Why answer, output/input/dry-run table |
| `src/traceUtils.ts` | Small helpers that read the trace (narration, what changed, shared objects) |

Pyodide is loaded from jsDelivr (`PYODIDE_URL` in `worker.ts`), so the first run needs internet.
