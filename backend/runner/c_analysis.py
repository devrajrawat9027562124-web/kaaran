"""Static analysis for the Why Engine: what each line of C/C++ reads and writes.

The C/C++ counterpart of tracer/analysis.py. It returns the same fields for
every line, found with tree-sitter instead of Python's ast:

    reads    variables the line uses              total += a[i] -> total, a, i
    writes   variables the line (re)assigns        total += a[i] -> total
    mutates  memory the line changes, as simple    a[i] = 5      -> "a[i]"
             lvalues ("a[i]", "p->next", "*p",     scanf("%d", &x) -> "x"
             "x"); the tracer asks GDB for their
             address while the program runs
    method_mutates  the same for calls like v.push_back(3) (C++)
    globals  file-scope variables this line writes
    control  line of the if/for/while/switch that decides whether this
             line runs (None at the top level of a function)
    branch   True in an if-body, False in its else-body
    header   "if", "loop" or None
    returns  True for a return statement (what runs after it is cleanup)

analyze() also returns where each variable is declared (so the tracer can
hide variables whose declaration hasn't run yet) and the program's own
function names.
"""
import tree_sitter_c
import tree_sitter_cpp
from tree_sitter import Language, Parser

LANGUAGES = {
    "c": Language(tree_sitter_c.language()),
    "cpp": Language(tree_sitter_cpp.language()),
}

# C++ methods that change the object they are called on, e.g. v.push_back(3)
MUTATING_METHODS = {
    "push_back", "pop_back", "emplace_back", "push_front", "pop_front",
    "emplace_front", "insert", "emplace", "erase", "clear", "push", "pop",
    "resize", "assign", "swap", "append", "sort", "reverse", "fill",
}

# Library functions that write into an argument, and which arguments
# (scanf("%d", &x) is handled by the & rule; this catches arrays: gets(buf))
WRITING_FUNCTIONS = {
    "scanf": 1, "fscanf": 2, "sscanf": 2,
    "gets": 0, "fgets": 0, "fread": 0, "strcpy": 0, "strncpy": 0,
    "strcat": 0, "strncat": 0, "memset": 0, "memcpy": 0, "memmove": 0,
    "sprintf": 0, "snprintf": 0, "getline": 1,
}

INPUT_STREAMS = {"cin", "std::cin"}
# Names from <iostream> that look like variables after `using namespace std;`
STREAM_NAMES = {"cin", "cout", "cerr", "clog", "endl"}
JUMPS = {"return_statement", "break_statement", "continue_statement", "goto_statement"}
LOOPS = {"for_statement", "while_statement", "do_statement", "for_range_loop"}


def analyze(code, language="c"):
    """Return {"lines": {line: info}, "declared": {function: {name: [lines]}},
    "ends": {function: closing-brace line}, "functions": [names], "globals": [names]}."""
    source = code.encode("utf-8")
    tree = Parser(LANGUAGES[language]).parse(source)
    analyzer = _Analyzer(source)
    analyzer.visit_unit(tree.root_node)
    return {
        "lines": analyzer.lines,
        "declared": analyzer.declared,
        "ends": analyzer.ends,
        "functions": sorted(analyzer.functions),
        "globals": sorted(analyzer.global_names),
    }


def _line(node):
    return node.start_point[0] + 1


def _add(items, name):
    if name and name not in items:
        items.append(name)


class _Analyzer:
    def __init__(self, source):
        self.source = source
        self.lines = {}
        self.declared = {}          # function -> {variable: [declaration lines]}
        self.ends = {}              # function -> line of its closing brace
        self.functions = set()
        self.global_names = set()
        self.func = None            # function being analysed
        self.in_method = False      # a C++ method: other names are members (this->x)
        self.locals = set()

    def text(self, node):
        return self.source[node.start_byte:node.end_byte].decode("utf-8")

    def entry(self, line):
        if line not in self.lines:
            self.lines[line] = {"reads": [], "writes": [], "mutates": [], "method_mutates": [],
                                "globals": [], "control": None, "branch": None, "header": None,
                                "returns": False, "_set": False}
        return self.lines[line]

    # ---------- Program structure ----------

    def visit_unit(self, root):
        functions = list(self._functions(root, in_class=False))
        # Names first, so calls to them can be told apart from library calls
        for node, _ in functions:
            name = self._function_name(node)
            if name:
                self.functions.update({name, name.split("::")[-1]})
        for node in root.children:
            if node.type == "declaration":
                self.global_names.update(self._declared_names(node))
        for node, in_class in functions:
            self.visit_function(node, in_class)
        for info in self.lines.values():
            del info["_set"]

    def _functions(self, node, in_class):
        """Every function definition, and whether it is a method of a class."""
        for child in node.named_children:
            if child.type == "function_definition":
                name = self._function_name(child) or ""
                yield child, in_class or "::" in name
            elif child.type in ("class_specifier", "struct_specifier", "field_declaration_list"):
                yield from self._functions(child, in_class=True)
            elif child.type in ("namespace_definition", "declaration_list", "template_declaration"):
                yield from self._functions(child, in_class)

    def _function_name(self, node):
        declarator = node.child_by_field_name("declarator")
        while declarator is not None and declarator.type != "function_declarator":
            declarator = declarator.child_by_field_name("declarator")
        if declarator is None:
            return None
        name = declarator.child_by_field_name("declarator")
        return self.text(name) if name is not None else None

    def visit_function(self, node, in_class=False):
        self.func = self._function_name(node)
        self.in_method = in_class
        # The closing brace: the tracer finishes the function from there,
        # which is how GDB reports the value it returns
        for name in {self.func, self.func.split("::")[-1]}:
            self.ends[name] = node.end_point[0] + 1
        self.locals = set()
        declared = self.declared.setdefault(self.func, {})
        declarator = node.child_by_field_name("declarator")
        while declarator is not None and declarator.type != "function_declarator":
            declarator = declarator.child_by_field_name("declarator")
        params = declarator.child_by_field_name("parameters") if declarator is not None else None
        for param in (params.named_children if params is not None else []):
            name = self._innermost_name(param.child_by_field_name("declarator"))
            if name:
                self.locals.add(name)
                declared.setdefault(name, []).append(_line(node))
        # Locals are known before the body is walked, so `globals` is right
        body = node.child_by_field_name("body")
        for decl in self._descendants(body, "declaration"):
            self.locals.update(self._declared_names(decl))
        self.visit_block(body, control=None, branch=None)
        self.func = None

    def _descendants(self, node, kind):
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type == kind:
                yield current
            stack.extend(current.named_children)

    # ---------- Statements ----------

    def visit_block(self, node, control, branch):
        statements = node.named_children if node.type == "compound_statement" else [node]
        for stmt in statements:
            self.visit_statement(stmt, control, branch)
            if stmt.type == "if_statement" and stmt.child_by_field_name("alternative") is None \
                    and self._always_jumps(stmt.child_by_field_name("consequence")):
                # A guard clause (`if (n <= 1) return 1;`): what follows only
                # runs when the condition was false
                control, branch = _line(stmt), False

    def _always_jumps(self, node):
        if node is None:
            return False
        if node.type == "compound_statement":
            children = node.named_children
            return bool(children) and children[-1].type in JUMPS
        return node.type in JUMPS

    def _start(self, node, control, branch):
        entry = self.entry(_line(node))
        if not entry["_set"]:  # with `if (x) y = 1;` on one line, the first statement decides
            entry["control"], entry["branch"], entry["_set"] = control, branch, True
        return entry

    def visit_statement(self, node, control, branch):
        kind = node.type
        if kind == "compound_statement":
            self.visit_block(node, control, branch)
            return
        if kind in ("comment", "preproc_include", "preproc_def", "break_statement",
                    "continue_statement", "goto_statement", "type_definition"):
            return
        if kind == "labeled_statement":
            for child in node.named_children[1:]:
                self.visit_statement(child, control, branch)
            return

        entry = self._start(node, control, branch)
        line = _line(node)

        if kind == "if_statement":
            entry["header"] = "if"
            self.collect(node.child_by_field_name("condition"), entry)
            self.visit_block(node.child_by_field_name("consequence"), line, True)
            alternative = node.child_by_field_name("alternative")
            if alternative is not None:
                for child in alternative.named_children:
                    self.visit_statement(child, line, False)

        elif kind == "switch_statement":
            entry["header"] = "if"
            self.collect(node.child_by_field_name("condition"), entry)
            for case in node.child_by_field_name("body").named_children:
                value = case.child_by_field_name("value")
                for child in case.named_children:
                    if child != value:
                        self.visit_statement(child, line, None)

        elif kind == "for_statement":
            entry["header"] = "loop"
            for field in ("initializer", "condition", "update"):
                part = node.child_by_field_name(field)
                if part is None:
                    continue
                if part.type == "declaration":
                    self.visit_declaration(part, entry)
                else:
                    self.collect(part, entry)
            self.visit_block(node.child_by_field_name("body"), line, None)

        elif kind == "for_range_loop":
            entry["header"] = "loop"
            name = self._innermost_name(node.child_by_field_name("declarator"))
            if name:
                self._write(name, entry)
                self._declare(name, line)
            self.collect(node.child_by_field_name("right"), entry)
            self.visit_block(node.child_by_field_name("body"), line, None)

        elif kind == "while_statement":
            entry["header"] = "loop"
            self.collect(node.child_by_field_name("condition"), entry)
            self.visit_block(node.child_by_field_name("body"), line, None)

        elif kind == "do_statement":
            # GDB stops on the `while (...)` line, so that is the header
            condition = node.child_by_field_name("condition")
            header = self._start(condition, control, branch)
            header["header"] = "loop"
            self.collect(condition, header)
            self.visit_block(node.child_by_field_name("body"), _line(condition), None)

        elif kind == "declaration":
            self.visit_declaration(node, entry)

        else:  # expression_statement, return_statement, ...
            if kind == "return_statement":
                entry["returns"] = True
            for child in node.named_children:
                self.collect(child, entry)

    def visit_declaration(self, node, entry):
        cpp_object = node.child_by_field_name("type") is not None and \
            node.child_by_field_name("type").type in ("qualified_identifier", "template_type", "type_identifier")
        for declarator in node.children_by_field_name("declarator"):
            name = self._innermost_name(declarator)
            if not name:
                continue
            self._declare(name, _line(node))
            if declarator.type == "init_declarator":
                self._write(name, entry)
                self.collect(declarator.child_by_field_name("value"), entry)
            elif cpp_object and self.func is not None:
                self._write(name, entry)  # std::vector<int> v; constructs an empty vector

    def _declare(self, name, line):
        if self.func is not None:
            self.declared.setdefault(self.func, {}).setdefault(name, []).append(line)

    def _declared_names(self, node):
        return [n for n in (self._innermost_name(d) for d in node.children_by_field_name("declarator")) if n]

    def _innermost_name(self, node):
        """`a` from `a`, `a[3]`, `*p`, `&r`, `x = 5`."""
        while node is not None:
            if node.type in ("identifier", "field_identifier"):
                return self.text(node)
            inner = node.child_by_field_name("declarator")
            if inner is None:
                named = [c for c in node.named_children if c.type in (
                    "identifier", "pointer_declarator", "array_declarator", "reference_declarator",
                    "init_declarator", "parenthesized_declarator")]
                inner = named[0] if named else None
            node = inner
        return None

    # ---------- Expressions ----------

    def _is_member(self, name):
        return self.in_method and name not in self.locals and name not in self.global_names \
            and name not in self.functions

    def _read(self, name, entry):
        # Inside a method, `value` means this->value: it reads the object
        _add(entry["reads"], "this" if self._is_member(name) else name)

    def _write(self, name, entry):
        if self._is_member(name):
            _add(entry["mutates"], f"this->{name}")
            _add(entry["reads"], "this")
            return
        _add(entry["writes"], name)
        if self.func is not None and name in self.global_names and name not in self.locals:
            _add(entry["globals"], name)

    def _target(self, node, entry, also_read=False):
        """The left side of `=`, `+=`, `++`: a variable or a piece of memory."""
        node = self._unwrap(node)
        if node.type == "identifier":
            name = self.text(node)
            if also_read:
                self._read(name, entry)
            self._write(name, entry)
        else:
            _add(entry["mutates"], self._path(node))
            self.collect(node, entry)

    def _unwrap(self, node):
        while node is not None and node.type == "parenthesized_expression" and node.named_children:
            node = node.named_children[0]
        return node

    def _path(self, node):
        """Text of a side-effect-free lvalue (a[i], p->next, *p, s.x), safe
        for GDB to evaluate; otherwise the variable it starts from."""
        if self._is_simple(node):
            return self.text(node)
        base = node
        while base is not None and base.type != "identifier":
            base = base.child_by_field_name("argument") or (base.named_children[0] if base.named_children else None)
        return self.text(base) if base is not None else None

    def _is_simple(self, node):
        node = self._unwrap(node)
        if node.type in ("identifier", "number_literal"):
            return True
        if node.type == "subscript_expression":
            # C calls it `index`; C++ has `indices` (a list, usually of one)
            index = node.child_by_field_name("index") or node.child_by_field_name("indices")
            if index is None:
                return False
            parts = index.named_children if index.type == "subscript_argument_list" else [index]
            return self._is_simple(node.child_by_field_name("argument")) and all(map(self._is_simple, parts))
        if node.type == "field_expression":
            return self._is_simple(node.child_by_field_name("argument"))
        if node.type == "pointer_expression":
            return self._is_simple(node.child_by_field_name("argument"))
        return False

    def collect(self, node, entry):
        if node is None:
            return
        kind = node.type
        if kind == "identifier":
            if self.text(node) not in STREAM_NAMES:
                self._read(self.text(node), entry)
        elif kind == "pointer_expression" and node.child_by_field_name("operator").type == "&" \
                and self._unwrap(node.child_by_field_name("argument")).type == "identifier":
            return  # &x is x's address, not its value
        elif kind == "assignment_expression":
            compound = node.child_by_field_name("operator").type != "="
            self._target(node.child_by_field_name("left"), entry, also_read=compound)
            self.collect(node.child_by_field_name("right"), entry)
        elif kind == "update_expression":
            self._target(node.child_by_field_name("argument"), entry, also_read=True)
        elif kind == "call_expression":
            self.visit_call(node, entry)
        elif kind == "binary_expression" and self._is_input(node):
            self.visit_input(node, entry)
        elif kind in ("qualified_identifier", "field_identifier", "type_identifier",
                      "namespace_identifier", "string_literal", "char_literal",
                      "number_literal", "true", "false", "null", "sizeof_expression"):
            return
        else:
            for child in node.named_children:
                self.collect(child, entry)

    def visit_call(self, node, entry):
        func = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        name = None
        if func.type == "identifier":
            name = self.text(func)
        elif func.type == "qualified_identifier":
            name = self.text(func).split("::")[-1]
        elif func.type == "field_expression":
            obj = func.child_by_field_name("argument")
            method = self.text(func.child_by_field_name("field"))
            if method in MUTATING_METHODS:
                _add(entry["method_mutates"], self._path(obj))
            self.collect(obj, entry)
        else:
            self.collect(func, entry)

        # A function of the program itself changes memory through its own
        # parameters, which the trace records from inside it. A library
        # function can't be traced, so what it writes is decided here.
        library = name is not None and name not in self.functions
        written_from = WRITING_FUNCTIONS.get(name) if library else None
        reads_many = name in ("scanf", "fscanf", "sscanf")
        for i, arg in enumerate(args.named_children if args is not None else []):
            arg = self._unwrap(arg)
            address_of = arg.type == "pointer_expression" and arg.child_by_field_name("operator").type == "&"
            if library and address_of:  # scanf("%d", &x) writes x
                target = self._unwrap(arg.child_by_field_name("argument"))
                _add(entry["mutates"], self._path(target))
                if target.type == "identifier":
                    self._write(self.text(target), entry)
                else:
                    self.collect(target, entry)  # &a[i] reads i
            elif written_from is not None and i >= written_from and arg.type == "identifier":
                _add(entry["mutates"], self.text(arg))  # gets(buf), strcpy(dst, src)
                _add(entry["reads"], self.text(arg))
                if not reads_many:
                    written_from = None  # only the destination, not the source
            else:
                self.collect(arg, entry)

    def _is_input(self, node):
        """cin >> a >> b"""
        while node.type == "binary_expression":
            if self.text(node.child_by_field_name("operator")) != ">>":
                return False
            node = node.child_by_field_name("left")
        return self.text(node) in INPUT_STREAMS

    def visit_input(self, node, entry):
        while node.type == "binary_expression":
            self._target(node.child_by_field_name("right"), entry)
            node = node.child_by_field_name("left")
