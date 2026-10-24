"""Why Engine: answer "why does this variable have this value?"

It works on any trace in Kaaran's format (docs/trace-format.md), so the same
code explains Python and C/C++ programs. First it builds a dynamic
dependency graph over the executed steps:

  data      a step depends on the step that last wrote each variable it
            reads, and on the last step that changed each object it reads
            (this is how aliasing is caught: b = a; a.append(3); print(b))
  control   a step depends on the if/for/while step that made it run
  calls     a call depends on the line that made it, and that line
            depends on the callee's return

The answer is a dynamic backward slice: every step reachable from the
question in this graph. See docs/design.md for the details and limitations.
"""
import bisect

WRITE, MUTATE = "write", "mutate"


class WhyEngine:
    def __init__(self, trace):
        self.steps = {s["step"]: s for s in trace["steps"]}
        self.source = trace.get("code", "").splitlines()
        self.deps = {n: set() for n in self.steps}   # step -> steps it depends on
        self.writers = {}        # (frame_id, name) -> steps that wrote it, in order
        self.mutators = {}       # object id -> steps that changed it, in order
        self.next_in_frame = {}  # step -> next step in the same frame
        self.controlled = {}     # step -> steps whose control_parent it is
        self._build()

    # ---------- Building the graph ----------

    def _build(self):
        last_line = {}    # frame_id -> latest "line" step in that frame
        last_any = {}     # frame_id -> latest step of any event in that frame
        loop_prev = {}    # (frame_id, line) -> previous run of that loop header
        caller_of = {}    # frame_id -> frame_id of its caller

        for n in sorted(self.steps):
            step = self.steps[n]
            fid, event, deps = step["frame_id"], step["event"], self.deps[n]
            if fid in last_any:
                self.next_in_frame[last_any[fid]] = n
            last_any[fid] = n

            if event == "call":
                stack = step["stack"]
                if len(stack) > 1:
                    caller_of[fid] = stack[-2]["frame_id"]
                if caller_of.get(fid) in last_line:  # the line that made the call
                    deps.add(last_line[caller_of[fid]])
            elif event in ("return", "exception"):
                if fid in last_line:  # the return statement (or the failing line)
                    deps.add(last_line[fid])
                if event == "return" and caller_of.get(fid) in last_line:
                    # the caller's line uses the returned value
                    self.deps[last_line[caller_of[fid]]].add(n)

            for name in step.get("reads", ()):
                deps.update(self._sources(step, name, n))
            for obj in step.get("mutates", ()):
                # the object's new state builds on its old state
                previous = self._visible(self.mutators.get(obj), n)
                if previous:
                    deps.add(previous)
            parent = step.get("control_parent")
            if parent:
                deps.add(parent)
                self.controlled.setdefault(parent, []).append(n)
            if step.get("header") == "loop":
                # each round of a loop continues from the round before
                key = (fid, step["line"])
                if key in loop_prev:
                    deps.add(loop_prev[key])
                loop_prev[key] = n

            for name in step.get("writes", ()):
                self.writers.setdefault(self._write_key(step, name), []).append(n)
            for obj in step.get("mutates", ()):
                self.mutators.setdefault(obj, []).append(n)
            if event == "line":
                last_line[fid] = n
            deps.discard(n)

    def _write_key(self, step, name):
        if name in step.get("globals", ()):
            return (step["stack"][0]["frame_id"], name)
        return (step["frame_id"], name)

    def _read_frame(self, step, name):
        """The frame whose variable `name` a step reads: its own, else the
        outermost (module globals in Python, globals in C)."""
        stack = step["stack"]
        for frame in (stack[-1], stack[0]):
            if name in frame["locals"]:
                return frame
        return None

    def _sources(self, step, name, at):
        """Steps that gave variable `name` the value it has at step `at`: its
        last write, and the last change to anything it refers to."""
        frame = self._read_frame(step, name)
        if frame is None:
            return []  # a builtin like print, or not defined yet
        found = []
        writer = self._visible(self.writers.get((frame["frame_id"], name)), at)
        if writer:
            found.append(writer)
        ref = frame.get("refs", {}).get(name)
        if ref is not None:
            for obj in _reachable(ref, step.get("heap", {})):
                changer = self._visible(self.mutators.get(obj), at)
                if changer:
                    found.append(changer)
        return found

    def _visible(self, steps, at):
        """Latest step in `steps` whose change can be seen at step `at`.

        A call sets its parameters at once. A line's changes only show once
        its frame moves on: `x = f()` hasn't set x while f is still running.
        """
        i = bisect.bisect_right(steps or [], at)
        while i:
            i -= 1
            n = steps[i]
            done = n if self.steps[n]["event"] == "call" else self.next_in_frame.get(n)
            if done is not None and done <= at:
                return n
        return None

    # ---------- Questions ----------

    def step(self, n):
        return self.steps[n]

    def why(self, step, name, frame_index=-1):
        """Why does variable `name` (in stack[frame_index]) have its value at `step`?"""
        s = self.steps[step]
        frame = s["stack"][frame_index]
        if name not in frame["locals"]:
            raise KeyError(f"{name} is not a variable of {frame['func']} at step {step}")
        view = dict(s, stack=[frame])  # read `name` from exactly this frame
        origins = set(self._sources(view, name, step))
        steps = self._closure(origins, limit=step)
        return {
            "question": {"step": step, "name": name, "frame": frame["func"],
                         "value": frame["locals"][name]},
            "summary": self._summary(s, frame, name, origins),
            "origins": sorted(origins),
            "slice": sorted(steps),
            "lines": sorted({self.steps[n]["line"] for n in steps}),
            "chain": [self.explain_step(n, at=step) for n in sorted(steps)],
        }

    def why_step(self, step):
        """Why did this step happen at all, with these values?"""
        # A line is still running until its frame's next step (calls it makes
        # and their return values are part of it)
        end = self.next_in_frame.get(step, max(self.steps) + 1) - 1
        steps = self._closure(self.deps[step] | {step}, limit=end)
        return {
            "question": {"step": step, "line": self.steps[step]["line"]},
            "summary": self.explain_step(step)["text"],
            "origins": sorted(self.deps[step]),
            "slice": sorted(steps),
            "lines": sorted({self.steps[n]["line"] for n in steps}),
            "chain": [self.explain_step(n, at=end) for n in sorted(steps)],
        }

    def output_step(self, line_index):
        """The step that printed output line `line_index` (0-based), or None."""
        previous = None
        for n in sorted(self.steps):
            if self.steps[n]["stdout"].count("\n") > line_index:
                return self._printing_step(previous) if previous else None
            previous = n
        return None

    def _printing_step(self, n):
        """Output first visible at the step after n was produced while n ran;
        if n is a return, the printing happened back in the caller's line."""
        step = self.steps[n]
        if step["event"] == "line":
            return n
        if step["event"] == "return" and len(step["stack"]) > 1:
            caller = step["stack"][-2]["frame_id"]
            lines = [m for m in self.steps if m < n and self.steps[m]["frame_id"] == caller
                     and self.steps[m]["event"] == "line"]
            return max(lines) if lines else None
        return None

    def why_output(self, line_index):
        n = self.output_step(line_index)
        if not n:
            return None
        answer = self.why_step(n)
        last = self.steps[max(self.steps)]["stdout"].split("\n")
        answer["question"]["output"] = last[line_index] if line_index < len(last) else ""
        return answer

    def _closure(self, start, limit):
        """Everything `start` depends on, transitively. Steps after `limit`
        are left out: they hadn't happened yet at the time of the question."""
        found, todo = set(), [n for n in start if n <= limit]
        while todo:
            n = todo.pop()
            if n in found:
                continue
            found.add(n)
            todo.extend(d for d in self.deps[n] if d <= limit and d not in found)
        return found

    # ---------- Explanations ----------

    def code(self, line):
        if 1 <= line <= len(self.source):
            return self.source[line - 1].strip()
        return ""

    def explain_step(self, n, at=None):
        """One sentence about step n. With `at`, only what was known by step
        `at` (a line that was still running then is described as such)."""
        s = self.steps[n]
        func = s["stack"][-1]["func"]
        event = s["event"]
        if event == "call":
            args = ", ".join(f"{p}={s['locals'].get(p, '?')}" for p in s.get("writes", ()))
            text, kind = f"{func}({args}) was called", "call"
        elif event == "return":
            if "return_value" in s:
                text = f"{func} returned {s['return_value']}"
            else:
                text = "the program finished" if len(s["stack"]) == 1 else f"{func} stopped"
            kind = "return"
        elif event == "exception":
            text, kind = f"error: {s.get('exception', '')}", "error"
        else:
            done = self.next_in_frame.get(n)
            if at is not None and (done is None or done > at):
                text, kind = self._explain_running(n, at), "call"
            else:
                text, kind = self._explain_line(n)
        return {"step": n, "line": s["line"], "code": self.code(s["line"]),
                "event": event, "func": func, "kind": kind, "text": text}

    def _explain_line(self, n):
        s = self.steps[n]
        used = self._used(n)
        using = f" (using {_pairs(used)})" if used else ""
        header = s.get("header")
        if header == "loop":
            if not self.controlled.get(n):
                return "the loop finished" + using, "control"
            written, _ = self._changes(n)
            if written:
                return f"loop round with {_pairs(written)}", "control"
            return "the loop condition was True, so the loop ran again" + using, "control"
        if header == "if":
            return f"the condition was {self._outcome(n)}" + using, "control"
        if header == "except":
            return "an error was caught here", "control"
        written, changed = self._changes(n)
        printed = self._printed(n)
        after = self._after(n)
        parts = []
        defined = [(k, v) for k, v in written if v.startswith(("function ", "class "))]
        if defined and len(defined) == len(written) and not changed and not printed:
            return "defined " + ", ".join(v.split(" ", 1)[0] + " " + k for k, v in defined), "definition"
        if written:
            parts.append(f"set {_pairs(written)}")
        if changed:
            parts.append("changed " + ", ".join(f"{k} to {v}" for k, v in changed))
        if printed:
            parts.append(f"printed {printed!r}")
        if after and after["event"] == "return" and "return_value" in after and not parts:
            parts.append(f"returned {after['return_value']}")
        calls = self._returns_used(n)
        if calls:
            using = f" (using {_pairs(used + calls)})"
        if parts:
            return " and ".join(parts) + using, "data"
        return "ran" + using, "data"

    def _explain_running(self, n, at):
        calls = [f"{self.steps[c]['stack'][-1]['func']}()" for c in self.controlled.get(n, ())
                 if c <= at and self.steps[c]["event"] == "call"]
        return "called " + ", ".join(calls) + " and was still waiting for it" if calls else "was still running"

    def _outcome(self, n):
        """True if an if-condition at step n was true (its body ran)."""
        children = self.controlled.get(n, [])
        if not children:
            return False
        return self.steps[children[0]].get("branch") is not False

    def _after(self, n):
        later = self.next_in_frame.get(n)
        return self.steps[later] if later else None

    def _used(self, n):
        s = self.steps[n]
        used = []
        for name in s.get("reads", ()):
            frame = self._read_frame(s, name)
            if frame is not None:
                value = frame["locals"][name]
                if not value.startswith(("function ", "class ", "method ")):
                    used.append((name, value))
        return used

    def _returns_used(self, n):
        """("square(...)", value) for each function call a line made."""
        found = []
        for d in sorted(self.deps[n]):
            r = self.steps[d]
            # a procedure's None (c.add(2), __init__) isn't a value the line used
            if d > n and r["event"] == "return" and r.get("return_value", "None") != "None":
                found.append((f"{r['stack'][-1]['func']}(...)", r["return_value"]))
        return found

    def _changes(self, n):
        """What step n did, as (name, new value) pairs: variables it set,
        and objects it changed in place (named by the variable it used)."""
        s, after = self.steps[n], self._after(n)
        if after is None or after["event"] == "exception":
            return [], []
        written, changed = [], []
        for name in s.get("writes", ()):
            frame = _frame(after, self._write_key(s, name)[0])
            if frame and name in frame["locals"]:
                written.append((name, frame["locals"][name]))
        for obj in s.get("mutates", ()):
            name = self._alias(s, obj)
            if name and name not in dict(written + changed):
                frame = self._read_frame(after, name)
                if frame:
                    changed.append((name, frame["locals"][name]))
        return written, changed

    def _printed(self, n):
        """Output written by line n itself: before its first call, and after
        each call it made returned (not what the called functions printed)."""
        own = [n] + [d for d in sorted(self.deps[n])
                     if d > n and self.steps[d]["event"] == "return"]
        text = ""
        for start in own:
            if start + 1 in self.steps:
                before, now = self.steps[start]["stdout"], self.steps[start + 1]["stdout"]
                if now.startswith(before):
                    text += now[len(before):]
        return text

    def _alias(self, step, obj):
        """The name a step used to reach object `obj` (e.g. `a` in a.append(3))."""
        frame = step["stack"][-1]
        refs = frame.get("refs", {})
        names = [name for name, ref in refs.items() if obj in _reachable(ref, step.get("heap", {}))]
        direct = [name for name in names if refs[name] == obj]
        for group in (direct, names):
            for name in group:
                if name in step.get("reads", ()) or name in step.get("writes", ()):
                    return name
        return (direct or names or [None])[0]

    def _summary(self, s, frame, name, origins):
        value = frame["locals"][name]
        if not origins:
            return f"{name} = {value}: no earlier step in this trace changed it."
        reasons = []
        for o in sorted(origins, reverse=True):
            reasons.append(self._reason(s, frame, name, o))
        return f"{name} = {value} because " + "; and ".join(reasons) + "."

    def _reason(self, s, frame, name, o):
        origin = self.steps[o]
        where = f"line {origin['line']} (`{self.code(origin['line'])}`)"
        if origin["event"] == "call":
            caller = origin.get("control_parent")
            place = f" on line {self.steps[caller]['line']}" if caller else ""
            return f"it was passed in when {origin['stack'][-1]['func']} was called{place}"
        if o in self.writers.get((frame["frame_id"], name), ()):
            used = self._used(o) + self._returns_used(o)
            verb = "updated it" if name in origin.get("reads", ()) else "set it"
            return f"{where} {verb}" + (f", using {_pairs(used)}" if used else "")
        # o changed an object that `name` refers to (or one inside it)
        ref = frame.get("refs", {}).get(name)
        heap = s.get("heap", {})
        changed = [obj for obj in origin.get("mutates", ()) if obj in _reachable(ref, heap)]
        obj = changed[0] if changed else ref
        kind = heap.get(obj, {}).get("type", "object")
        alias = self._alias(origin, obj)
        alias_ref = origin["stack"][-1].get("refs", {}).get(alias)
        if obj != ref:  # e.g. grid[0][0] = 5 changes a row inside grid
            through = f" (through {alias})" if alias and alias != name else ""
            return f"{where} changed a {kind} inside {name}{through}"
        if not alias or alias == name:
            return f"{where} changed {name} in place"
        if alias_ref == obj:
            return (f"{where} changed the {kind} that {name} refers to. {alias} and {name} "
                    f"are the same {kind}, so changing {alias} also changes {name}")
        return (f"{where} changed the {kind} that {name} refers to, through {alias} "
                f"(the {kind} {name} refers to is inside {alias})")


def _reachable(ref, heap):
    """ref and every object inside it (list of lists, object attributes...)."""
    found, todo = set(), [ref]
    while todo:
        obj = todo.pop()
        if obj in found:
            continue
        found.add(obj)
        todo.extend(heap.get(obj, {}).get("children", ()))
    return found


def _frame(step, frame_id):
    for frame in step["stack"]:
        if frame["frame_id"] == frame_id:
            return frame
    return None


def _pairs(pairs):
    return ", ".join(f"{k} = {v}" for k, v in pairs)
