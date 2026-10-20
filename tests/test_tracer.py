"""Tests for the Kaaran tracer.

Run from the kaaran folder:   python -m pytest tests -v

The tests are grouped by the build steps in tracer/tracer.py.
They will fail at first -- make them pass one step at a time.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tracer"))

from tracer import trace  # noqa: E402


def run(name):
    with open(os.path.join(ROOT, "tests", "programs", name), encoding="utf-8") as f:
        return trace(f.read())


def line_steps(result):
    return [s for s in result["steps"] if s["event"] == "line"]


def same(stored, expected):
    """Values may be stored as real values or as repr() strings -- accept both."""
    return stored == expected or stored == repr(expected)


# ---------- Step 1: line numbers ----------

def test_step1_loop_line_order():
    lines = [s["line"] for s in line_steps(run("01_loop.py"))]
    assert lines == [1, 2, 3, 2, 3, 2, 3, 2, 4]


def test_step1_step_numbers_start_at_1():
    steps = run("01_loop.py")["steps"]
    assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))


def test_step1_if_else_skips_branch():
    lines = [s["line"] for s in line_steps(run("02_if_else.py"))]
    assert 3 not in lines  # x = 7 is odd, so `kind = "even"` never runs
    assert 5 in lines


# ---------- Step 2: locals ----------

def test_step2_locals_change():
    steps = line_steps(run("01_loop.py"))
    before_print = steps[-1]  # line 4, before print runs
    assert same(before_print["locals"]["total"], 3)


def test_step2_no_dunder_names():
    for s in run("01_loop.py")["steps"]:
        assert not any(k.startswith("__") for k in s["locals"])


def test_step2_aliasing_snapshot():
    """The list must be recorded as it was AT that step, not at the end."""
    steps = line_steps(run("05_aliasing.py"))
    at_line3 = next(s for s in steps if s["line"] == 3)  # before a.append(3)
    assert same(at_line3["locals"]["b"], [1, 2])
    at_line4 = next(s for s in steps if s["line"] == 4)  # after a.append(3)
    assert same(at_line4["locals"]["b"], [1, 2, 3])


# ---------- Step 3: stdout ----------

def test_step3_stdout_grows():
    steps = run("01_loop.py")["steps"]
    at_print = next(s for s in steps if s["event"] == "line" and s["line"] == 4)
    assert at_print["stdout"] == ""   # print hasn't run yet
    assert steps[-1]["stdout"] == "3\n"


# ---------- Step 4: call stack ----------

def test_step4_recursion_depth():
    steps = run("04_recursion.py")["steps"]
    deepest = max(sum(1 for f in s["stack"] if f["func"] == "factorial") for s in steps)
    assert deepest == 4  # factorial(4) -> (3) -> (2) -> (1)


def test_step4_stack_outermost_first():
    steps = run("03_function.py")["steps"]
    inside = next(s for s in steps if s["event"] == "line" and s["line"] == 2)
    assert [f["func"] for f in inside["stack"]] == ["<module>", "square"]
    assert same(inside["stack"][-1]["locals"]["n"], 4)


# ---------- Safety (already works in the skeleton) ----------

def test_infinite_loop_stops():
    result = run("06_infinite_loop.py")
    assert result["error"] is not None
    assert "Stopped" in result["error"]
