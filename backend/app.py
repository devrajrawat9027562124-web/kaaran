"""Kaaran backend: traces C/C++ programs in a sandbox (and, later, explains
steps with an LLM).

Python never comes here: it runs in the browser with Pyodide.

    GET  /health
    POST /trace   {"language": "c" | "cpp", "code": "...", "input": "..."}

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

import sandbox  # noqa: E402  (reads settings loaded above)

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
runs = asyncio.Semaphore(MAX_PARALLEL_RUNS)


class TraceRequest(BaseModel):
    language: Literal["python", "c", "cpp"]
    code: str = Field(max_length=MAX_CODE_CHARS)
    input: str = Field(default="", max_length=MAX_INPUT_CHARS)


def client_address(request: Request):
    return request.client.host if request.client else "unknown"


@app.get("/health")
def health():
    return {"ok": True, "sandbox": sandbox.mode()}


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
