"""Static analysis for the Why Engine: what each line of Python reads and writes.

analyze(code) walks the AST once, before the program runs, and returns for
every line number:

    reads    names the line uses                  total += i  -> total, i
    writes   names the line (re)binds              total += i  -> total
    mutates  objects the line changes in place     a[0] = 1    -> "a"
             (as expressions like "a" or "self.items"; the tracer turns
             them into real objects while the program runs)
    method_mutates  the same, for calls like a.append(3); only trusted
             for built-in containers, since a student's own method with
             the same name is traced from the inside anyway
    globals  names declared `global` in the enclosing function
    control  line of the if/for/while/except that decides whether this
             line runs (None at the top level of a function or module)
    branch   True if the line is in an if-body, False if in its else-body
    header   "if" for an if/elif line, "loop" for for/while, "except" for
             an except line, "switch" for match, else None

This is the only Python-specific part of the Why Engine. The C/C++ adapter
fills the same fields using tree-sitter.
"""
import ast

# Methods that change the object they are called on, e.g. a.append(3)
MUTATING_METHODS = {
    "append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse",
    "update", "setdefault", "popitem",
    "add", "discard", "difference_update", "intersection_update",
    "symmetric_difference_update",
    "appendleft", "extendleft", "popleft", "rotate",
}

# Functions that change their first argument, e.g. random.shuffle(cards)
MUTATING_FUNCTIONS = {
    "shuffle", "heappush", "heappop", "heapify", "heapreplace", "heappushpop",
    "insort", "insort_left", "insort_right",
}


def analyze(code):
    """Return {line: info} for every line that holds a statement."""
    info = {}
    _visit_body(ast.parse(code).body, info, control=None, branch=None, globals_=set())
    return info


def _entry(info, line):
    if line not in info:
        info[line] = {"reads": [], "writes": [], "mutates": [], "method_mutates": [], "globals": [],
                      "control": None, "branch": None, "header": None}
    return info[line]


def _add(items, name):
    if name not in items:
        items.append(name)


def _merge(entry, names):
    for key in ("reads", "writes", "mutates", "method_mutates"):
        for name in getattr(names, key):
            _add(entry[key], name)


def _visit_body(stmts, info, control, branch, globals_):
    for stmt in stmts:
        _visit_stmt(stmt, info, control, branch, globals_)
        if isinstance(stmt, ast.If) and not stmt.orelse and _always_jumps(stmt.body):
            # A guard clause (`if n <= 1: return 1`): the lines after it
            # only run when its condition was False
            control, branch = stmt.lineno, False


def _always_jumps(body):
    return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))


def _visit_stmt(stmt, info, control, branch, globals_):
    new = stmt.lineno not in info
    entry = _entry(info, stmt.lineno)
    if new:  # with `if x: y = 1` on one line, the first statement decides
        entry["control"] = control
        entry["branch"] = branch
    if globals_:
        entry["globals"] = sorted(globals_)

    names = _Names()
    line = stmt.lineno

    if isinstance(stmt, ast.If):
        entry["header"] = "if"
        names.visit(stmt.test)
        _visit_body(stmt.body, info, line, True, globals_)
        _visit_body(stmt.orelse, info, line, False, globals_)

    elif isinstance(stmt, (ast.For, ast.AsyncFor)):
        entry["header"] = "loop"
        names.visit(stmt.target)
        names.visit(stmt.iter)
        _visit_body(stmt.body, info, line, None, globals_)
        _visit_body(stmt.orelse, info, line, None, globals_)

    elif isinstance(stmt, ast.While):
        entry["header"] = "loop"
        names.visit(stmt.test)
        _visit_body(stmt.body, info, line, None, globals_)
        _visit_body(stmt.orelse, info, line, None, globals_)

    elif isinstance(stmt, (ast.Try, getattr(ast, "TryStar", ast.Try))):
        # The try body runs unconditionally, so it keeps the outer control
        _visit_body(stmt.body, info, control, branch, globals_)
        for handler in stmt.handlers:
            h = _entry(info, handler.lineno)
            h["control"] = control
            h["header"] = "except"
            handler_names = _Names()
            if handler.type is not None:
                handler_names.visit(handler.type)
            if handler.name:
                _add(handler_names.writes, handler.name)
            _merge(h, handler_names)
            _visit_body(handler.body, info, handler.lineno, None, globals_)
        _visit_body(stmt.orelse, info, control, branch, globals_)
        _visit_body(stmt.finalbody, info, control, branch, globals_)

    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        for item in stmt.items:
            names.visit(item.context_expr)
            if item.optional_vars is not None:
                names.visit(item.optional_vars)
        _visit_body(stmt.body, info, control, branch, globals_)

    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _add(names.writes, stmt.name)
        for decorator in stmt.decorator_list:
            names.visit(decorator)
        for default in stmt.args.defaults + [d for d in stmt.args.kw_defaults if d]:
            names.visit(default)
        _visit_body(stmt.body, info, None, None, _declared_globals(stmt.body))

    elif isinstance(stmt, ast.ClassDef):
        _add(names.writes, stmt.name)
        for expr in stmt.bases + stmt.decorator_list:
            names.visit(expr)
        _visit_body(stmt.body, info, None, None, set())

    elif isinstance(stmt, ast.Match):
        entry["header"] = "switch"
        names.visit(stmt.subject)
        for case in stmt.cases:
            names.visit(case.pattern)
            if case.guard is not None:
                names.visit(case.guard)
            _visit_body(case.body, info, line, None, globals_)

    else:  # a simple statement: everything in it belongs to this line
        names.visit(stmt)

    _merge(entry, names)


def _declared_globals(body):
    """Names declared `global` in a function body (nested defs included,
    which is rare enough in beginner code to ignore)."""
    return {name for node in body for sub in ast.walk(node)
            if isinstance(sub, ast.Global) for name in sub.names}


def _object_path(expr):
    """Text for the object an expression refers to, if it is simple enough
    to look up safely while the program runs: a, self.items, grid[0], d["k"].
    Otherwise fall back to the variable it starts from."""
    if _is_simple_path(expr):
        return ast.unparse(expr)
    while isinstance(expr, (ast.Attribute, ast.Subscript, ast.Call)):
        expr = expr.func if isinstance(expr, ast.Call) else expr.value
    return expr.id if isinstance(expr, ast.Name) else None


def _is_simple_path(expr):
    if isinstance(expr, ast.Name):
        return True
    if isinstance(expr, ast.Attribute):
        return _is_simple_path(expr.value)
    if isinstance(expr, ast.Subscript):
        key = expr.slice
        simple_key = (isinstance(key, (ast.Constant, ast.Name))
                      or (isinstance(key, ast.UnaryOp) and isinstance(key.op, ast.USub)
                          and isinstance(key.operand, ast.Constant)))
        return simple_key and _is_simple_path(expr.value)
    return False


def _store_names(target):
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


class _Names(ast.NodeVisitor):
    """Collect reads, writes and mutations inside one statement."""

    def __init__(self):
        self.reads, self.writes, self.mutates, self.method_mutates = [], [], [], []
        self._bound = []  # names local to a comprehension or lambda on this line

    def _is_bound(self, name):
        return any(name in names for names in self._bound)

    def visit_Name(self, node):
        if self._is_bound(node.id):
            return
        if isinstance(node.ctx, ast.Load):
            _add(self.reads, node.id)
        else:  # Store or Del
            _add(self.writes, node.id)

    def _target(self, target):
        """An assignment target. a[i] = v and a.x = v change the object a."""
        if isinstance(target, (ast.Subscript, ast.Attribute)):
            path = _object_path(target.value)
            if path:
                _add(self.mutates, path)
        self.visit(target)

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets:
            self._target(target)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
            self._target(node.target)

    def visit_AugAssign(self, node):
        self.visit(node.value)
        target = node.target
        if isinstance(target, ast.Name):
            # total += i reads and writes total; for a list, a += [1]
            # also changes the list in place
            _add(self.reads, target.id)
            _add(self.writes, target.id)
            _add(self.mutates, target.id)
        else:
            self._target(target)

    def visit_Delete(self, node):
        for target in node.targets:
            self._target(target)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in MUTATING_METHODS:
            path = _object_path(func.value)
            if path:
                _add(self.method_mutates, path)
        else:
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in MUTATING_FUNCTIONS and node.args:
                path = _object_path(node.args[0])
                if path:
                    _add(self.mutates, path)
        self.generic_visit(node)

    def visit_Lambda(self, node):
        args = node.args
        for default in args.defaults + [d for d in args.kw_defaults if d]:
            self.visit(default)
        params = args.posonlyargs + args.args + args.kwonlyargs
        params += [a for a in (args.vararg, args.kwarg) if a]
        self._bound.append({a.arg for a in params})
        self.visit(node.body)
        self._bound.pop()

    def _comprehension(self, node, parts):
        # The first iterable runs in the enclosing scope; the loop
        # variables only exist inside the comprehension.
        self.visit(node.generators[0].iter)
        self._bound.append(set().union(*(_store_names(g.target) for g in node.generators)))
        for i, gen in enumerate(node.generators):
            if i:
                self.visit(gen.iter)
            for cond in gen.ifs:
                self.visit(cond)
        for part in parts:
            self.visit(part)
        self._bound.pop()

    def visit_ListComp(self, node):
        self._comprehension(node, [node.elt])

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node):
        self._comprehension(node, [node.key, node.value])

    def visit_MatchAs(self, node):
        if node.name:
            _add(self.writes, node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name:
            _add(self.writes, node.name)
