"""Kaaran tracer: run a Python program and record a step-by-step trace.

Usage: python tracer/tracer.py <program.py>

See docs/trace-format.md for the output format.
Fill in the TODOs one at a time and test on tests/programs/ after each.
"""
import ast
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

        # TODO: append a step dict here (step, line, event, stack, stdout).
        # Hints:
        #   frame.f_lineno, frame.f_code.co_name, frame.f_locals
        #   walk frame.f_back to build the stack (stop when it leaves FILENAME)
        #   copy values -- f_locals changes as the program runs
        #   skip names starting with "__"
        #   output.getvalue() gives stdout so far
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
