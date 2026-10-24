"""Tests for the Kaaran tracer.

Run from the kaaran folder:   python -m pytest tests -v

The tests are grouped by the build steps in tracer/tracer.py.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tracer"))

from tracer import trace  # noqa: E402


def run(name, stdin=""):
    with open(os.path.join(ROOT, "tests", "programs", name), encoding="utf-8") as f:
        return trace(f.read(), stdin)


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


def test_all_programs_run_without_internal_errors():
    stdin = {"13_input.py": "Asha\n19\n"}
    for name in sorted(os.listdir(os.path.join(ROOT, "tests", "programs"))):
        if name.endswith(".py"):
            result = run(name, stdin.get(name, ""))
            assert "internal_error" not in result, name
            assert result["steps"], name


def test_stdout_matches_a_normal_run():
    """Tracing must not change what the program prints."""
    import contextlib
    import io
    for name in ["01_loop.py", "07_nested_loops.py", "08_while.py", "09_strings.py",
                 "10_dict.py", "11_class.py", "14_list_of_lists.py"]:
        with open(os.path.join(ROOT, "tests", "programs", name), encoding="utf-8") as f:
            code = f.read()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(code, name, "exec"), {"__name__": "__main__"})
        assert run(name)["stdout"] == out.getvalue(), name


# ---------- Step 5: calls, returns and errors ----------

def test_step5_call_and_return_events():
    steps = run("03_function.py")["steps"]
    call = next(s for s in steps if s["event"] == "call")
    assert call["writes"] == ["n"] and same(call["locals"]["n"], 4)
    ret = next(s for s in steps if s["event"] == "return" and s["frame_id"] == call["frame_id"])
    assert ret["return_value"] == "16"


def test_step5_error_and_its_line():
    result = run("12_exception.py")
    assert result["error"].startswith("ZeroDivisionError")
    assert result["error_line"] == 2
    assert any(s["event"] == "exception" for s in result["steps"])


def test_step5_syntax_error():
    result = trace("x = (1 +\n")
    assert result["error"].startswith("SyntaxError")
    assert result["steps"] == []


def test_step5_except_exception_cannot_hide_the_step_limit():
    code = "while True:\n    try:\n        pass\n    except Exception:\n        pass\n"
    result = trace(code, max_steps=200)
    assert result["truncated"] and "Stopped" in result["error"]


# ---------- Step 6: input() ----------

def test_step6_input_is_read_and_echoed():
    result = run("13_input.py", "Asha\n19\n")
    assert result["error"] is None
    assert result["stdout"] == "Name: Asha\nAge: 19\nAsha will be 20 next year\n"


def test_step6_missing_input_is_an_eof_error():
    result = run("13_input.py", "Asha\n")
    assert result["error"].startswith("EOFError")
    assert result["error_line"] == 2


# ---------- Step 7: reads/writes, heap and control parents ----------

def test_step7_reads_and_writes_on_steps():
    steps = line_steps(run("01_loop.py"))
    body = next(s for s in steps if s["line"] == 3)
    assert set(body["reads"]) == {"total", "i"} and body["writes"] == ["total"]


def test_step7_aliasing_shares_one_heap_object():
    steps = line_steps(run("05_aliasing.py"))
    at_line3 = next(s for s in steps if s["line"] == 3)
    refs = at_line3["stack"][-1]["refs"]
    assert refs["a"] == refs["b"]
    assert at_line3["mutates"] == [refs["a"]]
    assert at_line3["heap"][refs["a"]]["type"] == "list"


def test_step7_list_inside_list_is_a_child():
    last = run("14_list_of_lists.py")["steps"][-1]
    refs = last["stack"][-1]["refs"]
    assert last["heap"][refs["grid"]]["children"] == [refs["row"], refs["row"]]


def test_step7_control_parent_points_to_the_if():
    steps = run("02_if_else.py")["steps"]
    branch = next(s for s in steps if s["event"] == "line" and s["line"] == 5)
    assert steps[branch["control_parent"] - 1]["line"] == 2
    assert branch["branch"] is False


def test_step7_objects_of_own_classes_are_shown_by_attributes():
    last = run("11_class.py")["steps"][-1]
    assert last["locals"]["c"] == "Counter(value=5)"


def test_step7_class_body_is_not_a_call():
    steps = run("11_class.py")["steps"]
    assert all(s["stack"][-1]["func"] != "Counter" for s in steps if s["event"] in ("call", "return"))


def test_values_are_cut_short():
    result = trace("big = list(range(1000))\n")
    value = result["steps"][-1]["locals"]["big"]
    assert len(value) <= 200 and "…" in value


def test_heap_objects_have_labelled_links():
    last = run("16_linked_list.py")["steps"][-1]
    refs = last["stack"][-1]["refs"]
    head = last["heap"][refs["head"]]
    assert head["fields"] == {"value": "1"}
    assert head["edges"] == [{"label": "next", "to": last["heap"][refs["head"]]["children"][0]}]
