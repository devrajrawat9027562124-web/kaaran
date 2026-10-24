# Evaluation

Every number below comes from a script in `evaluation/` that was actually run, and the table says where (Windows = the developer's laptop, Linux = GitHub Actions CI, commit `9d74d84`). Nothing marked "not run" has results yet: those are for you to run.

| Metric | Result | How it was measured | Status |
|---|---|---|---|
| Automated tests | 124 passing | `python -m pytest tests` (Windows), plus 4 CI jobs on Linux | Done |
| Tracer correctness | **52/52** programs behave identically traced and untraced (Windows; 49/49 on Linux before 3 programs were added) | `evaluation/tracer_correctness.py` | Done |
| Slice accuracy | precision **0.98**, recall **1.00**, exact **19/20** (Windows and Linux) | `evaluation/slicing/score.py` | Done; labels need checking (below) |
| Sandbox safety | Writing outside `/tmp`: blocked. Network: blocked | `backend/sandbox_check.py` (Linux, Docker) | Done |
| Speed | Python: 2000 steps in 0.02 s; Why answer in 4 ms. C in Docker: 1000 steps in 1.5 s (Linux); C with GDB 7.6: ~15 steps/s (Windows) | measured ad hoc; sandbox numbers from `sandbox_check.py` | Done |
| Explainer accuracy | (not run) | `evaluation/explainer_accuracy.py --yes` (needs your API key; up to 120 paid requests) | **Not run** |
| User study | (not run) | `evaluation/study/protocol.md` | **Not run** |

## Tracer correctness

Does tracing change what a program does? Each of 54 programs (Python, C and C++ from `tests/programs` and `evaluation/slicing/programs`) runs normally and under Kaaran with the same input. Output must match exactly, and errors must be the same kind. The two endless programs are skipped, because the tracer stops them on purpose. Full table: `evaluation/tracer_correctness.md`.

Two things are deliberately made equal before comparing:
- Kaaran echoes typed input like a terminal, so the echo is removed.
- The normal C build uses Kaaran's unbuffered output. Without it, a crashing program loses its last output in a pipe's buffer.

The first version of the script reported 3 "differences" that were exactly these two effects.

## Slice accuracy

20 small programs (16 Python, 4 C), each with a question ("why does `total` have its final value?") and the expected lines, written from the program's meaning. Full table: `evaluation/slicing/results.md`.

| | Value |
|---|---|
| Mean precision (share of Kaaran's lines that are right) | 0.98 |
| Mean recall (share of the right lines Kaaran finds) | 1.00 |
| Exact matches | 19/20 |
| The miss | `s17_pointer_overwrite.c`: after `x = 1; … *p = 5;` Kaaran still lists `x = 1`, because an overwrite through a pointer doesn't "kill" the old value (see design.md, Limitations) |

**Read these numbers with caution:**
1. **The labels were drafted by the AI assistant**, not by an independent person. Before reporting them, check every label in `evaluation/slicing/cases.json` yourself, and ideally have a second person label them without seeing Kaaran's output. Then rerun `score.py`.
2. **Two bugs were found and fixed using this benchmark:** C call steps were on the wrong line, and void calls pulled in extra lines. The fixes are general, but tuning on the test set makes the numbers optimistic. A fresh set of programs, labelled by someone else, would give a fairer number.
3. The programs are small and were written to test specific features. Real student code is messier.

## Explainer accuracy (not run)

`evaluation/explainer_accuracy.py --yes` explains 3 steps in each of 20 programs. It reports how many mentioned values were not in the trace on the first answer (no validator) and after the validator's retry, plus how many explanations ended up marked as checked. It needs `ANTHROPIC_API_KEY` in `backend/.env` and costs money (up to 120 requests). Spot-check some explanations by hand too: the validator can't see values that appear only in the prose.

## User study (not run)

Everything needed is in `evaluation/study/`: protocol (consent, counterbalanced design, timing, success criteria, analysis), three new buggy programs, answer key, feedback form and an empty results sheet. Report the results here when you have them, including where Kaaran did worse or made no difference.
