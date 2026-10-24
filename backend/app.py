"""Kaaran backend: traces C/C++ programs in a sandbox, and explains steps
with an LLM whose values are checked against the trace.

Python never comes here: it runs in the browser with Pyodide.

    GET  /health
    POST /trace    {"language": "c" | "cpp", "code": "...", "input": "..."}
    POST /explain  the facts of one step (see ExplainRequest) -> explanation

Run from the backend folder:   uvicorn app:app --port 8000
Settings come from the environment or backend/.env (see .env.example).
"""
import asyncio
import os
import time
from collections import defaultdict, deque
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import explainer  # noqa: E402  (both read settings loaded above)
import sandbox  # noqa: E402

MAX_CODE_CHARS = 20_000
MAX_INPUT_CHARS = 10_000
MAX_PARALLEL_RUNS = 4
DEFAULT_ORIGINS = "http://localhost:5173,https://devrajrawat9027562124-web.github.io"

app = FastAPI(title="Kaaran backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def allow_private_network(request: Request, call_next):
    # Lets the public demo page (GitHub Pages) call a backend on your own
    # machine (localhost): Chrome asks first with this preflight header.
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


class RateLimiter:
    """At most `limit` requests per `window` seconds from one address."""

    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self.seen = defaultdict(deque)

    def allow(self, key):
        now = time.monotonic()
        times = self.seen[key]
        while times and now - times[0] > self.window:
            times.popleft()
        if len(times) >= self.limit:
            return False
        times.append(now)
        return True


trace_limiter = RateLimiter(limit=int(os.environ.get("TRACE_RATE_LIMIT", "20")), window=60)
explain_limiter = RateLimiter(limit=int(os.environ.get("EXPLAIN_RATE_LIMIT", "10")), window=60)
runs = asyncio.Semaphore(MAX_PARALLEL_RUNS)
explanations = explainer.Explainer()


class TraceRequest(BaseModel):
    language: Literal["python", "c", "cpp"]
    code: str = Field(max_length=MAX_CODE_CHARS)
    input: str = Field(default="", max_length=MAX_INPUT_CHARS)


class WhyFacts(BaseModel):
    question: str = Field(max_length=500)
    summary: str = Field(max_length=4000)
    chain: list[str] = Field(default_factory=list, max_length=40)


class ExplainRequest(BaseModel):
    """One step, as the frontend reads it from the trace."""
    language: Literal["python", "c", "cpp"]
    code: str = Field(max_length=MAX_CODE_CHARS)
    step: int
    line: int
    event: str = Field(max_length=20)
    narration: str = Field(max_length=2000)
    before: dict[str, dict[str, str]] = Field(max_length=50)   # frame -> variables
    after: dict[str, str] | None = None
    output: str = Field(default="", max_length=2000)
    why: WhyFacts | None = None


def client_address(request: Request):
    return request.client.host if request.client else "unknown"


@app.get("/health")
def health():
    return {"ok": True, "sandbox": sandbox.mode(), "explainer": explainer.available()}


@app.post("/explain")
async def explain(body: ExplainRequest, request: Request):
    if not explainer.available():
        raise HTTPException(503, "The explainer isn't set up: add ANTHROPIC_API_KEY to backend/.env "
                                 "and restart the backend.")
    if not explain_limiter.allow(client_address(request)):
        raise HTTPException(429, "Too many explanations in a minute. Wait a little and try again.")
    try:
        return await asyncio.to_thread(explanations.explain, body.model_dump())
    except explainer.ExplainerError as e:
        raise HTTPException(502, str(e))


@app.post("/trace")
async def trace(body: TraceRequest, request: Request):
    if body.language == "python":
        raise HTTPException(400, "Python runs in your browser; the backend only runs C and C++.")
    if not trace_limiter.allow(client_address(request)):
        raise HTTPException(429, "Too many runs in a minute. Wait a little and try again.")
    async with runs:
        try:
            return await asyncio.to_thread(sandbox.run_trace, body.language, body.code, body.input)
        except sandbox.SandboxError as e:
            raise HTTPException(503, str(e))
