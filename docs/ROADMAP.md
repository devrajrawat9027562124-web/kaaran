# Kaaran: Roadmap and Task List (solo developer)

**Assumption:** about 16 weeks, one developer, ~12–15 hours/week. Change the weeks to fit your real deadline.
Tick `[x]` as you finish tasks. A phase is done only when its **Done when** check passes.

**Solo scope:** Core = Phases 1, 2, 3, 5 (simple), 8. The quiz, algorithm visuals and anything else are stretch goals.

---

## Workflow (solo)

```
Plan (Mon) ──► Build one small task ──► Test (pytest + tests/programs) ──► Commit ──► Demo to yourself / mentor (Fri)
     ▲                                                                                            │
     └──────────────────────────── docs/log.md: done / blocked / next ◄──────────────────────────┘
```

- **Monday (10 min):** pick 3–5 tasks from this file for the week. Not more.
- **Small commits:** commit every working step (`git commit -m "tracer: record call stack"`). Push daily, since GitHub is your backup.
- **Branches are optional** when working solo. Use one only for risky experiments.
- **Self-review:** before committing, run all tests and reread your diff.
- **Replace the team with feedback:** show your project guide every 2–3 weeks, and show 2–3 juniors at the Phase 1 and Phase 2 checkpoints. Without a team, these are the only people who'll catch your blind spots.
- **Friday:** write 3 lines in `docs/log.md`. This also becomes material for your report.
- **Stuck more than 2 hours?** Write down the exact problem, simplify it, or ask for help. Don't lose a week.

### Solo shortcuts (to save time)
- **No backend until Phase 5.** Everything runs in the browser with Pyodide.
- **Use a UI component library** (e.g. Tailwind + a ready component set) instead of designing your own.
- **Simple animations first** (CSS transitions). Only use D3 if you need it.
- **Deploy early** (GitHub Pages / Vercel in Week 5) so you always have a working demo link.

---

## Phase 0: Setup and problem validation (Week 1)

- [ ] Install Git, Node.js (LTS), VS Code (Python already installed)
- [ ] Create GitHub repo, push this folder
- [ ] Interview 5 juniors and 1 lab instructor (how do they debug? what confuses them?)
- [ ] Try Python Tutor on our test programs and note what it can't do
- [ ] Write `docs/problem.md`: target user, problem, existing tools, how Kaaran is different
- [ ] Show `problem.md` to your project guide

**Done when:** repo is on GitHub, interview notes are written, guide has seen the problem statement.

---

## Phase 1: Tracer + step-through UI (Week 2–5) [MVP]

### Tracer (Week 2–3)
- [ ] TODO 1: record steps (line, event, stack, locals, stdout)
- [ ] Copy values safely (`repr` or deep copy) so later changes don't overwrite earlier steps
- [ ] Build the call stack using `frame.f_back`
- [ ] Handle `call` / `return` events (save return values)
- [ ] Handle errors: show the error and its line
- [ ] Support `input()`: take all input before the run
- [ ] TODO 2: `analyze_reads_writes()` with `ast`
- [ ] Heap: track lists/dicts by `id()` (for aliasing)
- [ ] `tests/test_tracer.py` with pytest, covering all test programs
- [ ] Add 6 more test programs (nested loops, while, strings, dict, class, exception)

### Frontend (Week 4–5)
- [ ] React app (Vite) + Monaco editor
- [ ] Pyodide in a **Web Worker**, running `tracer.py`
- [ ] Stop the worker on timeout (infinite loop safety)
- [ ] Step controls: Run, Next, Back, Play/Pause, step slider
- [ ] Highlight the current line
- [ ] Variable table (changed values flash), call stack panel, output and error panel
- [ ] Deploy to GitHub Pages / Vercel

**Done when:** all test programs step forward and backward in the browser, infinite loops stop cleanly, and the demo link works.

> **Checkpoint (end of Week 5):** show 2–3 juniors. Note what confuses them.

---

## Phase 2: Why Engine (Week 6–8) [MVP, main contribution]

- [ ] Add `control_parent` to each step (which `if`/`for`/`while` made this line run)
- [ ] Dependency graph: link each read to the last step that wrote it
- [ ] Backward slice: `why(variable, step)` → steps that caused the value
- [ ] Handle aliasing using heap object ids
- [ ] Unit tests for slicing
- [ ] UI: click a variable → "Why?" → highlight only the slice steps and lines
- [ ] UI: show the chain as text: "`total = 3` because line 3 added `i = 2` to `total = 1`"
- [ ] Hand-label correct slices for 20 programs; measure accuracy
- [ ] Write down known limitations (globals, attributes, library calls)

**Done when:** slice accuracy is measured on 20 programs, and the demo works on the loop and aliasing programs.

> **Checkpoint (end of Week 8):** this is a complete, defendable project. Show your guide.

---

## Phase 3: Diff Engine, simple version (Week 9–10)

- [ ] Input: student code + reference code + test input
- [ ] Run both through the tracer
- [ ] Start simple: compare output line by line and point to the first wrong line
- [ ] Then: compare values at function returns and loop iterations, in order
- [ ] Report the first difference, then run the Why Engine on that value
- [ ] UI: side-by-side view, difference highlighted
- [ ] Make 10 buggy/correct pairs (off-by-one, wrong condition, wrong initial value, etc.)

**Done when:** finds the first difference on at least 7 of 10 pairs.

---

## Phase 5: LLM Explainer, simple version (Week 11–12)

- [ ] Tiny backend (FastAPI on Render, or one serverless function) with `/explain`
- [ ] API key in `.env` only (never in frontend or Git)
- [ ] Prompt = code + trace window + slice; ask for JSON `{step, explanation, mentioned_values}`
- [ ] Validator: every mentioned value must match the trace; flag it if not
- [ ] Cache by hash of code + input; simple rate limit
- [ ] UI: explanation panel synced with the current step
- [ ] Measure: % of correct values before vs after the validator (20 programs)

**Done when:** works on all test programs and accuracy numbers are recorded.

---

## Phase 8: Evaluation (Week 13–14)

- [ ] Prepare 3 buggy programs for the study
- [ ] Recruit 10–15 juniors; two groups (Kaaran vs print debugging / Python Tutor)
- [ ] Measure: time to find the bug, success rate, short feedback form
- [ ] Collect all numbers: tracer correctness, slice accuracy, diff accuracy, explainer accuracy
- [ ] Analyse results honestly, including where Kaaran did **worse**

**Done when:** `docs/evaluation.md` has tables and charts for every metric.

---

## Phase 9: Polish, report, presentation (Week 15–16)

- [ ] Fix the top bugs found in the study
- [ ] README: screenshots, how to run, demo link
- [ ] Report: Introduction → Problem & users → Related work (cite real papers/tools) → Design → Implementation → Evaluation → Limitations → Future work
- [ ] 3-minute demo video (backup in case the live demo fails)
- [ ] Slides: problem, demo, Why Engine, results, limitations
- [ ] Practice viva answers: "How is this different from Python Tutor?", "How does slicing work?", "Why solo, and how did you validate without a team?"

---

## Stretch goals (only if ahead of schedule)

- [ ] Phase 4: Prediction quiz + 2–3 misconception rules (copy vs alias, `range()` off-by-one)
- [ ] Algorithm visuals: sorting bars, recursion tree
- [ ] Complexity profiler

## Future work (mention in the report, don't build)

- Full misconception engine, teacher dashboard, Hindi explanations
- C support (GDB/MI + Docker, pointer and memory visuals), Java support

---

## Weekly overview

| Week | Phase | Main output |
|---|---|---|
| 1 | 0 Setup + validation | Repo, interviews, problem statement |
| 2–3 | 1 Tracer | Trace JSON correct on all test programs |
| 4–5 | 1 UI | Step-through in browser, deployed; **checkpoint** |
| 6–8 | 2 Why Engine | "Why?" works, accuracy measured; **checkpoint** |
| 9–10 | 3 Diff Engine | Finds the first difference |
| 11–12 | 5 LLM explainer | Explanations checked against the trace |
| 13–14 | 8 Evaluation | User study + metrics |
| 15–16 | 9 Polish + report | Report, slides, video |

**If you fall behind:** cut Phase 5, then simplify Phase 3 to output comparison only. Never cut Phases 1, 2 or 8.
