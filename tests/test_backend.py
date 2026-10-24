"""Tests for the backend API (backend/app.py), with the sandbox replaced by
a stub. The real sandbox is exercised in CI (the `sandbox` job).

Run from the kaaran folder:   python -m pytest tests -v
Skipped if FastAPI isn't installed (pip install -r backend/requirements.txt).
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import app as backend  # noqa: E402
import sandbox  # noqa: E402

TRACE = {"language": "c", "code": "int main(void){return 0;}", "steps": [], "stdout": "",
         "error": None, "error_line": None, "truncated": False}


@pytest.fixture
def client(monkeypatch):
    calls = []

    def fake_run(language, code, stdin=""):
        calls.append((language, code, stdin))
        return dict(TRACE, language=language, code=code)

    monkeypatch.setattr(sandbox, "run_trace", fake_run)
    backend.trace_limiter.seen.clear()
    test_client = TestClient(backend.app)
    test_client.calls = calls
    return test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json()["ok"] is True


def test_trace_runs_c_in_the_sandbox(client):
    response = client.post("/trace", json={"language": "c", "code": "int main(void){}", "input": "5"})
    assert response.status_code == 200
    assert response.json()["language"] == "c"
    assert client.calls == [("c", "int main(void){}", "5")]


def test_python_is_rejected(client):
    response = client.post("/trace", json={"language": "python", "code": "print(1)"})
    assert response.status_code == 400
    assert "browser" in response.json()["detail"]
    assert client.calls == []


def test_unknown_language_is_rejected(client):
    assert client.post("/trace", json={"language": "java", "code": "x"}).status_code == 422


def test_code_too_long_is_rejected(client):
    response = client.post("/trace", json={"language": "c", "code": "x" * 20_001})
    assert response.status_code == 422


def test_sandbox_failure_is_a_clear_503(client, monkeypatch):
    def broken(*args):
        raise sandbox.SandboxError("Docker isn't installed")

    monkeypatch.setattr(sandbox, "run_trace", broken)
    response = client.post("/trace", json={"language": "cpp", "code": "int main(){}"})
    assert response.status_code == 503 and "Docker" in response.json()["detail"]


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(backend.trace_limiter, "limit", 2)
    codes = [client.post("/trace", json={"language": "c", "code": "int main(){}"}).status_code
             for _ in range(3)]
    assert codes == [200, 200, 429]


def test_cors_and_private_network_preflight(client):
    response = client.options("/trace", headers={
        "Origin": "https://devrajrawat9027562124-web.github.io",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true",
    })
    assert response.headers["access-control-allow-origin"] == "https://devrajrawat9027562124-web.github.io"
    assert response.headers["access-control-allow-private-network"] == "true"


def test_docker_command_is_locked_down():
    command = " ".join(sandbox.docker_command("kaaran-test"))
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--pids-limit 64",
                 "--memory 256m", "no-new-privileges", "--user 10001:10001"):
        assert flag in command
