"""Kaaran backend: traces C/C++ programs in a sandbox, and explains steps
with an LLM whose values are checked against the trace.

Python never comes here: it runs in the browser with Pyodide.

    GET  /health
    POST /trace    {"language": "c" | "cpp", "code": "...", "input": "..."}
    WS   /run      run a C/C++ program live, for the student to type into
    POST /explain  the facts of one step (see ExplainRequest) -> explanation

Accounts (optional: the tool works without one), see accounts.py:
    POST /auth/signup {"name", "email", "password"} -> {"token", "user"}
    POST /auth/login  {"email", "password"}         -> {"token", "user"}
    POST /auth/logout, GET /auth/me                    (Authorization: Bearer <token>)
    GET/POST /programs, GET/PUT/DELETE /programs/{id}  the student's saved programs

Run from the backend folder:   uvicorn app:app --port 8000
Settings come from the environment or backend/.env (see .env.example).
"""
import asyncio
import codecs
import json
import os
import threading
import time
from collections import defaultdict, deque
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import accounts  # noqa: E402  (all three read settings loaded above)
import explainer  # noqa: E402
import sandbox  # noqa: E402

MAX_CODE_CHARS = 20_000
MAX_INPUT_CHARS = 10_000
MAX_PARALLEL_RUNS = 4
LIVE_SECONDS = 300          # a live run may last 5 minutes (it mostly waits for typing)
LIVE_OUTPUT_LIMIT = 64_000  # characters printed before a live run is stopped
DEFAULT_ORIGINS = "http://localhost:5173,https://devrajrawat9027562124-web.github.io"
ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]

app = FastAPI(title="Kaaran backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
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
# Logins and signups: slows down guessing passwords
auth_limiter = RateLimiter(limit=int(os.environ.get("AUTH_RATE_LIMIT", "10")), window=60)
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


class SignupRequest(BaseModel):
    # Only upper bounds here; accounts.signup checks the rest with messages for the student
    name: str = Field(max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)


class ProgramBody(BaseModel):
    title: str = Field(max_length=200)
    language: str = Field(max_length=10)
    code: str = Field(max_length=MAX_CODE_CHARS)
    input: str = Field(default="", max_length=MAX_INPUT_CHARS)


def client_address(request: Request):
    return request.client.host if request.client else "unknown"


def session_token(authorization: str | None = Header(default=None)):
    return authorization.removeprefix("Bearer ").strip() if authorization and authorization.startswith("Bearer ") else ""


def current_user(token: str = Depends(session_token)):
    user = accounts.user_for(token)
    if not user:
        raise HTTPException(401, "You're logged out (or your session ended). Log in again.")
    return user


def account_call(function, *args):
    try:
        return function(*args)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e))


@app.get("/health")
def health():
    return {"ok": True, "sandbox": sandbox.mode(), "explainer": explainer.available(), "accounts": True}


# ---------- Accounts and saved programs ----------

@app.post("/auth/signup", status_code=201)
def signup(body: SignupRequest, request: Request):
    if not auth_limiter.allow(client_address(request)):
        raise HTTPException(429, "Too many tries in a minute. Wait a little and try again.")
    token, user = account_call(accounts.signup, body.name, body.email, body.password)
    return {"token": token, "user": user}


@app.post("/auth/login")
def login(body: LoginRequest, request: Request):
    if not auth_limiter.allow(client_address(request)):
        raise HTTPException(429, "Too many tries in a minute. Wait a little and try again.")
    token, user = account_call(accounts.login, body.email, body.password)
    return {"token": token, "user": user}


@app.post("/auth/logout", status_code=204)
def logout(token: str = Depends(session_token)):
    if token:
        accounts.logout(token)
    return Response(status_code=204)


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return user


@app.get("/programs")
def list_programs(user=Depends(current_user)):
    return accounts.list_programs(user["id"])


@app.post("/programs", status_code=201)
def create_program(body: ProgramBody, user=Depends(current_user)):
    return account_call(accounts.create_program, user["id"], body.title, body.language, body.code, body.input)


@app.get("/programs/{program_id}")
def get_program(program_id: int, user=Depends(current_user)):
    return account_call(accounts.get_program, user["id"], program_id)


@app.put("/programs/{program_id}")
def update_program(program_id: int, body: ProgramBody, user=Depends(current_user)):
    return account_call(accounts.update_program, user["id"], program_id, body.title, body.language, body.code,
                        body.input)


@app.delete("/programs/{program_id}", status_code=204)
def delete_program(program_id: int, user=Depends(current_user)):
    account_call(accounts.delete_program, user["id"], program_id)
    return Response(status_code=204)


# ---------- Tracing and explaining ----------


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


@app.websocket("/run")
async def run_live(ws: WebSocket):
    """Run a C/C++ program for the student to type into, before it is explained.

    Browser -> backend: {"type": "start", "language", "code"}, then
        {"type": "input", "data": "5\n"}, {"type": "eof"} (end of input) or {"type": "stop"}.
    Backend -> browser: {"type": "compiled"} or {"type": "compile_error", ...},
        {"type": "output", "data": "..."} as the program prints, and finally
        {"type": "exit", "code", "signal", "message"} or {"type": "error", "message"}.
    """
    origin = ws.headers.get("origin")
    if origin and origin not in ORIGINS:  # CORS doesn't cover WebSockets
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        start = await asyncio.wait_for(ws.receive_json(), timeout=30)
    except Exception:
        await ws.close()
        return
    language, code = start.get("language"), start.get("code")
    if language not in ("c", "cpp") or not isinstance(code, str) or len(code) > MAX_CODE_CHARS:
        await ws.send_json({"type": "error", "message": "Only C and C++ programs (up to 20,000 characters) run here."})
        await ws.close()
        return
    if not trace_limiter.allow(ws.client.host if ws.client else "unknown"):
        await ws.send_json({"type": "error", "message": "Too many runs in a minute. Wait a little and try again."})
        await ws.close()
        return
    async with runs:
        try:
            run = await asyncio.to_thread(sandbox.LiveRun, language, code)
        except sandbox.SandboxError as e:
            await ws.send_json({"type": "error", "message": str(e)})
            await ws.close()
            return
        try:
            await _live_session(ws, run)
        finally:
            await asyncio.to_thread(run.stop)
            try:
                await ws.close()
            except Exception:
                pass


async def _live_session(ws, run):
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()

    def pump(stream, kind):
        # Raw reads return whatever the program printed, so a prompt without
        # a newline ("Enter a number: ") reaches the browser at once
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while chunk := stream.read(4096):
                loop.call_soon_threadsafe(events.put_nowait, (kind, decoder.decode(chunk)))
            loop.call_soon_threadsafe(events.put_nowait, (kind + "-end", decoder.decode(b"", final=True)))
        except (RuntimeError, OSError, ValueError):
            pass  # the session already ended (its event loop or the pipe is closed)

    threading.Thread(target=pump, args=(run.proc.stdout, "out"), daemon=True).start()
    threading.Thread(target=pump, args=(run.proc.stderr, "err"), daemon=True).start()

    deadline = loop.time() + LIVE_SECONDS
    compiled, pending, errors, printed, ended = None, "", "", 0, set()
    receive = asyncio.create_task(ws.receive_json())
    event = asyncio.create_task(events.get())
    try:
        while len(ended) < 2:
            done, _ = await asyncio.wait({receive, event}, timeout=max(0.0, deadline - loop.time()),
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                await ws.send_json({"type": "error", "message": f"Stopped after {LIVE_SECONDS // 60} minutes."})
                return
            if receive in done:
                try:
                    message = receive.result()
                except Exception:
                    return  # the browser went away
                if message.get("type") == "input":
                    run.write(str(message.get("data", ""))[:2000])
                elif message.get("type") == "eof":
                    run.close_input()
                elif message.get("type") == "stop":
                    await ws.send_json({"type": "exit", "stopped": True})
                    return
                receive = asyncio.create_task(ws.receive_json())
            if event in done:
                kind, text = event.result()
                event = asyncio.create_task(events.get())
                if kind == "err":
                    errors += text
                elif kind.endswith("-end"):
                    ended.add(kind)
                elif compiled is None:  # the first line says whether it compiled
                    pending += text
                    if "\n" not in pending:
                        continue
                    line, text = pending.split("\n", 1)
                    status = json.loads(line.removeprefix("KAARAN ").strip() or "{}") if line.startswith("KAARAN") else {}
                    compiled = bool(status.get("compiled"))
                    if not compiled:
                        await ws.send_json({"type": "compile_error", **status})
                        return
                    await ws.send_json({"type": "compiled"})
                if kind == "out" and compiled and text:
                    printed += len(text)
                    if printed > LIVE_OUTPUT_LIMIT:
                        await ws.send_json({"type": "error",
                                            "message": "The program printed too much (an endless loop?) and was stopped."})
                        return
                    # Windows programs print \r\n; the browser wants \n
                    await ws.send_json({"type": "output", "data": text.replace("\r\n", "\n")})
        exit_line = next((l for l in errors.splitlines() if l.startswith("KAARAN-EXIT ")), None)
        if exit_line:
            await ws.send_json({"type": "exit", **json.loads(exit_line.removeprefix("KAARAN-EXIT "))})
        else:
            detail = errors.strip().splitlines()[-1:] or ["no details"]
            await ws.send_json({"type": "error", "message": f"The program couldn't run: {detail[0]}"})
    finally:
        receive.cancel()
        event.cancel()
