"""Tests for tracer/analysis.py: what each line reads, writes and changes.

Run from the kaaran folder:   python -m pytest tests -v
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tracer"))

from analysis import analyze  # noqa: E402


def line(code, n):
    return analyze(code)[n]


def test_assignment_reads_and_writes():
    info = line("x = y + z\n", 1)
    assert info["writes"] == ["x"]
    assert set(info["reads"]) == {"y", "z"}


def test_augmented_assignment_reads_its_target():
    info = line("total = 0\ntotal += i\n", 2)
    assert "total" in info["reads"] and "i" in info["reads"]
    assert info["writes"] == ["total"]


def test_for_header_writes_loop_variable():
    info = line("for i in range(3):\n    pass\n", 1)
    assert info["writes"] == ["i"]
    assert "range" in info["reads"]
    assert info["header"] == "loop"


def test_method_call_mutates_object():
    info = line("a = [1]\na.append(2)\n", 2)
    assert info["method_mutates"] == ["a"]
    assert info["writes"] == []


def test_subscript_store_mutates_container():
    info = line("a[i] = v\n", 1)
    assert info["mutates"] == ["a"]
    assert set(info["reads"]) == {"a", "i", "v"}


def test_nested_subscript_mutates_inner_object():
    assert line("grid[0][1] = 5\n", 1)["mutates"] == ["grid[0]"]


def test_attribute_store_mutates_object():
    info = line("self.value += amount\n", 1)
    assert info["mutates"] == ["self"]
    assert "amount" in info["reads"]


def test_comprehension_variable_is_not_a_read():
    info = line("squares = [x * x for x in nums]\n", 1)
    assert info["reads"] == ["nums"]
    assert info["writes"] == ["squares"]


def test_control_parent_lines():
    code = "if a:\n    b = 1\nelse:\n    b = 2\nc = 3\n"
    info = analyze(code)
    assert info[2]["control"] == 1 and info[2]["branch"] is True
    assert info[4]["control"] == 1 and info[4]["branch"] is False
    assert info[5]["control"] is None


def test_guard_clause_controls_following_lines():
    code = "def f(n):\n    if n <= 1:\n        return 1\n    return n * f(n - 1)\n"
    info = analyze(code)
    assert info[4]["control"] == 2 and info[4]["branch"] is False


def test_global_declaration_is_recorded():
    code = "count = 0\ndef inc():\n    global count\n    count += 1\n"
    assert analyze(code)[4]["globals"] == ["count"]


def test_function_def_writes_its_name():
    info = line("def square(n):\n    return n * n\n", 1)
    assert info["writes"] == ["square"]
