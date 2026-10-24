"""Talk to GDB through its machine interface (GDB/MI).

GDB/MI is the text protocol IDEs use to drive GDB. A command is sent as
`<token>-command args`; GDB answers with a result record such as
`<token>^done,frame={line="7"}` or `<token>^error,msg="..."`. Records
starting with `*` arrive on their own: `*stopped,reason="end-stepping-range"`
says the program stopped. See the GDB manual, chapter "The GDB/MI Interface".
"""
import queue
import subprocess
import threading


class MIError(Exception):
    """GDB answered ^error, or GDB itself exited."""


class MITimeout(Exception):
    """GDB didn't answer in time (e.g. the program is stuck inside one line)."""


class GDB:
    def __init__(self, program, gdb="gdb", env=None, cwd=None):
        self.proc = subprocess.Popen(
            [gdb, "--interpreter=mi2", "--nx", "-q", program],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, cwd=cwd,
        )
        self.lines = queue.Queue()
        self.stops = []      # *stopped records not yet collected
        self.console = []    # console output (~"...") of the last command
        self.token = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in self.proc.stdout:
            self.lines.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        self.lines.put(None)  # GDB exited

    def _next_line(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise MITimeout("GDB did not answer in time")
        if line is None:
            raise MIError("GDB exited")
        return line

    def command(self, text, timeout=10):
        """Send one MI command and return its results (a dict)."""
        self.token += 1
        token = str(self.token)
        self.console = []
        self.proc.stdin.write(f"{token}{text}\n".encode("utf-8"))
        self.proc.stdin.flush()
        while True:
            record = parse_record(self._next_line(timeout))
            if record is None:
                continue
            if record["kind"] == "~":
                self.console.append(record["text"])
            elif record["kind"] == "*" and record["class"] == "stopped":
                self.stops.append(record["results"])
            elif record["kind"] == "^" and record["token"] == token:
                if record["class"] == "error":
                    raise MIError(record["results"].get("msg", "error"))
                return record["results"]

    def try_command(self, text, timeout=10):
        """Like command(), but None instead of an error (for optional settings)."""
        try:
            return self.command(text, timeout)
        except MIError:
            return None

    def wait_stopped(self, timeout):
        """Wait for the program to stop; returns the *stopped results."""
        while not self.stops:
            record = parse_record(self._next_line(timeout))
            if record and record["kind"] == "*" and record["class"] == "stopped":
                self.stops.append(record["results"])
        return self.stops.pop(0)

    def evaluate(self, expression, frame=0, timeout=10):
        """Value of an expression in a frame (0 = innermost), as GDB prints it."""
        escaped = expression.replace("\\", "\\\\").replace('"', '\\"')
        return self.command(f'-data-evaluate-expression --thread 1 --frame {frame} "{escaped}"',
                            timeout)["value"]

    def close(self):
        try:
            self.proc.stdin.write(b"-gdb-exit\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=3)
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


# ---------- Parsing MI output ----------

def parse_record(line):
    """One line of MI output -> {"kind", "token", "class", "results"} or
    {"kind": "~", "text"} for console text; None for the (gdb) prompt."""
    if not line or line.startswith("(gdb)"):
        return None
    i = 0
    while i < len(line) and line[i].isdigit():
        i += 1
    token, rest = line[:i], line[i:]
    if not rest:
        return None
    kind = rest[0]
    if kind in "~@&":
        text = _Parser(rest[1:]).string() if rest[1:2] == '"' else rest[1:]
        return {"kind": "~" if kind == "~" else kind, "text": text}
    if kind not in "^*+=":
        return None  # the program's own output, if it ever reaches here
    body = rest[1:]
    comma = body.find(",")
    cls = body if comma < 0 else body[:comma]
    results = _Parser(body[comma + 1:]).results() if comma >= 0 else {}
    return {"kind": kind, "token": token, "class": cls, "results": results}


class _Parser:
    """MI values: "c-strings", {tuples}, [lists] and name=value pairs."""

    def __init__(self, text):
        self.s = text
        self.i = 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def results(self, end=""):
        found = {}
        while self.i < len(self.s) and self.peek() != end:
            name, value = self.result()
            found[name] = value
            if self.peek() == ",":
                self.i += 1
        return found

    def result(self):
        start = self.i
        while self.peek() not in ("=", ""):
            self.i += 1
        name = self.s[start:self.i]
        self.i += 1  # '='
        return name, self.value()

    def value(self):
        c = self.peek()
        if c == '"':
            return self.string()
        if c == "{":
            self.i += 1
            found = self.results(end="}")
            self.i += 1
            return found
        if c == "[":
            self.i += 1
            items = []
            while self.peek() not in ("]", ""):
                if self.peek() in '"{[':
                    items.append(self.value())
                else:
                    items.append(self.result()[1])  # frame={...}: keep the value
                if self.peek() == ",":
                    self.i += 1
            self.i += 1
            return items
        raise ValueError(f"unexpected MI text at {self.i}: {self.s[self.i:self.i + 20]!r}")

    def string(self):
        """A C string with escapes; GDB sends non-ASCII as octal UTF-8 bytes."""
        self.i += 1  # opening quote
        out = bytearray()
        escapes = {"n": b"\n", "t": b"\t", "r": b"\r", '"': b'"', "\\": b"\\", "a": b"\a",
                   "b": b"\b", "f": b"\f", "v": b"\v", "e": b"\x1b"}
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                break
            if c == "\\" and self.i + 1 < len(self.s):
                nxt = self.s[self.i + 1]
                if nxt in "01234567":
                    j = self.i + 1
                    while j < len(self.s) and j < self.i + 4 and self.s[j] in "01234567":
                        j += 1
                    out.append(int(self.s[self.i + 1:j], 8) & 0xFF)
                    self.i = j
                    continue
                out += escapes.get(nxt, nxt.encode("utf-8"))
                self.i += 2
                continue
            out += c.encode("utf-8")
            self.i += 1
        return out.decode("utf-8", "replace")
