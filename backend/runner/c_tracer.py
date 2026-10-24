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
TIME_LIMIT = float(os.environ.get("KAARAN_TIME_LIMIT", "15"))  # seconds for the whole trace
STEP_TIMEOUT = 3.0       # seconds for one `step` (a single line that never ends)
COMPILE_TIMEOUT = 20
MAX_VALUE_CHARS = 200
MAX_HEAP_NODES = 40      # structs from malloc/new shown per step

# Linked into every program: reads input from a file, writes output to a
# file without buffering (so each step sees what was printed so far). The
# file names come from the environment, so no shell is involved.
IO_HELPER = r"""
#include <stdio.h>
#include <stdlib.h>
FILE *kaaran_stdin;  /* so the tracer can ask feof(kaaran_stdin): did input run out? */
__attribute__((constructor)) static void kaaran_io(void) {
    const char *in = getenv("KAARAN_STDIN"), *out = getenv("KAARAN_STDOUT");
    kaaran_stdin = stdin;
    if (in) kaaran_stdin = freopen(in, "r", stdin);
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
PRIMITIVES = {"int", "char", "short", "long", "float", "double", "bool", "_Bool", "void", "unsigned",
              "signed", "size_t", "int8_t", "int16_t", "int32_t", "int64_t", "uint8_t", "uint16_t",
              "uint32_t", "uint64_t", "wchar_t"}


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
        self.listing = None      # its variables as GDB last listed them
        self.listed_at = None    # the stop it was listed at
        self.targets = set()     # memory its pointers point into
        self.changing = set()    # memory its current line changes (until the line ends)
        self.snapshot = None     # the stack when this frame last stopped
        self.heap = {}

    def touched(self, changed):
        """Did memory this frame shows (its variables, or what its pointers
        point at) change? Only then does it need listing again."""
        mine = {address for address, _ in filter(None, self.addresses.values())}
        return bool(changed & (mine | self.targets))


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
        self.globals_listing = None
        self.nodes = {}             # heap address -> struct read from it (until it changes)
        self.struct_info = {}       # type name -> {"size", "fields"} or None
        self.changed = set()        # memory changed since the last snapshot (owner addresses)
        self.freed = set()          # heap addresses given to free()/delete
        self.pending = {}           # effects of the line that just ran, applied at the next stop
        self.input_ran_out = None   # line whose read hit the end of the input
        self.stop_id = 0            # counts GDB stops
        self.global_types = {}
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
        if self.input_ran_out:
            self.result["input_ran_out"] = self.input_ran_out
            if self.result["truncated"]:
                # The usual reason a menu program "never ends": it needed more input
                self.result["error"] = (
                    f"Stopped: the program ran out of input at line {self.input_ran_out} and kept going "
                    "without it. Type everything it reads in the Input tab, one value per line (for a "
                    "menu: each choice, then the values it asks for, ending with the exit choice), "
                    "and run again.")
                self.result["error_line"] = self.input_ran_out

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
        """Step to the next line; once a function is leaving, finish it
        instead, which is how GDB reports the value it returns."""
        if len(self.frames) > 1 and self.frames[-1].returning:
            return "-exec-finish"
        return "-exec-step"

    def _end_line(self, frame):
        ends = self.analysis["ends"]
        return ends.get(frame.func) or ends.get(frame.func.split("::")[-1])

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
        self.stop_id += 1
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
        if "input_line" in self.pending:
            # Check once execution has left the input line (GDB can stop
            # inside the C library, mid-line, before the read happened)
            frame_id, input_line = self.pending["input_line"]
            still_there = depth == len(self.frames) and self.frames \
                and self.frames[-1].frame_id == frame_id and line == input_line
            if not still_there:
                del self.pending["input_line"]
                self._check_input(input_line)
        returned = depth < len(self.frames)
        value = stop.get("return-value") if reason == "function-finished" else None
        while depth < len(self.frames):
            leaving = self.frames.pop()
            self.changed |= leaving.changing  # e.g. swap's last line `*b = t` changed the caller's y
            self._record_return(leaving, value)
            value = None
        if (returned or back_mid_line) and self.frames and line == self.frames[-1].current:
            return True  # back in the middle of a line that hasn't finished: it continues
        if depth == len(self.frames) and self.frames and (self.frames[-1].on_return or self.frames[-1].returning):
            # Its return statement has finished (a `return f(x);` line first
            # runs the call). What's left is cleanup, such as destructors
            # freeing memory, so the values are no longer meaningful.
            self.frames[-1].returning = True
            return True
        if depth > len(self.frames):
            for frame in user[:depth - len(self.frames)][::-1]:
                self._push(frame, stop)
        if line == self._end_line(self.frames[-1]):
            # The closing brace isn't a statement: the function is leaving
            # (finish it; for main, the program is ending)
            self.frames[-1].returning = True
            return True
        self._record_line(line, user)
        return True

    def _check_input(self, line):
        """After a line that read input: did the read hit the end of it?"""
        # The cast: newer GDBs won't call a library function without debug info otherwise
        ran_out = self._eval("(int) feof(kaaran_stdin)")
        if ran_out is not None and ran_out.strip() not in ("0", "") and not self.input_ran_out:
            self.input_ran_out = line

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
        # Like Python's call event, the call is shown on the function's first line
        starts = self.analysis["starts"]
        line = starts.get(frame.func) or starts.get(frame.func.split("::")[-1]) or frame.entry_line
        self.steps.append(self._step(number, line, "call", frame, stack, heap, writes=args,
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
            # What this line changes is only final once the line has run:
            # `root->left = insert(...)` changes root's node after the call
            frame.changing = {int(owner, 16) for owner in step["mutates"]}
            if info["input"]:
                self.pending["input_line"] = (frame.frame_id, line)
            if info["frees"]:
                freed = [_target(self._eval(path, 0)) for path in info["frees"]]
                self.pending["freed"] = [address for address in freed if address]
                step["frees"] = [_owner(address, self._all_regions()) for address in self.pending["freed"]]
            if info["allocates"] and info["writes"]:
                self.pending["allocated"] = (frame.frame_id, list(info["writes"]))
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
            shown = _display(value, "")
            address = _target(shown)
            if address in self.nodes:  # returned a pointer to a struct: show the struct too
                shown = f"{shown} → {self.nodes[address]['entry']['value']}"
            step["return_value"] = shown
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

    # ---------- Variables and memory ----------

    def _snapshot(self):
        """Every frame's variables (outermost first), a globals frame, and
        the structs on the heap that pointers lead to.

        Asking GDB costs milliseconds per question, so a caller's variables
        are listed again only when memory they show has changed: in C a
        function can change its caller's variables only through pointers,
        and every such change is recorded (self.changed). Heap structs are
        read again only after a line changed them.
        """
        self._apply_pending()
        # Memory changed since the last stop, plus memory that unfinished
        # lines (this one, or callers waiting on a call) are changing
        changed, self.changed = self.changed, set()
        for frame in self.frames:
            changed |= frame.changing
        for address in changed:
            self.nodes.pop(address, None)
        depth = len(self.frames)
        for index, frame in enumerate(self.frames):
            fresh = frame.listed_at == self.stop_id
            if not fresh and (index == depth - 1 or frame.listing is None or frame.touched(changed)):
                frame.listing = self._list(frame, depth - 1 - index)
                frame.listed_at = self.stop_id
        if self.analysis["globals"] and (self.globals_listing is None or self._globals_touched(changed)):
            self.globals_listing = self._list_globals()
        heap = self._read_heap()
        # Regions include the structs just read, so p->next belongs to *p
        return self._build_stack(self._all_regions(), heap), heap

    def _list(self, frame, level):
        """A frame's variables as GDB shows them: name, type and raw value."""
        try:
            variables = self.gdb.command(
                f"-stack-list-variables --thread 1 --frame {level} --simple-values")["variables"]
        except MIError:
            return frame.listing or []
        declared = self._declared(frame.func)
        listing = []
        for var in variables:
            name, vtype = var["name"], var.get("type", "")
            if var.get("arg") != "1" and name in declared and not _declared_yet(frame, declared[name]):
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
            if name not in frame.addresses:
                frame.addresses[name] = self._address(name, level)
            entry = {"name": name, "type": vtype, "raw": raw, "address": frame.addresses[name]}
            if _is_plain_pointer(vtype) and _target(raw) and self._struct(_pointee(vtype)) is None:
                entry["pointee"] = self._eval(f"*{name}", level)  # e.g. an int in a malloc'd array
            listing.append(entry)
        return listing

    def _list_globals(self):
        listing = []
        for name in self.analysis["globals"]:
            # 'prog.c'::count names the global even if a local hides it
            raw = self._eval(f"'{self.name}'::{name}") or self._eval(name)
            if raw is None:
                continue
            listing.append({"name": name, "type": self._global_type(name), "raw": raw,
                            "address": self._global_address(name)})
        return listing

    def _globals_touched(self, changed):
        return any(entry["address"] and entry["address"][0] in changed for entry in self.globals_listing or [])

    def _global_type(self, name):
        if name not in self.global_types:
            self.gdb.try_command(f"-interpreter-exec console \"whatis '{self.name}'::{name}\"")
            match = re.search(r"type = (.*)", "".join(self.gdb.console))
            self.global_types[name] = match.group(1).strip() if match else ""
        return self.global_types[name]

    def _global_address(self, name):
        """(address, size) of a global; it never moves, so ask GDB once."""
        if name not in self.global_addresses:
            self.global_addresses[name] = self._address(f"'{self.name}'::{name}", 0) or self._address(name, 0)
        return self.global_addresses[name]

    def _apply_pending(self):
        """Effects of the line that just ran: freed and newly allocated memory."""
        for address in self.pending.pop("freed", []):
            self.freed.add(address)
            self.nodes.pop(address, None)
            self.changed.add(address)
        frame_id, names = self.pending.pop("allocated", (None, []))
        for index, frame in enumerate(self.frames):
            if frame.frame_id == frame_id:
                level = len(self.frames) - 1 - index
                for name in names:
                    address = _target(self._eval(name, level))
                    if address:  # malloc may reuse freed memory: it's alive again
                        self.freed.discard(address)
                        self.nodes.pop(address, None)
                        self.changed.add(address)

    def _struct(self, ctype):
        """Fields of a struct/class type, from GDB's ptype; None if it isn't one."""
        ctype = ctype.strip()
        if ctype not in self.struct_info:
            info = None
            if ctype and ctype not in PRIMITIVES and ctype.split()[-1] not in PRIMITIVES:
                self.gdb.try_command(f'-interpreter-exec console "ptype {ctype}"')
                text = "".join(self.gdb.console)
                if re.match(r"type = (struct|class|union)\b", text.strip()):
                    fields = []
                    for line in text.splitlines()[1:]:
                        match = re.match(r"\s*([\w:<>, ]+?)\s*(\**)\s*(\w+)(\[[^\]]*\])?;\s*$", line)
                        if match and "(" not in line:
                            fields.append({"name": match.group(3), "base": match.group(1).strip(),
                                           "pointer": len(match.group(2)) == 1 and not match.group(4)})
                    size = self._eval(f"sizeof({ctype})")
                    if size and size.strip().isdigit():
                        info = {"size": int(size), "fields": fields}
            self.struct_info[ctype] = info
        return self.struct_info[ctype]

    def _read_heap(self):
        """Structs from malloc/new that pointers lead to, following their
        pointer fields (a linked list's next, a tree's left and right)."""
        variables = self._variable_regions()
        todo = []
        for listing in [self.globals_listing or []] + [f.listing or [] for f in self.frames]:
            for var in listing:
                address = _target(var["raw"]) if _is_plain_pointer(var["type"]) else None
                if address:
                    todo.append((address, _pointee(var["type"])))
        heap = {}
        while todo and len(heap) < MAX_HEAP_NODES:
            address, ctype = todo.pop(0)
            key = _hex(address)
            if key in heap or _inside(address, variables) or self._struct(ctype) is None:
                continue
            if address in self.freed:
                heap[key] = {"type": ctype, "value": "freed memory", "kind": "heap", "freed": True,
                             "fields": {}, "edges": [], "children": []}
                continue
            node = self._node(address, ctype)
            if node is None:
                continue
            heap[key] = node["entry"]
            todo.extend(node["links"])
        return heap

    def _node(self, address, ctype):
        cached = self.nodes.get(address)
        if cached and cached["entry"]["type"] == ctype:
            return cached
        info = self._struct(ctype)
        raw = self._eval(f"*({ctype} *) {_hex(address)}")
        if raw is None:
            return None  # not readable memory (an uninitialised pointer)
        values = _struct_fields(raw)
        fields, edges, links = {}, [], []
        for field in info["fields"]:
            value = values.get(field["name"])
            if value is None:
                continue
            if field["pointer"]:
                child = _target(value)
                if child:
                    edges.append({"label": field["name"], "to": _hex(child)})
                    links.append((child, field["base"]))
            else:
                fields[field["name"]] = _display(value, "")
        entry = {"type": ctype, "value": _display(re.sub(r"\b0x0\b", "NULL", raw), ""), "kind": "heap",
                 "fields": fields, "edges": edges, "children": [e["to"] for e in edges]}
        self.nodes[address] = {"entry": entry, "size": info["size"], "links": links}
        return self.nodes[address]

    def _build_stack(self, regions, heap):
        listings = ([(None, self.globals_listing)] if self.globals_listing else []) + \
                   [(frame, frame.listing or []) for frame in self.frames]
        stack, shown, kinds = [], {}, {}
        for frame, listing in listings:
            locals_, types, refs = {}, {}, {}
            for var in listing:
                name = var["name"]
                locals_[name] = _display(var["raw"], var["type"])
                types[name] = var["type"]
                if var["address"]:
                    refs[name] = _hex(var["address"][0])
                    shown.setdefault(refs[name], locals_[name])
                    kinds.setdefault(refs[name], var["type"])
            if frame is None:
                stack.append({"func": "globals", "frame_id": 0, "line": None,
                              "locals": locals_, "refs": refs, "types": types})
            else:
                line = frame.current if frame.current is not None else frame.entry_line
                stack.append({"func": frame.func, "frame_id": frame.frame_id, "line": line,
                              "locals": locals_, "refs": refs, "types": types})
        # Pointers and references refer to the variable or struct they point at
        for (frame, listing), entry in zip(listings, stack):
            targets = set()
            for var in listing:
                if not _is_pointer(var["type"]):
                    continue
                target = _target(var["raw"])
                if not target:
                    continue
                owner = _owner(target, regions)
                entry["refs"][var["name"]] = owner
                targets.add(int(owner, 16))
                if not _is_plain_pointer(var["type"]):
                    continue
                if owner in heap:
                    pointee = heap[owner]["value"]
                elif owner == _hex(target) and owner in shown:
                    pointee = shown[owner]
                elif var.get("pointee") is not None:
                    pointee = _display(var["pointee"], _pointee(var["type"]))
                else:
                    pointee = None
                if pointee is not None:
                    entry["locals"][var["name"]] = f"{entry['locals'][var['name']]} → {pointee}"
            if frame is not None:
                frame.targets = targets
        for owner, value in shown.items():  # variables' memory, so answers can name its type
            heap.setdefault(owner, {"type": kinds[owner], "value": value, "kind": "variable"})
        return stack

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
        """Memory this line changes, named by the variable or struct that owns it.

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

    def _variable_regions(self):
        regions = [a for frame in self.frames for a in frame.addresses.values() if a]
        regions += [self._global_address(name) for name in self.analysis["globals"]]
        return [r for r in regions if r]

    def _all_regions(self):
        """Memory with an owner: variables, then structs read from the heap."""
        return self._variable_regions() + [(address, node["size"]) for address, node in self.nodes.items()]


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


def _target(raw):
    """The address a pointer value points to, or None for NULL."""
    match = HEX.search(raw or "")
    address = int(match.group(0), 16) if match else 0
    return address or None


def _pointee(vtype):
    """`struct Node *` -> `struct Node`."""
    return _base_type(vtype)[:-1].strip()


def _inside(address, regions):
    return any(start <= address < start + max(size, 1) for start, size in regions)


def _struct_fields(raw):
    """{data = 50, left = 0x0, name = "a, b"} -> {"data": "50", ...}, split
    only at the top level (values can hold nested braces and strings)."""
    text = raw.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return {}
    parts, depth, quote, current = [], 0, None, ""
    for ch in text[1:-1]:
        if quote:
            if ch == quote and not current.endswith("\\"):
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += ch
    parts.append(current)
    fields = {}
    for part in parts:
        name, sep, value = part.strip().partition(" = ")
        if sep:
            fields[name.strip()] = value.strip()
    return fields


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
    # finish reports pointers as "(struct Node *) 0x..."; the cast is noise here
    value = re.sub(r"^\([^()]*\)\s*(?=0x|-?\d)", "", raw.strip())
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
