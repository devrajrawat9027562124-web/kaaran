"""Kaaran tracer: run a Python program and record a step-by-step trace.

Usage: python tracer/tracer.py <program.py> [--input <file>]

See docs/trace-format.md for the output format. This file also runs in the
browser (Pyodide), so it may only use the standard library.
"""
import ast
import builtins
import inspect
import io
import json
import random
import sys
import types

from analysis import analyze

FILENAME = "<kaaran>"
MAX_STEPS = 2000
MAX_VALUE_CHARS = 200   # longer values are cut short in the UI
MAX_ITEMS = 50          # list/dict items shown before "…"
MAX_DEPTH = 4           # nesting shown before "…"
MAX_HEAP_OBJECTS = 100

# Raised and caught inside Python internals all the time; not interesting
HIDDEN_EXCEPTIONS = (StopIteration, StopAsyncIteration, GeneratorExit)

CALLABLE_TYPES = (types.FunctionType, types.BuiltinFunctionType, types.MethodType,
                  types.ModuleType, type)


class StepLimitExceeded(BaseException):
    """A BaseException, so the student's `except Exception:` can't swallow it."""


# ---------- Values ----------

def describe(value):
    """Text shown for a value, e.g. [1, 2], 'odd', Point(x=1, y=2).

    A string is a snapshot: if the program changes a list later, earlier steps
    still show the old value. It never calls the student's own __repr__, and
    long values are cut short.
    """
    text = _describe(value, 0, frozenset())
    if len(text) > MAX_VALUE_CHARS:
        text = text[:MAX_VALUE_CHARS - 1] + "…"
    return text


def _describe(value, depth, seen):
    if value is None or isinstance(value, (bool, int, float, complex, str, bytes, range)):
        return repr(value)
    if isinstance(value, (types.FunctionType, types.BuiltinFunctionType)):
        return f"function {value.__name__}"
    if isinstance(value, types.MethodType):
        return f"method {value.__func__.__name__}"
    if isinstance(value, type):
        return f"class {value.__name__}"
    if isinstance(value, types.ModuleType):
        return f"module {value.__name__}"
    if id(value) in seen or depth >= MAX_DEPTH:
        return "…"
    seen = seen | {id(value)}

    def items(values):
        values = list(values)
        shown = [_describe(v, depth + 1, seen) for v in values[:MAX_ITEMS]]
        if len(values) > MAX_ITEMS:
            shown.append("…")
        return ", ".join(shown)

    if isinstance(value, list):
        return "[" + items(value) + "]"
    if isinstance(value, tuple):
        return "(" + items(value) + ("," if len(value) == 1 else "") + ")"
    if isinstance(value, (set, frozenset)):
        if not value:
            return f"{type(value).__name__}()"
        inner = "{" + items(value) + "}"
        return inner if isinstance(value, set) else f"frozenset({inner})"
    if isinstance(value, dict):
        pairs = list(value.items())
        shown = [f"{_describe(k, depth + 1, seen)}: {_describe(v, depth + 1, seen)}"
                 for k, v in pairs[:MAX_ITEMS]]
        if len(pairs) > MAX_ITEMS:
            shown.append("…")
        return "{" + ", ".join(shown) + "}"
    attrs = _instance_dict(value)
    if attrs is not None:
        fields = ", ".join(f"{k}={_describe(v, depth + 1, seen)}"
                           for k, v in list(attrs.items())[:MAX_ITEMS] if not k.startswith("__"))
        return f"{type(value).__name__}({fields})"
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def _instance_dict(value):
    """The attributes of an object of a student-defined class, else None."""
    if isinstance(value, CALLABLE_TYPES + (BaseException,)):
        return None
    try:
        attrs = object.__getattribute__(value, "__dict__")
    except Exception:
        return None
    return attrs if isinstance(attrs, dict) else None


def is_heap_object(value):
    """Mutable objects that two variables can share (aliasing)."""
    return isinstance(value, (list, dict, set, bytearray)) or _instance_dict(value) is not None


def _children(value):
    """Objects directly inside a container (looking through tuples)."""
    if isinstance(value, dict):
        found = list(value.keys()) + list(value.values())
    elif isinstance(value, (list, tuple, set, frozenset)):
        found = list(value)
    else:
        found = list((_instance_dict(value) or {}).values())
    for item in found:
        if isinstance(item, (tuple, frozenset)):
            yield from _children(item)
        else:
            yield item


def visible_locals(frame):
    """User-visible variables of one frame, skipping Python internals like
    __name__ and imported modules."""
    return {name: value for name, value in frame.f_locals.items()
            if not name.startswith("__") and not isinstance(value, types.ModuleType)}


def resolve_path(path, frame):
    """Look up an expression like a, self.items or grid[0] in a frame
    without running any of the student's code (no properties, no __getitem__
    of their own classes). Raises LookupError if that isn't possible."""
    return _resolve(ast.parse(path, mode="eval").body, frame)


def _resolve(node, frame):
    if isinstance(node, ast.Name):
        for scope in (frame.f_locals, frame.f_globals):
            if node.id in scope:
                return scope[node.id]
        raise LookupError(node.id)
    if isinstance(node, ast.Attribute):
        attrs = _instance_dict(_resolve(node.value, frame))
        if attrs is None or node.attr not in attrs:
            raise LookupError(node.attr)
        return attrs[node.attr]
    if isinstance(node, ast.Subscript):
        container = _resolve(node.value, frame)
        if type(container) not in (list, tuple, dict):
            raise LookupError("subscript")
        key = node.slice
        if isinstance(key, ast.Name):
            key = _resolve(key, frame)
        else:
            key = ast.literal_eval(key)
        try:
            return container[key]
        except Exception:
            raise LookupError("subscript")
    raise LookupError("unsupported")


# ---------- Recording ----------

class Recorder:
    """The trace function. Python calls it for every event in the student's
    code; it records one step per event."""

    def __init__(self, lines, max_steps):
        self.lines = lines              # static info from analyze()
        self.max_steps = max_steps
        self.steps = []
        self.output = io.StringIO()
        self.frame_ids = {}             # frame -> frame number (keeps frames alive,
        self.object_ids = {}            # id(obj) -> "obj_N"     so id()s are never
        self.keep_alive = []            #                         reused mid-run)
        self.call_step = {}             # frame number -> its "call" step
        self.last_at_line = {}          # (frame number, line) -> latest step there
        self.last_line_step = {}        # frame number -> latest "line" step
        self.last_event = {}            # frame number -> latest event
        self.internal_error = None

    def __call__(self, frame, event, arg):
        if frame.f_code.co_filename != FILENAME:
            return None  # only trace the student's code, not Python internals
        if event == "exception" and issubclass(arg[0], HIDDEN_EXCEPTIONS):
            return self
        if event in ("call", "return") and not is_function(frame.f_code):
            # The program starting, or a class body (class Counter:) running,
            # isn't a call the student made
            if event == "call" or frame.f_code.co_name != "<module>":
                self._frame_id(frame)
                return self
        if len(self.steps) >= self.max_steps:
            raise StepLimitExceeded(f"Stopped after {self.max_steps} steps (infinite loop?)")
        try:
            self._record(frame, event, arg)
        except Exception as e:
            # A bug in Kaaran must not change how the student's program runs
            self.internal_error = f"{type(e).__name__}: {e}"
        return self

    def _frame_id(self, frame):
        if frame not in self.frame_ids:
            self.frame_ids[frame] = len(self.frame_ids) + 1
        return self.frame_ids[frame]

    def _object_id(self, value):
        if id(value) not in self.object_ids:
            self.object_ids[id(value)] = f"obj_{len(self.object_ids) + 1}"
            self.keep_alive.append(value)
        return self.object_ids[id(value)]

    def _record(self, frame, event, arg):
        fid = self._frame_id(frame)
        number = len(self.steps) + 1
        stack, heap = self._snapshot(frame)
        step = {
            "step": number,
            "line": frame.f_lineno,  # for "line" events: the line about to run
            "event": event,
            "frame_id": fid,
            "locals": stack[-1]["locals"],
            "stack": stack,
            "heap": heap,
            "stdout": self.output.getvalue(),
            "reads": [],
            "writes": [],
            "mutates": [],
            "control_parent": None,
        }

        if event == "line":
            info = self.lines.get(frame.f_lineno)
            control_line = None
            if info:
                step["reads"] = list(info["reads"])
                step["writes"] = list(info["writes"])
                step["mutates"] = self._mutated_objects(info["mutates"], info["method_mutates"], frame)
                if info["globals"]:
                    step["globals"] = list(info["globals"])
                if info["branch"] is not None:
                    step["branch"] = info["branch"]
                if info["header"]:
                    step["header"] = info["header"]
                control_line = info["control"]
            if control_line is not None:
                step["control_parent"] = self.last_at_line.get((fid, control_line))
            else:  # top of a function body: the call decided that it runs
                step["control_parent"] = self.call_step.get(fid)
            self.last_at_line[(fid, frame.f_lineno)] = number
            self.last_line_step[fid] = number

        elif event == "call":
            step["writes"] = parameter_names(frame.f_code)
            caller = self.frame_ids.get(frame.f_back)
            step["control_parent"] = self.last_line_step.get(caller)
            self.call_step[fid] = number

        elif event == "return":
            unwinding = self.last_event.get(fid) == "exception"  # leaving because of an error
            if not unwinding and frame.f_code.co_name != "<module>":
                step["return_value"] = describe(arg)

        elif event == "exception":
            step["exception"] = f"{arg[0].__name__}: {arg[1]}"

        self.last_event[fid] = event
        self.steps.append(step)

    def _snapshot(self, frame):
        """Call stack (outermost first) and the shared objects it can reach."""
        frames = []
        while frame is not None and frame.f_code.co_filename == FILENAME:
            frames.append(frame)
            frame = frame.f_back
        frames.reverse()

        stack, roots = [], []
        for f in frames:
            variables = visible_locals(f)
            refs = {}
            for name, value in variables.items():
                if is_heap_object(value):
                    refs[name] = self._object_id(value)
                    roots.append(value)
                elif isinstance(value, (tuple, frozenset)):
                    roots.extend(_children(value))
            stack.append({
                "func": f.f_code.co_name,
                "frame_id": self._frame_id(f),
                "line": f.f_lineno,
                "locals": {name: describe(value) for name, value in variables.items()},
                "refs": refs,
            })
        return stack, self._heap(roots)

    def _heap(self, roots):
        heap, todo = {}, list(roots)
        while todo and len(heap) < MAX_HEAP_OBJECTS:
            value = todo.pop(0)
            if not is_heap_object(value):
                continue
            key = self._object_id(value)
            if key in heap:
                continue
            children = [c for c in _children(value) if is_heap_object(c)]
            fields, edges = self._links(value)
            heap[key] = {
                "type": type(value).__name__,
                "value": describe(value),
                "fields": fields,
                "edges": edges,
                "children": [self._object_id(c) for c in children],
            }
            todo.extend(children)
        return heap

    def _links(self, value):
        """For drawing memory: plain fields of an object, and labelled
        arrows to the objects it holds (node.next, tree.left, items[2])."""
        if isinstance(value, dict):
            pairs = [(_describe(k, 1, frozenset()), v) for k, v in value.items()]
        elif isinstance(value, list):
            pairs = [(f"[{i}]", v) for i, v in enumerate(value)]
        else:
            pairs = [(k, v) for k, v in (_instance_dict(value) or {}).items() if not k.startswith("__")]
        fields, edges = {}, []
        for label, item in pairs[:MAX_ITEMS]:
            if is_heap_object(item):
                edges.append({"label": label, "to": self._object_id(item)})
            elif _instance_dict(value) is not None:  # lists and dicts already show their items
                fields[label] = describe(item)
        return fields, edges

    def _mutated_objects(self, paths, method_paths, frame):
        found = []
        for path, by_method in [(p, False) for p in paths] + [(p, True) for p in method_paths]:
            try:
                value = resolve_path(path, frame)
            except Exception:
                continue  # e.g. a class attribute; the Why Engine falls back to reads
            if by_method and _instance_dict(value) is not None:
                continue  # c.add(2) on the student's own class: traced inside add
            if is_heap_object(value):
                key = self._object_id(value)
                if key not in found:
                    found.append(key)
        return found


def is_function(code):
    """True for functions and methods; False for the module and class bodies."""
    return bool(code.co_flags & inspect.CO_OPTIMIZED)


def parameter_names(code):
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS) + bool(code.co_flags & inspect.CO_VARKEYWORDS)
    return list(code.co_varnames[:count])


def error_line(tb):
    """Line of the student's code where an error happened (innermost frame)."""
    line = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == FILENAME:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


class NeedInput(BaseException):
    """input() found no more input during a live run: the student types it."""


def _program_globals(output, feed, when_empty):
    """Globals for the student's program. input() reads the next line from
    `feed` and echoes it like a terminal does; when_empty(prompt) decides
    what happens when there is none."""
    def fake_input(prompt=""):
        output.write(str(prompt))
        line = feed.readline()
        if not line:
            when_empty(str(prompt))
        output.write(line if line.endswith("\n") else line + "\n")
        return line.rstrip("\r\n")

    student_builtins = dict(vars(builtins))
    student_builtins["input"] = fake_input
    return {"__name__": "__main__", "__builtins__": student_builtins}


def _no_more_input(prompt):
    raise EOFError("EOF when reading a line (give the program more input)")


def trace(code, stdin="", max_steps=MAX_STEPS, seed=None):
    """Run code and return {"steps", "stdout", "error", ...} (docs/trace-format.md).

    stdin is everything the program will read with input(), given up front.
    seed makes random numbers repeat a live run's (see run_live).
    """
    result = {"language": "python", "code": code, "steps": [], "stdout": "",
              "error": None, "error_line": None, "truncated": False}
    try:
        compiled = compile(code, FILENAME, "exec")
        lines = analyze(code)
    except SyntaxError as e:
        result["error"] = f"SyntaxError: {e.msg}"
        result["error_line"] = e.lineno
        return result

    recorder = Recorder(lines, max_steps)
    feed = io.StringIO(stdin)
    program_globals = _program_globals(recorder.output, feed, _no_more_input)
    if seed is not None:
        random.seed(seed)

    old_stdout, old_stdin = sys.stdout, sys.stdin
    sys.stdout, sys.stdin = recorder.output, feed
    sys.settrace(recorder)
    try:
        exec(compiled, program_globals)
    except StepLimitExceeded as e:
        result["error"] = str(e)
        result["truncated"] = True
    except SystemExit as e:
        if e.code not in (None, 0):
            result["error"] = f"SystemExit: {e.code}"
    except BaseException as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_line"] = error_line(e.__traceback__)
    finally:
        sys.settrace(None)
        sys.stdout, sys.stdin = old_stdout, old_stdin

    result["steps"] = recorder.steps
    result["stdout"] = recorder.output.getvalue()
    if recorder.internal_error:
        result["internal_error"] = recorder.internal_error
    return result


def run_live(code, stdin="", seed=None, eof=False):
    """Run a program normally (not traced), for the student to use before it
    is explained. Returns {"status", "stdout", "error", "error_line"}.

    status "input" means the program is waiting for another line. The page
    asks the student, then runs the program again from the start with that
    line added. Up to that point it does exactly the same as before (with
    the same seed, even its random numbers), so to the student it works like
    typing into a terminal. With eof=True, input() at the end raises
    EOFError instead (the student ended the input).
    """
    result = {"status": "done", "stdout": "", "error": None, "error_line": None}
    try:
        compiled = compile(code, FILENAME, "exec")
    except SyntaxError as e:
        result["error"] = f"SyntaxError: {e.msg}"
        result["error_line"] = e.lineno
        return result

    def when_empty(prompt):
        if eof:
            _no_more_input(prompt)
        raise NeedInput(prompt)

    output, feed = io.StringIO(), io.StringIO(stdin)
    program_globals = _program_globals(output, feed, when_empty)
    if seed is not None:
        random.seed(seed)
    old_stdout, old_stdin = sys.stdout, sys.stdin
    sys.stdout, sys.stdin = output, feed
    try:
        exec(compiled, program_globals)
    except NeedInput:
        result["status"] = "input"
    except SystemExit as e:
        if e.code not in (None, 0):
            result["error"] = f"SystemExit: {e.code}"
    except BaseException as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_line"] = error_line(e.__traceback__)
    finally:
        sys.stdout, sys.stdin = old_stdout, old_stdin
    result["stdout"] = output.getvalue()
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    stdin = ""
    if "--input" in args:
        i = args.index("--input")
        with open(args[i + 1], encoding="utf-8") as f:
            stdin = f.read()
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    with open(args[0], encoding="utf-8") as f:
        print(json.dumps(trace(f.read(), stdin), indent=2))
