"""Tests for live runs: the student types into a running C/C++ program
(backend/app.py WebSocket /run, backend/runner/run_program.py).

Run from the kaaran folder:   python -m pytest tests -v
Needs gcc (the program really runs, in local mode); skipped without it.
"""
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

pytest.importorskip("fastapi")
pytest.importorskip("tree_sitter")  # run_program.py shares the tracer's compile step
if not shutil.which("gcc"):
    pytest.skip("gcc not installed", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

import app as backend  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("KAARAN_SANDBOX", "local")
    backend.trace_limiter.seen.clear()
    return TestClient(backend.app)


def program(path):
    with open(os.path.join(ROOT, "tests", "programs", path), encoding="utf-8") as f:
        return f.read()


def collect(ws, until="exit"):
    """Messages until one of type `until` (or an error) arrives."""
    messages = []
    while True:
        message = ws.receive_json()
        messages.append(message)
        if message["type"] in (until, "error", "compile_error", "exit"):
            return messages


def output(messages):
    return "".join(m["data"] for m in messages if m["type"] == "output")


def test_typing_into_a_menu_program(client):
    with client.websocket_connect("/run") as ws:
        ws.send_json({"type": "start", "language": "c", "code": program("c/13_menu.c")})
        assert ws.receive_json() == {"type": "compiled"}
        first = ws.receive_json()
        assert first["type"] == "output" and "1. Add" in first["data"]  # the prompt arrives before any input
        for line in ("1", "5", "2", "3"):
            ws.send_json({"type": "input", "data": line + "\n"})
        messages = collect(ws)
    assert "Total: 5" in output(messages)
    assert messages[-1] == {"type": "exit", "code": 0, "signal": None, "message": None}


def test_compile_error_is_reported(client):
    with client.websocket_connect("/run") as ws:
        ws.send_json({"type": "start", "language": "c", "code": "int main(void) {\n    int x = 5\n    return x;\n}\n"})
        message = ws.receive_json()
    assert message["type"] == "compile_error" and message["error"].startswith("Compile error")
    assert message["error_line"] in (2, 3)


def test_crash_is_reported(client):
    with client.websocket_connect("/run") as ws:
        ws.send_json({"type": "start", "language": "c", "code": program("c/10_segfault.c")})
        messages = collect(ws)
    assert "before" in output(messages)
    assert messages[-1]["type"] == "exit" and messages[-1]["signal"] == "SIGSEGV"


def test_stop_ends_a_waiting_program(client):
    with client.websocket_connect("/run") as ws:
        ws.send_json({"type": "start", "language": "c", "code": program("c/08_scanf_input.c")})
        assert ws.receive_json() == {"type": "compiled"}
        ws.send_json({"type": "stop"})
        messages = collect(ws)
    assert messages[-1] == {"type": "exit", "stopped": True}


def test_end_of_input(client):
    with client.websocket_connect("/run") as ws:
        ws.send_json({"type": "start", "language": "c", "code": program("c/08_scanf_input.c")})
        assert ws.receive_json() == {"type": "compiled"}
        ws.send_json({"type": "eof"})  # scanf gets nothing; the program goes on
        messages = collect(ws)
    assert messages[-1]["type"] == "exit" and messages[-1]["code"] == 0


def test_only_c_and_cpp(client):
    with client.websocket_connect("/run") as ws:
        ws.send_json({"type": "start", "language": "python", "code": "print(1)"})
        message = ws.receive_json()
    assert message["type"] == "error"
