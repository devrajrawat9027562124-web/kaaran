"""Tests for the Why Engine (tracer/why.py).

Run from the kaaran folder:   python -m pytest tests -v

Each test asks "why does this variable have this value?" and checks which
lines are in the answer (the slice) and what the summary says.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tracer"))

from tracer import trace  # noqa: E402
from why import WhyEngine  # noqa: E402


def engine(name=None, code=None, stdin=""):
    if name:
        with open(os.path.join(ROOT, "tests", "programs", name), encoding="utf-8") as f:
            code = f.read()
    result = trace(code, stdin)
    return WhyEngine(result), len(result["steps"])


def test_loop_total_depends_on_loop_and_start_value():
    e, last = engine("01_loop.py")
    answer = e.why(last, "total")
    assert answer["lines"] == [1, 2, 3]
    assert "line 3" in answer["summary"]


def test_print_line_is_not_in_its_own_slice():
    e, last = engine("01_loop.py")
    assert 4 not in e.why(last, "total")["lines"]


def test_aliasing_change_through_other_name():
    e, _ = engine("05_aliasing.py")
    answer = e.why(4, "b")  # at line 4: b is [1, 2, 3]
    assert 3 in answer["lines"]  # a.append(3) changed b's list
    assert "a and b are the same list" in answer["summary"]


def test_if_else_slice_has_condition_not_other_branch():
    e, last = engine("02_if_else.py")
    answer = e.why(last, "kind")
    assert answer["lines"] == [1, 2, 5]
    assert any("condition was False" in c["text"] for c in answer["chain"])


def test_value_returned_from_function():
    e, last = engine("03_function.py")
    answer = e.why(last, "a")
    assert {2, 3, 5} <= set(answer["lines"])
    assert "square(...) = 16" in answer["summary"]


def test_parameter_comes_from_call():
    e, _ = engine("03_function.py")
    call = next(n for n, s in e.steps.items() if s["event"] == "call")
    answer = e.why(call, "n")
    assert "passed in when square was called on line 5" in answer["summary"]


def test_mutation_inside_function_reaches_caller():
    code = "def add(lst, x):\n    lst.append(x)\n\nnums = [1]\nadd(nums, 5)\nprint(nums)\n"
    e, last = engine(code=code)
    answer = e.why(last, "nums")
    assert 2 in answer["lines"]
    assert "lst and nums are the same list" in answer["summary"]


def test_nested_list_change_is_explained():
    e, last = engine("14_list_of_lists.py")
    assert "changed a list inside grid" in e.why(last, "grid")["summary"]
    assert "through grid" in e.why(last, "row")["summary"]


def test_unrelated_lines_are_left_out():
    code = "a = 1\nb = 2\nc = a + 1\nb = b * 10\nprint(c)\n"
    e, last = engine(code=code)
    assert e.why(last, "c")["lines"] == [1, 3]


def test_recursion_base_case_condition_is_in_slice():
    e, _ = engine("04_recursion.py")
    answer = e.why_output(0)
    texts = [c["text"] for c in answer["chain"] if c["line"] == 2]
    assert any("False" in t for t in texts) and any("True" in t for t in texts)


def test_output_line_is_traced_to_print():
    e, _ = engine("08_while.py")
    answer = e.why_output(0)
    assert answer["question"]["line"] == 9
    assert {1, 2, 3, 8} <= set(answer["lines"])


def test_object_attribute_change_through_self():
    e, last = engine("11_class.py")
    answer = e.why(last, "c")
    assert 6 in answer["lines"]
    assert "self and c are the same Counter" in answer["summary"]


def test_dict_update_in_loop():
    e, last = engine("10_dict.py")
    answer = e.why(last, "counts")
    assert {2, 3, 4} <= set(answer["lines"])


def test_global_write_inside_function():
    code = "count = 0\ndef inc():\n    global count\n    count += 1\ninc()\ninc()\nprint(count)\n"
    e, last = engine(code=code)
    answer = e.why(last, "count")
    assert 4 in answer["lines"]


def test_slice_never_contains_future_steps():
    e, last = engine("04_recursion.py")
    for n in e.steps:
        for name in e.steps[n]["locals"]:
            assert max(e.why(n, name)["slice"] or [0]) <= n


def test_unknown_variable_raises():
    e, last = engine("01_loop.py")
    try:
        e.why(last, "nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_answer_never_mentions_values_from_later():
    """Asked inside average(), the call line `result = average(marks)` hasn't
    finished: the answer must not reveal what result will become."""
    e, _ = engine("15_average_bug.py")
    at = next(n for n, s in e.steps.items() if s["event"] == "line" and s["line"] == 5)
    answer = e.why(at, "total")
    assert "53.3" not in " ".join(c["text"] for c in answer["chain"])
    call_line = next(c for c in answer["chain"] if c["line"] == 9)
    assert "average()" in call_line["text"]


def test_outer_variable_not_set_while_its_line_is_still_running():
    code = "x = 1\ndef f():\n    return x + 1\nx = f()\n"
    e, _ = engine(code=code)
    inside = next(n for n, s in e.steps.items() if s["event"] == "line" and s["line"] == 3)
    # reading x inside f gets it from `x = 1`, not from the unfinished `x = f()`
    sources = e._sources(e.steps[inside], "x", inside)
    assert [e.steps[n]["line"] for n in sources] == [1]


def test_function_definitions_are_marked():
    e, last = engine("03_function.py")
    first = e.explain_step(1)
    assert first["kind"] == "definition" and first["text"] == "defined function square"
