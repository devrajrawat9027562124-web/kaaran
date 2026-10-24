"""Run a C/C++ program for the student to use, before Kaaran explains it.

The student types input while the program runs, as in a terminal. Kaaran
then traces the same program with exactly that input (c_tracer.py), so the
explanation follows the run the student just saw.

Protocol (backend/sandbox.py speaks it):
  1. The first line on stdin is JSON: {"language": "c" | "cpp", "code": "..."}.
  2. The program is compiled, and one line "KAARAN {...}" on stdout reports
     the result: {"compiled": true} or the compile error.
  3. The program runs. The rest of stdin is its input; what it prints (and
     its errors) come back on stdout.
  4. When it ends, one line "KAARAN-EXIT {...}" goes to stderr: the exit
     code, and the signal if it crashed.

It runs inside the same sandbox container as the tracer.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

from c_tracer import IO_HELPER, SIGNALS, _compile, _write

# Windows reports crashes as exception codes instead of signals
WINDOWS_CRASHES = {0xC0000005: "SIGSEGV", 0xC00000FD: "SIGSEGV", 0xC0000094: "SIGFPE", 0xC0000409: "SIGABRT"}


def read_first_line():
    """Read the JSON line byte by byte, so none of the program's input
    (which may follow right after it) is swallowed into a buffer."""
    data = b""
    while not data.endswith(b"\n"):
        byte = os.read(0, 1)
        if not byte:
            break
        data += byte
    return data


def main():
    request = json.loads(read_first_line() or b"{}")
    language = request.get("language", "c")
    workdir = tempfile.mkdtemp(prefix="kaaran-run-")
    try:
        name = "prog.cpp" if language == "cpp" else "prog.c"
        paths = {
            "source": os.path.join(workdir, name),
            "helper": os.path.join(workdir, "kaaran_io.c"),
            "exe": os.path.join(workdir, "prog.exe" if os.name == "nt" else "prog"),
        }
        _write(paths["source"], request.get("code", ""))
        _write(paths["helper"], IO_HELPER)  # unbuffered output, so prompts appear at once
        result = {}
        compiled = _compile(language, paths, name, result)
        status = {"compiled": compiled}
        status.update({k: result[k] for k in ("error", "error_line", "compile_output") if k in result})
        os.write(1, ("KAARAN " + json.dumps(status) + "\n").encode("utf-8"))
        if not compiled:
            return

        # No KAARAN_STDIN/STDOUT: the program reads and writes the pipes directly
        env = {k: v for k, v in os.environ.items() if not k.startswith("KAARAN_")}
        done = subprocess.run([paths["exe"]], stderr=subprocess.STDOUT, env=env, cwd=workdir)
        code = done.returncode
        crash = None
        if code < 0:
            crash = signal.Signals(-code).name
        elif (code & 0xFFFFFFFF) in WINDOWS_CRASHES:
            crash = WINDOWS_CRASHES[code & 0xFFFFFFFF]
        exit_status = {"code": code if not crash else None, "signal": crash,
                       "message": SIGNALS.get(crash, crash) if crash else None}
        os.write(2, ("KAARAN-EXIT " + json.dumps(exit_status) + "\n").encode("utf-8"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
