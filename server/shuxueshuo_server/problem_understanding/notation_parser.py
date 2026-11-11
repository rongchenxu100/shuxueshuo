"""Bounded mathematical notation parser. Produces inert syntax, never Python code."""

import re
import unicodedata


class NotationError(ValueError):
    def __init__(self, code, message=None, *, path=None, source=None):
        if not isinstance(code, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", code
        ):
            raise ValueError("NotationError requires an explicit dotted error code")
        super().__init__(code if message is None else f"{code}: {message}")
        self.path, self.source = path, source
        self.code = code


def node(kind, *args):
    return [kind, *args]


TOKEN = re.compile(
    r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z\u0370-\u03ff][A-Za-z0-9_\u0370-\u03ff]*)|(<=|>=|!=|\*\*|[+*/^=<>−\-(),{}\[\]:|∈∉∩∪∖⊆⊊⊇⊋∅∧∨→∀∃ℝ∞∠△°⟂∥√]))"
)
SUBSET_RELATIONS = {"⊆", "⊊", "⊇", "⊋"}
PREC = {
    "→": 1,
    "∨": 5,
    "∧": 10,
    "=": 20,
    "!=": 20,
    "<": 20,
    "<=": 20,
    ">": 20,
    ">=": 20,
    "∈": 20,
    "∉": 20,
    "⊆": 20,
    "⊊": 20,
    "⊇": 20,
    "⊋": 20,
    "⟂": 20,
    "∥": 20,
    "∩": 30,
    "∪": 30,
    "∖": 30,
    "+": 40,
    "-": 40,
    "*": 50,
    "/": 50,
    "^": 60,
}
RELATIONS = {"=", "!=", "<", "<=", ">", ">=", "∈", "∉", "⟂", "∥", *SUBSET_RELATIONS}
BUILTINS = {
    "Dom",
    "parity",
    "defined_on",
    "degree",
    "sqrt",
    "abs",
    "piecewise",
    "sum",
    "mod",
    "tan",
    "length",
    "angle",
    "area",
    "segment",
    "line",
    "ray",
    "midpoint",
    "square",
    "parallelogram",
    "quadrilateral",
    "bisects",
    "cut_ratio",
    "x",
    "y",
    # Keep x/y here so x(P)/y(P) are recognized as coordinate calls. The
    # compiler separately permits bare x/y as scalar variables for algebraic
    # notation.
    "axis",
    "vertex",
    "min",
    "max",
    "fixed",
    "moving",
}


def clean(text):
    # Keep mathematical ℝ and superscripts explicit rather than NFKC-erasing them.
    for a, b in {
        "−": "-",
        "–": "-",
        "×": "*",
        "÷": "/",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        ":=": "=",
        "≔": "=",
        "≡": "=",
        "²": "^2",
        "³": "^3",
        "：": ":",
        "，": ",",
        "（": "(",
        "）": ")",
        "∥": "∥",
        "⊥": "⟂",
        "⫋": "⊊",
        "⫌": "⊋",
        "Ø": "∅",
        "**": "^",
        "⇒": "→",
    }.items():
        text = text.replace(a, b)
    # A distinct set operator avoids interpreting arithmetic subtraction as a
    # domain restriction. LaTeX remains rejected by the controlled parser.
    text = re.sub(r"\bsetminus\b", "∖", text)
    return unicodedata.normalize("NFC", text.strip())


class Parser:
    def __init__(self, text):
        if len(text) > 4096:
            raise NotationError("notation.length_limit")
        text = clean(text)
        # LaTeX belongs in original_text only; here it is a formatting slip,
        # not unsupported mathematics.
        if "$" in text or "\\" in text:
            raise NotationError(
                "notation.latex_markup", "数学候选不写 $ 或 LaTeX 命令，改用目录中的 Unicode 记法"
            )
        self.tokens = []
        offset = 0
        while offset < len(text):
            match = TOKEN.match(text, offset)
            if not match:
                raise NotationError(
                    "notation.unrecognized_token",
                    f"at {offset}: {text[offset : offset + 12]}",
                )
            self.tokens.append(next(v for v in match.groups() if v is not None))
            offset = match.end()
        if len(self.tokens) > 1024:
            raise NotationError("notation.token_limit")
        # Only an explicit numeric coefficient gets implicit multiplication.
        # Never split AB or xy: those may be point lengths or named parameters.
        expanded = []
        for token in self.tokens:
            if (
                expanded
                and re.fullmatch(r"\d+(?:\.\d+)?", expanded[-1])
                and (
                    re.fullmatch(r"[A-Za-z\u0370-\u03ff][\w]*", token)
                    or token in ("(", "∠", "√")
                )
            ):
                expanded.append("*")
            expanded.append(token)
        self.tokens = expanded + ["EOF"]
        self.i = 0
        self.depth = 0
        self.count = 0

    def take(self, expected=None):
        value = self.tokens[self.i]
        if expected is not None and value != expected:
            raise NotationError(
                "notation.expected", f"expected {expected}, got {value}"
            )
        if value == "EOF":
            raise NotationError("notation.unexpected_end")
        self.i += 1
        return value

    def peek(self):
        return self.tokens[self.i]

    def set_builder_ahead(self):
        """After "{": a separator "|" or ":" before the matching "}" at depth 0.

        A bar where an operand is expected opens an absolute value and the next
        bar after an operand closes it, so {1, |a|} stays a literal set."""
        depth = 0
        bars = 0
        operand = True
        for token in self.tokens[self.i :]:
            if token == "|":
                if operand:
                    bars += 1
                    continue
                if bars:
                    bars -= 1
                    continue
                if depth == 0:
                    break
                operand = True
            elif token in ("(", "[", "{"):
                depth += 1
                operand = True
            elif token in (")", "]", "}"):
                if depth == 0:
                    return False
                depth -= 1
                operand = False
            elif token == ":" and depth == 0 and not bars:
                break
            elif token in ("∀", "∃") or token == "EOF":
                return False
            else:
                operand = not (
                    token in ("∅", "ℝ", "∞", "°")
                    or re.fullmatch(r"\d+(?:\.\d+)?|[A-Za-z\u0370-\u03ff][\w]*", token)
                )
        else:
            return False
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.peek()) or self.tokens[self.i + 1] != "∈":
            raise NotationError("notation.set_builder", "写成 {变量∈定义域 | 条件}")
        return True

    def make(self, kind, *args):
        self.count += 1
        if self.count > 512:
            raise NotationError("notation.node_limit")
        return node(kind, *args)

    def parse(self):
        value = self.expr()
        if self.peek() == ",":
            values = [value]
            while self.peek() == ",":
                self.take()
                values.append(self.expr(21))
            self.take("∈")
            domain = self.expr(21)
            value = self.make("and", *[self.make("∈", item, domain) for item in values])
        if self.peek() != "EOF":
            raise NotationError("notation.trailing_token", self.peek())
        return value

    def expr(self, minimum=0):
        self.depth += 1
        if self.depth > 40:
            raise NotationError("notation.depth_limit")
        token = self.take()
        if token in ("+", "-"):
            operand = self.expr(60)
            if operand[0] == "infinity":
                left = self.make(
                    "infinity", -operand[1] if token == "-" else operand[1]
                )
            else:
                left = self.make("neg", operand) if token == "-" else operand
        elif token == "√":
            # √ takes a number or an explicitly delimited expression. In
            # √2*AB the radical covers 2, never the following product.
            if self.peek() != "(" and not re.fullmatch(r"\d+(?:\.\d+)?", self.peek()):
                raise NotationError("notation.radical_requires_number_or_group")
            left = self.make("call", "sqrt", self.expr(61))
        elif token == "|":
            # |x-1| is abs(x-1); "|" is not an operator, so the inner
            # expression stops at the closing bar.
            left = self.make("call", "abs", self.expr())
            self.take("|")
        elif token in ("∀", "∃"):
            variables = [self.take()]
            while self.peek() == ',':
                self.take()
                variables.append(self.take())
            if (any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", var) for var in variables)
                    or len(set(variables)) != len(variables)):
                raise NotationError("notation.quantifier_variable")
            self.take("∈")
            domain = self.expr(21)
            def captures(tree):
                return (tree[0] == 'name' and tree[1] in variables
                        or any(captures(child) for child in tree[1:] if isinstance(child, list)))
            if len(variables) > 1 and captures(domain):
                raise NotationError('notation.quantifier_domain_dependency')
            guard = None
            if self.peek() == ',':
                self.take()
                guard = self.expr()
            self.take(":")
            left = self.expr()
            if guard is not None:
                left = self.make('implies' if token == '∀' else 'and', guard, left)
            for var in reversed(variables):
                left = self.make("quantifier", token, var, domain, left)
        elif token in ("∠", "△"):
            points = self.take()
            if not re.fullmatch("[A-Z]{3}", points):
                raise NotationError("notation.geometry_shorthand")
            left = self.make(
                "call",
                "angle" if token == "∠" else "triangle",
                *[node("name", p) for p in points],
            )
        elif token == "{" and self.set_builder_ahead():
            # {x∈ℝ | condition} or {x∈[0,2]: condition}: x is bound to the braces.
            var = self.take()
            self.take("∈")
            domain = self.expr(21)
            self.take()
            body = self.expr()
            self.take("}")
            left = self.make("set_builder", var, domain, body)
        elif token in ("(", "[", "{"):
            closing = {"(": ")", "[": "]", "{": "}"}[token]
            values = [self.expr()]
            while self.peek() == ",":
                self.take()
                values.append(self.expr())
            end = self.take()
            if end != closing and not (token in ("(", "[") and end in (")", "]")):
                raise NotationError("notation.unbalanced_group")
            if token == "{":
                left = self.make("set", *values)
            elif token == "[" or end == "]":
                if len(values) != 2:
                    raise NotationError("notation.interval_arity")
                left = self.make("interval", token == "[", end == "]", *values)
            elif len(values) == 1:
                left = values[0]
            else:
                left = self.make("tuple", *values)
        elif re.fullmatch(r"(?:min|max)_(?:[A-Za-z][A-Za-z0-9]*)?", token):
            operation, hint = token.split("_", 1)
            if hint:
                variables = [hint]
            else:
                self.take("{")
                variables = [self.take()]
                while self.peek() == ",":
                    self.take()
                    variables.append(self.take())
                self.take("}")
            self.take("(")
            argument = self.expr()
            self.take(")")
            left = self.make("extremum", operation, variables, argument)
        elif re.fullmatch(r"\d+(\.\d+)?", token):
            if len(token) > 64:
                raise NotationError("notation.number_limit")
            left = self.make("number", token)
        elif token == "ℝ":
            left = self.make("real")
        elif token == "∅":
            left = self.make("empty_set")
        elif token == "∞":
            # An endpoint token, never a scalar constant. The binder checks
            # its context and the type checker checks endpoint openness.
            left = self.make("infinity", 1)
        elif re.fullmatch(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_\u0370-\u03ff]*", token):
            if self.peek() == "(":
                self.take()
                args = []
                if self.peek() != ")":
                    args.append(self.expr())
                    while self.peek() == ",":
                        self.take()
                        args.append(self.expr())
                self.take(")")
                left = (
                    self.make("extremum", token, [], *args)
                    if token in ("min", "max")
                    else self.make("call", token, *args)
                )
                if token in ("min", "max") and len(args) != 1:
                    raise NotationError("notation.extremum_arity")
            else:
                left = self.make("name", token)
        else:
            raise NotationError("notation.unexpected_token", token)
        if self.peek() == "°":
            self.take()
            left = self.make("degrees", left)
        while PREC.get(self.peek(), -1) >= minimum:
            op = self.take()
            right = self.expr(PREC[op] + (0 if op in ("^", "→") else 1))
            if op in RELATIONS and left[0] in RELATIONS:
                previous = left
                left = self.make("and", previous, self.make(op, previous[2], right))
            else:
                left = self.make({"∧": "and", "∨": "or", "→": "implies", "∖": "set_difference"}.get(op, op), left, right)
        self.depth -= 1
        return left


def parse(text):
    return Parser(text).parse()


def definition(text, known_functions=()):
    text = clean(text)
    curve = re.fullmatch(r"([A-Za-z\u0370-\u03ff][\w]*)\s*:\s*y\s*=\s*(.+)", text)
    if curve:
        return node("curve_definition", curve[1], parse(curve[2]))
    function = re.fullmatch(r"([A-Za-z][\w]*)\(([A-Za-z][\w]*)\)\s*=\s*(.+)", text)
    if function:
        # A call of an already defined function is a relation, not a second
        # declaration. This distinction must not depend on the JSON array.
        if function[1] in BUILTINS or function[1] in known_functions:
            return parse(text)
        return node("function_definition", function[1], function[2], parse(function[3]))
    # A relation defining f through a nontrivial input keeps that input intact.
    # Its single displayed variable binds both sides over the real numbers.
    relation = re.fullmatch(r"([A-Za-z][\w]*)\((.+)\)\s*=\s*(.+)", text)
    if relation and relation[1] not in BUILTINS and relation[1] not in known_functions:
        argument, body = parse(relation[2]), parse(relation[3])
        def names(ast):
            if ast[0] == 'name':
                return {ast[1]}
            return set().union(*(names(child) for child in ast[1:] if isinstance(child, list)))
        variables = names(argument) | names(body)
        if len(variables) == 1:
            return node('function_input_relation', relation[1], next(iter(variables)), argument, body)
    if re.search("[\u4e00-\u9fff]", text):
        roles = []
        for part in re.split("[；;。]", text):
            if not part:
                continue
            match = re.fullmatch(
                r"([A-Z][A-Za-z0-9]*(?:[、,][A-Z][A-Za-z0-9]*)*)(?:为|是)(定点|动点|平面内一点)",
                part.strip(),
            )
            if not match:
                # New concepts are audit prose, never executed as a hidden definition.
                prose = text.split(":", 1)[-1].strip()
                if prose.startswith(("若", "定义", "称", "如果")) and "称" in prose:
                    return node("definition_prose", text)
                raise NotationError("notation.unsupported_declaration")
            roles.extend(
                node(
                    "role",
                    p,
                    {"定点": "fixed", "动点": "moving", "平面内一点": "point"}[
                        match[2]
                    ],
                )
                for p in re.split("[、,]", match[1])
            )
        return node("and", *roles)
    return parse(text)
