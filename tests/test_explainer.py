"""Tests for the LLM explainer (backend/explainer.py) with a fake Claude client:
no network, no API key, no cost.

Run from the kaaran folder:   python -m pytest tests -v
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

pytest.importorskip("anthropic")
pytest.importorskip("fastapi")
import explainer  # noqa: E402

FACTS = {
    "language": "python",
    "code": "total = 0\nfor i in range(3):\n    total += i\nprint(total)\n",
    "step": 7,
    "line": 3,
    "event": "line",
    "narration": "Line 3 ran: set total = 3 (using i = 2, total = 1).",
    "before": {"main program": {"total": "1", "i": "2"}},
    "after": {"total": "3", "i": "2"},
    "output": "",
    "why": {
        "question": "Why is total = 3?",
        "summary": "total = 3 because line 3 (`total += i`) updated it, using i = 2, total = 1.",
        "chain": ["step 5, line 3: set total = 1 (using i = 1, total = 0)"],
    },
}


class FakeClient:
    """Answers with the queued replies, recording each request."""

    def __init__(self, *replies, stop_reason="end_turn"):
        self.replies = list(replies)
        self.requests = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            model=kwargs["model"],
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=json.dumps(reply))],
        )


def answer(text, *values):
    return {"explanation": text, "mentioned_values": [{"name": n, "value": v} for n, v in values]}


def test_correct_values_are_verified():
    client = FakeClient(answer("total grew from 1 to 3 by adding i.", ("total", "1"), ("total", "3"), ("i", "2")))
    result = explainer.Explainer(client).explain(FACTS)
    assert result["verified"] and result["problems"] == [] and not result["retried"]


def test_wrong_value_gets_one_retry():
    client = FakeClient(answer("i is 3.", ("i", "3")), answer("i is 2.", ("i", "2")))
    result = explainer.Explainer(client).explain(FACTS)
    assert result["verified"] and result["retried"]
    assert len(client.requests) == 2
    assert "i = 3" in client.requests[1]["messages"][0]["content"]  # feedback names the wrong value


def test_still_wrong_after_retry_is_flagged():
    client = FakeClient(answer("i is 3.", ("i", "3")), answer("i is 5.", ("i", "5")))
    result = explainer.Explainer(client).explain(FACTS)
    assert not result["verified"]
    problem = result["problems"][0]
    assert problem["name"] == "i" and problem["value"] == "5"
    assert problem["trace_has"] == ["1", "2"]  # i = 1 is in the Why chain, i = 2 now


def test_quotes_and_spaces_dont_matter():
    facts = dict(FACTS, before={"main program": {"kind": "'odd'"}}, after=None, why=None)
    assert explainer.validate([{"name": "kind", "value": "odd"}], facts) == []


def test_values_from_the_why_chain_count():
    assert explainer.validate([{"name": "total", "value": "0"}], FACTS) == []


def test_unknown_variable_is_a_problem():
    problems = explainer.validate([{"name": "count", "value": "3"}], FACTS)
    assert problems and problems[0]["trace_has"] == []


def test_answers_are_cached():
    client = FakeClient(answer("ok", ("i", "2")))
    explain = explainer.Explainer(client)
    first, second = explain.explain(FACTS), explain.explain(FACTS)
    assert not first["cached"] and second["cached"]
    assert len(client.requests) == 1


def test_refusal_is_reported():
    client = FakeClient(answer("", ), stop_reason="refusal")
    with pytest.raises(explainer.ExplainerError):
        explainer.Explainer(client).explain(FACTS)


def test_request_shape(monkeypatch):
    monkeypatch.delenv("KAARAN_MODEL", raising=False)
    client = FakeClient(answer("ok", ("i", "2")))
    explainer.Explainer(client).explain(FACTS)
    request = client.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in request["betas"]
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["effort"] == "low"
    prompt = request["messages"][0]["content"]
    assert "  3 |     total += i" in prompt          # numbered program
    assert "line 3 `total += i`" in prompt
    assert "in main program: total = 1, i = 2" in prompt
    assert "Why is total = 3?" in prompt


def test_endpoint_without_key_explains_setup(monkeypatch):
    from fastapi.testclient import TestClient
    import app as backend
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = TestClient(backend.app).post("/explain", json=FACTS)
    assert response.status_code == 503 and "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_endpoint_with_fake_client(monkeypatch):
    from fastapi.testclient import TestClient
    import app as backend
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(backend, "explanations", explainer.Explainer(FakeClient(answer("ok", ("i", "2")))))
    backend.explain_limiter.seen.clear()
    response = TestClient(backend.app).post("/explain", json=FACTS)
    assert response.status_code == 200 and response.json()["verified"] is True
