"""Run the C/C++ tracer where a student's program can't do harm.

KAARAN_SANDBOX=docker (the default): every run gets a fresh container from
the kaaran-runner image (runner/Dockerfile) with
  - no network,
  - 256 MB of memory, one CPU, at most 64 processes,
  - a read-only filesystem except a small /tmp,
  - no Linux capabilities and a non-root user,
and it is removed afterwards.

KAARAN_SANDBOX=local: runs runner/c_tracer.py directly with this machine's
gcc and gdb. Only for developing Kaaran on your own programs: the program
can do anything you can.
"""
import json
import os
import subprocess
import sys
import uuid

RUNNER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner")
IMAGE = os.environ.get("KAARAN_RUNNER_IMAGE", "kaaran-runner")
# The tracer stops itself after KAARAN_TIME_LIMIT seconds (default 15);
# compiling and starting the container get extra time on top
TIMEOUT = float(os.environ.get("KAARAN_TIME_LIMIT", "15")) + 25


class SandboxError(Exception):
    """The program couldn't be run (not: the program had an error)."""


def mode():
    return os.environ.get("KAARAN_SANDBOX", "docker")


def docker_command(name):
    return [
        "docker", "run", "--rm", "-i", "--name", name,
        "--network", "none",
        "--memory", "256m", "--memory-swap", "256m", "--cpus", "1", "--pids-limit", "64",
        "--read-only", "--tmpfs", "/tmp:rw,exec,nosuid,size=32m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "10001:10001",
        IMAGE,
    ]


def run_trace(language, code, stdin=""):
    """Trace a C/C++ program; returns the trace (a dict)."""
    request = json.dumps({"language": language, "code": code, "input": stdin}).encode("utf-8")
    name = f"kaaran-{uuid.uuid4().hex[:12]}"
    if mode() == "local":
        command = [sys.executable, os.path.join(RUNNER_DIR, "c_tracer.py")]
    else:
        command = docker_command(name)
    try:
        done = subprocess.run(command, input=request, capture_output=True, timeout=TIMEOUT,
                              cwd=RUNNER_DIR if mode() == "local" else None)
    except FileNotFoundError:
        raise SandboxError("Docker isn't installed or isn't on PATH. Install Docker and build the "
                           "runner image (see backend/README.md), or set KAARAN_SANDBOX=local for development.")
    except subprocess.TimeoutExpired:
        if mode() == "docker":
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        raise SandboxError("The program took too long to trace.")

    output = done.stdout.decode("utf-8", "replace").strip()
    if not output:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        if "Unable to find image" in done.stderr.decode("utf-8", "replace"):
            raise SandboxError(f"The runner image '{IMAGE}' isn't built. Run: docker build -t {IMAGE} backend/runner")
        raise SandboxError(f"The sandbox failed: {detail[0]}")
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        raise SandboxError("The sandbox returned something that isn't a trace.")


# ---------- Live runs: the student uses the program before it is explained ----------

def live_command(name):
    if mode() == "local":
        return [sys.executable, os.path.join(RUNNER_DIR, "run_program.py")]
    # The same locked-down container, running the program instead of the tracer
    return docker_command(name)[:-1] + ["--entrypoint", "python3", IMAGE, "/app/run_program.py"]


class LiveRun:
    """A program running for the student to type into (runner/run_program.py).

    stdout carries one status line ("KAARAN {...}") and then the program's
    output; stderr ends with "KAARAN-EXIT {...}". The caller reads both
    (backend/app.py does it on threads) and writes input with write().
    """

    def __init__(self, language, code):
        self.name = f"kaaran-{uuid.uuid4().hex[:12]}"
        try:
            self.proc = subprocess.Popen(
                live_command(self.name), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0, cwd=RUNNER_DIR if mode() == "local" else None)
        except FileNotFoundError:
            raise SandboxError("Docker isn't installed or isn't on PATH. Install Docker and build the "
                               "runner image (see backend/README.md), or set KAARAN_SANDBOX=local for development.")
        self.proc.stdin.write((json.dumps({"language": language, "code": code}) + "\n").encode("utf-8"))

    def write(self, text):
        try:
            self.proc.stdin.write(text.encode("utf-8"))
        except (BrokenPipeError, OSError, ValueError):
            pass  # the program already ended

    def close_input(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass

    def stop(self):
        if mode() == "docker":
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        if self.proc.poll() is None:
            self.proc.kill()
