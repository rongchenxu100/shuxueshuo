"""Bounded mathematical notation parser. Produces inert syntax, never Python code."""

import re
import unicodedata


class NotationError(ValueError):
    pass


def node(kind, *args):
    return [kind, *args]


TOKEN = re.compile(
    r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z\u0370-\u03ff][A-Za-z0-9_\u0370-\u03ff]*)|(<=|>=|!=|\*\*|[+*/^=<>−\-(),{}\[\]:∈∩∧∨∀∃ℝ∠△°⟂∥]))"
)
PREC = {
    "∨": 5,
    "∧": 10,
    "=": 20,
    "!=": 20,
    "<": 20,
    "<=": 20,
    ">": 20,
    ">=": 20,
    "∈": 20,
    "⟂": 20,
    "∥": 20,
    "∩": 30,
    "+": 40,
    "-": 40,
    "*": 50,
    "/": 50,
    "^": 60,
}
RELATIONS = {"=", "!=", "<", "<=", ">", ">=", "∈", "⟂", "∥"}
BUILTINS = {
    "sqrt",
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
        "²": "^2",
        "³": "^3",
        "：": ":",
        "，": ",",
        "（": "(",
        "）": ")",
        "∥": "∥",
        "⊥": "⟂",
        "**": "^",
    }.items():
        text = text.replace(a, b)
    return unicodedata.normalize("NFC", text.strip())


class Parser:
    def __init__(self, text):
        if len(text) > 4096:
            raise NotationError("notation.length_limit")
        text = clean(text)
        self.tokens = []
        offset = 0
        while offset < len(text):
            match = TOKEN.match(text, offset)
            if not match:
                raise NotationError(
                    f"notation.unrecognized_token at {offset}: {text[offset : offset + 12]}"
                )
            self.tokens.append(next(v for v in match.groups() if v is not None))
            offset = match.end()
        if len(self.tokens) > 1024:
            raise NotationError("notation.token_limit")
        self.tokens.append("EOF")
        self.i = 0
        self.depth = 0
        self.count = 0

    def take(self, expected=None):
        value = self.tokens[self.i]
        if expected is not None and value != expected:
            raise NotationError(f"notation.expected {expected}, got {value}")
        if value == "EOF":
            raise NotationError("notation.unexpected_end")
        self.i += 1
        return value

    def peek(self):
        return self.tokens[self.i]

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
            raise NotationError(f"notation.trailing_token {self.peek()}")
        return value

    def expr(self, minimum=0):
        self.depth += 1
        if self.depth > 40:
            raise NotationError("notation.depth_limit")
        token = self.take()
        if token in ("+", "-"):
            left = self.make("neg", self.expr(60)) if token == "-" else self.expr(60)
        elif token in ("∀", "∃"):
            var = self.take()
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", var):
                raise NotationError("notation.quantifier_variable")
            self.take("∈")
            domain = self.expr(21)
            self.take(":")
            left = self.make("quantifier", token, var, domain, self.expr())
        elif token in ("∠", "△"):
            points = self.take()
            if not re.fullmatch("[A-Z]{3}", points):
                raise NotationError("notation.geometry_shorthand")
            left = self.make(
                "call",
                "angle" if token == "∠" else "triangle",
                *[node("name", p) for p in points],
            )
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
        elif token in ("min_", "max_"):
            self.take("{")
            variables = [self.take()]
            while self.peek() == ",":
                self.take()
                variables.append(self.take())
            self.take("}")
            self.take("(")
            argument = self.expr()
            self.take(")")
            left = self.make("extremum", token[:-1], variables, argument)
        elif re.fullmatch(r"\d+(\.\d+)?", token):
            if len(token) > 64:
                raise NotationError("notation.number_limit")
            left = self.make("number", token)
        elif token == "ℝ":
            left = self.make("real")
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
            raise NotationError(f"notation.unexpected_token {token}")
        if self.peek() == "°":
            self.take()
            left = self.make("degrees", left)
        while PREC.get(self.peek(), -1) >= minimum:
            op = self.take()
            right = self.expr(PREC[op] + (0 if op == "^" else 1))
            if op in RELATIONS and left[0] in RELATIONS:
                previous = left
                left = self.make("and", previous, self.make(op, previous[2], right))
            else:
                left = self.make({"∧": "and", "∨": "or"}.get(op, op), left, right)
        self.depth -= 1
        return left


def parse(text):
    return Parser(text).parse()


def definition(text):
    text = clean(text)
    curve = re.fullmatch(r"([A-Za-z\u0370-\u03ff][\w]*)\s*:\s*y\s*=\s*(.+)", text)
    if curve:
        return node("curve_definition", curve[1], parse(curve[2]))
    function = re.fullmatch(r"([A-Za-z][\w]*)\(([A-Za-z][\w]*)\)\s*=\s*(.+)", text)
    if function:
        if function[1] in BUILTINS:
            raise NotationError("notation.reserved_function_name")
        return node("function_definition", function[1], function[2], parse(function[3]))
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
                if text.startswith(("若", "定义", "称", "如果")) and "称" in text:
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
