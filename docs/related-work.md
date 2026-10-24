# Related work: existing tools

Test each tool yourself and fill in what you **observe**. Don't copy claims from websites without checking.
For the report, cite the official site or paper of each tool (record the link and the date you checked).

## Python Tutor (pythontutor.com)

Run each program in `tests/programs/` and note what happens.

| Program | Shows steps correctly? | Shows aliasing clearly? | Can you ask *why* a value is what it is? | Notes |
|---|---|---|---|---|
| 01_loop.py |yes |N/A |no |Easy to step through each iteration. |
| 02_if_else.py |yes |N/A |no |Clearly shows branch taken and variable updates. |
| 03_function.py |yes|limited |no |Function stack frames are shown clearly. |
| 04_recursion.py |yes |limited |no |Recursive call stack is visible and easy to follow. |
| 05_aliasing.py |yes |yes |no |Shared references between variables/objects are visualized well. |
| 06_infinite_loop.py |partially |N/A |no |Execution stops after reaching the visualization step limit. |

**Also check:**
- Does it explain lines in plain language?No. It visualizes execution but generally does not provide natural-language explanations.
- Can it compare your code against a correct solution?No.
- Does it quiz you or ask you to predict values?No built-in quiz/prediction mode found.
- What is the step limit? What happens with `input()`?Long-running programs are truncated by an execution-step limit. Programs requiring interactive input() are not handled like a normal terminal and generally need supplied input or modification before visualization.

## Other tools (shorter notes)

| Tool | What it does well | What it lacks (vs Kaaran's goals) | Link checked |
|---|---|---|---|
| Thonny debugger |Simple stepping, variables, beginner-friendly UI |Doesn't answer "why" questions or explain causality automatically |https://thonny.org |
| VS Code debugger |Powerful debugging, breakpoints, watches, call stacks |Designed for debugging, not learning; no novice-oriented explanations |https://code.visualstudio.com/docs/editor/debugging |
| ChatGPT / LLM explanations |Can explain code in plain English and answer questions |May hallucinate, lacks exact execution trace unless supplied one |https://chatgpt.com |

## Research to read and cite (verify each source yourself)
- The **Whyline** (Ko & Myers): asking "why" questions about program output
- **Dynamic program slicing** (start with a textbook or survey on program slicing)
- **Notional machines** and novice misconceptions (e.g. Juha Sorva's work)

## Gap summary (fill in last)
Existing tools either visualize execution, debug programs, or explain code, but none integrate execution tracing, dynamic slicing, "why" questions, and novice-focused tutoring in a single system, which is Kaaran's proposed contribution.
