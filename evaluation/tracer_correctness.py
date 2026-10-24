"""Tracer correctness: does tracing change what a program does?

    python evaluation/tracer_correctness.py          (from the kaaran folder)

Each program is run twice: normally (python, or gcc/g++ and the compiled
program) and under Kaaran's tracer, with the same input. The two outputs
must be identical, and an error must be the same kind of error. Programs
that never end are skipped (the tracer stops them on purpose).

C/C++ programs need gcc, g++ and gdb; without them they are skipped.
Writes evaluation/tracer_correctness.md.
"""
import datetime
import glob
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tracer"))
sys.path.insert(0, os.path.join(ROOT, "backend", "runner"))

from tracer import trace as trace_python  # noqa: E402

INPUTS = {
    "13_input.py": "Asha\n19\n", "s16_input.py": "Ravi\n20\n",
    "08_scanf_input.c": "41\n", "04_cin_input.cpp": "3 4\n", "s20_scanf.c": "7 3\n",
    "13_menu.c": "1\n5\n1\n7\n2\n3\n",
}
ENDLESS = {"06_infinite_loop.py", "09_infinite_loop.c"}


def programs():
    patterns = ["tests/programs/*.py", "evaluation/slicing/programs/*.py",
                "tests/programs/c/*.c", "tests/programs/cpp/*.cpp", "evaluation/slicing/programs/*.c"]
    for pattern in patterns:
        yield from sorted(glob.glob(os.path.join(ROOT, pattern)))


def run_python(path, stdin):
    done = subprocess.run([sys.executable, "-I", path], input=stdin.encode(), capture_output=True, timeout=20)
    stderr = done.stderr.decode("utf-8", "replace").strip().splitlines()
    error = stderr[-1].split(":")[0] if done.returncode else None
    return done.stdout.decode("utf-8", "replace").replace("\r\n", "\n"), error


def without_echo(text, stdin):
    """Kaaran echoes what input() reads, like a terminal does; a normal run
    with piped input doesn't. Remove the echoed lines before comparing."""
    position = 0
    for line in stdin.splitlines(keepends=True):
        found = text.find(line, position)
        if found >= 0:
            text = text[:found] + text[found + len(line):]
            position = found
    return text


def run_native(path, stdin):
    from c_tracer import IO_HELPER
    language = "cpp" if path.endswith(".cpp") else "c"
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "prog.exe" if os.name == "nt" else "prog")
        helper = os.path.join(tmp, "kaaran_io.c")
        with open(helper, "w", encoding="utf-8") as f:
            f.write(IO_HELPER)
        compiler = "g++" if language == "cpp" else "gcc"
        # The same unbuffered output as under Kaaran: otherwise a crashing
        # program loses what it printed, because a pipe is fully buffered
        subprocess.run([compiler, "-g", "-O0", path, helper, "-o", exe], check=True, capture_output=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("KAARAN_")}
        done = subprocess.run([exe], input=stdin.encode(), capture_output=True, timeout=20, env=env)
    crashed = done.returncode < 0 or done.returncode > 255  # a signal (Linux) or an exception code (Windows)
    return done.stdout.decode("utf-8", "replace").replace("\r\n", "\n"), "crash" if crashed else None


def check(path):
    name = os.path.basename(path)
    stdin = INPUTS.get(name, "")
    with open(path, encoding="utf-8") as f:
        code = f.read()
    if path.endswith(".py"):
        expected, expected_error = run_python(path, stdin)
        traced = trace_python(code, stdin)
        traced = dict(traced, stdout=without_echo(traced["stdout"], stdin))
        traced_error = traced["error"].split(":")[0] if traced["error"] else None
    else:
        from c_tracer import trace as trace_c
        expected, expected_error = run_native(path, stdin)
        traced = trace_c(code, "cpp" if path.endswith(".cpp") else "c", stdin)
        traced_error = "crash" if traced["error"] and "SIG" in traced["error"] else traced["error"]
    same_output = traced["stdout"] == expected
    same_error = traced_error == expected_error
    return {"program": os.path.relpath(path, ROOT).replace("\\", "/"), "steps": len(traced["steps"]),
            "ok": same_output and same_error and "internal_error" not in traced,
            "note": "" if same_output else f"output differs: {traced['stdout'][:40]!r} vs {expected[:40]!r}"
            + ("" if same_error else f" error {traced_error} vs {expected_error}")}


def main():
    can_c = all(shutil.which(t) for t in ("gcc", "g++", "gdb"))
    rows, skipped = [], []
    for path in programs():
        name = os.path.basename(path)
        if name in ENDLESS:
            skipped.append(f"{name} (never ends, by design)")
        elif not path.endswith(".py") and not can_c:
            skipped.append(f"{name} (no gcc/gdb)")
        else:
            rows.append(check(path))
    ok = sum(r["ok"] for r in rows)
    lines = [
        "# Tracer correctness (generated by evaluation/tracer_correctness.py)",
        "",
        f"Run on {datetime.date.today().isoformat()}, Python {platform.python_version()}, {platform.system()}.",
        "",
        f"**{ok}/{len(rows)} programs** print exactly the same output (and fail with the same kind of error) "
        "when traced as when run normally." + (f" Skipped: {', '.join(skipped)}." if skipped else ""),
        "",
        "Two choices are made the same in both runs on purpose: Kaaran's echo of typed input is removed "
        "before comparing (a terminal shows it, a pipe doesn't), and the normal C/C++ build uses Kaaran's "
        "unbuffered output (otherwise a crashing program loses its last output in a pipe's buffer).",
        "",
        "| Program | Steps traced | Same behaviour | Note |",
        "|---|---|---|---|",
    ]
    lines += [f"| {r['program']} | {r['steps']} | {'yes' if r['ok'] else 'NO'} | {r['note']} |" for r in rows]
    report = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "tracer_correctness.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(report)
    print(report)


if __name__ == "__main__":
    main()
