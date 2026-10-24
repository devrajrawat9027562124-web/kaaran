# Trace format

Every language adapter (Python now, C/C++ next, Java later) outputs this **same** format, so the UI and engines work for all languages without changes. The Why Engine (`tracer/why.py`) only reads this format; it never looks at Python itself.

## Whole trace

```json
{
  "language": "python",
  "code": "total = 0\nfor i in range(3):\n    total += i\nprint(total)\n",
  "steps": [ ... ],
  "stdout": "3\n",
  "error": null,
  "error_line": null,
  "truncated": false
}
```

| Field | Meaning |
|---|---|
| `language` | `python`, `c` or `cpp` |
| `code` | The program that was run (the Why Engine quotes lines from it) |
| `steps` | One entry per event, in order (below) |
| `stdout` | Everything the program printed |
| `error` | `"ZeroDivisionError: division by zero"`, `"Stopped after 2000 steps (infinite loop?)"`, a compile error, or `null` |
| `error_line` | Line of the error, if known |
| `truncated` | `true` if the step limit stopped the program |
| `compile_output` | C/C++ only: compiler messages |
| `exit_code` | C/C++ only: what `main` returned |
| `input_ran_out` | C/C++ only: line whose read found the input used up (a menu program given too little input) |

## One step

```json
{
  "step": 7,
  "line": 3,
  "event": "line",
  "frame_id": 1,
  "locals": {"total": "1", "i": "2"},
  "stack": [
    {"func": "<module>", "frame_id": 1, "line": 3,
     "locals": {"total": "1", "i": "2"}, "refs": {}}
  ],
  "heap": {},
  "stdout": "",
  "reads": ["total", "i"],
  "writes": ["total"],
  "mutates": [],
  "control_parent": 6
}
```

| Field | Meaning |
|---|---|
| `step` | Step number, starting at 1, no gaps |
| `line` | Line about to run (for `line` events) |
| `event` | `line`, `call`, `return`, or `exception` |
| `frame_id` | Which function call this step belongs to (each call gets a new number) |
| `locals` | Variables of the current function (same as the last `stack` entry) |
| `stack` | Call frames, outermost first, each with `func`, `frame_id`, current `line`, `locals` and `refs` |
| `refs` | For variables that hold a shared (mutable) object: variable → object id, e.g. `{"a": "obj_1", "b": "obj_1"}` means `a` and `b` are the **same** list |
| `heap` | Shared objects by id: `{"obj_1": {"type": "list", "value": "[1, 2]", "children": []}}`. `children` are objects inside it (a list of lists); `fields` are its plain values (`{"data": "50"}`) and `edges` its labelled arrows to other objects (`[{"label": "left", "to": "0x…"}]`), used to draw memory. C/C++ adds `kind` (`heap` for a struct from malloc/new, `variable` for a variable's own memory) and `freed` |
| `stdout` | All output printed **before** this step |
| `reads` / `writes` | Variables this line uses / rebinds |
| `mutates` | Object ids this line changes in place (`a.append(3)`, `a[0] = 1`, `self.x = 1`) |
| `globals` | (optional) Names this line writes in the outermost frame (`global count`) |
| `control_parent` | Step of the `if`/`for`/`while` (or the function call) that made this line run |
| `branch` | (optional) `true` if the line is in an if-body, `false` if in its else-body |
| `header` | (optional) `"if"`, `"loop"`, `"switch"` (C `switch`, Python `match`) or `"except"` for those header lines |
| `frees` | (optional, C/C++) memory this line frees (`free(p)`, `delete p`) |
| `return_value` | (`return` events) What the function returned |
| `exception` | (`exception` events) The error raised here |

## Rules every adapter follows

- **Values are display strings**, taken at that moment (`"[1, 2]"`, `"'odd'"`, `"Counter(value=5)"`). A string can't change later, so earlier steps keep their old values. Long values are cut short with `…`.
- **`line` steps show the state *before* the line runs.** Its effect shows up at the next step of the same frame.
- **`call` steps** write the parameters; their `control_parent` is the line that made the call.
- **The last step** is the `return` of the outermost frame, showing the final state ("the program finished").

The C/C++ adapter fills `refs`/`mutates` with memory addresses instead of `obj_N`, and `reads`/`writes` from tree-sitter instead of Python's `ast`.
