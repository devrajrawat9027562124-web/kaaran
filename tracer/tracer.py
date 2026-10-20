"""Kaaran tracer: run a Python program and record a step-by-step trace.

Usage: python tracer/tracer.py <program.py>

See docs/trace-format.md for the output format.
Remaining TODO: analyze_reads_writes() (needed for the Why Engine).
"""
import ast
import copy
import io
import json
import sys

FILENAME = "<kaaran>"
MAX_STEPS = 1000


class StepLimitExceeded(Exception):
    pass


def analyze_reads_writes(code):
    """Return {line_number: {"reads": [...], "writes": [...]}}.

    TODO: walk the AST (ast.walk). For each ast.Name node:
      - ctx is ast.Load  -> a read on node.lineno
      - ctx is ast.Store -> a write on node.lineno
    Careful: `total += i` is ast.AugAssign; its target is Store,
    but it also reads `total`.
    """
    return {}


def snapshot(value):
    """Copy a value as it is right now.

    Storing the object itself would be wrong for lists/dicts: if the program
    changes them later, every earlier step would show the new value too.
    """
    try:
        return copy.deepcopy(value)
    except Exception:
        return repr(value)  # some objects (files, generators) can't be copied


def snapshot_locals(frame):
    """User-visible variables of one frame, skipping Python internals like __name__."""
    return {name: snapshot(value)
            for name, value in frame.f_locals.items()
            if not name.startswith("__")}


def build_stack(frame):
    """Call stack from the outermost frame (<module>) to the current one."""
    stack = []
    while frame is not None and frame.f_code.co_filename == FILENAME:
        stack.append({"func": frame.f_code.co_name, "locals": snapshot_locals(frame)})
        frame = frame.f_back
    stack.reverse()
    return stack


def trace(code):
    steps = []
    event_count = 0
    rw = analyze_reads_writes(code)
    output = io.StringIO()

    def tracer(frame, event, arg):
        nonlocal event_count
        # Only trace the user's code, not Python internals
        if frame.f_code.co_filename != FILENAME:
            return None
        event_count += 1
        if event_count > MAX_STEPS:
            raise StepLimitExceeded(f"Stopped after {MAX_STEPS} steps (infinite loop?)")

        stack = build_stack(frame)
        steps.append({
            "step": len(steps) + 1,
            "line": frame.f_lineno,  # for "line" events: the line about to run
            "event": event,
            "locals": stack[-1]["locals"],
            "stack": stack,
            "stdout": output.getvalue(),
        })
        return tracer

    error = None
    old_stdout = sys.stdout
    sys.stdout = output
    sys.settrace(tracer)
    try:
        exec(compile(code, FILENAME, "exec"), {"__name__": "__main__"})
    except StepLimitExceeded as e:
        error = str(e)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    finally:
        sys.settrace(None)
        sys.stdout = old_stdout

    return {"steps": steps, "stdout": output.getvalue(), "error": error}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.dumps(trace(f.read()), indent=2, default=repr))
