"""Tests for backend/runner/c_analysis.py: what each C/C++ line reads and writes.

Run from the kaaran folder:   python -m pytest tests -v
Skipped if tree-sitter isn't installed (pip install -r backend/runner/requirements.txt).
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend", "runner"))

pytest.importorskip("tree_sitter")
from c_analysis import analyze  # noqa: E402


def program(path):
    with open(os.path.join(ROOT, "tests", "programs", path), encoding="utf-8") as f:
        return f.read()


def lines(code, language="c"):
    return analyze(code, language)["lines"]


def wrap(body):
    return "int main(void) {\n" + body + "\n}\n"


def test_declaration_with_value_is_a_write():
    info = lines(wrap("int x = y + z;"))[2]
    assert info["writes"] == ["x"] and set(info["reads"]) == {"y", "z"}


def test_declaration_without_value_is_not_a_write():
    assert lines(wrap("int x;"))[2]["writes"] == []


def test_compound_assignment_and_increment_read_their_target():
    info = lines(wrap("total += i;\ni++;"))
    assert set(info[2]["reads"]) == {"total", "i"} and info[2]["writes"] == ["total"]
    assert info[3]["reads"] == ["i"] and info[3]["writes"] == ["i"]


def test_memory_writes_are_mutations():
    info = lines(wrap("a[i] = 5;\n*p = 1;\np->next = q;\ns.x = 2;"))
    assert info[2]["mutates"] == ["a[i]"] and info[2]["writes"] == []
    assert info[3]["mutates"] == ["*p"]
    assert info[4]["mutates"] == ["p->next"]
    assert info[5]["mutates"] == ["s.x"]


def test_unsafe_lvalue_falls_back_to_the_variable():
    # a[i++] must never be evaluated by GDB: it would change i
    assert lines(wrap("a[i++] = 0;"))[2]["mutates"] == ["a"]


def test_scanf_writes_through_address():
    info = lines(program("c/08_scanf_input.c"))[6]
    assert info["writes"] == ["age"] and info["mutates"] == ["age"]
    assert "age" not in info["reads"]  # &age is an address, not a read


def test_address_of_is_not_a_read():
    assert lines(wrap("int *p = &x;"))[2]["reads"] == []


def test_strcpy_writes_destination_only():
    info = lines(wrap("strcpy(dst, src);"))[2]
    assert info["mutates"] == ["dst"]


def test_own_function_is_traced_inside_not_at_call():
    info = lines(program("c/06_pointer_swap.c"))
    assert info[11]["mutates"] == []          # swap(&x, &y)
    assert info[5]["mutates"] == ["*a"]       # *a = *b inside swap


def test_control_and_branches():
    info = lines(program("c/02_if_else.c"))
    assert info[6]["header"] == "if"
    assert info[7]["control"] == 6 and info[7]["branch"] is True
    assert info[9]["control"] == 6 and info[9]["branch"] is False
    assert info[11]["control"] is None


def test_guard_clause():
    info = lines(program("c/04_recursion.c"))
    assert info[6]["control"] == 4 and info[6]["branch"] is False


def test_for_loop_header():
    info = lines(program("c/01_loop.c"))
    assert info[5]["header"] == "loop" and info[5]["writes"] == ["i"]
    assert info[6]["control"] == 5


def test_global_write_inside_function():
    result = analyze(program("c/11_global.c"))
    assert result["globals"] == ["count"]
    assert result["lines"][6]["globals"] == ["count"]


def test_declaration_lines():
    declared = analyze(program("c/03_function.c"))["declared"]
    assert declared["square"] == {"n": [3], "result": [4]}


def test_cpp_input_stream_writes():
    info = lines(program("cpp/04_cin_input.cpp"), "cpp")
    assert set(info[7]["writes"]) == {"a", "b"}
    assert "cout" not in info[6]["reads"]


def test_cpp_method_call_mutates_container():
    info = lines(program("cpp/02_vector.cpp"), "cpp")
    assert info[8]["method_mutates"] == ["v"]
    assert info[11]["header"] == "loop" and info[11]["writes"] == ["x"]


def test_cpp_member_write_mutates_this():
    info = lines(program("cpp/05_class.cpp"), "cpp")
    assert info[9]["mutates"] == ["this->value"]
    assert "this" in info[9]["reads"]


def test_cpp_object_declaration_constructs():
    assert lines(program("cpp/02_vector.cpp"), "cpp")[6]["writes"] == ["v"]


def test_input_free_alloc_and_switch_facts():
    info = lines(program("c/12_bst.c"))
    assert info[12]["allocates"] and info[12]["writes"] == ["node"]
    assert info[32]["frees"] == ["old"]
    menu = lines(program("c/13_menu.c"))
    assert menu[7]["input"] and menu[8]["input"] and menu[13]["input"]
    assert menu[11]["header"] == "switch"


def test_cpp_new_and_delete():
    info = lines(wrap("Node *p = new Node();\ndelete p;"), "cpp")
    assert info[2]["allocates"] and info[3]["frees"] == ["p"]
