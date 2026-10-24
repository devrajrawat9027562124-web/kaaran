"""Tests for the C/C++ tracer (backend/runner/c_tracer.py) and the Why
Engine on its traces.

Run from the kaaran folder:   python -m pytest tests -v

They need gcc, g++ and gdb. Without them the tests are skipped, unless
KAARAN_REQUIRE_GDB=1 is set (CI sets it, so they can't silently skip there).
The checks avoid exact line sequences: different gcc/gdb versions stop on
slightly different lines (a closing brace, for example).
"""
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend", "runner"))
sys.path.insert(0, os.path.join(ROOT, "tracer"))

TOOLS = all(shutil.which(t) for t in ("gcc", "g++", "gdb"))
if not TOOLS:
    if os.environ.get("KAARAN_REQUIRE_GDB") == "1":
        raise RuntimeError("gcc, g++ and gdb are required for these tests")
    pytest.skip("gcc/g++/gdb not installed", allow_module_level=True)
pytest.importorskip("tree_sitter")

from c_tracer import trace  # noqa: E402
from why import WhyEngine  # noqa: E402

_cache = {}


def run(path, stdin="", max_steps=1000):
    key = (path, stdin, max_steps)
    if key not in _cache:
        with open(os.path.join(ROOT, "tests", "programs", path), encoding="utf-8") as f:
            language = "cpp" if path.endswith(".cpp") else "c"
            _cache[key] = trace(f.read(), language, stdin, max_steps)
    return _cache[key]


def last_locals(result):
    return result["steps"][-1]["locals"]


def why_last(result, name, frame_index=-1):
    return WhyEngine(result).why(len(result["steps"]), name, frame_index)


# ---------- Running and stepping ----------

def test_loop_runs_and_counts():
    result = run("c/01_loop.c")
    assert result["error"] is None and result["exit_code"] == 0
    assert result["stdout"] == "3\n"
    body = [s for s in result["steps"] if s["event"] == "line" and s["line"] == 6]
    assert len(body) == 3
    assert last_locals(result)["total"] == "3"


def test_steps_are_numbered_and_end_with_return():
    steps = run("c/01_loop.c")["steps"]
    assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))
    assert steps[-1]["event"] == "return" and steps[-1]["return_value"] == "0"


def test_variable_hidden_until_declared():
    first = run("c/03_function.c")["steps"][0]  # stopped on `int a = square(4);`
    assert "a" not in first["locals"]


def test_call_return_and_stack():
    steps = run("c/03_function.c")["steps"]
    call = next(s for s in steps if s["event"] == "call")
    assert call["writes"] == ["n"] and call["locals"]["n"] == "4"
    assert [f["func"] for f in call["stack"]] == ["main", "square"]
    ret = next(s for s in steps if s["event"] == "return" and s["frame_id"] == call["frame_id"])
    assert ret["return_value"] == "16"


def test_recursion_depth_and_return_values():
    result = run("c/04_recursion.c")
    assert result["stdout"] == "24\n"
    deepest = max(sum(1 for f in s["stack"] if f["func"] == "factorial") for s in result["steps"])
    assert deepest == 4
    returns = [s["return_value"] for s in result["steps"]
               if s["event"] == "return" and s["stack"][-1]["func"] == "factorial"]
    assert returns == ["1", "2", "6", "24"]


def test_scanf_reads_given_input():
    result = run("c/08_scanf_input.c", "41\n")
    assert result["stdout"] == "Age: Next year you will be 42\n"
    assert last_locals(result)["age"] == "41"


def test_segfault_is_reported_with_its_line():
    result = run("c/10_segfault.c")
    assert "SIGSEGV" in result["error"] and result["error_line"] == 6
    assert result["stdout"] == "before\n"
    assert result["steps"][-1]["event"] == "exception"


def test_infinite_loop_is_stopped():
    result = run("c/09_infinite_loop.c", max_steps=60)
    assert result["truncated"] and "Stopped" in result["error"]
    assert len(result["steps"]) <= 60


def test_compile_error_has_a_line():
    result = trace("int main(void) {\n    int x = 5\n    return x;\n}\n", "c")
    assert result["error"].startswith("Compile error")
    assert result["error_line"] in (2, 3)  # gcc points at the missing ';' or the next line
    assert result["steps"] == []


def test_globals_frame():
    step = run("c/11_global.c")["steps"][-1]
    assert step["stack"][0]["func"] == "globals"
    assert step["stack"][0]["locals"]["count"] == "2"


def test_pointer_shows_what_it_points_to():
    step = run("c/07_pointer_alias.c")["steps"][-1]
    assert step["locals"]["p"].endswith("→ 10")
    assert step["stack"][-1]["refs"]["p"] == step["stack"][-1]["refs"]["x"]


# ---------- Why Engine on C traces ----------

def test_why_through_pointer():
    answer = why_last(run("c/07_pointer_alias.c"), "x")
    assert 6 in answer["lines"]
    assert "p points to x" in answer["summary"]


def test_why_through_pointer_parameter():
    answer = why_last(run("c/06_pointer_swap.c"), "x")
    assert 5 in answer["lines"]
    assert "a points to x" in answer["summary"]


def test_why_finds_the_loop_bug():
    answer = why_last(run("c/05_array_bug.c"), "total")
    assert {4, 6, 7} <= set(answer["lines"])


def test_why_global_written_in_function():
    answer = why_last(run("c/11_global.c"), "count", frame_index=0)
    assert 6 in answer["lines"]


# ---------- C++ ----------

def test_cpp_vector_values():
    result = run("cpp/02_vector.cpp")
    assert result["stdout"] == "14\n"
    assert last_locals(result)["v"] == "{1, 4, 9}"


def test_cpp_input_stream():
    result = run("cpp/04_cin_input.cpp", "3 4\n")
    assert result["stdout"] == "Two numbers: Sum: 7\n"
    assert set(why_last(result, "sum")["lines"]) >= {7, 8}


def test_cpp_reference_parameter():
    answer = why_last(run("cpp/03_reference.cpp"), "a")
    assert "n is a reference to a" in answer["summary"]


def test_cpp_method_changes_object_through_this():
    result = run("cpp/05_class.cpp")
    assert result["stdout"] == "5\n"
    assert "this points to c" in why_last(result, "c")["summary"]
