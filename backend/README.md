# Kaaran backend

Python programs never come here: they run in the browser. The backend traces **C and C++** programs, runs the LLM explainer, and keeps the optional student accounts.

```
backend/
  app.py           FastAPI app: GET /health, POST /trace, POST /explain,
                   WS /run (a program running live, for the student to type into)
  sandbox.py       runs the tracer in a Docker container (or locally, for development)
  accounts.py      optional student accounts and saved programs (SQLite, scrypt);
                   POST /auth/signup, /auth/login, /auth/logout, GET /auth/me,
                   GET/POST /programs, GET/PUT/DELETE /programs/{id}
  runner/          the C/C++ tracer, which runs inside the sandbox
    c_tracer.py    compile with -g -O0, step with GDB, write the trace JSON
    c_analysis.py  reads/writes/control per line, with tree-sitter
    mi.py          talks to GDB through its machine interface (GDB/MI)
    run_program.py compiles and runs a program live (the Terminal), before it is explained
    Dockerfile     the sandbox image: Debian, gcc, g++, gdb, python3
```

## Run it

```
cd backend
python -m venv .venv
.venv\Scripts\activate            (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            (then edit .env)
uvicorn app:app --port 8000
```

### With Docker (safe, the default)

```
docker build -t kaaran-runner backend/runner      (from the kaaran folder)
```

`KAARAN_SANDBOX=docker` (in `.env`) starts one container per run.

### Without Docker (development only)

Set `KAARAN_SANDBOX=local` to run `runner/c_tracer.py` directly. You need `gcc`, `g++` and `gdb` on your PATH, and `pip install -r runner/requirements.txt`. The program runs with **your** permissions, so use this only for your own code.

## Security model

Running a stranger's C program is dangerous: it can read files, open network connections, fork-bomb, or fill memory. In Docker mode each run gets a fresh container:

| Limit | Docker option | Stops |
|---|---|---|
| No network | `--network none` | sending data out, attacking other machines |
| 256 MB memory, no swap | `--memory 256m --memory-swap 256m` | eating the server's memory |
| 1 CPU | `--cpus 1` | starving other users |
| 64 processes | `--pids-limit 64` | fork bombs |
| Read-only filesystem, 32 MB `/tmp` | `--read-only --tmpfs /tmp` | changing the image, filling the disk |
| No capabilities, no privilege gain, user 10001 | `--cap-drop ALL --security-opt no-new-privileges --user 10001:10001` | root-level actions |
| Time | tracer stops after 15 s / 1000 steps; container killed after 40 s | endless programs |

The API itself limits code to 20,000 characters, runs to 20 per minute per address (`TRACE_RATE_LIMIT`), and at most 4 at once.

Known gaps (fine for a classroom tool, not for a public service at scale): there's no authentication, the rate limit is per process and in memory, and GDB's ptrace runs under Docker's default seccomp profile rather than a custom one.

## Accounts

Accounts are optional and stored in `backend/kaaran.db` (SQLite, created on first use, ignored by git; `KAARAN_DB` to move it). Passwords are kept only as salted scrypt hashes, and session tokens only as SHA-256 hashes; tokens last `KAARAN_SESSION_DAYS` (14). Logins and signups are limited to `AUTH_RATE_LIMIT` (10) a minute per address. There is no email verification or password reset. Details and trade-offs: `docs/design.md`, section 6.

Don't share `kaaran.db`: it holds students' emails and their saved programs.
