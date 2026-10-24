"""Kaaran C/C++ tracer: compile a program, step through it with GDB, and
record a trace in the same format as the Python tracer (docs/trace-format.md).

Usage:  echo '{"language": "c", "code": "...", "input": "5"}' | python c_tracer.py

It runs inside the sandbox container (backend/runner/Dockerfile), which is
what makes running a stranger's C code acceptable. Outside it, use it only
on your own programs.

How it works: the program is compiled with debug info (-g -O0) and run under
GDB, which is driven through its machine interface (mi.py). After every
`step`, the tracer reads the call stack and variables and records a step.
Calls and returns are found by watching the stack grow and shrink, so the
events match Python's (call, line..., return).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from c_analysis import analyze
from mi import GDB, MIError, MITimeout

MAX_STEPS = 1000
TIME_LIMIT = 15.0        # seconds for the whole trace
STEP_TIMEOUT = 3.0       # seconds for one `step` (a single line that never ends)
COMPILE_TIMEOUT = 20
MAX_VALUE_CHARS = 200

# Linked into every program: reads input from a file, writes output to a
# file without buffering (so each step sees what was printed so far). The
# file names come from the environment, so no shell is involved.
IO_HELPER = r"""
#include <stdio.h>
#include <stdlib.h>
__attribute__((constructor)) static void kaaran_io(void) {
    const char *in = getenv("KAARAN_STDIN"), *out = getenv("KAARAN_STDOUT");
    if (in) freopen(in, "r", stdin);
    if (out) { freopen(out, "a", stdout); freopen(out, "a", stderr); }
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}
"""

SIGNALS = {
    "SIGSEGV": "Segmentation fault: the program used memory it doesn't own (a bad pointer or array index)",
    "SIGFPE": "Arithmetic error (for example, division by zero)",
    "SIGABRT": "The program aborted (for example, a failed assert)",
    "SIGBUS": "Bus error: a bad memory access",
}

HEX = re.compile(r"0x[0-9a-fA-F]+")


def trace(code, language="c", stdin="", max_steps=MAX_STEPS, time_limit=TIME_LIMIT):
    result = {"language": language, "code": code, "steps": [], "stdout": "",
              "error": None, "error_line": None, "truncated": False}
    analysis = analyze(code, language)
    with tempfile.TemporaryDirectory(prefix="kaaran-") as tmp:
        name = "prog.cpp" if language == "cpp" else "prog.c"
        paths = {
            "source": os.path.join(tmp, name),
            "helper": os.path.join(tmp, "kaaran_io.c"),
            "exe": os.path.join(tmp, "prog.exe" if os.name == "nt" else "prog"),
            "stdin": os.path.join(tmp, "stdin.txt"),
            "stdout": os.path.join(tmp, "stdout.txt"),
        }
        _write(paths["source"], code)
        _write(paths["helper"], IO_HELPER)
        _write(paths["stdin"], stdin)
        _write(paths["stdout"], "")

        if not _compile(language, paths, name, result):
            return result
        Stepper(paths, name, analysis, result, max_steps, time_limit).run()
    return result


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _compile(language, paths, name, result):
    compiler = os.environ.get("KAARAN_CXX", "g++") if language == "cpp" else os.environ.get("KAARAN_CC", "gcc")
    command = [compiler, "-g", "-O0", "-fno-omit-frame-pointer", paths["source"], paths["helper"],
               "-o", paths["exe"]]
    if language == "c":
        command.append("-lm")
    try:
        done = subprocess.run(command, capture_output=True, timeout=COMPILE_TIMEOUT)
    except FileNotFoundError:
        result["error"] = f"Compiler not found: {compiler}"
        return False
    except subprocess.TimeoutExpired:
        result["error"] = "Compiling took too long"
        return False
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    # Show the student's file name, not the temporary folder
    output = output.replace(paths["source"], name).replace(os.path.dirname(paths["source"]) + os.sep, "")
    if output.strip():
        result["compile_output"] = output.strip()
    if done.returncode != 0:
        match = re.search(rf"{re.escape(name)}:(\d+):\d+: (?:fatal )?error: (.*)", output)
        result["error"] = f"Compile error: {match.group(2)}" if match else "Compile error"
        result["error_line"] = int(match.group(1)) if match else None
        return False
    return True


class Frame:
    """One call of a function in the student's program, as Kaaran tracks it."""

    def __init__(self, frame_id, func):
        self.frame_id = frame_id
        self.func = func
        self.executed = set()    # lines that finished running in this call
        self.entry_line = None   # where the call started
        self.current = None      # line it is on now (None until its first line step)
        self.on_return = False   # its current line is a return statement
        self.returning = False   # that return statement finished: only cleanup is left
        self.addresses = {}      # variable -> (address, size), fixed for the call
        self.snapshot = None     # the stack when this frame last stopped
        self.heap = {}


class Stepper:
    def __init__(self, paths, name, analysis, result, max_steps, time_limit):
        self.paths = paths
        self.name = name
        self.analysis = analysis
        self.lines = analysis["lines"]
        self.result = result
        self.steps = result["steps"]
        self.max_steps = max_steps
        self.deadline = time.monotonic() + time_limit
        self.frames = []            # shadow stack, outermost first
        self.next_frame_id = 1
        self.call_step = {}         # frame_id -> its "call" step
        self.last_at_line = {}      # (frame_id, line) -> latest step there
        self.last_line_step = {}    # frame_id -> latest "line" step
        self.global_addresses = {}
        self.gdb = None

    # ---------- Running ----------

    def run(self):
        env = dict(os.environ, KAARAN_STDIN=self.paths["stdin"], KAARAN_STDOUT=self.paths["stdout"])
        self.gdb = GDB(self.paths["exe"], gdb=os.environ.get("KAARAN_GDB", "gdb"),
                       env=env, cwd=os.path.dirname(self.paths["exe"]))
        try:
            self._setup()
            stop = self.gdb.wait_stopped(STEP_TIMEOUT * 3)
            while self._handle(stop):
                if len(self.steps) >= self.max_steps:
                    self._stop_early(f"Stopped after {self.max_steps} steps (infinite loop?)")
                    break
                if time.monotonic() > self.deadline:
                    self._stop_early("Stopped: the program took too long (infinite loop?)")
                    break
                self.gdb.command(self._next_command())
                stop = self.gdb.wait_stopped(STEP_TIMEOUT)
        except MITimeout:
            line = self.frames[-1].current if self.frames else None
            self._stop_early(f"Stopped: line {line} kept running without finishing (infinite loop?)",
                             line)
        except MIError as e:
            if not self.result["error"]:
                self.result["error"] = f"Kaaran couldn't run this program under GDB: {e}"
        finally:
            self.result["stdout"] = self._stdout()
            self.gdb.close()

    def _setup(self):
        gdb = self.gdb
        for setting in ("confirm off", "pagination off", "print pretty off", "print null-stop on",
                        "print elements 50", "print repeats 10", "disable-randomization off",
                        "startup-with-shell off"):
            gdb.try_command(f"-gdb-set {setting}")
        # Don't step into the C++ standard library's headers
        for depth in range(1, 6):
            gdb.try_command(f'-interpreter-exec console "skip -gfi /usr/include/{"*/" * (depth - 1)}*"')
        gdb.command("-break-insert main")
        gdb.command("-exec-run")

    def _next_command(self):
        """Step to the next line; at a function's closing brace, finish it
        instead, which is how GDB reports the value it returns."""
        if len(self.frames) > 1:
            frame = self.frames[-1]
            ends = self.analysis["ends"]
            end = ends.get(frame.func) or ends.get(frame.func.split("::")[-1])
            if frame.returning or frame.current == end:
                return "-exec-finish"
        return "-exec-step"

    def _stop_early(self, message, line=None):
        self.result["error"] = message
        self.result["truncated"] = True
        if line:
            self.result["error_line"] = line

    def _stdout(self):
        try:
            with open(self.paths["stdout"], encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    # ---------- One stop ----------

    def _handle(self, stop, back_mid_line=False):
        """Record what this stop means. False when the program has ended."""
        reason = stop.get("reason", "")
        if reason.startswith("exited"):
            self._finish(stop)
            return False
        if reason == "signal-received":
            self._crash(stop)
            return False

        user = self._user_frames()
        if not user:
            return True  # library code without line info (or after main): keep stepping
        if user[0]["level"] != "0":
            self.gdb.command("-exec-finish")  # stepped into a header (C++ library code)
            return self._handle(self.gdb.wait_stopped(STEP_TIMEOUT), back_mid_line=True)

        depth = len(user)
        line = int(user[0]["line"])
        returned = depth < len(self.frames)
        value = stop.get("return-value") if reason == "function-finished" else None
        while depth < len(self.frames):
            self._record_return(self.frames.pop(), value)
            value = None
        if (returned or back_mid_line) and self.frames and line == self.frames[-1].current:
            return True  # back in the middle of a line that hasn't finished: it continues
        if depth == len(self.frames) and self.frames and self.frames[-1].on_return:
            # Its return statement has finished (a `return f(x);` line first
            # runs the call). What's left is cleanup, such as destructors
            # freeing memory, so the values are no longer meaningful.
            self.frames[-1].returning = True
            return True
        if depth > len(self.frames):
            for frame in user[:depth - len(self.frames)][::-1]:
                self._push(frame, stop)
        self._record_line(line, user)
        return True

    def _user_frames(self):
        """Frames of the student's program, innermost first."""
        frames = self.gdb.command("-stack-list-frames")["stack"]
        return [f for f in frames if os.path.basename(f.get("file", "")).lower() == self.name]

    def _push(self, gdb_frame, stop):
        frame = Frame(self.next_frame_id, gdb_frame.get("func", "?"))
        frame.entry_line = int(gdb_frame.get("line", 0))
        self.next_frame_id += 1
        caller = self.frames[-1] if self.frames else None
        self.frames.append(frame)
        if caller is None:
            return  # main: the program starting isn't a call step
        args = [a["name"] for a in stop.get("frame", {}).get("args", [])]
        stack, heap = self._snapshot()
        number = len(self.steps) + 1
        self.steps.append(self._step(number, frame.entry_line, "call", frame, stack, heap, writes=args,
                                     control_parent=self.last_line_step.get(caller.frame_id)))
        self.call_step[frame.frame_id] = number

    def _record_line(self, line, user):
        frame = self.frames[-1]
        if frame.current is not None:
            frame.executed.add(frame.current)  # the previous line finished
        frame.current = line
        for shadow, gdb_frame in zip(reversed(self.frames), user):
            shadow.current = int(gdb_frame["line"])
        stack, heap = self._snapshot()
        info = self.lines.get(line)
        number = len(self.steps) + 1
        step = self._step(number, line, "line", frame, stack, heap)
        if info:
            step["reads"] = list(info["reads"])
            step["writes"] = list(info["writes"])
            step["mutates"] = self._mutated(info)
            for key in ("globals",):
                if info[key]:
                    step[key] = list(info[key])
            if info["branch"] is not None:
                step["branch"] = info["branch"]
            if info["header"]:
                step["header"] = info["header"]
            frame.on_return = info["returns"]
            control_line = info["control"]
        else:
            control_line = None
        if control_line is not None:
            step["control_parent"] = self.last_at_line.get((frame.frame_id, control_line))
        else:
            step["control_parent"] = self.call_step.get(frame.frame_id)
        self.last_at_line[(frame.frame_id, line)] = number
        self.last_line_step[frame.frame_id] = number
        frame.snapshot, frame.heap = stack, heap
        self.steps.append(step)

    def _record_return(self, frame, value=None):
        """A function returned. `value` comes from GDB's `finish`; without it
        (no stop at the closing brace) the value is left out, never guessed."""
        if frame.snapshot is None:
            return
        step = self._step(len(self.steps) + 1, frame.current, "return", frame,
                          frame.snapshot, frame.heap)
        if value is not None:
            step["return_value"] = _display(value, "")
        self.steps.append(step)

    def _finish(self, stop):
        code = stop.get("exit-code")
        self.result["exit_code"] = int(code, 8) if code else 0
        while len(self.frames) > 1:
            self._record_return(self.frames.pop())
        if self.frames:
            main = self.frames.pop()
            if main.snapshot is not None:
                step = self._step(len(self.steps) + 1, main.current, "return", main,
                                  main.snapshot, main.heap)
                step["return_value"] = str(self.result["exit_code"])
                self.steps.append(step)

    def _crash(self, stop):
        name = stop.get("signal-name", "signal")
        message = SIGNALS.get(name, stop.get("signal-meaning", name))
        user = self._user_frames()
        line = int(user[0]["line"]) if user else None
        self.result["error"] = f"{message} ({name})"
        self.result["error_line"] = line
        if self.frames and line:
            frame = self.frames[-1]
            stack, heap = self._snapshot()
            step = self._step(len(self.steps) + 1, line, "exception", frame, stack, heap)
            step["exception"] = self.result["error"]
            self.steps.append(step)

    def _step(self, number, line, event, frame, stack, heap, writes=None, control_parent=None):
        return {
            "step": number,
            "line": line,
            "event": event,
            "frame_id": frame.frame_id,
            "locals": stack[-1]["locals"],
            "stack": stack,
            "heap": heap,
            "stdout": self._stdout(),
            "reads": [],
            "writes": writes or [],
            "mutates": [],
            "control_parent": control_parent,
        }

    # ---------- Variables ----------

    def _snapshot(self):
        """Every frame's variables (outermost first), plus a globals frame."""
        stack, regions, values = [], [], {}
        globals_frame = self._globals(regions)
        if globals_frame:
            stack.append(globals_frame)
        depth = len(self.frames)
        for index, frame in enumerate(self.frames):
            level = depth - 1 - index
            stack.append(self._frame_snapshot(frame, level, regions, values))
        # Pointers and references: refer to the variable that holds the address
        for entry in stack:
            for name, raw in entry.pop("_pointers", {}).items():
                entry["refs"][name] = _owner(raw, regions)
        heap = {}
        for entry in stack:
            for name, ref in entry["refs"].items():
                if ref not in heap and ref in values:
                    heap[ref] = values[ref]
        return stack, heap

    def _frame_snapshot(self, frame, level, regions, values):
        try:
            variables = self.gdb.command(
                f"-stack-list-variables --thread 1 --frame {level} --simple-values")["variables"]
        except MIError:
            variables = []
        declared = self._declared(frame.func)
        locals_, types, refs, pointers = {}, {}, {}, {}
        for var in variables:
            name, vtype = var["name"], var.get("type", "")
            is_arg = var.get("arg") == "1"
            if not is_arg and name in declared and not _declared_yet(frame, declared[name]):
                continue  # execution hasn't reached its declaration: the value is garbage
            raw = var.get("value")
            if raw is None:
                raw = self._eval(name, level) or "?"
            if "_M_impl" in raw and "_M_start" in raw:
                # A std::vector without GDB's pretty printers: read its elements
                impl = f"{name}._M_impl"
                raw = self._eval(f"*{impl}._M_start@({impl}._M_finish - {impl}._M_start)", level) \
                    if "_M_start = 0x0," not in raw else "{}"
                raw = raw or "?"
            locals_[name] = _display(raw, vtype)
            if _is_plain_pointer(vtype) and locals_[name] not in ("NULL", "?"):
                # 0x7ffd5c -> 0x7ffd5c → 10 (what the pointer points at)
                pointee = self._eval(f"*{name}", level)
                shown = _display(pointee, _base_type(vtype)[:-1]) if pointee is not None else "(invalid memory)"
                locals_[name] = f"{locals_[name]} → {shown}"
            types[name] = vtype
            if name not in frame.addresses:
                frame.addresses[name] = self._address(name, level)
            address = frame.addresses[name]
            if address:
                regions.append((address[0], address[1]))
                key = _hex(address[0])
                refs[name] = key
                values.setdefault(key, {"type": vtype, "value": locals_[name]})
            if _is_pointer(vtype):
                target = HEX.search(raw)
                if target and int(target.group(0), 16) != 0:
                    pointers[name] = int(target.group(0), 16)
        line = frame.current if frame.current is not None else frame.entry_line
        return {"func": frame.func, "frame_id": frame.frame_id, "line": line,
                "locals": locals_, "refs": refs, "types": types, "_pointers": pointers}

    def _globals(self, regions):
        names = self.analysis["globals"]
        if not names:
            return None
        locals_, refs, types = {}, {}, {}
        for name in names:
            # 'prog.c'::count names the global even if a local hides it
            value = self._eval(f"'{self.name}'::{name}") or self._eval(name)
            if value is None:
                continue
            locals_[name] = _display(value, "")
            address = self._global_address(name)
            if address:
                regions.append(address)
                refs[name] = _hex(address[0])
        return {"func": "globals", "frame_id": 0, "line": None, "locals": locals_,
                "refs": refs, "types": types, "_pointers": {}}

    def _global_address(self, name):
        """(address, size) of a global; it never moves, so ask GDB once."""
        if name not in self.global_addresses:
            self.global_addresses[name] = self._address(f"'{self.name}'::{name}", 0) or self._address(name, 0)
        return self.global_addresses[name]

    def _declared(self, func):
        declared = self.analysis["declared"]
        return declared.get(func) or declared.get(func.split("::")[-1], {})

    def _eval(self, expression, level=0):
        try:
            return self.gdb.evaluate(expression, level)
        except MIError:
            return None

    def _address(self, expression, level):
        """(address, size) of a variable's storage, or None."""
        where = self._eval(f"&({expression})", level)
        size = self._eval(f"sizeof({expression})", level)
        match = HEX.search(where or "")
        if not match or not size or not size.strip().isdigit():
            return None
        return int(match.group(0), 16), int(size)

    def _mutated(self, info):
        """Memory this line changes, named by the variable that owns it.

        The paths are side-effect-free lvalues from c_analysis (a[i], *p,
        p->next), so asking GDB for &(path) before the line runs is safe.
        """
        # In C, assigning to x changes x's memory too, so a pointer to x sees it
        paths = list(info["mutates"]) + list(info["method_mutates"])
        paths += [w for w in info["writes"] if w not in paths]
        regions = self._all_regions()
        found = []
        for path in paths:
            match = HEX.search(self._eval(f"&({path})", 0) or "")
            if match:
                owner = _owner(int(match.group(0), 16), regions)
                if owner not in found:
                    found.append(owner)
        return found

    def _all_regions(self):
        regions = []
        for frame in self.frames:
            regions.extend(a for a in frame.addresses.values() if a)
        for name in self.analysis["globals"]:
            address = self._global_address(name)
            if address:
                regions.append(address)
        return regions


# ---------- Values ----------

def _declared_yet(frame, lines):
    """Has execution reached a declaration on one of these lines?

    `int age;` has no code, so GDB never stops on it: being past the line
    counts. A line the frame is still on (`int a = f();` while f runs, or a
    `for` header the first time) hasn't finished, so it doesn't.
    """
    now = frame.current if frame.current is not None else frame.entry_line
    return any(now > d or any(e >= d for e in frame.executed) for d in lines)


def _hex(address):
    return f"0x{address:x}"


def _owner(address, regions):
    """The variable whose memory contains this address (so &a[1] belongs to a)."""
    for start, size in regions:
        if start <= address < start + max(size, 1):
            return _hex(start)
    return _hex(address)  # memory from malloc/new


def _base_type(vtype):
    """`Counter * const` -> `Counter *` (qualifiers after the * don't matter here)."""
    return re.sub(r"(\s+(const|volatile))+$", "", (vtype or "").strip())


def _is_pointer(vtype):
    """Pointers and C++ references: variables that refer to other memory."""
    vtype = _base_type(vtype)
    return vtype.endswith("*") or vtype.endswith("&")


def _is_char_pointer(vtype):
    return bool(re.search(r"\bchar\s*\*$", _base_type(vtype)))


def _is_plain_pointer(vtype):
    vtype = _base_type(vtype)
    return vtype.endswith("*") and not _is_char_pointer(vtype) and "void" not in vtype


def _display(raw, vtype):
    """GDB's text for a value, made easier to read for a beginner."""
    if raw is None:
        return "?"
    value = raw.strip()
    vtype = _base_type(vtype)
    if vtype.endswith("&"):  # a C++ reference: "@0x7ffd...: 5" -> "5"
        value = value.split(": ", 1)[-1]
    elif _is_char_pointer(vtype):  # 0x5555 "odd" -> "odd"
        quoted = value.find('"')
        if quoted > 0:
            value = value[quoted:]
    elif vtype.endswith("*"):  # 0x404010 <count> -> 0x404010; 0x0 -> NULL
        address = HEX.search(value)
        if address:
            value = "NULL" if int(address.group(0), 16) == 0 else address.group(0)
    vector = re.match(r"std::(?:__\w+::)?(\w+)(?:<.*?>)? (?:of length|with) (\d+)[^=]*(?:= (.*))?$", value)
    if vector:
        value = vector.group(3) or "{}"
    if len(value) > MAX_VALUE_CHARS:
        value = value[:MAX_VALUE_CHARS - 1] + "…"
    return value


def main():
    request = json.load(sys.stdin)
    language = request.get("language", "c")
    if language not in ("c", "cpp"):
        print(json.dumps({"error": f"Unsupported language: {language}"}))
        return
    try:
        result = trace(request.get("code", ""), language, request.get("input", ""),
                       int(request.get("max_steps", MAX_STEPS)))
    except Exception as e:  # always answer with JSON
        result = {"language": language, "code": request.get("code", ""), "steps": [], "stdout": "",
                  "error": "Kaaran couldn't trace this program.", "error_line": None,
                  "truncated": False, "internal_error": f"{type(e).__name__}: {e}"}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
