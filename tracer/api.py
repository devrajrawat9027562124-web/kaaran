"""JSON entry points for the browser worker (Pyodide) and the backend.

Each function takes and returns plain strings and numbers, so JavaScript can
call it directly. The last trace is kept so "Why?" questions can be asked
about it without sending it again.
"""
import json

from tracer import MAX_STEPS, trace
from why import WhyEngine

_engine = None


def run(code, stdin="", max_steps=MAX_STEPS):
    """Trace a Python program and keep it for later questions."""
    result = trace(code, stdin, max_steps)
    _keep(result)
    return json.dumps(result)


def load(trace_json):
    """Ask questions about a trace made elsewhere (the C/C++ backend)."""
    _keep(json.loads(trace_json))


def _keep(result):
    global _engine
    _engine = WhyEngine(result)


def why(step, name, frame_index=-1):
    return json.dumps(_engine.why(step, name, frame_index))


def why_step(step):
    return json.dumps(_engine.why_step(step))


def why_output(line_index):
    return json.dumps(_engine.why_output(line_index))


def explain_all():
    """One plain-language sentence per step, for the step-by-step narration."""
    return json.dumps([_engine.explain_step(n)["text"] for n in sorted(_engine.steps)])
