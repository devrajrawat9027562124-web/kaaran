# Kaaran: design

How Kaaran works, why it is built this way, and where it falls short. Read with `docs/trace-format.md`.

## 1. Architecture

```
 Browser                                               Backend (C/C++ and explanations only)
 ┌───────────────────────────────────────────┐         ┌─────────────────────────────────────┐
 │ React UI (frontend/)                      │  C/C++  │ FastAPI (backend/app.py)            │
 │  editor · step controls · variables ·     │ ──────► │  /trace ──► sandbox.py ──► Docker   │
 │  Why answer · dry-run table · explain     │ ◄────── │             container per run:      │
 │        │                     ▲            │  trace  │             c_tracer.py + GDB       │
 │        ▼ postMessage         │            │         │  /explain ─► explainer.py ─► Claude │
 │ Web Worker: Pyodide (Python in WASM)      │         └─────────────────────────────────────┘
 │  tracer/tracer.py  (runs Python)          │
 │  tracer/why.py     (Why Engine, any trace)│
 └───────────────────────────────────────────┘
```

- **One trace format** for every language (`docs/trace-format.md`). The UI and the Why Engine only read traces, so C/C++ support needed a new tracer and nothing else.
- **Python never leaves the browser.** The same `tracer/*.py` files the tests use are bundled into a Web Worker running Pyodide. It needs no server, the demo is a static page, and an endless program only blocks the worker, which the page stops after 20 seconds and replaces.
- **The Why Engine is Python and runs in the worker** for both languages. A C/C++ trace from the backend is loaded into the worker, so slicing has exactly one implementation.

## 2. Tracers

### Python (`tracer/tracer.py`)

- `sys.settrace` calls the recorder for every `call`, `line`, `return` and `exception` event in the student's code. Python internals are skipped by filename.
- **Values are display strings taken at that moment** (`describe()`), so a later change can't rewrite history. They never call the student's own `__repr__`, and long values are cut short.
- **Shared objects:** lists, dicts, sets and instances get ids (`obj_1`). `refs` maps each variable to its object, and `heap` lists the objects with what's inside them. This is how `b = a` shows as one list with two names.
- **Static analysis** (`tracer/analysis.py`, Python `ast`) finds, for each line:
  - which names it reads and writes;
  - what it changes in place (`a.append`, `a[i] = …`, `self.x = …`), given as lvalue paths and turned into object ids while the program runs;
  - which `if`/`for`/`while` controls it, including **guard clauses** (`if n <= 1: return 1` controls the lines after it).
- **Safety:**
  - A step limit (2000) is raised as a `BaseException`, so `except Exception:` in the student's code can't swallow it.
  - `input()` reads text given up front and echoes it like a terminal.
  - A bug inside Kaaran is recorded instead of changing how the program runs.

### C/C++ (`backend/runner/c_tracer.py`)

- Compiled with `gcc/g++ -g -O0` and run under **GDB, driven through its machine interface** (`mi.py`).
- A tiny helper linked into the program redirects stdin and stdout to files and turns off buffering. Each step can then read what has been printed, and no shell is needed.
- **One `step` at a time:**
  - The tracer keeps its own copy of the call stack. Depth growing means a `call`; depth shrinking means a `return`.
  - At a function's closing brace, or after its `return` statement finishes, it uses `finish` instead. That makes GDB report the **exact return value** and skips destructor clean-up, whose values are no longer meaningful.
  - GDB stops mid-line when returning into a caller; those stops are not recorded, which matches Python's events.
- **Variables:**
  - All variables in every frame, with types.
  - Variables whose declaration hasn't been reached are hidden: their memory is garbage.
  - Pointers show `address → value`, and `std::vector` shows its elements even without GDB's pretty-printers.
- **Structs on the heap:** a pointer to a struct type (from GDB's `ptype`) leads to a node read from memory, and its pointer fields lead on (a list's `next`, a tree's `left`/`right`), up to 40 nodes. Node regions use the struct's size, so `root->left = …` is a change to the node `root` points to. `free(p)`/`delete p` mark memory as freed, so a dangling pointer shows `→ freed memory`. The UI's Memory panel draws these nodes and arrows (a binary tree in in-order, so a BST reads left to right).
- **Asking GDB less:** each question costs milliseconds (about 9 ms with GDB 7.6 on Windows), so a caller's variables are listed again only when memory they show has changed. In C a function changes its caller's variables only through pointers, and those changes are recorded. A node is read again only after a line changed it; memory a line changes counts as changing until that line finishes (`root->right = insert(…)` assigns after the call returns).
- **Input that runs out:** after every line that reads input, the tracer asks `feof(kaaran_stdin)`. If a program then loops forever, which is what a menu does on end of input, the error says the input ran out instead of "infinite loop". The UI also asks for input before running a program that reads some.
- **Memory instead of objects:** a variable's id is the address of its storage, and a pointer's id is the address of the variable it points into (so `&a[2]` belongs to `a`). Writing `x` also "changes" `&x`. That is why the **unchanged Why Engine** follows `*p = 10` to `x`, references to their targets, and `this->value` to the object.
- `c_analysis.py` uses **tree-sitter** for the same per-line facts as the Python analysis: `scanf("%d", &x)` and `cin >> x` write `x`, `v.push_back` changes `v`, and inside a method, `value` means `this->value`.

### Live runs: type first, then explain

Students expect to run a program that reads input and type into it, so a program that reads input (with nothing in the Input tab) first runs in the **Terminal**, and only then is explained. When it finishes, the output stays on screen until the student presses **Explain this run** (in a menu program, choosing Exit shouldn't whisk the screen away). The lines typed are recorded and the program is traced with exactly that input.

- **C/C++** runs for real: `backend/runner/run_program.py` compiles the program and runs it in the same sandbox as the tracer; a WebSocket (`/run`) carries its output to the browser as it prints and the typed lines to the program. Output is unbuffered (the same helper as the tracer), so prompts without a newline appear at once. Limits: 5 minutes, 64,000 characters of output.
- **Python** runs in the browser, where a program can't stop and wait for typing. `tracer.run_live` runs it (untraced) until `input()` has no line; the page asks, and runs it again from the start with the line added. A program does the same up to that point each time, and a per-session seed for `random` makes even random numbers repeat, in the live run and in the trace.
- **Limit:** the explanation is a second run. A program whose behaviour depends on time or other outside state (`srand(time(NULL))`, the clock, files) can behave differently the second time.

## 3. The Why Engine (`tracer/why.py`)

"Why does `total` have the value 160?" is answered with a **dynamic backward slice** [Korel & Laski 1988; Agrawal & Horgan 1990]: the executed steps the value depends on.

The dependency graph has one node per step. A step depends on:

| Kind | Step S depends on… | Example |
|---|---|---|
| Data | the last step whose write to a variable S reads is visible at S | `total += i` ← the last `total = …` and the last `for i …` |
| Object change | the last step that changed (mutated) any object S reads, or any object inside it | `print(b)` ← `a.append(3)` when `a` and `b` are the same list |
| Control | the `if`/`for`/`while` step that made S run (`control_parent`) | the `if` that chose this branch |
| Loop | the previous round of the same loop header | each `for` round continues the last |
| Call | for a call step: the line that made the call | `square(4)` was called from line 5 |
| Return | for that calling line: the callee's return, only if it returned a value | `a = square(4)` ← `return result` |

**Visibility rule.** A line's changes only count once its frame moves on. `x = f()` hasn't set `x` while `f` is still running. Without this rule, answers asked inside a call would quote values from the future (found by testing the UI).

**Answering.**
1. The *origins* are the visible writer of the variable in the asked frame, plus the last change to each object it can reach.
2. The slice is everything reachable from the origins, cut at the question's step.
3. The summary sentence comes from the kind of origin: "set it, using…", "changed the list that b refers to: a and b are the same list", "changed x through p: p points to x".

Each step in the chain is described from the trace alone ("loop round with i = 2", "the condition was False (using x = 7)", "square returned 16").

**Output lines.** "Why was this printed?" finds the step that printed the line (output that first appears at step N was printed by the line running just before) and slices from it.

## 4. LLM explainer (`backend/explainer.py`)

- Claude (`claude-opus-5-5`, low effort, set by `KAARAN_MODEL` and `KAARAN_EFFORT`) gets the numbered program, the step, the variables before and after, and the open Why answer.
- It must answer in a JSON schema: `{explanation, mentioned_values}`.
- **The validator** checks every mentioned `name = value` against the values Kaaran recorded for that step and its Why chain:
  - A mismatch triggers one retry, with the wrong values named.
  - If it still doesn't match, the UI says which values not to trust.
  - The trace is the authority; the LLM only phrases it.
- Other details:
  - Answers are cached by request hash.
  - There is a per-address rate limit.
  - The key lives only in `backend/.env`.
  - The server-side refusal fallback (`fallbacks: "default"`) is on.
- **Gap:** a value written in the text but left out of `mentioned_values` isn't caught.

## 5. Sandbox

See `backend/README.md`: one container per run, with no network, 256 MB, 1 CPU, 64 processes, a read-only filesystem, no capabilities and a non-root user, plus time and step limits. CI builds the image and checks that a program inside it can't write outside `/tmp` or open a network connection (`backend/sandbox_check.py`).

## 6. Accounts (`backend/accounts.py`)

Optional: a student can use everything without an account; an account adds saved programs.

- **Storage:** one SQLite file (`KAARAN_DB`, ignored by git) with three tables: `users`, `sessions`, `programs`.
- **Passwords:** never stored. Each gets a random 16-byte salt and an scrypt hash (N=2^14, r=8, p=5, one of OWASP's recommended scrypt settings); checking uses a constant-time comparison.
- **Sessions:** logging in returns a random token (`secrets.token_urlsafe(32)`). The database keeps only its SHA-256, so a stolen copy of the database can't be used to log in. Tokens expire after `KAARAN_SESSION_DAYS` (14) and logging out deletes them.
- **Token in the browser:** sent as `Authorization: Bearer`, kept in `localStorage`. A cookie would hide it from scripts, but the Pages site and a backend on `localhost` are different sites, where browsers increasingly block cookies. The trade-off: script injection on the page could read the token; the app renders no user HTML, which limits that risk.
- **Guessing:** wrong email and wrong password get the same message and take the same time (an unknown email is still checked against a dummy hash); logins and signups are rate-limited per address (`AUTH_RATE_LIMIT`).
- **Isolation:** every program query includes the user's id, so one student can't read or change another's programs (tested).
- **Gaps:** no email verification, no password reset, no account deletion yet; the rate limit is in memory, per process.
- **Frontend:** hash routes (`#/`, `#/login`, `#/signup`, `#/app`) because GitHub Pages serves files only. The tool loads lazily the first time it's opened and then stays loaded, so going to log in and back keeps the program and the run.

## 7. Limitations (be ready to discuss these)

| Area | Limitation | Effect |
|---|---|---|
| Why Engine | An overwrite through a pointer doesn't "kill" the old value (`x = 1; *p = 5` keeps `x = 1` in x's slice) | Extra lines (`evaluation/slicing`, s17) |
| Why Engine | A call depends on *all* of the calling line's reads (`f(a) + g(b)`: f's parameter seems to depend on b) | Extra lines in rare cases |
| Why Engine | Control dependence is structural (enclosing if/loop, guard clauses); `break`/`continue` deeper in a loop aren't modelled | Possible missed lines |
| Python | `nonlocal`, class attributes changed through the class, and library functions that mutate arguments (beyond `random.shuffle`, `heapq`, `bisect`) aren't tracked | Possible missed lines |
| Python | Generators and threads: only the basics | Odd steps |
| C/C++ | Struct and array changes are tracked per variable or heap node, not per field or element | `s.x = 1` affects all of `s`; `average` of `marks` depends on `marks[0]` changes it never read |
| C/C++ | Heap memory is found only through pointers to struct types; a `malloc`'d array of ints is shown only through the pointer's first element, and uninitialised memory shows whatever it holds | Partial memory view |
| C/C++ | Pointer arithmetic outside a known variable (e.g. into `malloc` memory) is tracked by raw address only | Less precise answers |
| C/C++ | Library functions writing through pointers: only a known list (`scanf`, `strcpy`, `memset`…) | Possible missed lines |
| C/C++ | Speed: about 15 steps/s with the old Windows GDB 7.6, much faster with Linux GDB in Docker | Long programs hit the limits |
| Explainer | Values only in the text, not in `mentioned_values`, aren't checked | Possible unflagged error |
| All | Step limit (2000 Python, 1000 C/C++) and time limits | Long runs are cut |

## 8. References

Check each source yourself before citing it in the report.

- M. Weiser. Program slicing. *ICSE* 1981.
- B. Korel and J. Laski. Dynamic program slicing. *Information Processing Letters* 29(3), 1988.
- H. Agrawal and J. R. Horgan. Dynamic program slicing. *PLDI* 1990.
- A. J. Ko and B. A. Myers. Designing the Whyline: a debugging interface for asking questions about program behavior. *CHI* 2004.
- P. J. Guo. Online Python Tutor: embeddable web-based program visualization for CS education. *SIGCSE* 2013.
- J. Sorva. Notional machines and introductory programming education. *ACM Transactions on Computing Education* 13(2), 2013.
